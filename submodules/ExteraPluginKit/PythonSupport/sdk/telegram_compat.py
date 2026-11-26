# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Native shims for the Android app classes plugins touch most often.  They are
# registered in `compat`, so `from org.telegram.messenger import UserConfig`
# returns these objects instead of an opaque `ClassRef`.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import json
import math
import os
import random as _random
import threading as _threading
import time

import media_metadata
import message_fields
from java_crypto import (
    Cipher as JavaCipher,
    DexClassLoader as JavaDexClassLoader,
    IvParameterSpec as JavaIvParameterSpec,
    KeyFactory as JavaKeyFactory,
    MessageDigest as JavaMessageDigest,
    SecretKeySpec as JavaSecretKeySpec,
    Signature as JavaSignature,
    X509EncodedKeySpec as JavaX509EncodedKeySpec,
)
from android_sqlite import (
    Cursor as AndroidCursor,
    SQLiteDatabase as AndroidSQLiteDatabase,
    SQLiteOpenHelper as AndroidSQLiteOpenHelper,
    SQLiteStatement as AndroidSQLiteStatement,
)
from java_time import (
    DateTimeFormatter as JavaDateTimeFormatter,
    Duration as JavaDuration,
    Instant as JavaInstant,
    LocalDate as JavaLocalDate,
    LocalDateTime as JavaLocalDateTime,
    LocalTime as JavaLocalTime,
    ZoneId as JavaZoneId,
    ZoneOffset as JavaZoneOffset,
)


def _current_account():
    try:
        import extera_ios

        return int(extera_ios.current_account())
    except Exception:
        return 0


def _path_for(kind):
    try:
        import extera_ios

        value = extera_ios.host("paths.dir", kind=kind)
        if isinstance(value, str) and value:
            return value
    except Exception:
        pass
    return os.path.expanduser("~")


def _java_class_ref(name):
    """A `java.lang.Class` handle, like `Activity.class` on Android."""
    try:
        from extera_utils.classes import ClassRef

        return ClassRef(name)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# UserConfig


_MESSAGE_ID_LOCK = _threading.RLock()
_NEXT_MESSAGE_ID = {}


class _UserConfigMeta(type):
    @property
    def selectedAccount(cls):
        return _current_account()

    @property
    def selectedAccountId(cls):
        return _current_account()

    @property
    def isPremium(cls):
        try:
            import extera_ios

            return bool((extera_ios.get_me(_current_account()) or {}).get("premium", False))
        except Exception:
            return False

    @property
    def isTestDevice(cls):
        return False


class _UserConfigInstance:
    def __init__(self, account):
        self.account = int(account)
        self.registeredForPush = False
        self.contactsSavedCount = 0
        self.clientUserId = int(account)
        self.lastContactsSyncTime = 0
        self.lastHintsSyncTime = 0
        self.draftsLoaded = False
        self.tmpPassword = None
        self.ratingLoadTime = 0
        self.botRatingLoadTime = 0
        self.botGuestRatingLoadTime = 0
        self.webappRatingLoadTime = 0
        self.contactsReimported = False
        self.hasValidDialogLoadIds = True
        self.filtersLoaded = False
        self.sharingMyLocationUntil = 0
        self.lastMyLocationShareTime = 0
        self.notificationsSettingsLoaded = True
        self.notificationsSignUpSettingsLoaded = True
        self.showCallsTab = True
        self.hasSecureData = False
        self.loginTime = 0
        self.unacceptedTermsOfService = None
        self.autoDownloadConfigLoadTime = 0
        self.premiumGiftsStickerPack = None
        self.premiumTonStickerPack = None
        self.genericAnimationsStickerPack = None
        self.defaultTopicIcons = None
        self.lastUpdatedPremiumGiftsStickerPack = 0
        self.lastUpdatedTonGiftsStickerPack = 0
        self.lastUpdatedGenericAnimations = 0
        self.lastUpdatedDefaultTopicIcons = 0
        self.savedPasswordHash = None
        self.savedSaltedPassword = None
        self.savedPasswordTime = 0

    def getCurrentAccount(self):
        return self.account

    def getClientUserId(self):
        user = self.getClientUser()
        identifier = user.get("id") if isinstance(user, dict) else None
        return int(identifier) if identifier is not None else self.account

    def isClientActivated(self):
        return True

    def getClientUser(self):
        try:
            import extera_ios

            return extera_ios.get_me(self.account)
        except Exception:
            return {}

    def getCurrentUser(self):
        return self.getClientUser()

    def getCurrentUserFull(self):
        try:
            import extera_ios

            user = extera_ios.get_me(self.account) or {}
            user_id = user.get("id")
            if user_id is None:
                return {}
            return extera_ios.send_request(
                self.account, "users.getFullUser", {"id": int(user_id)}
            )
        except Exception:
            return {}

    def isPremium(self):
        try:
            import extera_ios

            return bool((extera_ios.get_me(self.account) or {}).get("premium", False))
        except Exception:
            return False

    def getClientPhone(self):
        user = self.getClientUser()
        return str(user.get("phone") or "") if isinstance(user, dict) else ""

    def setCurrentUser(self, user=None, *args, **kwargs):
        return None

    def isConfigLoaded(self):
        return True

    def getNewMessageId(self):
        with _MESSAGE_ID_LOCK:
            value = _NEXT_MESSAGE_ID.get(self.account, 0) + 1
            _NEXT_MESSAGE_ID[self.account] = value
            return value

    def saveConfig(self, *args, **kwargs):
        return None

    def savePassword(self, password_hash=None, salted=None, *args, **kwargs):
        self.savedPasswordHash = password_hash
        self.savedSaltedPassword = salted
        self.savedPasswordTime = int(time.time() * 1000)
        return None

    def checkSavedPassword(self):
        return None

    def resetSavedPassword(self):
        self.savedPasswordHash = None
        self.savedSaltedPassword = None
        self.savedPasswordTime = 0
        return None

    def getPreferences(self):
        return SharedPreferences("userconfig_%s" % self.account)

    def getSaveGalleryExceptions(self, *args, **kwargs):
        return {}

    def updateSaveGalleryExceptions(self, *args, **kwargs):
        return None

    def clearConfig(self):
        self.registeredForPush = False
        self.contactsReimported = False
        self.filtersLoaded = False
        return None

    def isPinnedDialogsLoaded(self, folder_id=0):
        return bool(
            self.getPreferences().getBoolean(
                "pinned_%s" % int(folder_id or 0), False
            )
        )

    def setPinnedDialogsLoaded(self, folder_id, loaded):
        self.getPreferences().edit().putBoolean(
            "pinned_%s" % int(folder_id or 0), bool(loaded)
        ).apply()
        return None

    def clearPinnedDialogsLoaded(self):
        self.getPreferences().edit().clear().apply()
        return None

    def getTotalDialogsCount(self, folder_id=0):
        try:
            from org.telegram.messenger import MessagesStorage

            return len(MessagesStorage.getInstance(self.account).getDialogs(folder_id))
        except Exception:
            return 0

    def setShowCallsTab(self, value, *args, **kwargs):
        self.showCallsTab = bool(value)
        self.getPreferences().edit().putBoolean(
            "show_calls_tab", self.showCallsTab
        ).apply()
        return None

    def setShowContactsTab(self, value, *args, **kwargs):
        self.getPreferences().edit().putBoolean(
            "show_contacts_tab", bool(value)
        ).apply()
        return None

    def getGlobalTTl(self, *args, **kwargs):
        return int(self.getPreferences().getInt("global_ttl", 0))

    def setGlobalTtl(self, value, *args, **kwargs):
        self.getPreferences().edit().putInt(
            "global_ttl", int(value or 0)
        ).apply()
        return None

    def clearFilters(self, *args, **kwargs):
        editor = self.getPreferences().edit()
        for key in [
            key for key in self.getPreferences().getAll() if key.startswith("filter_")
        ]:
            editor.remove(key)
        editor.apply()
        return None

    def getDialogLoadOffsets(self, folder_id=0, *args, **kwargs):
        raw = self.getPreferences().getString(
            "dialog_offsets_%s" % int(folder_id or 0), ""
        )
        if raw:
            try:
                value = json.loads(raw)
            except Exception:
                value = None
            if isinstance(value, (list, dict)):
                return value
        return []

    def setDialogsLoadOffset(self, folder_id=0, *args, **kwargs):
        self.getPreferences().edit().putString(
            "dialog_offsets_%s" % int(folder_id or 0),
            json.dumps(list(args)),
        ).apply()
        return None

    def getLoggedInAccountIds(self, *args, **kwargs):
        try:
            import extera_ios

            accounts = extera_ios.accounts()
            if isinstance(accounts, list) and accounts:
                return [int(value) for value in accounts]
        except Exception:
            pass
        return [self.account]

    def getProductionAccount(self, *args, **kwargs):
        return self.account

    def getEmojiStatus(self, *args, **kwargs):
        user = self.getClientUser()
        if isinstance(user, dict):
            return user.get("emoji_status")
        return None


class UserConfig(metaclass=_UserConfigMeta):
    MAX_ACCOUNT_COUNT = 4

    @classmethod
    def getSelectedAccount(cls):
        return _current_account()

    @classmethod
    def getSelectedAccountId(cls):
        return _current_account()

    @classmethod
    def getInstance(cls, account=0):
        return _UserConfigInstance(account)

    @classmethod
    def getClientUserId(cls):
        return _current_account()

    @classmethod
    def isClientActivated(cls):
        return True

    @classmethod
    def getCurrentAccount(cls):
        return _current_account()

    @classmethod
    def getCurrentUser(cls):
        return cls.getInstance(_current_account()).getCurrentUser()

    @classmethod
    def getCurrentUserFull(cls):
        return cls.getInstance(_current_account()).getCurrentUserFull()

    @classmethod
    def getActivatedAccountsCount(cls):
        try:
            import extera_ios

            accounts = extera_ios.accounts()
            return len(accounts) if isinstance(accounts, list) else 1
        except Exception:
            return 1

    @classmethod
    def hasPremiumOnAccounts(cls):
        try:
            import extera_ios

            for account in extera_ios.accounts() or []:
                if (extera_ios.get_me(account) or {}).get("premium"):
                    return True
        except Exception:
            pass
        return False

    @classmethod
    def getMaxAccountCount(cls):
        return 4

    @classmethod
    def isValidAccount(cls, num):
        try:
            return 0 <= int(num) < cls.getMaxAccountCount()
        except Exception:
            return False


# ---------------------------------------------------------------------------
# MessagesController / AccountInstance


class _UpdateConstantsMeta(type):
    def __getattr__(cls, name):
        if name.startswith("update") or name.endswith("Update") or name.isupper():
            return name
        raise AttributeError(name)


_OVERLAY_LOCK = _threading.RLock()
_USER_OVERLAY = {}
_CHAT_OVERLAY = {}


def _overlay_for(account):
    with _OVERLAY_LOCK:
        return (
            _USER_OVERLAY.setdefault(int(account), {}),
            _CHAT_OVERLAY.setdefault(int(account), {}),
        )


def _put_users(account, users):
    users_map, _ = _overlay_for(account)
    for user in users or []:
        if isinstance(user, dict):
            identifier = user.get("id") or user.get("user_id")
        else:
            identifier = getattr(user, "id", None)
        if identifier is not None:
            users_map[int(identifier)] = user


def _put_chats(account, chats):
    _, chats_map = _overlay_for(account)
    for chat in chats or []:
        if isinstance(chat, dict):
            identifier = chat.get("id") or chat.get("chat_id") or chat.get("channel_id")
        else:
            identifier = getattr(chat, "id", None)
        if identifier is not None:
            chats_map[int(identifier)] = chat


class _TopicsControllerInstance:
    """`org.telegram.messenger.TopicsController` facade.

    Forum topics need a separate topic store on iOS; the controller keeps the
    Android method surface so plugin code that asks for it does not crash on a
    `None` return.
    """

    def __init__(self, account):
        self.account = int(account)
        self._topics = []

    def preloadTopics(self, *args, **kwargs):
        return None

    def loadTopics(self, *args, **kwargs):
        return list(self._topics)

    def processTopics(self, *args, **kwargs):
        return None

    def getTopics(self, *args, **kwargs):
        return list(self._topics)

    def sortTopics(self, *args, **kwargs):
        return None

    def updateTopicsWithDeletedMessages(self, *args, **kwargs):
        return None

    def reloadTopics(self, *args, **kwargs):
        return None

    def searchTopics(self, *args, **kwargs):
        return 0

    def updateMaxReadId(self, *args, **kwargs):
        return None

    def findTopic(self, *args, **kwargs):
        return None

    def getTopicName(self, *args, **kwargs):
        return ""

    def getTopicIconName(self, *args, **kwargs):
        return ""

    def getTopicIconNameSafe(self, *args, **kwargs):
        return ""

    def getForumUnreadCount(self, *args, **kwargs):
        return [0, 0]

    def onTopicCreated(self, *args, **kwargs):
        return None

    def saveTopics(self, *args, **kwargs):
        return None

    def onTopicEdited(self, *args, **kwargs):
        return None

    def onTopicEditedServerSide(self, *args, **kwargs):
        return None

    def deleteTopics(self, *args, **kwargs):
        return None

    def toggleCloseTopic(self, *args, **kwargs):
        return None

    def getCurrentPinnedOrder(self, *args, **kwargs):
        return []

    def applyPinnedOrder(self, *args, **kwargs):
        return None

    def toggleShowTopic(self, *args, **kwargs):
        return None

    def toggleViewForumAsMessages(self, *args, **kwargs):
        return None

    def pinTopic(self, *args, **kwargs):
        return None

    def reorderPinnedTopics(self, *args, **kwargs):
        return None

    def updateMentionsUnread(self, *args, **kwargs):
        return 0

    def updateReactionsUnread(self, *args, **kwargs):
        return 0

    def updatePollVotesUnread(self, *args, **kwargs):
        return 0

    def markAllReactionsAsRead(self, *args, **kwargs):
        return None

    def markAllPollVotesAsRead(self, *args, **kwargs):
        return None

    def getLoadOffset(self, *args, **kwargs):
        return None

    def saveLoadOffset(self, *args, **kwargs):
        return None

    def clearLoadingOffset(self, *args, **kwargs):
        return None

    def endIsReached(self, *args, **kwargs):
        return True

    def processUpdate(self, *args, **kwargs):
        return None

    def isLoading(self, *args, **kwargs):
        return False

    def onTopicsDeletedServerSide(self, *args, **kwargs):
        return None

    def databaseCleared(self, *args, **kwargs):
        return None

    def updateReadOutbox(self, *args, **kwargs):
        return None

    def updateTopicInUi(self, *args, **kwargs):
        return None

    def processEditedMessages(self, *args, **kwargs):
        return None

    def processEditedMessage(self, *args, **kwargs):
        return None

    def loadTopic(self, *args, **kwargs):
        return None

    def onTopicFragmentResume(self, *args, **kwargs):
        return None

    def onTopicFragmentPause(self, *args, **kwargs):
        return None

    def getTopicRepliesCount(self, *args, **kwargs):
        return 0

    def getTopicsCount(self, *args, **kwargs):
        return len(self._topics)


class _MessagesControllerInstance:
    def __init__(self, account):
        self.account = int(account)

    def getUser(self, user_id):
        try:
            identifier = int(user_id)
        except (TypeError, ValueError):
            identifier = 0
        users_map, _ = _overlay_for(self.account)
        if identifier in users_map:
            return users_map[identifier]
        try:
            import extera_ios

            return extera_ios.get_peer(self.account, user_id)
        except Exception:
            return {}

    def getChat(self, chat_id):
        try:
            identifier = int(chat_id)
        except (TypeError, ValueError):
            identifier = 0
        _, chats_map = _overlay_for(self.account)
        if identifier in chats_map:
            return chats_map[identifier]
        return self.getUser(chat_id)

    def getPeer(self, peer_id):
        try:
            value = int(peer_id)
        except (TypeError, ValueError):
            value = 0
        return self.getChat(value) if value < 0 else self.getUser(value)

    def getSharedPreferences(self, name, mode=0, *args, **kwargs):
        return SharedPreferences(name)

    def getUserOrChat(self, peer_id):
        return self.getPeer(peer_id)

    def getInputPeer(self, dialog_id, *args, **kwargs):
        try:
            value = int(dialog_id)
        except (TypeError, ValueError):
            return {"_": "inputPeerEmpty"}
        if value > 0:
            user = _peer_dict(self.getUser(value)) or {}
            return {
                "_": "inputPeerUser",
                "user_id": value,
                "access_hash": int(user.get("access_hash") or 0),
            }
        if value <= -1000000000000:
            channel_id = -value - 1000000000000
            chat = _peer_dict(self.getChat(value)) or {}
            return {
                "_": "inputPeerChannel",
                "channel_id": channel_id,
                "access_hash": int(chat.get("access_hash") or 0),
            }
        if value < 0:
            return {"_": "inputPeerChat", "chat_id": -value}
        return {"_": "inputPeerEmpty"}

    def getInputUser(self, user_id, *args, **kwargs):
        value = int(user_id or 0)
        user = _peer_dict(self.getUser(value)) or {}
        return {
            "_": "inputUser",
            "user_id": value,
            "access_hash": int(user.get("access_hash") or 0),
        }

    def getInputChannel(self, channel_id, *args, **kwargs):
        value = int(channel_id or 0)
        chat = _peer_dict(self.getChat(-value if value > 0 else value)) or {}
        return {
            "_": "inputChannel",
            "channel_id": value,
            "access_hash": int(chat.get("access_hash") or 0),
        }

    # Android keeps users/chats that plugins inject in the same caches that
    # `getUser`/`getChat` read, so a plugin can register a peer it built.
    def putUser(self, user, *args, **kwargs):
        _put_users(self.account, [user])

    def putUsers(self, users, *args, **kwargs):
        _put_users(self.account, users)

    def putChat(self, chat, *args, **kwargs):
        _put_chats(self.account, [chat])

    def putChats(self, chats, *args, **kwargs):
        _put_chats(self.account, chats)

    def putUsersAndChats(self, users, chats, *args, **kwargs):
        _put_users(self.account, users)
        _put_chats(self.account, chats)

    def getDialog(self, peer_id):
        try:
            import extera_ios

            response = extera_ios.send_request(
                self.account, "messages.getPeerDialogs", {"peers": [int(peer_id)]}
            )
            if isinstance(response, dict):
                dialogs = response.get("dialogs", [])
                if isinstance(dialogs, list) and dialogs:
                    return dialogs[0]
        except Exception:
            pass
        return self.getUser(peer_id)

    def getPeerDialogs(self, peer_ids):
        try:
            import extera_ios

            return extera_ios.send_request(
                self.account,
                "messages.getPeerDialogs",
                {"peers": [int(value) for value in (peer_ids or [])]},
            )
        except Exception:
            return {}

    def getDialogUnreadCount(self, dialog, *args, **kwargs):
        data = _peer_dict(dialog)
        if isinstance(data, dict):
            return int(data.get("unread_count") or 0)
        return 0

    def isDialogPinned(self, dialog, *args, **kwargs):
        data = _peer_dict(dialog)
        return bool(data and (data.get("pinned") or data.get("is_pinned")))

    def getPinnedDialogs(self, folder_id=0, *args, **kwargs):
        return self._request(
            "messages.getPinnedDialogs", {"folder_id": int(folder_id or 0)}
        )

    def isPeerStoriesBlocked(self, *args, **kwargs):
        return False

    def getUserFull(self, user_id):
        try:
            import extera_ios

            return extera_ios.send_request(self.account, "users.getFullUser", {"id": int(user_id)})
        except Exception:
            return {}

    def getChatFull(self, chat_id):
        """`MessagesController.getChatFull` for a channel or a basic group.

        Android accepts either a dialog id or a chat's own id; a channel is
        resolved through `channels.getFullChannel`, a basic group through
        `messages.getFullChat`.
        """
        try:
            import extera_ios

            value = int(chat_id)
            if value <= -1000000000000:
                return extera_ios.send_request(
                    self.account, "channels.getFullChannel", {"channel": value}
                )
            positive = -value if value < 0 else value
            response = extera_ios.send_request(
                self.account, "messages.getFullChat", {"chat_id": positive}
            )
            if isinstance(response, dict) and response.get("error"):
                return extera_ios.send_request(
                    self.account,
                    "channels.getFullChannel",
                    {"channel": -1000000000000 - positive},
                )
            return response
        except Exception:
            return {}

    def loadFullUser(self, user, *args, **kwargs):
        return self.getUserFull(getattr(user, "id", user))

    def loadFullChat(self, chat, *args, **kwargs):
        return self.getChatFull(getattr(chat, "id", chat))

    def isChatNoForwards(self, chat):
        if isinstance(chat, dict):
            return bool(chat.get("noforwards"))
        return False

    def getMessages(self, peer_id, message_ids):
        """`MessagesController.getMessages`: users/groups use messages.getMessages,
        channels use channels.getMessages."""
        try:
            import extera_ios

            ids = [int(value) for value in (message_ids or [])]
            if not ids:
                return []
            value = int(peer_id)
            if value <= -1000000000000:
                response = extera_ios.send_request(
                    self.account, "channels.getMessages", {"channel": value, "id": ids}
                )
            else:
                response = extera_ios.send_request(
                    self.account, "messages.getMessages", {"id": ids}
                )
            if isinstance(response, dict):
                messages = response.get("messages", [])
                if isinstance(messages, list):
                    return messages
        except Exception:
            pass
        return []

    def getMessage(self, peer_id, message_id):
        wanted = int(message_id)
        for message in self.getMessages(peer_id, [wanted]):
            if isinstance(message, dict) and int(message.get("id", 0)) == wanted:
                return message
        return None

    @staticmethod
    def isChannel(peer):
        if isinstance(peer, dict):
            if peer.get("channel_id") or peer.get("is_channel"):
                return True
            return "channel" in str(peer.get("_", "")).lower()
        return False

    @staticmethod
    def isChat(peer):
        if isinstance(peer, dict):
            return bool(peer.get("chat_id")) and not bool(peer.get("channel_id"))
        return False

    @staticmethod
    def isUser(peer):
        if isinstance(peer, dict):
            return bool(peer.get("user_id")) and not peer.get("chat_id") and not peer.get("channel_id")
        return False

    # Android reads the controllers through `MessagesController` as well as
    # through `AccountInstance`; both routes must answer the same objects.
    def getContactsController(self):
        from client_utils import get_contacts_controller

        return get_contacts_controller(self.account)

    def getMediaDataController(self):
        from client_utils import get_media_data_controller

        return get_media_data_controller(self.account)

    def getNotificationsController(self):
        from client_utils import get_notifications_controller

        return get_notifications_controller(self.account)

    def getMessagesStorage(self):
        from client_utils import get_messages_storage

        return get_messages_storage(self.account)

    def getSendMessagesHelper(self):
        from client_utils import get_send_messages_helper

        return get_send_messages_helper(self.account)

    def getDownloadController(self):
        from client_utils import get_download_controller

        return get_download_controller(self.account)

    def getLocationController(self):
        from client_utils import get_location_controller

        return get_location_controller(self.account)

    def getSecretChatHelper(self):
        from client_utils import get_secret_chat_helper

        return get_secret_chat_helper(self.account)

    def getMediaController(self):
        from client_utils import get_media_controller

        return get_media_controller()

    def getAccountInstance(self):
        return _AccountInstance(self.account)

    def getConnectionsManager(self):
        return _ConnectionsManager(self.account)

    def getDialogs(self, folder=0, *args, **kwargs):
        return MessagesStorage.getInstance(self.account).getDialogs(folder)

    def getChats(self, *args, **kwargs):
        return MessagesStorage.getInstance(self.account).getChats()

    def getUsers(self, *args, **kwargs):
        return MessagesStorage.getInstance(self.account).getUsers()

    def isSupportChat(self, peer, *args, **kwargs):
        data = _peer_dict(peer)
        if not data:
            return False
        return bool(data.get("support")) or data.get("id") == 777000

    def checkCanOpenChat(self, *args, **kwargs):
        return True

    def canSendMessage(self, peer, *args, **kwargs):
        data = _peer_dict(peer)
        if not data:
            return True
        return not (
            data.get("left")
            or data.get("kicked")
            or data.get("restricted")
            or data.get("banned")
        )

    def isChatAdmin(self, chat, *args, **kwargs):
        return ChatObject.isAdmin(chat)

    def isChatMuted(self, chat, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("muted"))

    def _request(self, name, payload):
        try:
            import extera_ios

            return extera_ios.send_request(self.account, name, payload)
        except Exception:
            return None

    def _full_chat_request(self, chat):
        data = _peer_dict(chat)
        if not data or data.get("id") is None:
            return None
        identifier = int(data["id"])
        if ChatObject.isChannel(chat):
            return self._request(
                "channels.getFullChannel", {"peer": identifier, "channel": identifier}
            )
        return self._request(
            "messages.getFullChat", {"peer": identifier, "chat_id": identifier}
        )

    def loadFullUser(self, user, *args, **kwargs):
        data = _peer_dict(user)
        if not data or data.get("id") is None:
            return None
        return self._request("users.getFullUser", {"id": int(data["id"])})

    def loadFullChat(self, chat, *args, **kwargs):
        return self._full_chat_request(chat)

    def loadUserInfo(self, user, *args, **kwargs):
        return self.loadFullUser(user, *args, **kwargs)

    def loadChatInfo(self, chat, *args, **kwargs):
        return self.loadFullChat(chat, *args, **kwargs)

    def loadMessages(self, peer, *args, **kwargs):
        data = _peer_dict(peer)
        if not data or data.get("id") is None:
            return None
        return self._request(
            "messages.getHistory", {"peer": int(data["id"]), "limit": 100}
        )

    def loadPeerSettings(self, peer, *args, **kwargs):
        data = _peer_dict(peer)
        if not data or data.get("id") is None:
            return None
        return self._request(
            "messages.getPeerSettings", {"peer": int(data["id"])}
        )

    def getSponsoredMessages(self, *args, **kwargs):
        return {"messages": [], "chats": [], "users": []}

    def getChannelRecommendations(self, *args, **kwargs):
        return []

    def getTopicsController(self):
        controller = getattr(self, "_topics_controller", None)
        if controller is None:
            controller = _TopicsControllerInstance(self.account)
            self._topics_controller = controller
        return controller

    def loadUserPhotos(self, user, *args, **kwargs):
        data = _peer_dict(user)
        if not data or data.get("id") is None:
            return None
        return self._request(
            "photos.getUserPhotos", {"id": int(data["id"])}
        )

    def loadChatPhotos(self, *args, **kwargs):
        return None

    def sendTyping(self, peer, action="typing", *args, **kwargs):
        data = _peer_dict(peer)
        identifier = data.get("id") if data else (
            peer if isinstance(peer, int) else None
        )
        if identifier is None:
            return None
        return self._request(
            "messages.setTyping",
            {"peer": int(identifier), "action": str(action or "typing")},
        )

    def deleteMessages(self, messages, revoke=False, *args, **kwargs):
        ids = []
        for item in messages or []:
            if isinstance(item, int):
                ids.append(item)
                continue
            data = _peer_dict(item)
            value = data.get("id") if data else getattr(item, "id", None)
            if value is not None:
                ids.append(int(value))
        if not ids:
            return None
        return self._request(
            "messages.deleteMessages", {"id": ids, "revoke": bool(revoke)}
        )

    def markDialogAsRead(self, dialog_id, max_id=None, *args, **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        if identifier is None:
            return None
        payload = {"peer": int(identifier)}
        if max_id is not None:
            payload["max_id"] = int(max_id)
        return self._request("messages.readHistory", payload)

    def deleteHistory(self, dialog_id, just_clear=False, revoke=False, max_id=None,
                      min_date=None, max_date=None, *args, **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        if identifier is None:
            return None
        payload = {
            "peer": int(identifier),
            "just_clear": bool(just_clear),
            "revoke": bool(revoke),
        }
        if max_id is not None:
            payload["max_id"] = int(max_id)
        if min_date is not None:
            payload["min_date"] = int(min_date)
        if max_date is not None:
            payload["max_date"] = int(max_date)
        return self._request("messages.deleteHistory", payload)

    def deleteUserChatHistory(self, dialog_id, *args, **kwargs):
        return self.deleteHistory(dialog_id, *args, **kwargs)

    def deleteDialog(self, did, onlyHistory=0, revoke=False, *args, **kwargs):
        return self.deleteHistory(
            did, just_clear=bool(onlyHistory), revoke=bool(revoke)
        )

    def markDialogAsUnread(self, dialog_id, *args, **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        if identifier is None:
            return None
        return self._request(
            "messages.markDialogUnread", {"peer": int(identifier), "unread": True}
        )

    def mutePeer(self, peer, mute=True, *args, **kwargs):
        data = _peer_dict(peer)
        identifier = data.get("id") if data else (
            peer if isinstance(peer, int) else None
        )
        if identifier is None:
            return None
        return self._request(
            "account.updateNotifySettings",
            {
                "peer": int(identifier),
                "mute_until": 2147483647 if mute else 0,
                "show_previews": True,
            },
        )

    def unmutePeer(self, peer, *args, **kwargs):
        return self.mutePeer(peer, False, *args, **kwargs)

    def setPeerMuted(self, peer, mute, *args, **kwargs):
        return self.mutePeer(peer, mute, *args, **kwargs)

    def readMentions(self, peer, *args, **kwargs):
        data = _peer_dict(peer)
        identifier = data.get("id") if data else (
            peer if isinstance(peer, int) else None
        )
        if identifier is None:
            return None
        return self._request("messages.readMentions", {"peer": int(identifier)})

    def readReactions(self, peer, *args, **kwargs):
        data = _peer_dict(peer)
        identifier = data.get("id") if data else (
            peer if isinstance(peer, int) else None
        )
        if identifier is None:
            return None
        return self._request("messages.readReactions", {"peer": int(identifier)})

    def joinChannel(self, chat, *args, **kwargs):
        data = _peer_dict(chat)
        if not data or data.get("id") is None:
            return None
        identifier = int(data["id"])
        return self._request(
            "channels.joinChannel", {"channel": identifier, "peer": identifier}
        )

    def leaveChannel(self, chat, *args, **kwargs):
        data = _peer_dict(chat)
        if not data or data.get("id") is None:
            return None
        identifier = int(data["id"])
        return self._request(
            "channels.leaveChannel", {"channel": identifier, "peer": identifier}
        )

    @staticmethod
    def _message_reference(message):
        data = _peer_dict(message)
        if not data:
            return None, None
        message_id = data.get("id") or data.get("message_id")
        peer = (
            data.get("peer")
            or data.get("peer_id")
            or data.get("dialog_id")
            or data.get("dialogId")
        )
        if peer is None:
            for key in ("chat", "user", "channel"):
                nested = data.get(key)
                if isinstance(nested, dict) and nested.get("id") is not None:
                    peer = nested.get("id")
                    break
        return peer, message_id

    def pinMessage(self, message, silent=False, *args, **kwargs):
        peer, message_id = self._message_reference(message)
        if peer is None or message_id is None:
            return None
        return self._request(
            "messages.updatePinnedMessage",
            {
                "peer": int(peer),
                "id": int(message_id),
                "silent": bool(silent),
                "unpin": False,
            },
        )

    def unpinMessage(self, message, silent=False, *args, **kwargs):
        peer, message_id = self._message_reference(message)
        if peer is None:
            return None
        return self._request(
            "messages.updatePinnedMessage",
            {
                "peer": int(peer),
                "id": int(message_id or 0),
                "silent": bool(silent),
                "unpin": True,
            },
        )

    def blockUser(self, user, *args, **kwargs):
        data = _peer_dict(user)
        identifier = data.get("id") if data else (
            user if isinstance(user, int) else None
        )
        if identifier is None:
            return None
        return self._request("contacts.block", {"id": int(identifier)})

    def unblockUser(self, user, *args, **kwargs):
        data = _peer_dict(user)
        identifier = data.get("id") if data else (
            user if isinstance(user, int) else None
        )
        if identifier is None:
            return None
        return self._request("contacts.unblock", {"id": int(identifier)})

    def blockPeer(self, peer, *args, **kwargs):
        data = _peer_dict(peer)
        identifier = data.get("id") if data else (
            peer if isinstance(peer, int) else None
        )
        if identifier is None:
            return None
        return self._request("contacts.block", {"id": int(identifier)})

    def unblockPeer(self, peer, *args, **kwargs):
        return self.unblockUser(peer, *args, **kwargs)

    def addUserToChat(self, chat_id, user, *args, **kwargs):
        data = _peer_dict(user)
        identifier = data.get("id") if data else (
            user if isinstance(user, int) else None
        )
        if identifier is None:
            return None
        if ChatObject.isChannel(self.getChat(chat_id)):
            return self._request(
                "channels.inviteToChannel",
                {"channel": int(chat_id), "users": [int(identifier)]},
            )
        return self._request(
            "messages.addChatUser",
            {"chat_id": int(chat_id), "user_id": int(identifier), "fwd_limit": 0},
        )

    def deleteParticipantFromChat(self, chat_id, user, *args, **kwargs):
        data = _peer_dict(user)
        identifier = data.get("id") if data else (
            user if isinstance(user, int) else None
        )
        if identifier is None:
            return None
        chat = self.getChat(chat_id)
        if ChatObject.isChannel(chat):
            return self._request(
                "channels.editBanned",
                {
                    "channel": int(chat_id),
                    "participant": int(identifier),
                    "banned_rights": {"view_messages": True},
                },
            )
        return self._request(
            "messages.deleteChatUser",
            {"chat_id": int(chat_id), "user_id": int(identifier)},
        )

    def createChat(self, title, users=None, *args, **kwargs):
        identifiers = []
        for user in users or []:
            data = _peer_dict(user)
            identifier = data.get("id") if data else (
                user if isinstance(user, int) else None
            )
            if identifier is not None:
                identifiers.append(int(identifier))
        return self._request(
            "messages.createChat",
            {"title": str(title or ""), "users": identifiers},
        )

    def convertToMegaGroup(self, chat_id, *args, **kwargs):
        return self._request("messages.migrateChat", {"chat_id": int(chat_id)})

    def changeChatTitle(self, chat_id, title, *args, **kwargs):
        chat = self.getChat(chat_id)
        if ChatObject.isChannel(chat):
            return self._request(
                "channels.editTitle",
                {"channel": int(chat_id), "title": str(title or "")},
            )
        return self._request(
            "messages.editChatTitle",
            {"chat_id": int(chat_id), "title": str(title or "")},
        )

    def deleteUserPhoto(self, photo, *args, **kwargs):
        data = _peer_dict(photo)
        identifier = data.get("id") if data else (
            photo if isinstance(photo, int) else None
        )
        if identifier is None:
            return None
        return self._request("photos.deletePhotos", {"id": [int(identifier)]})

    def setUserBannedRights(self, chat_id, user, rights, *args, **kwargs):
        data = _peer_dict(user)
        identifier = data.get("id") if data else (
            user if isinstance(user, int) else None
        )
        if identifier is None:
            return None
        payload = _peer_dict(rights) or rights or {}
        return self._request(
            "channels.editBanned",
            {
                "channel": int(chat_id),
                "participant": int(identifier),
                "banned_rights": payload,
            },
        )

    def addDialogAction(self, dialog_id, action, *args, **kwargs):
        return self.sendTyping(dialog_id, action)

    def cancelTyping(self, action, dialog_id, *args, **kwargs):
        return self.sendTyping(dialog_id, None)

    def getDialogFolderId(self, dialog, *args, **kwargs):
        data = _peer_dict(dialog)
        if not data:
            return 0
        if data.get("folder_id") is not None:
            return int(data["folder_id"])
        if data.get("id") is not None and int(data["id"]) < 0:
            return 1 if data.get("is_folder") else 0
        return 0

    def isDialogUnread(self, dialog, *args, **kwargs):
        return self.getDialogUnreadCount(dialog) > 0

    def markMessageAsRead(self, dialog_id, message_id=0, *args, **kwargs):
        return self.markDialogAsRead(dialog_id, message_id)

    def loadSponsoredMessages(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        # A plugin may call a controller method this port has not mapped yet.
        # Answer the Java default for its shape instead of aborting the plugin.
        return _tolerant_java_getattr(self, name)


class SavedMusicList(list):
    def size(self):
        return len(self)

    def get(self, index):
        try:
            return self[int(index)]
        except (IndexError, TypeError, ValueError):
            return None

    def add(self, value):
        self.append(value)
        return True

    def isEmpty(self):
        return not self

    def clear(self):
        del self[:]


class MessagesController(metaclass=_UpdateConstantsMeta):
    SavedMusicList = SavedMusicList()

    @classmethod
    def getInstance(cls, account=0):
        return _MessagesControllerInstance(account)

    @classmethod
    def getGlobalMainSettings(cls):
        return SharedPreferences("mainconfig")


class _AccountInstance:
    def __init__(self, account):
        self.account = int(account)

    def getMessagesController(self):
        return MessagesController.getInstance(self.account)

    def getUserConfig(self):
        return UserConfig.getInstance(self.account)

    def getConnectionsManager(self):
        return _ConnectionsManager(self.account)

    def getContactsController(self):
        from client_utils import get_contacts_controller

        return get_contacts_controller(self.account)

    def getMediaDataController(self):
        from client_utils import get_media_data_controller

        return get_media_data_controller(self.account)

    def getNotificationsController(self):
        from client_utils import get_notifications_controller

        return get_notifications_controller(self.account)

    def getMessagesStorage(self):
        from client_utils import get_messages_storage

        return get_messages_storage(self.account)

    def getSendMessagesHelper(self):
        from client_utils import get_send_messages_helper

        return get_send_messages_helper(self.account)

    def getFileLoader(self):
        from client_utils import get_file_loader

        return get_file_loader(self.account)

    def getDownloadController(self):
        from client_utils import get_download_controller

        return get_download_controller(self.account)

    def getSecretChatHelper(self):
        from client_utils import get_secret_chat_helper

        return get_secret_chat_helper(self.account)

    def getLocationController(self):
        from client_utils import get_location_controller

        return get_location_controller(self.account)

    def getMediaController(self):
        return MediaController.getInstance(self.account)

    def getTopicsController(self):
        return MessagesController.getInstance(self.account).getTopicsController()

    def getNotificationsSettings(self):
        from client_utils import get_notifications_settings

        return get_notifications_settings(self.account)


class _ConnectionsManager:
    def __init__(self, account):
        self.account = int(account)

    def sendRequest(self, request, callback=None, *args, **kwargs):
        try:
            from client_utils import send_request

            return send_request(request, callback or (lambda result, error: None), account=self.account)
        except Exception:
            return 0

    def getCurrentTime(self):
        import time

        return int(time.time())

    def getConnectionState(self):
        return 3

    def cancelRequest(self, token, *args, **kwargs):
        return None

    def isConnected(self):
        return True

    def getCurrentDatacenterId(self, *args, **kwargs):
        return 1

    def getTimeDifference(self):
        return 0

    def getPingTime(self):
        return 0

    def setLangCode(self, code, *args, **kwargs):
        self._lang_code = str(code or "en")
        return None

    def getLangCode(self, *args, **kwargs):
        return getattr(self, "_lang_code", "en")

    def isTestBackend(self):
        return False

    def setTestBackend(self, value):
        return None

    def pauseNetwork(self, *args, **kwargs):
        return None

    def resumeNetwork(self, *args, **kwargs):
        return None

    def getProxySettings(self, *args, **kwargs):
        return None

    def setProxySettings(self, *args, **kwargs):
        return None

    def bindRequestToGuid(self, token, guid):
        return None

    def setAppPaused(self, *args, **kwargs):
        return None

    def sendRequestSync(self, request, *args, **kwargs):
        try:
            import extera_ios

            name = None
            payload = {}
            if isinstance(request, dict):
                name = request.get("_") or request.get("name")
                payload = request
            elif hasattr(request, "to_native"):
                name, payload = request.to_native()
            elif hasattr(request, "get_name"):
                name = request.get_name()
                payload = getattr(request, "fields", {}) or {}
            if not name:
                return None
            return extera_ios.send_request(self.account, name, payload)
        except Exception:
            return None


class ConnectionsManager:
    @classmethod
    def getInstance(cls, account=0):
        return _ConnectionsManager(account)

    @classmethod
    def setProxySettings(cls, *args, **kwargs):
        return cls.getInstance(0).setProxySettings(*args, **kwargs)

    @classmethod
    def getProxySettings(cls, *args, **kwargs):
        return cls.getInstance(0).getProxySettings(*args, **kwargs)


class AccountInstance:
    @classmethod
    def getInstance(cls, account=0):
        return _AccountInstance(account)


# ---------------------------------------------------------------------------
# FileLoader / ApplicationLoader


class ContactsController:
    @classmethod
    def getInstance(cls, account=0):
        return _ContactsControllerInstance(account)


class _ContactsControllerInstance:
    def __init__(self, account):
        self.account = int(account)

    def getContacts(self):
        try:
            import extera_ios

            return extera_ios.get_contacts(self.account)
        except Exception:
            return []

    @property
    def contacts(self):
        return self.getContacts()

    @property
    def contactsDict(self):
        result = {}
        for contact in self.getContacts():
            if not isinstance(contact, dict):
                continue
            identifier = contact.get("user_id") or contact.get("id")
            if identifier is not None:
                result[int(identifier)] = contact
        return result

    def getContactsHash(self):
        return sum(
            int(contact.get("user_id") or contact.get("id") or 0)
            for contact in self.getContacts()
            if isinstance(contact, dict)
        )

    def loadContacts(self, *args, **kwargs):
        return self.getContacts()

    def getContactsFromCache(self, *args, **kwargs):
        return self.getContacts()

    def isLoadingContacts(self):
        return False

    def _request(self, name, payload):
        try:
            import extera_ios

            return extera_ios.send_request(self.account, name, payload)
        except Exception:
            return None

    def addContact(self, user=None, first_name="", last_name="", phone="", note="",
                   *args, **kwargs):
        # Android overloads: `addContact(user)` and
        # `addContact(firstName, lastName, phone)`.
        if isinstance(user, str):
            if first_name or last_name:
                first_name, last_name, phone = (
                    user,
                    first_name,
                    last_name if last_name else phone,
                )
            else:
                first_name = user
            user = None
        payload = {
            "first_name": str(first_name or ""),
            "last_name": str(last_name or ""),
            "phone": str(phone or ""),
            "note": str(note or ""),
        }
        data = _peer_dict(user) if user is not None else None
        identifier = data.get("id") if data else (
            user if isinstance(user, int) else None
        )
        if identifier is not None:
            payload["id"] = int(identifier)
            return self._request("contacts.addContact", payload)
        if phone:
            contacts = dict(payload)
            contacts["client_id"] = abs(hash(phone)) % 1000000
            return self._request(
                "contacts.importContacts", {"contacts": [contacts]}
            )
        return None

    def deleteContact(self, user, *args, **kwargs):
        data = _peer_dict(user)
        identifier = data.get("id") if data else (
            user if isinstance(user, int) else None
        )
        if identifier is None:
            return None
        return self._request("contacts.deleteContacts", {"id": [int(identifier)]})

    def getContact(self, user_id):
        wanted = int(user_id)
        for contact in self.getContacts():
            if not isinstance(contact, dict):
                continue
            identifier = contact.get("user_id") or contact.get("id")
            if identifier is not None and int(identifier) == wanted:
                return contact
        return None

    def getUserName(self, user):
        from org.telegram.messenger import UserObject

        return UserObject.getUserName(user)

    def getContactsCopy(self, contacts=None, *args, **kwargs):
        source = contacts if isinstance(contacts, dict) else self.contactsDict
        result = {}
        for identifier, contact in dict(source).items():
            if isinstance(contact, dict):
                result[identifier] = dict(contact)
            elif contact is not None:
                result[identifier] = contact
        return result

    def hasContactsPermission(self, *args, **kwargs):
        return True

    def hasContactsWritePermission(self, *args, **kwargs):
        return True

    def checkContacts(self, *args, **kwargs):
        return None

    def readContacts(self, *args, **kwargs):
        return None

    def forceImportContacts(self, *args, **kwargs):
        return self._request("contacts.importContacts", {"contacts": []})

    def resetImportedContacts(self, *args, **kwargs):
        return None

    def getGlobalPrivacySettings(self, *args, **kwargs):
        return self._request("account.getGlobalPrivacySettings", {})

    def loadGlobalPrivacySetting(self, *args, **kwargs):
        return self.getGlobalPrivacySettings()

    def getPrivacyRules(self, key, *args, **kwargs):
        return self._request("account.getPrivacy", {"key": str(key)})

    def loadPrivacySettings(self, *args, **kwargs):
        return None

    def getInviteText(self, *args, **kwargs):
        return self._request("help.getInviteText", {})

    def getDeleteAccountTTL(self, *args, **kwargs):
        return self._request("account.getAccountTTL", {})

    def setDeleteAccountTTL(self, ttl, *args, **kwargs):
        return self._request(
            "account.setAccountTTL", {"days": int(ttl or 0)}
        )

    def setPrivacyRules(self, key, rules, *args, **kwargs):
        payload = {}
        if isinstance(rules, dict):
            payload = rules.get("rules") or []
        elif isinstance(rules, (list, tuple)):
            payload = list(rules)
        return self._request(
            "account.setPrivacy", {"key": str(key), "rules": payload}
        )

    def getContactsCount(self, *args, **kwargs):
        return len(self.getContacts())


class MediaController:
    @classmethod
    def getInstance(cls, account=0):
        return _MediaControllerInstance(account)


class VideoPlayer:
    def __init__(self, *args, **kwargs):
        self.position = 0
        self.volume = 1.0
        self._playing = False

    def play(self):
        self._playing = True

    def pause(self):
        self._playing = False

    def isPlaying(self):
        return self._playing

    def releasePlayer(self):
        self._playing = False

    def setVolume(self, value):
        self.volume = float(value or 0.0)

    def getVolume(self):
        return self.volume


class _AudioPlayerFacade:
    def __init__(self, controller):
        self._controller = controller

    def isPlaying(self):
        return self._controller.isPlayingAudio()

    def getCurrentPosition(self):
        return self._controller.getPlaybackPosition()

    def getDuration(self):
        return self._controller.getPlaybackDuration()

    def pause(self):
        self._controller.pauseAudio()

    def start(self):
        self._controller.resumeAudio()

    def release(self):
        self._controller._host("audio.stop")

    def setVolume(self, value):
        self._controller._host("audio.volume", volume=float(value or 0.0))

    def getVolume(self):
        return float(self._controller._state().get("volume") or 1.0)


class _MediaControllerInstance:
    def __init__(self, account):
        self.account = int(account)
        self._playing_message = None
        self._playing_path = None
        self._playback_order = 0
        self._playlist = []
        self.videoPlayer = VideoPlayer()
        self.audioPlayer = _AudioPlayerFacade(self)

    @staticmethod
    def _host(method, **payload):
        try:
            import extera_ios

            return extera_ios.host(method, **payload)
        except Exception:
            return None

    def _state(self):
        value = self._host("audio.state")
        return value if isinstance(value, dict) else {}

    def isPlayingAudio(self):
        return bool(self._state().get("playing"))

    def getPlayingMessageObject(self):
        return self._playing_message

    def playMessage(self, message, *args, **kwargs):
        if message is None:
            return False
        path = FileLoader.getPathToMessage(message)
        if path is None:
            return False
        location = path.getPath() if hasattr(path, "getPath") else str(path)
        if not location or not os.path.exists(location):
            return False
        result = self._host("audio.play", path=str(location)) or {}
        if isinstance(result, dict) and result.get("ok") is False:
            return False
        self._playing_message = message
        self._playing_path = location
        return True

    def stopPlayingMessage(self, *args, **kwargs):
        self._host("audio.stop")
        self._playing_message = None
        self._playing_path = None

    def getPlaybackPosition(self):
        return int(self._state().get("position") or 0)

    def getPlaybackDuration(self):
        return int(self._state().get("duration") or 0)

    def setPlaybackOrder(self, order, *args, **kwargs):
        self._playback_order = int(order or 0)

    def getPlaybackOrder(self):
        return self._playback_order

    def pauseAudio(self, *args, **kwargs):
        self._host("audio.pause")

    def resumeAudio(self, *args, **kwargs):
        self._host("audio.resume")

    def seekToProgress(self, progress, *args, **kwargs):
        duration = float(self._state().get("duration") or 0.0)
        self._host("audio.seek", position=float(progress or 0.0) * duration)

    def setPlaybackSpeed(self, speed, *args, **kwargs):
        self._host("audio.rate", rate=float(speed or 1.0))

    def getPlaybackSpeed(self):
        return float(self._state().get("rate") or 1.0)

    def setPlaylist(self, playlist=None, *args, **kwargs):
        self._playlist = list(playlist or [])

    def getPlaylist(self):
        return self._playlist

    def isPlayingMessage(self, message, *args, **kwargs):
        if self._playing_message is None:
            return False
        if message is self._playing_message:
            return True
        current_id = getattr(self._playing_message, "id", None)
        other_id = getattr(message, "id", None)
        return current_id is not None and current_id == other_id

    def playNextMessage(self, *args, **kwargs):
        if not self._playlist:
            return None
        try:
            index = self._playlist.index(self._playing_message)
        except ValueError:
            index = -1
        if index + 1 < len(self._playlist):
            return self.playMessage(self._playlist[index + 1])
        return None

    def playPreviousMessage(self, *args, **kwargs):
        if not self._playlist:
            return None
        try:
            index = self._playlist.index(self._playing_message)
        except ValueError:
            index = len(self._playlist)
        if index - 1 >= 0:
            return self.playMessage(self._playlist[index - 1])
        return None

    def cleanup(self, *args, **kwargs):
        self.stopPlayingMessage()

    def isMessagePaused(self, message=None, *args, **kwargs):
        state = self._state()
        if state.get("playing"):
            return False
        return bool(self._playing_message is not None and state.get("paused"))

    def isPaused(self, *args, **kwargs):
        return bool(self._state().get("paused"))

    def isBuffering(self, *args, **kwargs):
        return bool(self._state().get("buffering"))

    def isStreamingCurrentAudio(self, *args, **kwargs):
        return False

    def isDownloadingCurrentMessage(self, *args, **kwargs):
        return False

    def isPlayingMessageAndReadyToDraw(self, message=None, *args, **kwargs):
        return self.isPlayingMessage(message)

    def getMusicList(self, *args, **kwargs):
        return list(self._playlist)

    def getPlayingMessageObjectNum(self, *args, **kwargs):
        try:
            return self._playlist.index(self._playing_message)
        except ValueError:
            return -1

    def getCurrentPlaybackPosition(self, *args, **kwargs):
        return self.getPlaybackPosition()

    def getCurrentChromecastMedia(self, *args, **kwargs):
        return None

    def setCurrentPlayingMessage(self, message=None, *args, **kwargs):
        self._playing_message = message
        return None

    def checkIsNextMediaFileDownloaded(self, *args, **kwargs):
        return False

    def pauseMessage(self, message, *args, **kwargs):
        if message is None or self.isPlayingMessage(message):
            self.pauseAudio()
            return True
        return False

    def cleanupPlayer(self, *args, **kwargs):
        self.stopPlayingMessage()
        self._playlist = []
        return None

    @property
    def audioVolume(self):
        return float(self._state().get("volume") or 1.0)

    @audioVolume.setter
    def audioVolume(self, value):
        self._host("audio.volume", volume=float(value or 0.0))

    def getVideoPlayer(self, *args, **kwargs):
        return self.videoPlayer


class MediaDataController:
    @classmethod
    def getInstance(cls, account=0):
        return _MediaDataControllerInstance(account)


def _sticker_set_payload(value):
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if not isinstance(data, dict):
        return None
    payload = {}
    if isinstance(data.get("short_name"), str) and data["short_name"]:
        payload["short_name"] = data["short_name"]
    if data.get("id") is not None:
        payload["id"] = int(data["id"])
    if data.get("access_hash") is not None:
        payload["access_hash"] = int(data["access_hash"])
    return payload or None


def _sticker_document_payload(value):
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if not isinstance(data, dict):
        return None
    document = data.get("document") if isinstance(data.get("document"), dict) else data
    if not isinstance(document, dict) or document.get("id") is None:
        return None
    payload = {
        "id": int(document["id"]),
        "access_hash": int(document.get("access_hash") or 0),
    }
    reference = document.get("file_reference")
    if isinstance(reference, (bytes, bytearray)):
        import base64

        payload["file_reference"] = base64.b64encode(bytes(reference)).decode("ascii")
    elif isinstance(reference, str) and reference:
        payload["file_reference"] = reference
    return payload


class _MediaDataControllerInstance:
    def __init__(self, account):
        self.account = int(account)
        self._sticker_sets = []
        self._featured = []
        self._recent = []
        self._archived = []
        self._emoji_keywords = []
        self._emoji_version = 0
        self._recent_reactions = []
        self._double_tap_reaction = None

    def _request(self, name, payload):
        try:
            import extera_ios

            return extera_ios.send_request(self.account, name, payload)
        except Exception:
            return None

    @staticmethod
    def _list(response, key):
        if isinstance(response, dict):
            value = response.get(key)
            if isinstance(value, list):
                return list(value)
        return []

    def getStickerSets(self, *args, **kwargs):
        return list(self._sticker_sets)

    def getAllStickers(self, *args, **kwargs):
        return list(self._sticker_sets)

    def loadStickers(self, *args, **kwargs):
        response = self._request("messages.getAllStickers", {})
        self._sticker_sets = self._list(response, "sets")
        return self._sticker_sets

    def loadStickersByEmojiOrName(self, emoji, *args, **kwargs):
        response = self._request(
            "messages.getStickers",
            {"emoticon": str(emoji or ""), "hash": 0},
        )
        stickers = self._list(response, "stickers")
        return stickers if stickers else list(self._sticker_sets)

    def getStickersByEmojiOrName(self, emoji, *args, **kwargs):
        return self.loadStickersByEmojiOrName(emoji, *args, **kwargs)

    def getFeaturedStickers(self, *args, **kwargs):
        return list(self._featured)

    def loadFeaturedStickers(self, *args, **kwargs):
        response = self._request("messages.getFeaturedStickers", {"hash": 0})
        self._featured = self._list(response, "sets")
        return self._featured

    def getTrendingStickerSets(self, *args, **kwargs):
        return list(self._featured)

    def getRecentStickers(self, *args, **kwargs):
        return list(self._recent)

    def loadRecentStickers(self, *args, **kwargs):
        response = self._request("messages.getRecentStickers", {"hash": 0})
        self._recent = self._list(response, "stickers")
        return self._recent

    def getArchivedStickersCount(self, *args, **kwargs):
        response = self._request(
            "messages.getArchivedStickers", {"offset_id": 0, "limit": 1}
        )
        if isinstance(response, dict):
            count = response.get("count")
            if count is not None:
                return int(count)
            return len(self._list(response, "sets"))
        return 0

    def loadArchivedStickers(self, *args, **kwargs):
        response = self._request(
            "messages.getArchivedStickers", {"offset_id": 0, "limit": 200}
        )
        self._archived = self._list(response, "sets")
        return self._archived

    def toggleStickerSet(self, stickerset=None, installed=True, *args, **kwargs):
        payload = _sticker_set_payload(stickerset)
        if payload is None:
            return None
        if installed:
            payload["archived"] = False
            return self._request("messages.installStickerSet", payload)
        return self._request("messages.uninstallStickerSet", payload)

    def addRecentSticker(self, sticker, *args, **kwargs):
        payload = _sticker_document_payload(sticker)
        if payload is None:
            return None
        payload["unsave"] = False
        return self._request("messages.saveRecentSticker", payload)

    def removeRecentSticker(self, sticker, *args, **kwargs):
        payload = _sticker_document_payload(sticker)
        if payload is None:
            return None
        payload["unsave"] = True
        return self._request("messages.saveRecentSticker", payload)

    def getStickerSetByName(self, name, *args, **kwargs):
        return self._request("messages.getStickerSet", {"short_name": str(name)})

    def getStickerSetById(self, set_id, access_hash=0, *args, **kwargs):
        return self._request(
            "messages.getStickerSet",
            {"id": int(set_id), "access_hash": int(access_hash or 0)},
        )

    def getEmojiSuggestions(self, *args, **kwargs):
        return list(self._emoji_keywords)

    def getEmojiKeywords(self, *args, **kwargs):
        return list(self._emoji_keywords)

    def loadEmojiKeywords(self, lang_code="en", from_version=0, *args, **kwargs):
        response = self._request(
            "messages.getEmojiKeywordsDifference",
            {
                "lang_code": str(lang_code or "en"),
                "from_version": int(from_version or 0),
            },
        )
        if isinstance(response, dict):
            keywords = response.get("keywords")
            if isinstance(keywords, list):
                self._emoji_keywords = list(keywords)
            if response.get("version") is not None:
                self._emoji_version = response.get("version")
        return list(self._emoji_keywords)

    def areStickersLoaded(self, *args, **kwargs):
        return bool(self._sticker_sets)

    def checkStickers(self, *args, **kwargs):
        return None

    def checkFeaturedStickers(self, *args, **kwargs):
        return None

    def checkFeaturedEmoji(self, *args, **kwargs):
        return None

    def checkReactions(self, *args, **kwargs):
        return None

    def checkMenuBots(self, *args, **kwargs):
        return None

    def checkPremiumPromo(self, *args, **kwargs):
        return None

    def isLoadingStickers(self, *args, **kwargs):
        return False

    def getRecentStickersNoCopy(self, *args, **kwargs):
        return list(self._recent)

    def clearRecentStickers(self, *args, **kwargs):
        self._recent = []
        return None

    def isStickerInFavorites(self, sticker=None, *args, **kwargs):
        return False

    def getRecentGifs(self, *args, **kwargs):
        return []

    def addRecentGif(self, *args, **kwargs):
        return None

    def removeRecentGif(self, *args, **kwargs):
        return None

    def hasRecentGif(self, *args, **kwargs):
        return False

    def getStickerSetByEmojiOrName(self, value=None, *args, **kwargs):
        return self.getStickerSetByName(value)

    def getGroupStickerSetById(self, *args, **kwargs):
        return None

    def putGroupStickerSet(self, *args, **kwargs):
        return None

    def getInputStickerSet(self, value=None, *args, **kwargs):
        return _sticker_set_payload(value)

    def getInputStickerSetItem(self, value=None, *args, **kwargs):
        payload = _sticker_document_payload(value)
        if payload is None:
            return None
        payload["emoji"] = ""
        return payload

    def setPlaceholderImage(self, *args, **kwargs):
        return None

    def setPlaceholderImageByIndex(self, *args, **kwargs):
        return None

    def inputSetKey(self, *args, **kwargs):
        return ""

    def getStickerSet(self, value=None, *args, **kwargs):
        if isinstance(value, str):
            return self.getStickerSetByName(value)
        data = value if isinstance(value, dict) else getattr(value, "_value", None)
        if isinstance(data, dict):
            if data.get("short_name"):
                return self.getStickerSetByName(data["short_name"])
            if data.get("id") is not None:
                return self.getStickerSetById(
                    data.get("id"), data.get("access_hash") or 0
                )
        return None

    def putStickerSet(self, *args, **kwargs):
        return None

    def getAllStickersFeatured(self, *args, **kwargs):
        return list(self._featured)

    def getEmojiAnimatedSticker(self, *args, **kwargs):
        return None

    def canAddStickerToFavorites(self, *args, **kwargs):
        return False

    def getStickerByIds(self, *args, **kwargs):
        return {}

    def getFeaturedStickerSets(self, *args, **kwargs):
        return list(self._featured)

    def getFeaturedEmojiSets(self, *args, **kwargs):
        return []

    def getUnreadStickerSets(self, *args, **kwargs):
        return []

    def getUnreadEmojiSets(self, *args, **kwargs):
        return []

    def getPremiumPromo(self, *args, **kwargs):
        return None

    def getPremiumHintAnnualDiscount(self, *args, **kwargs):
        return None

    def getAttachMenuBots(self, *args, **kwargs):
        return None

    def loadAttachMenuBots(self, *args, **kwargs):
        return None

    def isMenuBotsUpdatedLocal(self, *args, **kwargs):
        return False

    def updateAttachMenuBotsInCache(self, *args, **kwargs):
        return None

    def loadPremiumPromo(self, *args, **kwargs):
        return None

    def getReactionsList(self, *args, **kwargs):
        return []

    def loadReactions(self, *args, **kwargs):
        return None

    def preloadDefaultReactions(self, *args, **kwargs):
        return None

    def preloadImage(self, *args, **kwargs):
        return None

    def getDraft(self, dialog_id, *args, **kwargs):
        try:
            return SharedPreferences(
                "drafts_%s" % self.account
            ).getString("draft_%s" % int(dialog_id), None)
        except Exception:
            return None

    def saveDraft(self, dialog_id, draft, *args, **kwargs):
        try:
            self._draft_preferences().edit().putString(
                "draft_%s" % int(dialog_id), str(draft or "")
            ).apply()
        except Exception:
            pass
        return None

    def clearDraft(self, dialog_id, *args, **kwargs):
        try:
            self._draft_preferences().edit().remove(
                "draft_%s" % int(dialog_id)
            ).apply()
        except Exception:
            pass
        return None

    def clearAllDrafts(self, *args, **kwargs):
        try:
            self._draft_preferences().edit().clear().apply()
        except Exception:
            pass
        return None

    def _draft_preferences(self):
        return SharedPreferences("drafts_%s" % self.account)

    def getDraftMessage(self, dialog_id, *args, **kwargs):
        return self.getDraft(dialog_id)

    def getDraftVoice(self, dialog_id, *args, **kwargs):
        return None

    def getAllStickers(self, *args, **kwargs):
        return list(self._recent)

    def getEnabledReactionsList(self, *args, **kwargs):
        return self.getReactionsList()

    def getRecentReactions(self, *args, **kwargs):
        return list(self._recent_reactions)

    def addRecentReaction(self, reaction, *args, **kwargs):
        values = getattr(self, "_recent_reactions", [])
        if reaction not in values:
            values.insert(0, reaction)
            self._recent_reactions = values[:20]
        return None

    def clearRecentReactions(self, *args, **kwargs):
        self._recent_reactions = []
        return None

    def loadRecentAndTopReactions(self, *args, **kwargs):
        return self.getRecentReactions()

    def loadReactionsFromPref(self, *args, **kwargs):
        return self.getReactionsList()

    def saveReactionsToPref(self, *args, **kwargs):
        return None

    def getDoubleTapReaction(self, *args, **kwargs):
        return getattr(self, "_double_tap_reaction", None)

    def setDoubleTapReaction(self, reaction, *args, **kwargs):
        self._double_tap_reaction = reaction
        return None

    def isStickerPackInstalled(self, set_id, *args, **kwargs):
        return int(set_id or 0) in {
            int(item.get("id") or 0)
            for item in self._sticker_sets
            if isinstance(item, dict)
        }

    def isStickerPackUnread(self, set_id, *args, **kwargs):
        return False

    def getStickerSetId(self, value, *args, **kwargs):
        data = value if isinstance(value, dict) else getattr(value, "_value", None)
        if isinstance(data, dict):
            return int(data.get("id") or 0)
        return 0

    def getStickerSetName(self, value, *args, **kwargs):
        data = value if isinstance(value, dict) else getattr(value, "_value", None)
        if isinstance(data, dict):
            return str(data.get("short_name") or "")
        return ""

    def findStickerSetByNameInCache(self, name, *args, **kwargs):
        return self.getStickerSetByName(name)

    def markFeaturedStickersAsRead(self, *args, **kwargs):
        return None

    def markFeaturedStickersByIdAsRead(self, *args, **kwargs):
        return None

    def removeMultipleStickerSets(self, *args, **kwargs):
        return None

    def replaceStickerSet(self, *args, **kwargs):
        return None

    def reorderStickers(self, *args, **kwargs):
        return None

    def sortEntities(self, *args, **kwargs):
        return None

    def entitiesEqual(self, first, second, *args, **kwargs):
        return first == second

    def stringsEqual(self, first, second, *args, **kwargs):
        return str(first or "") == str(second or "")

    def substring(self, value, start, end, *args, **kwargs):
        return str(value or "")[int(start):int(end)]

    def getMask(self, value, *args, **kwargs):
        try:
            return int(value) & 0xFFFFFFFF
        except (TypeError, ValueError):
            return 0

    def getMediaType(self, message, *args, **kwargs):
        return MessagesStorage.getInstance(self.account).getMessageMediaType(message)

    def loadHints(self, *args, **kwargs):
        return None

    def loadRecents(self, *args, **kwargs):
        return None

    def fetchEmojiStatuses(self, *args, **kwargs):
        return []

    def getDefaultEmojiStatuses(self, *args, **kwargs):
        return []

    def getRecentEmojiStatuses(self, *args, **kwargs):
        return []

    def clearRecentEmojiStatuses(self, *args, **kwargs):
        return None

    def cleanup(self, *args, **kwargs):
        return None


class NotificationsController:
    @classmethod
    def getInstance(cls, account=0):
        return _NotificationsControllerInstance(account)


class _NotificationsControllerInstance:
    def __init__(self, account):
        self.account = int(account)

    def _preferences(self):
        return SharedPreferences("notifications_%s" % self.account)

    def getNotificationsSettings(self):
        settings = {}
        try:
            from client_utils import get_notifications_settings

            settings.update(get_notifications_settings(self.account) or {})
        except Exception:
            pass
        with _PREFERENCES_LOCK:
            stored = self._preferences().getAll()
        for key, value in stored.items():
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    pass
            settings[key] = value
        return settings

    def setNotificationsSettings(self, settings=None, *args, **kwargs):
        if isinstance(settings, dict):
            editor = self._preferences().edit()
            for key, value in settings.items():
                editor.putString(str(key), json.dumps(value))
            editor.apply()
        return None

    def getCurrentNotificationSettings(self, *args, **kwargs):
        return self.getNotificationsSettings()

    def isGlobalNotificationsEnabled(self, *args, **kwargs):
        return bool(self.getNotificationsSettings().get("enabled", True))

    def getNotifySettings(self, dialog_id, *args, **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        if identifier is None:
            return None
        raw = self._preferences().getString("dialog_%s" % identifier, "")
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def setDialogNotificationsSettings(self, dialog_id, settings=None, *args,
                                       **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        if identifier is None:
            return None
        if isinstance(settings, dict):
            self._preferences().edit().putString(
                "dialog_%s" % identifier, json.dumps(settings)
            ).apply()
        return None

    def getDialogNotificationsSettings(self, dialog_id, *args, **kwargs):
        return self.getNotifySettings(dialog_id)

    def cleanup(self, *args, **kwargs):
        return None

    def muteDialog(self, dialog_id, mute, *args, **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        if identifier is None:
            return None
        until = 0
        if mute:
            until = int(time.time()) + 365 * 24 * 60 * 60
        settings = {"mute_until": until}
        self.setDialogNotificationsSettings(identifier, settings)
        try:
            import extera_ios

            return extera_ios.send_request(
                self.account,
                "account.updateNotifySettings",
                {
                    "peer": int(identifier),
                    "settings": settings,
                },
            )
        except Exception:
            return None

    def muteUntil(self, dialog_id, until, *args, **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        if identifier is None:
            return None
        settings = {"mute_until": int(until or 0)}
        self.setDialogNotificationsSettings(identifier, settings)
        try:
            import extera_ios

            return extera_ios.send_request(
                self.account,
                "account.updateNotifySettings",
                {"peer": int(identifier), "settings": settings},
            )
        except Exception:
            return None

    def getTotalUnreadCount(self, *args, **kwargs):
        try:
            from org.telegram.messenger import MessagesStorage

            return MessagesStorage.getInstance(self.account).getMainUnreadCount()
        except Exception:
            return 0

    def updateBadge(self, *args, **kwargs):
        try:
            import extera_ios

            return extera_ios.host(
                "app.updateBadge", count=int(self.getTotalUnreadCount())
            )
        except Exception:
            return None

    def showNotifications(self, *args, **kwargs):
        return None

    def hideNotifications(self, *args, **kwargs):
        return None

    def setOpenedDialogId(self, dialog_id, *args, **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        self._preferences().edit().putInt(
            "opened_dialog", int(identifier or 0)
        ).apply()
        return None

    def getOpenedDialogId(self, *args, **kwargs):
        return int(self._preferences().getInt("opened_dialog", 0))

    def playOutChatSound(self, *args, **kwargs):
        return None

    def removeNotificationsForDialog(self, dialog_id, *args, **kwargs):
        data = _peer_dict(dialog_id)
        identifier = data.get("id") if data else (
            dialog_id if isinstance(dialog_id, int) else None
        )
        self._preferences().edit().remove(
            "dialog_%s" % identifier
        ).apply()
        return None

    def getNotificationsSettingsFacade(self, *args, **kwargs):
        from client_utils import get_notifications_settings

        return get_notifications_settings(self.account)

    def setGlobalNotificationsEnabled(self, value, *args, **kwargs):
        settings = self.getNotificationsSettings()
        settings["enabled"] = bool(value)
        return self.setNotificationsSettings(settings)

    def setInChatSoundEnabled(self, value, *args, **kwargs):
        settings = self.getNotificationsSettings()
        settings["in_chat_sound"] = bool(value)
        return self.setNotificationsSettings(settings)


class NotificationsSettings:
    """`org.telegram.messenger.NotificationsSettings` per-dialog settings."""

    PROPERTY_NOTIFY = "notify2_"
    PROPERTY_CUSTOM = "custom_"
    PROPERTY_NOTIFY_UNTIL = "notifyuntil_"
    PROPERTY_CONTENT_PREVIEW = "content_preview_"
    PROPERTY_SILENT = "silent_"
    PROPERTY_STORIES_NOTIFY = "stories_"

    @classmethod
    def getInstance(cls, account=0):
        return _NotificationsSettingsInstance(account)


class _NotificationsSettingsInstance:
    PROPERTY_NOTIFY = NotificationsSettings.PROPERTY_NOTIFY
    PROPERTY_CUSTOM = NotificationsSettings.PROPERTY_CUSTOM
    PROPERTY_NOTIFY_UNTIL = NotificationsSettings.PROPERTY_NOTIFY_UNTIL
    PROPERTY_CONTENT_PREVIEW = NotificationsSettings.PROPERTY_CONTENT_PREVIEW
    PROPERTY_SILENT = NotificationsSettings.PROPERTY_SILENT
    PROPERTY_STORIES_NOTIFY = NotificationsSettings.PROPERTY_STORIES_NOTIFY

    def __init__(self, account):
        self.account = int(account)

    def _preferences(self):
        return SharedPreferences("notifications_%s" % self.account)

    @staticmethod
    def _key(dialog_id, topic_id=0, *args, **kwargs):
        dialog_id = int(dialog_id or 0)
        topic_id = int(topic_id or 0)
        return "%s_%s" % (dialog_id, topic_id) if topic_id else str(dialog_id)

    def isDefault(self, dialog_id, topic_id=0, *args, **kwargs):
        key = self._key(dialog_id, topic_id)
        return not self._preferences().contains(
            "%s%s" % (self.PROPERTY_NOTIFY, key)
        )

    def clearPreference(self, dialog_id, topic_id=0, *args, **kwargs):
        key = self._key(dialog_id, topic_id)
        editor = self._preferences().edit()
        for prefix in (
            self.PROPERTY_NOTIFY,
            self.PROPERTY_CUSTOM,
            self.PROPERTY_NOTIFY_UNTIL,
            self.PROPERTY_CONTENT_PREVIEW,
            self.PROPERTY_SILENT,
            self.PROPERTY_STORIES_NOTIFY,
        ):
            editor.remove(prefix + key)
        editor.apply()
        return None

    def getProperty(self, property, dialog_id, topic_id=0, default=0, *args,
                    **kwargs):
        preferences = self._preferences()
        key = self._key(dialog_id, topic_id)
        full = property + key
        if not preferences.contains(full):
            full = property + self._key(dialog_id, 0)
            if not preferences.contains(full):
                return default
        if isinstance(default, bool):
            return preferences.getBoolean(full, default)
        if isinstance(default, int):
            return preferences.getInt(full, default)
        return preferences.getString(full, default)

    def getPropertyString(self, property, dialog_id, topic_id=0, default="",
                          *args, **kwargs):
        key = self._key(dialog_id, topic_id)
        value = self._preferences().getString(property + key, None)
        if value is None:
            value = self._preferences().getString(
                property + self._key(dialog_id, 0), None
            )
        return default if value is None else value

    def removeProperty(self, property, dialog_id, topic_id=0, *args, **kwargs):
        key = self._key(dialog_id, topic_id)
        self._preferences().edit().remove(property + key).apply()
        return None

    def applyDialogNotificationsSettings(self, dialog_id, topic_id=0,
                                         notify_settings=None, *args, **kwargs):
        data = _peer_dict(notify_settings) or {}
        key = self._key(dialog_id, topic_id)
        editor = self._preferences().edit()
        until = data.get("mute_until")
        if until is not None:
            editor.putInt(self.PROPERTY_NOTIFY_UNTIL + key, int(until))
            editor.putInt(
                self.PROPERTY_NOTIFY + key,
                0 if int(until) == 0 else 1,
            )
        if data.get("silent") is not None:
            editor.putBoolean(self.PROPERTY_SILENT + key, bool(data["silent"]))
        if data.get("preview") is not None:
            editor.putBoolean(
                self.PROPERTY_CONTENT_PREVIEW + key, bool(data["preview"])
            )
        if data.get("stories_muted") is not None:
            editor.putBoolean(
                self.PROPERTY_STORIES_NOTIFY + key,
                not bool(data["stories_muted"]),
            )
        editor.apply()
        return None

    def applySoundSettings(self, *args, **kwargs):
        return None

    def setSettingsForDialog(self, *args, **kwargs):
        return None


_STORAGE_LOCK = _threading.RLock()
_STORAGE_CACHE = {}
_STORAGE_CACHE_TTL = 30.0


def _storage_dialogs(account):
    """The dialog list as chats/users, cached for a few seconds.

    `MessagesStorage` is a local cache on Android; filling it from the dialog
    list is the closest equivalent that does not require a separate database.
    """
    now = time.time()
    with _STORAGE_LOCK:
        cached = _STORAGE_CACHE.get(account)
        if cached is not None and now - cached[0] < _STORAGE_CACHE_TTL:
            return dict(cached[1]), dict(cached[2])
    chats = {}
    users = {}
    try:
        import extera_ios

        response = extera_ios.send_request(
            account, "messages.getDialogs", {"limit": 200}, timeout=10
        )
        if isinstance(response, dict):
            for chat in response.get("chats", []) or []:
                if isinstance(chat, dict) and chat.get("id") is not None:
                    chats[int(chat["id"])] = chat
            for user in response.get("users", []) or []:
                if isinstance(user, dict) and user.get("id") is not None:
                    users[int(user["id"])] = user
    except Exception:
        pass
    try:
        users_overlay, chats_overlay = _overlay_for(account)
        chats.update(chats_overlay)
        users.update(users_overlay)
    except Exception:
        pass
    with _STORAGE_LOCK:
        _STORAGE_CACHE[account] = (now, chats, users)
    return chats, users


_MESSAGE_CACHE_LOCK = _threading.RLock()
_MESSAGE_CACHE = {}


def _message_cache_key(value):
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if not isinstance(data, dict):
        return None, None
    message_id = data.get("id") or data.get("message_id")
    dialog_id = (
        data.get("peer")
        or data.get("peer_id")
        or data.get("dialog_id")
        or data.get("dialogId")
    )
    if dialog_id is None:
        for key in ("chat", "user", "channel"):
            nested = data.get(key)
            if isinstance(nested, dict) and nested.get("id") is not None:
                dialog_id = nested.get("id")
                break
    return dialog_id, message_id


def _cache_messages(account, messages):
    with _MESSAGE_CACHE_LOCK:
        for message in messages or []:
            data = message if isinstance(message, dict) else getattr(message, "_value", None)
            if not isinstance(data, dict):
                continue
            dialog_id, message_id = _message_cache_key(data)
            if dialog_id is None or message_id is None:
                continue
            _MESSAGE_CACHE.setdefault((int(account), int(dialog_id)), {})[
                int(message_id)
            ] = data


def _cached_messages(account, dialog_id):
    with _MESSAGE_CACHE_LOCK:
        return dict(_MESSAGE_CACHE.get((int(account), int(dialog_id)), {}))


def _cached_message_count(account, dialog_id=None):
    with _MESSAGE_CACHE_LOCK:
        if dialog_id is not None:
            return len(_MESSAGE_CACHE.get((int(account), int(dialog_id)), {}))
        return sum(
            len(messages)
            for (owner, _), messages in _MESSAGE_CACHE.items()
            if owner == int(account)
        )


class MessagesStorage:
    @classmethod
    def getInstance(cls, account=0):
        return _MessagesStorageInstance(account)


class _MessagesStorageInstance:
    def __init__(self, account):
        self.account = int(account)

    def getChats(self, *args, **kwargs):
        chats, _ = _storage_dialogs(self.account)
        return chats

    def getAllChats(self, *args, **kwargs):
        return self.getChats()

    def getUsers(self, *args, **kwargs):
        _, users = _storage_dialogs(self.account)
        return users

    def putUsersAndChats(self, users, chats, *args, **kwargs):
        _put_users(self.account, users)
        _put_chats(self.account, chats)
        return None

    def putUsers(self, users, *args, **kwargs):
        _put_users(self.account, users)
        return None

    def putChats(self, chats, *args, **kwargs):
        _put_chats(self.account, chats)
        return None

    def getDialog(self, dialog_id):
        return MessagesController.getInstance(self.account).getDialog(dialog_id)

    def getDialogs(self, folder=0, *args, **kwargs):
        try:
            import extera_ios

            payload = {"limit": 200}
            folder_id = int(folder or 0)
            if folder_id:
                payload["folder_id"] = folder_id
            response = extera_ios.send_request(
                self.account, "messages.getDialogs", payload, timeout=10
            )
            if isinstance(response, dict):
                dialogs = response.get("dialogs", [])
                if isinstance(dialogs, list):
                    return dialogs
        except Exception:
            pass
        return []

    def getMessages(self, dialog_id=None, message_ids=None, *args, **kwargs):
        if dialog_id is None:
            return {}
        cached = _cached_messages(self.account, dialog_id)
        if message_ids is None:
            return cached
        result = dict(cached)
        try:
            messages = MessagesController.getInstance(self.account).getMessages(
                dialog_id, message_ids
            )
        except Exception:
            messages = []
        for message in messages or []:
            if isinstance(message, dict):
                identifier = message.get("id") or message.get("message_id")
                if identifier is not None:
                    result[int(identifier)] = message
        return result

    def getMessage(self, dialog_id, message_id):
        try:
            cached = _cached_messages(self.account, dialog_id)
        except Exception:
            cached = {}
        if int(message_id) in cached:
            return cached[int(message_id)]
        return MessagesController.getInstance(self.account).getMessage(
            dialog_id, message_id
        )

    def getUser(self, user_id):
        _, users = _storage_dialogs(self.account)
        return users.get(int(user_id))

    def getChat(self, chat_id):
        chats, _ = _storage_dialogs(self.account)
        return chats.get(int(chat_id))

    def getMessagesCount(self, dialog_id=None, *args, **kwargs):
        return _cached_message_count(self.account, dialog_id)

    def getUnreadMessagesCount(self, *args, **kwargs):
        total = 0
        try:
            import extera_ios

            response = extera_ios.send_request(
                self.account, "messages.getDialogs", {"limit": 200}, timeout=10
            )
            if isinstance(response, dict):
                for dialog in response.get("dialogs", []) or []:
                    if isinstance(dialog, dict):
                        total += int(dialog.get("unread_count") or 0)
        except Exception:
            pass
        return total

    def putMessages(self, messages, *args, **kwargs):
        _cache_messages(self.account, messages)
        return None

    def getMainUnreadCount(self, *args, **kwargs):
        return self.getUnreadMessagesCount()

    def getArchiveUnreadCount(self, *args, **kwargs):
        return 0

    def getDatabaseSize(self, *args, **kwargs):
        return 0

    def getDatabaseFiles(self, *args, **kwargs):
        return []

    def getDatabase(self, *args, **kwargs):
        return None

    def getStorageQueue(self, *args, **kwargs):
        return DispatchQueue("extera-storage")

    def readAllDialogs(self, *args, **kwargs):
        return None

    def loadUnreadMessages(self, *args, **kwargs):
        return None

    def deleteUserChatHistory(self, dialog_id, *args, **kwargs):
        return MessagesController.getInstance(self.account).deleteUserChatHistory(
            dialog_id, *args, **kwargs
        )

    def deleteDialog(self, dialog_id, only_history=0, *args, **kwargs):
        return MessagesController.getInstance(self.account).deleteDialog(
            dialog_id, only_history, *args, **kwargs
        )

    def deleteDialogFilter(self, *args, **kwargs):
        return None

    def saveDialogFilter(self, *args, **kwargs):
        return None

    def getWallpapers(self, *args, **kwargs):
        return []

    def putWallpapers(self, *args, **kwargs):
        return None

    def deleteWallpaper(self, *args, **kwargs):
        return None

    def getSavedDialogMaxMessageId(self, *args, **kwargs):
        return 0

    def reset(self, *args, **kwargs):
        with _STORAGE_LOCK:
            _STORAGE_CACHE.pop(self.account, None)
        with _MESSAGE_CACHE_LOCK:
            for key in [key for key in _MESSAGE_CACHE if key[0] == self.account]:
                _MESSAGE_CACHE.pop(key, None)
        return None

    def fullReset(self, *args, **kwargs):
        return self.reset()

    def _state_preferences(self):
        return SharedPreferences("storage_state_%s" % self.account)

    def getLastDateValue(self, *args, **kwargs):
        return int(self._state_preferences().getInt("last_date", 0))

    def setLastDateValue(self, value=0, *args, **kwargs):
        self._state_preferences().edit().putInt("last_date", int(value or 0)).apply()
        return None

    def getLastPtsValue(self, *args, **kwargs):
        return int(self._state_preferences().getInt("last_pts", 0))

    def setLastPtsValue(self, value=0, *args, **kwargs):
        self._state_preferences().edit().putInt("last_pts", int(value or 0)).apply()
        return None

    def getLastQtsValue(self, *args, **kwargs):
        return int(self._state_preferences().getInt("last_qts", 0))

    def setLastQtsValue(self, value=0, *args, **kwargs):
        self._state_preferences().edit().putInt("last_qts", int(value or 0)).apply()
        return None

    def getLastSeqValue(self, *args, **kwargs):
        return int(self._state_preferences().getInt("last_seq", 0))

    def setLastSeqValue(self, value=0, *args, **kwargs):
        self._state_preferences().edit().putInt("last_seq", int(value or 0)).apply()
        return None

    def getLastSecretVersion(self, *args, **kwargs):
        return int(self._state_preferences().getInt("secret_version", 0))

    def setLastSecretVersion(self, value=0, *args, **kwargs):
        self._state_preferences().edit().putInt(
            "secret_version", int(value or 0)
        ).apply()
        return None

    def getSecretPBytes(self, *args, **kwargs):
        import base64

        raw = self._state_preferences().getString("secret_p", "")
        return base64.b64decode(raw) if raw else b""

    def setSecretPBytes(self, value=None, *args, **kwargs):
        import base64

        if isinstance(value, (bytes, bytearray)):
            self._state_preferences().edit().putString(
                "secret_p", base64.b64encode(bytes(value)).decode("ascii")
            ).apply()
        return None

    def getSecretG(self, *args, **kwargs):
        return int(self._state_preferences().getInt("secret_g", 0))

    def setSecretG(self, value=0, *args, **kwargs):
        self._state_preferences().edit().putInt("secret_g", int(value or 0)).apply()
        return None

    def setDialogFlags(self, *args, **kwargs):
        return None

    def deleteSavedDialog(self, *args, **kwargs):
        return None

    def saveChannelPts(self, *args, **kwargs):
        return None

    def saveDiffParams(self, *args, **kwargs):
        return None

    def updateMutedDialogsFiltersCounters(self, *args, **kwargs):
        return None

    def addRecentLocalFile(self, *args, **kwargs):
        return None

    def deleteAllReactionsFromChat(self, *args, **kwargs):
        return None

    def getWidgetState(self, *args, **kwargs):
        return None

    def putWidgetStorage(self, *args, **kwargs):
        return None

    def moveWidgetState(self, *args, **kwargs):
        return None

    def putWidgetHeight(self, *args, **kwargs):
        return None

    def clearWidgetHeights(self, *args, **kwargs):
        return None

    def clearLocalDatabase(self, *args, **kwargs):
        return None

    def updateRanksInLastMessages(self, *args, **kwargs):
        return None

    def saveTopics(self, *args, **kwargs):
        return None

    def updateTopicData(self, *args, **kwargs):
        return None

    def loadTopics(self, *args, **kwargs):
        return None

    def loadGroupedMessagesForTopicUpdates(self, *args, **kwargs):
        return None

    def loadGroupedMessagesForTopics(self, *args, **kwargs):
        return None

    def removeAllTopics(self, *args, **kwargs):
        return None

    def removeTopic(self, *args, **kwargs):
        return None

    def removeTopics(self, *args, **kwargs):
        return None

    def updateTopicsWithReadMessages(self, *args, **kwargs):
        return None

    def setDialogTtl(self, *args, **kwargs):
        return None

    def checkLoadedRemoteFilters(self, *args, **kwargs):
        return None

    def saveDialogFiltersOrderInternal(self, *args, **kwargs):
        return None

    def saveDialogFiltersOrder(self, *args, **kwargs):
        return None

    def checkMessageId(self, dialog_id, message_id, *args, **kwargs):
        try:
            return int(message_id) in _cached_messages(self.account, dialog_id)
        except Exception:
            return False

    def getDialogMaxMessageId(self, dialog_id, *args, **kwargs):
        try:
            messages = _cached_messages(self.account, dialog_id)
            return max(messages) if messages else 0
        except Exception:
            return 0

    def getDialogReadMax(self, is_out, dialog_id, *args, **kwargs):
        dialog = MessagesController.getInstance(self.account).getDialog(dialog_id)
        data = _peer_dict(dialog)
        if isinstance(data, dict):
            value = data.get("read_out" if is_out else "read_inbox")
            if value is None:
                value = data.get("read_inbox_max_id" if not is_out else "read_outbox_max_id")
            if value is not None:
                return int(value)
        return 0

    def getUnreadMention(self, dialog_id, *args, **kwargs):
        return 0

    def getUnsentMessages(self, limit=100, *args, **kwargs):
        return []

    def getChatSync(self, chat_id, *args, **kwargs):
        return MessagesController.getInstance(self.account).getChat(chat_id)

    def getUserSync(self, user_id, *args, **kwargs):
        return MessagesController.getInstance(self.account).getUser(user_id)

    def getEncryptedChat(self, chat_id, *args, **kwargs):
        return None

    def getEncryptedChatsInternal(self, *args, **kwargs):
        return []

    def getDownloadQueue(self, *args, **kwargs):
        return []

    def getBotCache(self, key, *args, **kwargs):
        return SharedPreferences("botcache_%s" % self.account).getString(
            str(key), None
        )

    def getCachedMessagesInRange(self, dialog_id, *args, **kwargs):
        messages = _cached_messages(self.account, dialog_id)
        return [messages[key] for key in sorted(messages)]

    def getMessagesInternal(self, dialog_id, *args, **kwargs):
        return self.getCachedMessagesInRange(dialog_id)

    def containsLocalDialog(self, dialog_id, *args, **kwargs):
        return bool(self.getDialogMaxMessageId(dialog_id))

    def getDialogFolderId(self, dialog_id, *args, **kwargs):
        return MessagesController.getInstance(self.account).getDialogFolderId(
            dialog_id
        )

    def clearSentMedia(self, *args, **kwargs):
        return None

    def clearDownloadQueue(self, *args, **kwargs):
        return None

    def clearUserPhoto(self, *args, **kwargs):
        return None

    def clearUserPhotos(self, *args, **kwargs):
        return None

    def deleteContacts(self, *args, **kwargs):
        return None

    def deleteStoryPushMessage(self, *args, **kwargs):
        return None

    def deleteAllStoryPushMessages(self, *args, **kwargs):
        return None

    def getSmallGroupsParticipantsCount(self, chat_id, *args, **kwargs):
        chat = MessagesController.getInstance(self.account).getChat(chat_id)
        data = _peer_dict(chat)
        if isinstance(data, dict):
            participants = data.get("participants_count") or data.get("participants")
            if participants is not None:
                return int(participants)
        return 0

    def getChannelPtsSync(self, chat_id, *args, **kwargs):
        return 0

    def getMessageMediaType(self, message, *args, **kwargs):
        data = _peer_dict(message)
        if not isinstance(data, dict):
            return 0
        media = data.get("media")
        if not isinstance(media, dict):
            return 0
        return {
            "messageMediaPhoto": 1,
            "messageMediaDocument": 2,
            "messageMediaGeo": 3,
            "messageMediaContact": 4,
            "messageMediaPoll": 5,
            "messageMediaWebPage": 6,
        }.get(media.get("_"), 0)


class DownloadController:
    @classmethod
    def getInstance(cls, account=0):
        return _DownloadControllerInstance(account)


class _DownloadControllerInstance:
    def __init__(self, account):
        self.account = int(account)

    def _preferences(self):
        return SharedPreferences("download_%s" % self.account)

    def getAutoDownloadSettings(self):
        raw = self._preferences().getString("auto_download", "")
        if raw:
            try:
                value = json.loads(raw)
            except Exception:
                value = None
            if isinstance(value, dict):
                return value
        return {}

    def setAutoDownloadSettings(self, settings=None, *args, **kwargs):
        if isinstance(settings, dict):
            self._preferences().edit().putString(
                "auto_download", json.dumps(settings)
            ).apply()
        return None

    def isAutoDownloadEnabled(self):
        return bool(self._preferences().getBoolean("auto_download_enabled", True))

    def setAutoDownloadEnabled(self, value):
        self._preferences().edit().putBoolean(
            "auto_download_enabled", bool(value)
        ).apply()
        return None

    def isStreamingMediaEnabled(self):
        return True

    def setStreamingMediaEnabled(self, value):
        return None

    def getCurrentDownloadMask(self):
        return int(self._preferences().getInt("download_mask", 0xFFFFFFFF))

    def setCurrentDownloadMask(self, mask):
        self._preferences().edit().putInt(
            "download_mask", int(mask or 0)
        ).apply()
        return None

    def isDownloadingMedia(self, *args, **kwargs):
        return False

    def canDownloadMedia(self, type, size, *args, **kwargs):
        return bool(self.isAutoDownloadEnabled())

    def canDownloadMediaType(self, type, *args, **kwargs):
        return bool(self.isAutoDownloadEnabled())

    def canPreloadStories(self, *args, **kwargs):
        return False

    def isDownloading(self, *args, **kwargs):
        return False

    def checkAutodownloadSettings(self, *args, **kwargs):
        return None

    def loadAutoDownloadConfig(self, *args, **kwargs):
        return None

    def loadDownloadingFiles(self, *args, **kwargs):
        return []

    def startDownloadFile(self, *args, **kwargs):
        return None

    def addLoadingFileObserver(self, file_name, observer=None, *args, **kwargs):
        return None

    def removeLoadingFileObserver(self, observer=None, *args, **kwargs):
        return None

    def generateObserverTag(self, *args, **kwargs):
        with _MESSAGE_ID_LOCK:
            value = _NEXT_MESSAGE_ID.get(("observer", self.account), 0) + 1
            _NEXT_MESSAGE_ID[("observer", self.account)] = value
            return value

    def getCurrentWiFiPreset(self, *args, **kwargs):
        return self.getCurrentMobilePreset()

    def getCurrentMobilePreset(self, *args, **kwargs):
        settings = self.getAutoDownloadSettings()
        preset = settings.get("preset")
        return preset if isinstance(preset, dict) else settings

    def getCurrentRoamingPreset(self, *args, **kwargs):
        return self.getCurrentMobilePreset()

    def getMaxVideoBitrate(self, *args, **kwargs):
        try:
            return int(self.getAutoDownloadSettings().get("max_video_bitrate") or 0)
        except Exception:
            return 0

    def getAutodownloadMask(self, *args, **kwargs):
        return self.getCurrentDownloadMask()

    def clearRecentDownloadedFiles(self, *args, **kwargs):
        return None

    def deleteRecentFiles(self, *args, **kwargs):
        return None

    def hasUnviewedDownloads(self, *args, **kwargs):
        return False

    def clearUnviewedDownloads(self, *args, **kwargs):
        return None

    def savePresetToServer(self, *args, **kwargs):
        return None

    def updateFilesLoadingPriority(self, *args, **kwargs):
        return None

    def swapLoadingPriority(self, *args, **kwargs):
        return None

    def onDownloadComplete(self, *args, **kwargs):
        return None

    def onDownloadFail(self, *args, **kwargs):
        return None


class SecretChatHelper:
    @classmethod
    def getInstance(cls, account=0):
        return _SecretChatHelperInstance(account)


class _SecretChatHelperInstance:
    def __init__(self, account):
        self.account = int(account)

    def declineSecretChat(self, *args, **kwargs):
        return None

    def acceptSecretChat(self, *args, **kwargs):
        return None

    def startSecretChat(self, *args, **kwargs):
        return None

    def processAcceptedSecretChat(self, *args, **kwargs):
        return None

    def checkSecretChat(self, *args, **kwargs):
        return None

    def sendTTLMessage(self, chat, message, *args, **kwargs):
        return None

    def sendMessagesReadMessage(self, chat, messages, *args, **kwargs):
        return None

    def sendMessagesDeleteMessage(self, chat, messages, *args, **kwargs):
        return None

    def sendClearHistoryMessage(self, chat, *args, **kwargs):
        return None

    def sendScreenshotMessage(self, chat, message, *args, **kwargs):
        return None

    def sendNoopMessage(self, chat, *args, **kwargs):
        return None

    def sendRequestKeyMessage(self, chat, *args, **kwargs):
        return None

    def sendAcceptKeyMessage(self, chat, *args, **kwargs):
        return None

    def sendCommitKeyMessage(self, chat, *args, **kwargs):
        return None

    def sendAbortKeyMessage(self, chat, exception, *args, **kwargs):
        return None

    def sendNotifyLayerMessage(self, chat, message, *args, **kwargs):
        return None

    def requestNewSecretChatKey(self, chat, *args, **kwargs):
        return None

    def processDecryptedObject(self, chat, object_type, object_value, *args,
                               **kwargs):
        return None

    def isSecretVisibleMessage(self, message, *args, **kwargs):
        data = _peer_dict(message)
        if not isinstance(data, dict):
            return False
        return not bool(data.get("action"))


class LocationController:
    @classmethod
    def getInstance(cls, account=0):
        return _LocationControllerInstance(account)

    @staticmethod
    def countryCodeToEmoji(code, *args, **kwargs):
        value = str(code or "").strip().upper()
        if len(value) != 2 or not value.isalpha():
            return ""
        return chr(0x1F1E6 + ord(value[0]) - 65) + chr(
            0x1F1E6 + ord(value[1]) - 65
        )


class _LocationControllerInstance:
    def __init__(self, account):
        self.account = int(account)
        self._sharing = {}
        self._last_location = None

    @staticmethod
    def _peer_key(peer):
        data = _peer_dict(peer)
        if data is not None:
            return data.get("id")
        return peer if isinstance(peer, int) else None

    def isSharingLocation(self, peer=None, *args, **kwargs):
        if peer is None:
            return bool(self._sharing)
        return self._peer_key(peer) in self._sharing

    def getLastKnownLocation(self):
        return self._last_location

    def getSharingLocations(self, *args, **kwargs):
        return list(self._sharing.values())

    def isLocationVisible(self, peer, *args, **kwargs):
        return self.isSharingLocation(peer)

    def getUserLocation(self, peer, *args, **kwargs):
        return self._sharing.get(self._peer_key(peer))

    def startSharingLocation(self, peer, latitude=None, longitude=None, *args,
                             **kwargs):
        key = self._peer_key(peer)
        if key is None:
            return None
        location = {"_": "geoPoint", "lat": latitude, "long": longitude}
        self._sharing[key] = location
        self._last_location = location
        return location

    def stopSharingLocation(self, peer=None, *args, **kwargs):
        if peer is None:
            self._sharing.clear()
            return None
        self._sharing.pop(self._peer_key(peer), None)
        return None

    def getSharingLocationInfo(self, peer, *args, **kwargs):
        return self._sharing.get(self._peer_key(peer))

    def removeSharingLocation(self, peer, *args, **kwargs):
        return self.stopSharingLocation(peer)

    def removeAllLocationSharings(self, *args, **kwargs):
        self._sharing.clear()
        return None

    def getLocationsCount(self, *args, **kwargs):
        return len(self._sharing)

    def getHeading(self, *args, **kwargs):
        return 0.0

    def detectOcean(self, *args, **kwargs):
        return False

    def fetchLocationAddress(self, location=None, *args, **kwargs):
        data = _peer_dict(location) or {}
        latitude = data.get("lat", data.get("latitude"))
        longitude = data.get("long", data.get("longitude"))
        if latitude is None or longitude is None:
            return ""
        try:
            import extera_ios

            result = extera_ios.host(
                "location.address",
                latitude=float(latitude),
                longitude=float(longitude),
            )
            if isinstance(result, dict):
                return str(result.get("address") or "")
            return str(result or "")
        except Exception:
            return ""

    @staticmethod
    def countryCodeToEmoji(code, *args, **kwargs):
        value = str(code or "").strip().upper()
        if len(value) != 2 or not value.isalpha():
            return ""
        return chr(0x1F1E6 + ord(value[0]) - 65) + chr(
            0x1F1E6 + ord(value[1]) - 65
        )

    def markLiveLoactionsAsRead(self, *args, **kwargs):
        return None

    def loadLiveLocations(self, *args, **kwargs):
        return None

    def setMapLocation(self, *args, **kwargs):
        return None

    def setProximityLocation(self, *args, **kwargs):
        return None

    def startFusedLocationRequest(self, *args, **kwargs):
        return None


class SendMessageParams:
    """Android's `SendMessageParams`, with the fields plugins set most often."""

    def __init__(self):
        self.dialogId = 0
        self.peer = 0
        self.message = None
        self.entities = None
        self.caption = None
        self.captionEntities = None
        self.reply_to_msg_id = 0
        self.scheduleDate = 0
        self.silent = False
        self.notify = True
        self.params = None
        self.photo = None
        self.document = None
        self.path = None
        self.location = None
        self.videoEditedInfo = None
        self.user = None
        self.game = None
        self.poll = None
        self.pollSendParams = None
        self.pollIndex = 0
        self.todo = None
        self.invoice = None
        self.mediaWebPage = None
        self.cover = None
        self.replyToTopMsg = 0
        self.webPage = None
        self.retryMessageObject = None
        self.replyMarkup = None
        self.searchLinks = True
        self.updateStickersOrder = False
        self.hasMediaSpoilers = False
        self.invert_media = False
        self.sendingHighQuality = False
        self.scheduleRepeatPeriod = 0
        self.ttl = 0
        self.effect_id = 0
        self.stars = 0
        self.payStars = 0
        self.dice_stake = 0
        self.monoForumPeer = 0
        self.quick_reply_shortcut_id = 0
        self.quick_reply_shortcut = None
        self.parentObject = None
        self.sendAnimationData = None
        self.replyToStoryItem = None
        self.sendingStory = None
        self.replyQuote = None
        self.suggestionParams = None
        self.isLivePhoto = False
        self.livePhotoTimestamp = 0
        self.ephemeralReceiverBotId = 0
        self.richMessage = None
        self.richMessageInputUsers = None


class SendMessagesHelper:
    SendMessageParams = SendMessageParams

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.messenger.SendMessagesHelper")

    @classmethod
    def getInstance(cls, account=0):
        return _SendMessagesHelperInstance(account)


class _SendMessagesHelperInstance:
    def __init__(self, account):
        self.account = int(account)

    def sendMessage(self, params):
        try:
            from client_utils import send_message

            if isinstance(params, dict):
                return send_message(params, account=self.account)
            values = getattr(params, "__dict__", None)
            if not isinstance(values, dict):
                values = {}
            payload = {
                key: value for key, value in values.items() if value is not None
            }
            dialog_id = values.get("dialogId") or values.get("peer") or 0
            payload["peer"] = int(dialog_id or 0)
            message = values.get("message")
            if isinstance(message, str):
                text = message
            elif isinstance(message, dict):
                text = message.get("message") or message.get("text")
            else:
                text = getattr(message, "message", None) if message is not None else None
            entities = values.get("entities")
            if not entities and message is not None:
                entities = getattr(message, "entities", None)
            payload["message"] = text
            payload["entities"] = entities
            reply = (
                values.get("replyToMsg")
                or values.get("reply_to_msg_id")
                or values.get("replyToTopMsg")
            )
            if reply is not None:
                payload["replyToMsg"] = reply
            has_media = any(
                payload.get(key) is not None
                for key in (
                    "path",
                    "photo",
                    "document",
                    "videoEditedInfo",
                    "location",
                    "poll",
                    "pollSendParams",
                    "todo",
                    "invoice",
                    "mediaWebPage",
                    "cover",
                    "user",
                    "game",
                    "webPage",
                )
            )
            if payload.get("message") is None and payload.get("caption") is None and not has_media:
                return None
            return send_message(payload, account=self.account)
        except Exception:
            pass
        return None

    def sendLocation(self, peer, latitude=None, longitude=None, *args, **kwargs):
        from client_utils import send_location

        return send_location(peer, latitude, longitude, account=self.account, **kwargs)

    def sendContact(self, peer, phone_number=None, first_name="", last_name="",
                    *args, **kwargs):
        from client_utils import send_contact

        return send_contact(
            peer, phone_number, first_name, last_name, account=self.account, **kwargs
        )

    def sendSticker(self, document, query="", peer=0, *args, **kwargs):
        from client_utils import send_sticker

        return send_sticker(peer, document, query, account=self.account, **kwargs)

    @staticmethod
    def _message_peer_id(message):
        data = _peer_dict(message)
        if isinstance(data, dict):
            peer = (
                data.get("peer")
                or data.get("peer_id")
                or data.get("dialog_id")
                or data.get("dialogId")
            )
            if peer is not None:
                return int(peer)
            for key in ("chat", "user", "channel"):
                nested = data.get(key)
                if isinstance(nested, dict) and nested.get("id") is not None:
                    return int(nested["id"])
        return message if isinstance(message, int) else None

    @staticmethod
    def _message_id(message):
        data = _peer_dict(message)
        if isinstance(data, dict):
            value = data.get("id") or data.get("message_id")
            if value is not None:
                return int(value)
        return None

    @staticmethod
    def _callback_data(value):
        if isinstance(value, (bytes, bytearray)):
            import base64

            return base64.b64encode(bytes(value)).decode("ascii")
        if isinstance(value, str):
            return value
        data = value if isinstance(value, dict) else getattr(value, "_value", None)
        if isinstance(data, dict):
            raw = data.get("data") or data.get("callback_data")
            if isinstance(raw, (bytes, bytearray)):
                import base64

                return base64.b64encode(bytes(raw)).decode("ascii")
            if isinstance(raw, str):
                return raw
        return ""

    def sendVote(self, first=None, second=None, third=None, *args, **kwargs):
        # `sendVote(message, answers, finishRunnable)` (Android) and
        # `sendVote(peer, message_id, options)` (iOS helper) both work.
        if isinstance(first, dict) or hasattr(first, "messageOwner"):
            if isinstance(second, (list, tuple)) or second is None:
                peer_id = self._message_peer_id(first)
                message_id = self._message_id(first)
                options = second
            else:
                peer_id = first.get("id") if isinstance(first, dict) else first
                message_id = second
                options = third
        else:
            peer_id = first.get("id") if isinstance(first, dict) else first
            message_id = second
            options = third
        if peer_id is None or message_id is None:
            return None
        values = []
        for option in options or []:
            raw = option
            if isinstance(option, dict):
                raw = (
                    option.get("option")
                    or option.get("data")
                    or option.get("option_bytes")
                )
            elif hasattr(option, "_value"):
                raw = getattr(option, "option", None) or getattr(option, "_value", None)
            if isinstance(raw, (bytes, bytearray)):
                import base64

                values.append(base64.b64encode(bytes(raw)).decode("ascii"))
            elif isinstance(raw, str):
                values.append(raw)
            elif raw is not None:
                values.append(str(raw))
        try:
            import extera_ios

            return extera_ios.send_request(
                self.account,
                "messages.sendVote",
                {
                    "peer": int(peer_id),
                    "msg_id": int(message_id),
                    "options": values,
                },
            )
        except Exception:
            return None

    def sendCallback(self, first=None, second=None, third=None, *args, **kwargs):
        # Android: `sendCallback(cache, messageObject, button, ...)`.
        # iOS helper: `sendCallback(peer, message_id, data)`.
        if isinstance(first, bool):
            peer_id = self._message_peer_id(second)
            message_id = self._message_id(second)
            data = self._callback_data(third)
        elif isinstance(first, dict) and (isinstance(second, dict) or second is None):
            peer_id = self._message_peer_id(first)
            message_id = self._message_id(first)
            data = self._callback_data(second)
        else:
            peer_id = first.get("id") if isinstance(first, dict) else first
            message_id = second
            data = self._callback_data(third)
        if peer_id is None:
            return None
        payload = {"peer": int(peer_id), "msg_id": int(message_id or 0)}
        if data:
            payload["data"] = data
        try:
            import extera_ios

            return extera_ios.send_request(
                self.account, "messages.getBotCallbackAnswer", payload
            )
        except Exception:
            return None

    def sendReaction(self, message, reactions=None, added_reaction=None, big=False,
                     add_to_recent=False, *args, **kwargs):
        peer_id = self._message_peer_id(message)
        message_id = self._message_id(message)
        if peer_id is None or message_id is None:
            return None

        def reaction_text(value):
            if isinstance(value, str):
                return value
            data = value if isinstance(value, dict) else getattr(value, "_value", None)
            if isinstance(data, dict):
                text = (
                    data.get("reaction")
                    or data.get("emoticon")
                    or data.get("document_id")
                )
                if text is not None:
                    return str(text)
            text = getattr(value, "reaction", None) or getattr(value, "emoticon", None)
            return str(text) if text is not None else None

        values = []
        for value in reactions or []:
            text = reaction_text(value)
            if text and text not in values:
                values.append(text)
        if added_reaction is not None:
            text = reaction_text(added_reaction)
            if text and text not in values:
                values.append(text)
        try:
            import extera_ios

            return extera_ios.send_request(
                self.account,
                "messages.sendReaction",
                {
                    "peer": int(peer_id),
                    "msg_id": int(message_id),
                    "reaction": values,
                    "big": bool(big),
                    "recent": bool(add_to_recent),
                },
            )
        except Exception:
            return None

    def sendCurrentLocation(self, message, button=None, *args, **kwargs):
        peer_id = self._message_peer_id(message)
        if peer_id is None:
            return None
        try:
            from org.telegram.messenger import LocationController

            location = LocationController.getInstance(
                self.account
            ).getLastKnownLocation()
        except Exception:
            location = None
        if not isinstance(location, dict):
            return None
        latitude = location.get("lat", location.get("latitude"))
        longitude = location.get("long", location.get("longitude"))
        if latitude is None or longitude is None:
            return None
        from client_utils import send_location

        return send_location(peer_id, latitude, longitude, account=self.account)

    # -- lifecycle helpers from `SendMessagesHelper` -----------------------
    def cancelSendingMessage(self, message, *args, **kwargs):
        return None

    def deleteSendingMessage(self, message, *args, **kwargs):
        return None

    def isSendingMessage(self, random_id, *args, **kwargs):
        return False

    def isSendingMessageIdDialog(self, message_id, *args, **kwargs):
        return False

    def isUploadingMessageIdDialog(self, message_id, *args, **kwargs):
        return False

    def isSendingCallback(self, *args, **kwargs):
        return False

    def isSendingVote(self, *args, **kwargs):
        return False

    def isSendingCurrentLocation(self, *args, **kwargs):
        return False

    def getSendingMessageId(self, *args, **kwargs):
        return None

    def canSendMessageToChat(self, chat, *args, **kwargs):
        try:
            from org.telegram.messenger import ChatObject

            return bool(ChatObject.canSendMessage(chat))
        except Exception:
            return True

    def editMessage(self, message, text=None, *args, **kwargs):
        from client_utils import edit_message

        return edit_message(message, text, account=self.account, **kwargs)

    def prepareSendingText(self, text, dialog_id=None, *args, **kwargs):
        from client_utils import send_text

        peer = dialog_id
        if peer is None:
            peer = args[0] if args else 0
        return send_text(peer, text, account=self.account)

    def prepareSendingDocument(self, path, dialog_id=None, *args, **kwargs):
        from client_utils import send_document

        peer = dialog_id
        if peer is None:
            peer = args[0] if args else 0
        caption = kwargs.get("caption", "")
        return send_document(peer, path, caption, account=self.account)

    def prepareSendingPhoto(self, path, dialog_id=None, *args, **kwargs):
        from client_utils import send_photo

        peer = dialog_id
        if peer is None:
            peer = args[0] if args else 0
        caption = kwargs.get("caption", "")
        return send_photo(peer, path, caption, account=self.account)

    def prepareSendingVideo(self, path, dialog_id=None, *args, **kwargs):
        from client_utils import send_video

        peer = dialog_id
        if peer is None:
            peer = args[0] if args else 0
        caption = kwargs.get("caption", "")
        return send_video(peer, path, caption, account=self.account)

    def prepareSendingAudioDocuments(self, paths, dialog_id=None, *args, **kwargs):
        from client_utils import send_audio

        peer = dialog_id
        if peer is None:
            peer = args[0] if args else 0
        results = []
        for path in paths or []:
            results.append(send_audio(peer, path, account=self.account))
        return results

    def prepareSendingDocuments(self, paths, dialog_id=None, *args, **kwargs):
        from client_utils import send_document

        peer = dialog_id
        if peer is None:
            peer = args[0] if args else 0
        results = []
        for path in paths or []:
            results.append(send_document(peer, path, account=self.account))
        return results

    def prepareSendingMedia(self, medias, dialog_id=None, *args, **kwargs):
        from client_utils import send_audio, send_document, send_photo, send_video

        peer = dialog_id
        if peer is None:
            peer = args[0] if args else 0
        results = []
        for media in medias or []:
            path = _location_path(media)
            if not path:
                continue
            extension = os.path.splitext(path)[1].lower()
            if extension in (".jpg", ".jpeg", ".png", ".heic", ".webp"):
                results.append(send_photo(peer, path, account=self.account))
            elif extension in (".mp4", ".mov", ".mkv", ".webm"):
                results.append(send_video(peer, path, account=self.account))
            elif extension in (".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav"):
                results.append(send_audio(peer, path, account=self.account))
            else:
                results.append(send_document(peer, path, account=self.account))
        return results

    def prepareSendingPoll(self, poll_send_params, dialog_id=None, *args,
                           **kwargs):
        from client_utils import send_poll

        peer = dialog_id
        if peer is None:
            peer = args[0] if args else 0
        caption = ""
        entities = None
        if isinstance(poll_send_params, dict):
            poll = (
                poll_send_params.get("inputMediaPoll")
                or poll_send_params.get("poll")
                or poll_send_params
            )
            caption = poll_send_params.get("caption") or ""
            entities = poll_send_params.get("entities")
        else:
            poll = getattr(poll_send_params, "inputMediaPoll", None) or getattr(
                poll_send_params, "poll", None
            )
            caption = getattr(poll_send_params, "caption", "") or ""
            entities = getattr(poll_send_params, "entities", None)
        return send_poll(
            peer,
            poll,
            caption,
            account=self.account,
            entities=entities,
        )

    def _edit_poll(self, message, poll):
        peer = self._message_peer_id(message)
        message_id = self._message_id(message)
        if peer is None or message_id is None:
            return None
        try:
            import extera_ios

            return extera_ios.send_request(
                self.account,
                "messages.editMessage",
                {
                    "peer": int(peer),
                    "id": int(message_id),
                    "message": "",
                    "media": {"_": "inputMediaPoll", "poll": poll},
                },
            )
        except Exception:
            return None

    def addPollOption(self, message, caption, attached_media=None, *args,
                      **kwargs):
        data = _peer_dict(message)
        media = data.get("media") if isinstance(data, dict) else None
        if not isinstance(media, dict) or media.get("_") != "messageMediaPoll":
            return None
        poll = dict(media.get("poll") or {})
        answers = list(poll.get("answers") or [])
        text = caption if isinstance(caption, str) else getattr(
            caption, "text", None
        )
        answers.append({"text": str(text or ""), "option": ""})
        poll["answers"] = answers
        return self._edit_poll(message, poll)

    def deletePollOption(self, message, option, *args, **kwargs):
        data = _peer_dict(message)
        media = data.get("media") if isinstance(data, dict) else None
        if not isinstance(media, dict) or media.get("_") != "messageMediaPoll":
            return None
        poll = dict(media.get("poll") or {})
        answers = list(poll.get("answers") or [])
        target = option
        if isinstance(option, (bytes, bytearray)):
            import base64

            target = base64.b64encode(bytes(option)).decode("ascii")
        filtered = []
        for answer in answers:
            item = answer if isinstance(answer, dict) else getattr(
                answer, "_value", None
            )
            if not isinstance(item, dict):
                filtered.append(answer)
                continue
            value = item.get("option")
            if isinstance(value, (bytes, bytearray)):
                import base64

                value = base64.b64encode(bytes(value)).decode("ascii")
            if value != target:
                filtered.append(item)
        poll["answers"] = filtered
        return self._edit_poll(message, poll)

    def getNextRandomId(self, *args, **kwargs):
        with _MESSAGE_ID_LOCK:
            value = _NEXT_MESSAGE_ID.get(("random", self.account), 0) + 1
            _NEXT_MESSAGE_ID[("random", self.account)] = value
            return value


def _location_path(value):
    """Finds a local path in a photo/document/location dictionary."""
    if isinstance(value, str):
        return value
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if not isinstance(data, dict):
        document = getattr(value, "document", None)
        data = document if isinstance(document, dict) else None
    if isinstance(data, dict):
        for key in ("path", "file_name"):
            item = data.get(key)
            if isinstance(item, str) and item:
                return item
        document = data.get("document")
        if isinstance(document, dict):
            for key in ("path", "file_name"):
                item = document.get(key)
                if isinstance(item, str) and item:
                    return item
    return ""


class ImageLocation:
    def __init__(self, path="", photo=None, document=None, object=None):
        self.path = path
        self.photo = photo
        self.document = document
        self.object = object

    @classmethod
    def getForPath(cls, path):
        return cls(path=path)

    @classmethod
    def getForPhoto(cls, photo_size=None, photo=None, *args, **kwargs):
        return cls(photo=photo or photo_size, object=photo_size, path=_location_path(photo_size))

    @classmethod
    def getForDocument(cls, document=None, photo_size=None, *args, **kwargs):
        return cls(document=document, object=document or photo_size, path=_location_path(document))

    @classmethod
    def getForObject(cls, obj=None, *args, **kwargs):
        return cls(object=obj, path=_location_path(obj))

    def getPath(self):
        return self.path or ""

    def __str__(self):
        return self.getPath()


_DOWNLOAD_LOCK = _threading.RLock()
_DOWNLOADING = {}


class JSONException(Exception):
    pass


class _JSONNull:
    def __repr__(self):
        return "null"

    def __bool__(self):
        return False

    def __str__(self):
        return "null"


JSON_NULL = _JSONNull()


def _json_value(value):
    if value is JSON_NULL or value is None:
        return None
    if isinstance(value, JSONObject):
        return value.toMap()
    if isinstance(value, JSONArray):
        return value.toList()
    return value


class JSONObject(dict):
    NULL = JSON_NULL

    def __init__(self, source=None):
        super().__init__()
        if source is None:
            return
        if isinstance(source, str):
            try:
                data = json.loads(source)
            except Exception as error:
                raise JSONException(str(error))
            if isinstance(data, dict):
                self.update(data)
            return
        if isinstance(source, dict):
            self.update(source)
            return
        raise JSONException("unsupported JSONObject source")

    def put(self, key, value=None):
        self[str(key)] = _json_value(value)
        return self

    def get(self, key, *args):
        if str(key) in self:
            return dict.__getitem__(self, str(key))
        if args:
            return args[0]
        raise JSONException("No value for %s" % key)

    def opt(self, key, default=None):
        return dict.get(self, str(key), default)

    def has(self, key):
        return str(key) in self

    def isNull(self, key):
        return dict.get(self, str(key)) is None

    def remove(self, key):
        return dict.pop(self, str(key), None)

    def keys(self):
        return iter(dict.keys(self))

    def keySet(self):
        return set(dict.keys(self))

    def names(self):
        return list(dict.keys(self))

    def length(self):
        return len(self)

    def getString(self, key, *args):
        value = self.get(key, *args)
        return "" if value is None else str(value)

    def optString(self, key, default=""):
        value = dict.get(self, str(key))
        return default if value is None else str(value)

    def getInt(self, key, *args):
        return int(self.get(key, *args))

    def optInt(self, key, default=0):
        try:
            return int(dict.get(self, str(key), default))
        except (TypeError, ValueError):
            return default

    def getLong(self, key, *args):
        return int(self.get(key, *args))

    def optLong(self, key, default=0):
        return self.optInt(key, default)

    def getDouble(self, key, *args):
        return float(self.get(key, *args))

    def optDouble(self, key, default=0.0):
        try:
            return float(dict.get(self, str(key), default))
        except (TypeError, ValueError):
            return default

    def getBoolean(self, key, *args):
        return bool(self.get(key, *args))

    def optBoolean(self, key, default=False):
        return bool(dict.get(self, str(key), default))

    def getJSONObject(self, key, *args):
        value = self.get(key, *args)
        if isinstance(value, JSONObject):
            return value
        if isinstance(value, dict):
            return JSONObject(value)
        if isinstance(value, str):
            return JSONObject(value)
        raise JSONException("not a JSONObject")

    def optJSONObject(self, key):
        try:
            return self.getJSONObject(key)
        except Exception:
            return None

    def getJSONArray(self, key, *args):
        value = self.get(key, *args)
        if isinstance(value, JSONArray):
            return value
        if isinstance(value, list):
            return JSONArray(value)
        if isinstance(value, str):
            return JSONArray(value)
        raise JSONException("not a JSONArray")

    def optJSONArray(self, key):
        try:
            return self.getJSONArray(key)
        except Exception:
            return None

    def toMap(self):
        return {key: value for key, value in dict.items(self)}

    def toString(self, indent=None):
        return json.dumps(
            self.toMap(),
            ensure_ascii=False,
            indent=indent,
            separators=(",", ":") if indent is None else None,
        )

    def __str__(self):
        return self.toString()


class JSONArray(list):
    def __init__(self, source=None):
        super().__init__()
        if source is None:
            return
        if isinstance(source, str):
            try:
                data = json.loads(source)
            except Exception as error:
                raise JSONException(str(error))
            if isinstance(data, list):
                self.extend(data)
            return
        if isinstance(source, (list, tuple, JSONArray)):
            self.extend(source)

    def put(self, value=None):
        self.append(_json_value(value))
        return self

    def get(self, index, *args):
        try:
            return list.__getitem__(self, int(index))
        except Exception:
            if args:
                return args[0]
            raise JSONException("index out of range")

    def opt(self, index, default=None):
        try:
            return self.get(index)
        except Exception:
            return default

    def length(self):
        return len(self)

    def remove(self, index):
        try:
            return list.pop(self, int(index))
        except Exception:
            return None

    def getString(self, index, *args):
        value = self.get(index, *args)
        return "" if value is None else str(value)

    def optString(self, index, default=""):
        value = self.opt(index)
        return default if value is None else str(value)

    def getInt(self, index, *args):
        return int(self.get(index, *args))

    def optInt(self, index, default=0):
        try:
            return int(self.opt(index, default))
        except (TypeError, ValueError):
            return default

    def getLong(self, index, *args):
        return int(self.get(index, *args))

    def optLong(self, index, default=0):
        return self.optInt(index, default)

    def getDouble(self, index, *args):
        return float(self.get(index, *args))

    def optDouble(self, index, default=0.0):
        try:
            return float(self.opt(index, default))
        except (TypeError, ValueError):
            return default

    def getBoolean(self, index, *args):
        return bool(self.get(index, *args))

    def optBoolean(self, index, default=False):
        return bool(self.opt(index, default))

    def getJSONObject(self, index, *args):
        value = self.get(index, *args)
        if isinstance(value, JSONObject):
            return value
        if isinstance(value, dict):
            return JSONObject(value)
        if isinstance(value, str):
            return JSONObject(value)
        raise JSONException("not a JSONObject")

    def optJSONObject(self, index):
        try:
            return self.getJSONObject(index)
        except Exception:
            return None

    def getJSONArray(self, index, *args):
        value = self.get(index, *args)
        if isinstance(value, JSONArray):
            return value
        if isinstance(value, list):
            return JSONArray(value)
        if isinstance(value, str):
            return JSONArray(value)
        raise JSONException("not a JSONArray")

    def optJSONArray(self, index):
        try:
            return self.getJSONArray(index)
        except Exception:
            return None

    def toList(self):
        return list(self)

    def toString(self, indent=None):
        return json.dumps(
            self.toList(),
            ensure_ascii=False,
            indent=indent,
            separators=(",", ":") if indent is None else None,
        )

    def __str__(self):
        return self.toString()


class _TolerantClassMeta(type):
    """A Java class answers an unmapped static member instead of raising."""

    def __getattr__(cls, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if (
            name[:2] == "is"
            or name[:3] == "can"
            or name[:3] == "has"
            or name[:6] == "should"
            or name[:4] == "need"
        ):
            return lambda *args, **kwargs: False
        return lambda *args, **kwargs: None


class FileLoader(metaclass=_TolerantClassMeta):
    MEDIA_DIR_IMAGE = 0
    MEDIA_DIR_AUDIO = 1
    MEDIA_DIR_VIDEO = 2
    MEDIA_DIR_DOCUMENTS = 3
    MEDIA_DIR_DOCUMENT = 3
    MEDIA_DIR_CACHE = 4
    MEDIA_DIR_FILES = 5
    MEDIA_DIR_DATABASE = 6
    MEDIA_DIR_EMOJI = 7
    MEDIA_DIR_WALLPAPERS = 8
    MEDIA_DIR_IMAGE_PUBLIC = 100
    MEDIA_DIR_VIDEO_PUBLIC = 101

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.messenger.FileLoader")

    _DIRECTORIES = {
        0: "images",
        1: "audios",
        2: "videos",
        3: "documents",
        4: "cache",
        5: "files",
        6: "database",
        7: "emoji",
        8: "wallpapers",
        100: "images",
        101: "videos",
    }

    @classmethod
    def getDirectory(cls, kind):
        from extera_utils.classes import NativeFile

        if isinstance(kind, int):
            kind = cls._DIRECTORIES.get(kind, "files")
        return NativeFile(_path_for(kind or "files"))

    @classmethod
    def getPathToAttach(cls, media, *args, **kwargs):
        from extera_utils.classes import NativeFile

        def as_dict(value):
            if isinstance(value, dict):
                return value
            inner = getattr(value, "_value", None)
            return inner if isinstance(inner, dict) else None

        def resolve(value):
            data = as_dict(value)
            if data is None:
                return None
            kind = data.get("_")
            if kind == "messageMediaPhoto":
                nested = data.get("photo")
                if isinstance(nested, dict):
                    identifier = nested.get("id")
                    if identifier is not None:
                        file_name = nested.get("file_name") or ("photo_%s.jpg" % identifier)
                        return os.path.join(_path_for("cache"), file_name)
                return None
            if kind in ("messageMediaDocument", "messageMediaFile"):
                nested = data.get("document")
                if nested is not None:
                    return resolve(nested)
            path = data.get("path")
            if isinstance(path, str) and path:
                return path
            nested = data.get("document")
            if nested is not None:
                return resolve(nested)
            nested = data.get("photo")
            if isinstance(nested, dict):
                identifier = nested.get("id")
                if identifier is not None:
                    file_name = nested.get("file_name") or ("photo_%s.jpg" % identifier)
                    return os.path.join(_path_for("cache"), file_name)
            if kind == "photo" and data.get("id") is not None:
                return os.path.join(_path_for("cache"), "photo_%s.jpg" % data.get("id"))
            file_name = data.get("file_name")
            if isinstance(file_name, str) and file_name:
                return os.path.join(_path_for("cache"), file_name)
            if data.get("id") is not None:
                return os.path.join(_path_for("cache"), "doc_%s" % data.get("id"))
            return None

        data = as_dict(media)
        if data is not None:
            path = data.get("path")
            if isinstance(path, str) and path:
                return NativeFile(path)
            for key in ("media", "messageOwner"):
                nested = data.get(key)
                if nested is not None:
                    resolved = resolve(nested)
                    if resolved:
                        return NativeFile(resolved)
            resolved = resolve(data)
            if resolved:
                return NativeFile(resolved)
        return cls.getDirectory(cls.MEDIA_DIR_CACHE)

    @classmethod
    def getPathToMessage(cls, message, *args, **kwargs):
        return cls.getPathToAttach(message, *args, **kwargs)

    @classmethod
    def getInstance(cls, account=0):
        # Android returns an account-scoped loader; all state this port keeps is
        # static, so the class itself is a valid instance.
        return cls

    @classmethod
    def getAttachFileName(cls, media, ext=None):
        data = media if isinstance(media, dict) else getattr(media, "_value", None)
        name = ""
        if isinstance(data, dict):
            for key in ("file_name", "name", "path"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    name = os.path.basename(value)
                    break
            if not name:
                document = data.get("document")
                if isinstance(document, dict):
                    value = document.get("file_name") or document.get("name")
                    if isinstance(value, str) and value:
                        name = os.path.basename(value)
            if not name:
                photo = data.get("photo")
                if isinstance(photo, dict):
                    identifier = photo.get("id")
                    if identifier is not None:
                        name = photo.get("file_name") or ("photo_%s.jpg" % identifier)
                elif data.get("_") == "photo" and data.get("id") is not None:
                    name = data.get("file_name") or ("photo_%s.jpg" % data.get("id"))
        if name:
            if ext and not name.lower().endswith("." + str(ext).lower()):
                return name + "." + str(ext)
            return name
        identifier = data.get("id") if isinstance(data, dict) else None
        if identifier is not None:
            return "file_%s%s" % (identifier, ("." + str(ext)) if ext else "")
        return ""

    @classmethod
    def loadFile(cls, media, parent=None, priority=0, cacheOnly=False):
        """Downloads a document into the plugin cache through the host.

        Android's `FileLoader.loadFile` is asynchronous and delivers progress
        through notification callbacks; this port starts the same download on a
        background thread, and `getFileProgress`/`isLoadingFile` read its state.
        """
        data = media if isinstance(media, dict) else getattr(media, "_value", None)
        if not isinstance(data, dict):
            return None
        kind = data.get("_")
        download_kind = "document"
        thumb_size = ""
        if kind == "messageMediaPhoto":
            photo = data.get("photo")
            if not isinstance(photo, dict):
                return None
            document = photo
            identifier = photo.get("id")
            if identifier is None:
                return None
            try:
                identifier = int(identifier)
            except (TypeError, ValueError):
                return None
            file_name = photo.get("file_name") or ("photo_%s.jpg" % identifier)
            download_kind = "photo"
            thumb_size = "x"
            best_weight = -1
            size = 0
            for item in photo.get("sizes") or []:
                if not isinstance(item, dict):
                    continue
                weight = int(item.get("size") or 0)
                if weight <= 0:
                    weight = int(item.get("w") or 0) * int(item.get("h") or 0)
                if weight > best_weight:
                    best_weight = weight
                    thumb_size = item.get("type") or "x"
                    if item.get("size"):
                        size = int(item.get("size") or 0)
        else:
            document = data
            if kind in ("messageMediaDocument", "messageMediaFile"):
                nested = data.get("document")
                if isinstance(nested, dict):
                    document = nested
            identifier = document.get("id")
            if identifier is None:
                return None
            try:
                identifier = int(identifier)
            except (TypeError, ValueError):
                return None
            file_name = document.get("file_name") or ("doc_%s" % identifier)
            size = document.get("size") or 0
        path = os.path.join(_path_for("cache"), file_name)
        from extera_utils.classes import NativeFile

        if os.path.exists(path):
            return NativeFile(path)
        if cacheOnly:
            return None
        key = (identifier, file_name)
        with _DOWNLOAD_LOCK:
            if key in _DOWNLOADING:
                return None
            _DOWNLOADING[key] = 0.0
        try:
            access_hash = int(document.get("access_hash") or 0)
        except (TypeError, ValueError):
            access_hash = 0
        try:
            size = int(size or 0)
        except (TypeError, ValueError):
            size = 0
        reference = document.get("file_reference")
        if not isinstance(reference, str):
            reference = ""

        def worker():
            try:
                import extera_ios

                result = extera_ios.host(
                    "client.download",
                    account=_current_account(),
                    id=identifier,
                    access_hash=access_hash,
                    file_reference=reference,
                    file_name=file_name,
                    size=size,
                    kind=download_kind,
                    thumb_size=thumb_size,
                )
                with _DOWNLOAD_LOCK:
                    if isinstance(result, dict) and result.get("path"):
                        _DOWNLOADING[key] = 1.0
                    else:
                        _DOWNLOADING.pop(key, None)
            except Exception:
                with _DOWNLOAD_LOCK:
                    _DOWNLOADING.pop(key, None)

        _threading.Thread(target=worker, daemon=True).start()
        return None

    @classmethod
    def isLoadingFile(cls, file_name):
        with _DOWNLOAD_LOCK:
            return any(name == file_name for _, name in _DOWNLOADING)

    @classmethod
    def cancelLoadingFile(cls, file_name):
        with _DOWNLOAD_LOCK:
            for key in [key for key in _DOWNLOADING if key[1] == file_name]:
                _DOWNLOADING.pop(key, None)
        return None

    @classmethod
    def getFileProgress(cls, file_name):
        with _DOWNLOAD_LOCK:
            values = [
                value for (_, name), value in _DOWNLOADING.items()
                if name == file_name
            ]
        if values:
            return 1.0 if max(values) >= 1.0 else 0.0
        path = os.path.join(_path_for("cache"), file_name)
        return 1.0 if os.path.exists(path) else 0.0

    @classmethod
    def getFileDir(cls, file_name):
        return "cache"

    @classmethod
    def getFileReference(cls, *args, **kwargs):
        def extract(value):
            data = value if isinstance(value, dict) else getattr(value, "_value", None)
            if not isinstance(data, dict):
                return None
            reference = data.get("file_reference")
            if isinstance(reference, (bytes, bytearray)):
                return bytes(reference)
            if isinstance(reference, str) and reference:
                return reference
            for key in ("document", "photo"):
                nested = data.get(key)
                if isinstance(nested, dict):
                    found = extract(nested)
                    if found:
                        return found
            return None

        for value in args:
            found = extract(value)
            if found:
                return found
        return ""

    @classmethod
    def isFileLoading(cls, file_name, *args, **kwargs):
        return cls.isLoadingFile(file_name)

    @classmethod
    def getFileLoadingPriority(cls, *args, **kwargs):
        return 0

    @classmethod
    def getLocalFile(cls, path, *args, **kwargs):
        from extera_utils.classes import NativeFile

        return NativeFile(str(path))

    @classmethod
    def getInternalCacheDir(cls, *args, **kwargs):
        return cls.getDirectory(cls.MEDIA_DIR_CACHE)

    @classmethod
    def getMessageFileName(cls, message, *args, **kwargs):
        return cls.getAttachFileName(message)

    @classmethod
    def getDocumentFileName(cls, document, *args, **kwargs):
        data = document if isinstance(document, dict) else getattr(
            document, "_value", None
        )
        if not isinstance(data, dict):
            return ""
        name = data.get("file_name") or data.get("name")
        if isinstance(name, str) and name:
            return os.path.basename(name)
        attributes = data.get("attributes")
        if isinstance(attributes, list):
            for attribute in attributes:
                if not isinstance(attribute, dict):
                    continue
                name = attribute.get("file_name")
                if isinstance(name, str) and name:
                    return os.path.basename(name)
        return ""

    @classmethod
    def getDocumentExtension(cls, document, *args, **kwargs):
        name = cls.getDocumentFileName(document)
        extension = os.path.splitext(name)[1]
        return extension[1:].lower() if extension else ""

    @classmethod
    def getExtensionByMimeType(cls, mime_type, *args, **kwargs):
        mapping = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/gif": "gif",
            "image/webp": "webp",
            "video/mp4": "mp4",
            "video/quicktime": "mov",
            "audio/mpeg": "mp3",
            "audio/ogg": "ogg",
            "audio/opus": "opus",
            "audio/flac": "flac",
            "audio/wav": "wav",
            "application/pdf": "pdf",
            "application/zip": "zip",
            "text/plain": "txt",
            "application/json": "json",
        }
        value = str(mime_type or "").lower().split(";")[0].strip()
        return mapping.get(value, "")

    @classmethod
    def getMimeTypePart(cls, mime_type, *args, **kwargs):
        return str(mime_type or "").split("/")[0].lower()

    @classmethod
    def isVideoMimeType(cls, mime_type, *args, **kwargs):
        return cls.getMimeTypePart(mime_type) == "video"

    @classmethod
    def fixFileName(cls, file_name, *args, **kwargs):
        return os.path.basename(str(file_name or ""))

    @classmethod
    def canSaveAsFile(cls, *args, **kwargs):
        return True

    @classmethod
    def getClosestPhotoSizeWithSize(cls, sizes, size, *args, **kwargs):
        best = None
        best_weight = -1
        target = int(size or 0)
        for item in sizes or []:
            if isinstance(item, dict):
                width = int(item.get("w") or item.get("width") or 0)
                height = int(item.get("h") or item.get("height") or 0)
            else:
                width = int(getattr(item, "w", 0) or 0)
                height = int(getattr(item, "h", 0) or 0)
            weight = max(width, height)
            if best is None or abs(weight - target) < abs(best_weight - target):
                best = item
                best_weight = weight
        return best

    @classmethod
    def getClosestVideoSizeWithSize(cls, sizes, size, *args, **kwargs):
        return cls.getClosestPhotoSizeWithSize(sizes, size, *args, **kwargs)

    @classmethod
    def getPathPhotoSize(cls, photo, *args, **kwargs):
        path = cls.getPathToAttach(photo)
        try:
            return os.path.getsize(str(path))
        except Exception:
            return 0

    @classmethod
    def getPhotoId(cls, photo, *args, **kwargs):
        data = photo if isinstance(photo, dict) else getattr(photo, "_value", None)
        if isinstance(data, dict):
            if data.get("id") is not None:
                return int(data["id"])
            nested = data.get("photo")
            if isinstance(nested, dict) and nested.get("id") is not None:
                return int(nested["id"])
        return 0

    @classmethod
    def isSamePhoto(cls, first, second, *args, **kwargs):
        return cls.getPhotoId(first) == cls.getPhotoId(second) != 0

    @classmethod
    def getStrippedPhotoSize(cls, sizes, size, *args, **kwargs):
        return cls.getClosestPhotoSizeWithSize(sizes, size, *args, **kwargs)

    @classmethod
    def getVectorMarkupVideoSize(cls, sizes, size, *args, **kwargs):
        return cls.getClosestPhotoSizeWithSize(sizes, size, *args, **kwargs)

    @classmethod
    def getBufferedProgressFromPosition(cls, position, file_name, *args, **kwargs):
        return cls.getFileProgress(file_name)

    @classmethod
    def hasAnotherRefOnFile(cls, path, *args, **kwargs):
        return False

    @classmethod
    def isLocallyCreatedFile(cls, path, *args, **kwargs):
        try:
            return os.path.exists(str(path))
        except Exception:
            return False


_PREFERENCES = {}
_PREFERENCES_LOCK = _threading.RLock()


def _preferences_path(name):
    base = os.environ.get("EXTERA_PREFS_DIR", "")
    if not base:
        try:
            import extera_ios

            base = extera_ios.host("paths.dir", kind="files") or ""
        except Exception:
            base = ""
    if not base:
        base = os.path.expanduser("~")
    directory = os.path.join(str(base), "shared_prefs")
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        pass
    safe = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in str(name)
    ) or "default"
    return os.path.join(directory, safe + ".json")


def _preferences_values(name):
    path = _preferences_path(name)
    with _PREFERENCES_LOCK:
        if path in _PREFERENCES:
            return _PREFERENCES[path]
        values = {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                values = data
        except Exception:
            values = {}
        _PREFERENCES[path] = values
        return values


def _save_preferences(name, values):
    path = _preferences_path(name)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(values, handle, ensure_ascii=False, indent=2)
    except Exception:
        pass


class SharedPreferences:
    """`android.content.SharedPreferences` backed by a JSON file.

    Values are kept under `<files>/shared_prefs/<name>.json`.  The file format
    is an implementation detail; a plugin sees the Android getters and editor.
    """

    def __init__(self, name):
        self.name = str(name)

    def _values(self):
        return _preferences_values(self.name)

    def getAll(self):
        with _PREFERENCES_LOCK:
            return dict(self._values())

    def getString(self, key, default=""):
        value = self._values().get(key, default)
        return value if isinstance(value, str) else default

    def getInt(self, key, default=0):
        try:
            return int(self._values().get(key, default))
        except (TypeError, ValueError):
            return default

    def getLong(self, key, default=0):
        return self.getInt(key, default)

    def getFloat(self, key, default=0.0):
        try:
            return float(self._values().get(key, default))
        except (TypeError, ValueError):
            return default

    def getBoolean(self, key, default=False):
        value = self._values().get(key, default)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes")
        return bool(value)

    def getStringSet(self, key, default=None):
        value = self._values().get(key)
        if isinstance(value, list):
            return set(str(item) for item in value)
        return set(default or [])

    def contains(self, key):
        return key in self._values()

    def edit(self):
        return _SharedPreferencesEditor(self)

    def registerOnSharedPreferenceChangeListener(self, listener):
        return None

    def unregisterOnSharedPreferenceChangeListener(self, listener):
        return None


class _SharedPreferencesEditor:
    def __init__(self, parent):
        self._parent = parent
        self._changes = {}
        self._remove = set()
        self._clear = False

    def putString(self, key, value):
        self._changes[key] = None if value is None else str(value)
        return self

    def putInt(self, key, value):
        self._changes[key] = int(value)
        return self

    def putLong(self, key, value):
        self._changes[key] = int(value)
        return self

    def putFloat(self, key, value):
        self._changes[key] = float(value)
        return self

    def putBoolean(self, key, value):
        self._changes[key] = bool(value)
        return self

    def putStringSet(self, key, values):
        self._changes[key] = [str(item) for item in (values or [])]
        return self

    def remove(self, key):
        self._remove.add(key)
        return self

    def clear(self):
        self._clear = True
        return self

    def commit(self):
        with _PREFERENCES_LOCK:
            values = self._parent._values()
            if self._clear:
                values.clear()
            for key in self._remove:
                values.pop(key, None)
            values.update(self._changes)
            _save_preferences(self._parent.name, values)
        return True

    def apply(self):
        self.commit()


class PreferenceManager:
    @classmethod
    def getDefaultSharedPreferences(cls, context=None):
        return SharedPreferences("default")


class ClipData:
    @staticmethod
    def newPlainText(label, text):
        return str(text)


class ClipboardManager:
    def setPrimaryClip(self, clip):
        try:
            import extera_ios

            extera_ios.copy_to_clipboard(str(clip))
        except Exception:
            pass

    def getPrimaryClip(self):
        try:
            import extera_ios

            return extera_ios.get_clipboard()
        except Exception:
            return ""

    def getText(self):
        return self.getPrimaryClip()

    def addPrimaryClipChangedListener(self, listener):
        return None

    def removePrimaryClipChangedListener(self, listener):
        return None


class ComponentName:
    def __init__(self, package_name="", class_name=""):
        self.package_name = str(package_name or "")
        self.class_name = str(class_name or "")

    def getPackageName(self):
        return self.package_name

    def getClassName(self):
        return self.class_name

    def getShortClassName(self):
        return self.class_name.rsplit(".", 1)[-1]

    def flattenToString(self):
        return "%s/%s" % (self.package_name, self.class_name)

    def flattenToShortString(self):
        return self.flattenToString()

    def toShortString(self):
        return self.flattenToString()

    @staticmethod
    def unflattenFromString(value):
        text = str(value or "")
        if "/" not in text:
            return None
        package_name, class_name = text.split("/", 1)
        return ComponentName(package_name, class_name)

    def __str__(self):
        return self.flattenToString()


class BroadcastReceiver:
    def __init__(self, *args, **kwargs):
        self._result_code = 0
        self._result_data = None
        self._result_extras = None
        self._aborted = False

    def onReceive(self, context=None, intent=None):
        return None

    def goAsync(self):
        return _PendingResult()

    def abortBroadcast(self):
        self._aborted = True
        return None

    def getAbortBroadcast(self):
        return self._aborted

    def clearAbortBroadcast(self):
        self._aborted = False
        return None

    def setResultCode(self, code):
        self._result_code = int(code or 0)
        return None

    def getResultCode(self):
        return self._result_code

    def setResultData(self, data):
        self._result_data = data
        return None

    def getResultData(self):
        return self._result_data

    def setResultExtras(self, extras):
        self._result_extras = extras
        return None

    def getResultExtras(self, make_map=False):
        return self._result_extras or Bundle()

    def peekService(self, context=None, intent=None):
        return None

    def isOrderedBroadcast(self):
        return False

    def isInitialStickyBroadcast(self):
        return False


class _PendingResult:
    def finish(self):
        return None


class IntentFilter:
    def __init__(self, action=None):
        self._actions = [str(action)] if action else []
        self._categories = []
        self._schemes = []

    def addAction(self, action):
        self._actions.append(str(action))
        return None

    def addCategory(self, category):
        self._categories.append(str(category))
        return None

    def addDataScheme(self, scheme):
        self._schemes.append(str(scheme))
        return None

    def addDataAuthority(self, *args):
        return None

    def addDataPath(self, *args):
        return None

    def countActions(self):
        return len(self._actions)

    def getAction(self, index):
        try:
            return self._actions[int(index)]
        except (IndexError, TypeError, ValueError):
            return None

    def hasAction(self, action):
        return str(action) in self._actions

    def countCategories(self):
        return len(self._categories)

    def hasCategory(self, category):
        return str(category) in self._categories

    def match(self, action=None, type=None, scheme=None, data=None,
              categories=None, log_level=0):
        if action is not None and not self.hasAction(action):
            return -1
        return 0


class ContextWrapper:
    def __init__(self, base=None):
        self._base = base

    def getBaseContext(self):
        return self._base

    def getApplicationContext(self):
        return self._base or ApplicationLoader.getApplicationContext()

    def getSystemService(self, name):
        base = self._base
        if base is not None and hasattr(base, "getSystemService"):
            return base.getSystemService(name)
        return ApplicationLoader.applicationContext.getSystemService(name)

    def getSharedPreferences(self, name, mode=0):
        return SharedPreferences(name)

    def getResources(self):
        return Resources()

    def getAssets(self):
        return AssetManager(_path_for("files"))

    def getPackageName(self):
        return "org.telegram.Telegram"

    def getContentResolver(self):
        return ContentResolver()

    def getFilesDir(self):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_FILES)

    def getCacheDir(self):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_CACHE)

    def getExternalFilesDir(self, kind=None):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_FILES)

    def getExternalCacheDir(self):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_CACHE)

    def getPackageManager(self):
        return PackageManager()

    def startActivity(self, intent):
        return None

    def startService(self, intent):
        return None

    def stopService(self, intent):
        return False

    def bindService(self, *args):
        return False

    def unbindService(self, *args):
        return None


class Service(ContextWrapper):
    START_STICKY = 1
    START_NOT_STICKY = 2
    START_REDELIVER_INTENT = 3
    START_STICKY_COMPATIBILITY = 0

    def onCreate(self):
        return None

    def onStartCommand(self, intent=None, flags=0, start_id=0):
        return self.START_STICKY

    def onBind(self, intent=None):
        return None

    def onUnbind(self, intent=None):
        return False

    def onDestroy(self):
        return None

    def stopSelf(self):
        return None

    def startForeground(self, notification_id, notification=None):
        return None

    def stopForeground(self, *args):
        return None


class NetworkInfo:
    TYPE_MOBILE = 0
    TYPE_WIFI = 1
    TYPE_WIMAX = 6
    TYPE_ETHERNET = 9
    TYPE_NONE = -1

    def __init__(self, network_type=1, connected=True, state=None):
        self._type = int(network_type if network_type is not None else 1)
        self._connected = bool(connected)
        self._state = state or ("CONNECTED" if connected else "DISCONNECTED")

    def isConnected(self):
        return self._connected

    def isConnectedOrConnecting(self):
        return self._connected

    def isAvailable(self):
        return self._connected

    def isRoaming(self):
        return False

    def getType(self):
        return self._type

    def getTypeName(self):
        return {0: "MOBILE", 1: "WIFI", 9: "ETHERNET"}.get(self._type, "UNKNOWN")

    def getState(self):
        return self._state

    def getDetailedState(self):
        return self._state

    def getExtraInfo(self):
        return None

    def getReason(self):
        return None

    def toString(self):
        return "NetworkInfo[%s]" % self.getTypeName()


class NetworkCapabilities:
    TRANSPORT_CELLULAR = 0
    TRANSPORT_WIFI = 1
    TRANSPORT_BLUETOOTH = 2
    TRANSPORT_ETHERNET = 3
    TRANSPORT_VPN = 4
    NET_CAPABILITY_INTERNET = 12
    NET_CAPABILITY_VALIDATED = 16
    NET_CAPABILITY_NOT_METERED = 11

    def __init__(self, *args, **kwargs):
        self._transports = set()
        self._capabilities = set()

    def hasTransport(self, transport):
        return int(transport) in self._transports

    def hasCapability(self, capability):
        return int(capability) in self._capabilities

    def addTransportType(self, transport):
        self._transports.add(int(transport))
        return self

    def addCapability(self, capability):
        self._capabilities.add(int(capability))
        return self

    def removeCapability(self, capability):
        self._capabilities.discard(int(capability))
        return self

    def getLinkDownstreamBandwidthKbps(self):
        return 0

    def getLinkUpstreamBandwidthKbps(self):
        return 0


class ConnectivityManager:
    TYPE_NONE = -1
    TYPE_MOBILE = 0
    TYPE_WIFI = 1
    TYPE_WIMAX = 6
    TYPE_ETHERNET = 9
    CONNECTIVITY_ACTION = "android.net.conn.CONNECTIVITY_CHANGE"
    DEFAULT_NETWORK_PREFERENCE = 1

    class NetworkCallback:
        def onAvailable(self, network=None):
            pass

        def onLost(self, network=None):
            pass

        def onCapabilitiesChanged(self, network=None, capabilities=None):
            pass

        def onLinkPropertiesChanged(self, network=None, properties=None):
            pass

        def onUnavailable(self):
            pass

    def getActiveNetworkInfo(self):
        return NetworkInfo(NetworkInfo.TYPE_WIFI, True)

    def getNetworkInfo(self, network_type):
        return NetworkInfo(network_type, True)

    def isActiveNetworkMetered(self):
        return False

    def getActiveNetwork(self):
        return None

    def getNetworkCapabilities(self, network=None):
        capabilities = NetworkCapabilities()
        capabilities.addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
        capabilities.addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        capabilities.addCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
        capabilities.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
        return capabilities

    def registerNetworkCallback(self, request, callback):
        return None

    def unregisterNetworkCallback(self, callback):
        return None

    def addDefaultNetworkActiveListener(self, listener):
        return None

    def removeDefaultNetworkActiveListener(self, listener):
        return None

    def isDefaultNetworkActive(self):
        return True

    def startUsingNetworkFeature(self, *args):
        return 0

    def stopUsingNetworkFeature(self, *args):
        return 0


class NotificationChannel:
    IMPORTANCE_NONE = 0
    IMPORTANCE_MIN = 1
    IMPORTANCE_LOW = 2
    IMPORTANCE_DEFAULT = 3
    IMPORTANCE_HIGH = 4

    def __init__(self, channel_id="", name="", importance=0):
        self._id = str(channel_id or "")
        self._name = str(name or "")
        self._importance = int(importance or 0)
        self._description = ""
        self._group = None
        self._show_badge = True
        self._sound = None
        self._vibration = False
        self._vibration_pattern = None
        self._lights = False
        self._light_color = 0
        self._bypass_dnd = False
        self._lockscreen_visibility = 0

    def getId(self):
        return self._id

    def setId(self, value):
        self._id = str(value or "")
        return None

    def getName(self):
        return self._name

    def setName(self, value):
        self._name = str(value or "")
        return None

    def getImportance(self):
        return self._importance

    def setImportance(self, value):
        self._importance = int(value or 0)
        return None

    def getDescription(self):
        return self._description

    def setDescription(self, value):
        self._description = str(value or "")
        return None

    def setSound(self, value, audio_attributes=None):
        self._sound = value
        return None

    def getSound(self):
        return self._sound

    def enableVibration(self, value):
        self._vibration = bool(value)
        return None

    def shouldVibrate(self):
        return self._vibration

    def setVibrationPattern(self, value):
        self._vibration_pattern = value
        return None

    def getVibrationPattern(self):
        return self._vibration_pattern

    def setLockscreenVisibility(self, value):
        self._lockscreen_visibility = int(value or 0)
        return None

    def getLockscreenVisibility(self):
        return self._lockscreen_visibility

    def setShowBadge(self, value):
        self._show_badge = bool(value)
        return None

    def canShowBadge(self):
        return self._show_badge

    def setGroup(self, value):
        self._group = value
        return None

    def getGroup(self):
        return self._group

    def setBypassDnd(self, value):
        self._bypass_dnd = bool(value)
        return None

    def canBypassDnd(self):
        return self._bypass_dnd

    def enableLights(self, value):
        self._lights = bool(value)
        return None

    def setLightColor(self, value):
        self._light_color = int(value or 0)
        return None

    def shouldShowLights(self):
        return self._lights


class NotificationManager:
    IMPORTANCE_NONE = 0
    IMPORTANCE_MIN = 1
    IMPORTANCE_LOW = 2
    IMPORTANCE_DEFAULT = 3
    IMPORTANCE_HIGH = 4

    def __init__(self):
        self._channels = {}
        self._groups = {}
        self._notifications = {}

    def createNotificationChannel(self, channel):
        if channel is not None:
            self._channels[channel.getId()] = channel
        return None

    def createNotificationChannels(self, channels):
        for channel in channels or []:
            self.createNotificationChannel(channel)
        return None

    def getNotificationChannel(self, channel_id):
        return self._channels.get(str(channel_id or ""))

    def getNotificationChannels(self):
        return list(self._channels.values())

    def deleteNotificationChannel(self, channel_id):
        self._channels.pop(str(channel_id or ""), None)
        return None

    def deleteAllNotificationChannels(self):
        self._channels.clear()
        return None

    def createNotificationChannelGroup(self, group):
        return None

    def getNotificationChannelGroup(self, group_id):
        return None

    def getNotificationChannelGroups(self):
        return []

    def notify(self, notification_id, notification):
        self._notifications[int(notification_id or 0)] = notification
        return None

    def cancel(self, notification_id):
        self._notifications.pop(int(notification_id or 0), None)
        return None

    def cancelAll(self):
        self._notifications.clear()
        return None

    def areNotificationsEnabled(self):
        return True

    def getActiveNotifications(self):
        return list(self._notifications.values())


class Notification:
    PRIORITY_MIN = -2
    PRIORITY_LOW = -1
    PRIORITY_DEFAULT = 0
    PRIORITY_HIGH = 1
    PRIORITY_MAX = 2
    DEFAULT_ALL = -1
    DEFAULT_SOUND = 1
    DEFAULT_VIBRATE = 2
    DEFAULT_LIGHTS = 4
    CATEGORY_MESSAGE = "msg"
    CATEGORY_EMAIL = "email"
    CATEGORY_CALL = "call"
    CATEGORY_EVENT = "event"
    CATEGORY_PROMO = "promo"
    CATEGORY_ALARM = "alarm"
    CATEGORY_PROGRESS = "progress"
    CATEGORY_SOCIAL = "social"
    CATEGORY_ERROR = "err"
    CATEGORY_TRANSPORT = "transport"
    CATEGORY_SYSTEM = "sys"
    CATEGORY_SERVICE = "service"
    CATEGORY_REMINDER = "reminder"
    CATEGORY_RECOMMENDATION = "recommendation"
    CATEGORY_STATUS = "status"

    def __init__(self):
        self.extras = Bundle()
        self.priority = 0
        self.when = 0
        self.flags = 0
        self.icon = 0
        self.title = None
        self.text = None
        self.sound = None
        self.vibrate = None
        self.ticker = None
        self.contentIntent = None
        self.deleteIntent = None
        self.actions = []
        self.category = None
        self.group = None
        self.color = 0
        self.number = 0
        self.progress = 0
        self.progressMax = 0
        self.progressIndeterminate = False
        self.ongoing = False
        self.autoCancel = False
        self.onlyAlertOnce = False
        self.showWhen = True
        self.style = None

    class Builder:
        def __init__(self, context=None, channel_id=""):
            self.context = context
            self.channel_id = str(channel_id or "")
            self.notification = Notification()

        def setSmallIcon(self, icon, level=None):
            self.notification.icon = icon
            return self

        def setContentTitle(self, value):
            self.notification.title = value
            return self

        def setContentText(self, value):
            self.notification.text = value
            return self

        def setContentIntent(self, value):
            self.notification.contentIntent = value
            return self

        def setDeleteIntent(self, value):
            self.notification.deleteIntent = value
            return self

        def setAutoCancel(self, value):
            self.notification.autoCancel = bool(value)
            return self

        def setPriority(self, value):
            self.notification.priority = int(value or 0)
            return self

        def setWhen(self, value):
            self.notification.when = int(value or 0)
            return self

        def setShowWhen(self, value):
            self.notification.showWhen = bool(value)
            return self

        def setStyle(self, value):
            self.notification.style = value
            return self

        def setProgress(self, max_value, progress=0, indeterminate=False):
            self.notification.progressMax = int(max_value or 0)
            self.notification.progress = int(progress or 0)
            self.notification.progressIndeterminate = bool(indeterminate)
            return self

        def setOngoing(self, value):
            self.notification.ongoing = bool(value)
            return self

        def setOnlyAlertOnce(self, value):
            self.notification.onlyAlertOnce = bool(value)
            return self

        def setColor(self, value):
            self.notification.color = int(value or 0)
            return self

        def setNumber(self, value):
            self.notification.number = int(value or 0)
            return self

        def setCategory(self, value):
            self.notification.category = value
            return self

        def setGroup(self, value):
            self.notification.group = value
            return self

        def setSortKey(self, value):
            return self

        def setLocalOnly(self, value):
            return self

        def setDefaults(self, value):
            return self

        def setSound(self, value, audio_attributes=None):
            self.notification.sound = value
            return self

        def setVibrate(self, value):
            self.notification.vibrate = value
            return self

        def setLights(self, *args):
            return self

        def setTicker(self, value):
            self.notification.ticker = value
            return self

        def setSubText(self, value):
            return self

        def setContentInfo(self, value):
            return self

        def setLargeIcon(self, value):
            return self

        def addAction(self, *args):
            self.notification.actions.append(args)
            return self

        def setExtras(self, value):
            self.notification.extras = value
            return self

        def build(self):
            return self.notification


class NotificationCompat:
    class Builder(Notification.Builder):
        pass


class Display:
    def __init__(self, width=1080, height=1920, density=3.0):
        self._width = int(width)
        self._height = int(height)
        self._density = float(density)

    def getWidth(self):
        return self._width

    def getHeight(self):
        return self._height

    def getRotation(self):
        return 0

    def getMetrics(self, metrics=None):
        value = metrics or DisplayMetrics()
        value.widthPixels = self._width
        value.heightPixels = self._height
        value.density = self._density
        value.densityDpi = int(self._density * 160)
        return value

    def getRealMetrics(self, metrics=None):
        return self.getMetrics(metrics)

    def getSize(self, point=None):
        if point is not None:
            point.x = self._width
            point.y = self._height
        return None

    def getRealSize(self, point=None):
        return self.getSize(point)


class WindowManager:
    def getDefaultDisplay(self):
        return Display()

    def getCurrentWindowMetrics(self):
        return None


class Window:
    FEATURE_NO_TITLE = 1
    FEATURE_ACTION_BAR = 8
    FEATURE_ACTION_BAR_OVERLAY = 9
    FEATURE_INDETERMINATE_PROGRESS = 5
    FLAG_FULLSCREEN = 1024
    FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS = 0x80000000
    FLAG_TRANSLUCENT_STATUS = 0x04000000
    FLAG_TRANSLUCENT_NAVIGATION = 0x08000000
    FLAG_KEEP_SCREEN_ON = 128
    FLAG_SECURE = 8192
    SOFT_INPUT_ADJUST_RESIZE = 16
    SOFT_INPUT_ADJUST_PAN = 32
    SOFT_INPUT_STATE_ALWAYS_HIDDEN = 3
    SOFT_INPUT_STATE_ALWAYS_VISIBLE = 4

    def __init__(self, context=None):
        self.context = context
        self.decorView = None
        self.flags = 0

    def setFlags(self, *args):
        if args:
            self.flags |= int(args[0] or 0)
        return None

    def addFlags(self, value):
        self.flags |= int(value or 0)
        return None

    def clearFlags(self, value):
        self.flags &= ~int(value or 0)
        return None

    def getAttributes(self):
        return None

    def setAttributes(self, value):
        return None

    def setStatusBarColor(self, color):
        return None

    def setNavigationBarColor(self, color):
        return None

    def setSoftInputMode(self, value):
        return None

    def setLayout(self, *args):
        return None

    def setGravity(self, value):
        return None

    def setBackgroundDrawable(self, value):
        return None

    def setDimAmount(self, value):
        return None

    def setType(self, value):
        return None

    def setFormat(self, value):
        return None

    def setWindowAnimations(self, value):
        return None

    def setDecorView(self, value):
        self.decorView = value
        return None

    def getDecorView(self):
        if self.decorView is None:
            self.decorView = View()
        return self.decorView

    def findViewById(self, identifier):
        return None

    def requestFeature(self, value):
        return None

    def setTitle(self, value):
        return None


class LayoutInflater:
    @classmethod
    def from_(cls, context=None):
        return cls()

    def inflate(self, resource, root=None, attach_to_root=True):
        return View()

    def cloneInContext(self, context):
        return self


class Parcel:
    def __init__(self):
        self._data = []
        self._position = 0

    @staticmethod
    def obtain():
        return Parcel()

    def writeString(self, value):
        self._data.append(value)
        return None

    def writeInt(self, value):
        self._data.append(int(value or 0))
        return None

    def writeLong(self, value):
        self._data.append(int(value or 0))
        return None

    def writeFloat(self, value):
        self._data.append(float(value or 0))
        return None

    def writeDouble(self, value):
        self._data.append(float(value or 0))
        return None

    def writeByte(self, value):
        self._data.append(int(value or 0))
        return None

    def writeByteArray(self, value):
        self._data.append(bytes(value or b""))
        return None

    def writeBundle(self, value):
        self._data.append(value)
        return None

    def writeParcelable(self, value, flags=0):
        self._data.append(value)
        return None

    def writeList(self, value):
        self._data.append(list(value or []))
        return None

    def writeValue(self, value):
        self._data.append(value)
        return None

    def readString(self):
        return ""

    def readInt(self):
        return 0

    def readLong(self):
        return 0

    def readFloat(self):
        return 0.0

    def readDouble(self):
        return 0.0

    def readByte(self):
        return 0

    def readByteArray(self):
        return b""

    def readBundle(self, loader=None):
        return Bundle()

    def readParcelable(self, loader=None):
        return None

    def readList(self):
        return []

    def readValue(self):
        return None

    def dataSize(self):
        return len(self._data)

    def dataPosition(self):
        return self._position

    def setDataPosition(self, value):
        self._position = int(value or 0)
        return None

    def dataAvail(self):
        return max(0, len(self._data) - self._position)

    def marshall(self):
        return b""

    def unmarshall(self, data, offset=0, length=None):
        return None

    def recycle(self):
        self._data = []
        self._position = 0
        return None


class Parcelable:
    CONTENTS_FILE_DESCRIPTOR = 1
    PARCELABLE_WRITE_RETURN_VALUE = 1

    def describeContents(self):
        return 0

    def writeToParcel(self, parcel, flags):
        return None

    class Creator:
        def createFromParcel(self, parcel):
            return None

        def newArray(self, size):
            return []

    class ClassLoaderCreator(Creator):
        pass


class IBinder:
    def transact(self, *args):
        return False

    def queryLocalInterface(self, name):
        return None

    def getInterfaceDescriptor(self):
        return ""

    def isBinderAlive(self):
        return True

    def pingBinder(self):
        return True

    def linkToDeath(self, *args):
        return None

    def unlinkToDeath(self, *args):
        return True


class Binder(IBinder):
    pass


class Intent:
    ACTION_VIEW = "android.intent.action.VIEW"
    ACTION_SEND = "android.intent.action.SEND"
    ACTION_SEND_MULTIPLE = "android.intent.action.SEND_MULTIPLE"
    ACTION_SENDTO = "android.intent.action.SENDTO"
    ACTION_CHOOSER = "android.intent.action.CHOOSER"
    ACTION_MAIN = "android.intent.action.MAIN"
    ACTION_GET_CONTENT = "android.intent.action.GET_CONTENT"
    ACTION_OPEN_DOCUMENT = "android.intent.action.OPEN_DOCUMENT"
    ACTION_PICK = "android.intent.action.PICK"
    ACTION_EDIT = "android.intent.action.EDIT"
    ACTION_INSERT = "android.intent.action.INSERT"
    ACTION_DELETE = "android.intent.action.DELETE"
    ACTION_ANSWER = "android.intent.action.ANSWER"
    ACTION_CALL = "android.intent.action.CALL"
    ACTION_DIAL = "android.intent.action.DIAL"
    ACTION_SEARCH = "android.intent.action.SEARCH"
    ACTION_WEB_SEARCH = "android.intent.action.WEB_SEARCH"
    ACTION_BATTERY_CHANGED = "android.intent.action.BATTERY_CHANGED"
    ACTION_BATTERY_LOW = "android.intent.action.BATTERY_LOW"
    ACTION_BATTERY_OKAY = "android.intent.action.BATTERY_OKAY"
    ACTION_POWER_CONNECTED = "android.intent.action.ACTION_POWER_CONNECTED"
    ACTION_POWER_DISCONNECTED = "android.intent.action.ACTION_POWER_DISCONNECTED"
    ACTION_SCREEN_ON = "android.intent.action.SCREEN_ON"
    ACTION_SCREEN_OFF = "android.intent.action.SCREEN_OFF"
    ACTION_USER_PRESENT = "android.intent.action.USER_PRESENT"
    ACTION_TIME_TICK = "android.intent.action.TIME_TICK"
    ACTION_TIME_CHANGED = "android.intent.action.TIME_SET"
    ACTION_TIMEZONE_CHANGED = "android.intent.action.TIMEZONE_CHANGED"
    ACTION_LOCALE_CHANGED = "android.intent.action.LOCALE_CHANGED"
    ACTION_CONFIGURATION_CHANGED = "android.intent.action.CONFIGURATION_CHANGED"
    ACTION_AIRPLANE_MODE_CHANGED = "android.intent.action.AIRPLANE_MODE"
    ACTION_HEADSET_PLUG = "android.intent.action.HEADSET_PLUG"
    ACTION_MEDIA_BUTTON = "android.intent.action.MEDIA_BUTTON"
    ACTION_BOOT_COMPLETED = "android.intent.action.BOOT_COMPLETED"
    ACTION_SHUTDOWN = "android.intent.action.ACTION_SHUTDOWN"
    ACTION_MY_PACKAGE_REPLACED = "android.intent.action.MY_PACKAGE_REPLACED"
    ACTION_PACKAGE_ADDED = "android.intent.action.PACKAGE_ADDED"
    ACTION_PACKAGE_REMOVED = "android.intent.action.PACKAGE_REMOVED"
    ACTION_PACKAGE_REPLACED = "android.intent.action.PACKAGE_REPLACED"
    ACTION_NEW_OUTGOING_CALL = "android.intent.action.NEW_OUTGOING_CALL"
    ACTION_REBOOT = "android.intent.action.REBOOT"
    CATEGORY_BROWSABLE = "android.intent.category.BROWSABLE"
    CATEGORY_LAUNCHER = "android.intent.category.LAUNCHER"
    CATEGORY_OPENABLE = "android.intent.category.OPENABLE"
    CATEGORY_DEFAULT = "android.intent.category.DEFAULT"
    CATEGORY_HOME = "android.intent.category.HOME"
    CATEGORY_APP_BROWSER = "android.intent.category.APP_BROWSER"
    FLAG_ACTIVITY_NEW_TASK = 0x10000000
    FLAG_ACTIVITY_CLEAR_TOP = 0x04000000
    FLAG_ACTIVITY_SINGLE_TOP = 0x20000000
    FLAG_ACTIVITY_MULTIPLE_TASK = 0x08000000
    FLAG_ACTIVITY_CLEAR_TASK = 0x00008000
    FLAG_ACTIVITY_RESET_TASK_IF_NEEDED = 0x00200000
    FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS = 0x00800000
    FLAG_ACTIVITY_NO_ANIMATION = 0x00010000
    FLAG_ACTIVITY_NEW_DOCUMENT = 0x00080000
    FLAG_ACTIVITY_RETAIN_IN_RECENTS = 0x00002000
    FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY = 0x00100000
    FLAG_ACTIVITY_TASK_ON_HOME = 0x00004000
    FLAG_GRANT_READ_URI_PERMISSION = 0x00000001
    FLAG_GRANT_WRITE_URI_PERMISSION = 0x00000002
    EXTRA_STREAM = "android.intent.extra.STREAM"
    EXTRA_TEXT = "android.intent.extra.TEXT"
    EXTRA_SUBJECT = "android.intent.extra.SUBJECT"
    EXTRA_EMAIL = "android.intent.extra.EMAIL"

    @classmethod
    def getClass(cls):
        return _java_class_ref("android.content.Intent")

    @staticmethod
    def createChooser(target, title=None):
        intent = Intent("android.intent.action.CHOOSER")
        intent.putExtra("android.intent.extra.INTENT", target)
        if title is not None:
            intent.putExtra("android.intent.extra.TITLE", title)
        return intent

    def __init__(self, action=None, uri=None):
        self._action = action
        self._data = uri
        self._type = None
        self._extras = {}
        self._flags = 0
        self._package = None

    def setAction(self, action):
        self._action = action
        return self

    def getAction(self):
        return self._action

    def setData(self, uri):
        self._data = uri
        return self

    def getData(self):
        return self._data

    def setType(self, value):
        self._type = value
        return self

    def getType(self):
        return self._type

    def putExtra(self, key, value):
        self._extras[key] = value
        return self

    def getStringExtra(self, key):
        value = self._extras.get(key)
        return value if isinstance(value, str) else None

    def getIntExtra(self, key, default=0):
        try:
            return int(self._extras.get(key, default))
        except (TypeError, ValueError):
            return default

    def getBooleanExtra(self, key, default=False):
        return bool(self._extras.get(key, default))

    def addFlags(self, flags):
        self._flags |= int(flags)
        return self

    def getFlags(self):
        return self._flags

    def setPackage(self, value):
        self._package = value
        return self

    def getPackage(self):
        return self._package


class Icon:
    TYPE_BITMAP = 1
    TYPE_RESOURCE = 2
    TYPE_DATA = 3
    TYPE_URI = 4
    TYPE_ADAPTIVE_BITMAP = 5

    def __init__(self, kind=None, value=None, resource=None):
        self.kind = kind
        self.value = value
        self.resource = resource

    @staticmethod
    def createWithBitmap(bitmap):
        return Icon("bitmap", bitmap)

    @staticmethod
    def createWithResource(context, resource):
        return Icon("resource", None, resource)

    @staticmethod
    def createWithAdaptiveBitmap(bitmap):
        return Icon("adaptive", bitmap)

    @staticmethod
    def createWithData(data):
        return Icon("data", data)

    @staticmethod
    def createWithContentUri(uri):
        return Icon("uri", uri)

    @staticmethod
    def createWithFilePath(path):
        return Icon("file", path)


class ShortcutInfo:
    class Builder:
        def __init__(self, context=None, shortcut_id=""):
            self._context = context
            self._id = str(shortcut_id or "")
            self._short_label = ""
            self._long_label = ""
            self._icon = None
            self._intents = []
            self._rank = 0
            self._disabled_message = ""
            self._categories = set()

        def setShortLabel(self, value):
            self._short_label = str(value or "")
            return self

        def setLongLabel(self, value):
            self._long_label = str(value or "")
            return self

        def setIcon(self, value):
            self._icon = value
            return self

        def setIntent(self, value):
            self._intents = [value]
            return self

        def setIntents(self, values):
            self._intents = list(values or [])
            return self

        def setRank(self, value):
            self._rank = int(value or 0)
            return self

        def setDisabledMessage(self, value):
            self._disabled_message = str(value or "")
            return self

        def setCategories(self, values):
            self._categories = set(values or ())
            return self

        def build(self):
            shortcut = ShortcutInfo(self._id)
            shortcut._short_label = self._short_label
            shortcut._long_label = self._long_label
            shortcut._icon = self._icon
            shortcut._intents = list(self._intents)
            shortcut._rank = self._rank
            shortcut._disabled_message = self._disabled_message
            shortcut._categories = set(self._categories)
            return shortcut

    def __init__(self, shortcut_id=""):
        self._id = str(shortcut_id or "")
        self._short_label = ""
        self._long_label = ""
        self._icon = None
        self._intents = []
        self._rank = 0
        self._disabled_message = ""
        self._categories = set()
        self._enabled = True

    def getId(self):
        return self._id

    def getShortLabel(self):
        return self._short_label

    def getLongLabel(self):
        return self._long_label

    def getIcon(self):
        return self._icon

    def getIntent(self):
        return self._intents[0] if self._intents else None

    def getIntents(self):
        return list(self._intents)

    def getRank(self):
        return self._rank

    def isEnabled(self):
        return self._enabled

    def getDisabledMessage(self):
        return self._disabled_message

    def getCategories(self):
        return set(self._categories)


class ShortcutManager:
    def __init__(self):
        self._dynamic = []
        self._pinned = []

    def getDynamicShortcuts(self):
        return list(self._dynamic)

    def getPinnedShortcuts(self):
        return list(self._pinned)

    def getMaxShortcutCountPerActivity(self):
        return 5

    def setDynamicShortcuts(self, shortcuts):
        self._dynamic = list(shortcuts or [])
        return True

    def addDynamicShortcuts(self, shortcuts):
        self._dynamic.extend(shortcuts or [])
        return True

    def updateShortcuts(self, shortcuts):
        updated = {item.getId(): item for item in shortcuts or []}
        self._dynamic = [updated.get(item.getId(), item) for item in self._dynamic]
        return True

    def removeDynamicShortcuts(self, ids):
        values = set(ids or ())
        self._dynamic = [item for item in self._dynamic if item.getId() not in values]
        return None

    def removeAllDynamicShortcuts(self):
        self._dynamic = []
        return None

    def requestPinShortcut(self, shortcut, callback=None):
        self._pinned.append(shortcut)
        return True

    def isRequestPinShortcutSupported(self):
        return False

    def enableShortcuts(self, ids):
        return None

    def disableShortcuts(self, ids, message=None):
        return None


class ActivityManager:
    class TaskDescription:
        def __init__(self, label=None, icon=None, color=0, *args, **kwargs):
            self._label = label
            self._icon = icon
            self._color = int(color or 0)

        def getLabel(self):
            return self._label

        def getIcon(self):
            return self._icon

        def getPrimaryColor(self):
            return self._color

        def setLabel(self, value):
            self._label = value
            return self

        def setIcon(self, value):
            self._icon = value
            return self

        def setPrimaryColor(self, value):
            self._color = int(value or 0)
            return self

    class AppTask:
        def __init__(self, *args, **kwargs):
            self.task_info = None

        def setExcludeFromRecents(self, value):
            return None

        def finishAndRemoveTask(self):
            return None

        def moveToFront(self):
            return None

        def startActivity(self, *args, **kwargs):
            return None

        def getTaskInfo(self):
            return self.task_info

    class MemoryInfo:
        def __init__(self):
            self.availMem = 0
            self.totalMem = 0
            self.threshold = 0
            self.lowMemory = False

        def getAvailMem(self):
            return self.availMem

        def getTotalMem(self):
            return self.totalMem

        def getThreshold(self):
            return self.threshold

        def isLowMemory(self):
            return self.lowMemory

    def __init__(self):
        self._tasks = []

    def getMemoryInfo(self, info=None):
        value = info or self.MemoryInfo()
        try:
            import os

            if hasattr(os, "sysconf"):
                value.totalMem = int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
        except Exception:
            pass
        return value

    def getProcessMemoryInfo(self, pids=None):
        return []

    def getMyMemoryState(self, state=None):
        return None

    def getRunningTasks(self, max_num=1):
        return []

    def getAppTasks(self):
        return []

    def getRunningAppProcesses(self):
        return []

    def setTaskDescription(self, description):
        return None

    def getDeviceConfigurationInfo(self):
        return None


class Context:
    MODE_PRIVATE = 0
    MODE_WORLD_READABLE = 1
    MODE_WORLD_WRITEABLE = 2
    MODE_APPEND = 32768
    MODE_MULTI_PROCESS = 4
    VIBRATOR_SERVICE = "vibrator"
    CLIPBOARD_SERVICE = "clipboard"
    ACTIVITY_SERVICE = "activity"
    SHORTCUT_SERVICE = "shortcut"
    NOTIFICATION_SERVICE = "notification"
    WINDOW_SERVICE = "window"
    LAYOUT_INFLATER_SERVICE = "layout_inflater"
    CONNECTIVITY_SERVICE = "connectivity"
    POWER_SERVICE = "power"
    WINDOW_SERVICE = "window"
    NSD_SERVICE = "servicediscovery"
    WIFI_SERVICE = "wifi"
    TELEPHONY_SERVICE = "phone"
    BATTERY_SERVICE = "batterymanager"
    SENSOR_SERVICE = "sensor"
    LOCATION_SERVICE = "location"
    CAMERA_SERVICE = "camera"
    AUDIO_SERVICE = "audio"
    ALARM_SERVICE = "alarm"
    KEYGUARD_SERVICE = "keyguard"
    SEARCH_SERVICE = "search"
    INPUT_METHOD_SERVICE = "input_method"
    DOWNLOAD_SERVICE = "download"
    STORAGE_SERVICE = "storage"
    USER_SERVICE = "user"
    BLUETOOTH_SERVICE = "bluetooth"
    UI_MODE_SERVICE = "uimode"
    DISPLAY_SERVICE = "display"
    ACCESSIBILITY_SERVICE = "accessibility"
    NFC_SERVICE = "nfc"
    TELECOM_SERVICE = "telecom"
    WALLPAPER_SERVICE = "wallpaper"
    ACCOUNT_SERVICE = "account"
    APPWIDGET_SERVICE = "appwidget"
    JOB_SCHEDULER_SERVICE = "jobscheduler"
    MEDIA_ROUTER_SERVICE = "media_router"
    CONSUMER_IR_SERVICE = "consumer_ir"
    DROPBOX_SERVICE = "dropbox"
    DEVICE_POLICY_SERVICE = "device_policy"
    FINGERPRINT_SERVICE = "fingerprint"
    PRINT_SERVICE = "print"
    RESTRICTIONS_SERVICE = "restrictions"
    SYSTEM_HEALTH_SERVICE = "systemhealth"
    TV_INPUT_SERVICE = "tv_input"
    USAGE_STATS_SERVICE = "usagestats"
    VPN_MANAGEMENT_SERVICE = "vpn_management"

    def getApplicationInfo(self):
        return ApplicationInfo()

    def getString(self, identifier, *args):
        return _resource_string(identifier, *args)


class AssetManager:
    def __init__(self, root=None):
        self._root = str(root or _path_for("files"))

    def open(self, path, mode=0):
        from extera_utils.classes import ByteArrayInputStream

        full = os.path.join(self._root, str(path or ""))
        try:
            with open(full, "rb") as handle:
                return ByteArrayInputStream(handle.read())
        except OSError:
            return ByteArrayInputStream(b"")

    def list(self, path=""):
        full = os.path.join(self._root, str(path or ""))
        try:
            return sorted(os.listdir(full))
        except OSError:
            return []

    def close(self):
        return None


class _ApplicationContext:
    def getPackageName(self):
        return "org.telegram.Telegram"

    def getApplicationInfo(self):
        return ApplicationInfo(self.getPackageName())

    def getString(self, identifier, *args):
        return _resource_string(identifier, *args)

    def getAssets(self):
        return AssetManager(_path_for("files"))

    def getFilesDir(self):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_FILES)

    def getCacheDir(self):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_CACHE)

    def getExternalFilesDir(self, kind=None):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_FILES)

    def getSharedPreferences(self, name, mode=0):
        return SharedPreferences(name)

    def getSystemService(self, name):
        service = str(name or "").lower()
        if service in ("clipboard", "android.content.clipboardmanager"):
            return ClipboardManager()
        if service in ("power", "android.os.powermanager"):
            return PowerManager()
        if service in ("vibrator", "android.os.vibrator"):
            return Vibrator()
        if service in ("audio", "android.media.audiomanager"):
            return AudioManager()
        if service in ("activity", "android.app.activitymanager"):
            return ActivityManager()
        if service in ("shortcut", "android.content.pm.shortcutmanager"):
            return ShortcutManager()
        if service in ("servicediscovery", "nsd", "android.net.nsd.nsdmanager"):
            return NsdManager()
        if service in ("wifi", "android.net.wifi.wifimanager"):
            return WifiManager()
        if service in ("phone", "android.telephony.telephonymanager"):
            return TelephonyManager()
        if service in ("batterymanager", "battery", "android.os.batterymanager"):
            return BatteryManager()
        if service in ("connectivity", "android.net.connectivitymanager"):
            return ConnectivityManager()
        if service in ("sensor", "android.hardware.sensormanager"):
            return SensorManager()
        if service in ("location", "android.location.locationmanager"):
            return LocationManager()
        if service in ("notification", "android.app.notificationmanager"):
            return NotificationManager()
        if service in ("window", "android.view.windowmanager"):
            return WindowManager()
        return None

    def getContentResolver(self):
        return ContentResolver()

    def getResources(self):
        return Resources()

    def getExternalCacheDir(self):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_CACHE)

    def getDir(self, name, mode=0):
        from extera_utils.classes import NativeFile

        directory = os.path.join(_path_for("files"), "app_%s" % str(name or ""))
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
        return NativeFile(directory)

    def getDatabasePath(self, name):
        from extera_utils.classes import NativeFile

        directory = os.path.join(_path_for("files"), "databases")
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
        return NativeFile(os.path.join(directory, str(name or "")))

    def getCodeCacheDir(self):
        from extera_utils.classes import NativeFile

        directory = os.path.join(_path_for("cache"), "code_cache")
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
        return NativeFile(directory)

    def getNoBackupFilesDir(self):
        from extera_utils.classes import NativeFile

        directory = os.path.join(_path_for("files"), "no_backup")
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
        return NativeFile(directory)

    def getPackageCodePath(self):
        return ""

    def getPackageResourcePath(self):
        return ""

    def getPackageManager(self):
        return PackageManager()

    def startActivity(self, intent):
        try:
            import extera_ios

            uri = intent.getData() if isinstance(intent, Intent) else None
            if uri:
                extera_ios.open_url(str(uri), True)
        except Exception:
            pass


class Browser:
    @staticmethod
    def openUrl(*args, **kwargs):
        url = kwargs.get("url")
        if url is None:
            if len(args) >= 2 and isinstance(args[1], str):
                url = args[1]
            elif args and isinstance(args[0], str):
                url = args[0]
        if not url:
            return False
        try:
            import extera_ios

            extera_ios.open_url(str(url))
            return True
        except Exception:
            return False

    @staticmethod
    def openUrlInApp(*args, **kwargs):
        return Browser.openUrl(*args, **kwargs)

    @staticmethod
    def openUrlInExternalBrowser(*args, **kwargs):
        return Browser.openUrl(*args, **kwargs)


class ApplicationLoader(metaclass=_TolerantClassMeta):
    applicationContext = _ApplicationContext()

    @classmethod
    def getApplicationContext(cls):
        return cls.applicationContext

    @classmethod
    def getApplicationId(cls):
        try:
            import extera_ios

            info = extera_ios.app_info() or {}
            bundle = info.get("bundle_id") or info.get("package")
            if bundle:
                return str(bundle)
        except Exception:
            pass
        return "org.telegram.Telegram"

    @classmethod
    def getFilesDirFixed(cls):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_FILES)

    @classmethod
    def isNetworkOnline(cls, *args, **kwargs):
        return True

    @classmethod
    def isNetworkOnlineFast(cls, *args, **kwargs):
        return True

    @classmethod
    def isNetworkOnlineRealtime(cls, *args, **kwargs):
        return True

    @classmethod
    def isConnectedToWiFi(cls, *args, **kwargs):
        return True

    @classmethod
    def isConnectedOrConnectingToWiFi(cls, *args, **kwargs):
        return True

    @classmethod
    def isRoaming(cls, *args, **kwargs):
        return False

    @classmethod
    def isConnectionSlow(cls, *args, **kwargs):
        return False

    @classmethod
    def getCurrentNetworkType(cls, *args, **kwargs):
        return 1

    @classmethod
    def getAutodownloadNetworkType(cls, *args, **kwargs):
        return 1

    @classmethod
    def isDownloadingUpdate(cls, *args, **kwargs):
        return False

    @classmethod
    def getDownloadingUpdateProgress(cls, *args, **kwargs):
        return 0

    @classmethod
    def getDownloadedUpdateFile(cls, *args, **kwargs):
        return None

    @classmethod
    def cancelDownloadingUpdate(cls, *args, **kwargs):
        return None

    @classmethod
    def downloadUpdate(cls, *args, **kwargs):
        return None

    @classmethod
    def checkUpdate(cls, *args, **kwargs):
        return None

    @classmethod
    def getPushProvider(cls, *args, **kwargs):
        return None

    @classmethod
    def getLocationServiceProvider(cls, *args, **kwargs):
        return None

    @classmethod
    def getMapsProvider(cls, *args, **kwargs):
        return None

    @classmethod
    def getFirebaseAnalytics(cls, *args, **kwargs):
        return None

    @classmethod
    def getFirebaseCrashlytics(cls, *args, **kwargs):
        return None

    @classmethod
    def openSettings(cls, *args, **kwargs):
        return None

    @classmethod
    def startPushService(cls, *args, **kwargs):
        return None

    @classmethod
    def postInitApplication(cls, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# LocaleController / AndroidUtilities / Utilities


class LocaleController(metaclass=_TolerantClassMeta):
    @classmethod
    def _localized(cls, key):
        try:
            import extera_ios

            value = extera_ios.host("locale.string", key=str(key))
            if isinstance(value, str) and value:
                return value
        except Exception:
            pass
        return str(key)

    @classmethod
    def getString(cls, key, *args):
        return cls._localized(key)

    @classmethod
    def formatString(cls, key, *args):
        text = cls._localized(key)
        try:
            if args:
                return text % args
        except Exception:
            pass
        return text

    @classmethod
    def getPluralString(cls, key, quantity, *args):
        return cls._localized(key)

    @classmethod
    def formatPluralString(cls, key, quantity, *args):
        text = cls._localized(key)
        try:
            if args:
                return text % args
        except Exception:
            pass
        return text

    @classmethod
    def formatShortNumber(cls, number, *args):
        value = float(number or 0)
        if value >= 1_000_000:
            return "%.1fM" % (value / 1_000_000.0)
        if value >= 1000:
            return "%.1fK" % (value / 1000.0)
        return str(int(value))

    @classmethod
    def formatUserStatus(cls, account, user, *args, **kwargs):
        return ""

    @classmethod
    def formatDate(cls, date, *args, **kwargs):
        try:
            millis = int(date) * 1000
            return SimpleDateFormat("MMM d, yyyy").format(millis)
        except Exception:
            return ""

    @classmethod
    def formatTime(cls, date, *args, **kwargs):
        try:
            millis = int(date) * 1000
            return SimpleDateFormat("HH:mm").format(millis)
        except Exception:
            return ""

    @classmethod
    def getInstance(cls, account=0):
        return cls

    @classmethod
    def getCurrentLocale(cls):
        try:
            return Locale.getDefault()
        except Exception:
            return None

    @classmethod
    def formatPluralStringComma(cls, key, quantity, *args):
        text = cls._localized(key)
        try:
            return (text % tuple([quantity] + list(args))).replace(",", "")
        except Exception:
            return str(quantity)

    @classmethod
    def formatPluralStringSpaced(cls, key, quantity, *args):
        text = cls._localized(key)
        try:
            return text % tuple([quantity] + list(args))
        except Exception:
            return str(quantity)

    @classmethod
    def formatNumber(cls, number, *args):
        try:
            return "{:,}".format(int(number)).replace(",", " ")
        except Exception:
            return str(number)

    @classmethod
    def formatNumberWithMillion(cls, number, *args):
        value = float(number or 0)
        if value >= 1_000_000:
            return "%.1fM" % (value / 1_000_000.0)
        return cls.formatNumber(value)

    @classmethod
    def formatDuration(cls, seconds, *args):
        return AndroidUtilities.getDurationString(seconds)

    @classmethod
    def formatCallDuration(cls, seconds, *args):
        return AndroidUtilities.getDurationString(seconds)

    @classmethod
    def formatShortDuration(cls, seconds, *args):
        value = int(seconds or 0)
        if value >= 3600:
            return "%d:%02d:%02d" % (
                value // 3600,
                (value % 3600) // 60,
                value % 60,
            )
        return "%d:%02d" % (value // 60, value % 60)

    @classmethod
    def formatShortDuration2(cls, seconds, *args):
        return cls.formatShortDuration(seconds)

    @classmethod
    def formatDateChat(cls, date, *args):
        try:
            import datetime as _datetime

            value = int(date)
            if value < 100_000_000_000:
                value *= 1000
            return _datetime.datetime.fromtimestamp(value / 1000.0).strftime(
                "%d.%m.%Y"
            )
        except Exception:
            return ""

    @classmethod
    def formatShortDate(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatDateTime(cls, date, *args):
        try:
            import datetime as _datetime

            value = int(date)
            if value < 100_000_000_000:
                value *= 1000
            return _datetime.datetime.fromtimestamp(value / 1000.0).strftime(
                "%d.%m.%Y %H:%M"
            )
        except Exception:
            return ""

    @classmethod
    def formatShortDateTime(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatRelativeDate(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatSectionDate(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatYearMonthDay(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatYearMont(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatTTLString(cls, seconds, *args):
        return cls.formatShortDuration(seconds)

    @classmethod
    def formatStringSimple(cls, key, *args):
        return cls._localized(key)

    @classmethod
    def getServerString(cls, key, *args):
        return cls._localized(key)

    @classmethod
    def nullable(cls, value, *args):
        return "" if value is None else str(value)

    @classmethod
    def fixNumbers(cls, value, *args):
        translation = str.maketrans(
            "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"
        )
        return str(value or "").translate(translation)

    @classmethod
    def getLanguageFlag(cls, *args):
        return ""

    @classmethod
    def getSystemLocaleStringIso639(cls, *args):
        try:
            import locale

            return locale.getdefaultlocale()[0] or "en"
        except Exception:
            return "en"

    @classmethod
    def getLocaleStringIso639(cls, *args):
        return cls.getSystemLocaleStringIso639()

    @classmethod
    def getCurrentLanguageName(cls, *args):
        return cls.getSystemLocaleStringIso639()

    @classmethod
    def isRTLCharacter(cls, character, *args):
        try:
            code = ord(str(character)[0])
        except Exception:
            return False
        return (
            0x0590 <= code <= 0x08FF
            or 0xFB1D <= code <= 0xFDFF
            or 0xFE70 <= code <= 0xFEFF
        )

    @classmethod
    def stringForMessageListDate(cls, date, *args):
        try:
            import datetime as _datetime

            value = int(date)
            if value > 100_000_000_000:
                value = value // 1000
            moment = _datetime.datetime.fromtimestamp(value)
            now = _datetime.datetime.now()
            if moment.date() == now.date():
                return moment.strftime("%H:%M")
            return moment.strftime("%d.%m.%Y")
        except Exception:
            return ""

    @classmethod
    def formatStartsTime(cls, date, *args):
        return cls.formatTime(date)

    @classmethod
    def formatDateOnline(cls, date, *args):
        return cls.formatDate(date)

    @classmethod
    def addNbsp(cls, value, *args):
        return str(value or "").replace(" ", "\u00a0")

    @classmethod
    def bold(cls, value, *args):
        return str(value or "")

    @classmethod
    def formatSpannable(cls, key, *args):
        return cls._localized(key)

    @classmethod
    def formatPluralSpannable(cls, key, quantity, *args):
        return cls.formatPluralString(key, quantity, *args)

    class LocaleInfo:
        def __init__(self, code="en"):
            self.code = str(code or "en")
            parts = self.code.replace("-", "_").split("_", 1)
            self.language = parts[0]
            self.country = parts[1] if len(parts) > 1 else ""
            self.name = self.code
            self.shortName = self.code
            self.pluralForm = 0

        def getLanguageCode(self):
            return self.language

        def getCountryCode(self):
            return self.country

        def getBaseLanguageCode(self):
            return self.language

        def getPluralForm(self):
            return self.pluralForm

        def isRtl(self):
            return self.language in ("ar", "fa", "he", "ku", "ps", "ur")

        def __str__(self):
            return self.name

        def __repr__(self):
            return "<LocaleInfo %s>" % self.code

    @classmethod
    def getCurrentLocaleInfo(cls, *args):
        return cls.LocaleInfo(cls.getSystemLocaleStringIso639())

    @classmethod
    def getCurrentLocale(cls, *args):
        code = cls.getSystemLocaleStringIso639()
        try:
            return Locale.forLanguageTag(code)
        except Exception:
            return None

    @classmethod
    def getLangCode(cls, *args):
        return cls.getSystemLocaleStringIso639()

    @classmethod
    def getBaseLangCode(cls, *args):
        return cls.getSystemLocaleStringIso639().split("-")[0].split("_")[0]

    @classmethod
    def getKey(cls, *args):
        return ""

    @classmethod
    def getSystemDefaultLocale(cls, *args):
        return cls.getSystemLocaleStringIso639()

    @classmethod
    def getTimeZoneName(cls, *args):
        try:
            import time

            return time.tzname[0] or "UTC"
        except Exception:
            return "UTC"

    @classmethod
    def getUseImperialSystemType(cls, *args):
        return 0

    @classmethod
    def quantityForNumber(cls, key, quantity, *args):
        value = abs(int(quantity or 0))
        if value == 1:
            return 0
        if value == 2:
            return 1
        if value in (3, 4):
            return 2
        return 3

    @classmethod
    def getTranslitString(cls, text, *args):
        import unicodedata

        normalized = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )

    _COUNTRY_NAMES = {
        "US": "United States",
        "GB": "United Kingdom",
        "RU": "Russia",
        "DE": "Germany",
        "FR": "France",
        "ES": "Spain",
        "IT": "Italy",
        "UA": "Ukraine",
        "BY": "Belarus",
        "KZ": "Kazakhstan",
        "TR": "Turkey",
        "CN": "China",
        "JP": "Japan",
        "KR": "South Korea",
        "IN": "India",
        "BR": "Brazil",
        "CA": "Canada",
        "AU": "Australia",
    }

    @classmethod
    def getCountryName(cls, code, *args):
        value = str(code or "").upper()
        return cls._COUNTRY_NAMES.get(value, value)

    @classmethod
    def getCountryWithFlag(cls, code, *args):
        from org.telegram.messenger import LocationController

        return "%s %s" % (
            LocationController.countryCodeToEmoji(code),
            cls.getCountryName(code),
        )

    @classmethod
    def formatDistance(cls, distance, type=0, *args):
        value = float(distance or 0.0)
        if type == 1 or value >= 1000:
            return "%.1f km" % (value / 1000.0) if value >= 1000 else "%d m" % value
        return "%d m" % int(value)

    @classmethod
    def formatDateAudio(cls, date, *args):
        return cls.formatDate(date)

    @classmethod
    def formatDateCallLog(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatSeenDate(cls, date, *args):
        return cls.formatTime(date)

    @classmethod
    def formatJoined(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatPmEditedDate(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatPmFwdDate(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatPmSeenDate(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatPmSentDate(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatPollEndTime(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatLocationLeftTime(cls, seconds, *args):
        return cls.formatShortDuration(seconds)

    @classmethod
    def formatLocationUpdateDate(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatSmallDateChat(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatStoryDate(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatTodoCompletedDate(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatGroupMemberJoined(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatImportedDate(cls, date, *args):
        return cls.formatDateChat(date)

    @classmethod
    def formatStatusExpireDateTime(cls, date, *args):
        return cls.formatDateTime(date)

    @classmethod
    def formatDateForBan(cls, date, *args):
        return cls.formatDateTime(date)


_UI_TASK_HANDLES = {}


class AndroidUtilities(metaclass=_TolerantClassMeta):
    density = 3.0
    TYPEFACE_ROBOTO_REGULAR = "default"
    TYPEFACE_ROBOTO_MEDIUM = "default-bold"
    TYPEFACE_ROBOTO_LIGHT = "default-light"

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.messenger.AndroidUtilities")

    @staticmethod
    def decelerateInterpolator():
        return DecelerateInterpolator()

    @staticmethod
    def accelerateInterpolator():
        try:
            return AccelerateInterpolator()
        except NameError:
            return DecelerateInterpolator()

    @staticmethod
    def linearInterpolator():
        try:
            return LinearInterpolator()
        except NameError:
            return DecelerateInterpolator()

    @staticmethod
    def runOnUIThread(function, delay=0):
        if hasattr(function, "run"):
            function = function.run
        import extera_ios

        handle = extera_ios.run_on_ui_thread(function, delay)
        if handle is not None:
            _UI_TASK_HANDLES[id(function)] = handle
        return handle

    @staticmethod
    def cancelRunOnUIThread(function):
        if hasattr(function, "run"):
            function = function.run
        handle = _UI_TASK_HANDLES.pop(id(function), None)
        if handle is None:
            return None
        try:
            import extera_ios

            return extera_ios.cancel_ui_task(handle)
        except Exception:
            return None

    @staticmethod
    def dp(value):
        return value

    @staticmethod
    def px(value):
        return value

    @staticmethod
    def isTablet():
        return False

    @staticmethod
    def isSmallTablet():
        return False

    @staticmethod
    def isSmallScreen():
        return False

    @staticmethod
    def addToClipboard(text):
        try:
            import extera_ios

            extera_ios.copy_to_clipboard(str(text))
            return True
        except Exception:
            return False

    @staticmethod
    def getPhotoSize(high_quality=False):
        return 2560 if high_quality else 1280

    @staticmethod
    def formatFileSize(size):
        return Utilities.readableFileSize(size)

    @staticmethod
    def getMinuteOfDay(hour, minute):
        return int(hour) * 60 + int(minute)

    @staticmethod
    def showKeyboard(view):
        return None

    @staticmethod
    def hideKeyboard(view):
        return None

    @staticmethod
    def shakeViewSpring(view, *args, **kwargs):
        return None

    @staticmethod
    def dpf(value):
        return float(value or 0)

    @staticmethod
    def formatDuration(seconds):
        return AndroidUtilities.getDurationString(seconds)

    @staticmethod
    def getDurationString(seconds):
        try:
            total = max(0, int(seconds or 0))
        except (TypeError, ValueError):
            total = 0
        return "%d:%02d" % (total // 60, total % 60)

    @staticmethod
    def replaceTags(text):
        import re

        return re.sub(r"<[^>]+>", "", str(text or ""))

    @staticmethod
    def isEmpty(value):
        return value is None or len(value) == 0

    @staticmethod
    def isRTL():
        return False

    @staticmethod
    def getStatusBarHeight():
        return 44

    @staticmethod
    def getNavigationBarHeight():
        return 0

    @staticmethod
    def getShadowHeight():
        return 0

    @staticmethod
    def getCurrentTime():
        return int(time.time() * 1000)

    @staticmethod
    def openUrl(url, *args, **kwargs):
        try:
            import extera_ios

            extera_ios.open_url(str(url))
            return True
        except Exception:
            return False

    @staticmethod
    def openTelegramLink(url):
        return AndroidUtilities.openUrl(url)

    @staticmethod
    def copyText(text):
        return AndroidUtilities.addToClipboard(text)

    @staticmethod
    def getColor(key):
        return _theme_color(key)

    @staticmethod
    def bold():
        return Typeface.DEFAULT_BOLD

    @staticmethod
    def medium():
        return Typeface.DEFAULT

    @staticmethod
    def getTypeface(font):
        return Typeface.DEFAULT

    @staticmethod
    def removeDiacritics(text):
        import unicodedata

        normalized = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )

    @staticmethod
    def removeRTL(text):
        return "".join(
            character
            for character in str(text or "")
            if not ("\u0590" <= character <= "\u08ff")
        )

    @staticmethod
    def getOffset(x, y):
        return int(x) + int(y)

    @staticmethod
    def dp2(value):
        return float(value or 0) * 2.0

    @staticmethod
    def dpf2(value):
        return float(value or 0) * 2.0

    @staticmethod
    def dpr(value):
        return float(value or 0)

    @staticmethod
    def formatCount(count):
        value = int(count or 0)
        if value >= 1_000_000:
            return "%.1fM" % (value / 1_000_000.0)
        if value >= 1000:
            return "%.1fK" % (value / 1000.0)
        return str(value)

    @staticmethod
    def formatWholeNumber(number):
        try:
            return "{:,}".format(int(number)).replace(",", " ")
        except (TypeError, ValueError):
            return str(number)

    @staticmethod
    def formatLongDuration(seconds, *args):
        value = int(seconds or 0)
        hours = value // 3600
        minutes = (value % 3600) // 60
        secs = value % 60
        if hours:
            return "%d:%02d:%02d" % (hours, minutes, secs)
        return "%d:%02d" % (minutes, secs)

    @staticmethod
    def formatShortDuration(seconds, *args):
        value = int(seconds or 0)
        if value >= 3600:
            return "%d:%02d:%02d" % (value // 3600, (value % 3600) // 60, value % 60)
        return "%d:%02d" % (value // 60, value % 60)

    @staticmethod
    def formatVideoDuration(seconds, *args):
        return AndroidUtilities.formatLongDuration(seconds)

    @staticmethod
    def formatVideoDurationFast(seconds, *args):
        return AndroidUtilities.formatLongDuration(seconds)

    @staticmethod
    def formatFullDuration(seconds, *args):
        return AndroidUtilities.formatLongDuration(seconds)

    @staticmethod
    def formatDurationNoHours(seconds, *args):
        value = int(seconds or 0)
        return "%d:%02d" % (value // 60, value % 60)

    @staticmethod
    def formatTimerDurationFast(seconds, *args):
        return AndroidUtilities.formatLongDuration(seconds)

    @staticmethod
    def formatTimestamp(seconds, *args):
        return AndroidUtilities.formatLongDuration(seconds)

    @staticmethod
    def ellipsize(text, max_length=0, *args):
        value = str(text or "")
        limit = int(max_length or 0)
        if limit <= 0 or len(value) <= limit:
            return value
        if limit <= 3:
            return value[:limit]
        return value[: limit - 3] + "..."

    @staticmethod
    def ellipsizeCenterEnd(text, max_length=0, *args):
        value = str(text or "")
        limit = int(max_length or 0)
        if limit <= 0 or len(value) <= limit:
            return value
        if limit <= 3:
            return value[:limit]
        left = (limit - 3) // 2
        right = limit - 3 - left
        return value[:left] + "..." + value[-right:]

    @staticmethod
    def generateFileName(extension="", *args):
        import random
        import string

        suffix = "".join(
            random.choice(string.ascii_lowercase + string.digits) for _ in range(12)
        )
        name = "file_%s_%s" % (int(time.time() * 1000), suffix)
        ext = str(extension or "").lstrip(".")
        return name + ("." + ext if ext else "")

    @staticmethod
    def generatePicturePath(*args):
        return os.path.join(_path_for("images"), AndroidUtilities.generateFileName("jpg"))

    @staticmethod
    def generateVideoPath(*args):
        return os.path.join(_path_for("videos"), AndroidUtilities.generateFileName("mp4"))

    @staticmethod
    def copyFile(source, destination, *args):
        try:
            with open(str(source), "rb") as reader:
                data = reader.read()
            with open(str(destination), "wb") as writer:
                writer.write(data)
            return True
        except Exception:
            return False

    @staticmethod
    def copyFileSafe(source, destination, *args):
        return AndroidUtilities.copyFile(source, destination)

    @staticmethod
    def createEmptyFile(path, *args):
        try:
            with open(str(path), "wb"):
                pass
            return True
        except Exception:
            return False

    @staticmethod
    def getCacheDir(*args):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_CACHE)

    @staticmethod
    def getBuildVersionInfo(*args):
        try:
            import extera_ios

            info = extera_ios.app_info() or {}
            return "%s (%s)" % (
                info.get("version") or "",
                info.get("build") or "",
            )
        except Exception:
            return ""

    @staticmethod
    def distance(x1, y1, x2, y2):
        return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

    @staticmethod
    def compare(a, b):
        return (a > b) - (a < b)

    @staticmethod
    def computePerceivedBrightness(color):
        value = int(color or 0)
        red = (value >> 16) & 0xFF
        green = (value >> 8) & 0xFF
        blue = value & 0xFF
        return (0.299 * red + 0.587 * green + 0.114 * blue) / 255.0


class _DisplaySize:
    x = 1080
    y = 1920


AndroidUtilities.displaySize = _DisplaySize()


class DisplayMetrics:
    def __init__(self):
        self.widthPixels = 1080
        self.heightPixels = 1920
        self.density = 3.0
        self.densityDpi = 480
        self.scaledDensity = 3.0
        self.xdpi = 480.0
        self.ydpi = 480.0


class Configuration:
    ORIENTATION_UNDEFINED = 0
    ORIENTATION_PORTRAIT = 1
    ORIENTATION_LANDSCAPE = 2
    UI_MODE_TYPE_NORMAL = 1
    UI_MODE_TYPE_DESK = 2
    UI_MODE_TYPE_CAR = 3
    UI_MODE_TYPE_TELEVISION = 4
    UI_MODE_TYPE_APPLIANCE = 5
    UI_MODE_TYPE_WATCH = 6
    UI_MODE_NIGHT_NO = 16
    UI_MODE_NIGHT_YES = 32

    def __init__(self):
        self.orientation = Configuration.ORIENTATION_PORTRAIT
        self.screenWidthDp = 360
        self.screenHeightDp = 640
        self.smallestScreenWidthDp = 360
        self.densityDpi = 480
        self.fontScale = 1.0
        self.uiMode = Configuration.UI_MODE_TYPE_NORMAL | Configuration.UI_MODE_NIGHT_NO
        self.locale = None


def _resource_string(identifier, *args):
    if isinstance(identifier, int):
        text = "Telegram"
    else:
        name = str(identifier or "")
        if name.startswith("R.string."):
            name = name[len("R.string."):]
        mapping = {
            "app_name": "Telegram",
            "Continue": "Continue",
            "Cancel": "Cancel",
            "OK": "OK",
            "Delete": "Delete",
            "Save": "Save",
            "Settings": "Settings",
            "Plugins": "Plugins",
        }
        text = mapping.get(name, name if name and not name.startswith("0x") else "Telegram")
    if args:
        try:
            return text % tuple(args)
        except Exception:
            pass
    return text


class ApplicationInfo:
    def __init__(self, package_name="org.telegram.Telegram"):
        self.packageName = str(package_name)
        self.labelRes = 0x7F0F0001
        self.iconRes = 0x7F0E0001
        self.theme = 0
        self.flags = 0
        self.uid = 0
        self.className = ""
        self.processName = self.packageName
        self.enabled = True
        self.targetSdkVersion = 34
        self.minSdkVersion = 21
        self.name = "Telegram"


class ColorStateList:
    def __init__(self, states=None, colors=None):
        self.states = list(states or [])
        self.colors = [int(color) for color in (colors or [])]

    @classmethod
    def valueOf(cls, color):
        return cls([], [int(color or 0)])

    def getDefaultColor(self):
        return self.colors[0] if self.colors else 0

    def getColorForState(self, stateSet=None, defaultColor=0):
        return self.getDefaultColor() if self.colors else int(defaultColor or 0)

    def isStateful(self):
        return len(self.colors) > 1

    def withAlpha(self, alpha):
        value = int(alpha or 0) & 0xFF
        return ColorStateList(
            self.states,
            [((color & 0x00FFFFFF) | (value << 24)) for color in self.colors],
        )


class Resources:
    def __init__(self):
        self._metrics = DisplayMetrics()
        self._configuration = Configuration()

    def getDisplayMetrics(self):
        return self._metrics

    def getConfiguration(self):
        return self._configuration

    def getDimension(self, identifier):
        return 0.0

    def getDimensionPixelSize(self, identifier):
        return 0

    def getDimensionPixelOffset(self, identifier):
        return 0

    def getString(self, identifier, *args):
        return _resource_string(identifier, *args)

    def getColor(self, identifier):
        return 0

    def getDrawable(self, identifier):
        return None

    def getIdentifier(self, name, defType, defPackage):
        return 0


class TypedValue:
    COMPLEX_UNIT_PX = 0
    COMPLEX_UNIT_DIP = 1
    COMPLEX_UNIT_SP = 2
    COMPLEX_UNIT_PT = 3
    COMPLEX_UNIT_IN = 4
    COMPLEX_UNIT_MM = 5

    @staticmethod
    def applyDimension(unit, value, metrics=None):
        return float(value)

    @staticmethod
    def complexToDimensionPixelSize(unit, value):
        return int(round(float(value)))

    @staticmethod
    def complexToFloat(value):
        return float(value)


class _Random:
    """`Utilities.random`, the `java.util.Random` plugins call nextInt on."""

    def nextInt(self, bound=None):
        if bound is None:
            return _random.randint(-2147483648, 2147483647)
        return _random.randrange(max(1, int(bound)))

    def nextLong(self):
        return _random.randint(-9223372036854775808, 9223372036854775807)

    def nextFloat(self):
        return _random.random()

    def nextDouble(self):
        return _random.random()

    def nextBoolean(self):
        return bool(_random.getrandbits(1))

    def nextGaussian(self):
        return _random.gauss(0, 1)

    def setSeed(self, seed):
        _random.seed(seed)

    def __call__(self, minimum=0, maximum=None):
        if maximum is None:
            return self.nextInt(minimum) if minimum else self.nextInt()
        return _random.randint(int(minimum), int(maximum))


class Utilities(metaclass=_TolerantClassMeta):
    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.messenger.Utilities")

    @staticmethod
    def parseInt(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def parseLong(value, default=0):
        return Utilities.parseInt(value, default)

    @staticmethod
    def parseDouble(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def parseFloat(value, default=0.0):
        return Utilities.parseDouble(value, default)

    @staticmethod
    def parseBoolean(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes")
        return bool(value)

    @staticmethod
    def isEmpty(value):
        return value is None or len(value) == 0

    @staticmethod
    def readableFileSize(size):
        size = float(size or 0)
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024.0
            index += 1
        if index == 0:
            return "%d %s" % (int(size), units[index])
        return "%.1f %s" % (size, units[index])

    @staticmethod
    def getFileExtension(path):
        name = str(path or "")
        separator = name.rfind(".")
        return name[separator + 1:].lower() if separator >= 0 else ""

    @staticmethod
    def readFile(path):
        try:
            with open(str(path), "rb") as handle:
                return handle.read()
        except Exception:
            return None

    @staticmethod
    def getDir(path):
        return os.path.dirname(str(path or ""))

    @staticmethod
    def getFileName(path):
        return os.path.basename(str(path or ""))

    @staticmethod
    def copyFile(source, destination):
        try:
            with open(str(source), "rb") as handle:
                data = handle.read()
            with open(str(destination), "wb") as handle:
                handle.write(data)
            return True
        except Exception:
            return False

    @staticmethod
    def isValidFileName(name):
        if not name:
            return False
        return not any(character in str(name) for character in ("/", "\\", "\x00"))

    @staticmethod
    def getIntValue(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def getStringValue(value, default=""):
        return default if value is None else str(value)

    @staticmethod
    def getMD5(text):
        import hashlib

        return hashlib.md5(str(text).encode("utf-8")).hexdigest()

    @staticmethod
    def getSha256(text):
        import hashlib

        return hashlib.sha256(str(text).encode("utf-8")).hexdigest()

    @staticmethod
    def clamp(value, minimum, maximum):
        return max(minimum, min(maximum, value))

    @staticmethod
    def lerp(start, end, amount):
        return start + (end - start) * amount

    @staticmethod
    def currentTimeMillis():
        return int(time.time() * 1000)

    @staticmethod
    def getFileSize(path):
        try:
            return os.path.getsize(str(path))
        except OSError:
            return 0

    @staticmethod
    def isValidPhone(phone):
        digits = "".join(character for character in str(phone or "") if character.isdigit())
        return 7 <= len(digits) <= 15

    @staticmethod
    def join(separator, values):
        return str(separator).join(str(value) for value in (values or []))

    @staticmethod
    def formatDate(timestamp, *args, **kwargs):
        try:
            import datetime as _datetime

            return _datetime.datetime.fromtimestamp(int(timestamp)).strftime("%d.%m.%Y")
        except Exception:
            return ""

    @staticmethod
    def getDurationString(seconds):
        return AndroidUtilities.getDurationString(seconds)

    # -- Android `Utilities` static API ------------------------------------
    @staticmethod
    def MD5(value):
        import hashlib

        return hashlib.md5(str(value).encode("utf-8")).digest()

    @staticmethod
    def SHA256(value):
        import hashlib

        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    @staticmethod
    def bytesToHex(bytes_):
        return "".join("%02x" % (byte & 0xFF) for byte in (bytes_ or b""))

    @staticmethod
    def hexToBytes(hex_):
        value = str(hex_ or "")
        if len(value) % 2:
            value = "0" + value
        try:
            return bytes.fromhex(value)
        except ValueError:
            return b""

    @staticmethod
    def bytesToInt(bytes_):
        value = bytes(bytes_ or b"")
        if len(value) < 4:
            value = value + b"\x00" * (4 - len(value))
        return int.from_bytes(value[:4], "little", signed=True)

    @staticmethod
    def bytesToLong(bytes_):
        value = bytes(bytes_ or b"")
        if len(value) < 8:
            value = value + b"\x00" * (8 - len(value))
        return int.from_bytes(value[:8], "little", signed=True)

    @staticmethod
    def intToBytes(value):
        return int(value or 0).to_bytes(4, "little", signed=True)

    @staticmethod
    def getExtension(file_name):
        name = str(file_name or "")
        separator = name.rfind(".")
        return name[separator + 1:].lower() if separator >= 0 else ""

    @staticmethod
    def isNullOrEmpty(value):
        return value is None or len(value) == 0

    @staticmethod
    def parseIntToString(value):
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value)[:1] or "0"

    @staticmethod
    def clamp01(value):
        return max(0.0, min(1.0, float(value or 0.0)))

    @staticmethod
    def divCeil(a, b):
        return -(-int(a) // int(b)) if b else 0

    @staticmethod
    def dist(x1, y1, x2, y2):
        return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

    @staticmethod
    def generateRandomString(chars=10):
        import random
        import string

        alphabet = string.ascii_letters + string.digits
        return "".join(random.choice(alphabet) for _ in range(int(chars or 10)))

    @staticmethod
    def computePBKDF2(password, salt):
        import hashlib

        return hashlib.pbkdf2_hmac(
            "sha512",
            bytes(password or b""),
            bytes(salt or b"2099900658"),
            100000,
            64,
        )

    @staticmethod
    def computeSHA1(value):
        import hashlib

        if isinstance(value, (bytes, bytearray, memoryview)):
            data = bytes(value)
        else:
            data = bytes(getattr(value, "array", b"") or b"")
        return hashlib.sha1(data).digest()

    @staticmethod
    def computeSHA256(value, *args):
        import hashlib

        if isinstance(value, tuple):
            data = b"".join(bytes(item) for item in value)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            data = bytes(value)
        else:
            data = bytes(getattr(value, "array", b"") or b"")
        if args and isinstance(value, (bytes, bytearray)):
            offset = int(args[0] or 0)
            length = int(args[1]) if len(args) > 1 and args[1] is not None else len(data) - offset
            data = data[offset:offset + length]
        return hashlib.sha256(data).digest()

    @staticmethod
    def computeSHA512(value, *others):
        import hashlib

        chunks = []
        for item in (value,) + others:
            if isinstance(item, (bytes, bytearray, memoryview)):
                chunks.append(bytes(item))
            elif isinstance(item, str):
                chunks.append(item.encode("utf-8"))
        return hashlib.sha512(b"".join(chunks)).digest()

    @staticmethod
    def tryParseLong(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def arraysEquals(arr1, offset1, arr2, offset2):
        try:
            return bytes(arr1)[int(offset1):] == bytes(arr2)[int(offset2):]
        except Exception:
            return False

    @staticmethod
    def swapItems(values, index1, index2):
        try:
            values[int(index1)], values[int(index2)] = (
                values[int(index2)],
                values[int(index1)],
            )
        except Exception:
            pass
        return values

    @staticmethod
    def getDirSize(path):
        total = 0
        for root, _, files in os.walk(str(path or ".")):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total

    @staticmethod
    def clearDir(path):
        try:
            for entry in os.listdir(str(path)):
                item = os.path.join(str(path), entry)
                if os.path.isdir(item):
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    os.remove(item)
        except OSError:
            pass
        return None

    @staticmethod
    def getLastUsageFileTime(path):
        try:
            return int(os.path.getatime(str(path)) * 1000)
        except OSError:
            return 0


class _CallbackBase:
    def __init__(self, function=None):
        self._function = function

    def run(self, *args):
        if self._function is None:
            return None
        return self._function(*args)

    def __call__(self, *args):
        return self.run(*args)


class _CallbackReturn(_CallbackBase):
    pass


Utilities.Callback = _CallbackBase
Utilities.Callback2 = _CallbackBase
Utilities.Callback3 = _CallbackBase
Utilities.Callback4 = _CallbackBase
Utilities.Callback5 = _CallbackBase
Utilities.CallbackVoidReturn = _CallbackBase
Utilities.Callback0Return = _CallbackReturn
Utilities.CallbackReturn = _CallbackReturn
Utilities.Callback2Return = _CallbackReturn
Utilities.Callback3Return = _CallbackReturn
Utilities.Callback4Return = _CallbackReturn
Utilities.Callback5Return = _CallbackReturn


class _GlobalQueue:
    """`Utilities.globalQueue` / `pluginsQueue` posting onto the iOS main queue."""

    def __init__(self, name="globalQueue"):
        self.name = name

    def postRunnable(self, runnable, delay=0):
        try:
            import extera_ios

            callback = runnable.run if hasattr(runnable, "run") else runnable
            return extera_ios.run_on_ui_thread(callback, delay)
        except Exception:
            return None

    def cancelRunnable(self, handle):
        try:
            import extera_ios

            extera_ios.cancel_ui_task(handle)
        except Exception:
            pass


Utilities.globalQueue = _GlobalQueue("globalQueue")
Utilities.pluginsQueue = _GlobalQueue("pluginsQueue")
Utilities.searchQueue = _GlobalQueue("searchQueue")
Utilities.random = _Random()
Utilities.getQueueByName = staticmethod(lambda name: _GlobalQueue(str(name)))


class IndexedConsumer(_CallbackBase):
    def accept(self, value, index):
        return self.run(value, index)


class Runnable(_CallbackBase):
    def run(self):
        if self._function is None:
            return None
        return self._function()


class _MessageObjectMeta(type):
    def __instancecheck__(cls, instance):
        try:
            if MessageObject in type(instance).__mro__:
                return True
        except Exception:
            pass
        if not isinstance(instance, dict):
            return False
        return any(
            key in instance
            for key in ("messageOwner", "message", "dialog_id", "peer_id",
                        "message_id", "id", "from_id", "date")
        )


class MessageObject(metaclass=_MessageObjectMeta):
    """`MessageObject` stand-in.

    The host passes messages as dictionaries (`AttrDict`), so `isinstance`
    accepts them and the common getters read the same fields. A real
    `MessageObject` instance wraps one dictionary.
    """

    def __init__(self, value=None, *args, **kwargs):
        # Android constructs `MessageObject(int currentAccount, TLRPC.Message
        # message, ...)`; accept that overload as well as a dict or another
        # `MessageObject`.  `_MessageObjectMeta.__instancecheck__` also accepts
        # dictionaries, so test for the wrapped dict explicitly.
        if isinstance(value, int):
            value = args[0] if args else None
        if not isinstance(value, dict):
            inner = getattr(value, "_value", None)
            if isinstance(inner, dict):
                value = inner
        self._value = value if isinstance(value, dict) else dict(kwargs)

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.messenger.MessageObject")

    def __getattr__(self, name):
        value = self.__dict__.get("_value", {})
        if name == "messageOwner":
            return value
        if name in value:
            return value[name]
        # The same defaults a hook payload gets (`_extera_runtime.AttrDict`):
        # an absent flag reads as false and an absent getter as null, so a
        # plugin's `if message.isMediaEmpty():` keeps working.
        if name[:2] == "is" and name[2:3].isupper():
            return lambda *args, **kwargs: False
        if name[:3] == "can" and name[3:4].isupper():
            return lambda *args, **kwargs: False
        if name[:3] == "get" and name[3:4].isupper():
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def _field(self, *names):
        for name in names:
            value = self._value.get(name)
            if value is not None:
                return value
        return None

    def getId(self):
        return self._field("id", "message_id") or 0

    def getDialogId(self):
        return self._field("dialog_id", "peer_id") or 0

    def getPeerId(self):
        return self.getDialogId()

    def getFromId(self):
        return self._field("from_id", "sender_id", "from") or 0

    def getSenderId(self):
        return self.getFromId()

    def isOut(self):
        return bool(self._field("out", "is_out"))

    def isOutOwner(self):
        return self.isOut()

    def getMessageText(self):
        return self._field("message", "text")

    def getDocument(self):
        document = self._field("document")
        if isinstance(document, dict):
            return document
        media = self._field("media")
        if isinstance(media, dict):
            nested = media.get("document")
            if isinstance(nested, dict):
                return nested
        return None

    def getDocumentName(self):
        document = self.getDocument()
        if isinstance(document, dict):
            return document.get("file_name") or document.get("name")
        return self._field("file_name")

    def getPhoto(self):
        photo = self._field("photo")
        if isinstance(photo, dict):
            return photo
        media = self._field("media")
        if isinstance(media, dict):
            nested = media.get("photo")
            if isinstance(nested, dict):
                return nested
        return None

    def getMedia(self):
        return self._field("media")

    def isMediaEmpty(self):
        return self._field("media") is None

    def isUnread(self):
        return bool(self._field("unread", "is_unread"))

    def getDate(self):
        return self._field("date") or 0

    def getRealDate(self):
        return self.getDate()

    def isForwarded(self):
        return self._field("fwd_from") is not None

    def isReply(self):
        return self._field("reply_to") is not None or self._field("reply_to_msg_id") is not None

    def getReplyMsgId(self):
        reply = self._field("reply_to")
        if isinstance(reply, dict):
            return reply.get("reply_to_msg_id") or reply.get("reply_to_id") or 0
        return self._field("reply_to_msg_id", "reply_to") or 0

    def isSending(self):
        return bool(self._field("sending", "is_sending"))

    def isEditingMessage(self):
        return bool(self._field("editing", "is_editing"))

    def isDeleted(self):
        return bool(self._field("deleted", "is_deleted"))

    def getMessageOwner(self):
        return self._value

    def isVoice(self):
        return message_fields.is_voice(self._value)

    def isMusic(self):
        return message_fields.is_music(self._value)

    def isVideo(self):
        return message_fields.is_video(self._value)

    def isRoundVideo(self):
        return message_fields.is_round_video(self._value)

    def isGif(self):
        return message_fields.is_gif(self._value)

    def isSticker(self):
        return message_fields.is_sticker(self._value)

    def isPhoto(self):
        return message_fields.is_photo(self._value)

    def isDocument(self):
        return message_fields.is_document(self._value)

    def hasPhoto(self):
        return message_fields.has_photo(self._value)

    def hasDocument(self):
        return message_fields.has_document(self._value)

    def getMediaDuration(self):
        return message_fields.media_duration(self._value)

    def getFileName(self):
        return message_fields.file_name(self._value)

    def getFileSize(self):
        return message_fields.file_size(self._value)

    def getMediaSize(self):
        return message_fields.file_size(self._value)

    def getDocumentSize(self):
        return message_fields.file_size(self._value)

    def canForwardMessage(self):
        return not bool(self._field("noforwards", "no_forwards"))

    def canEditMessage(self):
        if self._field("edit_hide", "edit_hidden"):
            return False
        return True

    def canDeleteMessage(self):
        return not bool(self._field("noforwards", "no_forwards"))

    def isScheduled(self):
        return bool(self._field("scheduled", "is_scheduled"))

    def isSponsored(self):
        return bool(self._field("sponsored", "is_sponsored"))

    def isSecret(self):
        return bool(self._field("secret", "is_secret"))

    def getApproximateHeight(self):
        return 0

    # -- peer/id helpers ----------------------------------------------------
    def getFromChatId(self, *args, **kwargs):
        return self.getFromId()

    def getChatId(self, *args, **kwargs):
        dialog_id = self.getDialogId()
        return dialog_id if dialog_id < 0 else 0

    def getChannelId(self, *args, **kwargs):
        value = self._field("channel_id")
        if value is not None:
            return int(value)
        dialog_id = self.getDialogId()
        return -dialog_id if dialog_id < 0 else 0

    def getSavedDialogId(self, *args, **kwargs):
        value = self._field("saved_dialog_id", "saved_peer")
        if isinstance(value, dict):
            return value.get("id") or 0
        return value or 0

    def getTopicId(self, *args, **kwargs):
        reply = self._field("reply_to")
        if isinstance(reply, dict) and reply.get("forum_topic_id") is not None:
            return int(reply["forum_topic_id"])
        return int(self._field("topic_id") or 0)

    def getGroupId(self, *args, **kwargs):
        return self._field("grouped_id", "group_id") or 0

    def getGroupIdForUse(self, *args, **kwargs):
        return self.getGroupId()

    def hasValidGroupId(self, *args, **kwargs):
        return self._field("grouped_id", "group_id") is not None

    def isFromUser(self, *args, **kwargs):
        return not self.isFromChat() and not self.isFromChannel()

    def isFromChat(self, *args, **kwargs):
        return self._field("post", "from_chat") is not None and not self.isFromChannel()

    def isFromChannel(self, *args, **kwargs):
        return bool(self._field("post", "channel_post", "from_channel"))

    def isFromGroup(self, *args, **kwargs):
        return self.isFromChat()

    def isSupergroup(self, *args, **kwargs):
        dialog_id = self.getDialogId()
        return bool(self._field("megagroup", "supergroup")) or (
            dialog_id < 0 and abs(dialog_id) > 1000000000000
        )

    def isPrivateForward(self, *args, **kwargs):
        forwarded = self._field("fwd_from")
        return isinstance(forwarded, dict) and forwarded.get("from_id") is not None

    def isForwardedChannelPost(self, *args, **kwargs):
        forwarded = self._field("fwd_from")
        if not isinstance(forwarded, dict):
            return False
        channel = forwarded.get("channel_post")
        return bool(channel)

    def isImportedForward(self, *args, **kwargs):
        forwarded = self._field("fwd_from")
        return isinstance(forwarded, dict) and forwarded.get("imported") is not None

    def isEdited(self, *args, **kwargs):
        return self._field("edit_date") is not None

    def getMaxEditDate(self, *args, **kwargs):
        return int(self._field("edit_date") or 0)

    # -- replies ------------------------------------------------------------
    def getReplyAnyMsgId(self, *args, **kwargs):
        reply = self._field("reply_to")
        if isinstance(reply, dict):
            for key in ("reply_to_msg_id", "reply_to_top_id"):
                value = reply.get(key)
                if value:
                    return int(value)
        return int(self._field("reply_to_msg_id", "reply_to") or 0)

    def getReplyToDialogId(self, *args, **kwargs):
        reply = self._field("reply_to")
        if isinstance(reply, dict):
            value = reply.get("reply_to_peer_id")
            if isinstance(value, dict):
                return value.get("id") or 0
            if value is not None:
                return int(value)
        return self.getDialogId()

    def getReplyTopMsgId(self, *args, **kwargs):
        reply = self._field("reply_to")
        if isinstance(reply, dict):
            return int(reply.get("reply_to_top_id") or 0)
        return 0

    def hasReplies(self, *args, **kwargs):
        return isinstance(self._field("replies"), dict)

    def getRepliesCount(self, *args, **kwargs):
        replies = self._field("replies")
        if isinstance(replies, dict):
            return int(replies.get("replies") or 0)
        return 0

    def isComments(self, *args, **kwargs):
        replies = self._field("replies")
        return isinstance(replies, dict) and bool(replies.get("comments"))

    # -- documents/media ----------------------------------------------------
    @staticmethod
    def _document_attributes(document):
        if not isinstance(document, dict):
            return []
        values = document.get("attributes")
        return values if isinstance(values, list) else []

    def getDocumentDuration(self, document=None, *args, **kwargs):
        target = document if document is not None else self.getDocument()
        for attribute in self._document_attributes(target):
            if isinstance(attribute, dict) and attribute.get("duration") is not None:
                return int(attribute["duration"])
        return 0

    def _document_attribute(self, key):
        for attribute in self._document_attributes(self.getDocument()):
            if isinstance(attribute, dict) and attribute.get(key) is not None:
                return attribute.get(key)
        return None

    def getMusicTitle(self, *args, **kwargs):
        return self._document_attribute("title") or ""

    def getMusicAuthor(self, *args, **kwargs):
        return self._document_attribute("performer") or ""

    def _sticker_attribute(self):
        for attribute in self._document_attributes(self.getDocument()):
            if isinstance(attribute, dict) and attribute.get("_") == "documentAttributeSticker":
                return attribute
        return {}

    def getStickerChar(self, *args, **kwargs):
        sticker = self._sticker_attribute()
        return sticker.get("alt") or sticker.get("emoticon") or ""

    def getStickerEmoji(self, *args, **kwargs):
        sticker = self._sticker_attribute()
        return sticker.get("emoticon") or sticker.get("alt") or ""

    def getStickerSetName(self, document=None, *args, **kwargs):
        target = document if document is not None else self.getDocument()
        for attribute in self._document_attributes(target):
            if isinstance(attribute, dict) and attribute.get("_") == "documentAttributeSticker":
                sticker_set = attribute.get("stickerset")
                if isinstance(sticker_set, dict):
                    return sticker_set.get("short_name") or ""
        return ""

    def getStickerSetId(self, document=None, *args, **kwargs):
        target = document if document is not None else self.getDocument()
        for attribute in self._document_attributes(target):
            if isinstance(attribute, dict) and attribute.get("_") == "documentAttributeSticker":
                sticker_set = attribute.get("stickerset")
                if isinstance(sticker_set, dict):
                    return int(sticker_set.get("id") or 0)
        return 0

    # -- polls --------------------------------------------------------------
    def _poll_media(self):
        media = self._field("media")
        if isinstance(media, dict) and media.get("_") == "messageMediaPoll":
            return media
        return None

    def isPoll(self, *args, **kwargs):
        return self._poll_media() is not None

    def isQuiz(self, *args, **kwargs):
        media = self._poll_media()
        poll = media.get("poll") if isinstance(media, dict) else None
        return isinstance(poll, dict) and bool(poll.get("quiz"))

    def getPollId(self, *args, **kwargs):
        media = self._poll_media()
        poll = media.get("poll") if isinstance(media, dict) else None
        return int(poll.get("id") or 0) if isinstance(poll, dict) else 0

    def getPollHash(self, *args, **kwargs):
        media = self._poll_media()
        poll = media.get("poll") if isinstance(media, dict) else None
        return poll.get("hash") or 0 if isinstance(poll, dict) else 0

    def isPollClosed(self, *args, **kwargs):
        media = self._poll_media()
        poll = media.get("poll") if isinstance(media, dict) else None
        return isinstance(poll, dict) and bool(poll.get("closed"))

    def isPublicPoll(self, *args, **kwargs):
        media = self._poll_media()
        poll = media.get("poll") if isinstance(media, dict) else None
        return isinstance(poll, dict) and bool(poll.get("public_voters"))

    def isVoted(self, media_poll=None, *args, **kwargs):
        media = media_poll if isinstance(media_poll, dict) else self._poll_media()
        if not isinstance(media, dict):
            return False
        results = media.get("results")
        return isinstance(results, dict) and bool(results.get("results"))

    def hasVoteResults(self, *args, **kwargs):
        return self.isVoted()

    # -- other media --------------------------------------------------------
    def isLocation(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") in (
            "messageMediaGeo", "messageMediaVenue", "messageMediaGeoLive",
        )

    def isLiveLocation(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") == "messageMediaGeoLive"

    def getDuration(self, *args, **kwargs):
        media = self._field("media")
        if isinstance(media, dict):
            document = media.get("document")
            if isinstance(document, dict):
                return self.getDocumentDuration(document)
        return self.getMediaDuration()

    def getEffectId(self, *args, **kwargs):
        return int(self._field("effect") or 0)

    def isGame(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("game") is not None

    def isInvoice(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("invoice") is not None

    def isGiveaway(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") in (
            "messageMediaGiveaway", "messageMediaGiveawayResults",
        )

    def isStory(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") == "messageMediaStory"

    def isTodo(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") in (
            "messageMediaToDo", "messageMediaTodo",
        )

    def isPaid(self, *args, **kwargs):
        media = self._field("media")
        return bool(
            self._field("paid")
            or (isinstance(media, dict) and media.get("paid_media") is not None)
        )

    def isStakeableDice(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") == "messageMediaDice" and (
            media.get("stake") is not None or media.get("stake_amount") is not None
        )

    def getDiceEmoji(self, *args, **kwargs):
        media = self._field("media")
        if isinstance(media, dict) and media.get("_") == "messageMediaDice":
            return media.get("emoticon") or ""
        return ""

    def getDiceValue(self, *args, **kwargs):
        media = self._field("media")
        if isinstance(media, dict) and media.get("_") == "messageMediaDice":
            return int(media.get("value") or 0)
        return 0

    def isContentUnread(self, *args, **kwargs):
        return bool(self._field("media_unread"))

    # -- forwarding ---------------------------------------------------------
    def getForwardedFromId(self, *args, **kwargs):
        forwarded = self._field("fwd_from")
        if not isinstance(forwarded, dict):
            return 0
        peer = forwarded.get("from_id") or forwarded.get("saved_from_peer")
        if isinstance(peer, dict):
            return peer.get("id") or 0
        return int(forwarded.get("saved_from_id") or 0)

    def getForwardedName(self, *args, **kwargs):
        forwarded = self._field("fwd_from")
        if isinstance(forwarded, dict):
            name = forwarded.get("from_name")
            if name:
                return str(name)
        return ""

    def isSecretMedia(self, *args, **kwargs):
        media = self._field("media")
        return bool(
            self.isSecret()
            or (isinstance(media, dict) and media.get("ttl_seconds"))
        )

    # -- peer objects -------------------------------------------------------
    def getFromPeer(self, *args, **kwargs):
        value = self._field("from_id", "sender_id")
        if value is not None:
            return value
        forwarded = self._field("fwd_from")
        if isinstance(forwarded, dict):
            return forwarded.get("from_id")
        return None

    def getFromPeerObject(self, *args, **kwargs):
        peer = self.getFromPeer()
        data = _peer_dict(peer)
        identifier = data.get("id") if data else (
            peer if isinstance(peer, int) else None
        )
        if identifier is None:
            return None
        try:
            from org.telegram.messenger import MessagesController

            return MessagesController.getInstance(0).getUserOrChat(identifier)
        except Exception:
            return None

    def getPeerObject(self, *args, **kwargs):
        dialog_id = self.getDialogId()
        try:
            from org.telegram.messenger import MessagesController

            return MessagesController.getInstance(0).getUserOrChat(dialog_id)
        except Exception:
            return None

    def getPeerObjectName(self, *args, **kwargs):
        peer = self.getPeerObject()
        if peer is None:
            return ""
        data = _peer_dict(peer)
        if isinstance(data, dict):
            title = data.get("title")
            if title:
                return str(title)
            first = data.get("first_name") or ""
            last = data.get("last_name") or ""
            name = (str(first) + " " + str(last)).strip()
            if name:
                return name
        return ""

    @staticmethod
    def peersEqual(first, second, *args, **kwargs):
        left = _peer_dict(first)
        right = _peer_dict(second)
        if left is None or right is None:
            return first == second
        return left.get("id") == right.get("id")

    def equals(self, other, *args, **kwargs):
        if self is other:
            return True
        left_id = self.getId()
        if isinstance(other, dict):
            return other.get("id") == left_id and other.get("peer_id") == self.getDialogId()
        if isinstance(other, MessageObject):
            return other.getId() == left_id and other.getDialogId() == self.getDialogId()
        return False

    # -- sticker/emoji ------------------------------------------------------
    def _document_mime(self):
        document = self.getDocument()
        if isinstance(document, dict):
            return str(document.get("mime_type") or "")
        return ""

    def _has_document_attribute(self, name):
        return any(
            isinstance(attribute, dict) and attribute.get("_") == name
            for attribute in self._document_attributes(self.getDocument())
        )

    def getInputStickerSet(self, *args, **kwargs):
        sticker = self._sticker_attribute()
        sticker_set = sticker.get("stickerset") if isinstance(sticker, dict) else None
        return sticker_set if isinstance(sticker_set, dict) else None

    def getEmoji(self, *args, **kwargs):
        return self.getStickerChar()

    def getEmojiOnlyCount(self, *args, **kwargs):
        text = self.getMessageText() or ""
        if not isinstance(text, str) or not text:
            return 0
        count = 0
        for character in text:
            code = ord(character)
            if character.isspace():
                continue
            if code >= 0x1F000 or 0x2600 <= code <= 0x27BF:
                count += 1
            else:
                return 0
        return count

    def hasAttachedStickers(self, *args, **kwargs):
        return self._has_document_attribute("documentAttributeSticker") or (
            self._has_document_attribute("documentAttributeCustomEmoji")
        )

    def isStickerDocument(self, *args, **kwargs):
        return self._has_document_attribute("documentAttributeSticker")

    def isAnimatedStickerDocument(self, *args, **kwargs):
        return self._document_mime() in (
            "application/x-tgsticker", "application/x-tgs",
        ) or self._has_document_attribute("documentAttributeAnimated")

    def isVideoStickerDocument(self, *args, **kwargs):
        return self._document_mime() == "video/webm" and self.isStickerDocument()

    def isStaticStickerDocument(self, *args, **kwargs):
        return self._document_mime() == "image/webp" and self.isStickerDocument()

    def isAnimatedSticker(self, *args, **kwargs):
        return self.isAnimatedStickerDocument()

    def isPremiumSticker(self, *args, **kwargs):
        document = self.getDocument()
        return bool(isinstance(document, dict) and document.get("premium"))

    def isMask(self, *args, **kwargs):
        sticker = self._sticker_attribute()
        return bool(isinstance(sticker, dict) and sticker.get("mask"))

    def isGifDocument(self, *args, **kwargs):
        return self._document_mime() == "image/gif" or self._has_document_attribute(
            "documentAttributeAnimated"
        )

    def isVideoDocument(self, *args, **kwargs):
        return self._document_mime().startswith("video/") or self._has_document_attribute(
            "documentAttributeVideo"
        )

    def isVoiceDocument(self, *args, **kwargs):
        for attribute in self._document_attributes(self.getDocument()):
            if isinstance(attribute, dict) and attribute.get("_") == "documentAttributeAudio":
                return bool(attribute.get("voice"))
        return False

    def isMusicDocument(self, *args, **kwargs):
        for attribute in self._document_attributes(self.getDocument()):
            if isinstance(attribute, dict) and attribute.get("_") == "documentAttributeAudio":
                return not bool(attribute.get("voice"))
        return False

    def isRoundVideoDocument(self, *args, **kwargs):
        for attribute in self._document_attributes(self.getDocument()):
            if isinstance(attribute, dict) and attribute.get("_") == "documentAttributeVideo":
                return bool(attribute.get("round_message"))
        return False

    # -- message kind aliases ----------------------------------------------
    def isVoiceMessage(self, *args, **kwargs):
        return self.isVoice()

    def isForwardedMessage(self, *args, **kwargs):
        return self.isForwarded()

    def isEditingMedia(self, *args, **kwargs):
        return bool(self._field("editing_media", "is_editing_media"))

    def isSecretPhotoOrVideo(self, *args, **kwargs):
        return self.isSecretMedia() and (self.isPhoto() or self.isVideo())

    def isVideoMessage(self, *args, **kwargs):
        return self.isVideo()

    def isMusicMessage(self, *args, **kwargs):
        return self.isMusic()

    def isStickerMessage(self, *args, **kwargs):
        return self.isSticker()

    def isGifMessage(self, *args, **kwargs):
        return self.isGif()

    def isRoundVideoMessage(self, *args, **kwargs):
        return self.isRoundVideo()

    def isGameMessage(self, *args, **kwargs):
        return self.isGame()

    def isInvoiceMessage(self, *args, **kwargs):
        return self.isInvoice()

    def isLocationMessage(self, *args, **kwargs):
        return self.isLocation()

    def isLiveLocationMessage(self, *args, **kwargs):
        return self.isLiveLocation()

    def isStoryMedia(self, *args, **kwargs):
        return self.isStory()

    def isGiveawayResults(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") == "messageMediaGiveawayResults"

    def isGiveawayOrGiveawayResults(self, *args, **kwargs):
        return self.isGiveaway()

    def isAnyKindOfSticker(self, *args, **kwargs):
        return self.isSticker() or self.isAnimatedSticker() or self.isMask()

    def isAnyKindOfStickerOrEmoji(self, *args, **kwargs):
        return self.isAnyKindOfSticker() or self.getEmojiOnlyCount() > 0

    # -- webpage ------------------------------------------------------------
    def _webpage(self):
        media = self._field("media")
        if isinstance(media, dict) and media.get("_") == "messageMediaWebPage":
            page = media.get("webpage")
            return page if isinstance(page, dict) else {}
        return None

    def isWebpage(self, *args, **kwargs):
        return self._webpage() is not None

    def isMediaEmptyWebpage(self, *args, **kwargs):
        page = self._webpage()
        return isinstance(page, dict) and page.get("_") in (
            "webPageEmpty", "webPagePending",
        )

    def isImageWebDocument(self, *args, **kwargs):
        page = self._webpage() or {}
        return page.get("type") in ("photo", "image")

    def isVideoWebDocument(self, *args, **kwargs):
        page = self._webpage() or {}
        return page.get("type") in ("video", "gif")

    def isVoiceWebDocument(self, *args, **kwargs):
        page = self._webpage() or {}
        return page.get("type") == "audio"

    def isWebM(self, *args, **kwargs):
        return self._document_mime() == "video/webm"

    def isYouTubeVideo(self, *args, **kwargs):
        page = self._webpage() or {}
        return page.get("type") == "video" and (
            "youtube" in str(page.get("url") or "").lower()
            or page.get("site_name") == "YouTube"
        )

    def isEmbedVideo(self, *args, **kwargs):
        page = self._webpage() or {}
        return bool(page.get("embed_url"))

    def isRoundOnce(self, *args, **kwargs):
        return bool(self._field("ttl_seconds")) and (
            self.isRoundVideo() or self.isVoice()
        )

    # -- edit/send state ----------------------------------------------------
    def isEditing(self, *args, **kwargs):
        return bool(self._field("editing", "is_editing"))

    def isSendError(self, *args, **kwargs):
        return bool(self._field("send_error", "is_send_error"))

    def isSent(self, *args, **kwargs):
        return not self.isSending() and not self.isSendError()

    def isCompleted(self, *args, **kwargs):
        return not self.isSending()

    def canEditMessageAnytime(self, *args, **kwargs):
        return bool(self._field("edit_date")) or bool(self._field("can_edit_anytime"))

    def canEditMessageScheduleTime(self, *args, **kwargs):
        return self.isScheduled()

    def canEditMedia(self, *args, **kwargs):
        return self.getMedia() is not None and self.canEditMessage()

    def canSetReaction(self, *args, **kwargs):
        return not self.isSecret() and not self.isScheduled()

    def canUnvote(self, *args, **kwargs):
        return self.isVoted()

    def canViewThread(self, *args, **kwargs):
        return self.hasReplies()

    def canStreamVideo(self, *args, **kwargs):
        return self.isVideo() or self.isRoundVideo()

    def canPreviewDocument(self, *args, **kwargs):
        return self.isDocument()

    def canBeSensitive(self, *args, **kwargs):
        return self.getMedia() is not None

    def canAppendToTodo(self, *args, **kwargs):
        return self.isTodo()

    def canCompleteTodo(self, *args, **kwargs):
        return self.isTodo()

    # -- replies/text -------------------------------------------------------
    def hasValidReplyMessageObject(self, *args, **kwargs):
        return self._field("reply_to") is not None

    def isReplyToStory(self, *args, **kwargs):
        reply = self._field("reply_to")
        return isinstance(reply, dict) and reply.get("reply_to_story_id") is not None

    def getReplyQuoteNameWithIcon(self, *args, **kwargs):
        reply = self._field("reply_to")
        if isinstance(reply, dict):
            return reply.get("quote_name") or reply.get("quote_text") or ""
        return ""

    def getEntities(self, *args, **kwargs):
        value = self._field("entities")
        return value if isinstance(value, list) else []

    def getMessageTextToTranslate(self, *args, **kwargs):
        return self.getMessageText()

    def getVoiceTranscription(self, *args, **kwargs):
        media = self._field("media")
        if isinstance(media, dict):
            transcription = media.get("transcription")
            if isinstance(transcription, dict):
                return transcription.get("text") or ""
            if isinstance(transcription, str):
                return transcription
        return ""

    # -- files --------------------------------------------------------------
    def getMimeType(self, *args, **kwargs):
        return self._document_mime()

    def getExtension(self, *args, **kwargs):
        name = self.getFileName() or ""
        separator = str(name).rfind(".")
        return str(name)[separator + 1:].lower() if separator >= 0 else ""

    def getArtworkUrl(self, *args, **kwargs):
        document = self.getDocument()
        if isinstance(document, dict):
            return document.get("artwork_url")
        return None

    def getMediaTitle(self, *args, **kwargs):
        return self._document_attribute("title") or ""

    def getSize(self, *args, **kwargs):
        return self.getFileSize()

    def getMessageSize(self, *args, **kwargs):
        return self.getFileSize()

    def getDocumentFast(self, *args, **kwargs):
        return self.getDocument()

    def getFileNameFast(self, *args, **kwargs):
        return self.getFileName()

    # -- inline results/effects --------------------------------------------
    def getInlineBotButtons(self, *args, **kwargs):
        media = self._field("media")
        if isinstance(media, dict):
            for key in ("bot_results", "inline_result", "results"):
                value = media.get(key)
                if value is not None:
                    return value
        return None

    def hasInlineBotButtons(self, *args, **kwargs):
        return self.getInlineBotButtons() is not None

    def hasSuggestionInlineButtons(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("suggested") is not None

    def getEffect(self, *args, **kwargs):
        return self._field("effect")

    def getMediaType(self, *args, **kwargs):
        try:
            from org.telegram.messenger import FileLoader

            if self.isVideo():
                return FileLoader.MEDIA_DIR_VIDEO
            if self.isVoice() or self.isMusic():
                return FileLoader.MEDIA_DIR_AUDIO
            if self.getDocument() is not None:
                return FileLoader.MEDIA_DIR_DOCUMENT
            if self.getPhoto() is not None:
                return FileLoader.MEDIA_DIR_IMAGE
            return FileLoader.MEDIA_DIR_CACHE
        except Exception:
            return 4

    def getRealId(self, *args, **kwargs):
        return self._field("real_id") or self.getId()

    def getObjectPeerId(self, *args, **kwargs):
        return self.getDialogId()

    def getSavedDialogPeer(self, *args, **kwargs):
        return self._field("saved_dialog_peer")

    # -- reactions ----------------------------------------------------------
    def _reactions(self):
        value = self._field("reactions")
        return value if isinstance(value, dict) else None

    def hasReactions(self, *args, **kwargs):
        return self._reactions() is not None

    def hasReaction(self, *args, **kwargs):
        return self.hasReactions()

    def hasChosenReaction(self, *args, **kwargs):
        reactions = self._reactions()
        return bool(reactions and reactions.get("chosen"))

    def hasUnreadReactions(self, *args, **kwargs):
        reactions = self._reactions()
        return bool(reactions and reactions.get("unread"))

    def isPaidReactionChosen(self, *args, **kwargs):
        return bool(self._field("paid_reaction", "paid_reaction_chosen"))

    def doesPaidReactionExist(self, *args, **kwargs):
        return bool(self._field("paid_reaction"))

    def getChoosenReactions(self, *args, **kwargs):
        reactions = self._reactions()
        if not reactions:
            return []
        chosen = reactions.get("chosen")
        if isinstance(chosen, list):
            return chosen
        recent = reactions.get("recent_reactions")
        if isinstance(recent, list):
            return [
                item.get("reaction")
                for item in recent
                if isinstance(item, dict) and item.get("chosen")
            ]
        return []

    def getRandomUnreadReaction(self, *args, **kwargs):
        return None

    def isReactionsAvailable(self, *args, **kwargs):
        return not self.isSecret() and not self.isScheduled()

    def getPollResult(self, *args, **kwargs):
        media = self._poll_media()
        return media.get("results") if isinstance(media, dict) else None

    # -- misc flags ---------------------------------------------------------
    def isRtl(self, *args, **kwargs):
        from org.telegram.messenger import LocaleController

        text = self.getMessageText() or ""
        return any(
            LocaleController.isRTLCharacter(character)
            for character in str(text)[:1]
        )

    def isTheme(self, *args, **kwargs):
        return bool(self._field("theme"))

    def isWallpaper(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") == "messageMediaWallpaper"

    def isLivePhoto(self, *args, **kwargs):
        return bool(self._field("live_photo"))

    def isDice(self, *args, **kwargs):
        media = self._field("media")
        return isinstance(media, dict) and media.get("_") == "messageMediaDice"

    def isStakedDice(self, *args, **kwargs):
        return self.isStakeableDice()

    def isQuickReply(self, *args, **kwargs):
        return bool(self._field("quick_reply_shortcut_id"))

    def isBotPreview(self, *args, **kwargs):
        return bool(self._field("bot_preview"))

    def isExpiredStory(self, *args, **kwargs):
        return bool(self._field("expired"))

    def isExpiredLiveLocation(self, *args, **kwargs):
        media = self._field("media")
        if isinstance(media, dict) and media.get("_") == "messageMediaGeoLive":
            period = int(media.get("period") or 0)
            return period > 0 and (int(self.getDate()) + period) < int(time.time())
        return False

    def isConferenceCall(self, *args, **kwargs):
        return bool(self._field("conference_call"))

    def isVideoCall(self, *args, **kwargs):
        return bool(self._field("video_call"))

    def isVideoAvatar(self, *args, **kwargs):
        return bool(self._field("video_avatar"))

    def isSystemSignUp(self, *args, **kwargs):
        return bool(self._field("system_signup"))

    def isWelcomeMessage(self, *args, **kwargs):
        return bool(self._field("welcome"))

    def isTopicActionMessage(self, *args, **kwargs):
        return bool(self._field("topic_action"))

    def isWallpaperAction(self, *args, **kwargs):
        return self.isWallpaper()

    def isStarGiftAction(self, *args, **kwargs):
        return bool(self._field("star_gift_action"))

    def isUnsupported(self, *args, **kwargs):
        return bool(self._field("unsupported"))

    def isFactCheckable(self, *args, **kwargs):
        return self._field("factcheck") is not None

    def isSensitive(self, *args, **kwargs):
        return bool(self._field("sensitive"))

    def isHiddenSensitive(self, *args, **kwargs):
        return bool(self._field("hidden_sensitive"))

    def isPaidSuggestedPost(self, *args, **kwargs):
        return bool(self._field("paid_suggested_post"))

    def isPaidSuggestedPostProtected(self, *args, **kwargs):
        return bool(self._field("paid_suggested_post_protected"))

    def isAnyGift(self, *args, **kwargs):
        return bool(self._field("star_gift"))

    def isPaidVideo(self, *args, **kwargs):
        return self.isVideo() and bool(self._field("paid"))

    def isExtendedVideo(self, *args, **kwargs):
        return self.isVideo() and bool(self._field("extended"))

    def isVoiceOnce(self, *args, **kwargs):
        return self.isVoice() and bool(self._field("ttl_seconds"))

    def getStakedDiceAmount(self, *args, **kwargs):
        media = self._field("media")
        return int(media.get("stake_amount") or 0) if isinstance(media, dict) else 0

    def getStakedDiceWinAmount(self, *args, **kwargs):
        media = self._field("media")
        return int(media.get("stake_win_amount") or 0) if isinstance(media, dict) else 0

    # -- video/audio metadata ----------------------------------------------
    def _video_attribute(self):
        for attribute in self._document_attributes(self.getDocument()):
            if isinstance(attribute, dict) and attribute.get("_") == "documentAttributeVideo":
                return attribute
        return {}

    def getVideoWidth(self, *args, **kwargs):
        attribute = self._video_attribute()
        if attribute:
            return int(attribute.get("w") or 0)
        photo = self.getPhoto()
        return int(photo.get("w") or 0) if isinstance(photo, dict) else 0

    def getVideoHeight(self, *args, **kwargs):
        attribute = self._video_attribute()
        if attribute:
            return int(attribute.get("h") or 0)
        photo = self.getPhoto()
        return int(photo.get("h") or 0) if isinstance(photo, dict) else 0

    def getVideoStartsTimestamp(self, *args, **kwargs):
        return int(self._video_attribute().get("video_start_ts") or 0)

    def getVideoSavedProgress(self, *args, **kwargs):
        return 0

    def getVideoCodec(self, *args, **kwargs):
        return self._video_attribute().get("video_codec") or ""

    def getVideoCover(self, *args, **kwargs):
        return self._field("video_cover")

    def hasVideoCover(self, *args, **kwargs):
        return self.getVideoCover() is not None

    def hasVideoQualities(self, *args, **kwargs):
        document = self.getDocument()
        return bool(isinstance(document, dict) and document.get("video_qualities"))

    def getWaveform(self, *args, **kwargs):
        for attribute in self._document_attributes(self.getDocument()):
            if isinstance(attribute, dict) and attribute.get("waveform") is not None:
                return attribute.get("waveform")
        return None

    def getProgress(self, *args, **kwargs):
        return float(self._field("progress") or 0.0)

    def getPosition(self, *args, **kwargs):
        return int(self._field("position") or 0)

    # -- secret/ephemeral ---------------------------------------------------
    def getSecretTimeLeft(self, *args, **kwargs):
        ttl = int(self._field("ttl_seconds") or 0)
        if ttl <= 0:
            return 0
        sent = int(self._field("date") or 0)
        elapsed = int(time.time()) - sent
        return max(0, ttl - elapsed)

    def getSecretTimeString(self, *args, **kwargs):
        return AndroidUtilities.formatShortDuration(self.getSecretTimeLeft())

    def getEphemeralId(self, *args, **kwargs):
        return self._field("ephemeral_id")

    def getEphemeralReceiverBotId(self, *args, **kwargs):
        return int(self._field("ephemeral_receiver_bot_id") or 0)

    def isEphemeral(self, *args, **kwargs):
        return self._field("ephemeral_id") is not None

    # -- quick replies ------------------------------------------------------
    def getQuickReplyId(self, *args, **kwargs):
        return int(self._field("quick_reply_shortcut_id") or 0)

    def getQuickReplyName(self, *args, **kwargs):
        return self._field("quick_reply_name") or ""

    def getQuickReplyDisplayName(self, *args, **kwargs):
        return self.getQuickReplyName()

    # -- fact check/webpage -------------------------------------------------
    def getFactCheck(self, *args, **kwargs):
        return self._field("factcheck")

    def getFactCheckText(self, *args, **kwargs):
        factcheck = self.getFactCheck()
        if isinstance(factcheck, dict):
            return factcheck.get("text") or ""
        return ""

    def getStoryMentionWebpage(self, *args, **kwargs):
        return self._field("story_mention_webpage")

    def getWebPagePhotos(self, *args, **kwargs):
        page = self._webpage() or {}
        photos = page.get("photos")
        if isinstance(photos, list):
            return photos
        photo = page.get("photo")
        return [photo] if photo is not None else []

    def getWebDocumentDuration(self, *args, **kwargs):
        page = self._webpage() or {}
        document = page.get("document")
        if isinstance(document, dict):
            return self.getDocumentDuration(document)
        return 0

    # -- flags --------------------------------------------------------------
    def getUnreadFlags(self, *args, **kwargs):
        return int(self._field("unread_flags") or 0)

    def setUnreadFlags(self, value, *args, **kwargs):
        self._value["unread_flags"] = int(value or 0)
        return None

    def normalizeFlags(self, *args, **kwargs):
        return None

    def isAlbumSingle(self, *args, **kwargs):
        return self.getGroupId() != 0 and bool(self._field("album_single"))

    def isSavedFromMegagroup(self, *args, **kwargs):
        return bool(self._field("saved_from_megagroup"))

    def isLinkedToChat(self, *args, **kwargs):
        return bool(self._field("linked_chat"))

    def isNewGif(self, *args, **kwargs):
        return self.isGif() and bool(self._field("new_gif"))

    def isNewGifDocument(self, *args, **kwargs):
        return self.isGifDocument() and bool(self._field("new_gif"))

    def isNewGifMessage(self, *args, **kwargs):
        return self.isNewGif()

    def isDocumentHasThumb(self, *args, **kwargs):
        document = self.getDocument()
        return bool(isinstance(document, dict) and document.get("thumbs"))

    def isDocumentHasAttachedStickers(self, *args, **kwargs):
        return self.hasAttachedStickers()

    def isTextColorSet(self, *args, **kwargs):
        return self._field("text_color") is not None

    def isTextColorEmoji(self, *args, **kwargs):
        return self._field("text_color_emoji") is not None

    def isFreeEmoji(self, *args, **kwargs):
        return bool(self._field("free_emoji"))

    def isPremiumEmojiPack(self, *args, **kwargs):
        return bool(self._field("premium_emoji"))

    def isAnimatedEmoji(self, *args, **kwargs):
        return self._document_mime() == "application/x-tgsticker" and self._has_document_attribute(
            "documentAttributeCustomEmoji"
        )

    def isAnimatedEmojiStickers(self, *args, **kwargs):
        return self.isAnimatedEmoji()

    def isAnimatedAnimatedEmoji(self, *args, **kwargs):
        return self.isAnimatedEmoji()

    def isWelcomeAnchored(self, *args, **kwargs):
        return bool(self._field("welcome_anchored"))

    def isVoiceTranscriptionOpen(self, *args, **kwargs):
        return bool(self._field("voice_transcription_open"))

    def isVoteResultsIsNotEmpty(self, *args, **kwargs):
        results = self.getPollResult()
        return isinstance(results, dict) and bool(results.get("results"))

    def isVotedButResultsHiddenUntilClose(self, *args, **kwargs):
        return self.isVoted() and self.isPollClosed() and not self.isPublicPoll()

    def isWallpaperForBoth(self, *args, **kwargs):
        return self.isWallpaper() and bool(self._field("wallpaper_both"))

    def isBlueBlock(self, *args, **kwargs):
        return bool(self._field("blue_block"))

    def isCompactMode(self, *args, **kwargs):
        return bool(self._field("compact_mode"))

    def isCurrentWallpaper(self, *args, **kwargs):
        return bool(self._field("current_wallpaper"))

    def needDrawAvatar(self, *args, **kwargs):
        return not self.isOutOwner()

    def needDrawBluredPreview(self, *args, **kwargs):
        return self.isSecretMedia() and self.getMedia() is not None

    def needDrawForwarded(self, *args, **kwargs):
        return self.isForwarded()

    def needDrawShareButton(self, *args, **kwargs):
        return not self.isOutOwner()

    def shouldAnimateSending(self, *args, **kwargs):
        return self.isSending()

    def shouldDrawReactions(self, *args, **kwargs):
        return self.hasReactions()

    def shouldDrawReactionsInLayout(self, *args, **kwargs):
        return self.hasReactions()

    def shouldDrawWithoutBackground(self, *args, **kwargs):
        return False

    def shouldEncryptPhotoOrVideo(self, *args, **kwargs):
        return self.isSecretMedia() and (self.isPhoto() or self.isVideo())

    def shouldHideLinks(self, *args, **kwargs):
        return bool(self._field("hide_links"))

    def getForwardedFromPeerObject(self, *args, **kwargs):
        forwarded = self._field("fwd_from")
        if not isinstance(forwarded, dict):
            return None
        peer = forwarded.get("from_id")
        data = _peer_dict(peer)
        identifier = data.get("id") if data else (
            peer if isinstance(peer, int) else None
        )
        if identifier is None:
            return None
        try:
            from org.telegram.messenger import MessagesController

            return MessagesController.getInstance(0).getUserOrChat(identifier)
        except Exception:
            return None

    def getMediaExistanceFlags(self, *args, **kwargs):
        return int(self._field("media_existance_flags") or 0)

    def mediaExists(self, *args, **kwargs):
        return bool(self._field("media_exists"))

    def getPremiumStickerAnimation(self, *args, **kwargs):
        return None

    def getReplyQuoteNameWithIcon(self, *args, **kwargs):
        reply = self._field("reply_to")
        if isinstance(reply, dict):
            return reply.get("quote_name") or reply.get("quote_text") or ""
        return ""


def _peer_dict(value):
    if isinstance(value, dict):
        return value
    inner = getattr(value, "_value", None)
    return inner if isinstance(inner, dict) else None


def _public_username(value):
    data = _peer_dict(value)
    if data is None:
        return None
    username = data.get("username")
    if isinstance(username, str) and username:
        return username
    usernames = data.get("usernames")
    if isinstance(usernames, list):
        for item in usernames:
            if isinstance(item, dict) and isinstance(item.get("username"), str) and item["username"]:
                return item["username"]
    return None


class ChatObject:
    """`org.telegram.messenger.ChatObject` for chats and TL chat dictionaries."""

    @staticmethod
    def getTitle(chat, *args, **kwargs):
        data = chat if isinstance(chat, dict) else getattr(chat, "_value", None)
        if not isinstance(data, dict):
            return ""
        title = data.get("title")
        if title:
            return str(title)
        first = data.get("first_name") or ""
        last = data.get("last_name") or ""
        return (str(first) + " " + str(last)).strip()

    @staticmethod
    def isChannel(chat, *args):
        if isinstance(chat, int) and args:
            try:
                from org.telegram.messenger import MessagesController

                chat = MessagesController.getInstance(args[0]).getChat(chat)
            except Exception:
                return False
        data = _peer_dict(chat)
        if data is None:
            return False
        if "isChannel" in data:
            return bool(data["isChannel"])
        if data.get("kind") == "channel" or data.get("_") == "channel":
            return True
        return bool(data.get("channel_id")) or bool(data.get("is_channel"))

    @staticmethod
    def isGroup(chat):
        data = _peer_dict(chat)
        if data is None:
            return False
        if data.get("kind") in ("group", "community") or data.get("_") in ("chat", "chatForbidden"):
            return True
        return bool(data.get("chat_id")) or bool(data.get("isGroup"))

    @staticmethod
    def isBroadcast(chat):
        data = _peer_dict(chat)
        if data is None:
            return False
        return bool(data.get("broadcast", data.get("is_broadcast", False)))

    @staticmethod
    def isMegagroup(chat, *args):
        if isinstance(chat, int) and args:
            try:
                from org.telegram.messenger import MessagesController

                chat = MessagesController.getInstance(args[0]).getChat(chat)
            except Exception:
                return False
        data = _peer_dict(chat)
        if data is None:
            return False
        return bool(data.get("megagroup", data.get("is_megagroup", False)))

    @staticmethod
    def isChannelAndNotMegaGroup(chat, *args):
        if isinstance(chat, int) and args:
            try:
                from org.telegram.messenger import MessagesController

                chat = MessagesController.getInstance(args[0]).getChat(chat)
            except Exception:
                return False
        return ChatObject.isChannel(chat) and not ChatObject.isMegagroup(chat)

    @staticmethod
    def getPublicUsername(chat):
        return _public_username(chat)

    @staticmethod
    def isPublic(chat):
        return bool(ChatObject.getPublicUsername(chat))

    @staticmethod
    def isKickedFromGroup(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("kicked"))

    @staticmethod
    def isLeft(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("left"))

    @staticmethod
    def isBanned(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("banned"))

    @staticmethod
    def isForum(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("forum"))

    @staticmethod
    def isPreHistoryHidden(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("pre_history_hidden"))

    @staticmethod
    def isAdmin(chat, user_id=None):
        data = _peer_dict(chat)
        if data is None:
            return False
        if data.get("admin_rights") is not None or data.get("creator"):
            return True
        if user_id is not None and data.get("admin_id") is not None:
            try:
                return int(data["admin_id"]) == int(user_id)
            except (TypeError, ValueError):
                return False
        return False

    @staticmethod
    def isLocalChannel(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("local"))

    @staticmethod
    def isMigrated(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("migrated_to"))

    @staticmethod
    def isDiscussionGroup(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("linked_chat_id"))

    @staticmethod
    def isMonoforum(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("monoforum"))

    @staticmethod
    def isPaid(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("paid"))

    @staticmethod
    def isStarGiftAvailable(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("star_gift"))

    @staticmethod
    def isVerified(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("verified"))

    @staticmethod
    def isScam(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("scam"))

    @staticmethod
    def isFake(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("fake"))

    @staticmethod
    def isRestricted(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("restricted"))

    @staticmethod
    def hasBots(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("bots"))

    _ACTION_RIGHTS = {
        "send_messages": "send_messages",
        "send_media": "send_media",
        "send_stickers": "send_stickers",
        "send_gifs": "send_gifs",
        "send_games": "send_games",
        "send_inline": "send_inline",
        "embed_links": "embed_links",
        "send_polls": "send_polls",
        "change_info": "change_info",
        "invite_users": "invite_users",
        "pin_messages": "pin_messages",
        "manage_topics": "manage_topics",
        "send_photos": "send_photos",
        "send_videos": "send_videos",
        "send_roundvideos": "send_roundvideos",
        "send_audios": "send_audios",
        "send_voices": "send_voices",
        "send_docs": "send_docs",
        "send_plain": "send_plain",
        "add_admins": "add_admins",
        "manage_call": "manage_call",
        "manage_tags": "manage_tags",
        "delete_messages": "delete_messages",
        "ban_users": "ban_users",
        "block_users": "ban_users",
    }

    @staticmethod
    def _resolve_chat(chat, args):
        if isinstance(chat, int) and args:
            try:
                from org.telegram.messenger import MessagesController

                return MessagesController.getInstance(args[0]).getChat(chat)
            except Exception:
                return None
        return chat

    @staticmethod
    def _banned(chat, action, defaults_only=False):
        key = ChatObject._ACTION_RIGHTS.get(str(action), str(action))
        data = _peer_dict(chat)
        if not isinstance(data, dict):
            return False
        if not defaults_only:
            if data.get("creator"):
                return False
            rights = data.get("banned_rights")
            if isinstance(rights, dict) and bool(rights.get(key)):
                return True
        defaults = data.get("default_banned_rights")
        if isinstance(defaults, dict) and bool(defaults.get(key)):
            admin = data.get("admin_rights")
            if not defaults_only and isinstance(admin, dict) and bool(admin.get(key)):
                return False
            return True
        return False

    @staticmethod
    def isActionBanned(chat, action):
        return ChatObject._banned(chat, action, defaults_only=False)

    @staticmethod
    def isActionBannedByDefault(chat, action):
        return ChatObject._banned(chat, action, defaults_only=True)

    @staticmethod
    def _can_send(chat, action):
        return not ChatObject.isActionBanned(chat, action)

    @staticmethod
    def canSendMessages(chat):
        return ChatObject._can_send(chat, "send_messages")

    @staticmethod
    def canSendPlain(chat):
        return ChatObject._can_send(chat, "send_plain")

    @staticmethod
    def canSendPhoto(chat):
        return ChatObject._can_send(chat, "send_photos")

    @staticmethod
    def canSendVideo(chat):
        return ChatObject._can_send(chat, "send_videos")

    @staticmethod
    def canSendRoundVideo(chat):
        return ChatObject._can_send(chat, "send_roundvideos")

    @staticmethod
    def canSendMusic(chat):
        return ChatObject._can_send(chat, "send_audios")

    @staticmethod
    def canSendVoice(chat):
        return ChatObject._can_send(chat, "send_voices")

    @staticmethod
    def canSendDocument(chat):
        return ChatObject._can_send(chat, "send_docs")

    @staticmethod
    def canSendStickers(chat):
        return ChatObject._can_send(chat, "send_stickers")

    @staticmethod
    def canSendEmbed(chat):
        return ChatObject._can_send(chat, "embed_links")

    @staticmethod
    def canSendPolls(chat):
        return ChatObject._can_send(chat, "send_polls")

    @staticmethod
    def canSendAnyMedia(chat):
        return (
            ChatObject.canSendPhoto(chat)
            or ChatObject.canSendVideo(chat)
            or ChatObject.canSendMusic(chat)
            or ChatObject.canSendDocument(chat)
            or ChatObject.canSendVoice(chat)
            or ChatObject.canSendRoundVideo(chat)
            or ChatObject.canSendStickers(chat)
        )

    @staticmethod
    def canAddUsers(chat):
        return ChatObject._can_send(chat, "invite_users")

    @staticmethod
    def canAddBotsToChat(chat):
        return ChatObject.canAddUsers(chat)

    @staticmethod
    def canPinMessages(chat):
        return ChatObject._can_send(chat, "pin_messages")

    @staticmethod
    def canChangeChatInfo(chat):
        return ChatObject._can_send(chat, "change_info")

    @staticmethod
    def canManageTags(chat):
        return ChatObject._can_send(chat, "manage_tags")

    @staticmethod
    def canManageMyTag(chat):
        return ChatObject.canManageTags(chat)

    @staticmethod
    def canBlockUsers(chat):
        return ChatObject._can_send(chat, "ban_users")

    @staticmethod
    def canManageCalls(chat):
        return ChatObject._can_send(chat, "manage_call")

    @staticmethod
    def canAddAdmins(chat):
        return ChatObject._can_send(chat, "add_admins")

    @staticmethod
    def hasAdminRights(chat):
        data = _peer_dict(chat)
        if not isinstance(data, dict):
            return False
        if data.get("creator"):
            return True
        admin = data.get("admin_rights")
        if isinstance(admin, dict):
            return any(bool(value) for value in admin.values())
        return bool(data.get("admin"))

    @staticmethod
    def isCreator(chat):
        data = _peer_dict(chat)
        return bool(data and (data.get("creator") or data.get("is_creator")))

    @staticmethod
    def isLeftFromChat(chat):
        return ChatObject.isLeft(chat)

    @staticmethod
    def isKickedFromChat(chat):
        return ChatObject.isKickedFromGroup(chat) or ChatObject.isBanned(chat)

    @staticmethod
    def isNotInChat(chat):
        return ChatObject.isLeftFromChat(chat) or ChatObject.isKickedFromChat(chat)

    @staticmethod
    def isInChat(chat):
        return not ChatObject.isNotInChat(chat)

    @staticmethod
    def canWriteToChat(chat):
        if ChatObject.isNotInChat(chat):
            return False
        if ChatObject.isBroadcast(chat):
            return ChatObject.hasAdminRights(chat)
        return ChatObject.canSendMessages(chat)

    @staticmethod
    def isCanWriteToChannel(chat_id, current_account=0):
        try:
            from org.telegram.messenger import MessagesController

            chat = MessagesController.getInstance(current_account).getChat(chat_id)
        except Exception:
            chat = None
        return ChatObject.canWriteToChat(chat) if chat is not None else True

    @staticmethod
    def canSendAsPeers(chat):
        data = _peer_dict(chat)
        return bool(data and (data.get("send_as") or data.get("anonymous")))

    @staticmethod
    def shouldSendAnonymously(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("anonymous"))

    @staticmethod
    def getSendAsPeerId(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return int(data.get("send_as_peer_id") or 0) if data else 0

    @staticmethod
    def canCreateTopic(chat):
        return ChatObject.isForum(chat) and ChatObject._can_send(chat, "manage_topics")

    @staticmethod
    def canManageTopics(chat):
        return ChatObject._can_send(chat, "manage_topics")

    @staticmethod
    def hasPhoto(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("photo") is not None)

    @staticmethod
    def getPhoto(chat):
        data = _peer_dict(chat)
        return data.get("photo") if data else None

    @staticmethod
    def hasPublicLink(chat, username):
        return ChatObject.getPublicUsername(chat) == username

    @staticmethod
    def isCommunity(chat, *args):
        data = _peer_dict(ChatObject._resolve_chat(chat, args))
        if not isinstance(data, dict):
            return False
        return bool(
            data.get("_") == "community"
            or data.get("community")
            or data.get("is_community")
        )

    @staticmethod
    def isChannelOrGiga(chat):
        return ChatObject.isChannel(chat) or ChatObject.isMegagroup(chat)

    @staticmethod
    def isMonoForum(chat, *args):
        return ChatObject.isMonoforum(ChatObject._resolve_chat(chat, args))

    @staticmethod
    def hasStories(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("stories") is not None)

    @staticmethod
    def isBoostSupported(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("boost_supported"))

    @staticmethod
    def isBoosted(chat):
        data = _peer_dict(chat)
        return bool(data and data.get("boosted"))

    @staticmethod
    def reactionIsAvailable(chat_info, reaction):
        data = _peer_dict(chat_info)
        if not isinstance(data, dict):
            return True
        values = data.get("available_reactions")
        if values is None:
            return True
        if isinstance(values, list):
            return reaction in values
        if isinstance(values, dict):
            return bool(values.get(str(reaction)))
        return True

    @staticmethod
    def getBannedRightsString(rights):
        data = _peer_dict(rights)
        if not isinstance(data, dict):
            return ""
        return ", ".join(
            sorted(key for key, value in data.items() if value is True)
        )

    @staticmethod
    def canPost(chat, *args, **kwargs):
        return ChatObject.canSendMessages(chat)

    @staticmethod
    def isScheduled(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("scheduled"))

    @staticmethod
    def isCalling(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("call_active"))

    @staticmethod
    def equals(first, second, *args, **kwargs):
        if first is second:
            return True
        left = _peer_dict(first)
        right = _peer_dict(second)
        if left is None or right is None:
            return left == right
        return left.get("id") == right.get("id")

    @staticmethod
    def getColorId(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return int(data.get("color") or 0) if data else 0

    @staticmethod
    def getEmojiId(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return int(data.get("emoji") or 0) if data else 0

    @staticmethod
    def getProfileColorId(chat, *args, **kwargs):
        data = _peer_dict(chat)
        if not data:
            return 0
        return int(data.get("profile_color") or data.get("color") or 0)

    @staticmethod
    def getProfileEmojiId(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return int(data.get("profile_emoji") or 0) if data else 0

    @staticmethod
    def getProfileCollectibleId(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return int(data.get("profile_collectible") or 0) if data else 0

    @staticmethod
    def getOnlyProfileEmojiId(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return int(data.get("only_profile_emoji") or 0) if data else 0

    @staticmethod
    def getPeerColorForAvatar(chat, *args, **kwargs):
        return ChatObject.getProfileColorId(chat)

    @staticmethod
    def getInputGroupCall(chat, *args, **kwargs):
        data = _peer_dict(chat)
        if data and isinstance(data.get("call"), dict):
            return data["call"]
        return None

    @staticmethod
    def getParticipantVolume(chat, participant, *args, **kwargs):
        data = _peer_dict(chat)
        if not isinstance(data, dict):
            return 100
        volumes = data.get("participant_volumes")
        if isinstance(volumes, dict):
            key = _peer_dict(participant)
            identifier = key.get("id") if key else participant
            return int(volumes.get(str(identifier), 100))
        return 100

    @staticmethod
    def getRestrictedErrorText(chat, *args, **kwargs):
        data = _peer_dict(chat)
        if isinstance(data, dict):
            text = data.get("restriction_reason") or data.get("restricted_text")
            if text:
                return str(text)
        return ""

    @staticmethod
    def make(chat, *args, **kwargs):
        return chat

    @staticmethod
    def canUserDoAction(chat, participant=None, action=None, *args, **kwargs):
        if isinstance(participant, int) and action is None:
            action = participant
        return ChatObject.canSendMessages(chat)

    @staticmethod
    def canUserDoAdminAction(chat, action=None, *args, **kwargs):
        data = _peer_dict(chat)
        rights = None
        if isinstance(data, dict):
            if isinstance(data.get("admin_rights"), dict):
                rights = data["admin_rights"]
            elif any(
                key in data
                for key in (
                    "change_info",
                    "delete_messages",
                    "ban_users",
                    "invite_users",
                    "pin_messages",
                    "add_admins",
                    "anonymous",
                    "manage_call",
                    "other",
                    "manage_topics",
                    "post_messages",
                    "edit_messages",
                )
            ):
                rights = data
        if not isinstance(rights, dict):
            return False
        if action is not None:
            keys = {
                0: "change_info",
                1: "delete_messages",
                2: "ban_users",
                3: "invite_users",
                4: "pin_messages",
                5: "add_admins",
                6: "anonymous",
                7: "manage_call",
                8: "other",
                9: "manage_topics",
                10: "post_messages",
                11: "edit_messages",
                12: "delete_stories",
                13: "edit_stories",
                14: "post_stories",
                15: "manage_direct",
                16: "manage_ranks",
                17: "manage_linked_peers",
            }
            key = keys.get(int(action))
            if key and key in rights:
                return bool(rights.get(key))
            return False
        return bool(rights)

    @staticmethod
    def canUserDoChannelDirectAdminAction(account, chat, action=None, *args,
                                          **kwargs):
        if isinstance(chat, int) and action is None:
            action = chat
        target = chat
        if isinstance(target, int):
            try:
                from org.telegram.messenger import MessagesController

                target = MessagesController.getInstance(account).getChat(target)
            except Exception:
                target = None
        return ChatObject.canUserDoAdminAction(target, action)

    @staticmethod
    def canAddChatToCommunity(chat, *args, **kwargs):
        return ChatObject.isChannel(chat)

    @staticmethod
    def canRemoveChatFromCommunity(chat, *args, **kwargs):
        return ChatObject.isCommunity(chat)

    @staticmethod
    def areTabsEnabled(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("tabs_enabled"))

    @staticmethod
    def isSidebarEnabled(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("sidebar_enabled"))

    @staticmethod
    def isCommunityPeerHidden(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("community_hidden"))

    @staticmethod
    def isHiddenInCommunity(chat, *args, **kwargs):
        return ChatObject.isCommunityPeerHidden(chat)

    @staticmethod
    def isUserCollapsedInCommunity(chat, user, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("community_collapsed"))

    @staticmethod
    def isChatCollapsedInCommunity(chat, *args, **kwargs):
        return ChatObject.isCollapsedInCommunity(chat)

    @staticmethod
    def isCollapsedInCommunity(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("collapsed"))

    @staticmethod
    def isMyTopic(chat, *args, **kwargs):
        data = _peer_dict(chat)
        return bool(data and data.get("is_my_topic"))

    @staticmethod
    def canDeleteTopic(chat, *args, **kwargs):
        return ChatObject.canManageTopics(chat)

    @staticmethod
    def canManageTopic(chat, *args, **kwargs):
        return ChatObject.canManageTopics(chat)

    @staticmethod
    def canRecordVideo(chat, *args, **kwargs):
        return ChatObject.canSendRoundVideo(chat)


class UserObject:
    """`org.telegram.messenger.UserObject` for users and TL user dictionaries."""

    @staticmethod
    def getFirstName(user):
        data = _peer_dict(user)
        return str(data.get("first_name") or "") if data else ""

    @staticmethod
    def getLastName(user):
        data = _peer_dict(user)
        return str(data.get("last_name") or "") if data else ""

    @staticmethod
    def getUserName(user):
        data = _peer_dict(user)
        if data is None:
            return ""
        name = (UserObject.getFirstName(user) + " " + UserObject.getLastName(user)).strip()
        if name:
            return name
        username = _public_username(user)
        if username:
            return username
        phone = data.get("phone")
        return str(phone) if phone else ""

    @staticmethod
    def getPublicUsername(user):
        return _public_username(user)

    @staticmethod
    def isBot(user):
        data = _peer_dict(user)
        return bool(data and data.get("bot"))

    @staticmethod
    def isDeleted(user):
        data = _peer_dict(user)
        return bool(data and data.get("deleted"))

    @staticmethod
    def isContact(user):
        data = _peer_dict(user)
        return bool(data and data.get("contact"))

    @staticmethod
    def isSupport(user):
        data = _peer_dict(user)
        return bool(data and data.get("support"))

    @staticmethod
    def isPremium(user):
        data = _peer_dict(user)
        return bool(data and data.get("premium"))

    @staticmethod
    def isVerified(user):
        data = _peer_dict(user)
        return bool(data and data.get("verified"))

    @staticmethod
    def getStatus(user, *args, **kwargs):
        data = _peer_dict(user)
        return str(data.get("status") or "") if data else ""

    @staticmethod
    def getUserStatus(user, *args, **kwargs):
        return UserObject.getStatus(user)

    @staticmethod
    def isService(user):
        data = _peer_dict(user)
        return bool(data and data.get("support"))

    @staticmethod
    def isAnonymous(user):
        data = _peer_dict(user)
        return bool(data and data.get("anonymous"))

    @staticmethod
    def isSigned(user):
        data = _peer_dict(user)
        return bool(data and data.get("signed"))

    @staticmethod
    def isBlocked(user):
        data = _peer_dict(user)
        return bool(data and data.get("blocked"))

    @staticmethod
    def isCloseFriend(user):
        data = _peer_dict(user)
        return bool(data and data.get("close_friend"))

    @staticmethod
    def isMutualContact(user):
        data = _peer_dict(user)
        return bool(data and data.get("mutual_contact"))

    @staticmethod
    def isScam(user):
        data = _peer_dict(user)
        return bool(data and data.get("scam"))

    @staticmethod
    def isFake(user):
        data = _peer_dict(user)
        return bool(data and data.get("fake"))

    @staticmethod
    def isSelf(user):
        data = _peer_dict(user)
        return bool(data and data.get("self"))

    @staticmethod
    def isRisky(user):
        return UserObject.isScam(user) or UserObject.isFake(user)

    @staticmethod
    def getFullName(user):
        return (UserObject.getFirstName(user) + " " + UserObject.getLastName(user)).strip()

    @staticmethod
    def isUserSelf(user):
        return UserObject.isSelf(user)

    @staticmethod
    def isReplyUser(user):
        data = _peer_dict(user)
        if not isinstance(data, dict):
            return False
        return bool(data.get("reply") or data.get("id") == 1271266957)

    @staticmethod
    def getBotStatus(user):
        data = _peer_dict(user)
        return str(data.get("bot_status") or "") if data else ""

    @staticmethod
    def getForcedFirstName(user):
        first = UserObject.getFirstName(user)
        if first:
            return first
        return UserObject.getPublicUsername(user) or ""

    @staticmethod
    def hasPhoto(user):
        data = _peer_dict(user)
        return bool(data and data.get("photo") is not None)

    @staticmethod
    def getPhoto(user):
        data = _peer_dict(user)
        return data.get("photo") if data else None

    @staticmethod
    def hasFallbackPhoto(user_full):
        data = _peer_dict(user_full)
        return bool(data and data.get("fallback_photo") is not None)

    @staticmethod
    def getEmojiStatusDocumentId(user):
        data = _peer_dict(user)
        if not isinstance(data, dict):
            return None
        status = data.get("emoji_status")
        if isinstance(status, dict) and status.get("document_id") is not None:
            return int(status["document_id"])
        if data.get("emoji_status_document_id") is not None:
            return int(data["emoji_status_document_id"])
        return None

    @staticmethod
    def hasPublicUsername(user, username):
        return UserObject.getPublicUsername(user) == username

    @staticmethod
    def getColorId(user):
        data = _peer_dict(user)
        return int(data.get("color") or 0) if data else 0

    @staticmethod
    def getEmojiId(user):
        data = _peer_dict(user)
        return int(data.get("emoji") or 0) if data else 0

    @staticmethod
    def getProfileColorId(user):
        data = _peer_dict(user)
        if not data:
            return 0
        return int(data.get("profile_color") or data.get("color") or 0)

    @staticmethod
    def getProfileEmojiId(user):
        data = _peer_dict(user)
        return int(data.get("profile_emoji") or 0) if data else 0

    @staticmethod
    def getOnlyProfileEmojiId(user):
        data = _peer_dict(user)
        return int(data.get("only_profile_emoji") or 0) if data else 0

    @staticmethod
    def getProfileCollectibleId(user):
        data = _peer_dict(user)
        return int(data.get("profile_collectible") or 0) if data else 0

    @staticmethod
    def isBotForum(user):
        data = _peer_dict(user)
        return bool(data and data.get("bot_forum"))

    @staticmethod
    def isBotForumSidebar(user):
        data = _peer_dict(user)
        return bool(data and data.get("bot_forum_sidebar"))

    @staticmethod
    def isBotForumWithEditableTopics(user):
        data = _peer_dict(user)
        return bool(data and data.get("bot_forum_editable"))

    @staticmethod
    def getRequirementToContact(user):
        data = _peer_dict(user)
        if not data:
            return 0
        return int(data.get("contact_requirement") or 0)

    @staticmethod
    def getPeerColorForAvatar(user):
        data = _peer_dict(user)
        if not data:
            return 0
        return int(
            data.get("profile_color")
            or data.get("color")
            or data.get("peer_color")
            or 0
        )

    @staticmethod
    def areGiftsDisabled(user):
        data = _peer_dict(user)
        return bool(data and data.get("gifts_disabled"))

    @staticmethod
    def applyRequirementToContact(user):
        data = _peer_dict(user)
        if isinstance(data, dict):
            data["contact_requirement"] = 0
        return user

    @staticmethod
    def eq(first, second):
        if first is second:
            return True
        left = _peer_dict(first)
        right = _peer_dict(second)
        if left is None or right is None:
            return left == right
        return left.get("id") == right.get("id") and (
            left.get("_") == right.get("_")
            or left.get("id") is not None
        )


class DialogObject:
    """`org.telegram.messenger.DialogObject` id helpers."""

    _FOLDER_MASK = 0x2000000000000000
    _ENCRYPTED_MASK = 0x4000000000000000
    _SIGN_MASK = 0x8000000000000000

    @staticmethod
    def getPeerId(dialog_id):
        try:
            return int(dialog_id)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def isChannel(dialog):
        data = _peer_dict(dialog)
        if data is None:
            return False
        flags = data.get("flags")
        if isinstance(flags, int):
            return bool(flags & 1)
        return bool(
            data.get("channel")
            or data.get("broadcast")
            or data.get("megagroup")
            or data.get("channel_id")
            or data.get("_") == "channel"
        )

    @staticmethod
    def makeFolderDialogId(folder_id):
        return DialogObject._FOLDER_MASK | (int(folder_id) & 0xFFFFFFFF)

    @staticmethod
    def isFolderDialogId(dialog_id):
        try:
            value = int(dialog_id)
        except (TypeError, ValueError):
            return False
        return (value & DialogObject._FOLDER_MASK) != 0 and (
            value & DialogObject._SIGN_MASK
        ) == 0

    @staticmethod
    def getFolderId(dialog_id):
        return int(dialog_id) & 0xFFFFFFFF

    @staticmethod
    def initDialog(dialog):
        data = _peer_dict(dialog)
        if not isinstance(data, dict) or data.get("id"):
            return data.get("id") if isinstance(data, dict) else None
        kind = data.get("_")
        if kind == "dialog":
            peer = data.get("peer")
            if isinstance(peer, dict):
                data["id"] = DialogObject.getPeerDialogId(peer)
        elif kind == "dialogFolder":
            folder = data.get("folder")
            if isinstance(folder, dict):
                data["id"] = DialogObject.makeFolderDialogId(folder.get("id") or 0)
        elif kind == "dialogCommunity":
            data["id"] = -int(data.get("community_id") or 0)
        return data.get("id")

    @staticmethod
    def getDialogId(obj):
        data = _peer_dict(obj)
        if not isinstance(data, dict):
            return 0
        kind = data.get("_")
        if kind in ("user", "userEmpty"):
            return int(data.get("id") or 0)
        if kind in ("chat", "chatForbidden"):
            return -int(data.get("id") or 0)
        return DialogObject.getPeerDialogId(data)

    @staticmethod
    def getPeerDialogId(peer):
        data = _peer_dict(peer)
        if not isinstance(data, dict):
            return 0
        if data.get("user_id"):
            return int(data["user_id"])
        if data.get("chat_id"):
            return -int(data["chat_id"])
        if data.get("channel_id"):
            return -int(data["channel_id"])
        if data.get("id") is not None:
            return int(data["id"])
        return 0

    @staticmethod
    def getLastMessageOrDraftDate(dialog, draft):
        dialog_data = _peer_dict(dialog) or {}
        draft_data = _peer_dict(draft) or {}
        dialog_date = int(dialog_data.get("last_message_date") or 0)
        draft_date = int(draft_data.get("date") or 0)
        if draft is not None and draft_date >= dialog_date:
            return draft_date
        return dialog_date

    @staticmethod
    def isUserDialog(dialog_id):
        try:
            value = int(dialog_id)
        except (TypeError, ValueError):
            return False
        return (
            not DialogObject.isEncryptedDialog(value)
            and not DialogObject.isFolderDialogId(value)
            and value > 0
        )

    @staticmethod
    def isChatDialog(dialog_id):
        try:
            value = int(dialog_id)
        except (TypeError, ValueError):
            return False
        return (
            not DialogObject.isEncryptedDialog(value)
            and not DialogObject.isFolderDialogId(value)
            and value < 0
        )

    @staticmethod
    def isChannelDialog(dialog_id):
        try:
            return int(dialog_id) <= -1000000000000
        except (TypeError, ValueError):
            return False

    @staticmethod
    def isEncryptedDialog(dialog_id):
        try:
            value = int(dialog_id)
        except (TypeError, ValueError):
            return False
        return (value & DialogObject._ENCRYPTED_MASK) != 0 and (
            value & DialogObject._SIGN_MASK
        ) == 0

    @staticmethod
    def makeEncryptedDialogId(chat_id):
        return DialogObject._ENCRYPTED_MASK | (int(chat_id) & 0xFFFFFFFF)

    @staticmethod
    def getEncryptedChatId(dialog_id):
        return int(dialog_id) & 0xFFFFFFFF

    @staticmethod
    def makeUserDialogId(user_id):
        return int(user_id)

    @staticmethod
    def makeChatDialogId(chat_id):
        return -abs(int(chat_id))

    @staticmethod
    def makeChannelDialogId(channel_id):
        return -1000000000000 - abs(int(channel_id))

    @staticmethod
    def makePeerDialogId(peer_id, *args, **kwargs):
        return int(peer_id)

    @staticmethod
    def getInputPeer(dialog_id):
        return int(dialog_id)

    @staticmethod
    def getPeer(dialog_id):
        return int(dialog_id)

    @staticmethod
    def getUser(dialog_id):
        return int(dialog_id) if DialogObject.isUserDialog(dialog_id) else None

    @staticmethod
    def getChat(dialog_id):
        return int(dialog_id) if DialogObject.isChatDialog(dialog_id) else None

    @staticmethod
    def getShortTitle(obj):
        data = _peer_dict(obj)
        if not isinstance(data, dict):
            return ""
        kind = data.get("_")
        if kind in ("user", "userEmpty") or data.get("first_name") is not None:
            return UserObject.getFirstName(obj)
        return str(data.get("title") or "")

    @staticmethod
    def getDialogTitle(obj):
        data = _peer_dict(obj)
        if not isinstance(data, dict):
            return ""
        kind = data.get("_")
        if kind in ("user", "userEmpty") or data.get("first_name") is not None:
            return UserObject.getUserName(obj)
        return str(data.get("title") or "")

    @staticmethod
    def _resolve_dialog(args):
        if args and isinstance(args[0], int):
            try:
                from org.telegram.messenger import MessagesController

                return MessagesController.getInstance(args[0]).getUserOrChat(args[1])
            except Exception:
                return None
        return None

    @staticmethod
    def getName(obj, *args, **kwargs):
        resolved = DialogObject._resolve_dialog(args)
        return DialogObject.getDialogTitle(resolved if resolved is not None else obj)

    @staticmethod
    def getStatus(obj, *args, **kwargs):
        resolved = DialogObject._resolve_dialog(args)
        target = resolved if resolved is not None else obj
        data = _peer_dict(target)
        if not isinstance(data, dict):
            return ""
        kind = data.get("_")
        if kind in ("user", "userEmpty") or data.get("first_name") is not None:
            return UserObject.getStatus(target)
        count = int(data.get("participants_count") or 0)
        if count > 1:
            label = (
                "subscribers"
                if ChatObject.isChannelAndNotMegaGroup(target)
                else "members"
            )
            return "%d %s" % (count, label)
        return ""

    @staticmethod
    def getShortName(obj, *args, **kwargs):
        resolved = DialogObject._resolve_dialog(args)
        return _public_username(resolved if resolved is not None else obj) or ""

    @staticmethod
    def isEmpty(obj, *args, **kwargs):
        data = _peer_dict(obj)
        if not data:
            return True
        return data.get("id") is None and not data.get("title")

    @staticmethod
    def hasPhoto(obj, *args, **kwargs):
        data = _peer_dict(obj)
        if not data:
            return False
        return bool(data.get("photo") or data.get("photo_id"))

    @staticmethod
    def getPublicUsername(obj, *args, **kwargs):
        resolved = DialogObject._resolve_dialog(args)
        return _public_username(resolved if resolved is not None else obj) or ""

    @staticmethod
    def findUsername(obj, *args, **kwargs):
        return DialogObject.getPublicUsername(obj, *args, **kwargs)

    @staticmethod
    def getSimilarPublicUsername(obj, *args, **kwargs):
        return ""

    @staticmethod
    def getEmojiStatusDocumentId(obj, *args, **kwargs):
        data = _peer_dict(obj)
        if not data:
            return 0
        status = data.get("emoji_status")
        if isinstance(status, dict):
            return int(status.get("document_id") or status.get("id") or 0)
        return int(data.get("emoji_status_document_id") or 0)

    @staticmethod
    def getEmojiStatusUntil(obj, *args, **kwargs):
        data = _peer_dict(obj)
        if not data:
            return 0
        status = data.get("emoji_status")
        if isinstance(status, dict):
            return int(status.get("until") or 0)
        return int(data.get("emoji_status_until") or 0)

    @staticmethod
    def getEmojiStatusCollectibleId(obj, *args, **kwargs):
        data = _peer_dict(obj)
        if not data:
            return 0
        status = data.get("emoji_status")
        if isinstance(status, dict):
            return int(status.get("collectible_id") or 0)
        return int(data.get("emoji_status_collectible_id") or 0)

    @staticmethod
    def isEmojiStatusCollectible(obj, *args, **kwargs):
        return DialogObject.getEmojiStatusCollectibleId(obj) != 0

    @staticmethod
    def getBotVerification(obj, *args, **kwargs):
        data = _peer_dict(obj)
        if not data:
            return None
        return data.get("bot_verification")

    @staticmethod
    def getBotVerificationIcon(obj, *args, **kwargs):
        verification = DialogObject.getBotVerification(obj)
        if isinstance(verification, dict):
            return int(verification.get("icon") or 0)
        return 0

    @staticmethod
    def getMessagesStarsPrice(obj, *args, **kwargs):
        data = _peer_dict(obj)
        if not data:
            return 0
        try:
            return int(data.get("stars_price") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def isPremiumBlocked(obj, *args, **kwargs):
        data = _peer_dict(obj)
        return bool(data and data.get("premium_blocked"))

    @staticmethod
    def editDistance(first, second, *args, **kwargs):
        left = str(first or "")
        right = str(second or "")
        previous = list(range(len(right) + 1))
        for i, left_char in enumerate(left, 1):
            current = [i]
            for j, right_char in enumerate(right, 1):
                current.append(min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                ))
            previous = current
        return previous[-1]

    @staticmethod
    def similarity(first, second, *args, **kwargs):
        left = str(first or "")
        right = str(second or "")
        length = max(len(left), len(right))
        if not length:
            return 1.0
        return 1.0 - DialogObject.editDistance(left, right) / float(length)

    @staticmethod
    def filterEmojiStatus(obj, *args, **kwargs):
        return obj

    @staticmethod
    def emojiStatusesEqual(first, second, *args, **kwargs):
        return (
            DialogObject.getEmojiStatusDocumentId(first)
            == DialogObject.getEmojiStatusDocumentId(second)
            and DialogObject.getEmojiStatusUntil(first)
            == DialogObject.getEmojiStatusUntil(second)
        )

    @staticmethod
    def setDialogPhotoTitle(dialog, *args, **kwargs):
        return None


class PythonPluginsEngine:
    """`com.exteragram.messenger.plugins.PythonPluginsEngine` facade."""

    SDK_VERSION = "1.4.6.5"
    _INSTANCE = None

    @classmethod
    def getClass(cls):
        return _java_class_ref("com.exteragram.messenger.plugins.PythonPluginsEngine")

    @classmethod
    def getInstance(cls):
        if cls._INSTANCE is None:
            cls._INSTANCE = cls()
        return cls._INSTANCE

    @classmethod
    def getSDKVersion(cls):
        return cls.SDK_VERSION

    def loadPluginFromFile(self, *args, **kwargs):
        return None

    def setDebuggerListener(self, *args, **kwargs):
        return None

    def getPluginEngine(self, *args, **kwargs):
        return None


class PluginsController:
    """Facade over the iOS plugin manager for plugins that use the app class."""

    _INSTANCE = None
    _xposed_hooks = {}
    _partial_hooks = {}

    @classmethod
    def getClass(cls):
        return _java_class_ref("com.exteragram.messenger.plugins.PluginsController")

    class HookResult:
        def __init__(self, result=None, cancel=False, is_final=False):
            self.result = result
            self.cancel = cancel
            self.isFinal = bool(is_final)

    class PluginValidationResult:
        def __init__(self, metadata=None, validation_error=None):
            self.metadata = metadata
            self.validationError = validation_error

    class PluginsEngine:
        pass

    @classmethod
    def getInstance(cls, *args, **kwargs):
        if cls._INSTANCE is None:
            cls._INSTANCE = cls()
        return cls._INSTANCE

    @property
    def plugins(self):
        try:
            import _extera_runtime

            result = {}
            for plugin_id, entry in list(_extera_runtime._PLUGINS.items()):
                if entry.instance is not None:
                    result[plugin_id] = entry.instance
            return result
        except Exception:
            return {}

    @property
    def pluginsDir(self):
        return self.getPluginsDir().getPath()

    def getPluginsDir(self):
        from extera_utils.classes import NativeFile

        path = ""
        try:
            import extera_ios

            path = extera_ios.host("paths.dir", kind="plugins") or ""
        except Exception:
            path = ""
        return NativeFile(path or ".")

    @classmethod
    def getEngines(cls):
        return {"python": PythonPluginsEngine.getInstance()}

    @property
    def engines(self):
        return self.getEngines()

    @classmethod
    def getPluginEngine(cls, name="python"):
        try:
            return cls.getEngines().get(str(name or "python"))
        except Exception:
            return None

    @classmethod
    def showInstallDialog(cls, *args, **kwargs):
        try:
            import extera_ios

            return extera_ios.host("plugins.show_install")
        except Exception:
            return None

    @classmethod
    def isPluginEngineAvailable(cls):
        try:
            import extera_ios

            return bool(extera_ios.host("runtime.is_started"))
        except Exception:
            return True

    @classmethod
    def isPluginPinned(cls, plugin_id):
        try:
            import extera_ios

            return bool(extera_ios.host("plugins.is_pinned", plugin_id=plugin_id))
        except Exception:
            return False

    @classmethod
    def setPluginPinned(cls, plugin_id, pinned):
        try:
            import extera_ios

            return bool(extera_ios.host("plugins.set_pinned", plugin_id=plugin_id, pinned=bool(pinned)))
        except Exception:
            return False

    @classmethod
    def runOnPluginsQueue(cls, runnable):
        try:
            import extera_ios

            callback = runnable.run if hasattr(runnable, "run") else runnable
            return extera_ios.run_on_ui_thread(callback)
        except Exception:
            return None

    @classmethod
    def registerFileIcon(cls, extension, icon=None):
        return 0

    @classmethod
    def unregisterFileIcon(cls, extension):
        return None

    @classmethod
    def clearFileIcons(cls):
        return None

    def addEventHook(self, plugin_id, name, match_substring=False, priority=0):
        try:
            import extera_ios

            return extera_ios.register_event_hook(plugin_id, name, match_substring, priority)
        except Exception:
            return None

    def removeEventHook(self, plugin_id, name):
        try:
            import extera_ios

            return extera_ios.remove_event_hook(plugin_id, name)
        except Exception:
            return None

    def addXposedHook(self, plugin_id, unhook):
        handle = getattr(unhook, "_handle", None) or getattr(unhook, "handle", None)
        if not handle:
            return False
        try:
            import extera_ios

            registered = extera_ios.host(
                "hooks.add_xposed", plugin_id=plugin_id, handle=str(handle)
            )
            self._xposed_hooks.setdefault(plugin_id, []).append(unhook)
            return bool(registered)
        except Exception:
            return False

    def addXposedHooks(self, plugin_id, unhooks):
        result = True
        for unhook in list(unhooks or []):
            result = self.addXposedHook(plugin_id, unhook) and result
        return result

    def removeXposedHook(self, plugin_id, unhook):
        handle = getattr(unhook, "_handle", None) or getattr(unhook, "handle", None)
        registered = self._xposed_hooks.get(plugin_id, [])
        if unhook in registered:
            registered.remove(unhook)
        if not handle:
            return False
        try:
            import extera_ios

            extera_ios.host("runtime.unswizzle", handle=str(handle))
            return True
        except Exception:
            return False

    def addPartialHook(self, plugin_id, handle):
        if handle is None:
            return False
        native_handle = getattr(handle, "handle", None) or handle
        if not isinstance(native_handle, str):
            return False
        try:
            import extera_ios

            extera_ios.host(
                "hooks.add_xposed", plugin_id=plugin_id, handle=native_handle
            )
            self._partial_hooks.setdefault(plugin_id, []).append(handle)
            return True
        except Exception:
            return False

    def removePartialHook(self, plugin_id, handle):
        registered = self._partial_hooks.get(plugin_id, [])
        if handle in registered:
            registered.remove(handle)
        try:
            if hasattr(handle, "unhook"):
                handle.unhook()
            else:
                import extera_ios

                extera_ios.host("runtime.unswizzle", handle=str(handle))
            return True
        except Exception:
            return False

    def addMenuItem(self, plugin_id, data):
        try:
            import extera_ios

            return extera_ios.add_menu_item(plugin_id, data)
        except Exception:
            return None

    def removeMenuItem(self, plugin_id, item_id):
        try:
            import extera_ios

            return extera_ios.remove_menu_item(plugin_id, item_id)
        except Exception:
            return False

    def setPluginEnabled(self, plugin_id, enabled, callback=None):
        result = None
        try:
            import extera_ios

            result = extera_ios.host("plugins.set_enabled", plugin_id=plugin_id, enabled=bool(enabled))
        except Exception:
            result = None
        if callback is not None:
            callback(None)
        return result

    def deletePlugin(self, plugin_id, callback=None):
        result = None
        try:
            import _extera_runtime

            result = _extera_runtime.unload_plugin(plugin_id)
        except Exception:
            result = None
        if callback is not None:
            callback(None)
        return result

    def loadPluginSettings(self, plugin_id):
        return None

    def invalidatePluginSettings(self, plugin_id):
        return None

    def clearPluginSettingsPreferences(self, plugin_id, clear_enabled_state=False):
        try:
            import plugin_settings

            plugin_settings.clear_settings(plugin_id)
        except Exception:
            pass
        return None

    def hasPluginSettings(self, plugin_id):
        try:
            import _extera_runtime

            entry = _extera_runtime._PLUGINS.get(plugin_id)
            if entry is not None and entry.instance is not None:
                return bool(entry.instance.create_settings() or [])
        except Exception:
            pass
        return False

    def getPluginSettingBoolean(self, plugin_id, key, default=False):
        try:
            import plugin_settings

            return bool(plugin_settings.get_setting(plugin_id, key, default))
        except Exception:
            return default

    def getPluginSettingString(self, plugin_id, key, default=None):
        try:
            import plugin_settings

            return plugin_settings.get_setting(plugin_id, key, default)
        except Exception:
            return default

    def getPluginSettingInt(self, plugin_id, key, default=0):
        try:
            import plugin_settings

            return int(plugin_settings.get_setting(plugin_id, key, default))
        except Exception:
            return default

    def setPluginSetting(self, plugin_id, key, value):
        try:
            import plugin_settings

            plugin_settings.set_setting(plugin_id, key, value)
        except Exception:
            pass

    def isPluginActive(self, plugin_id):
        try:
            import _extera_runtime

            entry = _extera_runtime._PLUGINS.get(plugin_id)
            return bool(entry is not None and entry.instance is not None)
        except Exception:
            return False


class PipController:
    """`com.exteragram.messenger.plugins.pip.PipController` stub."""

    INSTANCE = None

    class InstallerDelegate:
        def onInstallationFinished(self, *args):
            pass

        def onInstallationFailed(self, *args):
            pass

    @classmethod
    def getInstance(cls):
        return cls.INSTANCE or cls()

    def installDependencies(self, *args, **kwargs):
        return None

    def uninstallDependencies(self, plugin_id=None, *args, **kwargs):
        return None


PipController.INSTANCE = PipController()


class IntentsController:
    """`com.exteragram.messenger.utils.IntentsController` facade."""

    PLUGIN_REPOSITORY_LINK = "exteraPluginRepo"
    PLUGIN_REPOSITORY_QUERY_KEY = "c"
    PLUGIN_REPOSITORY_GIT_QUERY_KEY = "git"

    @classmethod
    def getClass(cls):
        return _java_class_ref("com.exteragram.messenger.utils.IntentsController")

    @classmethod
    def getInstance(cls, account=0):
        return cls()

    def openUrl(self, url, *args, **kwargs):
        try:
            import extera_ios

            return extera_ios.open_url(str(url))
        except Exception:
            return None

    def openTelegramLink(self, url):
        return self.openUrl(url)

    def shareText(self, text, *args, **kwargs):
        try:
            import extera_ios

            return extera_ios.copy_to_clipboard(str(text))
        except Exception:
            return None

    def handleIntent(self, intent):
        return None


class PluginsConstants:
    """`com.exteragram.messenger.plugins.PluginsConstants`."""

    class Settings:
        TYPE_SWITCH = "switch"
        TYPE_SELECTOR = "selector"
        TYPE_INPUT = "input"
        TYPE_TEXT = "text"
        TYPE_HEADER = "header"
        TYPE_DIVIDER = "divider"
        TYPE_EDIT_TEXT = "edit_text"
        TYPE_CUSTOM = "custom"

    PYTHON = "python"
    SEND_MESSAGE_HOOK = "send_message_hook"
    STRATEGY = "strategy"
    PARAMS = "params"
    UPDATE = "update"
    UPDATES = "updates"
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    PLUGINS = "plugins"
    PLUGINS_EXT = ".plugin"
    PLUGINS_SDK = "plugins-sdk"
    CREATE_SETTINGS = "create_settings"
    APP_START = "app_start"
    APP_STOP = "app_stop"
    APP_PAUSE = "app_pause"
    APP_RESUME = "app_resume"
    ON_APP_EVENT = "on_app_event"
    ON_PLUGIN_LOAD = "on_plugin_load"
    ON_PLUGIN_UNLOAD = "on_plugin_unload"

    class Strategy:
        MODIFY = "MODIFY"
        CANCEL = "CANCEL"
        DEFAULT = "DEFAULT"
        MODIFY_FINAL = "MODIFY_FINAL"

    class MenuItemTypes:
        MESSAGE_CONTEXT_MENU = "message_context_menu"
        DRAWER_MENU = "drawer_menu"
        MAIN_MENU = "main_menu"
        CHAT_ACTION_MENU = "chat_action_menu"
        PROFILE_ACTION_MENU = "profile_action_menu"

    class MenuItemProperties:
        MENU_TYPE = "menu_type"
        ITEM_ID = "item_id"
        TEXT = "text"
        SUBTEXT = "subtext"
        ICON = "icon"
        CONDITION = "condition"
        PRIORITY = "priority"

    class HookFilterTypes:
        RESULT_IS_NULL = "result_is_null"
        RESULT_IS_TRUE = "result_is_true"
        RESULT_IS_FALSE = "result_is_false"
        RESULT_NOT_NULL = "result_not_null"
        RESULT_IS_INSTANCE_OF = "result_is_instance_of"
        RESULT_EQUAL = "result_equal"
        RESULT_NOT_EQUAL = "result_not_equal"
        ARGUMENT_IS_NULL = "argument_is_null"
        ARGUMENT_IS_TRUE = "argument_is_true"
        ARGUMENT_IS_FALSE = "argument_is_false"
        ARGUMENT_NOT_NULL = "argument_not_null"
        ARGUMENT_IS_INSTANCE_OF = "argument_is_instance_of"
        ARGUMENT_EQUAL = "argument_equal"
        ARGUMENT_NOT_EQUAL = "argument_not_equal"
        CONDITION = "condition"
        OR = "or"

    class Xposed:
        REPLACE_HOOKED_METHOD = "replace_hooked_method"
        BEFORE_HOOKED_METHOD = "before_hooked_method"
        AFTER_HOOKED_METHOD = "after_hooked_method"


class _ExteraConfigMeta(type):
    """Reads and writes the app flags through the host `config.*` bridge."""

    def __getattr__(cls, name):
        if name.startswith("get") and len(name) > 3:
            key = name[3].lower() + name[4:]
            return lambda: cls._read(key)
        if name.startswith("set") and len(name) > 3:
            key = name[3].lower() + name[4:]
            return lambda value: cls._write(key, value)
        value = cls._read(name)
        if value is cls._MISSING:
            raise AttributeError(name)
        return value

    def __setattr__(cls, name, value):
        if name.startswith("_"):
            return super().__setattr__(name, value)
        cls._write(name, value)


class ExteraConfig(metaclass=_ExteraConfigMeta):
    """The app flags Android's `com.exteragram.messenger.ExteraConfig` exposes."""

    _MISSING = object()
    _OVERRIDES = {}
    _DEFAULTS = {
        "translationProvider": 0,
        "disableNumberRounding": False,
        "formatTimeWithSeconds": False,
        "relativeLastSeen": False,
        "inAppVibration": True,
        "disableNotificationDelay": False,
        "filterZalgo": True,
        "downloadSpeedBoost": 0,
        "uploadSpeedBoost": False,
        "hidePhoneNumber": False,
        "showIdAndDc": 1,
        "defaultProfileTab": 0,
        "hideArchiveFolder": False,
        "archiveOnPull": False,
        "disableUnarchiveSwipe": True,
        "doNotUseProxy": 0,
        "customSavePath": "exteraGram",
        "iconPack": 0,
        "editingIconPackId": None,
        "avatarCorners": 28.0,
        "singleCornerRadius": False,
        "dividerStyle": 1,
        "forceSnow": False,
        "hideActionBarStatus": False,
        "centerTitle": False,
        "hideStories": False,
        "hideFloatingButton": False,
        "hideDialogsSearchBar": False,
        "senderMiniAvatars": True,
        "titleText": 0,
        "tabIcons": 1,
        "tabCounterMode": 0,
        "hideAllChats": False,
        "squareFab": True,
        "sectionRadius": 20.0,
        "newLoadingStyle": True,
        "newSliderStyle": True,
        "newSwitchStyle": True,
        "newChatHeaderStyle": False,
        "newNavigationBarStyle": False,
        "newFabStyle": False,
        "newProfileActionsStyle": False,
        "newPlayerStyle": False,
        "playerCoverColors": False,
        "playerMiniCoverColors": False,
        "lyricsOnline": False,
        "lyricsProviders": ["lrclib", "lrcmux"],
        "lyricsProgress": 1,
        "lyricsSubtitle": 1,
        "playerMotionCovers": False,
        "playerSpotifyCanvas": False,
        "playerYandexCanvas": False,
        "playerRhythmBackground": True,
        "playerParticles": False,
        "playerSpeedPitch": False,
        "playerMode": 0,
        "tabletMode": 0,
        "tabletLeftFraction": 0.35,
        "useSystemFonts": True,
        "gooeyAvatarAnimation": True,
        "customThemes": True,
        "predictiveBackIntensity": 1.0,
        "transitionAnimation": 2,
        "glassOutlineStyle": 0,
        "glassMessageMenu": True,
        "headerBlurStyle": 1,
        "eventType": 0,
        "navigationDrawer": False,
        "immersiveDrawerAnimation": False,
        "hideNavigationBarLabels": False,
        "showFeedTab": False,
        "showFeedUnreadCounter": True,
        "stickerSize": 12.0,
        "stickerTimeMode": 0,
        "replyColors": True,
        "replyEmoji": True,
        "replyBackground": True,
        "stickerShape": 1,
        "unlimitedRecentStickers": False,
        "hideReactionsInPrivateChats": False,
        "hideReactionsInChannels": False,
        "hideReactionsInGroups": False,
        "doubleTapAction": 1,
        "doubleTapActionOutOwner": 1,
        "swipeActions": "0",
        "swipeActionsLoop": False,
        "swipeActionsReversed": False,
        "bottomButton": 2,
        "widePostsInFeed": True,
        "widePostsInChannels": False,
        "telegramAiEditor": True,
        "telegramAiSummaries": True,
        "telegramAiInstantViewSummaries": True,
        "quickAdminShortcuts": True,
        "quickTransitionForChannels": True,
        "quickTransitionForTopics": True,
        "disableGreetingSticker": False,
        "autoRunWidgets": False,
        "hideKeyboardOnScroll": True,
        "addCommaAfterMention": True,
        "inlineResults": True,
        "inlineMathResult": True,
        "inlineCurrencyRates": True,
        "inlineUnitConversion": True,
        "inlineTimeZones": False,
        "inlineTargetCurrency": "",
        "inlineAngleUnit": 0,
        "inlineMeasureSystem": 0,
        "inlineDigitGrouping": True,
        "disableMarkdown": False,
        "hideSendAsPeer": False,
        "removeMessageTail": True,
        "replaceEditedWithIcon": True,
        "showOnlineStatus": False,
        "showForwardsCount": False,
        "hideShareButton": True,
        "showResultsBeforeVoting": False,
        "showCopyPhotoButton": True,
        "showSaveMessageButton": False,
        "showRepeatMessageButton": False,
        "showClearButton": True,
        "showHistoryButton": False,
        "showReportButton": True,
        "showGenerateButton": True,
        "showDetailsButton": False,
        "groupMessageMenu": True,
        "recognitionLanguage": "none",
        "postprocessingWithAi": False,
        "cameraType": 0,
        "extendedFramesPerSecond": False,
        "cameraStabilization": False,
        "cameraMirrorMode": True,
        "videoMessagesCamera": 0,
        "rememberLastUsedCamera": False,
        "startWithWideAngleCamera": False,
        "zoomSlider": True,
        "staticZoom": False,
        "alwaysSendInHD": True,
        "hideCameraTile": False,
        "doubleTapSeekDuration": 1,
        "preferOriginalQuality": False,
        "swipeToPip": False,
        "unmuteWithVolumeButtons": False,
        "pauseOnMinimizeVideo": True,
        "pauseOnMinimizeVoice": False,
        "pauseOnMinimizeRound": False,
        "messageExportWatermark": True,
        "messageExportSource": True,
        "messageExportAuthors": False,
        "messageExportTime": True,
        "useGoogleCrashlytics": False,
        "useGoogleAnalytics": False,
        "enableAdBlock": True,
        "exportTypes": 0,
        "exportFullChats": 0,
        "exportMediaTypes": 0,
        "exportSizeLimit": 8 * 1024 * 1024,
        "exportFormat": 0,
        "exportFolder": "",
        "updateScheduleTimestamp": 0,
        "sdkUpdateScheduleTimestamp": 0,
        "targetLang": "app",
        "flashWarmth": 0.5,
        "flashIntensity": 1.0,
        "pluginsEngine": True,
        "pluginsDevMode": False,
        "pluginsSafeMode": False,
        "pluginsCompactView": False,
        "pluginsPySdkAutoUpdate": False,
        "pluginsPySdkBetaVersions": False,
        "pluginsDisableArtOpts": False,
        "pluginsUnknownSources": False,
        "pluginsStaticAnalysis": True,
        "pinnedPlugins": [],
        "useSystemIconShape": True,
        "doNotMarkAsNew": [],
        "newFeaturesShowedAt": {},
        "radius": 0.0,
    }

    @classmethod
    def getInstance(cls):
        return cls

    @classmethod
    def _read(cls, key):
        try:
            from extera_ios import host

            value = host("config.get", key=key)
            if isinstance(value, dict) and "error" in value:
                value = None
            if value is not None:
                return value
        except Exception:
            pass
        if key in cls._OVERRIDES:
            value = cls._OVERRIDES[key]
        else:
            value = cls._DEFAULTS.get(key, cls._MISSING)
        if isinstance(value, list):
            return list(value)
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, set):
            return set(value)
        return value

    @classmethod
    def _write(cls, key, value):
        cls._OVERRIDES[key] = value
        try:
            from extera_ios import host

            host("config.set", key=key, value=value)
        except Exception:
            pass
        return True

    @classmethod
    def isProxyDisabledOn(cls, condition):
        return bool(int(cls.doNotUseProxy or 0) & int(condition or 0))

    @classmethod
    def setProxyDisabledOn(cls, condition, disable):
        value = int(cls.doNotUseProxy or 0)
        if disable:
            value |= int(condition or 0)
        else:
            value &= ~int(condition or 0)
        cls.doNotUseProxy = value


class AppUtils:
    @staticmethod
    def log(text):
        FileLog.d(str(text))


class MVEL:
    """`org.mvel2.MVEL` facade over the SDK's condition evaluator."""

    @staticmethod
    def eval(expression, context=None):
        try:
            import json
            import _extera_runtime

            raw = _extera_runtime.evaluate_condition(expression, json.dumps(context or {}))
            return json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return None


class BuildVars(metaclass=_TolerantClassMeta):
    BUILD_VERSION = 66999
    BUILD_VERSION_STRING = "13.2.1"
    APP_ID = 0
    APP_HASH = ""
    DEBUG_VERSION = False
    LOGS_ENABLED = False
    DEBUG_PRIVATE_VERSION = False
    USE_CLOUD_STRINGS = True
    CHECK_UPDATES = False
    NO_SCOPED_STORAGE = False
    PM_BUILD = False
    IS_LITE_VERSION = False
    SAFETYNET_KEY = ""
    GITHUB_APP_URL = "https://github.com/exteraSquad/exteraGram/releases/latest"
    RELEASES_URL = "https://t.me/exteraReleases"
    GOOGLE_AUTH_CLIENT_ID = ""
    IS_BILLING_UNAVAILABLE = False
    SUPPORTS_PASSKEYS = True
    isBeta = False

    @staticmethod
    def getExteraAppId():
        return 0

    @staticmethod
    def getExteraAppHash():
        return ""

    @staticmethod
    def getSmsHash():
        return ""

    @staticmethod
    def isBetaApp():
        return False

    @staticmethod
    def useInvoiceBilling():
        return False


class BuildConfig:
    APPLICATION_ID = "org.telegram.Telegram"
    BUILD_TYPE = "release"
    DEBUG = False
    FLAVOR = "full"
    VERSION_CODE = BuildVars.BUILD_VERSION
    VERSION_NAME = BuildVars.BUILD_VERSION_STRING


class PackageInfo:
    def __init__(self, package_name):
        self.packageName = str(package_name)
        self.versionName = BuildVars.BUILD_VERSION_STRING
        self.versionCode = BuildVars.BUILD_VERSION
        self.firstInstallTime = 0
        self.lastUpdateTime = 0


class PackageManager:
    GET_META_DATA = 128
    GET_ACTIVITIES = 1
    GET_PROVIDERS = 8
    GET_RECEIVERS = 2
    GET_SERVICES = 4

    def getPackageInfo(self, package_name, flags=0):
        return PackageInfo(package_name)

    def getApplicationLabel(self, info):
        return "Telegram"

    def getLaunchIntentForPackage(self, package_name):
        return None


class PyException(Exception):
    """`com.chaquo.python.PyException`, catchable from plugin code."""

    def __init__(self, message="", cause=None):
        super().__init__(str(message))
        self.message = str(message)
        self.cause = cause

    def getMessage(self):
        return self.message

    def getCause(self):
        return self.cause

    @classmethod
    def getClass(cls):
        return _java_class_ref("com.chaquo.python.PyException")


class Python:
    """`com.chaquo.python.Python`; the runtime is Python already."""

    _INSTANCE = None

    @classmethod
    def getInstance(cls):
        if cls._INSTANCE is None:
            cls._INSTANCE = cls()
        return cls._INSTANCE

    def getModule(self, name):
        import importlib

        return PyObject(importlib.import_module(str(name)))

    def getPlatform(self):
        return "ios"

    def getVersion(self):
        import sys

        return ".".join(str(part) for part in sys.version_info[:3])

    def start(self, *args, **kwargs):
        return None

    def getIsStarted(self):
        return True

    @classmethod
    def getClass(cls):
        return _java_class_ref("com.chaquo.python.Python")


class _ProxyList(list):
    def size(self):
        return len(self)

    def get(self, index):
        try:
            return self[int(index)]
        except (IndexError, TypeError, ValueError):
            return None

    def add(self, value):
        self.append(value)
        return True


class ProxyInfo:
    def __init__(self, address="", port=0, username="", password="", secret=""):
        self.address = str(address or "")
        try:
            self.port = int(port or 0)
        except (TypeError, ValueError):
            self.port = 0
        self.username = str(username or "")
        self.password = str(password or "")
        self.secret = str(secret or "")

    def __str__(self):
        return "%s:%s" % (self.address, self.port)


class SharedConfig(metaclass=_TolerantClassMeta):
    passcodeHash = ""
    isFrozen = False
    showNotifications = True
    contactsWriterEnabled = True
    appLocked = False
    autoLockIn = 3600
    passcodeType = 0
    passcodeRetryInMs = 0
    badPasscodeTries = 0
    saveIncomingPhotos = False
    allowScreenCapture = True
    useFingerprintLock = True
    useFaceLock = True
    suggestStickers = 0
    suggestAnimatedEmoji = True
    keepMedia = 30 * 24 * 60 * 60
    disableVoiceAudioEffects = False
    forceDisableTabletMode = False
    updateStickersOrderOnSend = True
    bigCameraForRound = False
    useSurfaceInStories = False
    photoViewerBlur = True
    payByInvoice = False
    directShareHash = ""
    forceForumTabs = False
    fastWallpaperDisabled = False
    frameMetricsEnabled = False
    pushType = 1
    pushString = ""
    pushStringStatus = ""
    pushStatSent = False
    storiesIntroShown = False
    storyReactionsLongPressHint = False
    searchMessagesAsListUsed = False
    stickersReorderingHintUsed = False
    forwardingOptionsHintShown = False
    replyingOptionsHintShown = False
    readOnlyStorageDirAlertShowed = False
    animationsEnabled = True
    autoplayGifs = True
    autoplayVideo = True
    compactMode = False
    chatBlurEnabled = True
    proxyEnabled = False
    passportConfigLoaded = False
    usingCamera2 = True
    appUpdateAvailable = False
    secretMapPreviewSet = False
    mediaColumnsCount = 3
    playbackOrderType = 0
    lastLocalId = 0
    lastCheckedBackgroundActivity = 0
    dismissedCount = 0
    fastScrollHintCount = 3
    distanceSystemType = 0
    chosenDebugConfig = 0
    proxyList = _ProxyList()
    currentProxyInfo = None
    currentProxy = None

    @classmethod
    def isPremium(cls):
        return False

    @classmethod
    def loadProxyList(cls, *args, **kwargs):
        return cls.proxyList

    @classmethod
    def saveProxyList(cls, *args, **kwargs):
        return None

    @classmethod
    def saveConfig(cls, *args, **kwargs):
        return None

    @classmethod
    def addProxy(cls, *args, **kwargs):
        if args and isinstance(args[0], ProxyInfo):
            proxy = args[0]
        elif args:
            proxy = ProxyInfo(
                args[0],
                args[1] if len(args) > 1 else kwargs.get("port", 0),
                args[2] if len(args) > 2 else kwargs.get("username", ""),
                args[3] if len(args) > 3 else kwargs.get("password", ""),
                args[4] if len(args) > 4 else kwargs.get("secret", ""),
            )
        else:
            proxy = ProxyInfo(**kwargs)
        if proxy not in cls.proxyList:
            cls.proxyList.add(proxy)
        cls.currentProxyInfo = proxy
        cls.currentProxy = proxy
        return proxy

    @classmethod
    def deleteProxy(cls, proxy, *args, **kwargs):
        try:
            cls.proxyList[:] = [
                item for item in cls.proxyList
                if item is not proxy and str(item) != str(proxy)
            ]
        except Exception:
            pass
        return None

    @classmethod
    def setAnimationsEnabled(cls, value, *args, **kwargs):
        cls.animationsEnabled = bool(value)
        return None

    @classmethod
    def isAutoplayGifs(cls, *args, **kwargs):
        return True

    @classmethod
    def isAutoplayVideo(cls, *args, **kwargs):
        return True

    @classmethod
    def isCompactMode(cls, *args, **kwargs):
        return bool(cls.compactMode)

    @classmethod
    def chatBlurEnabled(cls, *args, **kwargs):
        return True

    @classmethod
    def canBlurChat(cls, *args, **kwargs):
        return True

    @classmethod
    def isProxyEnabled(cls, *args, **kwargs):
        return False

    @classmethod
    def loadProxyList(cls, *args, **kwargs):
        return None

    @classmethod
    def deviceIsLow(cls, *args, **kwargs):
        return False

    @classmethod
    def deviceIsAverage(cls, *args, **kwargs):
        return True

    @classmethod
    def deviceIsHigh(cls, *args, **kwargs):
        return False

    @classmethod
    def deviceIsAboveAverage(cls, *args, **kwargs):
        return True

    @classmethod
    def getDevicePerformanceClass(cls, *args, **kwargs):
        return 2

    @classmethod
    def getLegacyDevicePerformanceClass(cls, *args, **kwargs):
        return 1

    @classmethod
    def performanceClassName(cls, value=None, *args, **kwargs):
        return "CLASS_MID_RANGE"

    @classmethod
    def measureDevicePerformanceClass(cls, *args, **kwargs):
        return 2

    @classmethod
    def overrideDevicePerformanceClass(cls, *args, **kwargs):
        return None

    @classmethod
    def getChatSwipeAction(cls, *args, **kwargs):
        return 0

    @classmethod
    def getCountryLangs(cls, *args, **kwargs):
        return ["en"]

    @classmethod
    def getLastLocalId(cls, *args, **kwargs):
        cls.lastLocalId += 1
        return cls.lastLocalId

    @classmethod
    def getLastCheckedBackgroundActivity(cls, *args, **kwargs):
        return cls.lastCheckedBackgroundActivity

    @classmethod
    def setLastCheckedBackgroundActivity(cls, value, *args, **kwargs):
        cls.lastCheckedBackgroundActivity = int(value or 0)
        return None

    @classmethod
    def getDismissedCount(cls, *args, **kwargs):
        return cls.dismissedCount

    @classmethod
    def increaseDismissedCount(cls, *args, **kwargs):
        cls.dismissedCount += 1
        return None

    @classmethod
    def isPassportConfigLoaded(cls, *args, **kwargs):
        return bool(cls.passportConfigLoaded)

    @classmethod
    def setPassportConfig(cls, *args, **kwargs):
        cls.passportConfigLoaded = True
        return None

    @classmethod
    def isUsingCamera2(cls, *args, **kwargs):
        return True

    @classmethod
    def isAppUpdateAvailable(cls, *args, **kwargs):
        return False

    @classmethod
    def checkPasscode(cls, *args, **kwargs):
        return None

    @classmethod
    def getMediaColumnsCount(cls, *args, **kwargs):
        return int(cls.mediaColumnsCount)

    @classmethod
    def setMediaColumnsCount(cls, value, *args, **kwargs):
        cls.mediaColumnsCount = int(value or 3)
        return None

    @classmethod
    def getPlaybackOrderType(cls, *args, **kwargs):
        return int(cls.playbackOrderType)

    @classmethod
    def isSecretMapPreviewSet(cls, *args, **kwargs):
        return False

    @classmethod
    def reloadConfig(cls, *args, **kwargs):
        return None

    @classmethod
    def saveDebugConfig(cls, *args, **kwargs):
        return None

    @classmethod
    def normalizeAvailableCheckTime(cls, value, *args, **kwargs):
        return value

    @classmethod
    def loopStickers(cls):
        return False

    @classmethod
    def allowPreparingHevcPlayers(cls):
        return False

    @classmethod
    def findGoodHevcEncoder(cls):
        return None

    @classmethod
    def togglePaymentByInvoice(cls):
        return None

    @classmethod
    def toggleSurfaceInStories(cls):
        return None

    @classmethod
    def togglePhotoViewerBlur(cls):
        return None

    @classmethod
    def checkSdCard(cls, file=None):
        return None

    @classmethod
    def versionBiggerOrEqual(cls, actual, required):
        def parts(value):
            result = []
            for piece in str(value or "0").split("."):
                digits = "".join(character for character in piece if character.isdigit())
                result.append(int(digits or 0))
            return result

        left = parts(actual)
        right = parts(required)
        length = max(len(left), len(right))
        left += [0] * (length - len(left))
        right += [0] * (length - len(right))
        return left >= right


class FileLog:
    """`org.telegram.messenger.FileLog`, routed to the plugin log."""

    @staticmethod
    def _write(text, error=None):
        message = str(text)
        if error is not None:
            message = message + "\n" + str(error)
        try:
            import extera_ios

            extera_ios.log("[FileLog] " + message)
        except Exception:
            pass

    @staticmethod
    def e(text, error=None):
        FileLog._write(text, error)

    @staticmethod
    def w(text, error=None):
        FileLog._write(text, error)

    @staticmethod
    def d(text, error=None):
        FileLog._write(text, error)

    @staticmethod
    def i(text, error=None):
        FileLog._write(text, error)


class TextUtils:
    class TruncateAt:
        START = "start"
        MIDDLE = "middle"
        END = "end"
        MARQUEE = "marquee"

    @staticmethod
    def isEmpty(value):
        return value is None or len(value) == 0

    @staticmethod
    def equals(first, second):
        return first == second

    @staticmethod
    def join(delimiter, values):
        return str(delimiter).join(str(value) for value in (values or []))

    @staticmethod
    def split(text, expression):
        import re

        return [item for item in re.split(expression, text or "") if item]

    @staticmethod
    def isDigitsOnly(text):
        return bool(text) and str(text).isdigit()

    @staticmethod
    def concat(*values):
        return "".join(str(value) for value in values if value is not None)

    @staticmethod
    def getReverse(text):
        return str(text or "")[::-1]

    @staticmethod
    def substring(text, start, end=None):
        value = str(text or "")
        if end is None:
            return value[int(start):]
        return value[int(start): int(end)]

    @staticmethod
    def indexOf(text, needle):
        return str(text or "").find(str(needle))

    @staticmethod
    def lastIndexOf(text, needle):
        return str(text or "").rfind(str(needle))

    @staticmethod
    def replace(text, old, new):
        return str(text or "").replace(str(old), str(new))

    @staticmethod
    def getTrimmedLength(text):
        return len(str(text or "").strip())

    @staticmethod
    def ellipsize(text, paint, availableWidth, ellipsize):
        value = str(text or "")
        try:
            width = float(availableWidth)
            if width <= 0:
                return ""
            limit = max(1, int(width / 8))
        except Exception:
            return value
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 1)] + "…"


class Log:
    @staticmethod
    def d(tag, message):
        FileLog.d("%s: %s" % (tag, message))

    @staticmethod
    def i(tag, message):
        FileLog.d("%s: %s" % (tag, message))

    @staticmethod
    def v(tag, message):
        FileLog.d("%s: %s" % (tag, message))

    @staticmethod
    def w(tag, message):
        FileLog._write("%s: %s" % (tag, message), None)

    @staticmethod
    def e(tag, message, error=None):
        FileLog.e("%s: %s" % (tag, message), error)

    @staticmethod
    def println(priority, tag, message):
        FileLog.d("%s: %s" % (tag, message))


class SystemClock:
    @staticmethod
    def elapsedRealtime():
        return int(time.time() * 1000)

    @staticmethod
    def uptimeMillis():
        return int(time.monotonic() * 1000)

    @staticmethod
    def sleep(milliseconds):
        time.sleep(max(0, int(milliseconds)) / 1000.0)


class MovementMethod:
    def initialize(self, widget=None, text=None):
        return None

    def onKeyDown(self, *args):
        return False

    def onKeyUp(self, *args):
        return False

    def onKeyOther(self, *args):
        return False

    def onTouchEvent(self, *args, **kwargs):
        return False

    def onTrackballEvent(self, *args):
        return False

    def onGenericMotionEvent(self, *args):
        return False

    def onTakeFocus(self, *args):
        return None

    def canSelectArbitrarily(self):
        return False


class BaseMovementMethod(MovementMethod):
    pass


class LinkMovementMethod(BaseMovementMethod):
    _instance = None

    @classmethod
    def getInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


class ArrowKeyMovementMethod(BaseMovementMethod):
    _instance = None

    @classmethod
    def getInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


class InputFilter:
    def filter(self, source, start=0, end=0, dest=None, dstart=0, dend=0):
        return None


class _AllCapsInputFilter(InputFilter):
    def filter(self, source, start=0, end=0, dest=None, dstart=0, dend=0):
        try:
            import android.text

            return android.text.SpannableString(
                str(source)[int(start):int(end)].upper()
            )
        except Exception:
            return None


class _LengthInputFilter(InputFilter):
    def __init__(self, max_length=0):
        self.max_length = int(max_length or 0)

    def filter(self, source, start=0, end=0, dest=None, dstart=0, dend=0):
        return None


InputFilter.AllCaps = _AllCapsInputFilter
InputFilter.LengthFilter = _LengthInputFilter


class NumberKeyListener:
    def getInputType(self):
        return 2

    def getAcceptedChars(self):
        return "0123456789"


class DigitsKeyListener(NumberKeyListener):
    def __init__(self, sign=False, decimal=False):
        self.sign = bool(sign)
        self.decimal = bool(decimal)

    @classmethod
    def getInstance(cls, accepted="0123456789"):
        instance = cls()
        instance.accepted = str(accepted or "")
        return instance

    def filter(self, source, start=0, end=0, dest=None, dstart=0, dend=0):
        return None


class TransformationMethod:
    def getTransformation(self, source, view=None):
        try:
            import android.text

            return android.text.SpannableString(str(source))
        except Exception:
            return source

    def onFocusChanged(self, *args):
        return None


class PasswordTransformationMethod(TransformationMethod):
    _instance = None

    @classmethod
    def getInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def getTransformation(self, source, view=None):
        try:
            import android.text

            return android.text.SpannableString("\u2022" * len(str(source)))
        except Exception:
            return source


class HideReturnsTransformationMethod(TransformationMethod):
    _instance = None

    @classmethod
    def getInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


class SingleLineTransformationMethod(TransformationMethod):
    _instance = None

    @classmethod
    def getInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


class MetaKeyKeyListener:
    @staticmethod
    def clearMetaKeyState(*args):
        return None

    @staticmethod
    def getMetaState(text=None, meta=None, current=None):
        return 0

    @staticmethod
    def isMetaKey(meta=0):
        return False

    @staticmethod
    def resetLockedMeta(text=None):
        return 0

    @staticmethod
    def adjustMetaAfterKeypress(text=None):
        return 0


class ScrollingMovementMethod(LinkMovementMethod):
    pass


class ArrowKeyMovementMethod(LinkMovementMethod):
    pass


class URLConnection:
    HTTP_OK = 200
    HTTP_CREATED = 201
    HTTP_ACCEPTED = 202
    HTTP_NO_CONTENT = 204
    HTTP_MOVED_PERM = 301
    HTTP_MOVED_TEMP = 302
    HTTP_NOT_MODIFIED = 304
    HTTP_BAD_REQUEST = 400
    HTTP_UNAUTHORIZED = 401
    HTTP_FORBIDDEN = 403
    HTTP_NOT_FOUND = 404
    HTTP_INTERNAL_ERROR = 500

    def __init__(self, url=""):
        self.url = str(url or "")
        self.doInput = True
        self.doOutput = False
        self.connectTimeout = 0
        self.readTimeout = 0
        self._headers = {}

    def setRequestProperty(self, key, value):
        self._headers[str(key)] = str(value)
        return None

    def addRequestProperty(self, key, value):
        return self.setRequestProperty(key, value)

    def setConnectTimeout(self, milliseconds):
        self.connectTimeout = int(milliseconds or 0)
        return None

    def setReadTimeout(self, milliseconds):
        self.readTimeout = int(milliseconds or 0)
        return None

    def setDoInput(self, value):
        self.doInput = bool(value)
        return None

    def setDoOutput(self, value):
        self.doOutput = bool(value)
        return None

    def connect(self):
        return None

    def disconnect(self):
        return None

    def getHeaderField(self, name):
        return None

    def getHeaderFields(self):
        return {}

    def getContentLength(self):
        return -1

    def getContentType(self):
        return None

    def getURL(self):
        return URL(self.url)

    def getDoInput(self):
        return self.doInput

    def getDoOutput(self):
        return self.doOutput

    def getConnectTimeout(self):
        return self.connectTimeout

    def getReadTimeout(self):
        return self.readTimeout

    def toString(self):
        return str(self.url)

    def getInputStream(self):
        raise OSError("not connected")

    def getOutputStream(self):
        raise OSError("not connected")


class HttpURLConnection(URLConnection):
    def __init__(self, url=""):
        super().__init__(url)
        self.method = "GET"
        self._body = b""
        self._executed = False
        self._response_code = 0
        self._response_message = ""
        self._stream = None
        self._error_stream = None
        self._response_headers = {}
        self._content_length = -1
        self._content_type = None

    def setRequestMethod(self, method):
        self.method = str(method or "GET").upper()
        return None

    def getRequestMethod(self):
        return self.method

    def getURL(self):
        return URL(self.url)

    def _execute(self):
        if self._executed:
            return
        self._executed = True
        import io
        import urllib.error
        import urllib.request

        data = None
        if self.doOutput or self.method in ("POST", "PUT", "PATCH"):
            data = self._body
        request = urllib.request.Request(
            self.url,
            data=data,
            headers=self._headers,
            method=self.method,
        )
        timeout = (self.connectTimeout or self.readTimeout or 30000) / 1000.0
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
            self._response_code = int(getattr(response, "status", 200))
            headers = dict(getattr(response, "headers", {}) or {})
            self._response_headers = headers
            self._content_length = int(
                headers.get("Content-Length", headers.get("content-length", -1)) or -1
            )
            self._content_type = headers.get(
                "Content-Type", headers.get("content-type")
            )
            self._stream = io.BytesIO(response.read())
        except urllib.error.HTTPError as error:
            self._response_code = int(error.code)
            self._response_message = str(error.reason or "")
            headers = dict(getattr(error, "headers", {}) or {})
            self._response_headers = headers
            self._content_length = int(
                headers.get("Content-Length", headers.get("content-length", -1)) or -1
            )
            self._content_type = headers.get(
                "Content-Type", headers.get("content-type")
            )
            payload = error.read()
            self._stream = io.BytesIO(payload)
            self._error_stream = io.BytesIO(payload)
        except Exception as error:
            self._response_code = 0
            self._response_message = str(error)
            self._response_headers = {}
            self._content_length = -1
            self._content_type = None
            self._stream = io.BytesIO(b"")
            self._error_stream = io.BytesIO(b"")

    def connect(self):
        self._execute()
        return None

    def getResponseCode(self):
        self._execute()
        return self._response_code

    def getResponseMessage(self):
        self._execute()
        return self._response_message

    def getHeaderField(self, name):
        self._execute()
        target = str(name or "").lower()
        for key, value in self._response_headers.items():
            if str(key).lower() == target:
                return value
        return None

    def getHeaderFields(self):
        self._execute()
        return dict(self._response_headers)

    def getContentLength(self):
        self._execute()
        return int(self._content_length or -1)

    def getContentType(self):
        self._execute()
        return self._content_type

    def usingProxy(self):
        return False

    def getInstanceFollowRedirects(self):
        return True

    def setInstanceFollowRedirects(self, value):
        return None

    def getInputStream(self):
        import io

        self._execute()
        return self._stream or io.BytesIO(b"")

    def getErrorStream(self):
        self._execute()
        return self._error_stream

    def getOutputStream(self):
        self.doOutput = True
        connection = self

        class _Output:
            def write(self, data):
                if isinstance(data, str):
                    data = data.encode("utf-8")
                if isinstance(data, int):
                    data = bytes([data & 0xFF])
                connection._body += bytes(data)
                return len(data)

            def flush(self):
                return None

            def close(self):
                connection._execute()

        return _Output()

    def disconnect(self):
        self._executed = False
        self._stream = None
        self._error_stream = None
        self._response_headers = {}
        self._content_length = -1
        self._content_type = None
        return None


class HttpsURLConnection(HttpURLConnection):
    """`javax.net.ssl.HttpsURLConnection`, the HTTPS variant of the client."""

    def getCipherSuite(self):
        return "TLS"

    def getPeerCertificates(self):
        return []

    def getLocalCertificates(self):
        return []


class ByteArrayOutputStream:
    """`java.io.ByteArrayOutputStream` backed by a bytearray."""

    def __init__(self, size=32):
        self._buffer = bytearray()

    def write(self, data, offset=0, length=None):
        if isinstance(data, int):
            self._buffer.append(data & 0xFF)
        elif isinstance(data, str):
            self._buffer.extend(data.encode("utf-8"))
        elif isinstance(data, (bytes, bytearray, memoryview)):
            raw = bytes(data)
            offset = int(offset or 0)
            if length is None:
                self._buffer.extend(raw[offset:])
            else:
                self._buffer.extend(raw[offset:offset + int(length)])
        else:
            self._buffer.extend(bytes(data))
        return None

    def writeBytes(self, data):
        self._buffer.extend(bytes(data or b""))
        return None

    def toByteArray(self):
        return bytes(self._buffer)

    def size(self):
        return len(self._buffer)

    def reset(self):
        self._buffer.clear()
        return None

    def flush(self):
        return None

    def close(self):
        return None

    def toString(self, charset="utf-8"):
        return self._buffer.decode(str(charset or "utf-8"), "replace")

    def writeTo(self, output):
        output.write(bytes(self._buffer))
        return None


class Thread:
    """`java.lang.Thread` facade backed by a Python daemon thread."""

    MIN_PRIORITY = 1
    NORM_PRIORITY = 5
    MAX_PRIORITY = 10
    _current = None

    def __init__(self, runnable=None, name=None):
        self._runnable = runnable
        self._thread = None
        self._priority = self.NORM_PRIORITY
        self._name = str(name or "Thread")

    def start(self):
        target = self._runnable
        if hasattr(target, "run"):
            target = target.run
        if not callable(target):
            target = self.run
        self._thread = _threading.Thread(target=target, name=self._name, daemon=True)
        self._thread.start()
        return None

    def run(self):
        if callable(self._runnable):
            return self._runnable()
        if hasattr(self._runnable, "run"):
            return self._runnable.run()
        return None

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(None if timeout is None else float(timeout) / 1000.0)
        return None

    def isAlive(self):
        return bool(self._thread is not None and self._thread.is_alive())

    def interrupt(self):
        return None

    def setPriority(self, value):
        self._priority = int(value or self.NORM_PRIORITY)
        return None

    def getPriority(self):
        return self._priority

    def setName(self, value):
        self._name = str(value or "Thread")
        return None

    def getName(self):
        return self._name

    def getId(self):
        return id(self)

    @staticmethod
    def currentThread():
        if Thread._current is None:
            Thread._current = Thread(name="main")
        return Thread._current

    @staticmethod
    def sleep(milliseconds):
        import time

        time.sleep(float(milliseconds or 0) / 1000.0)
        return None

    @staticmethod
    def yield_():
        import time

        time.sleep(0)
        return None


class InetAddress:
    """`java.net.InetAddress` resolved through the host resolver."""

    def __init__(self, host="127.0.0.1", address=None):
        self._host = str(host or "127.0.0.1")
        self._address = str(address or self._host)

    @staticmethod
    def getByName(host):
        import socket

        name = str(host or "127.0.0.1")
        try:
            return InetAddress(name, socket.gethostbyname(name))
        except Exception:
            return InetAddress(name, name)

    @staticmethod
    def getAllByName(host):
        import socket

        name = str(host or "127.0.0.1")
        try:
            return [InetAddress(name, address) for address in socket.gethostbyname_ex(name)[2]]
        except Exception:
            return [InetAddress(name, name)]

    @staticmethod
    def getLocalHost():
        return InetAddress.getByName("127.0.0.1")

    def getHostName(self):
        return self._host

    def getHostAddress(self):
        return self._address

    def getCanonicalHostName(self):
        return self._address

    def isLoopbackAddress(self):
        return self._address.startswith("127.") or self._address in ("::1", "localhost")

    def isAnyLocalAddress(self):
        return self._address in ("0.0.0.0", "::")

    def toString(self):
        return "%s/%s" % (self._host, self._address)

    def equals(self, other):
        return isinstance(other, InetAddress) and other._address == self._address

    def hashCode(self):
        return hash(self._address)

    def __str__(self):
        return self.getHostAddress()

    def __repr__(self):
        return "<InetAddress %s>" % self.toString()


class InetSocketAddress:
    """`java.net.InetSocketAddress`."""

    def __init__(self, host=None, port=0):
        if isinstance(host, int):
            port = host
            host = None
        self._host = "" if host is None else str(host)
        self._port = int(port or 0)
        self._address = None if host is None else InetAddress.getByName(str(host))

    def getHostString(self):
        return self._host

    def getHostName(self):
        return self._host

    def getAddress(self):
        return self._address

    def getPort(self):
        return self._port

    def isUnresolved(self):
        return self._address is None

    def toString(self):
        return "%s:%s" % (self._host, self._port)

    def __repr__(self):
        return "<InetSocketAddress %s>" % self.toString()


class Socket:
    """`java.net.Socket` over the CPython socket module."""

    def __init__(self, host=None, port=None):
        self._socket = None
        self._host = "" if host is None else str(host)
        self._port = int(port or 0)
        self._timeout = 0
        self._closed = False
        if host is not None and port is not None:
            self.connect(host, port)

    def connect(self, host_or_address, port=None, timeout=None):
        import socket

        if isinstance(host_or_address, InetAddress):
            host = host_or_address.getHostAddress()
        elif isinstance(host_or_address, InetSocketAddress):
            host = host_or_address.getHostString()
            port = host_or_address.getPort()
        else:
            host = str(host_or_address)
        if port is None:
            port = self._port
        timeout_seconds = None
        if timeout is not None:
            timeout_seconds = float(timeout) / 1000.0
        elif self._timeout:
            timeout_seconds = float(self._timeout) / 1000.0
        try:
            self._socket = socket.create_connection(
                (host, int(port)), timeout=timeout_seconds
            )
            self._host = host
            self._port = int(port)
            self._closed = False
        except Exception:
            self._socket = None
        return None

    def getInputStream(self):
        if self._socket is None:
            from extera_utils.classes import ByteArrayInputStream

            return ByteArrayInputStream(b"")
        return self._socket.makefile("rb")

    def getOutputStream(self):
        if self._socket is None:
            return ByteArrayOutputStream()
        return self._socket.makefile("wb")

    def close(self):
        self._closed = True
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        return None

    def isConnected(self):
        return self._socket is not None

    def isClosed(self):
        return self._closed

    def getInetAddress(self):
        return InetAddress(self._host, self._host)

    def getPort(self):
        return self._port

    def getLocalPort(self):
        try:
            return int(self._socket.getsockname()[1]) if self._socket else 0
        except Exception:
            return 0

    def setSoTimeout(self, milliseconds):
        self._timeout = int(milliseconds or 0)
        if self._socket is not None:
            try:
                self._socket.settimeout(float(self._timeout) / 1000.0)
            except Exception:
                pass
        return None

    def getSoTimeout(self):
        return self._timeout

    def setTcpNoDelay(self, value):
        if self._socket is not None:
            try:
                self._socket.setsockopt(6, 1, 1 if value else 0)
            except Exception:
                pass
        return None

    def setKeepAlive(self, value):
        if self._socket is not None:
            try:
                self._socket.setsockopt(1, 9, 1 if value else 0)
            except Exception:
                pass
        return None

    def setReuseAddress(self, value):
        return None

    def shutdownInput(self):
        return None

    def shutdownOutput(self):
        return None

    def toString(self):
        return "Socket[addr=%s,port=%s]" % (self._host, self._port)

    def __repr__(self):
        return "<Socket %s>" % self.toString()


class ServerSocket:
    """`java.net.ServerSocket` over the CPython socket module."""

    def __init__(self, port=None, backlog=50):
        self._socket = None
        self._port = int(port or 0)
        self._closed = False
        self._timeout = 0
        if port is not None:
            self.bind(self._port, backlog)

    def bind(self, port_or_address, backlog=50):
        import socket

        port = (
            port_or_address.getPort()
            if isinstance(port_or_address, InetSocketAddress)
            else int(port_or_address or 0)
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.listen(int(backlog or 50))
        self._socket = sock
        self._port = int(sock.getsockname()[1])
        self._closed = False
        return None

    def accept(self):
        if self._socket is None:
            return None
        connection, address = self._socket.accept()
        client = Socket()
        client._socket = connection
        client._host = address[0]
        client._port = address[1]
        return client

    def close(self):
        self._closed = True
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        return None

    def getLocalPort(self):
        return self._port

    def getLocalSocketAddress(self):
        return InetSocketAddress("0.0.0.0", self._port)

    def setSoTimeout(self, milliseconds):
        self._timeout = int(milliseconds or 0)
        if self._socket is not None:
            try:
                self._socket.settimeout(float(self._timeout) / 1000.0)
            except Exception:
                pass
        return None

    def getSoTimeout(self):
        return self._timeout

    def isClosed(self):
        return self._closed

    def setReuseAddress(self, value):
        return None

    def toString(self):
        return "ServerSocket[port=%s]" % self._port

    def __repr__(self):
        return "<ServerSocket %s>" % self.toString()


class SoundPool:
    """`android.media.SoundPool` facade; sound playback is host-owned."""

    class OnLoadCompleteListener:
        def onLoadComplete(self, sound_pool, sample_id, status):
            pass

    def __init__(self, max_streams=1, stream_type=3, src_quality=0):
        self.max_streams = int(max_streams or 1)
        self.stream_type = int(stream_type or 3)
        self.src_quality = int(src_quality or 0)
        self._sounds = {}
        self._next_id = 1
        self._listener = None

    def load(self, context_or_path, resource_id=None, priority=1):
        sample_id = self._next_id
        self._next_id += 1
        self._sounds[sample_id] = context_or_path
        return sample_id

    def play(self, sound_id, left_volume=1.0, right_volume=1.0, priority=0,
             loop=0, rate=1.0):
        return int(sound_id or 0)

    def stop(self, stream_id):
        return None

    def pause(self, stream_id):
        return None

    def resume(self, stream_id):
        return None

    def autoPause(self):
        return None

    def autoResume(self):
        return None

    def unload(self, sound_id):
        self._sounds.pop(int(sound_id or 0), None)
        return True

    def release(self):
        self._sounds.clear()
        return None

    def setVolume(self, stream_id, left_volume, right_volume):
        return None

    def setRate(self, stream_id, rate):
        return None

    def setLoop(self, stream_id, loop):
        return None

    def setPriority(self, stream_id, priority):
        return None

    def setOnLoadCompleteListener(self, listener):
        self._listener = listener
        return None


class URI:
    """`java.net.URI` parser."""

    def __init__(self, spec=""):
        self.spec = str(spec or "")

    @staticmethod
    def create(spec):
        return URI(spec)

    def _parts(self):
        import urllib.parse

        return urllib.parse.urlsplit(self.spec)

    def toString(self):
        return self.spec

    def __str__(self):
        return self.spec

    def getScheme(self):
        return self._parts().scheme or None

    def getHost(self):
        return self._parts().hostname

    def getPort(self):
        return self._parts().port or -1

    def getPath(self):
        return self._parts().path or ""

    def getQuery(self):
        return self._parts().query or None

    def getFragment(self):
        return self._parts().fragment or None

    def getAuthority(self):
        return self._parts().netloc or None

    def getUserInfo(self):
        parts = self._parts()
        if parts.username is None:
            return None
        if parts.password is None:
            return parts.username
        return "%s:%s" % (parts.username, parts.password)

    def isAbsolute(self):
        return bool(self._parts().scheme)

    def isOpaque(self):
        return False

    def normalize(self):
        return self

    def resolve(self, other):
        import urllib.parse

        return URI(urllib.parse.urljoin(self.spec, str(other)))

    def relativize(self, other):
        return URI(str(other))

    def toURL(self):
        return URL(self.spec)

    def equals(self, other):
        return isinstance(other, URI) and other.spec == self.spec

    def hashCode(self):
        return hash(self.spec)


class RandomAccessFile:
    """`java.io.RandomAccessFile` over a Python file object."""

    def __init__(self, path, mode="r"):
        self.path = path.getPath() if hasattr(path, "getPath") else str(path)
        self.mode = str(mode or "r")
        try:
            if "w" in self.mode or "rw" in self.mode or "+" in self.mode:
                import os

                descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT)
                self._file = os.fdopen(descriptor, "r+b")
            else:
                self._file = open(self.path, "rb")
        except Exception:
            self._file = None

    def read(self, target=None, offset=0, length=None):
        if self._file is None:
            return -1
        if target is None:
            chunk = self._file.read(1)
            return chunk[0] if chunk else -1
        if isinstance(target, int):
            return list(self._file.read(int(target)))
        offset = int(offset or 0)
        amount = int(length if length is not None else len(target) - offset)
        data = self._file.read(amount)
        target[offset:offset + len(data)] = data
        return len(data)

    def readFully(self, target, offset=0, length=None):
        return self.read(target, offset, length)

    def readByte(self):
        value = self.read()
        return value if value != -1 else 0

    def readShort(self):
        data = self._file.read(2) if self._file else b""
        return int.from_bytes(data, "big", signed=True) if data else 0

    def readInt(self):
        data = self._file.read(4) if self._file else b""
        return int.from_bytes(data, "big", signed=True) if data else 0

    def readLong(self):
        data = self._file.read(8) if self._file else b""
        return int.from_bytes(data, "big", signed=True) if data else 0

    def readUTF(self):
        data = self._file.read(2) if self._file else b""
        length = int.from_bytes(data, "big") if data else 0
        return self._file.read(length).decode("utf-8", "replace") if self._file else ""

    def readLine(self):
        if self._file is None:
            return None
        line = self._file.readline()
        if not line:
            return None
        return line.decode("utf-8", "replace").rstrip("\r\n")

    def write(self, value, offset=0, length=None):
        if self._file is None:
            return None
        if isinstance(value, int):
            data = bytes([value & 0xFF])
        elif isinstance(value, str):
            data = value.encode("utf-8")
        else:
            raw = bytes(value)
            offset = int(offset or 0)
            data = raw[offset:] if length is None else raw[offset:offset + int(length)]
        self._file.write(data)
        return None

    def writeByte(self, value):
        return self.write(int(value))

    def writeShort(self, value):
        if self._file:
            self._file.write(int(value).to_bytes(2, "big", signed=True))
        return None

    def writeInt(self, value):
        if self._file:
            self._file.write(int(value).to_bytes(4, "big", signed=True))
        return None

    def writeLong(self, value):
        if self._file:
            self._file.write(int(value).to_bytes(8, "big", signed=True))
        return None

    def writeUTF(self, value):
        data = str(value or "").encode("utf-8")
        if self._file:
            self._file.write(len(data).to_bytes(2, "big"))
            self._file.write(data)
        return None

    def seek(self, position):
        if self._file:
            self._file.seek(int(position))
        return None

    def getFilePointer(self):
        return self._file.tell() if self._file else 0

    def length(self):
        if self._file is None:
            return 0
        current = self._file.tell()
        self._file.seek(0, 2)
        size = self._file.tell()
        self._file.seek(current)
        return size

    def setLength(self, length):
        if self._file:
            self._file.truncate(int(length))
        return None

    def getFD(self):
        return self._file

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None
        return None


class DataInputStream:
    def __init__(self, source):
        self._source = source

    def _read(self, size):
        try:
            return self._source.read(int(size)) or b""
        except Exception:
            return b""

    def read(self, target=None, offset=0, length=None):
        if target is None:
            data = self._read(1)
            return data[0] if data else -1
        if isinstance(target, int):
            return list(self._read(target))
        data = self._read(int(length if length is not None else len(target) - offset))
        target[int(offset):int(offset) + len(data)] = data
        return len(data)

    def readInt(self):
        data = self._read(4)
        return int.from_bytes(data, "big", signed=True) if data else 0

    def readLong(self):
        data = self._read(8)
        return int.from_bytes(data, "big", signed=True) if data else 0

    def readShort(self):
        data = self._read(2)
        return int.from_bytes(data, "big", signed=True) if data else 0

    def readByte(self):
        value = self.read()
        return value if value != -1 else 0

    def readUTF(self):
        data = self._read(2)
        length = int.from_bytes(data, "big") if data else 0
        return self._read(length).decode("utf-8", "replace")

    def readLine(self):
        line = getattr(self._source, "readline", lambda: b"")()
        return line.decode("utf-8", "replace").rstrip("\r\n") if line else None

    def close(self):
        return None


class DataOutputStream:
    def __init__(self, target):
        self._target = target

    def _write(self, data):
        try:
            self._target.write(data)
        except Exception:
            pass
        return None

    def write(self, value, offset=0, length=None):
        if isinstance(value, int):
            self._write(bytes([value & 0xFF]))
        elif isinstance(value, str):
            self._write(value.encode("utf-8"))
        else:
            raw = bytes(value)
            offset = int(offset or 0)
            self._write(raw[offset:] if length is None else raw[offset:offset + int(length)])
        return None

    def writeInt(self, value):
        self._write(int(value).to_bytes(4, "big", signed=True))
        return None

    def writeLong(self, value):
        self._write(int(value).to_bytes(8, "big", signed=True))
        return None

    def writeShort(self, value):
        self._write(int(value).to_bytes(2, "big", signed=True))
        return None

    def writeByte(self, value):
        self._write(bytes([int(value) & 0xFF]))
        return None

    def writeUTF(self, value):
        data = str(value or "").encode("utf-8")
        self._write(len(data).to_bytes(2, "big") + data)
        return None

    def flush(self):
        try:
            self._target.flush()
        except Exception:
            pass
        return None

    def close(self):
        return None


class SecureRandom:
    def __init__(self):
        self._algorithm = "SHA1PRNG"
        self._seed = None

    def nextBytes(self, values):
        import os

        size = len(values) if hasattr(values, "__len__") else int(values)
        data = os.urandom(size)
        if isinstance(values, list):
            for index, value in enumerate(data):
                if index < len(values):
                    values[index] = value
        return None

    def nextInt(self, bound=None):
        import secrets

        if bound is None:
            return secrets.randbits(31)
        return secrets.randbelow(int(bound))

    def nextLong(self):
        import secrets

        return secrets.randbits(63)

    def nextBoolean(self):
        import secrets

        return bool(secrets.randbits(1))

    def nextDouble(self):
        import secrets

        return secrets.randbits(53) / float(1 << 53)

    def nextFloat(self):
        import secrets

        return secrets.randbits(24) / float(1 << 24)

    def setSeed(self, seed):
        self._seed = seed
        return None

    def generateSeed(self, count):
        import os

        return list(os.urandom(int(count)))

    def getAlgorithm(self):
        return self._algorithm


class JavaMac:
    def __init__(self, algorithm="HmacSHA256"):
        self._algorithm = str(algorithm or "HmacSHA256")
        self._key = b""
        self._data = bytearray()

    @staticmethod
    def getInstance(algorithm):
        return JavaMac(algorithm)

    def init(self, key, params=None):
        if hasattr(key, "getEncoded"):
            key = key.getEncoded()
        if isinstance(key, str):
            key = key.encode("utf-8")
        self._key = bytes(key or b"")
        return None

    def update(self, data):
        if isinstance(data, int):
            self._data.append(data & 0xFF)
        else:
            self._data.extend(bytes(data))
        return None

    def doFinal(self, data=None):
        import hashlib
        import hmac

        name = self._algorithm.lower().replace("hmac", "").strip()
        digest = {
            "sha1": hashlib.sha1,
            "sha224": hashlib.sha224,
            "sha256": hashlib.sha256,
            "sha384": hashlib.sha384,
            "sha512": hashlib.sha512,
            "md5": hashlib.md5,
        }.get(name, hashlib.sha256)
        payload = bytes(self._data)
        if data is not None:
            payload += bytes(data) if not isinstance(data, int) else bytes([data & 0xFF])
        result = hmac.new(self._key, payload, digest).digest()
        self._data.clear()
        return list(result)

    def getMacLength(self):
        return 32

    def reset(self):
        self._data.clear()
        return None

    def getAlgorithm(self):
        return self._algorithm


class URL:
    def __init__(self, spec=""):
        self.spec = str(spec or "")

    def openConnection(self, *args, **kwargs):
        return HttpURLConnection(self.spec)

    def openStream(self):
        import urllib.request

        return urllib.request.urlopen(self.spec)

    def toString(self):
        return self.spec

    def __str__(self):
        return self.spec

    def getProtocol(self):
        return self.spec.split(":", 1)[0] if ":" in self.spec else ""

    def getHost(self):
        import urllib.parse

        return urllib.parse.urlparse(self.spec).hostname or ""

    def getPath(self):
        import urllib.parse

        return urllib.parse.urlparse(self.spec).path or ""

    def getQuery(self):
        import urllib.parse

        return urllib.parse.urlparse(self.spec).query or ""

    def getPort(self):
        import urllib.parse

        return urllib.parse.urlparse(self.spec).port or -1

    def getDefaultPort(self):
        protocol = self.getProtocol().lower()
        if protocol == "https":
            return 443
        if protocol == "http":
            return 80
        if protocol == "ftp":
            return 21
        return -1

    def getAuthority(self):
        import urllib.parse

        return urllib.parse.urlparse(self.spec).netloc or ""

    def getUserInfo(self):
        import urllib.parse

        parts = urllib.parse.urlparse(self.spec)
        if parts.username is None:
            return None
        if parts.password is None:
            return parts.username
        return "%s:%s" % (parts.username, parts.password)

    def getRef(self):
        import urllib.parse

        return urllib.parse.urlparse(self.spec).fragment or None

    def getFile(self):
        path = self.getPath()
        query = self.getQuery()
        return path + ("?" + query if query else "")

    def equals(self, other):
        return isinstance(other, URL) and other.spec == self.spec

    def sameFile(self, other):
        return self.equals(other)

    def hashCode(self):
        return hash(self.spec)


class Html:
    FROM_HTML_MODE_LEGACY = 0
    FROM_HTML_MODE_COMPACT = 63
    FROM_HTML_SEPARATOR_LINE_BREAK_PARAGRAPH = 1
    FROM_HTML_SEPARATOR_LINE_BREAK_HEADING = 2
    FROM_HTML_SEPARATOR_LINE_BREAK_LIST_ITEM = 4
    FROM_HTML_SEPARATOR_LINE_BREAK_LIST = 8
    FROM_HTML_SEPARATOR_LINE_BREAK_DIV = 16
    FROM_HTML_SEPARATOR_LINE_BREAK_BLOCKQUOTE = 32
    TO_HTML_PARAGRAPH_LINES_CONSECUTIVE = 0
    TO_HTML_PARAGRAPH_LINES_INDIVIDUAL = 1

    @staticmethod
    def fromHtml(source, *args, **kwargs):
        import html as _html
        import re

        text = re.sub(r"<br\s*/?>", "\n", str(source or ""), flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return _html.unescape(text)

    @staticmethod
    def toHtml(source):
        import html as _html

        return _html.escape(str(source or "")).replace("\n", "<br>")


class Base64:
    DEFAULT = 0
    NO_PADDING = 1
    NO_WRAP = 2
    CRLF = 4
    URL_SAFE = 8
    NO_CLOSE = 16

    @staticmethod
    def encodeToString(data, flags=0):
        import base64

        if isinstance(data, str):
            data = data.encode("utf-8")
        encoded = (
            base64.urlsafe_b64encode(data)
            if flags & Base64.URL_SAFE
            else base64.b64encode(data)
        )
        if flags & Base64.NO_PADDING:
            encoded = encoded.rstrip(b"=")
        if not flags & Base64.NO_WRAP:
            encoded += b"\n"
        return encoded.decode("ascii")

    @staticmethod
    def encode(data, flags=0):
        return Base64.encodeToString(data, flags).encode("ascii")

    @staticmethod
    def decode(value, flags=0):
        import base64

        data = value.encode("ascii") if isinstance(value, str) else value
        data = data.strip()
        data += b"=" * (-len(data) % 4)
        try:
            if flags & Base64.URL_SAFE:
                return base64.urlsafe_b64decode(data)
            return base64.b64decode(data)
        except Exception:
            return b""


class Integer:
    MAX_VALUE = 2147483647
    MIN_VALUE = -2147483648
    TYPE = _java_class_ref("int")

    def __new__(cls, value=0):
        return int(value)

    @staticmethod
    def parseInt(value, default=0, radix=10):
        try:
            return int(str(value), int(radix))
        except Exception:
            return default

    @staticmethod
    def valueOf(value):
        return int(value)

    @staticmethod
    def toString(value):
        return str(int(value))

    @staticmethod
    def toHexString(value):
        return format(int(value) & 0xFFFFFFFF, "x")

    @staticmethod
    def compare(first, second):
        return (int(first) > int(second)) - (int(first) < int(second))


class Long:
    MAX_VALUE = 9223372036854775807
    MIN_VALUE = -9223372036854775808
    TYPE = _java_class_ref("long")

    def __new__(cls, value=0):
        return int(value)

    @staticmethod
    def parseLong(value, default=0):
        try:
            return int(str(value))
        except Exception:
            return default

    @staticmethod
    def valueOf(value):
        return int(value)

    @staticmethod
    def toString(value):
        return str(int(value))


class Short:
    MAX_VALUE = 32767
    MIN_VALUE = -32768
    TYPE = _java_class_ref("short")

    def __new__(cls, value=0):
        return int(value)

    @staticmethod
    def parseShort(value, default=0, radix=10):
        try:
            return int(str(value), int(radix))
        except Exception:
            return default

    @staticmethod
    def valueOf(value):
        return int(value)

    @staticmethod
    def toString(value):
        return str(int(value))


class Byte:
    MAX_VALUE = 127
    MIN_VALUE = -128
    TYPE = _java_class_ref("byte")

    def __new__(cls, value=0):
        return int(value)

    @staticmethod
    def parseByte(value, default=0, radix=10):
        try:
            return int(str(value), int(radix))
        except Exception:
            return default

    @staticmethod
    def valueOf(value):
        return int(value)

    @staticmethod
    def toString(value):
        return str(int(value))


class Void:
    TYPE = _java_class_ref("void")


class Modifier:
    PUBLIC = 0x0001
    PRIVATE = 0x0002
    PROTECTED = 0x0004
    STATIC = 0x0008
    FINAL = 0x0010
    SYNCHRONIZED = 0x0020
    VOLATILE = 0x0040
    TRANSIENT = 0x0080
    NATIVE = 0x0100
    INTERFACE = 0x0200
    ABSTRACT = 0x0400
    STRICT = 0x0800
    SYNTHETIC = 0x1000

    @staticmethod
    def isPublic(value):
        return bool(int(value) & Modifier.PUBLIC)

    @staticmethod
    def isPrivate(value):
        return bool(int(value) & Modifier.PRIVATE)

    @staticmethod
    def isProtected(value):
        return bool(int(value) & Modifier.PROTECTED)

    @staticmethod
    def isStatic(value):
        return bool(int(value) & Modifier.STATIC)

    @staticmethod
    def isFinal(value):
        return bool(int(value) & Modifier.FINAL)

    @staticmethod
    def isAbstract(value):
        return bool(int(value) & Modifier.ABSTRACT)

    @staticmethod
    def isInterface(value):
        return bool(int(value) & Modifier.INTERFACE)

    @staticmethod
    def isNative(value):
        return bool(int(value) & Modifier.NATIVE)

    @staticmethod
    def isSynchronized(value):
        return bool(int(value) & Modifier.SYNCHRONIZED)


class Double:
    MAX_VALUE = 1.7976931348623157e308
    MIN_VALUE = 4.9e-324
    NaN = float("nan")
    POSITIVE_INFINITY = float("inf")
    NEGATIVE_INFINITY = float("-inf")
    TYPE = _java_class_ref("double")

    def __new__(cls, value=0.0):
        return float(value)

    @staticmethod
    def parseDouble(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def valueOf(value):
        return float(value)

    @staticmethod
    def toString(value):
        return str(float(value))

    @staticmethod
    def isNaN(value):
        try:
            return float(value) != float(value)
        except Exception:
            return False


class Float(Double):
    TYPE = _java_class_ref("float")


class Boolean:
    TRUE = True
    FALSE = False
    TYPE = _java_class_ref("boolean")

    def __new__(cls, value=False):
        return bool(value)

    @staticmethod
    def parseBoolean(value):
        return str(value).strip().lower() == "true"

    @staticmethod
    def valueOf(value):
        return bool(value)

    @staticmethod
    def toString(value):
        return "true" if value else "false"


class String:
    def __new__(cls, value=""):
        return str(value)

    @staticmethod
    def valueOf(value):
        return "null" if value is None else str(value)

    @staticmethod
    def format(template, *args):
        try:
            return str(template) % args
        except Exception:
            return str(template)

    @staticmethod
    def join(delimiter, values):
        return str(delimiter).join(str(value) for value in (values or []))

    @staticmethod
    def isEmpty(value):
        return not value


class Random:
    def __init__(self, seed=None):
        import random as _r

        self._random = _r.Random(seed)

    def nextInt(self, bound=None):
        if bound is None:
            return self._random.randint(-2147483648, 2147483647)
        return self._random.randrange(max(1, int(bound)))

    def nextLong(self):
        return self._random.randint(-9223372036854775808, 9223372036854775807)

    def nextFloat(self):
        return self._random.random()

    def nextDouble(self):
        return self._random.random()

    def nextBoolean(self):
        return bool(self._random.getrandbits(1))

    def setSeed(self, seed):
        self._random.seed(seed)


class UUID:
    def __init__(self, value):
        self.value = str(value)

    @classmethod
    def randomUUID(cls):
        import uuid

        return cls(str(uuid.uuid4()))

    def toString(self):
        return self.value

    def __str__(self):
        return self.value


class Math:
    PI = math.pi
    E = math.e

    @staticmethod
    def max(first, second):
        return max(first, second)

    @staticmethod
    def min(first, second):
        return min(first, second)

    @staticmethod
    def abs(value):
        return abs(value)

    @staticmethod
    def round(value):
        return int(math.floor(float(value) + 0.5))

    @staticmethod
    def floor(value):
        return math.floor(value)

    @staticmethod
    def ceil(value):
        return math.ceil(value)

    @staticmethod
    def sqrt(value):
        return math.sqrt(value)

    @staticmethod
    def pow(base, exponent):
        return math.pow(base, exponent)

    @staticmethod
    def random():
        return _random.random()

    @staticmethod
    def toRadians(value):
        return math.radians(value)

    @staticmethod
    def toDegrees(value):
        return math.degrees(value)


class System:
    @staticmethod
    def currentTimeMillis():
        return int(time.time() * 1000)

    @staticmethod
    def nanoTime():
        return time.perf_counter_ns()

    @staticmethod
    def getProperty(name, default=None):
        values = {
            "java.version": "11.0",
            "os.name": "iOS",
            "line.separator": "\n",
            "file.separator": "/",
        }
        return values.get(str(name), default)

    @staticmethod
    def lineSeparator():
        return "\n"

    @staticmethod
    def arraycopy(source, source_index, destination, destination_index, length):
        values = list(source[int(source_index): int(source_index) + int(length)])
        for offset, value in enumerate(values):
            destination[int(destination_index) + offset] = value


class Locale:
    @classmethod
    def getDefault(cls):
        try:
            import extera_ios

            return cls((extera_ios.host("device.info") or {}).get("locale", "en_US"))
        except Exception:
            return cls("en_US")

    @classmethod
    def forLanguageTag(cls, tag):
        return cls(tag)

    def __init__(self, language="en", country=None):
        value = str(language or "en")
        if "_" in value and country is None:
            value, country = value.split("_", 1)
        elif "-" in value and country is None:
            value, country = value.split("-", 1)
        self.language = value
        self.country = country

    def getLanguage(self):
        return self.language

    def getCountry(self):
        return self.country or ""

    def getISO3Language(self):
        return self.language

    def toString(self):
        return self.language + ("_" + self.country if self.country else "")

    def getDisplayName(self):
        return self.toString()

    def getDisplayLanguage(self):
        return self.language


Locale.US = Locale("en", "US")
Locale.UK = Locale("en", "GB")
Locale.ENGLISH = Locale("en")
Locale.GERMAN = Locale("de")
Locale.FRENCH = Locale("fr")
Locale.RUSSIAN = Locale("ru")
Locale.CHINESE = Locale("zh")
Locale.JAPANESE = Locale("ja")


class Character:
    TYPE = _java_class_ref("char")

    @staticmethod
    def isDigit(value):
        return len(str(value)) == 1 and str(value).isdigit()

    @staticmethod
    def isLetter(value):
        return len(str(value)) == 1 and str(value).isalpha()

    @staticmethod
    def isLetterOrDigit(value):
        return len(str(value)) == 1 and str(value).isalnum()

    @staticmethod
    def isWhitespace(value):
        return str(value).isspace()

    @staticmethod
    def toLowerCase(value):
        return str(value).lower()

    @staticmethod
    def toUpperCase(value):
        return str(value).upper()

    @staticmethod
    def toString(value):
        return str(value)

    @staticmethod
    def getNumericValue(value):
        try:
            return int(str(value))
        except Exception:
            return -1

    @staticmethod
    def digit(value, radix=10):
        try:
            return int(str(value), int(radix))
        except Exception:
            return -1


class DateFormat:
    @staticmethod
    def format(pattern, date):
        return SimpleDateFormat(pattern).format(date)

    @staticmethod
    def getDateFormat(context=None):
        return SimpleDateFormat("MMM d, yyyy")

    @staticmethod
    def getTimeFormat(context=None):
        return SimpleDateFormat("HH:mm")


class JavaDateFormat:
    @staticmethod
    def getDateInstance(*args, **kwargs):
        return SimpleDateFormat("MMM d, yyyy")

    @staticmethod
    def getTimeInstance(*args, **kwargs):
        return SimpleDateFormat("HH:mm")

    @staticmethod
    def getDateTimeInstance(*args, **kwargs):
        return SimpleDateFormat("MMM d, yyyy HH:mm")


class TimeZone:
    @staticmethod
    def getDefault():
        return TimeZone()

    @staticmethod
    def getTimeZone(name):
        return TimeZone()

    def getID(self):
        return "UTC"

    def getDisplayName(self):
        return "UTC"

    def getRawOffset(self):
        return 0

    def getOffset(self, millis):
        return 0


class Calendar:
    YEAR = 1
    MONTH = 2
    WEEK_OF_YEAR = 3
    WEEK_OF_MONTH = 4
    DATE = 5
    DAY_OF_MONTH = 5
    DAY_OF_YEAR = 6
    DAY_OF_WEEK = 7
    HOUR = 10
    HOUR_OF_DAY = 11
    MINUTE = 12
    SECOND = 13
    MILLISECOND = 14
    JANUARY = 0
    FEBRUARY = 1
    MARCH = 2
    APRIL = 3
    MAY = 4
    JUNE = 5
    JULY = 6
    AUGUST = 7
    SEPTEMBER = 8
    OCTOBER = 9
    NOVEMBER = 10
    DECEMBER = 11
    SUNDAY = 1
    MONDAY = 2
    TUESDAY = 3
    WEDNESDAY = 4
    THURSDAY = 5
    FRIDAY = 6
    SATURDAY = 7

    @classmethod
    def getInstance(cls):
        return cls()

    def __init__(self):
        import datetime

        self._value = datetime.datetime.now()

    def getTimeInMillis(self):
        return int(self._value.timestamp() * 1000)

    def setTimeInMillis(self, millis):
        import datetime

        self._value = datetime.datetime.fromtimestamp(int(millis) / 1000.0)

    def getTime(self):
        return Date(self.getTimeInMillis())

    def setTime(self, date):
        self.setTimeInMillis(date.getTime() if hasattr(date, "getTime") else date)

    def get(self, field):
        field = int(field)
        if field == Calendar.YEAR:
            return self._value.year
        if field == Calendar.MONTH:
            return self._value.month - 1
        if field in (Calendar.DATE, Calendar.DAY_OF_MONTH):
            return self._value.day
        if field == Calendar.DAY_OF_WEEK:
            return (self._value.weekday() + 1) % 7 + 1
        if field in (Calendar.HOUR, Calendar.HOUR_OF_DAY):
            return self._value.hour
        if field == Calendar.MINUTE:
            return self._value.minute
        if field == Calendar.SECOND:
            return self._value.second
        if field == Calendar.MILLISECOND:
            return self._value.microsecond // 1000
        return 0

    def set(self, *args):
        if len(args) >= 3:
            self._value = self._value.replace(
                year=int(args[0]), month=int(args[1]) + 1, day=int(args[2])
            )
            return
        if len(args) == 2:
            field, value = int(args[0]), int(args[1])
            if field == Calendar.YEAR:
                self._value = self._value.replace(year=value)
            elif field == Calendar.MONTH:
                self._value = self._value.replace(month=value + 1)
            elif field in (Calendar.DATE, Calendar.DAY_OF_MONTH):
                self._value = self._value.replace(day=value)
            elif field in (Calendar.HOUR, Calendar.HOUR_OF_DAY):
                self._value = self._value.replace(hour=value)
            elif field == Calendar.MINUTE:
                self._value = self._value.replace(minute=value)
            elif field == Calendar.SECOND:
                self._value = self._value.replace(second=value)
            elif field == Calendar.MILLISECOND:
                self._value = self._value.replace(microsecond=value * 1000)

    def add(self, field, amount):
        import datetime

        amount = int(amount)
        if field == Calendar.YEAR:
            self._value = self._value.replace(year=self._value.year + amount)
        elif field == Calendar.MONTH:
            month = self._value.month - 1 + amount
            year = self._value.year + month // 12
            self._value = self._value.replace(year=year, month=month % 12 + 1)
        elif field in (Calendar.DATE, Calendar.DAY_OF_MONTH):
            self._value += datetime.timedelta(days=amount)
        elif field in (Calendar.HOUR, Calendar.HOUR_OF_DAY):
            self._value += datetime.timedelta(hours=amount)
        elif field == Calendar.MINUTE:
            self._value += datetime.timedelta(minutes=amount)
        elif field == Calendar.SECOND:
            self._value += datetime.timedelta(seconds=amount)
        elif field == Calendar.MILLISECOND:
            self._value += datetime.timedelta(milliseconds=amount)


class _JavaBase64Encoder:
    def encodeToString(self, data):
        return Base64.encodeToString(data, Base64.NO_WRAP)

    def encode(self, data):
        return Base64.encode(data, Base64.NO_WRAP)


class _JavaBase64Decoder:
    def decode(self, value):
        return Base64.decode(value, Base64.NO_WRAP)


class JavaBase64:
    @staticmethod
    def getEncoder():
        return _JavaBase64Encoder()

    @staticmethod
    def getDecoder():
        return _JavaBase64Decoder()


class StandardCharsets:
    UTF_8 = "utf-8"
    US_ASCII = "ascii"
    UTF_16 = "utf-16"
    UTF_16BE = "utf-16-be"
    UTF_16LE = "utf-16-le"
    ISO_8859_1 = "iso-8859-1"


class Charset:
    @staticmethod
    def forName(name):
        return str(name or "utf-8")

    @staticmethod
    def defaultCharset():
        return "utf-8"


class ByteBuffer:
    """`java.nio.ByteBuffer` backed by a bytearray."""

    def __init__(self, data=b"", capacity=None):
        self._data = bytearray(data or b"")
        if capacity is not None and int(capacity) > len(self._data):
            self._data.extend(b"\x00" * (int(capacity) - len(self._data)))
        self._position = 0
        self._limit = len(self._data)
        self._mark = -1
        self._order = "big"

    @staticmethod
    def allocate(size):
        return ByteBuffer(bytes(int(size or 0)))

    @staticmethod
    def allocateDirect(size):
        return ByteBuffer(bytes(int(size or 0)))

    @staticmethod
    def wrap(data, offset=0, length=None):
        raw = bytes(data or b"")
        offset = int(offset or 0)
        if length is None:
            return ByteBuffer(raw[offset:])
        return ByteBuffer(raw[offset:offset + int(length)])

    def _read(self, size):
        end = min(self._limit, self._position + int(size))
        chunk = bytes(self._data[self._position:end])
        self._position = end
        return chunk

    def _write(self, chunk):
        chunk = bytes(chunk)
        end = self._position + len(chunk)
        if end > len(self._data):
            self._data.extend(b"\x00" * (end - len(self._data)))
        self._data[self._position:end] = chunk
        self._position = end
        if self._position > self._limit:
            self._limit = self._position
        return self

    def put(self, value):
        if isinstance(value, int):
            return self._write(bytes([value & 0xFF]))
        if isinstance(value, (bytes, bytearray, memoryview)):
            return self._write(value)
        if isinstance(value, ByteBuffer):
            return self._write(value.array())
        return self._write(bytes(value or b""))

    def putInt(self, value):
        return self._write(int(value).to_bytes(4, self._order, signed=True))

    def putLong(self, value):
        return self._write(int(value).to_bytes(8, self._order, signed=True))

    def putShort(self, value):
        return self._write(int(value).to_bytes(2, self._order, signed=True))

    def putFloat(self, value):
        import struct

        return self._write(struct.pack((">" if self._order == "big" else "<") + "f", float(value)))

    def putDouble(self, value):
        import struct

        return self._write(struct.pack((">" if self._order == "big" else "<") + "d", float(value)))

    def putChar(self, value):
        return self._write(str(value)[:1].encode("utf-8"))

    def putBytes(self, value):
        return self._write(value)

    def get(self, length=None):
        if length is None:
            if self._position >= self._limit:
                raise IndexError("buffer underflow")
            value = self._data[self._position]
            self._position += 1
            return value
        return int.from_bytes(self._read(length), self._order, signed=True)

    def getInt(self):
        return int.from_bytes(self._read(4), self._order, signed=True)

    def getLong(self):
        return int.from_bytes(self._read(8), self._order, signed=True)

    def getShort(self):
        return int.from_bytes(self._read(2), self._order, signed=True)

    def getFloat(self):
        import struct

        return struct.unpack((">" if self._order == "big" else "<") + "f", self._read(4))[0]

    def getDouble(self):
        import struct

        return struct.unpack((">" if self._order == "big" else "<") + "d", self._read(8))[0]

    def getChar(self):
        chunk = self._read(1)
        return chunk.decode("utf-8", "replace") if chunk else "\x00"

    def array(self):
        return bytes(self._data[:self._limit])

    def arrayOffset(self):
        return 0

    def capacity(self):
        return len(self._data)

    def position(self, value=None):
        if value is None:
            return self._position
        self._position = max(0, min(int(value), len(self._data)))
        if self._position > self._limit:
            self._limit = self._position
        return self

    def limit(self, value=None):
        if value is None:
            return self._limit
        self._limit = max(0, min(int(value), len(self._data)))
        if self._position > self._limit:
            self._position = self._limit
        return self

    def remaining(self):
        return max(0, self._limit - self._position)

    def hasRemaining(self):
        return self.remaining() > 0

    def flip(self):
        self._limit = self._position
        self._position = 0
        self._mark = -1
        return self

    def clear(self):
        self._position = 0
        self._limit = len(self._data)
        self._mark = -1
        return self

    def rewind(self):
        self._position = 0
        self._mark = -1
        return self

    def mark(self):
        self._mark = self._position
        return self

    def reset(self):
        if self._mark >= 0:
            self._position = self._mark
        return self

    def duplicate(self):
        result = ByteBuffer(self._data)
        result._position = self._position
        result._limit = self._limit
        result._order = self._order
        return result

    def asReadOnlyBuffer(self):
        return self.duplicate()

    def slice(self):
        return ByteBuffer(self._data[self._position:self._limit])

    def compact(self):
        remaining = self._data[self._position:self._limit]
        self._data[:len(remaining)] = remaining
        self._position = len(remaining)
        self._limit = len(self._data)
        return self

    def order(self, value=None):
        if value is None:
            return self._order
        self._order = str(value).lower()
        return self

    def isDirect(self):
        return False

    def isReadOnly(self):
        return False

    def __len__(self):
        return self.remaining()

    def __bytes__(self):
        return self.array()

    def __repr__(self):
        return "<ByteBuffer pos=%d lim=%d cap=%d>" % (
            self._position,
            self._limit,
            len(self._data),
        )


class Bundle(dict):
    """`android.os.Bundle`, a string-keyed dictionary with the Android getters."""

    def putString(self, key, value):
        self[key] = value
        return self

    def putInt(self, key, value):
        self[key] = int(value)
        return self

    def putLong(self, key, value):
        self[key] = int(value)
        return self

    def putBoolean(self, key, value):
        self[key] = bool(value)
        return self

    def putStringArrayList(self, key, value):
        self[key] = list(value or [])
        return self

    def putParcelableArrayList(self, key, value):
        self[key] = list(value or [])
        return self

    def getString(self, key, default=None):
        value = dict.get(self, key, default)
        return value if isinstance(value, str) else default

    def getInt(self, key, default=0):
        try:
            return int(dict.get(self, key, default))
        except (TypeError, ValueError):
            return default

    def getLong(self, key, default=0):
        return self.getInt(key, default)

    def getBoolean(self, key, default=False):
        return bool(dict.get(self, key, default))

    def getStringArrayList(self, key):
        value = dict.get(self, key)
        return list(value) if isinstance(value, (list, tuple)) else None

    def getParcelableArrayList(self, key):
        return self.getStringArrayList(key)

    def containsKey(self, key):
        return key in self

    def keySet(self):
        return set(self.keys())

    def get(self, key, default=None):
        return dict.get(self, key, default)


class Uri:
    def __init__(self, value):
        self.value = str(value)

    @classmethod
    def getClass(cls):
        return _java_class_ref("android.net.Uri")

    @classmethod
    def parse(cls, value):
        return cls(value)

    @classmethod
    def fromFile(cls, file):
        path = file.getPath() if hasattr(file, "getPath") else str(file)
        return cls("file://" + path)

    def toString(self):
        return self.value

    def getScheme(self):
        return self.value.split(":", 1)[0] if ":" in self.value else ""

    def getHost(self):
        import urllib.parse

        return urllib.parse.urlparse(self.value).hostname or ""

    def getAuthority(self):
        import urllib.parse

        return urllib.parse.urlparse(self.value).netloc or ""

    def getPath(self):
        value = self.value
        if value.startswith("file://"):
            return value[7:]
        return value

    def getLastPathSegment(self):
        return os.path.basename(self.getPath())

    def getQuery(self):
        import urllib.parse

        return urllib.parse.urlparse(self.value).query or ""

    def getQueryParameter(self, key):
        import urllib.parse

        values = urllib.parse.parse_qs(urllib.parse.urlparse(self.value).query)
        items = values.get(str(key))
        return items[0] if items else None

    def getQueryParameterNames(self):
        import urllib.parse

        return set(urllib.parse.parse_qs(urllib.parse.urlparse(self.value).query).keys())

    def getFragment(self):
        import urllib.parse

        return urllib.parse.urlparse(self.value).fragment or ""

    def buildUpon(self):
        return UriBuilder(self.value)

    def __str__(self):
        return self.value


class Location:
    FORMAT_DEGREES = 0
    FORMAT_MINUTES = 1
    FORMAT_SECONDS = 2

    def __init__(self, provider=""):
        self._provider = str(provider or "")
        self._latitude = 0.0
        self._longitude = 0.0
        self._altitude = 0.0
        self._accuracy = 0.0
        self._speed = 0.0
        self._bearing = 0.0
        self._time = 0
        self._elapsed_realtime_nanos = 0
        self._extras = {}

    @staticmethod
    def convert(value, output_type):
        return str(value)

    @staticmethod
    def distanceBetween(lat1, lon1, lat2, lon2, results=None):
        import math

        radius = 6371000.0
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        delta_phi = math.radians(float(lat2) - float(lat1))
        delta_lambda = math.radians(float(lon2) - float(lon1))
        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        distance = 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        if results is not None:
            try:
                results[0] = distance
            except Exception:
                pass
        return distance

    def getProvider(self):
        return self._provider

    def setProvider(self, value):
        self._provider = str(value or "")
        return None

    def getLatitude(self):
        return self._latitude

    def setLatitude(self, value):
        self._latitude = float(value or 0)
        return None

    def getLongitude(self):
        return self._longitude

    def setLongitude(self, value):
        self._longitude = float(value or 0)
        return None

    def getAltitude(self):
        return self._altitude

    def setAltitude(self, value):
        self._altitude = float(value or 0)
        return None

    def getAccuracy(self):
        return self._accuracy

    def setAccuracy(self, value):
        self._accuracy = float(value or 0)
        return None

    def getSpeed(self):
        return self._speed

    def setSpeed(self, value):
        self._speed = float(value or 0)
        return None

    def getBearing(self):
        return self._bearing

    def setBearing(self, value):
        self._bearing = float(value or 0)
        return None

    def getTime(self):
        return self._time

    def setTime(self, value):
        self._time = int(value or 0)
        return None

    def getElapsedRealtimeNanos(self):
        return self._elapsed_realtime_nanos

    def setElapsedRealtimeNanos(self, value):
        self._elapsed_realtime_nanos = int(value or 0)
        return None

    def hasAccuracy(self):
        return self._accuracy > 0

    def hasAltitude(self):
        return self._altitude != 0

    def hasSpeed(self):
        return self._speed > 0

    def hasBearing(self):
        return self._bearing != 0

    def distanceTo(self, other):
        if other is None:
            return 0.0
        return Location.distanceBetween(
            self._latitude,
            self._longitude,
            other.getLatitude(),
            other.getLongitude(),
        )

    def bearingTo(self, other):
        if other is None:
            return 0.0
        import math

        lat1 = math.radians(self._latitude)
        lat2 = math.radians(other.getLatitude())
        delta_lon = math.radians(other.getLongitude() - self._longitude)
        y = math.sin(delta_lon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
            delta_lon
        )
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def getExtras(self):
        return Bundle()

    def setExtras(self, value):
        return None

    def isFromMockProvider(self):
        return False

    def isMock(self):
        return False

    def reset(self):
        self._latitude = 0.0
        self._longitude = 0.0
        self._altitude = 0.0
        self._accuracy = 0.0
        self._speed = 0.0
        self._bearing = 0.0
        self._time = 0
        return None

    def describeContents(self):
        return 0

    def writeToParcel(self, parcel, flags):
        return None


class LocationListener:
    def onLocationChanged(self, location):
        pass

    def onStatusChanged(self, provider, status, extras):
        pass

    def onProviderEnabled(self, provider):
        pass

    def onProviderDisabled(self, provider):
        pass


class LocationManager:
    GPS_PROVIDER = "gps"
    NETWORK_PROVIDER = "network"
    PASSIVE_PROVIDER = "passive"
    FUSED_PROVIDER = "fused"

    def __init__(self):
        self._last_known = None

    def isProviderEnabled(self, provider):
        return True

    def getProviders(self, enabled_only=True):
        return [self.GPS_PROVIDER, self.NETWORK_PROVIDER]

    def getAllProviders(self):
        return [self.GPS_PROVIDER, self.NETWORK_PROVIDER, self.PASSIVE_PROVIDER]

    def getBestProvider(self, criteria=None, enabled_only=True):
        return self.GPS_PROVIDER

    def getLastKnownLocation(self, provider):
        return self._last_known

    def requestLocationUpdates(self, *args):
        return None

    def requestSingleUpdate(self, *args):
        return None

    def removeUpdates(self, listener):
        return None

    def addGpsStatusListener(self, listener):
        return False

    def getGpsStatus(self, status=None):
        return None

    def sendExtraCommand(self, *args):
        return False

    def isLocationEnabled(self):
        return True

    def hasProvider(self, provider):
        return self.isProviderEnabled(provider)


class Criteria:
    ACCURACY_FINE = 1
    ACCURACY_COARSE = 2
    POWER_LOW = 1
    POWER_MEDIUM = 2
    POWER_HIGH = 3
    NO_REQUIREMENT = 0

    def __init__(self):
        self.accuracy = self.ACCURACY_COARSE
        self.power_requirement = self.POWER_MEDIUM

    def setAccuracy(self, value):
        self.accuracy = int(value or 0)
        return None

    def getAccuracy(self):
        return self.accuracy

    def setPowerRequirement(self, value):
        self.power_requirement = int(value or 0)
        return None

    def getPowerRequirement(self):
        return self.power_requirement

    def setAltitudeRequired(self, value):
        return None

    def setBearingRequired(self, value):
        return None

    def setSpeedRequired(self, value):
        return None

    def setCostAllowed(self, value):
        return None


class Geocoder:
    def __init__(self, context=None):
        self.context = context

    def getFromLocation(self, latitude, longitude, max_results=1):
        return []

    def getFromLocationName(self, location_name, max_results=1, *args):
        return []

    def isPresent(self):
        return False


class Sensor:
    TYPE_ACCELEROMETER = 1
    TYPE_MAGNETIC_FIELD = 2
    TYPE_ORIENTATION = 3
    TYPE_GYROSCOPE = 4
    TYPE_LIGHT = 5
    TYPE_PRESSURE = 6
    TYPE_TEMPERATURE = 7
    TYPE_PROXIMITY = 8
    TYPE_GRAVITY = 9
    TYPE_LINEAR_ACCELERATION = 10
    TYPE_ROTATION_VECTOR = 11
    TYPE_RELATIVE_HUMIDITY = 12
    TYPE_AMBIENT_TEMPERATURE = 13
    TYPE_STEP_COUNTER = 19
    TYPE_STEP_DETECTOR = 18
    TYPE_HEART_RATE = 21

    def __init__(self, name="", type_=0):
        self._name = str(name or "")
        self._type = int(type_ or 0)
        self._vendor = "Extera"
        self._version = 1
        self._resolution = 0.0
        self._max_range = 0.0
        self._power = 0.0

    def getName(self):
        return self._name

    def getType(self):
        return self._type

    def getVendor(self):
        return self._vendor

    def getVersion(self):
        return self._version

    def getResolution(self):
        return self._resolution

    def getMaximumRange(self):
        return self._max_range

    def getPower(self):
        return self._power

    def getMinDelay(self):
        return 0

    def isWakeUpSensor(self):
        return False

    def isDynamicSensor(self):
        return False

    def getReportingMode(self):
        return 0

    def getStringType(self):
        return self._name or "sensor"


class SensorEvent:
    def __init__(self, sensor=None, values=None, accuracy=0, timestamp=0):
        self.sensor = sensor
        self.values = list(values or [])
        self.accuracy = int(accuracy or 0)
        self.timestamp = int(timestamp or 0)


class SensorEventListener:
    def onSensorChanged(self, event):
        pass

    def onAccuracyChanged(self, sensor, accuracy):
        pass


class SensorManager:
    SENSOR_DELAY_FASTEST = 0
    SENSOR_DELAY_GAME = 1
    SENSOR_DELAY_UI = 2
    SENSOR_DELAY_NORMAL = 3

    def getSensorList(self, type_=0):
        return []

    def getDefaultSensor(self, type_):
        return Sensor("sensor", type_)

    def registerListener(self, *args):
        return False

    def unregisterListener(self, *args):
        return None

    def getRotationMatrix(self, *args):
        return []

    def getOrientation(self, *args):
        return []


class TelephonyManager:
    NETWORK_TYPE_UNKNOWN = 0
    NETWORK_TYPE_GPRS = 1
    NETWORK_TYPE_EDGE = 2
    NETWORK_TYPE_UMTS = 3
    NETWORK_TYPE_CDMA = 4
    NETWORK_TYPE_EVDO_0 = 5
    NETWORK_TYPE_EVDO_A = 6
    NETWORK_TYPE_1xRTT = 7
    NETWORK_TYPE_HSDPA = 8
    NETWORK_TYPE_HSUPA = 9
    NETWORK_TYPE_HSPA = 10
    NETWORK_TYPE_IDEN = 11
    NETWORK_TYPE_EVDO_B = 12
    NETWORK_TYPE_LTE = 13
    NETWORK_TYPE_EHRPD = 14
    NETWORK_TYPE_HSPAP = 15
    NETWORK_TYPE_GSM = 16
    NETWORK_TYPE_TD_SCDMA = 17
    NETWORK_TYPE_IWLAN = 18
    NETWORK_TYPE_NR = 20
    PHONE_TYPE_NONE = 0
    PHONE_TYPE_GSM = 1
    PHONE_TYPE_CDMA = 2
    PHONE_TYPE_SIP = 3
    SIM_STATE_UNKNOWN = 0
    SIM_STATE_ABSENT = 1
    SIM_STATE_PIN_REQUIRED = 2
    SIM_STATE_PUK_REQUIRED = 3
    SIM_STATE_NETWORK_LOCKED = 4
    SIM_STATE_READY = 5
    SIM_STATE_NOT_READY = 6
    SIM_STATE_PERM_DISABLED = 7
    SIM_STATE_CARD_IO_ERROR = 8
    SIM_STATE_CARD_RESTRICTED = 9

    def getNetworkCountryIso(self):
        return ""

    def getSimCountryIso(self):
        return ""

    def getNetworkOperator(self):
        return ""

    def getNetworkOperatorName(self):
        return ""

    def getSimOperator(self):
        return ""

    def getSimOperatorName(self):
        return ""

    def getPhoneType(self):
        return self.PHONE_TYPE_NONE

    def getNetworkType(self):
        return self.NETWORK_TYPE_UNKNOWN

    def getDataState(self):
        return 0

    def getSimState(self):
        return self.SIM_STATE_UNKNOWN

    def getDeviceId(self, slot=0):
        return ""

    def getImei(self, slot=0):
        return ""

    def getSubscriberId(self):
        return ""

    def getLine1Number(self):
        return ""

    def getSimSerialNumber(self):
        return ""

    def isNetworkRoaming(self):
        return False

    def isDataEnabled(self):
        return False

    def getCallState(self):
        return 0


class WifiInfo:
    """`android.net.wifi.WifiInfo` snapshot."""

    def __init__(self):
        self._ssid = ""
        self._bssid = "02:00:00:00:00:00"
        self._mac = "02:00:00:00:00:00"
        self._ip = 0
        self._link_speed = 0
        self._rssi = -55
        self._network_id = -1
        self._frequency = 0
        self._hidden = False

    def getSSID(self):
        return self._ssid

    def getBSSID(self):
        return self._bssid

    def getMacAddress(self):
        return self._mac

    def getIpAddress(self):
        return self._ip

    def getLinkSpeed(self):
        return self._link_speed

    def getRssi(self):
        return self._rssi

    def getNetworkId(self):
        return self._network_id

    def getFrequency(self):
        return self._frequency

    def isHiddenSSID(self):
        return self._hidden

    def getSupplicantState(self):
        return "COMPLETED"

    def toString(self):
        return "SSID: %s, BSSID: %s" % (self._ssid, self._bssid)

    def __repr__(self):
        return "<WifiInfo %s>" % self.toString()


class ScanResult:
    """One `android.net.wifi.ScanResult` entry."""

    def __init__(self, SSID="", BSSID="", capabilities="", level=-55, frequency=0):
        self.SSID = SSID
        self.BSSID = BSSID
        self.capabilities = capabilities
        self.level = int(level or 0)
        self.frequency = int(frequency or 0)
        self.timestamp = 0
        self.channelWidth = 0
        self.centerFreq0 = 0
        self.centerFreq1 = 0
        self.wifiStandard = 0

    def __repr__(self):
        return "<ScanResult %s %s>" % (self.SSID, self.BSSID)


class WifiConfiguration:
    def __init__(self):
        self.SSID = ""
        self.BSSID = ""
        self.networkId = -1
        self.status = 0
        self.priority = 0
        self.allowedKeyManagement = set()


class _WifiLock:
    def __init__(self, name, mode=0):
        self.name = name
        self.mode = mode
        self._held = False

    def acquire(self):
        self._held = True
        return None

    def release(self):
        self._held = False
        return None

    def setReferenceCounted(self, value):
        return None

    def isHeld(self):
        return self._held


class WifiManager:
    """`android.net.wifi.WifiManager` facade."""

    WIFI_STATE_DISABLED = 1
    WIFI_STATE_ENABLED = 3
    WIFI_STATE_ENABLING = 2
    WIFI_STATE_DISABLING = 0
    WIFI_STATE_UNKNOWN = 4
    ACTION_WIFI_STATE_CHANGED = "android.net.wifi.WIFI_STATE_CHANGED"
    ACTION_SCAN_RESULTS_AVAILABLE = "android.net.wifi.SCAN_RESULTS"
    WIFI_MODE_FULL = 1
    WIFI_MODE_FULL_HIGH_PERF = 3
    WIFI_MODE_SCAN_ONLY = 2

    def __init__(self):
        self._enabled = True
        self._info = WifiInfo()
        self._scan_results = []

    @staticmethod
    def calculateSignalLevel(rssi, num_levels=5):
        try:
            rssi = int(rssi)
            num_levels = max(1, int(num_levels))
        except (TypeError, ValueError):
            return 0
        if rssi <= -100:
            return 0
        if rssi >= -50:
            return num_levels - 1
        return int((rssi + 100) * (num_levels - 1) / 50)

    @staticmethod
    def compareSignalLevel(level_a, level_b):
        return int(level_a or 0) - int(level_b or 0)

    def isWifiEnabled(self):
        return self._enabled

    def setWifiEnabled(self, enabled):
        self._enabled = bool(enabled)
        return True

    def getWifiState(self):
        return self.WIFI_STATE_ENABLED if self._enabled else self.WIFI_STATE_DISABLED

    def getConnectionInfo(self):
        return self._info

    def getScanResults(self):
        return list(self._scan_results)

    def startScan(self):
        return True

    def disconnect(self):
        return True

    def reconnect(self):
        return True

    def addNetwork(self, configuration):
        return -1

    def removeNetwork(self, network_id):
        return True

    def saveConfiguration(self):
        return True

    def getConfiguredNetworks(self):
        return []

    def createWifiLock(self, mode, tag=None):
        return _WifiLock(tag or "wifi", mode)

    def createMulticastLock(self, tag=None):
        return _WifiLock(tag or "multicast", 0)


class NsdServiceInfo:
    """`android.net.nsd.NsdServiceInfo`: a service advertised over Bonjour."""

    def __init__(self, name=None, service_type=None, port=0):
        self.serviceName = name
        self.serviceType = service_type
        self.port = int(port or 0)
        self.host = None
        self.attributes = {}

    def setServiceName(self, value):
        self.serviceName = value
        return None

    def getServiceName(self):
        return self.serviceName or ""

    def setServiceType(self, value):
        self.serviceType = value
        return None

    def getServiceType(self):
        return self.serviceType or ""

    def setPort(self, value):
        self.port = int(value or 0)
        return None

    def getPort(self):
        return self.port

    def setHost(self, value):
        self.host = value
        return None

    def getHost(self):
        return self.host

    def setAttribute(self, key, value):
        self.attributes[str(key)] = value
        return None

    def getAttributes(self):
        return dict(self.attributes)

    def removeAttribute(self, key):
        self.attributes.pop(str(key), None)
        return None

    def toString(self):
        return "%s (%s)" % (self.getServiceName(), self.getServiceType())

    def __repr__(self):
        return "<NsdServiceInfo %s>" % self.toString()


class NsdManager:
    """`android.net.nsd.NsdManager` facade over Bonjour/NSD."""

    PROTOCOL_DNS_SD = 1
    SERVICE_TYPE_HTTP = "_http._tcp."
    FAILURE_INTERNAL_ERROR = 0
    FAILURE_ALREADY_ACTIVE = 3
    FAILURE_MAX_LIMIT = 4

    class RegistrationListener:
        def onServiceRegistered(self, service_info):
            pass

        def onRegistrationFailed(self, service_info, error_code):
            pass

        def onServiceUnregistered(self, service_info):
            pass

        def onUnregistrationFailed(self, service_info, error_code):
            pass

    class DiscoveryListener:
        def onDiscoveryStarted(self, service_type):
            pass

        def onServiceFound(self, service_info):
            pass

        def onServiceLost(self, service_info):
            pass

        def onDiscoveryStopped(self, service_type):
            pass

        def onStartDiscoveryFailed(self, service_type, error_code):
            pass

        def onStopDiscoveryFailed(self, service_type, error_code):
            pass

    class ResolveListener:
        def onResolveFailed(self, service_info, error_code):
            pass

        def onServiceResolved(self, service_info):
            pass

    def __init__(self):
        self._registrations = {}
        self._discoveries = {}

    def registerService(self, service_info, protocol=PROTOCOL_DNS_SD, listener=None):
        if listener is not None:
            self._registrations[id(listener)] = service_info
            try:
                listener.onServiceRegistered(service_info)
            except Exception:
                pass
        return None

    def unregisterService(self, listener):
        service_info = self._registrations.pop(id(listener), None)
        if listener is not None:
            try:
                listener.onServiceUnregistered(service_info)
            except Exception:
                pass
        return None

    def discoverServices(self, service_type, protocol, listener=None):
        if listener is not None:
            self._discoveries[id(listener)] = service_type
            try:
                listener.onDiscoveryStarted(service_type)
            except Exception:
                pass
        return None

    def stopServiceDiscovery(self, listener):
        service_type = self._discoveries.pop(id(listener), None)
        if listener is not None:
            try:
                listener.onDiscoveryStopped(service_type)
            except Exception:
                pass
        return None

    def resolveService(self, service_info, listener=None):
        if listener is not None:
            try:
                listener.onServiceResolved(service_info)
            except Exception:
                pass
        return None


class UriBuilder:
    def __init__(self, value):
        self.value = str(value)

    def appendQueryParameter(self, key, value):
        import urllib.parse

        parts = urllib.parse.urlparse(self.value)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query.append((str(key), str(value)))
        self.value = urllib.parse.urlunparse(
            parts._replace(query=urllib.parse.urlencode(query))
        )
        return self

    def build(self):
        return Uri(self.value)


class Environment:
    MEDIA_UNKNOWN = "unknown"
    MEDIA_REMOVED = "removed"
    MEDIA_UNMOUNTED = "unmounted"
    MEDIA_CHECKING = "checking"
    MEDIA_NOFS = "nofs"
    MEDIA_MOUNTED = "mounted"
    MEDIA_MOUNTED_READ_ONLY = "mounted_ro"
    MEDIA_SHARED = "shared"
    MEDIA_BAD_REMOVAL = "bad_removal"
    MEDIA_UNMOUNTABLE = "unmountable"
    MEDIA_EJECTING = "ejecting"
    DIRECTORY_MUSIC = "Music"
    DIRECTORY_PODCASTS = "Podcasts"
    DIRECTORY_RINGTONES = "Ringtones"
    DIRECTORY_ALARMS = "Alarms"
    DIRECTORY_NOTIFICATIONS = "Notifications"
    DIRECTORY_PICTURES = "Pictures"
    DIRECTORY_MOVIES = "Movies"
    DIRECTORY_DOWNLOADS = "Download"
    DIRECTORY_DCIM = "DCIM"
    DIRECTORY_DOCUMENTS = "Documents"
    DIRECTORY_SCREENSHOTS = "Screenshots"
    DIRECTORY_AUDIOBOOKS = "Audiobooks"
    DIRECTORY_RECORDINGS = "Recordings"

    @staticmethod
    def getExternalStorageState():
        return Environment.MEDIA_MOUNTED

    @staticmethod
    def getExternalStorageDirectory():
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_FILES)

    @staticmethod
    def getExternalStoragePublicDirectory(kind=None):
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_FILES)

    @staticmethod
    def getDataDirectory():
        return FileLoader.getDirectory(FileLoader.MEDIA_DIR_FILES)


class _WakeLock:
    def __init__(self, tag):
        self.tag = tag
        self._held = False

    def acquire(self, *args, **kwargs):
        self._held = True
        return None

    def release(self, *args, **kwargs):
        self._held = False
        return None

    def setReferenceCounted(self, value):
        return None

    def isHeld(self):
        return self._held


class PowerManager:
    PARTIAL_WAKE_LOCK = 1
    SCREEN_DIM_WAKE_LOCK = 6
    SCREEN_BRIGHT_WAKE_LOCK = 10
    FULL_WAKE_LOCK = 26

    def newWakeLock(self, flags, tag):
        return _WakeLock(tag)


class Vibrator:
    def vibrate(self, *args, **kwargs):
        return None

    def cancel(self):
        return None


_ANDROID_ID = None


def _android_id():
    global _ANDROID_ID
    if _ANDROID_ID is None:
        import uuid

        _ANDROID_ID = uuid.uuid4().hex
    return _ANDROID_ID


class _SettingsSecure:
    @staticmethod
    def getString(resolver, name):
        if str(name) == "android_id":
            return _android_id()
        return None

    @staticmethod
    def getInt(resolver, name, default=0):
        return default


class Settings:
    Secure = _SettingsSecure()


class ContentResolver:
    def openInputStream(self, uri):
        path = uri.getPath() if isinstance(uri, Uri) else str(uri)
        return FileInputStream(path)

    def openOutputStream(self, uri):
        path = uri.getPath() if isinstance(uri, Uri) else str(uri)
        return FileOutputStream(path)

    def getType(self, uri):
        return None

    def delete(self, uri, *args, **kwargs):
        path = uri.getPath() if isinstance(uri, Uri) else str(uri)
        try:
            os.remove(path)
            return 1
        except OSError:
            return 0


class HandlerThread(_threading.Thread):
    def __init__(self, name=None):
        super().__init__(name=name, daemon=True)

    def getLooper(self):
        return Looper.getMainLooper()

    def quit(self):
        return None

    def quitSafely(self):
        return None


class BatteryManager:
    EXTRA_STATUS = "status"
    EXTRA_HEALTH = "health"
    EXTRA_PRESENT = "present"
    EXTRA_LEVEL = "level"
    EXTRA_SCALE = "scale"
    EXTRA_ICON_SMALL = "icon-small"
    EXTRA_PLUGGED = "plugged"
    EXTRA_VOLTAGE = "voltage"
    EXTRA_TEMPERATURE = "temperature"
    EXTRA_TECHNOLOGY = "technology"
    BATTERY_STATUS_UNKNOWN = 1
    BATTERY_STATUS_CHARGING = 2
    BATTERY_STATUS_DISCHARGING = 3
    BATTERY_STATUS_NOT_CHARGING = 4
    BATTERY_STATUS_FULL = 5
    BATTERY_HEALTH_UNKNOWN = 1
    BATTERY_HEALTH_GOOD = 2
    BATTERY_HEALTH_OVERHEAT = 3
    BATTERY_HEALTH_DEAD = 4
    BATTERY_HEALTH_OVER_VOLTAGE = 5
    BATTERY_HEALTH_UNSPECIFIED_FAILURE = 6
    BATTERY_HEALTH_COLD = 7
    BATTERY_PLUGGED_AC = 1
    BATTERY_PLUGGED_USB = 2
    BATTERY_PLUGGED_WIRELESS = 4
    BATTERY_PLUGGED_DOCK = 8
    ACTION_CHARGING = "android.os.action.CHARGING"
    ACTION_DISCHARGING = "android.os.action.DISCHARGING"

    def __init__(self):
        self._level = 100
        self._scale = 100
        self._status = self.BATTERY_STATUS_FULL
        self._plugged = self.BATTERY_PLUGGED_USB
        self._temperature = 300
        self._voltage = 4000
        self._health = self.BATTERY_HEALTH_GOOD
        self._technology = "Li-ion"

    def isCharging(self):
        return self._status in (
            self.BATTERY_STATUS_CHARGING,
            self.BATTERY_STATUS_FULL,
        )

    def getIntProperty(self, key):
        name = str(key)
        if name == self.EXTRA_LEVEL:
            return self._level
        if name == self.EXTRA_SCALE:
            return self._scale
        if name == self.EXTRA_STATUS:
            return self._status
        if name == self.EXTRA_PLUGGED:
            return self._plugged
        if name == self.EXTRA_TEMPERATURE:
            return self._temperature
        if name == self.EXTRA_VOLTAGE:
            return self._voltage
        if name == self.EXTRA_HEALTH:
            return self._health
        return 0

    def getLongProperty(self, key):
        return int(self.getIntProperty(key) or 0)

    def getStringProperty(self, key):
        if str(key) == self.EXTRA_TECHNOLOGY:
            return self._technology
        return None


class Process:
    @staticmethod
    def myPid():
        return os.getpid()

    @staticmethod
    def myTid():
        return _threading.get_ident()

    @staticmethod
    def myUid():
        getuid = getattr(os, "getuid", None)
        return getuid() if getuid is not None else 0

    @staticmethod
    def myUserHandle():
        return None

    @staticmethod
    def getElapsedCpuTime():
        try:
            import time

            return int(time.process_time() * 1000)
        except Exception:
            return 0

    @staticmethod
    def getStartUptimeMillis():
        try:
            import time

            return int(time.monotonic() * 1000)
        except Exception:
            return 0

    @staticmethod
    def setPriority(priority):
        return None


class FileProvider:
    @staticmethod
    def getUriForFile(context, authority, file):
        path = file.getPath() if hasattr(file, "getPath") else str(file)
        return Uri("file://" + path)


def _image_dimensions(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return (
            int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"),
        )
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return (
            int.from_bytes(data[6:8], "little"),
            int.from_bytes(data[8:10], "little"),
        )
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return (
                1 + int.from_bytes(data[24:27], "little"),
                1 + int.from_bytes(data[27:30], "little"),
            )
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 " and len(data) >= 30:
            return (
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0xD9):
                index += 2
                continue
            length = int.from_bytes(data[index + 2:index + 4], "big")
            if marker in (
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            ):
                return (
                    int.from_bytes(data[index + 7:index + 9], "big"),
                    int.from_bytes(data[index + 5:index + 7], "big"),
                )
            index += 2 + length
    return 0, 0


class Bitmap:
    class CompressFormat:
        PNG = 1
        JPEG = 2
        WEBP = 3

    class Config:
        ALPHA_8 = 1
        RGB_565 = 2
        ARGB_4444 = 3
        ARGB_8888 = 4
        RGBA_F16 = 5
        HARDWARE = 6

    @staticmethod
    def createBitmap(*args, **kwargs):
        config = kwargs.get("config")
        source = None
        numbers = []
        for value in args:
            if isinstance(value, Bitmap):
                source = value
            elif isinstance(value, int):
                numbers.append(value)
        if source is not None:
            if len(numbers) >= 4:
                width, height = numbers[2], numbers[3]
            else:
                width = source.getWidth()
                height = source.getHeight()
            bitmap = Bitmap(
                getattr(source, "_data", b""),
                width,
                height,
                getattr(source, "_path", None),
            )
            bitmap._config = config or getattr(source, "_config", None)
            return bitmap
        width = numbers[0] if numbers else 0
        height = numbers[1] if len(numbers) > 1 else 0
        bitmap = Bitmap(b"", width, height)
        bitmap._config = config
        return bitmap

    @staticmethod
    def createScaledBitmap(source, width, height, filter=True):
        bitmap = Bitmap(
            getattr(source, "_data", b"") if source is not None else b"",
            width,
            height,
            getattr(source, "_path", None) if source is not None else None,
        )
        return bitmap

    def __init__(self, data=b"", width=0, height=0, path=None):
        self._data = bytes(data or b"")
        self._width = int(width)
        self._height = int(height)
        self._path = path
        self._recycled = False

    def getWidth(self):
        return self._width

    def getHeight(self):
        return self._height

    def getByteCount(self):
        return len(self._data)

    def isRecycled(self):
        return self._recycled

    def recycle(self):
        self._recycled = True

    def compress(self, format, quality, stream):
        if self._recycled:
            return False
        try:
            if hasattr(stream, "write"):
                stream.write(self._data)
                return True
        except Exception:
            pass
        return False

    def copy(self, config=None, is_mutable=False):
        bitmap = Bitmap(self._data, self._width, self._height, self._path)
        bitmap._config = config or getattr(self, "_config", None)
        return bitmap

    def getConfig(self):
        return getattr(self, "_config", None)

    def getRowBytes(self):
        return self._width * 4

    def getAllocationByteCount(self):
        return len(self._data) or self._width * self._height * 4

    def setPixel(self, x, y, color):
        return None

    def getPixel(self, x, y):
        return 0

    def getPixels(self, *args):
        return None

    def setPixels(self, *args):
        return None

    def eraseColor(self, color):
        return None

    def describeContents(self):
        return 0

    def writeToParcel(self, parcel, flags):
        return None

    def isMutable(self):
        return False

    def prepareToDraw(self):
        return None


class _BitmapFactoryOptions:
    def __init__(self):
        self.inJustDecodeBounds = False
        self.outWidth = -1
        self.outHeight = -1
        self.inSampleSize = 1
        self.inPreferredConfig = None


class BitmapFactory:
    Options = _BitmapFactoryOptions

    @staticmethod
    def decodeFile(path, options=None):
        try:
            with open(str(path), "rb") as handle:
                data = handle.read()
        except Exception:
            return None
        width, height = _image_dimensions(data)
        if options is not None:
            options.outWidth = width
            options.outHeight = height
            if getattr(options, "inJustDecodeBounds", False):
                return None
        return Bitmap(data, width, height, path=str(path))

    @staticmethod
    def decodeByteArray(data, offset=0, length=None):
        value = bytes(data or b"")
        offset = int(offset or 0)
        if length is None:
            value = value[offset:]
        else:
            value = value[offset: offset + int(length)]
        width, height = _image_dimensions(value)
        return Bitmap(value, width, height)

    @staticmethod
    def decodeStream(stream):
        try:
            if hasattr(stream, "_read_bytes"):
                data = stream._read_bytes(-1)
            else:
                data = stream.read()
        except Exception:
            return None
        if isinstance(data, str):
            data = data.encode("utf-8")
        value = bytes(data or b"")
        width, height = _image_dimensions(value)
        return Bitmap(value, width, height)


class ContentValues(dict):
    def put(self, key, value):
        self[key] = value

    def getAsString(self, key):
        value = dict.get(self, key)
        return None if value is None else str(value)

    def getAsInteger(self, key):
        try:
            return int(dict.get(self, key))
        except (TypeError, ValueError):
            return None

    def getAsLong(self, key):
        return self.getAsInteger(key)

    def getAsBoolean(self, key):
        return bool(dict.get(self, key))

    def containsKey(self, key):
        return key in self

    def size(self):
        return len(self)

    def clear(self):
        dict.clear(self)


def _run_runnable(value):
    if callable(value):
        return value()
    run = getattr(value, "run", None)
    if callable(run):
        return run()
    return None


class Looper:
    _main = None

    @classmethod
    def getMainLooper(cls):
        if cls._main is None:
            cls._main = cls()
        return cls._main

    @classmethod
    def myLooper(cls):
        return cls.getMainLooper()


class Choreographer:
    _instance = None

    class FrameCallback:
        def doFrame(self, frame_time_nanos):
            pass

    @classmethod
    def getInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def postFrameCallback(self, callback):
        import time

        frame_time = int(time.time() * 1_000_000_000)
        try:
            if hasattr(callback, "doFrame"):
                callback.doFrame(frame_time)
            elif callable(callback):
                callback(frame_time)
        except Exception:
            pass
        return None

    def postFrameCallbackDelayed(self, callback, delay=0):
        return self.postFrameCallback(callback)

    def removeFrameCallback(self, callback):
        return None


class Message:
    """`android.os.Message` delivered by `Handler`."""

    def __init__(self):
        self.what = 0
        self.arg1 = 0
        self.arg2 = 0
        self.obj = None
        self.target = None
        self.callback = None
        self.data = None
        self.when = 0
        self.sendingUptime = 0
        self.isAsynchronous = False

    @staticmethod
    def obtain(handler=None, what=0, arg1=None, arg2=None, obj=None):
        if isinstance(handler, Message):
            message = Message()
            message.copyFrom(handler)
            return message
        message = Message()
        if handler is not None:
            message.target = handler
        message.what = int(what or 0)
        if arg1 is not None:
            message.arg1 = int(arg1)
        if arg2 is not None:
            message.arg2 = int(arg2)
        if obj is not None:
            message.obj = obj
        return message

    def sendToTarget(self):
        if self.target is not None and hasattr(self.target, "sendMessage"):
            self.target.sendMessage(self)
        return None

    def copyFrom(self, other):
        for name in (
            "what", "arg1", "arg2", "obj", "target", "callback", "data",
            "when", "sendingUptime", "isAsynchronous",
        ):
            setattr(self, name, getattr(other, name, None))
        return None

    def recycle(self):
        return None

    def setTarget(self, target):
        self.target = target
        return None

    def getTarget(self):
        return self.target

    def getCallback(self):
        return self.callback

    def setData(self, data):
        self.data = data
        return None

    def getData(self):
        if self.data is None:
            self.data = Bundle()
        return self.data

    def peekData(self):
        return self.data

    def describeContents(self):
        return 0

    def writeToParcel(self, parcel, flags):
        return None


class Handler:
    """`android.os.Handler` posting onto the iOS main queue."""

    def __init__(self, looper=None):
        self.looper = looper or Looper.getMainLooper()
        self._handles = []

    def post(self, runnable):
        try:
            import extera_ios

            handle = extera_ios.run_on_ui_thread(lambda: _run_runnable(runnable))
            if handle:
                self._handles.append(handle)
            return True
        except Exception:
            return False

    def postDelayed(self, runnable, delay):
        try:
            import extera_ios

            milliseconds = int(delay or 0)
            handle = extera_ios.run_on_ui_thread(
                lambda: _run_runnable(runnable), milliseconds
            )
            if handle:
                self._handles.append(handle)
            return True
        except Exception:
            return False

    def removeCallbacks(self, runnable=None):
        try:
            import extera_ios
        except Exception:
            return
        for handle in self._handles:
            try:
                extera_ios.cancel_ui_task(handle)
            except Exception:
                pass
        self._handles.clear()

    def removeCallbacksAndMessages(self, token=None):
        return self.removeCallbacks()

    def hasMessages(self, what=None, object=None):
        return False

    def removeMessages(self, what, object=None):
        return None

    def sendEmptyMessage(self, what):
        return self.sendMessageAtTime(what, 0)

    def sendEmptyMessageDelayed(self, what, delay):
        return self.sendMessageAtTime(what, int(delay or 0))

    def sendEmptyMessageAtTime(self, what, uptimeMillis):
        return self.sendMessageAtTime(what, uptimeMillis)

    def sendMessage(self, message):
        return self.sendMessageAtTime(message, 0)

    def sendMessageDelayed(self, message, delay):
        return self.sendMessageAtTime(message, int(delay or 0))

    def sendMessageAtTime(self, message, uptimeMillis):
        function = None
        if hasattr(message, "callback") and callable(message.callback):
            function = message.callback
        elif hasattr(message, "run") and callable(message.run):
            function = message.run
        elif callable(message):
            function = message
        if function is None:
            return False
        try:
            import extera_ios

            handle = extera_ios.run_on_ui_thread(
                lambda: _run_runnable(function), int(uptimeMillis or 0)
            )
            if handle:
                self._handles.append(handle)
            return True
        except Exception:
            return False

    def postAtTime(self, runnable, uptimeMillis):
        return self.sendMessageAtTime(runnable, uptimeMillis)

    def postAtFrontOfQueue(self, runnable):
        return self.sendMessageAtTime(runnable, 0)

    def obtainMessage(self, what=0, obj=None):
        try:
            return Message.obtain(self, what, obj)
        except Exception:
            return None

    def getLooper(self):
        return self.looper

    def getMessageName(self, message):
        return None


class CountDownTimer:
    """`android.os.CountDownTimer` driven by a daemon timer and the UI queue."""

    def __init__(self, millis_in_future, count_down_interval):
        self._remaining = int(millis_in_future)
        self._interval = max(1, int(count_down_interval))
        self._cancelled = False
        self._timer = None

    def start(self):
        self._cancelled = False
        self._schedule()
        return self

    def _schedule(self):
        if self._cancelled:
            return
        if self._remaining <= 0:
            self._deliver_finish()
            return
        self._timer = _threading.Timer(self._interval / 1000.0, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        if self._cancelled:
            return
        self._remaining = max(0, self._remaining - self._interval)
        self._deliver_tick(self._remaining)
        if self._remaining <= 0:
            self._deliver_finish()
        else:
            self._schedule()

    def _deliver_tick(self, remaining):
        try:
            import extera_ios

            extera_ios.run_on_ui_thread(lambda: self.onTick(remaining))
        except Exception:
            pass

    def _deliver_finish(self):
        try:
            import extera_ios

            extera_ios.run_on_ui_thread(self.onFinish)
        except Exception:
            pass

    def cancel(self):
        self._cancelled = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def onTick(self, millis_until_finished):
        pass

    def onFinish(self):
        pass


class FileInputStream:
    def __init__(self, source):
        path = source.getPath() if hasattr(source, "getPath") else str(source)
        self._file = open(path, "rb")

    def _read_bytes(self, count=-1):
        return self._file.read(count)

    def read(self, buffer=None, offset=0, length=None):
        if buffer is None:
            data = self._file.read(1)
            return data[0] if data else -1
        count = length if length is not None else len(buffer) - offset
        data = self._file.read(max(0, int(count)))
        if not data:
            return -1
        for index, value in enumerate(data):
            buffer[offset + index] = value
        return len(data)

    def skip(self, count):
        return len(self._file.read(max(0, int(count))))

    def available(self):
        try:
            return os.fstat(self._file.fileno()).st_size - self._file.tell()
        except Exception:
            return 0

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FileOutputStream:
    def __init__(self, target, append=False):
        path = target.getPath() if hasattr(target, "getPath") else str(target)
        self._file = open(path, "ab" if append else "wb")

    def write(self, data, offset=0, length=None):
        if isinstance(data, int):
            data = bytes([data & 0xFF])
        elif isinstance(data, (bytes, bytearray, list, tuple)):
            data = bytes(data[offset: offset + length] if length is not None else data[offset:])
        elif isinstance(data, str):
            data = data.encode("utf-8")
        self._file.write(data)
        return len(data)

    def flush(self):
        self._file.flush()

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FileReader:
    def __init__(self, source):
        path = source.getPath() if hasattr(source, "getPath") else str(source)
        self._file = open(path, "r", encoding="utf-8", errors="replace")

    def read(self, *args):
        return self._file.read(*args)

    def readLine(self):
        line = self._file.readline()
        return line.rstrip("\n") if line else None

    def close(self):
        self._file.close()


class FileWriter:
    def __init__(self, target, append=False):
        path = target.getPath() if hasattr(target, "getPath") else str(target)
        self._file = open(path, "a" if append else "w", encoding="utf-8")

    def write(self, value):
        return self._file.write(str(value))

    def flush(self):
        self._file.flush()

    def close(self):
        self._file.close()


class InputStreamReader:
    def __init__(self, stream, charset=None):
        self._stream = stream

    def read(self, *args):
        if hasattr(self._stream, "_read_bytes"):
            data = self._stream._read_bytes(*args)
        elif hasattr(self._stream, "read"):
            data = self._stream.read(*args)
        else:
            return -1
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return data

    def close(self):
        close = getattr(self._stream, "close", None)
        if callable(close):
            close()


class BufferedReader:
    def __init__(self, reader):
        self._reader = reader

    def readLine(self):
        line = self._reader.readLine()
        return line

    def read(self, *args):
        return self._reader.read(*args)

    def close(self):
        self._reader.close()


class BufferedWriter:
    def __init__(self, writer):
        self._writer = writer

    def write(self, value):
        return self._writer.write(value)

    def newLine(self):
        self._writer.write("\n")

    def flush(self):
        flush = getattr(self._writer, "flush", None)
        if callable(flush):
            flush()

    def close(self):
        close = getattr(self._writer, "close", None)
        if callable(close):
            close()


class LruCache:
    def __init__(self, max_size):
        from collections import OrderedDict

        self._max_size = max(1, int(max_size))
        self._values = OrderedDict()

    def put(self, key, value):
        self._values[key] = value
        self._values.move_to_end(key)
        while len(self._values) > self._max_size:
            self._values.popitem(last=False)
        return value

    def get(self, key):
        value = self._values.get(key)
        if key in self._values:
            self._values.move_to_end(key)
        return value

    def remove(self, key):
        return self._values.pop(key, None)

    def evictAll(self):
        self._values.clear()

    def size(self):
        return len(self._values)

    def snapshot(self):
        return dict(self._values)


class AtomicInteger:
    def __init__(self, value=0):
        self._lock = _threading.Lock()
        self._value = int(value)

    def get(self):
        with self._lock:
            return self._value

    def set(self, value):
        with self._lock:
            self._value = int(value)

    def getAndSet(self, value):
        with self._lock:
            previous = self._value
            self._value = int(value)
            return previous

    def incrementAndGet(self):
        with self._lock:
            self._value += 1
            return self._value

    def getAndIncrement(self):
        with self._lock:
            previous = self._value
            self._value += 1
            return previous

    def decrementAndGet(self):
        with self._lock:
            self._value -= 1
            return self._value

    def addAndGet(self, delta):
        with self._lock:
            self._value += int(delta)
            return self._value

    def compareAndSet(self, expected, update):
        with self._lock:
            if self._value == expected:
                self._value = int(update)
                return True
            return False


class AtomicLong(AtomicInteger):
    pass


class AtomicBoolean:
    def __init__(self, value=False):
        self._lock = _threading.Lock()
        self._value = bool(value)

    def get(self):
        with self._lock:
            return self._value

    def set(self, value):
        with self._lock:
            self._value = bool(value)

    def getAndSet(self, value):
        with self._lock:
            previous = self._value
            self._value = bool(value)
            return previous

    def compareAndSet(self, expected, update):
        with self._lock:
            if self._value == bool(expected):
                self._value = bool(update)
                return True
            return False


class TimeUnit:
    _FACTORS = {
        "ns": 1e-9,
        "us": 1e-6,
        "ms": 1e-3,
        "s": 1.0,
        "min": 60.0,
        "h": 3600.0,
        "d": 86400.0,
    }

    def __init__(self, name):
        self.name = name

    def _seconds(self, value):
        return float(value) * self._FACTORS.get(self.name, 1.0)

    def toNanos(self, value):
        return int(self._seconds(value) * 1_000_000_000)

    def toMillis(self, value):
        return int(self._seconds(value) * 1000)

    def toSeconds(self, value):
        return int(self._seconds(value))

    def sleep(self, value):
        time.sleep(max(0.0, self._seconds(value)))

    @classmethod
    def _convert(cls, value, unit):
        if isinstance(unit, TimeUnit):
            return unit._seconds(value)
        return float(value) * cls._FACTORS.get(str(unit), 1.0)


TimeUnit.NANOSECONDS = TimeUnit("ns")
TimeUnit.MICROSECONDS = TimeUnit("us")
TimeUnit.MILLISECONDS = TimeUnit("ms")
TimeUnit.SECONDS = TimeUnit("s")
TimeUnit.MINUTES = TimeUnit("min")
TimeUnit.HOURS = TimeUnit("h")
TimeUnit.DAYS = TimeUnit("d")


class _Future:
    def __init__(self, future):
        self._future = future

    def get(self, timeout=None):
        if timeout is None:
            return self._future.result()
        return self._future.result(timeout=float(timeout))

    def cancel(self, may_interrupt=True):
        return self._future.cancel()

    def isDone(self):
        return self._future.done()

    def isCancelled(self):
        return self._future.cancelled()


class _ExecutorService:
    def __init__(self, workers=1):
        import concurrent.futures

        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(workers))
        )
        self._futures = []

    def submit(self, runnable, *args):
        callback = runnable.run if hasattr(runnable, "run") else runnable
        future = _Future(self._executor.submit(callback, *args))
        self._futures.append(future)
        return future

    def execute(self, runnable):
        self.submit(runnable)

    def shutdown(self):
        self._executor.shutdown(wait=False)

    def shutdownNow(self):
        self._executor.shutdown(wait=False)
        return []

    def awaitTermination(self, timeout, unit):
        seconds = TimeUnit._convert(timeout, unit)
        deadline = time.time() + seconds
        while time.time() < deadline:
            if all(future.isDone() for future in list(self._futures)):
                return True
            time.sleep(0.01)
        return all(future.isDone() for future in list(self._futures))


class Executors:
    @staticmethod
    def newSingleThreadExecutor():
        return _ExecutorService(1)

    @staticmethod
    def newFixedThreadPool(size):
        return _ExecutorService(max(1, int(size)))

    @staticmethod
    def newCachedThreadPool():
        return _ExecutorService(16)

    @staticmethod
    def newWorkStealingPool(*args):
        return _ExecutorService(4)


class AsyncTask:
    """`android.os.AsyncTask`, running `doInBackground` off the main queue."""

    def __init__(self):
        self._cancelled = False
        self._thread = None

    def execute(self, *args):
        self._cancelled = False

        def run():
            try:
                self.onPreExecute()
                result = self.doInBackground(*args)
                if not self._cancelled:
                    try:
                        import extera_ios

                        extera_ios.run_on_ui_thread(lambda: self.onPostExecute(result))
                    except Exception:
                        self.onPostExecute(result)
            except Exception:
                pass

        thread = _threading.Thread(target=run, daemon=True)
        self._thread = thread
        thread.start()
        return self

    def executeOnExecutor(self, executor, *args):
        return self.execute(*args)

    def publishProgress(self, *values):
        try:
            import extera_ios

            extera_ios.run_on_ui_thread(lambda: self.onProgressUpdate(*values))
        except Exception:
            pass

    def cancel(self, *args):
        self._cancelled = True
        return False

    def isCancelled(self):
        return self._cancelled

    def onPreExecute(self):
        pass

    def doInBackground(self, *args):
        return None

    def onPostExecute(self, result):
        pass

    def onProgressUpdate(self, *values):
        pass


class TimerTask:
    def run(self):
        pass


class Timer:
    def __init__(self, *args, **kwargs):
        self._timers = []

    def schedule(self, task, delay, period=None):
        def fire():
            _run_runnable(task)
            if period:
                self.schedule(task, period, period)

        timer = _threading.Timer(max(0, int(delay)) / 1000.0, fire)
        timer.daemon = True
        self._timers.append(timer)
        timer.start()

    def scheduleAtFixedRate(self, task, delay, period):
        self.schedule(task, delay, period)

    def cancel(self):
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()


class SparseArray:
    def __init__(self):
        self._values = {}

    def put(self, key, value):
        self._values[int(key)] = value
        return self

    def get(self, key, default=None):
        return self._values.get(int(key), default)

    def remove(self, key):
        self._values.pop(int(key), None)

    def size(self):
        return len(self._values)

    def keyAt(self, index):
        return sorted(self._values)[index]

    def valueAt(self, index):
        return self._values[sorted(self._values)[index]]

    def clear(self):
        self._values.clear()

    def __len__(self):
        return len(self._values)


class ArrayMap(dict):
    def put(self, key, value):
        self[key] = value
        return value

    def get(self, key, default=None):
        return dict.get(self, key, default)

    def containsKey(self, key):
        return key in self

    def size(self):
        return len(self)

    def isEmpty(self):
        return not self

    def keyAt(self, index):
        return list(self.keys())[int(index)]

    def valueAt(self, index):
        return list(self.values())[int(index)]

    def remove(self, key):
        return self.pop(key, None)

    def removeAt(self, index):
        key = list(self.keys())[int(index)]
        return self.pop(key, None)

    def clear(self):
        dict.clear(self)


class ArraySet(set):
    def add(self, value):
        set.add(self, value)
        return True

    def contains(self, value):
        return value in self

    def size(self):
        return len(self)

    def isEmpty(self):
        return not self

    def remove(self, value):
        if value in self:
            set.remove(self, value)
            return True
        return False

    def toArray(self):
        return list(self)


class Pair:
    def __init__(self, first=None, second=None):
        self.first = first
        self.second = second

    @staticmethod
    def create(first, second):
        return Pair(first, second)

    def __iter__(self):
        return iter((self.first, self.second))

    def __repr__(self):
        return "Pair(%r, %r)" % (self.first, self.second)


class CharacterStyle:
    def updateDrawState(self, paint=None):
        return None


class MetricAffectingSpan(CharacterStyle):
    pass


class ReplacementSpan(MetricAffectingSpan):
    def getSize(self, paint=None, text=None, start=0, end=0, fm=None):
        return 0.0

    def draw(self, canvas=None, text=None, start=0, end=0, x=0, top=0,
             y=0, bottom=0, paint=None):
        return None


class ForegroundColorSpan(CharacterStyle):
    def __init__(self, color=0):
        self.color = int(color or 0)

    def getForegroundColor(self):
        return self.color


class BackgroundColorSpan(CharacterStyle):
    def __init__(self, color=0):
        self.color = int(color or 0)

    def getBackgroundColor(self):
        return self.color


class StyleSpan(CharacterStyle):
    def __init__(self, style=0):
        self.style = int(style or 0)

    def getStyle(self):
        return self.style


class TypefaceSpan(CharacterStyle):
    def __init__(self, family=None):
        self.family = family

    def getFamily(self):
        return self.family


class RelativeSizeSpan(MetricAffectingSpan):
    def __init__(self, proportion=1.0):
        self.proportion = float(proportion or 1.0)

    def getSizeChange(self):
        return self.proportion


class AbsoluteSizeSpan(MetricAffectingSpan):
    def __init__(self, size=0, dip=False):
        self.size = int(size or 0)
        self.dip = bool(dip)

    def getSize(self):
        return self.size

    def getDip(self):
        return self.dip


class ScaleXSpan(MetricAffectingSpan):
    def __init__(self, proportion=1.0):
        self.proportion = float(proportion or 1.0)

    def getScaleX(self):
        return self.proportion


class UnderlineSpan(CharacterStyle):
    pass


class StrikethroughSpan(CharacterStyle):
    pass


class SuperscriptSpan(MetricAffectingSpan):
    pass


class SubscriptSpan(MetricAffectingSpan):
    pass


class MaskFilterSpan(CharacterStyle):
    def __init__(self, filter=None):
        self.filter = filter


class ClickableSpan(CharacterStyle):
    def onClick(self, view=None):
        pass

    def updateDrawState(self, paint=None):
        return None


class URLSpan(ClickableSpan):
    def __init__(self, url=""):
        self.url = str(url or "")

    def getURL(self):
        return self.url


class ImageSpan(ReplacementSpan):
    def __init__(self, drawable=None, *args, **kwargs):
        self.drawable = drawable

    def getDrawable(self):
        return self.drawable


class TextAppearanceSpan(CharacterStyle):
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class LocaleSpan(CharacterStyle):
    def __init__(self, locale=None):
        self.locale = locale


class SpannableString(str):
    SPAN_INCLUSIVE_EXCLUSIVE = 17
    SPAN_INCLUSIVE_INCLUSIVE = 18
    SPAN_EXCLUSIVE_EXCLUSIVE = 33
    SPAN_EXCLUSIVE_INCLUSIVE = 34
    SPAN_POINT_MARK = 0
    SPAN_MARK_MARK = 0
    SPAN_MARK_POINT = 1
    SPAN_POINT_POINT = 2
    SPAN_PARAGRAPH = 3
    SPAN_COMPOSING = 256
    SPAN_USER = 0xFF000000
    SPAN_USER_SHIFT = 24
    SPAN_PRIORITY = 0x00FF0000
    SPAN_PRIORITY_SHIFT = 16

    def __new__(cls, text=""):
        instance = super().__new__(cls, str(text))
        instance._spans = []
        return instance

    def toString(self):
        return str(self)

    def length(self):
        return len(self)

    def setSpan(self, span, start=0, end=0, flags=0):
        self._spans.append((span, int(start), int(end), int(flags)))
        return None

    def removeSpan(self, span):
        self._spans = [item for item in self._spans if item[0] is not span]
        return None

    def getSpanStart(self, span):
        for item in self._spans:
            if item[0] is span:
                return item[1]
        return -1

    def getSpanEnd(self, span):
        for item in self._spans:
            if item[0] is span:
                return item[2]
        return -1

    def getSpanFlags(self, span):
        for item in self._spans:
            if item[0] is span:
                return item[3]
        return 0

    def getSpans(self, start=0, end=None, kind=None):
        if end is None:
            end = len(self)
        result = []
        for span, span_start, span_end, _flags in self._spans:
            if span_start < int(end) and span_end > int(start):
                if kind is None or isinstance(span, kind):
                    result.append(span)
        return result

    def nextSpanTransition(self, start, limit, kind=None):
        return int(limit)


class SpannableStringBuilder(SpannableString):
    def append(self, value):
        return SpannableStringBuilder(str(self) + str(value))

    def insert(self, index, value):
        index = int(index)
        return SpannableStringBuilder(str(self)[:index] + str(value) + str(self)[index:])


class Editable(SpannableStringBuilder):
    pass


class Selection:
    @staticmethod
    def getSelectionStart(text):
        return int(getattr(text, "_selection_start", 0))

    @staticmethod
    def getSelectionEnd(text):
        return int(getattr(text, "_selection_end", 0))

    @staticmethod
    def setSelection(text, start, end=None):
        text._selection_start = int(start)
        text._selection_end = int(end if end is not None else start)
        return None

    @staticmethod
    def moveSelection(text, *args):
        return None

    @staticmethod
    def removeSelection(text):
        return None


class Pattern:
    CASE_INSENSITIVE = 2
    MULTILINE = 8
    DOTALL = 32

    def __init__(self, pattern, flags=0):
        import re

        self._pattern = str(pattern)
        self._flags = int(flags)
        py_flags = 0
        if self._flags & Pattern.CASE_INSENSITIVE:
            py_flags |= re.IGNORECASE
        if self._flags & Pattern.MULTILINE:
            py_flags |= re.MULTILINE
        if self._flags & Pattern.DOTALL:
            py_flags |= re.DOTALL
        self._compiled = re.compile(self._pattern, py_flags)

    @classmethod
    def compile(cls, pattern, flags=0):
        return cls(pattern, flags)

    @classmethod
    def matches(cls, regex, value):
        import re

        return bool(re.fullmatch(regex, str(value or "")))

    def matcher(self, value):
        return Matcher(self._compiled, value)

    def pattern(self):
        return self._pattern


class Patterns:
    EMAIL_ADDRESS = Pattern(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    WEB_URL = Pattern(r"https?://\S+")
    PHONE = Pattern(r"\+?[0-9][0-9\s\-()]{5,}")
    DOMAIN_NAME = Pattern(r"[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    IP_ADDRESS = Pattern(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


class Matcher:
    def __init__(self, compiled, value):
        self._compiled = compiled
        self._input = str(value or "")
        self._match = None

    def find(self):
        self._match = self._compiled.search(self._input)
        return self._match is not None

    def matches(self):
        self._match = self._compiled.fullmatch(self._input)
        return self._match is not None

    def lookingAt(self):
        self._match = self._compiled.match(self._input)
        return self._match is not None

    def group(self, index=0):
        if self._match is None:
            return None
        try:
            return self._match.group(index)
        except Exception:
            return None

    def groupCount(self):
        return self._compiled.groups

    def start(self, group=0):
        return self._match.start(group) if self._match else -1

    def end(self, group=0):
        return self._match.end(group) if self._match else -1

    def replaceAll(self, replacement):
        return self._compiled.sub(replacement, self._input)


class StringBuilder:
    def __init__(self, value=""):
        self._value = str(value or "")

    def append(self, value):
        self._value += str(value)
        return self

    def insert(self, index, value):
        index = int(index)
        self._value = self._value[:index] + str(value) + self._value[index:]
        return self

    def delete(self, start, end):
        self._value = self._value[: int(start)] + self._value[int(end):]
        return self

    def reverse(self):
        self._value = self._value[::-1]
        return self

    def substring(self, start, end=None):
        if end is None:
            return self._value[int(start):]
        return self._value[int(start): int(end)]

    def setLength(self, length):
        length = max(0, int(length))
        self._value = self._value[:length].ljust(length, "\0")
        return self

    def toString(self):
        return self._value

    def length(self):
        return len(self._value)

    def charAt(self, index):
        return self._value[int(index)]

    def __str__(self):
        return self._value


class Date:
    def __init__(self, millis=None):
        self._millis = int(millis) if millis is not None else int(time.time() * 1000)

    def getTime(self):
        return self._millis

    def setTime(self, millis):
        self._millis = int(millis)

    def before(self, other):
        return self._millis < int(getattr(other, "_millis", other))

    def after(self, other):
        return self._millis > int(getattr(other, "_millis", other))

    def toString(self):
        import datetime

        return datetime.datetime.fromtimestamp(self._millis / 1000.0).strftime(
            "%a %b %d %H:%M:%S %Y"
        )


class SimpleDateFormat:
    _TOKENS = [
        ("yyyy", "%Y"),
        ("yy", "%y"),
        ("MMMM", "%B"),
        ("MMM", "%b"),
        ("MM", "%m"),
        ("dd", "%d"),
        ("HH", "%H"),
        ("hh", "%I"),
        ("mm", "%M"),
        ("ss", "%S"),
        ("SSS", "%f"),
        ("a", "%p"),
        ("EEEE", "%A"),
        ("EEE", "%a"),
    ]

    def __init__(self, pattern="yyyy-MM-dd HH:mm:ss", locale=None):
        self._pattern = str(pattern)
        self._python = self._convert(self._pattern)

    @classmethod
    def _convert(cls, pattern):
        result = pattern
        for java, python in sorted(cls._TOKENS, key=lambda item: -len(item[0])):
            result = result.replace(java, python)
        return result

    def format(self, value):
        import datetime

        millis = value.getTime() if hasattr(value, "getTime") else int(value)
        return datetime.datetime.fromtimestamp(millis / 1000.0).strftime(self._python)

    def parse(self, value):
        import datetime

        parsed = datetime.datetime.strptime(str(value), self._python)
        return Date(int(parsed.timestamp() * 1000))


class DecimalFormat:
    def __init__(self, pattern="#,##0.###"):
        self._pattern = str(pattern or "#,##0.###")
        self._grouping = "," in self._pattern
        self._max_fraction = 0
        self._min_fraction = 0
        if "." in self._pattern:
            fraction = self._pattern.split(".", 1)[1]
            self._max_fraction = fraction.count("0") + fraction.count("#")
            self._min_fraction = fraction.count("0")
        self._multiplier = 100 if "%" in self._pattern else 1
        self._suffix = "%" if "%" in self._pattern else ""

    def applyPattern(self, pattern):
        self.__init__(pattern)
        return None

    def format(self, value=0.0):
        number = float(value or 0.0) * self._multiplier
        spec = "{:" + ("," if self._grouping else "") + "." + str(self._max_fraction) + "f}"
        text = spec.format(number)
        if "." in text:
            integer, fraction = text.split(".", 1)
            if self._min_fraction < self._max_fraction:
                fraction = fraction.rstrip("0")
                while len(fraction) < self._min_fraction:
                    fraction += "0"
            text = integer + ("." + fraction if fraction else "")
        if text.startswith("-0") and float(text) == 0.0:
            text = text[1:]
        return text + self._suffix

    def parse(self, value):
        text = str(value or "").replace(self._suffix, "").replace(",", "").strip()
        try:
            return float(text) / self._multiplier
        except (TypeError, ValueError):
            return 0.0

    def setMaximumFractionDigits(self, value):
        self._max_fraction = int(value)
        return None

    def setMinimumFractionDigits(self, value):
        self._min_fraction = int(value)
        return None

    def setGroupingUsed(self, value):
        self._grouping = bool(value)
        return None

    def setDecimalSeparator(self, value):
        return None

    def setGroupingSeparator(self, value):
        return None

    def setMultiplier(self, value):
        self._multiplier = int(value or 1)
        return None

    def isGroupingUsed(self):
        return self._grouping

    def getMaximumFractionDigits(self):
        return self._max_fraction

    def getMinimumFractionDigits(self):
        return self._min_fraction


class MessageFormat:
    def __init__(self, pattern="", locale=None):
        self._pattern = str(pattern or "")

    def format(self, *args):
        # Android has both `MessageFormat.format(pattern, args...)` and the
        # instance `format(args...)`; the first call passes the pattern as
        # `self`, so accept both shapes here.
        if isinstance(self, MessageFormat):
            pattern = self._pattern
            values = args
        else:
            pattern = str(self or "")
            values = args
        if len(values) == 1 and isinstance(values[0], (list, tuple, dict)):
            values = values[0]
        if values is None:
            values = ()
        if isinstance(values, dict):
            try:
                return pattern.format(**values)
            except Exception:
                return pattern
        if not isinstance(values, (list, tuple)):
            values = (values,)
        try:
            return pattern.format(*values)
        except Exception:
            try:
                return pattern % tuple(values)
            except Exception:
                return pattern

    def parse(self, value):
        return None

    def setLocale(self, locale):
        return None


class Typeface:
    DEFAULT = "default"
    DEFAULT_BOLD = "default-bold"
    SANS_SERIF = "sans-serif"
    SERIF = "serif"
    MONOSPACE = "monospace"
    NORMAL = 0
    BOLD = 1
    ITALIC = 2
    BOLD_ITALIC = 3

    @staticmethod
    def create(family, style):
        return family

    @staticmethod
    def createFromFile(path):
        return path

    @staticmethod
    def defaultFromStyle(style):
        return Typeface.DEFAULT_BOLD if int(style) & Typeface.BOLD else Typeface.DEFAULT


class VibrationEffect:
    DEFAULT_AMPLITUDE = -1

    @staticmethod
    def createOneShot(duration, amplitude=-1):
        return {"duration": int(duration), "amplitude": int(amplitude)}

    @staticmethod
    def createWaveform(timings, amplitudes=-1, repeat=-1):
        return {
            "timings": list(timings or []),
            "amplitudes": amplitudes,
            "repeat": int(repeat),
        }


class MediaMetadataRetriever:
    METADATA_KEY_DURATION = 9
    METADATA_KEY_MIMETYPE = 12
    METADATA_KEY_ARTIST = 2
    METADATA_KEY_TITLE = 7
    METADATA_KEY_HAS_VIDEO = 17
    METADATA_KEY_VIDEO_WIDTH = 18
    METADATA_KEY_VIDEO_HEIGHT = 19
    METADATA_KEY_VIDEO_ROTATION = 24
    OPTION_CLOSEST_SYNC = 2

    def __init__(self):
        self._path = None
        self._metadata = {}

    def setDataSource(self, path, *args, **kwargs):
        self._path = str(path) if path is not None else None
        self._metadata = (
            media_metadata.read_metadata(self._path) if self._path else {}
        )
        return None

    def extractMetadata(self, key):
        metadata = self._metadata or {}
        if key == self.METADATA_KEY_DURATION:
            duration = metadata.get("duration")
            if duration:
                return str(int(float(duration) * 1000))
            return None
        if key == self.METADATA_KEY_MIMETYPE:
            return metadata.get("mime_type") or None
        if key == self.METADATA_KEY_TITLE:
            return metadata.get("title") or None
        if key == self.METADATA_KEY_ARTIST:
            return metadata.get("artist") or None
        if key == self.METADATA_KEY_HAS_VIDEO:
            return "yes" if metadata.get("has_video") else "no"
        if key == self.METADATA_KEY_VIDEO_WIDTH:
            width = metadata.get("width")
            return str(int(width)) if width else None
        if key == self.METADATA_KEY_VIDEO_HEIGHT:
            height = metadata.get("height")
            return str(int(height)) if height else None
        if key == self.METADATA_KEY_VIDEO_ROTATION:
            rotation = metadata.get("rotation")
            return str(int(rotation)) if rotation is not None else None
        return None

    def getFrameAtTime(self, time_us=0, option=None, *args, **kwargs):
        if not self._path:
            return None
        try:
            import base64

            import extera_ios

            result = extera_ios.host(
                "media.frame",
                path=str(self._path),
                time=float(time_us or 0) / 1000000.0,
            )
            if isinstance(result, dict) and result.get("ok") and result.get("data"):
                data = base64.b64decode(result["data"])
                return Bitmap(
                    data,
                    int(result.get("width") or 0),
                    int(result.get("height") or 0),
                    path=str(self._path),
                )
        except Exception:
            pass
        return None

    def release(self):
        self._path = None
        self._metadata = {}


class MediaPlayer:
    @staticmethod
    def create(context, uri):
        return MediaPlayer()

    def setDataSource(self, *args, **kwargs):
        return None

    def prepare(self):
        return None

    def prepareAsync(self):
        return None

    def start(self):
        return None

    def pause(self):
        return None

    def stop(self):
        return None

    def reset(self):
        return None

    def release(self):
        return None

    def isPlaying(self):
        return False

    def getDuration(self):
        return 0

    def getCurrentPosition(self):
        return 0

    def seekTo(self, *args, **kwargs):
        return None

    def setOnCompletionListener(self, listener):
        return None

    def setOnPreparedListener(self, listener):
        return None

    def setOnErrorListener(self, listener):
        return None


class AudioManager:
    STREAM_VOICE_CALL = 0
    STREAM_SYSTEM = 1
    STREAM_RING = 2
    STREAM_MUSIC = 3
    STREAM_ALARM = 4
    AUDIOFOCUS_GAIN = 1
    AUDIOFOCUS_LOSS = -1
    AUDIOFOCUS_LOSS_TRANSIENT = -2

    def getStreamVolume(self, stream):
        return 0

    def setStreamVolume(self, stream, index, flags=0):
        return None

    def getStreamMaxVolume(self, stream):
        return 0

    def isMusicActive(self):
        return False

    def requestAudioFocus(self, *args, **kwargs):
        return 1

    def abandonAudioFocus(self, *args, **kwargs):
        return 1


class _BuildVersionCodes:
    BASE = 1
    DONUT = 4
    ECLAIR = 5
    FROYO = 8
    GINGERBREAD = 9
    GINGERBREAD_MR1 = 10
    HONEYCOMB = 11
    HONEYCOMB_MR1 = 12
    HONEYCOMB_MR2 = 13
    ICE_CREAM_SANDWICH = 14
    ICE_CREAM_SANDWICH_MR1 = 15
    JELLY_BEAN = 16
    JELLY_BEAN_MR1 = 17
    JELLY_BEAN_MR2 = 18
    KITKAT = 19
    KITKAT_WATCH = 20
    LOLLIPOP = 21
    LOLLIPOP_MR1 = 22
    M = 23
    N = 24
    N_MR1 = 25
    O = 26
    O_MR1 = 27
    P = 28
    Q = 29
    R = 30
    S = 31
    S_V2 = 32
    T = 33
    TIRAMISU = 33
    U = 34
    UPSIDE_DOWN_CAKE = 34
    V = 35
    VANILLA_ICE_CREAM = 35


class _BuildVersion:
    SDK_INT = 34
    RELEASE = "14"
    CODENAME = "REL"
    INCREMENTAL = "1"
    PREVIEW_SDK_INT = 0


class Build:
    VERSION = _BuildVersion()
    VERSION_CODES = _BuildVersionCodes()
    MANUFACTURER = "Apple"
    MODEL = "iPhone"
    DEVICE = "iphone"
    PRODUCT = "telegram"
    ID = "iOS"
    DISPLAY = "iOS"
    TYPE = "user"
    TAGS = "release-keys"
    BRAND = "Apple"
    BOARD = "iphone"
    HARDWARE = "arm64"
    FINGERPRINT = "Apple/iPhone/iOS"
    BOOTLOADER = "unknown"
    HOST = "iPhone"
    USER = "mobile"
    SERIAL = "unknown"
    SUPPORTED_ABIS = ["arm64-v8a", "arm64"]
    SUPPORTED_32_BIT_ABIS = []
    SUPPORTED_64_BIT_ABIS = ["arm64-v8a", "arm64"]
    TIME = 0


_THEME_OVERRIDES = {}


def _theme_color(key):
    override = _THEME_OVERRIDES.get(str(key))
    if override is not None:
        return override
    name = str(key or "").lower()
    if "hint" in name or "gray" in name or "grey" in name or "secondary" in name:
        return 0xFF8E8E93
    if "red" in name or "danger" in name or "destructive" in name:
        return 0xFFFF3B30
    if "green" in name or "success" in name:
        return 0xFF34C759
    if "blue" in name or "accent" in name or "link" in name or "activated" in name:
        return 0xFF007AFF
    if "orange" in name or "yellow" in name:
        return 0xFFFF9500
    if "black" in name:
        return 0xFF000000
    if "white" in name or "background" in name:
        return 0xFFFFFFFF
    return 0xFF000000


class _ThemeMeta(_TolerantClassMeta):
    def __getattr__(cls, name):
        if name.startswith("key_") or name.isupper():
            return name
        return super().__getattr__(name)


class Theme(metaclass=_ThemeMeta):
    class ResourcesProvider:
        @classmethod
        def getClass(cls):
            return _java_class_ref(
                "org.telegram.ui.ActionBar.Theme$ResourcesProvider"
            )

    @staticmethod
    def getColor(key, *args):
        return _theme_color(key)

    @staticmethod
    def getDefaultColor(key):
        return _theme_color(key)

    @staticmethod
    def setColor(key, color, useDefault=True):
        _THEME_OVERRIDES[str(key)] = int(color)
        return None

    @staticmethod
    def getAccentColor(key):
        return _theme_color(key)

    @staticmethod
    def getCurrentTheme():
        return Theme

    @staticmethod
    def getActiveTheme():
        return Theme

    @staticmethod
    def isCurrentThemeDark():
        return False

    @staticmethod
    def isDark():
        return False

    @staticmethod
    def createDialogSelectionDrawable(*args, **kwargs):
        return None

    @staticmethod
    def getSelectorDrawable(*args, **kwargs):
        return None

    @staticmethod
    def createSelectorDrawable(color=0, maskType=0, radius=0, *args, **kwargs):
        drawable = GradientDrawable()
        drawable.setColor(int(color or 0))
        drawable.setCornerRadius(float(int(radius or 0)))
        return drawable

    @staticmethod
    def createSelectorDrawableFromDrawables(normal=None, pressed=None, *args,
                                            **kwargs):
        return pressed or normal or ColorDrawable()

    @staticmethod
    def createRoundRectDrawable(*args, **kwargs):
        drawable = GradientDrawable()
        numbers = [int(value) for value in args if isinstance(value, int)]
        if numbers:
            drawable.setColor(numbers[-1])
        if len(numbers) == 2:
            drawable.setCornerRadius(numbers[0])
        elif len(numbers) >= 5:
            drawable.setCornerRadius(max(numbers[:4]))
        elif len(numbers) == 3:
            drawable.setCornerRadius(max(numbers[0], numbers[1]))
        return drawable

    @staticmethod
    def createRoundRectDrawableWithIcon(radius=0, icon=0, *args, **kwargs):
        drawable = GradientDrawable()
        drawable.setCornerRadius(float(int(radius or 0)))
        drawable.icon = icon
        return drawable

    @staticmethod
    def createRoundRectGradientDrawable(*args, **kwargs):
        return GradientDrawable()

    @staticmethod
    def createCircleDrawable(size=0, color=0, colorBottom=None, *args, **kwargs):
        drawable = GradientDrawable()
        drawable.setCornerRadius(float(int(size or 0)) / 2.0)
        drawable.setColor(int(color or 0))
        drawable.size = int(size or 0)
        return drawable

    @staticmethod
    def createCircleDrawableWithIcon(size=0, icon=0, stroke=0, *args, **kwargs):
        drawable = Theme.createCircleDrawable(size)
        drawable.icon = icon
        drawable.stroke = stroke
        return drawable

    @staticmethod
    def createSimpleSelectorCircleDrawable(size=0, defaultColor=0,
                                           pressedColor=0, *args, **kwargs):
        drawable = Theme.createCircleDrawable(size, defaultColor)
        drawable.pressedColor = int(pressedColor or 0)
        return drawable

    @staticmethod
    def createSimpleSelectorRoundRectDrawable(radius=0, defaultColor=0,
                                              pressedColor=0, maskColor=None,
                                              *args, **kwargs):
        drawable = Theme.createRoundRectDrawable(radius, defaultColor)
        drawable.pressedColor = int(pressedColor or 0)
        return drawable

    @staticmethod
    def createSimpleSelectorDrawable(*args, **kwargs):
        return Theme.createSelectorDrawable(
            args[0] if args else 0,
            args[1] if len(args) > 1 else 0,
        )

    @staticmethod
    def createRadSelectorDrawable(*args, **kwargs):
        numbers = [int(value) for value in args if isinstance(value, int)]
        drawable = GradientDrawable()
        if numbers:
            drawable.setColor(numbers[0])
        if len(numbers) > 1:
            drawable.setCornerRadius(max(numbers[1:]))
        return drawable

    @staticmethod
    def createOutlineCircleDrawable(size=0, color=0, strokeWidth=0, *args,
                                    **kwargs):
        drawable = Theme.createCircleDrawable(size)
        drawable.color = int(color or 0)
        drawable.strokeWidth = int(strokeWidth or 0)
        return drawable

    @staticmethod
    def createInsetRoundRectDrawable(color=0, radius=0, inset=0, *args,
                                     **kwargs):
        drawable = GradientDrawable()
        drawable.setColor(int(color or 0))
        drawable.setCornerRadius(float(radius or 0))
        drawable.inset = inset
        return drawable

    @staticmethod
    def createEditTextDrawable(*args, **kwargs):
        return GradientDrawable()

    @staticmethod
    def applyDefaultShadow(paint=None, *args, **kwargs):
        if paint is not None and hasattr(paint, "setShadowLayer"):
            try:
                paint.setShadowLayer(1.0, 0.0, 1.0, 0x55000000)
            except Exception:
                pass
        return None


class Color:
    BLACK = 0xFF000000
    DKGRAY = 0xFF444444
    GRAY = 0xFF888888
    LTGRAY = 0xFFCCCCCC
    WHITE = 0xFFFFFFFF
    RED = 0xFFFF0000
    GREEN = 0xFF00FF00
    BLUE = 0xFF0000FF
    YELLOW = 0xFFFFFF00
    CYAN = 0xFF00FFFF
    MAGENTA = 0xFFFF00FF
    TRANSPARENT = 0

    @staticmethod
    def parseColor(value):
        text = str(value or "").strip().lstrip("#")
        try:
            if len(text) == 3:
                text = "".join(character * 2 for character in text)
            number = int(text, 16)
            return number if len(text) == 8 else (0xFF000000 | number)
        except Exception:
            return 0

    @staticmethod
    def rgb(red, green, blue):
        return (0xFF << 24) | ((int(red) & 0xFF) << 16) | ((int(green) & 0xFF) << 8) | (int(blue) & 0xFF)

    @staticmethod
    def argb(alpha, red, green, blue):
        return ((int(alpha) & 0xFF) << 24) | ((int(red) & 0xFF) << 16) | ((int(green) & 0xFF) << 8) | (int(blue) & 0xFF)

    @staticmethod
    def rgba(red, green, blue, alpha):
        return Color.argb(alpha, red, green, blue)

    @staticmethod
    def alpha(color):
        return (int(color) >> 24) & 0xFF

    @staticmethod
    def red(color):
        return (int(color) >> 16) & 0xFF

    @staticmethod
    def green(color):
        return (int(color) >> 8) & 0xFF

    @staticmethod
    def blue(color):
        return int(color) & 0xFF

    @staticmethod
    def colorToHSV(color, hsv=None):
        import colorsys

        red = ((int(color) >> 16) & 0xFF) / 255.0
        green = ((int(color) >> 8) & 0xFF) / 255.0
        blue = (int(color) & 0xFF) / 255.0
        hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
        values = [hue * 360.0, saturation, value]
        if hsv is not None:
            try:
                hsv[0:3] = values
            except Exception:
                pass
            return None
        return values

    @staticmethod
    def HSVToColor(*args):
        import colorsys

        if len(args) == 1:
            alpha, hsv = 255, args[0]
        else:
            alpha, hsv = args[0], args[1]
        hue = float(hsv[0]) / 360.0
        red, green, blue = colorsys.hsv_to_rgb(hue, float(hsv[1]), float(hsv[2]))
        return Color.argb(
            alpha,
            int(round(red * 255)),
            int(round(green * 255)),
            int(round(blue * 255)),
        )

    @staticmethod
    def luminance(color):
        red = Color.red(color) / 255.0
        green = Color.green(color) / 255.0
        blue = Color.blue(color) / 255.0
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue


class Toast:
    LENGTH_SHORT = 0
    LENGTH_LONG = 1

    def __init__(self, text):
        self._text = text

    @classmethod
    def makeText(cls, context, text, duration=0):
        return cls(text)

    def show(self):
        try:
            from ui.bulletin import BulletinHelper

            BulletinHelper.show_info(self._text)
        except Exception:
            pass

    def cancel(self):
        return None


class _Bulletin:
    def __init__(self, kind, text, subtext=None, duration=None, button_text=None,
                 on_click=None, undo_text=None, on_undo=None, on_action=None):
        self.kind = kind
        self.text = text
        self.subtext = subtext
        self.duration = duration
        self.button_text = button_text
        self.on_click = on_click
        self.undo_text = undo_text
        self.on_undo = on_undo
        self.on_action = on_action

    def show(self):
        from ui.bulletin import BulletinHelper

        BulletinHelper._show(
            self.kind,
            self.text,
            subtext=self.subtext,
            duration=self.duration or BulletinHelper.DURATION_LONG,
            button_text=self.button_text,
            on_click=self.on_click,
            undo_text=self.undo_text,
            on_undo=self.on_undo,
            on_action=self.on_action,
        )

    def hide(self):
        return None


class _BulletinFactory:
    @staticmethod
    def _simple(icon, text, args):
        subtitle = None
        button_text = None
        duration = None
        action = None
        for arg in args:
            if isinstance(arg, str) and subtitle is None:
                subtitle = arg
            elif isinstance(arg, int) and duration is None:
                duration = arg
            elif callable(arg) and action is None:
                action = arg
        return _Bulletin(
            "simple", text, subtext=subtitle, duration=duration,
            button_text=button_text, on_click=action
        )

    def createSimpleBulletin(self, icon, text, *args, **kwargs):
        item = self._simple(icon, text, args)
        button_text = kwargs.get("button_text")
        on_click = kwargs.get("on_click")
        if button_text:
            item.button_text = button_text
        if on_click and item.on_click is None:
            item.on_click = on_click
        return item

    def createTwoLineBulletin(self, title, subtitle, icon=None, *args, **kwargs):
        return _Bulletin("simple", title, subtext=subtitle)

    def createEmojiBulletin(self, emoji, text, *args, **kwargs):
        prefix = str(emoji or "")
        return _Bulletin("simple", (prefix + " " + str(text or "")).strip())

    def createReportBulletin(self, report=None, *args, **kwargs):
        return _Bulletin("success", "Report sent")

    def createErrorBulletin(self, text, *args, **kwargs):
        return _Bulletin("error", text)

    def createSuccessBulletin(self, text, *args, **kwargs):
        return _Bulletin("success", text)

    def createCopyBulletin(self, text, provider=None):
        return _Bulletin("success", text)

    def createCopyLinkBulletin(self, private_link_info=False, provider=None):
        return _Bulletin("success", "Link copied")

    def createUndoBulletin(self, text, *args, **kwargs):
        subtitle = kwargs.get("subtitle")
        undo = None
        action = None
        for arg in args:
            if isinstance(arg, str) and subtitle is None:
                subtitle = arg
            elif callable(arg) and undo is None:
                undo = arg
            elif callable(arg) and action is None:
                action = arg
        return _Bulletin(
            "simple", text, subtext=subtitle, undo_text="Undo",
            on_undo=undo, on_action=action
        )

    def createDownloadBulletin(self, file_type=None, amount=1, provider=None):
        name = str(getattr(file_type, "name", file_type) or "UNKNOWN").upper()
        if "VIDEO" in name:
            text = "Videos saved to Photos" if amount > 1 else "Video saved to Photos"
        elif "PHOTO" in name or "IMAGE" in name:
            text = "Photos saved to Photos" if amount > 1 else "Photo saved to Photos"
        else:
            text = "Files saved to Files" if amount > 1 else "File saved to Files"
        return _Bulletin("success", text)


class ItemOptions:
    """`org.telegram.ui.Components.ItemOptions` popup-menu entry."""

    def __init__(self, *args, **kwargs):
        self.text = kwargs.get("text")
        self.subtext = kwargs.get("subtext")
        self.icon = kwargs.get("icon")
        self.color = int(kwargs.get("color") or 0)
        self.onClickListener = kwargs.get("onClickListener")
        self.enabled = True
        self.divider = False
        self.closeMenuOnClick = True
        self.minWidth = 0
        self.occupy = False

    @staticmethod
    def makeOptions(*args, **kwargs):
        result = []
        for value in args:
            if isinstance(value, str):
                result.append(ItemOptions(text=value))
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, str):
                        result.append(ItemOptions(text=item))
        return result

    @staticmethod
    def makeOptionsWithMask(*args, **kwargs):
        return ItemOptions.makeOptions(*args, **kwargs)

    def setText(self, value, subtext=None):
        self.text = value
        if subtext is not None:
            self.subtext = subtext
        return self

    def setSubtext(self, value):
        self.subtext = value
        return self

    def setIcon(self, value):
        self.icon = value
        return self

    def setIconColor(self, value):
        self.color = int(value or 0)
        return self

    def setOnClickListener(self, value):
        self.onClickListener = value
        return self

    def setEnabled(self, value):
        self.enabled = bool(value)
        return self

    def setDivider(self):
        self.divider = True
        return self

    def setSelector(self, value):
        return self

    def setCloseMenuOnClick(self, value):
        self.closeMenuOnClick = bool(value)
        return self

    def setMinWidth(self, value):
        self.minWidth = int(value or 0)
        return self

    def setOccupy(self, value):
        self.occupy = bool(value)
        return self


class BulletinFactory:
    class FileType:
        UNKNOWN = "UNKNOWN"
        UNKNOWNS = "UNKNOWNS"
        PHOTO = "PHOTO"
        PHOTOS = "PHOTOS"
        VIDEO = "VIDEO"
        VIDEOS = "VIDEOS"
        PHOTO_TO_DOWNLOADS = "PHOTO_TO_DOWNLOADS"
        PHOTOS_TO_DOWNLOADS = "PHOTOS_TO_DOWNLOADS"
        VIDEO_TO_DOWNLOADS = "VIDEO_TO_DOWNLOADS"
        VIDEOS_TO_DOWNLOADS = "VIDEOS_TO_DOWNLOADS"

        @classmethod
        def valueOf(cls, name):
            return getattr(cls, str(name or "UNKNOWN").upper(), cls.UNKNOWN)

        @classmethod
        def getName(cls, value):
            return str(value)

    @staticmethod
    def of(fragment=None):
        return _BulletinFactory()

    @staticmethod
    def global_():
        return _BulletinFactory()


# ---------------------------------------------------------------------------
# NotificationCenter
#
# Android plugins subscribe to app events with
# `get_notification_center(account).addObserver(delegate, NotificationCenter.updateNewMessage)`
# and implement `didReceivedNotification(id, account, args)`.  The iOS host
# names updates with the same strings, so a notification id is its own name and
# `update*` attributes resolve to that name.

_NOTIFICATION_INSTANCES = []
_NOTIFICATION_LOCK = _threading.RLock()


def _notification_key(identifier):
    if isinstance(identifier, str):
        return identifier
    name = getattr(identifier, "name", None)
    if isinstance(name, str):
        return name
    return str(identifier)


def _plugin_id_for(delegate):
    try:
        from extera_utils import lifecycle

        scope = lifecycle.current_scope()
        if scope is not None:
            return getattr(scope, "plugin_id", None)
    except Exception:
        pass
    return getattr(delegate, "id", None)


def _deliver(delegate, identifier, account, args):
    method = getattr(delegate, "didReceivedNotification", None)
    if not callable(method):
        return
    try:
        method(identifier, account, list(args))
    except Exception:
        try:
            import traceback

            import extera_ios

            extera_ios.log(
                "NotificationCenter observer failed for %s: %s"
                % (identifier, traceback.format_exc())
            )
        except Exception:
            pass


class NotificationCenterDelegate:
    """Base class matching `NotificationCenter.NotificationCenterDelegate`."""

    def didReceivedNotification(self, identifier, account, args):
        pass


def _sync_observed(identifier):
    """Tells the host whether any observer still needs this update name."""
    key = _notification_key(identifier)
    with _NOTIFICATION_LOCK:
        instances = list(_NOTIFICATION_INSTANCES)
    observed = any(instance.hasObservers(key) for instance in instances)
    try:
        import extera_ios

        extera_ios.host("notifications.set_observed", name=key, observed=observed)
    except Exception:
        pass


class _NotificationCenterMeta(type):
    def __getattr__(cls, name):
        # Android declares every event as a static int constant.  The host uses
        # the same names for updates, so the constant is its own identifier.
        # Return it for every non-dunder name; a plugin asking for
        # `NotificationCenter.dialogsNeedReload` gets a usable key.
        if name.startswith("__"):
            raise AttributeError(name)
        return name


class _NotificationCenterInstance:
    def __init__(self, account):
        self.account = int(account)
        self._observers = {}
        self._lock = _threading.RLock()

    def addObserver(self, delegate, identifier):
        if delegate is None:
            return
        if isinstance(identifier, (list, tuple, set, frozenset)):
            for item in identifier:
                self.addObserver(delegate, item)
            return
        key = _notification_key(identifier)
        plugin_id = _plugin_id_for(delegate)
        with self._lock:
            entries = self._observers.setdefault(key, [])
            for existing, _owner in entries:
                if existing is delegate:
                    return
            entries.append((delegate, plugin_id))
        _sync_observed(key)

    def removeObserver(self, delegate, identifier=None):
        with self._lock:
            keys = [_notification_key(identifier)] if identifier is not None else list(self._observers)
            for key in keys:
                entries = self._observers.get(key)
                if not entries:
                    continue
                remaining = [item for item in entries if item[0] is not delegate]
                if remaining:
                    self._observers[key] = remaining
                else:
                    self._observers.pop(key, None)
        for key in keys:
            _sync_observed(key)

    def removeAllObservers(self, delegate):
        self.removeObserver(delegate)

    def postNotificationName(self, identifier, *args):
        notify(self.account, identifier, *args)

    def postNotificationNameDelayed(self, identifier, args=(), delay=0):
        import extera_ios

        values = list(args or ())
        extera_ios.run_on_ui_thread(
            lambda: self.postNotificationName(identifier, *values), delay
        )

    def postNotificationNameOnUIThread(self, identifier, *args):
        import extera_ios

        values = list(args or ())
        extera_ios.run_on_ui_thread(
            lambda: self.postNotificationName(identifier, *values)
        )

    def addWeakObserver(self, delegate, identifier):
        return self.addObserver(delegate, identifier)

    def getObservers(self, identifier):
        with self._lock:
            return [delegate for delegate, _owner in self._observers.get(
                _notification_key(identifier), ()
            )]

    def setAnimationInProgress(self, value):
        with self._lock:
            self._animation_in_progress = bool(value)
        return None

    def isAnimationInProgress(self):
        with self._lock:
            return bool(getattr(self, "_animation_in_progress", False))

    def performOnAnimationFinish(self, runnable):
        if not self.isAnimationInProgress():
            try:
                runnable()
            except Exception:
                pass
            return None
        with self._lock:
            if not hasattr(self, "_animation_finish"):
                self._animation_finish = []
            self._animation_finish.append(runnable)
        return None

    def finishAnimation(self):
        with self._lock:
            callbacks = list(getattr(self, "_animation_finish", ()))
            self._animation_finish = []
            self._animation_in_progress = False
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass
        return None

    def listenForNotifications(self, value=True):
        with self._lock:
            self._listening = bool(value)
        return None

    def stopListeningForNotifications(self):
        return self.listenForNotifications(False)

    def addPostponeNotificationsCallback(self, callback):
        with self._lock:
            if not hasattr(self, "_postpone_callbacks"):
                self._postpone_callbacks = []
            if callback not in self._postpone_callbacks:
                self._postpone_callbacks.append(callback)
        return None

    def removePostponeNotificationsCallback(self, callback):
        with self._lock:
            callbacks = getattr(self, "_postpone_callbacks", [])
            if callback in callbacks:
                callbacks.remove(callback)
        return None

    def runDelayedNotifications(self):
        return None

    def hasObservers(self, identifier):
        with self._lock:
            return bool(self._observers.get(_notification_key(identifier)))

    def _snapshot(self, key):
        with self._lock:
            return list(self._observers.get(key, ()))


class NotificationCenter(metaclass=_NotificationCenterMeta):
    NotificationCenterDelegate = NotificationCenterDelegate

    @classmethod
    def getInstance(cls, account=0):
        account = int(account or 0)
        with _NOTIFICATION_LOCK:
            for instance in _NOTIFICATION_INSTANCES:
                if instance.account == account:
                    return instance
            instance = _NotificationCenterInstance(account)
            _NOTIFICATION_INSTANCES.append(instance)
            return instance

    @classmethod
    def getGlobalInstance(cls):
        return cls.getInstance(0)


def notify(account, identifier, *args):
    """Posts a notification to the observers of `account` and to global ones."""
    key = _notification_key(identifier)
    account = int(account or 0)
    with _NOTIFICATION_LOCK:
        instances = list(_NOTIFICATION_INSTANCES)
    for instance in instances:
        if instance.account not in (0, account):
            continue
        for delegate, _owner in instance._snapshot(key):
            _deliver(delegate, key, account, args)


def notify_update(update_name, account, update):
    """Bridges a host update into the Android-style notification bus."""
    notify(account, update_name, update)


def notify_all(identifier, *args):
    """Posts a notification to every account's observers and to global ones.

    Used for app-wide notifications such as `pluginsUpdated`, which Android
    broadcasts globally.
    """
    key = _notification_key(identifier)
    with _NOTIFICATION_LOCK:
        instances = list(_NOTIFICATION_INSTANCES)
    for instance in instances:
        for delegate, _owner in instance._snapshot(key):
            _deliver(delegate, key, instance.account, args)


def remove_observers_for_plugin(plugin_id):
    if not plugin_id:
        return
    with _NOTIFICATION_LOCK:
        instances = list(_NOTIFICATION_INSTANCES)
    for instance in instances:
        with instance._lock:
            for key in list(instance._observers):
                remaining = [
                    item for item in instance._observers[key] if item[1] != plugin_id
                ]
                if remaining:
                    instance._observers[key] = remaining
                else:
                    instance._observers.pop(key, None)
                    _sync_observed(key)


# ---------------------------------------------------------------------------
# Android view/widget/graphics stubs
#
# Plugins build these objects for custom settings rows and dialogs. iOS cannot
# render an Android view, but the objects and their common mutators must exist
# so plugin code runs; a declarative `view` spec is still the way to render one.

class WeakReference:
    def __init__(self, value=None):
        self._value = value

    def get(self):
        return self._value

    def clear(self):
        self._value = None

    def __call__(self):
        return self._value


class PyObject:
    def __init__(self, value=None):
        self.value = value

    @classmethod
    def getClass(cls):
        return _java_class_ref("com.chaquo.python.PyObject")

    @classmethod
    def fromJava(cls, value):
        if isinstance(value, PyObject):
            return value
        return cls(value)

    def toJava(self, *args, **kwargs):
        return self.value

    def call(self, *args, **kwargs):
        if callable(self.value):
            return PyObject(self.value(*args, **kwargs))
        raise PyException("%r is not callable" % (self.value,))

    def callAttr(self, name, *args):
        return PyObject(getattr(self.value, name)(*args))

    def get(self, key):
        if isinstance(self.value, dict):
            return PyObject(self.value.get(key))
        if isinstance(self.value, (list, tuple)) and isinstance(key, int):
            return PyObject(self.value[key])
        return PyObject(getattr(self.value, str(key), None))

    def put(self, key, value):
        raw = value.value if isinstance(value, PyObject) else value
        if isinstance(self.value, dict):
            self.value[key] = raw
            return None
        if isinstance(self.value, list) and isinstance(key, int):
            while len(self.value) <= key:
                self.value.append(None)
            self.value[key] = raw
            return None
        setattr(self.value, str(key), raw)
        return None

    def __call__(self, *args, **kwargs):
        return self.call(*args, **kwargs)

    def __bool__(self):
        return bool(self.value)

    def __len__(self):
        try:
            return len(self.value)
        except TypeError:
            return 0

    def __eq__(self, other):
        if isinstance(other, PyObject):
            return self.value == other.value
        return self.value == other

    def __hash__(self):
        return hash(self.value)

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return "PyObject(%r)" % (self.value,)


class _TextValue(str):
    """`CharSequence` from `TextView.getText()`: still compares as a string."""

    def toString(self):
        return str(self)

    def length(self):
        return len(self)

    def charAt(self, index):
        return str(self)[int(index)]

    def subSequence(self, start, end):
        return _TextValue(str(self)[int(start):int(end)])


class ViewPropertyAnimator:
    def __init__(self, view=None):
        self.view = view
        self.duration = 300
        self.start_delay = 0
        self.interpolator = None
        self.listener = None
        self._end_action = None
        self._start_action = None

    def alpha(self, value):
        self._alpha = float(value)
        return self

    def translationX(self, value):
        self._translation_x = float(value)
        return self

    def translationY(self, value):
        self._translation_y = float(value)
        return self

    def translationZ(self, value):
        return self

    def scaleX(self, value):
        self._scale_x = float(value)
        return self

    def scaleY(self, value):
        self._scale_y = float(value)
        return self

    def rotation(self, value):
        self._rotation = float(value)
        return self

    def rotationX(self, value):
        return self

    def rotationY(self, value):
        return self

    def setDuration(self, value):
        self.duration = int(value or 0)
        return self

    def setStartDelay(self, value):
        self.start_delay = int(value or 0)
        return self

    def setInterpolator(self, value):
        self.interpolator = value
        return self

    def setListener(self, listener):
        self.listener = listener
        return self

    def withEndAction(self, action):
        self._end_action = action
        return self

    def withStartAction(self, action):
        self._start_action = action
        return self

    def start(self):
        if callable(self._start_action):
            self._start_action()
        if callable(self._end_action):
            self._end_action()

    def cancel(self):
        return None


class Animator:
    def __init__(self):
        self._listeners = []
        self._duration = 300
        self._start_delay = 0
        self._running = False

    def setDuration(self, value):
        self._duration = int(value or 0)
        return self

    def getDuration(self):
        return self._duration

    def setStartDelay(self, value):
        self._start_delay = int(value or 0)
        return self

    def setInterpolator(self, value):
        self._interpolator = value
        return self

    def addListener(self, listener):
        self._listeners.append(listener)
        return self

    def removeAllListeners(self):
        self._listeners.clear()
        return None

    def start(self):
        self._running = True

    def end(self):
        self._running = False

    def cancel(self):
        self._running = False

    def isRunning(self):
        return self._running


class ValueAnimator(Animator):
    RESTART = 1
    REVERSE = 2
    INFINITE = -1

    def __init__(self):
        super().__init__()
        self._update_listeners = []
        self._values = []
        self._repeat_count = 0
        self._repeat_mode = 1

    @classmethod
    def ofFloat(cls, *values):
        animator = cls()
        animator._values = list(values)
        return animator

    @classmethod
    def ofInt(cls, *values):
        animator = cls()
        animator._values = list(values)
        return animator

    @classmethod
    def ofArgb(cls, *values):
        return cls.ofInt(*values)

    def addUpdateListener(self, listener):
        self._update_listeners.append(listener)
        return self

    def removeUpdateListener(self, listener):
        try:
            self._update_listeners.remove(listener)
        except ValueError:
            pass
        return None

    def removeAllUpdateListeners(self):
        self._update_listeners.clear()
        return None

    def setRepeatCount(self, value):
        self._repeat_count = int(value or 0)
        return self

    def setRepeatMode(self, value):
        self._repeat_mode = int(value or 0)
        return self

    def start(self):
        super().start()
        for listener in list(self._update_listeners):
            callback = getattr(listener, "onAnimationUpdate", None)
            try:
                if callable(callback):
                    callback(self)
                elif callable(listener):
                    listener(self)
            except Exception:
                pass

    def reverse(self):
        return None

    def getAnimatedValue(self):
        return self._values[-1] if self._values else 0.0

    def getAnimatedValueAt(self, index=0):
        try:
            return self._values[int(index)]
        except (IndexError, TypeError, ValueError):
            return 0.0

    def setEvaluator(self, value):
        return None


class ObjectAnimator(ValueAnimator):
    @classmethod
    def ofFloat(cls, target=None, property_name="", *values):
        animator = cls()
        animator.target = target
        animator.property_name = str(property_name or "")
        animator._values = list(values)
        return animator

    @classmethod
    def ofInt(cls, target=None, property_name="", *values):
        return cls.ofFloat(target, property_name, *values)

    @classmethod
    def ofArgb(cls, target=None, property_name="", *values):
        return cls.ofFloat(target, property_name, *values)

    def setPropertyName(self, value):
        self.property_name = str(value or "")
        return None

    def getPropertyName(self):
        return getattr(self, "property_name", "")


class AnimatorSet(Animator):
    def __init__(self):
        super().__init__()
        self._animators = []

    def playTogether(self, *animators):
        self._animators.extend(animators)
        return self

    def playSequentially(self, *animators):
        self._animators.extend(animators)
        return self

    def setDuration(self, value):
        super().setDuration(value)
        return self

    def start(self):
        super().start()
        for animator in list(self._animators):
            try:
                animator.start()
            except Exception:
                pass

    def cancel(self):
        super().cancel()
        for animator in list(self._animators):
            try:
                animator.cancel()
            except Exception:
                pass


class AnimatorListenerAdapter:
    def onAnimationStart(self, animation=None, is_reverse=False):
        return None

    def onAnimationEnd(self, animation=None, is_reverse=False):
        return None

    def onAnimationCancel(self, animation=None):
        return None

    def onAnimationRepeat(self, animation=None):
        return None


class AnimatorInflater:
    @staticmethod
    def loadAnimator(context=None, resource=0):
        return ValueAnimator()

    @staticmethod
    def loadStateListAnimator(context=None, resource=0):
        return None


class TimeInterpolator:
    def getInterpolation(self, value):
        return float(value or 0.0)


class LinearInterpolator(TimeInterpolator):
    pass


class AccelerateInterpolator(TimeInterpolator):
    def __init__(self, factor=1.0):
        self.factor = float(factor or 1.0)

    def getInterpolation(self, value):
        return float(value or 0.0) ** (2.0 * self.factor)


class DecelerateInterpolator(TimeInterpolator):
    def __init__(self, factor=1.0):
        self.factor = float(factor or 1.0)

    def getInterpolation(self, value):
        inverse = 1.0 - float(value or 0.0)
        return 1.0 - inverse ** (2.0 * self.factor)


class AccelerateDecelerateInterpolator(TimeInterpolator):
    def getInterpolation(self, value):
        import math

        return (math.cos((float(value or 0.0) + 1.0) * math.pi) / 2.0) + 0.5


class OvershootInterpolator(TimeInterpolator):
    def __init__(self, tension=2.0):
        self.tension = float(tension or 2.0)

    def getInterpolation(self, value):
        shifted = float(value or 0.0) - 1.0
        return shifted * shifted * ((self.tension + 1.0) * shifted + self.tension) + 1.0


class AnticipateInterpolator(TimeInterpolator):
    def __init__(self, tension=2.0):
        self.tension = float(tension or 2.0)

    def getInterpolation(self, value):
        value = float(value or 0.0)
        return value * value * ((self.tension + 1.0) * value - self.tension)


class AnticipateOvershootInterpolator(TimeInterpolator):
    def __init__(self, tension=2.0):
        self.tension = float(tension or 2.0)

    def getInterpolation(self, value):
        value = float(value or 0.0)
        if value < 0.5:
            return 0.5 * AnticipateInterpolator(self.tension).getInterpolation(
                value * 2.0
            )
        return 0.5 * (
            OvershootInterpolator(self.tension).getInterpolation(value * 2.0 - 1.0)
            + 1.0
        )


class BounceInterpolator(TimeInterpolator):
    def getInterpolation(self, value):
        value = float(value or 0.0)
        if value < 1.0 / 2.75:
            return 7.5625 * value * value
        if value < 2.0 / 2.75:
            value -= 1.5 / 2.75
            return 7.5625 * value * value + 0.75
        if value < 2.5 / 2.75:
            value -= 2.25 / 2.75
            return 7.5625 * value * value + 0.9375
        value -= 2.625 / 2.75
        return 7.5625 * value * value + 0.984375


class CycleInterpolator(TimeInterpolator):
    def __init__(self, cycles=1.0):
        self.cycles = float(cycles or 1.0)

    def getInterpolation(self, value):
        import math

        return math.sin(2.0 * math.pi * self.cycles * float(value or 0.0))


class PathInterpolator(TimeInterpolator):
    def __init__(self, *args, **kwargs):
        self.args = args

    def getInterpolation(self, value):
        return float(value or 0.0)


class Animation:
    RESTART = 1
    REVERSE = 2
    INFINITE = -1
    ABSOLUTE = 0
    RELATIVE_TO_SELF = 1
    RELATIVE_TO_PARENT = 2

    def __init__(self):
        self.duration = 0
        self.start_offset = 0
        self.fill_after = False
        self.fill_before = False
        self.repeat_count = 0
        self.repeat_mode = 0
        self.interpolator = None
        self.listener = None

    def setDuration(self, value):
        self.duration = int(value or 0)
        return self

    def getDuration(self):
        return self.duration

    def setStartOffset(self, value):
        self.start_offset = int(value or 0)
        return self

    def setFillAfter(self, value):
        self.fill_after = bool(value)
        return self

    def setFillBefore(self, value):
        self.fill_before = bool(value)
        return self

    def setRepeatCount(self, value):
        self.repeat_count = int(value or 0)
        return self

    def setRepeatMode(self, value):
        self.repeat_mode = int(value or 0)
        return self

    def setInterpolator(self, value):
        self.interpolator = value
        return self

    def setAnimationListener(self, listener):
        self.listener = listener
        return self

    def start(self):
        return None

    def startNow(self):
        return None

    def cancel(self):
        return None

    def reset(self):
        return None

    def setZAdjustment(self, value):
        return None

    def setBackgroundColor(self, value):
        return None

    def getTransformation(self, *args):
        return False

    def getStartTime(self):
        return 0

    def isInitialized(self):
        return True

    def hasStarted(self):
        return False

    def hasEnded(self):
        return False


class AlphaAnimation(Animation):
    def __init__(self, from_alpha=1.0, to_alpha=1.0):
        super().__init__()
        self.from_alpha = float(from_alpha or 0.0)
        self.to_alpha = float(to_alpha or 0.0)


class ScaleAnimation(Animation):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args


class TranslateAnimation(Animation):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args


class RotateAnimation(Animation):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args


class AnimationSet(Animation):
    def __init__(self, share_interpolator=False):
        super().__init__()
        self.share_interpolator = bool(share_interpolator)
        self._animations = []

    def addAnimation(self, animation):
        self._animations.append(animation)
        return None

    def getAnimations(self):
        return list(self._animations)

    def clear(self):
        self._animations.clear()
        return None


class AnimationUtils:
    @staticmethod
    def loadAnimation(context=None, resource=0):
        return AlphaAnimation()

    @staticmethod
    def currentAnimationTimeMillis():
        import time

        return int(time.time() * 1000)

    @staticmethod
    def makeInAnimation(context=None, from_left=True):
        return TranslateAnimation()

    @staticmethod
    def makeOutAnimation(context=None, to_right=True):
        return TranslateAnimation()

    @staticmethod
    def makeInChildBottomAnimation(context=None):
        return TranslateAnimation()


class Scene:
    def __init__(self, *args, **kwargs):
        self.args = args

    @staticmethod
    def getSceneForLayout(scene_root=None, layout_id=0, context=None):
        return Scene()


class Transition:
    def __init__(self):
        self.duration = 300
        self.start_delay = 0
        self.interpolator = None
        self._targets = []
        self._listeners = []

    def setDuration(self, value):
        self.duration = int(value or 0)
        return self

    def getDuration(self):
        return self.duration

    def setStartDelay(self, value):
        self.start_delay = int(value or 0)
        return self

    def setInterpolator(self, value):
        self.interpolator = value
        return self

    def addTarget(self, target):
        self._targets.append(target)
        return self

    def removeTarget(self, target):
        try:
            self._targets.remove(target)
        except ValueError:
            pass
        return self

    def addListener(self, listener):
        self._listeners.append(listener)
        return self

    def removeListener(self, listener):
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass
        return self

    def startTransition(self, scene_root=None):
        return None

    def endTransition(self):
        return None

    def setPathMotion(self, value):
        return self

    def setEpicenterCallback(self, value):
        return self

    def excludeTarget(self, *args):
        return self

    def excludeChildren(self, *args):
        return self


class Fade(Transition):
    IN = 1
    OUT = 2
    IN_OUT = 3

    def __init__(self, mode=IN):
        super().__init__()
        self.mode = mode

    def setFadingIn(self, value):
        return self

    def setFadingOut(self, value):
        return self


class Slide(Transition):
    LEFT = 3
    RIGHT = 4
    TOP = 1
    BOTTOM = 2

    def __init__(self, gravity=LEFT):
        super().__init__()
        self.gravity = gravity

    def setSlideEdge(self, value):
        self.gravity = value
        return self


class ChangeBounds(Transition):
    pass


class ChangeTransform(Transition):
    pass


class ChangeImageTransform(Transition):
    pass


class Explode(Transition):
    pass


class TransitionSet(Transition):
    def __init__(self):
        super().__init__()
        self._transitions = []

    def addTransition(self, value):
        self._transitions.append(value)
        return self

    def removeTransition(self, value):
        try:
            self._transitions.remove(value)
        except ValueError:
            pass
        return self

    def getTransitionCount(self):
        return len(self._transitions)


class TransitionManager:
    @staticmethod
    def beginDelayedTransition(scene_root=None, transition=None):
        return None

    @staticmethod
    def go(scene=None, transition=None):
        return None


class ViewTreeObserver:
    """The listener registry Android views expose through `getViewTreeObserver`."""

    class OnGlobalLayoutListener:
        def onGlobalLayout(self):
            pass

    class OnPreDrawListener:
        def onPreDraw(self):
            return True

    class OnScrollChangedListener:
        def onScrollChanged(self):
            pass

    class OnTouchModeChangeListener:
        def onTouchModeChanged(self, is_in_touch_mode):
            pass

    class OnWindowAttachListener:
        def onWindowAttached(self):
            pass

        def onWindowDetached(self):
            pass

    class OnWindowFocusChangeListener:
        def onWindowFocusChanged(self, has_focus):
            pass

    class OnDrawListener:
        def onDraw(self):
            pass

    def __init__(self):
        self._global_layout = []
        self._pre_draw = []
        self._scroll_changed = []
        self._touch_mode = []
        self._window_attach = []
        self._window_focus = []
        self._draw = []

    def addOnGlobalLayoutListener(self, listener):
        self._global_layout.append(listener)
        return None

    def removeOnGlobalLayoutListener(self, listener):
        try:
            self._global_layout.remove(listener)
        except ValueError:
            pass
        return None

    def addOnPreDrawListener(self, listener):
        self._pre_draw.append(listener)
        return None

    def removeOnPreDrawListener(self, listener):
        try:
            self._pre_draw.remove(listener)
        except ValueError:
            pass
        return None

    def addOnScrollChangedListener(self, listener):
        self._scroll_changed.append(listener)
        return None

    def removeOnScrollChangedListener(self, listener):
        try:
            self._scroll_changed.remove(listener)
        except ValueError:
            pass
        return None

    def addOnTouchModeChangeListener(self, listener):
        self._touch_mode.append(listener)
        return None

    def removeOnTouchModeChangeListener(self, listener):
        try:
            self._touch_mode.remove(listener)
        except ValueError:
            pass
        return None

    def addOnWindowAttachListener(self, listener):
        self._window_attach.append(listener)
        return None

    def removeOnWindowAttachListener(self, listener):
        try:
            self._window_attach.remove(listener)
        except ValueError:
            pass
        return None

    def addOnWindowFocusChangeListener(self, listener):
        self._window_focus.append(listener)
        return None

    def removeOnWindowFocusChangeListener(self, listener):
        try:
            self._window_focus.remove(listener)
        except ValueError:
            pass
        return None

    def addOnDrawListener(self, listener):
        self._draw.append(listener)
        return None

    def removeOnDrawListener(self, listener):
        try:
            self._draw.remove(listener)
        except ValueError:
            pass
        return None

    def dispatchOnGlobalLayout(self):
        for listener in list(self._global_layout):
            try:
                listener.onGlobalLayout()
            except Exception:
                pass
        return None

    def dispatchOnPreDraw(self):
        result = True
        for listener in list(self._pre_draw):
            try:
                result = listener.onPreDraw() and result
            except Exception:
                result = False
        return result

    def isAlive(self):
        return True

    def kill(self):
        return None


class View:
    VISIBLE = 0
    INVISIBLE = 4
    GONE = 8
    NO_ID = -1
    FOCUS_BACKWARD = 1
    FOCUS_FORWARD = 2
    FOCUS_LEFT = 17
    FOCUS_UP = 33
    FOCUS_RIGHT = 66
    FOCUS_DOWN = 130
    SCROLLBARS_INSIDE_OVERLAY = 0
    SCROLLBARS_INSIDE_INSET = 0x01000000
    SCROLLBARS_OUTSIDE_OVERLAY = 0x02000000
    SCROLLBARS_OUTSIDE_INSET = 0x03000000
    OVER_SCROLL_ALWAYS = 0
    OVER_SCROLL_IF_CONTENT_SCROLLS = 1
    OVER_SCROLL_NEVER = 2
    SYSTEM_UI_FLAG_VISIBLE = 0
    SYSTEM_UI_FLAG_LOW_PROFILE = 1
    SYSTEM_UI_FLAG_HIDE_NAVIGATION = 2
    SYSTEM_UI_FLAG_FULLSCREEN = 4
    SYSTEM_UI_FLAG_LAYOUT_STABLE = 256
    SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION = 512
    SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN = 1024
    SYSTEM_UI_FLAG_IMMERSIVE = 2048
    SYSTEM_UI_FLAG_IMMERSIVE_STICKY = 4096

    @classmethod
    def getClass(cls):
        return _java_class_ref("android.view.View")

    class OnClickListener:
        def onClick(self, view):
            pass

    class OnLongClickListener:
        def onLongClick(self, view):
            return False

    class OnTouchListener:
        def onTouch(self, view, event):
            return False

    class OnFocusChangeListener:
        def onFocusChange(self, view, hasFocus):
            pass

    class OnLayoutChangeListener:
        def onLayoutChange(self, *args):
            pass

    class MeasureSpec:
        UNSPECIFIED = 0
        EXACTLY = 1
        AT_MOST = 2

        @staticmethod
        def makeMeasureSpec(size, mode):
            return (int(size) << 2) | (int(mode) & 3)

        @staticmethod
        def getMode(spec):
            return int(spec) & 3

        @staticmethod
        def getSize(spec):
            return int(spec) >> 2

    class BaseSavedState:
        pass

    def __init__(self, context=None, *args, **kwargs):
        self.context = context
        self.visibility = View.VISIBLE
        self.tag = None
        self.enabled = True
        self.alpha = 1.0
        self.layoutParams = None
        self.background = None
        self.contentDescription = None
        self._click = None
        self._longClick = None
        self._focusListener = None
        self._touchListener = None

    def setVisibility(self, value):
        self.visibility = value

    def getVisibility(self):
        return self.visibility

    def getViewTreeObserver(self):
        observer = getattr(self, "_viewTreeObserver", None)
        if observer is None:
            observer = ViewTreeObserver()
            self._viewTreeObserver = observer
        return observer

    def post(self, runnable):
        try:
            import extera_ios

            function = runnable.run if hasattr(runnable, "run") else runnable
            return extera_ios.run_on_ui_thread(function)
        except Exception:
            return None

    def postDelayed(self, runnable, delay=0):
        try:
            import extera_ios

            function = runnable.run if hasattr(runnable, "run") else runnable
            return extera_ios.run_on_ui_thread(function, delay)
        except Exception:
            return None

    def removeCallbacks(self, runnable=None):
        return None

    def setOnClickListener(self, listener):
        self._click = listener

    def setOnLongClickListener(self, listener):
        self._longClick = listener

    def setOnFocusChangeListener(self, listener):
        self._focusListener = listener

    def setOnTouchListener(self, listener):
        self._touchListener = listener

    def performHapticFeedback(self, *args):
        return False

    def performClick(self):
        if self._click is not None:
            self._click(self)
        return True

    def setLayoutParams(self, params):
        self.layoutParams = params

    def getLayoutParams(self):
        return self.layoutParams

    def setPadding(self, *args):
        return None

    def setBackgroundColor(self, color):
        self.background = color

    def setBackground(self, drawable):
        self.background = drawable

    def setTag(self, tag):
        self.tag = tag

    def getTag(self):
        return self.tag

    def setEnabled(self, value):
        self.enabled = bool(value)

    def isEnabled(self):
        return self.enabled

    def setAlpha(self, value):
        self.alpha = float(value)

    def setTranslationX(self, value):
        return None

    def setTranslationY(self, value):
        return None

    def setScaleX(self, value):
        return None

    def setScaleY(self, value):
        return None

    def invalidate(self):
        return None

    def requestLayout(self):
        return None

    def getWidth(self):
        return 0

    def getHeight(self):
        return 0

    def getContext(self):
        return self.context

    def setContentDescription(self, value):
        self.contentDescription = value

    def post(self, runnable):
        return AndroidUtilities.runOnUIThread(runnable)

    def setMinimumHeight(self, value):
        return None

    def setMinimumWidth(self, value):
        return None


    def animate(self):
        return ViewPropertyAnimator(self)

    def setRotation(self, value):
        self.rotation = float(value)
        return None

    def setRotationX(self, value):
        return None

    def setRotationY(self, value):
        return None

    def setPivotX(self, value):
        return None

    def setPivotY(self, value):
        return None

    def setElevation(self, value):
        self.elevation = float(value)
        return None

    def setTranslationZ(self, value):
        return None

    def setSelected(self, value):
        self.selected = bool(value)
        return None

    def isSelected(self):
        return bool(getattr(self, "selected", False))

    def setClickable(self, value):
        self.clickable = bool(value)
        return None

    def setLongClickable(self, value):
        self.longClickable = bool(value)
        return None

    def setFocusable(self, value):
        self.focusable = bool(value)
        return None

    def setFocusableInTouchMode(self, value):
        return None

    def getParent(self):
        return getattr(self, "parent", None)

    def getRootView(self):
        return self

    def bringToFront(self):
        return None

    def setKeepScreenOn(self, value):
        return None

    def setOnCreateContextMenuListener(self, listener):
        self.createContextMenuListener = listener
        return None

    def setOnKeyListener(self, listener):
        self.keyListener = listener
        return None

    def setOnDragListener(self, listener):
        return None

    def startDragAndDrop(self, data):
        return False

    def setSystemUiVisibility(self, value):
        return None

    def setFitsSystemWindows(self, value):
        return None

    def setBackgroundResource(self, resource):
        self.backgroundResource = resource
        return None

    def setForeground(self, drawable):
        return None

    def setOutlineProvider(self, provider):
        return None

    def setClipToOutline(self, value):
        return None

    def getLayoutDirection(self):
        return 0

    def setLayoutDirection(self, value):
        return None

    def setImportantForAccessibility(self, value):
        return None


class WebSettings:
    def __init__(self):
        self._values = {}

    def setJavaScriptEnabled(self, value):
        self._values["javascript"] = bool(value)
        return None

    def getJavaScriptEnabled(self):
        return self._values.get("javascript", True)

    def setDomStorageEnabled(self, value):
        self._values["dom"] = bool(value)
        return None

    def getDomStorageEnabled(self):
        return self._values.get("dom", True)

    def setDatabaseEnabled(self, value):
        return None

    def setAllowFileAccess(self, value):
        return None

    def setAllowContentAccess(self, value):
        return None

    def setLoadWithOverviewMode(self, value):
        return None

    def setUseWideViewPort(self, value):
        return None

    def setSupportZoom(self, value):
        return None

    def setBuiltInZoomControls(self, value):
        return None

    def setDisplayZoomControls(self, value):
        return None

    def setMediaPlaybackRequiresUserGesture(self, value):
        return None

    def setMixedContentMode(self, value):
        return None

    def setCacheMode(self, value):
        return None

    def setUserAgentString(self, value):
        self._values["ua"] = str(value or "")
        return None

    def getUserAgentString(self):
        return self._values.get("ua", "")

    def setTextZoom(self, value):
        return None

    def setDefaultFontSize(self, value):
        return None

    def setDefaultTextEncodingName(self, value):
        return None

    def setJavaScriptCanOpenWindowsAutomatically(self, value):
        return None

    def setSupportMultipleWindows(self, value):
        return None

    def setAppCacheEnabled(self, value):
        return None

    def setGeolocationEnabled(self, value):
        return None

    def setSaveFormData(self, value):
        return None

    def setBlockNetworkImage(self, value):
        return None

    def setBlockNetworkLoads(self, value):
        return None

    def setForceDark(self, value):
        return None

    def setAlgorithmicDarkeningAllowed(self, value):
        return None


class WebView(View):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self._settings = WebSettings()
        self._url = ""
        self._client = None
        self._chrome = None

    def loadUrl(self, url, headers=None):
        self._url = str(url or "")
        return None

    def loadData(self, data, mime_type="text/html", encoding="utf-8"):
        return None

    def loadDataWithBaseURL(self, base_url, data, mime_type="text/html",
                            encoding="utf-8", history_url=None):
        return None

    def getSettings(self):
        return self._settings

    def setWebViewClient(self, client):
        self._client = client
        return None

    def setWebChromeClient(self, client):
        self._chrome = client
        return None

    def evaluateJavascript(self, script, callback=None):
        if callable(callback):
            callback("")
        return None

    def addJavascriptInterface(self, obj, name):
        return None

    def removeJavascriptInterface(self, name):
        return None

    def reload(self):
        return None

    def stopLoading(self):
        return None

    def destroy(self):
        return None

    def getUrl(self):
        return self._url

    def canGoBack(self):
        return False

    def goBack(self):
        return None

    def canGoForward(self):
        return False

    def goForward(self):
        return None

    def setBackgroundColor(self, color):
        return None

    def clearCache(self, include_disk_files=False):
        return None

    def clearHistory(self):
        return None

    def setLayerType(self, *args):
        return None

    def getProgress(self):
        return 100

    def setInitialScale(self, scale):
        return None

    def postUrl(self, *args):
        return None


class WebViewClient:
    def __init__(self, *args, **kwargs):
        pass

    def shouldOverrideUrlLoading(self, view=None, request=None):
        return False

    def onPageStarted(self, view=None, url=None, favicon=None):
        pass

    def onPageFinished(self, view=None, url=None):
        pass

    def onReceivedError(self, *args):
        pass

    def onReceivedHttpError(self, *args):
        pass

    def onLoadResource(self, *args):
        pass

    def shouldInterceptRequest(self, *args):
        return None

    def doUpdateVisitedHistory(self, *args):
        pass

    def onFormResubmission(self, *args):
        pass


class WebChromeClient:
    def __init__(self, *args, **kwargs):
        pass

    def onJsAlert(self, view=None, url=None, message=None, result=None):
        return False

    def onJsConfirm(self, view=None, url=None, message=None, result=None):
        return False

    def onJsPrompt(self, *args):
        return False

    def onConsoleMessage(self, *args):
        return False

    def onProgressChanged(self, view=None, progress=0):
        pass

    def onShowFileChooser(self, *args):
        return False

    def onCreateWindow(self, *args):
        return False

    def onCloseWindow(self, *args):
        pass

    def onPermissionRequest(self, *args):
        pass

    def onGeolocationPermissionsShowPrompt(self, *args):
        pass


class CookieManager:
    _instance = None

    @classmethod
    def getInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def setCookie(self, url, value):
        return None

    def getCookie(self, url):
        return ""

    def removeAllCookies(self, callback=None):
        if callable(callback):
            callback(True)
        return None

    def removeSessionCookies(self, callback=None):
        if callable(callback):
            callback(True)
        return None

    def flush(self):
        return None

    def setAcceptCookie(self, value):
        return None

    def acceptCookie(self):
        return True

    def setAcceptThirdPartyCookies(self, webview, value):
        return None


class WebResourceRequest:
    def __init__(self, url="", method="GET", headers=None,
                 is_for_main_frame=True):
        self._url = url
        self._method = str(method or "GET")
        self._headers = dict(headers or {})
        self._main = bool(is_for_main_frame)

    def getUrl(self):
        return Uri.parse(self._url) if isinstance(self._url, str) else self._url

    def getMethod(self):
        return self._method

    def getRequestHeaders(self):
        return dict(self._headers)

    def isForMainFrame(self):
        return self._main

    def isRedirect(self):
        return False

    def hasGesture(self):
        return False


class WebResourceResponse:
    def __init__(self, mime_type="", encoding="", status_code=200, reason="",
                 headers=None, data=None):
        self._mime = str(mime_type or "")
        self._encoding = str(encoding or "")
        self._status = int(status_code or 200)
        self._reason = str(reason or "")
        self._headers = dict(headers or {})
        self._data = data

    def getMimeType(self):
        return self._mime

    def setMimeType(self, value):
        self._mime = str(value or "")

    def getEncoding(self):
        return self._encoding

    def setEncoding(self, value):
        self._encoding = str(value or "")

    def getStatusCode(self):
        return self._status

    def getReasonPhrase(self):
        return self._reason

    def setStatusCodeAndReasonPhrase(self, status, reason):
        self._status = int(status)
        self._reason = str(reason)

    def getResponseHeaders(self):
        return dict(self._headers)

    def setResponseHeaders(self, value):
        self._headers = dict(value or {})

    def getData(self):
        return self._data

    def setData(self, value):
        self._data = value


class TextView(View):
    class OnEditorActionListener:
        def onEditorAction(self, view, actionId, event):
            return False

    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.text = ""
        self.hint = ""
        self.textSize = 14.0
        self.textColor = 0xFF000000
        self.hintTextColor = 0xFF808080
        self.cursorColor = 0xFF007AFF
        self.cursorWidth = 1.0
        self.gravity = 0
        self.typeface = None
        self._editorActionListener = None

    def setText(self, value):
        self.text = "" if value is None else str(value)

    def getText(self):
        return _TextValue(self.text)

    def setTextSize(self, *args):
        if args:
            self.textSize = float(args[-1])

    def setTextColor(self, color):
        self.textColor = color

    def setGravity(self, value):
        self.gravity = value

    def setTypeface(self, value):
        self.typeface = value

    def setSingleLine(self, value=True):
        return None

    def setMaxLines(self, value):
        return None

    def setLines(self, value):
        return None

    def setEllipsize(self, value):
        return None

    def setHint(self, value):
        self.hint = "" if value is None else str(value)

    def setHintTextColor(self, color):
        self.hintTextColor = color

    def setCursorColor(self, color):
        self.cursorColor = color

    def setCursorWidth(self, width):
        self.cursorWidth = float(width)

    def setOnEditorActionListener(self, listener):
        self._editorActionListener = listener

    def length(self):
        return len(self.text or "")

    def requestFocus(self):
        return True

    def setSelection(self, *args):
        return None


class EditText(TextView):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.inputType = 0
        self._watchers = []

    def setInputType(self, value):
        self.inputType = value

    def addTextChangedListener(self, watcher):
        self._watchers.append(watcher)

    def setSelection(self, *args):
        return None

    def getSelectionStart(self):
        return 0

    def getSelectionEnd(self):
        return 0


class Button(TextView):
    pass


class ImageView(View):
    class ScaleType:
        MATRIX = 0
        FIT_XY = 1
        FIT_START = 2
        FIT_CENTER = 3
        FIT_END = 4
        CENTER = 5
        CENTER_CROP = 6
        CENTER_INSIDE = 7

    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.drawable = None
        self.scaleType = ImageView.ScaleType.FIT_CENTER

    def setImageDrawable(self, drawable):
        self.drawable = drawable

    def setImageBitmap(self, bitmap):
        self.drawable = bitmap

    def setImageResource(self, resource):
        self.drawable = resource

    def setScaleType(self, value):
        self.scaleType = value
        return None

    def getScaleType(self):
        return self.scaleType

    def setColorFilter(self, *args, **kwargs):
        return None


class CompoundButton(TextView):
    class OnCheckedChangeListener:
        def onCheckedChanged(self, button, isChecked):
            pass

    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.checked = False
        self._checkedListener = None

    def setChecked(self, value):
        self.checked = bool(value)
        return None

    def isChecked(self):
        return self.checked

    def setOnCheckedChangeListener(self, listener):
        self._checkedListener = listener
        return None

    def toggle(self):
        self.checked = not self.checked
        return None


class Switch(CompoundButton):

    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.checked = False
        self._checkedListener = None

    def setChecked(self, value):
        self.checked = bool(value)

    def isChecked(self):
        return self.checked

    def setOnCheckedChangeListener(self, listener):
        self._checkedListener = listener

    def toggle(self):
        self.checked = not self.checked


class LinearLayout(View):
    HORIZONTAL = 0
    VERTICAL = 1

    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.orientation = LinearLayout.VERTICAL
        self.children = []

    def setOrientation(self, value):
        self.orientation = value

    def addView(self, view, *args, **kwargs):
        self.children.append(view)

    def removeAllViews(self):
        self.children.clear()

    def getChildCount(self):
        return len(self.children)

    def getChildAt(self, index):
        return self.children[index] if 0 <= index < len(self.children) else None


class FrameLayout(LinearLayout):
    pass


class ScrollView(LinearLayout):
    def setFillViewport(self, value):
        return None


class RelativeLayout(LinearLayout):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.rules = {}

    def addRule(self, rule, value=None):
        self.rules[rule] = value


class ViewGroup(View):
    class LayoutParams:
        MATCH_PARENT = -1
        WRAP_CONTENT = -2

        def __init__(self, width=MATCH_PARENT, height=WRAP_CONTENT):
            self.width = width
            self.height = height

    class MarginLayoutParams(LayoutParams):
        def __init__(self, width=-1, height=-2):
            super().__init__(width, height)
            self.leftMargin = 0
            self.topMargin = 0
            self.rightMargin = 0
            self.bottomMargin = 0

        def setMargins(self, left, top, right, bottom):
            self.leftMargin = left
            self.topMargin = top
            self.rightMargin = right
            self.bottomMargin = bottom

    def removeView(self, view):
        return None

    def removeViewAt(self, index):
        return None

    def setClipChildren(self, value):
        return None

    def setClipToPadding(self, value):
        return None


class ProgressBar(View):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.progress = 0
        self.max = 100
        self.indeterminate = False

    def setProgress(self, value):
        self.progress = int(value)

    def getProgress(self):
        return self.progress

    def setMax(self, value):
        self.max = int(value)

    def getMax(self):
        return self.max

    def setIndeterminate(self, value):
        self.indeterminate = bool(value)


class SeekBar(ProgressBar):
    class OnSeekBarChangeListener:
        def onProgressChanged(self, seek_bar, progress, from_user):
            pass

        def onStartTrackingTouch(self, seek_bar):
            pass

        def onStopTrackingTouch(self, seek_bar):
            pass

    def setOnSeekBarChangeListener(self, listener):
        self._seekListener = listener


class CheckBox(Switch):
    pass


class RadioButton(Switch):
    pass


class BaseAdapter:
    def __init__(self, *args, **kwargs):
        self._observers = []

    def getCount(self):
        return 0

    def getItem(self, position):
        return None

    def getItemId(self, position):
        return 0

    def getView(self, position, convertView=None, parent=None):
        return convertView

    def getDropDownView(self, position, convertView=None, parent=None):
        return convertView

    def getViewTypeCount(self):
        return 1

    def getItemViewType(self, position):
        return 0

    def isEmpty(self):
        return self.getCount() == 0

    def hasStableIds(self):
        return False

    def areAllItemsEnabled(self):
        return True

    def isEnabled(self, position):
        return True

    def notifyDataSetChanged(self):
        return None

    def notifyDataSetInvalidated(self):
        return None

    def registerDataSetObserver(self, observer):
        self._observers.append(observer)
        return None

    def unregisterDataSetObserver(self, observer):
        try:
            self._observers.remove(observer)
        except ValueError:
            pass
        return None


class ArrayAdapter(BaseAdapter):
    def __init__(self, context=None, resource=0, objects=None):
        super().__init__()
        self.context = context
        self.resource = resource
        self.objects = list(objects or [])

    def add(self, value):
        self.objects.append(value)
        return None

    def addAll(self, values):
        self.objects.extend(values or [])
        return None

    def insert(self, position, value):
        self.objects.insert(int(position), value)
        return None

    def remove(self, value):
        try:
            self.objects.remove(value)
        except ValueError:
            pass
        return None

    def clear(self):
        self.objects.clear()
        return None

    def getCount(self):
        return len(self.objects)

    def getItem(self, position):
        try:
            return self.objects[int(position)]
        except (IndexError, TypeError, ValueError):
            return None

    def getPosition(self, item):
        try:
            return self.objects.index(item)
        except ValueError:
            return -1

    def setNotifyOnChange(self, value):
        return None

    def sort(self, comparator=None):
        return None

    def setDropDownViewResource(self, value):
        return None

    def getContext(self):
        return self.context


class SimpleAdapter(BaseAdapter):
    def __init__(self, context=None, data=None, resource=0, from_=None, to=None):
        super().__init__()
        self.context = context
        self.data = list(data or [])
        self.resource = resource
        self.from_ = list(from_ or [])
        self.to = list(to or [])

    def getCount(self):
        return len(self.data)

    def getItem(self, position):
        try:
            return self.data[int(position)]
        except (IndexError, TypeError, ValueError):
            return None

    def getView(self, *args):
        return None


class ListView(ViewGroup):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.adapter = None
        self._item_click = None
        self._item_long_click = None

    def setAdapter(self, value):
        self.adapter = value
        return None

    def getAdapter(self):
        return self.adapter

    def setOnItemClickListener(self, value):
        self._item_click = value
        return None

    def setOnItemLongClickListener(self, value):
        self._item_long_click = value
        return None

    def setSelection(self, value):
        return None

    def getSelectedItemPosition(self):
        return 0

    def smoothScrollToPosition(self, value):
        return None

    def setDivider(self, value):
        return None

    def setDividerHeight(self, value):
        return None

    def setEmptyView(self, value):
        return None

    def getCount(self):
        return self.adapter.getCount() if self.adapter is not None else 0

    def getChildCount(self):
        return 0

    def getChildAt(self, index):
        return None

    def invalidateViews(self):
        return None

    def setFastScrollEnabled(self, value):
        return None

    def setVerticalScrollBarEnabled(self, value):
        return None

    def setOverScrollMode(self, value):
        return None


class GridView(ViewGroup):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.adapter = None
        self.num_columns = 1

    def setAdapter(self, value):
        self.adapter = value
        return None

    def getAdapter(self):
        return self.adapter

    def setNumColumns(self, value):
        self.num_columns = int(value or 1)
        return None

    def getNumColumns(self):
        return self.num_columns

    def setHorizontalSpacing(self, value):
        return None

    def setVerticalSpacing(self, value):
        return None

    def setStretchMode(self, value):
        return None

    def setColumnWidth(self, value):
        return None

    def setOnItemClickListener(self, value):
        return None

    def getCount(self):
        return self.adapter.getCount() if self.adapter is not None else 0


class AbsListView(ListView):
    pass


class AdapterView:
    class OnItemClickListener:
        def onItemClick(self, parent=None, view=None, position=0, identifier=0):
            pass

    class OnItemLongClickListener:
        def onItemLongClick(self, parent=None, view=None, position=0,
                           identifier=0):
            return False

    class OnItemSelectedListener:
        def onItemSelected(self, parent=None, view=None, position=0,
                           identifier=0):
            pass

        def onNothingSelected(self, parent=None):
            pass


class PopupWindow:
    INPUT_METHOD_FROM_FOCUSABLE = 0
    INPUT_METHOD_NEEDED = 1
    INPUT_METHOD_NOT_NEEDED = 2

    def __init__(self, *args, **kwargs):
        self.contentView = args[0] if args else kwargs.get("contentView")
        self.width = 0
        self.height = 0
        self.focusable = False
        self.showing = False

    def setContentView(self, value):
        self.contentView = value
        return None

    def getContentView(self):
        return self.contentView

    def setWidth(self, value):
        self.width = int(value or 0)
        return None

    def getWidth(self):
        return self.width

    def setHeight(self, value):
        self.height = int(value or 0)
        return None

    def getHeight(self):
        return self.height

    def setFocusable(self, value):
        self.focusable = bool(value)
        return None

    def isFocusable(self):
        return self.focusable

    def setOutsideTouchable(self, value):
        return None

    def setBackgroundDrawable(self, value):
        return None

    def setAnimationStyle(self, value):
        return None

    def setElevation(self, value):
        return None

    def setTouchInterceptor(self, value):
        return None

    def setOnDismissListener(self, value):
        return None

    def showAtLocation(self, parent=None, gravity=0, x=0, y=0):
        self.showing = True
        return None

    def showAsDropDown(self, anchor=None, *args):
        self.showing = True
        return None

    def dismiss(self):
        self.showing = False
        return None

    def isShowing(self):
        return self.showing

    def update(self, *args):
        return None


class ListPopupWindow:
    def __init__(self, context=None):
        self.context = context
        self.adapter = None
        self.showing = False

    def setAdapter(self, value):
        self.adapter = value
        return None

    def getAdapter(self):
        return self.adapter

    def setAnchorView(self, value):
        return None

    def setWidth(self, value):
        return None

    def setHeight(self, value):
        return None

    def setModal(self, value):
        return None

    def setOnItemClickListener(self, value):
        return None

    def setOnItemSelectedListener(self, value):
        return None

    def setPromptView(self, value):
        return None

    def setVerticalOffset(self, value):
        return None

    def setHorizontalOffset(self, value):
        return None

    def show(self):
        self.showing = True
        return None

    def dismiss(self):
        self.showing = False
        return None

    def isShowing(self):
        return self.showing

    def setSelection(self, value):
        return None

    def getSelectedItem(self):
        return None

    def getSelectedItemPosition(self):
        return -1

    def getListView(self):
        return None


class MotionEvent:
    ACTION_DOWN = 0
    ACTION_UP = 1
    ACTION_MOVE = 2
    ACTION_CANCEL = 3
    ACTION_POINTER_DOWN = 5
    ACTION_POINTER_UP = 6
    ACTION_MASK = 0xFF

    def __init__(self):
        self._x = 0.0
        self._y = 0.0
        self._action = 0
        self._event_time = 0
        self._down_time = 0

    @staticmethod
    def obtain(*args):
        return MotionEvent()

    def getX(self, index=0):
        return self._x

    def getY(self, index=0):
        return self._y

    def getRawX(self):
        return self._x

    def getRawY(self):
        return self._y

    def getAction(self):
        return self._action

    def getActionMasked(self):
        return self._action & 0xFF

    def setAction(self, value):
        self._action = int(value or 0)
        return None

    def getPointerCount(self):
        return 1

    def getPointerId(self, index=0):
        return 0

    def getEventTime(self):
        return self._event_time

    def getDownTime(self):
        return self._down_time

    def getPressure(self, index=0):
        return 1.0

    def getSize(self, index=0):
        return 1.0

    def getHistorySize(self):
        return 0

    def getHistoricalX(self, *args):
        return self._x

    def getHistoricalY(self, *args):
        return self._y

    def recycle(self):
        return None


class KeyEvent:
    ACTION_DOWN = 0
    ACTION_UP = 1
    KEYCODE_BACK = 4
    KEYCODE_ENTER = 66
    KEYCODE_DPAD_UP = 19
    KEYCODE_DPAD_DOWN = 20
    KEYCODE_DPAD_LEFT = 21
    KEYCODE_DPAD_RIGHT = 22
    KEYCODE_DEL = 67
    KEYCODE_MENU = 82
    KEYCODE_SEARCH = 84
    KEYCODE_VOLUME_UP = 24
    KEYCODE_VOLUME_DOWN = 25

    def __init__(self, action=0, code=0):
        self._action = int(action or 0)
        self._code = int(code or 0)

    def getAction(self):
        return self._action

    def getKeyCode(self):
        return self._code

    def getUnicodeChar(self, *args):
        return 0

    def isCtrlPressed(self):
        return False

    def isShiftPressed(self):
        return False

    def isAltPressed(self):
        return False

    def getRepeatCount(self):
        return 0

    def getEventTime(self):
        return 0


class GestureDetector:
    def __init__(self, context=None, listener=None):
        self.context = context
        self.listener = listener
        self.double_tap_listener = None
        self.longpress_enabled = True

    class SimpleOnGestureListener:
        def onDown(self, event=None):
            return False

        def onShowPress(self, event=None):
            return None

        def onSingleTapUp(self, event=None):
            return False

        def onScroll(self, *args):
            return False

        def onLongPress(self, event=None):
            return None

        def onFling(self, *args):
            return False

        def onSingleTapConfirmed(self, event=None):
            return False

        def onDoubleTap(self, event=None):
            return False

        def onDoubleTapEvent(self, event=None):
            return False

        def onContextClick(self, event=None):
            return False

    def setOnDoubleTapListener(self, value):
        self.double_tap_listener = value
        return None

    def setLongpressEnabled(self, value):
        self.longpress_enabled = bool(value)
        return None

    def isLongpressEnabled(self):
        return self.longpress_enabled

    def onTouchEvent(self, event=None):
        return False


class ScaleGestureDetector:
    def __init__(self, context=None, listener=None):
        self.context = context
        self.listener = listener

    def getScaleFactor(self):
        return 1.0

    def getFocusX(self):
        return 0.0

    def getFocusY(self):
        return 0.0

    def isInProgress(self):
        return False

    def onTouchEvent(self, event=None):
        return False

    def setQuickScaleEnabled(self, value):
        return None

    def isQuickScaleEnabled(self):
        return False


class Spinner(View):
    def setAdapter(self, adapter):
        self.adapter = adapter

    def setSelection(self, index):
        self.selection = index

    def getSelectedItem(self):
        return None

    def setOnItemSelectedListener(self, listener):
        return None


class HorizontalScrollView(ScrollView):
    pass


class Toolbar(ViewGroup):
    def setTitle(self, value):
        self.title = value

    def setSubtitle(self, value):
        self.subtitle = value

    def setNavigationOnClickListener(self, listener):
        self._navClick = listener


class EditTextBoldCursor(EditText):
    def getText(self):
        return _TextValue(self.text)

    def setText(self, value, *args, **kwargs):
        super().setText(value)

    def setHintTextColor(self, color):
        self.hintTextColor = color

    def setBackground(self, drawable):
        self.background = drawable

    def setCursorColor(self, color):
        self.cursorColor = color

    def setCursorWidth(self, width):
        self.cursorWidth = float(width)

    def setContentDescription(self, value):
        self.contentDescription = value

    def setPadding(self, *args):
        return None


class OutlineTextContainerView(LinearLayout):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context, *args, **kwargs)
        self.text = ""
        self.editText = None

    def setText(self, value):
        self.text = "" if value is None else str(value)

    def addView(self, view, *args, **kwargs):
        super().addView(view, *args, **kwargs)
        if isinstance(view, EditText):
            self.editText = view

    def attachEditText(self, edit):
        self.editText = edit

    def animateSelection(self, *args, **kwargs):
        return None

    def animateError(self, *args, **kwargs):
        return None


class RLottieImageView(ImageView):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context, *args, **kwargs)
        self.animation = None

    def setAnimation(self, resource, width=0, height=0):
        self.animation = resource

    def playAnimation(self):
        return None

    def setAutoRepeat(self, value):
        return None


class ButtonWithCounterView(LinearLayout):
    def __init__(self, context=None, blurred=False, resourcesProvider=None, *args, **kwargs):
        super().__init__(context, *args, **kwargs)
        self.text = ""
        self.round = False
        self.counter = 0

    def setRound(self):
        self.round = True

    def setText(self, text, animated=True):
        self.text = "" if text is None else str(text)

    def setCounter(self, value):
        self.counter = int(value)


class RecyclerView(ViewGroup):
    class LayoutManager:
        pass

    class Adapter:
        def notifyDataSetChanged(self):
            return None

        def notifyItemChanged(self, position):
            return None

        def notifyItemInserted(self, position):
            return None

        def notifyItemRemoved(self, position):
            return None

        def notifyItemRangeChanged(self, *args):
            return None

        def getItemCount(self):
            return 0

    class ItemAnimator:
        def setSupportsChangeAnimations(self, value):
            return None

        def setAddDuration(self, value):
            return None

        def setRemoveDuration(self, value):
            return None

        def setMoveDuration(self, value):
            return None

        def setChangeDuration(self, value):
            return None

    class ItemDecoration:
        pass

    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context, *args, **kwargs)
        self.adapter = None
        self.layoutManager = None
        self.itemAnimator = None

    def setLayoutManager(self, manager):
        self.layoutManager = manager

    def getLayoutManager(self):
        return self.layoutManager

    def setAdapter(self, adapter):
        self.adapter = adapter

    def getAdapter(self):
        return self.adapter

    def setItemAnimator(self, animator):
        self.itemAnimator = animator

    def getItemAnimator(self):
        return self.itemAnimator

    def addItemDecoration(self, decoration, index=None):
        return None

    def removeItemDecoration(self, decoration):
        return None

    def setHasFixedSize(self, value):
        return None

    def setNestedScrollingEnabled(self, value):
        return None

    def setClipToPadding(self, value):
        return None

    def scrollToPosition(self, position):
        return None

    def smoothScrollToPosition(self, position):
        return None

    def stopScroll(self):
        return None

    def swapAdapter(self, adapter, remove_and_recycle):
        self.adapter = adapter

    def setItemViewCacheSize(self, size):
        return None

    def setDrawingCacheEnabled(self, value):
        return None

    def setFocusable(self, value):
        return None


class LinearLayoutManager:
    HORIZONTAL = 0
    VERTICAL = 1

    def __init__(self, context=None, orientation=1, reverse=False):
        self.context = context
        self.orientation = orientation
        self.reverse = reverse

    def setOrientation(self, value):
        self.orientation = value

    def getOrientation(self):
        return self.orientation

    def setReverseLayout(self, value):
        self.reverse = value

    def scrollToPosition(self, position):
        return None

    def scrollToPositionWithOffset(self, position, offset):
        return None

    def findFirstVisibleItemPosition(self):
        return -1

    def findLastVisibleItemPosition(self):
        return -1

    def findFirstCompletelyVisibleItemPosition(self):
        return -1

    def findLastCompletelyVisibleItemPosition(self):
        return -1

    def setStackFromEnd(self, value):
        return None

    def setSmoothScrollbarEnabled(self, value):
        return None


class GridLayoutManager(LinearLayoutManager):
    def __init__(self, context=None, span_count=2, orientation=1, reverse=False):
        super().__init__(context, orientation, reverse)
        self.spanCount = span_count

    def setSpanCount(self, value):
        self.spanCount = value

    def getSpanCount(self):
        return self.spanCount


class DrawableCompat:
    @staticmethod
    def setTint(drawable, color):
        if hasattr(drawable, "setTint"):
            drawable.setTint(color)
        return None

    @staticmethod
    def setTintList(drawable, tint):
        return None

    @staticmethod
    def wrap(drawable):
        return drawable

    @staticmethod
    def unwrap(drawable):
        return drawable


class ViewCompat:
    @staticmethod
    def setBackgroundTintList(view, tint):
        return None

    @staticmethod
    def setElevation(view, value):
        return None

    @staticmethod
    def setTranslationZ(view, value):
        return None

    @staticmethod
    def isAttachedToWindow(view):
        return True

    @staticmethod
    def setImportantForAccessibility(view, value):
        return None


class ViewPager(ViewGroup):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context, *args, **kwargs)
        self.adapter = None
        self.currentItem = 0

    def setAdapter(self, adapter):
        self.adapter = adapter

    def getAdapter(self):
        return self.adapter

    def setCurrentItem(self, item, smooth=True):
        self.currentItem = int(item)

    def getCurrentItem(self):
        return self.currentItem

    def setOffscreenPageLimit(self, value):
        return None

    def addOnPageChangeListener(self, listener):
        return None

    def setPageTransformer(self, reverse, transformer):
        return None


class MediaActionDrawable:
    ICON_DELETE = 0
    ICON_DOWNLOAD = 1
    ICON_CANCEL = 2
    ICON_PLAY = 3
    ICON_PAUSE = 4
    ICON_FILE = 5
    ICON_STOP = 6
    ICON_RELOAD = 7
    ICON_CHECK = 8
    ICON_UNDO = 9

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.ui.Components.MediaActionDrawable")

    def setIcon(self, icon, animated=True):
        self.icon = icon

    def setColor(self, color):
        self.color = color

    def setProgress(self, value, animated=True):
        self.progress = value

    def setDelegate(self, delegate):
        self.delegate = delegate


class RLottieDrawable:
    def __init__(self, *args, **kwargs):
        self.currentFrame = 0
        self.duration = 0
        self.playing = False

    def setCurrentFrame(self, frame, notify=True):
        self.currentFrame = int(frame)

    def start(self):
        self.playing = True

    def stop(self):
        self.playing = False

    def setAllowDecodeSingleFrame(self, value):
        return None

    def setAutoRepeat(self, value):
        return None

    def setOnAnimationEndListener(self, listener):
        self.endListener = listener

    def getDuration(self):
        return self.duration

    def recycle(self):
        return None

    def setColorFilter(self, *args):
        return None


class UniversalAdapter:
    def __init__(self, *args, **kwargs):
        self.items = []

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.ui.Components.UniversalAdapter")

    def getItem(self, position):
        return self.items[position] if 0 <= position < len(self.items) else None

    def getItemCount(self):
        return len(self.items)

    def notifyDataSetChanged(self):
        return None

    def update(self, animated=True):
        return None

    def setItems(self, items):
        self.items = list(items or [])


class BaseFragment:
    def __init__(self, *args, **kwargs):
        self.arguments = None

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.ui.ActionBar.BaseFragment")

    def getParentActivity(self):
        return None

    def getContext(self):
        return None

    def presentFragment(self, fragment, *args, **kwargs):
        return None

    def removeSelfFromStack(self):
        return None

    def getMessagesController(self):
        from org.telegram.messenger import MessagesController

        return MessagesController.getInstance(0)

    def getAccountInstance(self):
        from org.telegram.messenger import AccountInstance

        return AccountInstance.getInstance(0)

    def getUserConfig(self):
        from org.telegram.messenger import UserConfig

        return UserConfig.getInstance(0)

    def getConnectionsManager(self):
        from org.telegram.messenger import ConnectionsManager

        return ConnectionsManager.getInstance(0)

    def finishFragment(self):
        return None


class SvgHelper:
    class SvgDrawable:
        def __init__(self, data=None, *args, **kwargs):
            self.data = data
            self.bounds = (0, 0, 0, 0)
            self.alpha = 255

        def setBounds(self, *args):
            if len(args) == 4:
                self.bounds = tuple(int(value) for value in args)

        def getBounds(self):
            return self.bounds

        def setAlpha(self, value):
            self.alpha = value

        def mutate(self):
            return self

    @staticmethod
    def getSvg(width, height, path, *args, **kwargs):
        return None

    @staticmethod
    def getSvgFromBytes(data, *args, **kwargs):
        return None

    @staticmethod
    def getDrawable(data, *args, **kwargs):
        return SvgHelper.SvgDrawable(data)

    @staticmethod
    def getBitmap(data, width=0, height=0, color=None, *args, **kwargs):
        try:
            return Bitmap(
                data if isinstance(data, (bytes, bytearray)) else b"", width, height
            )
        except Exception:
            return None


class LayoutParams:
    MATCH_PARENT = -1
    WRAP_CONTENT = -2

    def __init__(self, width=MATCH_PARENT, height=WRAP_CONTENT, weight=0.0):
        self.width = width
        self.height = height
        self.weight = float(weight or 0.0)
        self.gravity = 0
        self.margins = (0, 0, 0, 0)

    def setMargins(self, left, top, right, bottom):
        self.margins = (int(left), int(top), int(right), int(bottom))


# Android exposes these as nested classes (`LinearLayout.LayoutParams`, ...).
for _layout_class in (
    LinearLayout,
    FrameLayout,
    ScrollView,
    HorizontalScrollView,
    RelativeLayout,
    Toolbar,
):
    _layout_class.LayoutParams = LayoutParams
    _layout_class.MarginLayoutParams = LayoutParams
del _layout_class


class Drawable:
    def __init__(self, *args, **kwargs):
        self.bounds = (0, 0, 0, 0)
        self.alpha = 255
        self.colorFilter = None

    @classmethod
    def getClass(cls):
        return _java_class_ref("android.graphics.drawable.Drawable")

    @staticmethod
    def createFromPath(path, *args, **kwargs):
        drawable = Drawable()
        drawable.path = str(path)
        return drawable

    @staticmethod
    def createFromStream(stream, name=None, *args, **kwargs):
        drawable = Drawable()
        drawable.stream = stream
        drawable.name = name
        return drawable

    def setBounds(self, *args):
        if len(args) == 4:
            self.bounds = tuple(int(value) for value in args)

    def getBounds(self):
        return self.bounds

    def setAlpha(self, value):
        self.alpha = value

    def setColorFilter(self, *args, **kwargs):
        return None

    def mutate(self):
        return self

    def invalidateSelf(self):
        return None


class BitmapDrawable(Drawable):
    def __init__(self, bitmap=None, *args, **kwargs):
        super().__init__()
        self.bitmap = bitmap


class ColorDrawable(Drawable):
    def __init__(self, color=0, *args, **kwargs):
        super().__init__()
        self.color = color

    def setColor(self, color):
        self.color = color


class GradientDrawable(Drawable):
    RECTANGLE = 0
    OVAL = 1
    LINE = 2
    RING = 3
    TOP_BOTTOM = 1
    TR_BL = 2
    BR_TL = 3
    BOTTOM_TOP = 4
    BL_TR = 5
    TL_BR = 6
    LEFT_RIGHT = 7
    RIGHT_LEFT = 8
    LINEAR_GRADIENT = 0
    RADIAL_GRADIENT = 1
    SWEEP_GRADIENT = 2

    def __init__(self):
        super().__init__()
        self.color = 0
        self.cornerRadius = 0.0
        self.cornerRadii = [0.0] * 8
        self.colors = []
        self.strokeWidth = 0
        self.strokeColor = 0
        self.gradientType = 0
        self.orientation = 0
        self.shape = 0
        self.size = (0, 0)
        self.tint = None
        self.tintList = None

    def setColor(self, color):
        self.color = color

    def setCornerRadius(self, value):
        self.cornerRadius = float(value)

    def setCornerRadii(self, values):
        self.cornerRadii = [float(value) for value in (values or [])]
        return None

    def setStroke(self, width, color=None, dash_width=0, dash_gap=0):
        self.strokeWidth = int(width or 0)
        self.strokeColor = int(color or 0)
        return None

    def setShape(self, value):
        self.shape = value
        return None

    def setGradientType(self, value):
        self.gradientType = value
        return None

    def setOrientation(self, value):
        self.orientation = value
        return None

    def setColors(self, value):
        self.colors = list(value or [])
        return None

    def setSize(self, width, height):
        self.size = (int(width), int(height))
        return None

    def setTint(self, color):
        self.tint = color
        return None

    def setTintList(self, value):
        self.tintList = value
        return None

    def getConstantState(self):
        return self

    def mutate(self):
        return self


class StateListDrawable(Drawable):
    def __init__(self):
        super().__init__()
        self._states = []
        self._current = []

    def addState(self, state_set, drawable):
        self._states.append((list(state_set or []), drawable))
        return None

    def getStateCount(self):
        return len(self._states)

    def getStateDrawable(self, index):
        try:
            return self._states[int(index)][1]
        except (IndexError, TypeError, ValueError):
            return None

    def setState(self, state):
        self._current = list(state or [])
        return True

    def setEnterFadeDuration(self, value):
        return None

    def setExitFadeDuration(self, value):
        return None


class LayerDrawable(Drawable):
    def __init__(self, drawables=None):
        super().__init__()
        self._layers = list(drawables or [])

    def getNumberOfLayers(self):
        return len(self._layers)

    def getDrawable(self, index):
        try:
            return self._layers[int(index)]
        except (IndexError, TypeError, ValueError):
            return None

    def setDrawable(self, index, drawable):
        try:
            self._layers[int(index)] = drawable
        except (IndexError, TypeError, ValueError):
            pass
        return None

    def setLayerInset(self, *args):
        return None

    def setLayerGravity(self, *args):
        return None

    def setPadding(self, *args):
        return None


class RippleDrawable(LayerDrawable):
    def __init__(self, color=None, content=None, mask=None):
        super().__init__([item for item in (content, mask) if item is not None])
        self.color = color
        self.radius = 0

    def setColor(self, color):
        self.color = color
        return None

    def setRadius(self, radius):
        self.radius = int(radius or 0)
        return None


class InsetDrawable(Drawable):
    def __init__(self, drawable=None, inset=0, *args, **kwargs):
        super().__init__()
        self.drawable = drawable
        self.inset = inset

    def getDrawable(self):
        return self.drawable


class ClipDrawable(Drawable):
    HORIZONTAL = 1
    VERTICAL = 2

    def __init__(self, drawable=None, gravity=0, orientation=1):
        super().__init__()
        self.drawable = drawable
        self.gravity = gravity
        self.orientation = orientation
        self.level = 0

    def setLevel(self, level):
        self.level = int(level or 0)
        return None


class PaintDrawable(Drawable):
    def __init__(self, color=0):
        super().__init__()
        self.color = int(color or 0)
        self.cornerRadius = 0.0
        self.cornerRadii = [0.0] * 8

    def setColor(self, color):
        self.color = color
        return None

    def setCornerRadius(self, radius):
        self.cornerRadius = float(radius)
        return None

    def setCornerRadii(self, values):
        self.cornerRadii = [float(value) for value in (values or [])]
        return None


class Paint:
    ANTI_ALIAS_FLAG = 1
    STYLE_FILL = 0
    STYLE_STROKE = 1
    STYLE_FILL_AND_STROKE = 2
    Align = type("Align", (), {"LEFT": 0, "CENTER": 1, "RIGHT": 2})
    Cap = type("Cap", (), {"BUTT": 0, "ROUND": 1, "SQUARE": 2})
    Join = type("Join", (), {"MITER": 0, "ROUND": 1, "BEVEL": 2})
    Style = type("Style", (), {"FILL": 0, "STROKE": 1, "FILL_AND_STROKE": 2})

    class FontMetrics:
        def __init__(self):
            self.top = 0.0
            self.ascent = 0.0
            self.descent = 0.0
            self.bottom = 0.0
            self.leading = 0.0

    def __init__(self, flags=0):
        self.flags = flags
        self.color = 0xFF000000
        self.strokeWidth = 0.0
        self.style = Paint.STYLE_FILL
        self.textSize = 14.0
        self.typeface = None
        self.shader = None
        self.alpha = 255
        self.strokeCap = Paint.Cap.BUTT
        self.strokeJoin = Paint.Join.MITER
        self.pathEffect = None
        self.textAlign = Paint.Align.LEFT
        self.colorFilter = None
        self.antiAlias = bool(flags & Paint.ANTI_ALIAS_FLAG)

    def setColor(self, color):
        self.color = color

    def getColor(self):
        return self.color

    def setStrokeWidth(self, width):
        self.strokeWidth = float(width)

    def getStrokeWidth(self):
        return self.strokeWidth

    def setStyle(self, style):
        self.style = style

    def getStyle(self):
        return self.style

    def setTextSize(self, size):
        self.textSize = float(size)

    def getTextSize(self):
        return self.textSize

    def setTypeface(self, typeface):
        self.typeface = typeface

    def getTypeface(self):
        return self.typeface

    def setAntiAlias(self, value):
        self.antiAlias = bool(value)

    def setShader(self, shader):
        self.shader = shader

    def setAlpha(self, alpha):
        self.alpha = int(alpha)

    def setStrokeCap(self, cap):
        self.strokeCap = cap

    def setStrokeJoin(self, join):
        self.strokeJoin = join

    def setPathEffect(self, effect):
        self.pathEffect = effect

    def setTextAlign(self, align):
        self.textAlign = align

    def setColorFilter(self, filter):
        self.colorFilter = filter

    def setDither(self, value):
        return None

    def setFlags(self, flags):
        self.flags = flags

    def measureText(self, text):
        return len(str(text or "")) * self.textSize * 0.55

    def getTextBounds(self, text, start, end, bounds=None):
        width = self.measureText(text)
        if bounds is not None:
            bounds.set(0, 0, int(width), int(self.textSize))
        return bounds

    def getFontMetrics(self, metrics=None):
        value = metrics or Paint.FontMetrics()
        value.ascent = -self.textSize * 0.8
        value.descent = self.textSize * 0.2
        value.top = -self.textSize
        value.bottom = self.textSize * 0.3
        return value

    def reset(self):
        self.__init__()


class TextPaint(Paint):
    def __init__(self, flags=0):
        super().__init__(flags)
        self.bgColor = 0
        self.baselineShift = 0
        self.linkColor = 0
        self.drawableState = []
        self.density = 1.0
        self.underlineColor = 0
        self.underlineThickness = 0.0

    def set(self, paint):
        return None


class Layout:
    Alignment = type(
        "Alignment",
        (),
        {"ALIGN_NORMAL": 0, "ALIGN_CENTER": 1, "ALIGN_OPPOSITE": 2},
    )

    def __init__(self, text="", paint=None, width=0, alignment=0):
        self._text = str(text or "")
        self._paint = paint
        self._width = int(width or 0)
        self._alignment = alignment

    def getWidth(self):
        return self._width

    def getHeight(self):
        return max(1, len(self._text.splitlines())) * 20

    def getLineCount(self):
        return max(1, len(self._text.splitlines()))

    def getLineTop(self, line):
        return int(line) * 20

    def getLineBottom(self, line):
        return (int(line) + 1) * 20

    def getLineBaseline(self, line):
        return max(0, (int(line) + 1) * 20 - 4)

    def getPrimaryHorizontal(self, offset):
        return float(offset) * 7.0

    def getSecondaryHorizontal(self, offset):
        return float(offset) * 7.0

    def getEllipsisCount(self, line):
        return 0

    def getText(self):
        return self._text

    def getPaint(self):
        return self._paint

    def draw(self, canvas):
        return None


class StaticLayout(Layout):
    def __init__(self, text="", paint=None, width=0, alignment=0,
                 spacingmult=1.0, spacingadd=0.0, includepad=True, *args,
                 **kwargs):
        super().__init__(text, paint, width, alignment)


class DynamicLayout(StaticLayout):
    pass


class Canvas:
    def __init__(self, bitmap=None):
        self.bitmap = bitmap
        self.width = 1080
        self.height = 1920
        self._saveCount = 0

    def drawColor(self, *args):
        return None

    def drawARGB(self, *args):
        return None

    def drawRect(self, *args):
        return None

    def drawRoundRect(self, *args):
        return None

    def drawCircle(self, *args):
        return None

    def drawLine(self, *args):
        return None

    def drawPath(self, *args):
        return None

    def drawText(self, *args):
        return None

    def drawBitmap(self, *args):
        return None

    def drawDrawable(self, *args):
        return None

    def save(self):
        self._saveCount += 1
        return self._saveCount

    def restore(self):
        if self._saveCount > 0:
            self._saveCount -= 1
        return None

    def restoreToCount(self, count):
        self._saveCount = int(count)

    def translate(self, *args):
        return None

    def scale(self, *args):
        return None

    def rotate(self, *args):
        return None

    def clipRect(self, *args):
        return None

    def clipPath(self, *args):
        return None

    def getWidth(self):
        return self.width

    def getHeight(self):
        return self.height

    def setBitmap(self, bitmap):
        self.bitmap = bitmap


class Path:
    FILL_TYPE_WINDING = 0
    FILL_TYPE_EVEN_ODD = 1

    def __init__(self):
        self.commands = []
        self.fillType = Path.FILL_TYPE_WINDING

    def moveTo(self, x, y):
        self.commands.append(("M", x, y))

    def lineTo(self, x, y):
        self.commands.append(("L", x, y))

    def quadTo(self, x1, y1, x2, y2):
        self.commands.append(("Q", x1, y1, x2, y2))

    def cubicTo(self, x1, y1, x2, y2, x3, y3):
        self.commands.append(("C", x1, y1, x2, y2, x3, y3))

    def close(self):
        self.commands.append(("Z",))

    def reset(self):
        self.commands.clear()

    def rewind(self):
        self.commands.clear()

    def addRoundRect(self, *args):
        return None

    def addCircle(self, *args):
        return None

    def addRect(self, *args):
        return None

    def setFillType(self, value):
        self.fillType = value

    def isEmpty(self):
        return not self.commands


class PathMeasure:
    def __init__(self, path=None, forceClosed=False):
        self._path = path
        self._force_closed = bool(forceClosed)

    def setPath(self, path, forceClosed=False):
        self._path = path
        self._force_closed = bool(forceClosed)
        return None

    def _points(self):
        points = []
        for command in getattr(self._path, "commands", []) if self._path else []:
            if command[0] in ("M", "L"):
                points.append((float(command[1]), float(command[2])))
        return points

    def getLength(self):
        import math

        points = self._points()
        length = 0.0
        for index in range(1, len(points)):
            length += math.dist(points[index - 1], points[index])
        if self._force_closed and len(points) > 1:
            length += math.dist(points[-1], points[0])
        return length

    def getPosTan(self, distance, pos=None, tan=None):
        import math

        points = self._points()
        if not points:
            if pos is not None:
                pos[0], pos[1] = 0.0, 0.0
            if tan is not None:
                tan[0], tan[1] = 1.0, 0.0
            return False
        remaining = max(0.0, float(distance or 0.0))
        x, y = points[0]
        dx, dy = 1.0, 0.0
        for index in range(1, len(points)):
            start = points[index - 1]
            end = points[index]
            segment = math.dist(start, end)
            if remaining <= segment or index == len(points) - 1:
                fraction = 0.0 if segment == 0 else min(1.0, remaining / segment)
                x = start[0] + (end[0] - start[0]) * fraction
                y = start[1] + (end[1] - start[1]) * fraction
                length = segment or 1.0
                dx = (end[0] - start[0]) / length
                dy = (end[1] - start[1]) / length
                break
            remaining -= segment
        if pos is not None:
            pos[0], pos[1] = x, y
        if tan is not None:
            tan[0], tan[1] = dx, dy
        return True

    def getSegment(self, start, stop, dst=None, startWithMoveTo=True):
        if dst is None or self._path is None:
            return False
        for command in getattr(self._path, "commands", []):
            dst.commands.append(command)
        return True

    def nextContour(self):
        return False

    def isClosed(self):
        return self._force_closed


class PathParser:
    @staticmethod
    def createPathFromPathData(data):
        path = Path()
        text = str(data or "").strip()
        if not text:
            return path
        import re

        tokens = re.findall(r"[MLQCZmlqcz]|-?\d+(?:\.\d+)?", text)
        index = 0
        command = None
        while index < len(tokens):
            token = tokens[index]
            if token.upper() in ("M", "L", "Q", "C", "Z"):
                command = token
                index += 1
                if command.upper() == "Z":
                    path.close()
                continue
            try:
                if command and command.upper() == "M" and index + 1 < len(tokens):
                    path.moveTo(float(tokens[index]), float(tokens[index + 1]))
                    index += 2
                elif command and command.upper() == "L" and index + 1 < len(tokens):
                    path.lineTo(float(tokens[index]), float(tokens[index + 1]))
                    index += 2
                elif command and command.upper() == "Q" and index + 3 < len(tokens):
                    path.quadTo(
                        float(tokens[index]),
                        float(tokens[index + 1]),
                        float(tokens[index + 2]),
                        float(tokens[index + 3]),
                    )
                    index += 4
                elif command and command.upper() == "C" and index + 5 < len(tokens):
                    path.cubicTo(
                        float(tokens[index]),
                        float(tokens[index + 1]),
                        float(tokens[index + 2]),
                        float(tokens[index + 3]),
                        float(tokens[index + 4]),
                        float(tokens[index + 5]),
                    )
                    index += 6
                else:
                    index += 1
            except (TypeError, ValueError):
                index += 1
        return path

    @staticmethod
    def canMorph(first, second):
        return str(first or "") == str(second or "")

    @staticmethod
    def interpolatePathData(first, second, fraction):
        return first if float(fraction or 0) < 0.5 else second


class Rect:
    def __init__(self, left=0, top=0, right=0, bottom=0):
        self.left = int(left)
        self.top = int(top)
        self.right = int(right)
        self.bottom = int(bottom)

    def set(self, left, top, right, bottom):
        self.left = int(left)
        self.top = int(top)
        self.right = int(right)
        self.bottom = int(bottom)

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top

    def centerX(self):
        return (self.left + self.right) // 2

    def centerY(self):
        return (self.top + self.bottom) // 2

    def inset(self, dx, dy):
        self.left += dx
        self.top += dy
        self.right -= dx
        self.bottom -= dy

    def contains(self, x, y):
        return self.left <= x < self.right and self.top <= y < self.bottom


class RectF:
    def __init__(self, left=0.0, top=0.0, right=0.0, bottom=0.0):
        self.left = float(left)
        self.top = float(top)
        self.right = float(right)
        self.bottom = float(bottom)

    def set(self, left, top, right, bottom):
        self.left = float(left)
        self.top = float(top)
        self.right = float(right)
        self.bottom = float(bottom)

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top

    def centerX(self):
        return (self.left + self.right) / 2.0

    def centerY(self):
        return (self.top + self.bottom) / 2.0

    def inset(self, dx, dy):
        self.left += dx
        self.top += dy
        self.right -= dx
        self.bottom -= dy

    def contains(self, x, y):
        return self.left <= x < self.right and self.top <= y < self.bottom


class Matrix:
    def __init__(self):
        self.values = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    def reset(self):
        self.values = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    def setTranslate(self, x, y):
        self.values = [1.0, 0.0, x, 0.0, 1.0, y, 0.0, 0.0, 1.0]

    def postTranslate(self, x, y):
        self.values[2] += x
        self.values[5] += y

    def setScale(self, sx, sy):
        self.values = [sx, 0.0, 0.0, 0.0, sy, 0.0, 0.0, 0.0, 1.0]

    def postScale(self, sx, sy):
        self.values[0] *= sx
        self.values[4] *= sy

    def mapRect(self, rect):
        return rect

    def mapPoints(self, points):
        return points


class Xfermode:
    pass


class PorterDuff:
    class Mode:
        CLEAR = 0
        SRC = 1
        DST = 2
        SRC_OVER = 3
        DST_OVER = 4
        SRC_IN = 5
        DST_IN = 6
        SRC_OUT = 7
        DST_OUT = 8
        SRC_ATOP = 9
        DST_ATOP = 10
        XOR = 11
        DARKEN = 12
        LIGHTEN = 13
        MULTIPLY = 14
        SCREEN = 15
        ADD = 16
        OVERLAY = 17


class PorterDuffXfermode(Xfermode):
    def __init__(self, mode=None):
        self.mode = mode


class ColorFilter:
    pass


class PorterDuffColorFilter(ColorFilter):
    def __init__(self, color=0, mode=None):
        self.color = color
        self.mode = mode


class LightingColorFilter(ColorFilter):
    def __init__(self, multiply=0, add=0):
        self.multiply = multiply
        self.add = add


class Shader:
    class TileMode:
        CLAMP = 0
        REPEAT = 1
        MIRROR = 2


class LinearGradient(Shader):
    def __init__(self, *args, **kwargs):
        self.args = args


class RadialGradient(Shader):
    def __init__(self, *args, **kwargs):
        self.args = args


class BitmapShader(Shader):
    def __init__(self, bitmap=None, tileX=0, tileY=0):
        self.bitmap = bitmap
        self.tileX = tileX
        self.tileY = tileY


class ComposeShader(Shader):
    def __init__(self, *args, **kwargs):
        self.args = args


class SweepGradient(Shader):
    def __init__(self, *args, **kwargs):
        self.args = args


class PathEffect:
    pass


class DashPathEffect(PathEffect):
    def __init__(self, intervals=None, phase=0):
        self.intervals = list(intervals or [])
        self.phase = float(phase or 0)


class CornerPathEffect(PathEffect):
    def __init__(self, radius=0):
        self.radius = float(radius or 0)


class ComposePathEffect(PathEffect):
    def __init__(self, outer=None, inner=None):
        self.outer = outer
        self.inner = inner


class SumPathEffect(PathEffect):
    def __init__(self, first=None, second=None):
        self.first = first
        self.second = second


class ColorMatrix:
    def __init__(self, values=None):
        self.values = [float(value) for value in (values or [])] or [
            1.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 1.0, 0.0,
        ]

    def set(self, values):
        self.values = [float(value) for value in (values or [])]
        return None

    def getArray(self):
        return list(self.values)

    def setSaturation(self, value):
        return None

    def setScale(self, r, g, b, a):
        return None

    def setRotate(self, axis, degrees):
        return None

    def reset(self):
        return None

    def postConcat(self, other):
        return None

    def setConcat(self, first, second):
        return None


class ColorMatrixColorFilter(ColorFilter):
    def __init__(self, matrix=None):
        self.matrix = matrix
        self.values = matrix.getArray() if hasattr(matrix, "getArray") else []


class PixelFormat:
    UNKNOWN = 0
    RGBA_8888 = 1
    RGBX_8888 = 2
    RGB_888 = 3
    RGB_565 = 4
    RGBA_5551 = 6
    RGBA_4444 = 7
    A_8 = 8
    L_8 = 9
    LA_88 = 0xA
    RGB_332 = 0xB
    YCbCr_422_SP = 0x10
    YCbCr_420_SP = 0x11
    TRANSLUCENT = -3
    OPAQUE = -1


class ImageFormat:
    UNKNOWN = 0
    RGB_565 = 4
    YV12 = 0x32315659
    NV16 = 0x10
    NV21 = 0x11
    YUY2 = 0x32595559
    JPEG = 0x100
    DEPTH_16 = 0x30
    DEPTH_POINT_CLOUD = 0x31


class BlendMode:
    CLEAR = 0
    SRC = 1
    DST = 2
    SRC_OVER = 3
    DST_OVER = 4
    SRC_IN = 5
    DST_IN = 6
    SRC_OUT = 7
    DST_OUT = 8
    SRC_ATOP = 9
    DST_ATOP = 10
    XOR = 11
    PLUS = 12
    MODULATE = 13
    SCREEN = 14
    OVERLAY = 15
    DARKEN = 16
    LIGHTEN = 17
    COLOR_DODGE = 18
    COLOR_BURN = 19
    HARD_LIGHT = 20
    SOFT_LIGHT = 21
    DIFFERENCE = 22
    EXCLUSION = 23
    MULTIPLY = 24
    HUE = 25
    SATURATION = 26
    COLOR = 27
    LUMINOSITY = 28


class Gravity:
    NO_GRAVITY = 0
    TOP = 0x30
    BOTTOM = 0x50
    LEFT = 0x03
    RIGHT = 0x05
    CENTER_VERTICAL = 0x10
    CENTER_HORIZONTAL = 0x01
    CENTER = 0x11
    CENTER_IN_PARENT = 0x11
    START = 0x00800003
    END = 0x00800005


class InputType:
    TYPE_CLASS_TEXT = 0x00000001
    TYPE_TEXT_FLAG_MULTI_LINE = 0x00020000
    TYPE_TEXT_FLAG_CAP_SENTENCES = 0x00004000
    TYPE_TEXT_VARIATION_URI = 0x00000010
    TYPE_TEXT_VARIATION_EMAIL_ADDRESS = 0x00000020
    TYPE_TEXT_VARIATION_PASSWORD = 0x00000080
    TYPE_NUMBER_VARIATION_PASSWORD = 0x00000010
    TYPE_CLASS_NUMBER = 0x00000002
    TYPE_CLASS_PHONE = 0x00000003
    TYPE_NULL = 0


class HapticFeedbackConstants:
    LONG_PRESS = 0
    VIRTUAL_KEY = 1
    KEYBOARD_TAP = 3
    CLOCK_TICK = 4
    CONTEXT_CLICK = 6
    GESTURE_START = 8
    GESTURE_END = 9
    FLAG_IGNORE_GLOBAL_SETTING = 1
    FLAG_IGNORE_VIEW_SETTING = 2


class EditorInfo:
    IME_ACTION_DONE = 6
    IME_ACTION_GO = 2
    IME_ACTION_NEXT = 5
    IME_ACTION_SEARCH = 3
    IME_ACTION_SEND = 4
    IME_FLAG_NO_EXTRACT_UI = 0x10000000
    IME_FLAG_NO_ENTER_ACTION = 0x40000000


class TextWatcher:
    def beforeTextChanged(self, *args):
        pass

    def onTextChanged(self, *args):
        pass

    def afterTextChanged(self, *args):
        pass


class MimeTypeMap:
    _INSTANCE = None

    @classmethod
    def getSingleton(cls):
        if cls._INSTANCE is None:
            cls._INSTANCE = cls()
        return cls._INSTANCE

    def getMimeTypeFromExtension(self, extension):
        import mimetypes

        return mimetypes.guess_type("file." + str(extension))[0]

    def getExtensionFromMimeType(self, mime):
        import mimetypes

        return mimetypes.guess_extension(str(mime))


class ContextCompat:
    @staticmethod
    def getColor(context, color):
        return int(color) if isinstance(color, int) else _theme_color(color)

    @staticmethod
    def getDrawable(context, resource):
        return Drawable()

    @staticmethod
    def getSystemService(context, name):
        if hasattr(context, "getSystemService"):
            return context.getSystemService(name)
        return None


class Activity(ContextWrapper):
    RESULT_OK = -1
    RESULT_CANCELED = 0

    @classmethod
    def getClass(cls):
        return _java_class_ref("android.app.Activity")

    def __init__(self, *args, **kwargs):
        super().__init__()
        self._result = None
        self._finished = False
        self._intent = None

    def finish(self):
        self._finished = True
        return None

    def isFinishing(self):
        return self._finished

    def isDestroyed(self):
        return False

    def getIntent(self):
        return self._intent

    def setIntent(self, intent):
        self._intent = intent
        return None

    def getWindow(self):
        return Window(self)

    def getWindowManager(self):
        return WindowManager()

    def getLayoutInflater(self):
        return LayoutInflater.from_(self)

    def getParentActivity(self):
        return self

    def getFragmentView(self):
        return self

    def runOnUiThread(self, runnable):
        return AndroidUtilities.runOnUIThread(runnable)

    def getApplicationContext(self):
        return ApplicationLoader.getApplicationContext()

    def setResult(self, result, data=None):
        self._result = (result, data)


class ChatActivity(Activity):
    def __init__(self, data=None):
        super().__init__()
        self._data = data if isinstance(data, dict) else {}
        self._dialog_id = int(
            self._data.get("dialog_id")
            or self._data.get("peer")
            or self._data.get("peer_id")
            or 0
        )
        self._topic_id = int(self._data.get("topic_id") or 0)

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.ui.ChatActivity")

    def getDialogId(self):
        return self._dialog_id

    def getTopicId(self):
        return self._topic_id

    def getChatMode(self):
        return 0

    def getSavedDialogId(self):
        return 0

    def getMergeDialogId(self):
        return 0

    def getCurrentEncryptedChat(self):
        return None

    def getCurrentChat(self):
        try:
            from org.telegram.messenger import MessagesController

            return MessagesController.getInstance(0).getChat(self._dialog_id)
        except Exception:
            return None

    def getMessagesController(self):
        from org.telegram.messenger import MessagesController

        return MessagesController.getInstance(0)

    def getConnectionsManager(self):
        from org.telegram.messenger import AccountInstance

        return AccountInstance.getInstance(0).getConnectionsManager()

    def getUserConfig(self):
        from org.telegram.messenger import UserConfig

        return UserConfig.getInstance(0)

    def getParentActivity(self):
        return Activity()

    def getFragmentView(self):
        return View()

    def getAccountInstance(self):
        from org.telegram.messenger import AccountInstance

        return AccountInstance.getInstance(0)


class LaunchActivity(Activity):
    @classmethod
    def getSafeLastFragment(cls):
        try:
            import extera_ios

            fragment = extera_ios.host("ui.last_fragment")
            if isinstance(fragment, dict):
                return ChatActivity(fragment)
            if fragment is not None:
                return fragment
        except Exception:
            pass
        return None


LaunchActivity.instance = Activity()


class PluginsInfoActivity(Activity):
    """`com.exteragram.messenger.plugins.ui.PluginsInfoActivity` facade."""

    @classmethod
    def getClass(cls):
        return _java_class_ref(
            "com.exteragram.messenger.plugins.ui.PluginsInfoActivity"
        )

    def fillItems(self, *args, **kwargs):
        return None

    def onClick(self, *args, **kwargs):
        return None


class PluginsActivity(Activity):
    """`com.exteragram.messenger.plugins.ui.PluginsActivity` facade."""

    @classmethod
    def getClass(cls):
        return _java_class_ref(
            "com.exteragram.messenger.plugins.ui.PluginsActivity"
        )


class PluginSettingsActivity(Activity):
    """`com.exteragram.messenger.plugins.ui.PluginSettingsActivity` facade."""

    def __init__(self, plugin_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plugin_id = plugin_id

    @classmethod
    def getClass(cls):
        return _java_class_ref(
            "com.exteragram.messenger.plugins.ui.PluginSettingsActivity"
        )

    def getPluginId(self):
        return self.plugin_id

    def loadPluginSettings(self, *args, **kwargs):
        return None


class PluginCellDelegate:
    """`...plugins.ui.components.PluginCellDelegate` callback interface."""

    @classmethod
    def getClass(cls):
        return _java_class_ref(
            "com.exteragram.messenger.plugins.ui.components.PluginCellDelegate"
        )

    def onClick(self, *args, **kwargs):
        return None

    def onLongClick(self, *args, **kwargs):
        return None


class InstallPluginBottomSheet:
    """`...plugins.ui.components.InstallPluginBottomSheet` facade."""

    class PluginInstallParams:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def to_json(self):
            data = dict(self.kwargs)
            data.setdefault("args", list(self.args))
            return data

    def __init__(self, fragment=None, validation_result=None, params=None):
        self.fragment = fragment
        self.validation_result = validation_result
        self.params = params
        self.shown = False

    @classmethod
    def getClass(cls):
        return _java_class_ref(
            "com.exteragram.messenger.plugins.ui.components.InstallPluginBottomSheet"
        )

    def show(self):
        self.shown = True
        return self

    def dismiss(self):
        self.shown = False



class DialogInterface:
    BUTTON_POSITIVE = -1
    BUTTON_NEGATIVE = -2
    BUTTON_NEUTRAL = -3

    class OnClickListener:
        def onClick(self, dialog, which):
            pass

    class OnDismissListener:
        def onDismiss(self, dialog):
            pass

    class OnShowListener:
        def onShow(self, dialog):
            pass

    class OnCancelListener:
        def onCancel(self, dialog):
            pass

    class OnMultiChoiceClickListener:
        def onClick(self, dialog, which, isChecked):
            pass


class AttributeSet:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def getAttributeBooleanValue(self, *args):
        return False

    def getAttributeIntValue(self, *args):
        return 0

    def getAttributeValue(self, *args):
        return None


class Dialog:
    def __init__(self, context=None, *args, **kwargs):
        self.context = context
        self._dismissListener = None
        self._showListener = None
        self._cancelListener = None
        self._showing = False

    def show(self):
        self._showing = True

    def dismiss(self):
        self._showing = False

    def isShowing(self):
        return self._showing

    def setCanceledOnTouchOutside(self, value):
        return None

    def setCancelable(self, value):
        return None

    def setOnDismissListener(self, listener):
        self._dismissListener = listener

    def setOnShowListener(self, listener):
        self._showListener = listener

    def setOnCancelListener(self, listener):
        self._cancelListener = listener

    def setContentView(self, view):
        self.contentView = view

    def findViewById(self, identifier):
        return None

    def getWindow(self):
        return None


class LayoutHelper:
    @staticmethod
    def measureText(text, paint=None):
        return len(str(text or "")) * 7

    @staticmethod
    def createFrame(width, height, gravity=0, left=0, top=0, right=0, bottom=0):
        params = LayoutParams(width, height)
        params.gravity = gravity
        params.margins = (int(left), int(top), int(right), int(bottom))
        return params

    @staticmethod
    def createLinear(width, height, gravity=0, left=0, top=0, right=0, bottom=0):
        return LayoutHelper.createFrame(width, height, gravity, left, top, right, bottom)

    @staticmethod
    def createRelative(width, height, gravity=0, left=0, top=0, right=0, bottom=0):
        return LayoutHelper.createFrame(width, height, gravity, left, top, right, bottom)

    @staticmethod
    def createScroll(width, height, gravity=0, left=0, top=0, right=0, bottom=0):
        return LayoutHelper.createFrame(width, height, gravity, left, top, right, bottom)

    @staticmethod
    def getLocationInWindow(view):
        return [0, 0]

    @staticmethod
    def getLocationInView(view):
        return [0, 0]

    @staticmethod
    def getRelativeLeft(view):
        return 0

    @staticmethod
    def getRelativeTop(view):
        return 0

    @staticmethod
    def getRelativeRight(view):
        return 0

    @staticmethod
    def getRelativeBottom(view):
        return 0


class RequestDelegate:
    def run(self, response, error):
        pass


# ---------------------------------------------------------------------------
# Remaining Android services used by the SDK and by advanced plugins


class DispatchQueue:
    """`org.telegram.messenger.DispatchQueue` backed by a Python thread."""

    def __init__(self, name="extera-queue", priority=0):
        self.name = str(name or "extera-queue")
        self.priority = int(priority or 0)
        self._threads = []
        self._cancelled = {}

    def runOnQueue(self, runnable):
        function = runnable.run if hasattr(runnable, "run") else runnable
        if not callable(function):
            return None
        event = _threading.Event()
        self._cancelled[id(runnable)] = event

        def runner():
            try:
                if event.is_set():
                    return
                function()
            finally:
                self._cancelled.pop(id(runnable), None)

        thread = _threading.Thread(target=runner, name=self.name, daemon=True)
        self._cancelled[id(thread)] = event
        self._threads = [item for item in self._threads if item.is_alive()]
        self._threads.append(thread)
        thread.start()
        return thread

    def postRunnable(self, runnable):
        return self.runOnQueue(runnable)

    def cancelRunnable(self, runnable):
        event = self._cancelled.pop(id(runnable), None)
        if event is not None:
            event.set()
            return True
        return False

    def getQueueName(self):
        return self.name

    def recycle(self):
        for event in list(self._cancelled.values()):
            event.set()
        self._cancelled.clear()
        self._threads.clear()

    def __repr__(self):
        return "<DispatchQueue %s>" % self.name


class _PhotoSize:
    """The `TLRPC.TL_photoSize` shape `ImageLoader.scaleAndSaveImage` returns."""

    def __init__(self, kind, width, height, size=0, path=None):
        self.type = kind
        self.w = int(width)
        self.h = int(height)
        self.size = int(size)
        self.location = path

    def to_json(self):
        return {
            "_": "photoSize",
            "type": self.type,
            "w": self.w,
            "h": self.h,
            "size": self.size,
        }

    def __repr__(self):
        return "<photoSize %s %dx%d>" % (self.type, self.w, self.h)


class ImageLoader(metaclass=_TolerantClassMeta):
    """`org.telegram.messenger.ImageLoader` for photo/video thumbnails."""

    @staticmethod
    def loadBitmap(path, *args, **kwargs):
        try:
            with open(str(path), "rb") as handle:
                data = handle.read()
        except Exception:
            return None
        width, height = _image_dimensions(data)
        limit = 0
        for value in args:
            if isinstance(value, int) and value > 0:
                limit = max(limit, value)
        if limit and width and height and max(width, height) > limit:
            scale = float(limit) / float(max(width, height))
            width = max(1, int(width * scale))
            height = max(1, int(height * scale))
        return Bitmap(data, width, height, path=str(path))

    @staticmethod
    def scaleAndSaveImage(*args, **kwargs):
        bitmap = None
        for value in args:
            if isinstance(value, Bitmap):
                bitmap = value
                break
        if bitmap is None:
            return None
        numbers = [value for value in args if isinstance(value, int)]
        # Overloads: `(bitmap, w, h, quality, cacheOnly, ...)` and
        # `(None, bitmap, format, ..., w, h, quality, ...)`.
        width = numbers[0] if numbers else bitmap.getWidth()
        height = numbers[1] if len(numbers) > 1 else bitmap.getHeight()
        return _PhotoSize(
            "x",
            width or bitmap.getWidth(),
            height or bitmap.getHeight(),
            len(bitmap._data or b""),
        )

    @staticmethod
    def getBitmapFromPath(path, *args, **kwargs):
        return ImageLoader.loadBitmap(path, *args, **kwargs)

    _MEMORY_CACHE = {}
    _USE_COUNTS = {}

    @classmethod
    def getInstance(cls):
        return cls

    @classmethod
    def getFromMemCache(cls, key, *args, **kwargs):
        return cls._MEMORY_CACHE.get(str(key))

    @classmethod
    def getImageFromMemory(cls, key, *args, **kwargs):
        return cls._MEMORY_CACHE.get(str(key))

    @classmethod
    def isInMemCache(cls, key, *args, **kwargs):
        return str(key) in cls._MEMORY_CACHE

    @classmethod
    def putImageToCache(cls, bitmap, key, *args, **kwargs):
        cls._MEMORY_CACHE[str(key)] = bitmap
        return None

    @classmethod
    def put(cls, key, bitmap, *args, **kwargs):
        cls._MEMORY_CACHE[str(key)] = bitmap
        return None

    @classmethod
    def removeImage(cls, key, *args, **kwargs):
        cls._MEMORY_CACHE.pop(str(key), None)
        return None

    @classmethod
    def clearMemory(cls, *args, **kwargs):
        cls._MEMORY_CACHE.clear()
        cls._USE_COUNTS.clear()
        return None

    @classmethod
    def incrementUseCount(cls, key, *args, **kwargs):
        key = str(key)
        cls._USE_COUNTS[key] = cls._USE_COUNTS.get(key, 0) + 1
        return cls._USE_COUNTS[key]

    @classmethod
    def decrementUseCount(cls, key, *args, **kwargs):
        key = str(key)
        cls._USE_COUNTS[key] = max(0, cls._USE_COUNTS.get(key, 0) - 1)
        return cls._USE_COUNTS[key]

    @classmethod
    def loadImageForImageReceiver(cls, receiver, *args, **kwargs):
        location = receiver
        for attribute in ("imageLocation", "currentImageLocation", "getImageLocation"):
            try:
                value = getattr(receiver, attribute)
                location = value() if callable(value) else value
            except Exception:
                continue
            if location:
                break
        path = location
        if not isinstance(path, str):
            data = location if isinstance(location, dict) else getattr(
                location, "_value", None
            )
            if isinstance(data, dict):
                path = data.get("path") or data.get("file_name")
            else:
                path = None
        if isinstance(path, str) and os.path.exists(path):
            return cls.loadBitmap(path)
        return None

    @classmethod
    def cancel(cls, receiver, *args, **kwargs):
        return None

    @classmethod
    def cancelForceLoadingForImageReceiver(cls, receiver, *args, **kwargs):
        return None

    @classmethod
    def changeFileLoadingPriorityForImageReceiver(cls, receiver, priority, *args,
                                                  **kwargs):
        return None

    @classmethod
    def getFileProgress(cls, file_name, *args, **kwargs):
        return FileLoader.getFileProgress(file_name)

    @classmethod
    def getFileProgressSizes(cls, file_name, *args, **kwargs):
        progress = cls.getFileProgress(file_name)
        return progress, progress

    @staticmethod
    def getHttpFileName(url, *args, **kwargs):
        import hashlib

        return hashlib.md5(str(url or "").encode("utf-8")).hexdigest()

    @classmethod
    def getHttpFilePath(cls, url, extension=None, *args, **kwargs):
        name = cls.getHttpFileName(url)
        if extension:
            name += "." + str(extension).lstrip(".")
        return os.path.join(_path_for("cache"), name)

    @staticmethod
    def getHttpUrlExtension(url, default_ext="", *args, **kwargs):
        path = str(url or "").split("?")[0].split("#")[0]
        name = os.path.basename(path)
        if "." in name:
            extension = name.rsplit(".", 1)[1].lower()
            if 1 <= len(extension) <= 8:
                return extension
        return str(default_ext or "")

    @classmethod
    def isLoadingHttpFile(cls, url, *args, **kwargs):
        return False

    @classmethod
    def loadHttpFile(cls, url, extension=None, *args, **kwargs):
        return None

    @classmethod
    def cancelLoadHttpFile(cls, url, *args, **kwargs):
        return None

    @classmethod
    def removeImageReceiver(cls, *args, **kwargs):
        return None

    @classmethod
    def replaceImageInCache(cls, *args, **kwargs):
        return None

    @classmethod
    def hasLottieMemCache(cls, key, *args, **kwargs):
        return False

    @classmethod
    def getLottieMemCahce(cls, key, *args, **kwargs):
        return None

    @classmethod
    def getCacheOutQueue(cls, *args, **kwargs):
        return DispatchQueue("image-cache")


class _ResourceNamespace:
    def __init__(self, name):
        self._name = name

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return "%s.%s" % (self._name, name)


class R:
    """`org.telegram.messenger.R` resource ids; iOS keeps their names."""

    anim = _ResourceNamespace("R.anim")
    array = _ResourceNamespace("R.array")
    attr = _ResourceNamespace("R.attr")
    color = _ResourceNamespace("R.color")
    dimen = _ResourceNamespace("R.dimen")
    drawable = _ResourceNamespace("R.drawable")
    id = _ResourceNamespace("R.id")
    integer = _ResourceNamespace("R.integer")
    layout = _ResourceNamespace("R.layout")
    menu = _ResourceNamespace("R.menu")
    mipmap = _ResourceNamespace("R.mipmap")
    plurals = _ResourceNamespace("R.plurals")
    raw = _ResourceNamespace("R.raw")
    string = _ResourceNamespace("R.string")
    style = _ResourceNamespace("R.style")
    xml = _ResourceNamespace("R.xml")


class Plugin:
    """`com.exteragram.messenger.plugins.Plugin` model."""

    def __init__(self, plugin_id="", name="", metadata=None):
        self.id = str(plugin_id)
        self.name = str(name)
        self.metadata = dict(metadata or {})
        self.enabled = False

    def getId(self):
        return self.id

    def getName(self):
        return self.name

    def getMetadata(self):
        return dict(self.metadata)

    def setEnabled(self, value):
        self.enabled = bool(value)

    def isEnabled(self):
        return self.enabled

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


class RequiredPluginInfo:
    """`com.exteragram.messenger.plugins.ui.components.RequiredPluginInfo`."""

    STATE_UNKNOWN = 0
    STATE_SATISFIED = 1
    STATE_MISSING = 2
    STATE_DISABLED = 3
    STATE_OUTDATED = 4

    def __init__(self, plugin_id="", state=STATE_UNKNOWN):
        self.id = str(plugin_id)
        self.plugin_id = self.id
        self.state = state
        self.name = self.id
        self.version = None

    def isSatisfied(self):
        return self.state == self.STATE_SATISFIED


class PluginsHooks:
    """Containers returned by the Android hooks layer."""

    class PostRequestResult:
        def __init__(self, response=None, error=None):
            self.response = response
            self.error = error

        def getResponse(self):
            return self.response

        def getError(self):
            return self.error

    class PreRequestResult(PostRequestResult):
        pass

    class UpdateResult:
        def __init__(self, update=None, error=None):
            self.update = update
            self.error = error

    class UpdatesResult:
        def __init__(self, updates=None, error=None):
            self.updates = list(updates or [])
            self.error = error


class PyMethodHook:
    """`com.exteragram.messenger.plugins.xposed.PyMethodHook` callback carrier."""

    def __init__(self, plugin_id, hook=None, *args):
        self.plugin_id = plugin_id
        self.hook = hook
        self.legacy_args = args

    def before_hooked_method(self, param):
        callback = getattr(self.hook, "before_hooked_method", None)
        if callable(callback):
            return callback(param)
        return None

    def after_hooked_method(self, param):
        callback = getattr(self.hook, "after_hooked_method", None)
        if callable(callback):
            return callback(param)
        return None

    def replace_hooked_method(self, param):
        callback = getattr(self.hook, "replace_hooked_method", None)
        if callable(callback):
            return callback(param)
        return None

    @classmethod
    def getClass(cls):
        return _java_class_ref(
            "com.exteragram.messenger.plugins.xposed.PyMethodHook"
        )

    def __repr__(self):
        return "<PyMethodHook %s>" % self.plugin_id


class PyMethodReplacement(PyMethodHook):
    @classmethod
    def getClass(cls):
        return _java_class_ref(
            "com.exteragram.messenger.plugins.xposed.PyMethodReplacement"
        )


class ChatMessageCell(View):
    """`org.telegram.ui.Cells.ChatMessageCell` reflection target."""

    @classmethod
    def getClass(cls):
        return _java_class_ref("org.telegram.ui.Cells.ChatMessageCell")

    @staticmethod
    def getFileIcon(*args, **kwargs):
        return None


def _tolerant_java_getattr(self, name):
    """Android controllers answer an unmapped member instead of crashing.

    A plugin may call a Java method this port has not modelled yet.  The
    default follows the shape of the name: predicates read false, getters read
    null, and the rest are no-ops.  Mapped methods are unaffected because
    `__getattr__` is only reached for a missing attribute.
    """
    if name.startswith("__") or name.startswith("_"):
        raise AttributeError(name)
    if (
        name[:2] == "is"
        or name[:3] == "can"
        or name[:3] == "has"
        or name[:6] == "should"
        or name[:4] == "need"
    ):
        return lambda *args, **kwargs: False
    return lambda *args, **kwargs: None


for _tolerant_class in (
    _AccountInstance,
    _ConnectionsManager,
    _UserConfigInstance,
    _SendMessagesHelperInstance,
    _MediaControllerInstance,
    _MessagesStorageInstance,
    _ContactsControllerInstance,
    _NotificationsControllerInstance,
    _NotificationsSettingsInstance,
    _DownloadControllerInstance,
    _LocationControllerInstance,
    _SecretChatHelperInstance,
    _MediaDataControllerInstance,
):
    if "__getattr__" not in _tolerant_class.__dict__:
        _tolerant_class.__getattr__ = _tolerant_java_getattr
del _tolerant_class


class StatFs:
    """`android.os.StatFs` backed by `shutil.disk_usage`."""

    def __init__(self, path):
        self.path = str(path or ".")
        self._block_size = 4096
        self._total = 0
        self._free = 0
        self.restat()

    def restat(self):
        try:
            import shutil

            usage = shutil.disk_usage(self.path)
            self._total = int(usage.total)
            self._free = int(usage.free)
        except Exception:
            self._total = 0
            self._free = 0
        return None

    def getBlockSize(self):
        return self._block_size

    def getBlockCount(self):
        return self._total // self._block_size

    def getFreeBlocks(self):
        return self._free // self._block_size

    def getAvailableBlocks(self):
        return self._free // self._block_size

    def getAvailableBytes(self):
        return self._free

    def getFreeBytes(self):
        return self._free

    def getTotalBytes(self):
        return self._total


class Scanner:
    """`java.util.Scanner` over a string, bytes or readable stream."""

    def __init__(self, source, charset="UTF-8"):
        self._charset = str(charset or "UTF-8")
        try:
            if hasattr(source, "read"):
                data = source.read()
            elif isinstance(source, (bytes, bytearray, memoryview)):
                data = bytes(source)
            else:
                data = str(source)
        except Exception:
            data = b""
        if isinstance(data, (bytes, bytearray, memoryview)):
            data = bytes(data).decode(self._charset, "replace")
        self._data = str(data)
        self._position = 0
        self._delimiter = None
        self._tokens = None
        self._token_index = 0

    def useDelimiter(self, pattern):
        import re

        self._delimiter = re.compile(str(pattern))
        self._tokens = None
        self._token_index = 0
        return self

    def _ensure_tokens(self):
        if self._tokens is None:
            if self._delimiter is None:
                self._tokens = self._data.split()
            else:
                self._tokens = [
                    token for token in self._delimiter.split(self._data) if token != ""
                ]
            self._token_index = 0
        return self._tokens

    def hasNext(self):
        return self._token_index < len(self._ensure_tokens())

    def next(self):
        tokens = self._ensure_tokens()
        if self._token_index >= len(tokens):
            raise StopIteration("no more tokens")
        token = tokens[self._token_index]
        self._token_index += 1
        return token

    def nextLine(self):
        if self._position >= len(self._data):
            raise StopIteration("no more lines")
        end = self._data.find("\n", self._position)
        if end < 0:
            end = len(self._data)
        line = self._data[self._position:end]
        self._position = end + 1
        return line

    def hasNextLine(self):
        return self._position < len(self._data)

    def nextInt(self):
        return int(self.next())

    def nextLong(self):
        return int(self.next())

    def nextFloat(self):
        return float(self.next())

    def nextDouble(self):
        return float(self.next())

    def nextBoolean(self):
        return str(self.next()).lower() == "true"

    def hasNextInt(self):
        try:
            int(self._ensure_tokens()[self._token_index])
            return True
        except (IndexError, ValueError):
            return False

    def hasNextLong(self):
        return self.hasNextInt()

    def hasNextDouble(self):
        try:
            float(self._ensure_tokens()[self._token_index])
            return True
        except (IndexError, ValueError):
            return False

    def close(self):
        return None

    def reset(self):
        self._token_index = 0
        self._position = 0
        return self


class RequestTimeDelegate:
    def run(self, time):
        pass


class BottomSheet(View):
    """`org.telegram.ui.ActionBar.BottomSheet` facade."""

    class BottomSheetDelegateInterface:
        def canDismiss(self):
            return True

        def onOpenAnimationEnd(self):
            pass

        def onDismissAnimationEnd(self):
            pass

    def __init__(self, context=None, need_full_screen=False, resources_provider=None):
        super().__init__(context)
        self.need_full_screen = bool(need_full_screen)
        self.resources_provider = resources_provider
        self._custom_view = None
        self._title = None
        self._showing = False
        self._cancelable = True
        self._dim = True
        self._dismiss_listener = None
        self._delegate = None

    def setCustomView(self, view):
        self._custom_view = view
        return self

    def setTitle(self, title):
        self._title = title
        return self

    def setApplyBottomPadding(self, value):
        return self

    def setApplyTopPadding(self, value):
        return self

    def setDelegate(self, delegate):
        self._delegate = delegate
        return self

    def show(self):
        self._showing = True
        return None

    def dismiss(self):
        if self._showing and self._dismiss_listener is not None:
            try:
                self._dismiss_listener.onDismiss()
            except Exception:
                pass
        self._showing = False
        return None

    def isShowing(self):
        return self._showing

    def setCancelable(self, value):
        self._cancelable = bool(value)
        return self

    def setDimBehind(self, value):
        self._dim = bool(value)
        return self

    def setBackgroundColor(self, color):
        self.background = int(color or 0)
        return self

    def setOnDismissListener(self, listener):
        self._dismiss_listener = listener
        return self

    def getSheetContainer(self):
        return self._custom_view if self._custom_view is not None else View(self.context)

    def setFocusable(self, value):
        return self

    def setSlidingEnabled(self, value):
        return self

    def setCanDismissWithSwipe(self, value):
        return self

    def setCanDismissWithTouchOutside(self, value):
        return self

    def setUseLightStatusBar(self, value):
        return self

    def setUseBackground(self, value):
        return self

    def setOpenNoDelay(self, value):
        return self

    def setCustomView(self, view):
        self._custom_view = view
        return self


class StarParticlesView(View):
    """`org.telegram.ui.Components.Premium.StarParticlesView` effect view."""

    def __init__(self, context=None, size=0):
        super().__init__(context)
        self.size = int(size or 0)
        self.speed = 1.0
        self.color = 0
        self.stars = 0
        self._started = False
        self._delegate = None

    def setSpeed(self, value):
        self.speed = float(value or 0)
        return self

    def setColor(self, value):
        self.color = int(value or 0)
        return self

    def setStars(self, value):
        self.stars = int(value or 0)
        return self

    def setParticlesCount(self, value):
        return self.setStars(value)

    def start(self):
        self._started = True
        return None

    def stop(self):
        self._started = False
        return None

    def setDelegate(self, value):
        self._delegate = value
        return self


class NestedScrollView(ScrollView):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self._nested = True
        self._scroll_listener = None

    def setNestedScrollingEnabled(self, value):
        self._nested = bool(value)
        return None

    def isNestedScrollingEnabled(self):
        return self._nested

    def setOnScrollChangeListener(self, listener):
        self._scroll_listener = listener
        return None

    def smoothScrollTo(self, x, y):
        return None

    def fullScroll(self, direction):
        return True


class BackupImageView(ImageView):
    def __init__(self, context=None, *args, **kwargs):
        super().__init__(context)
        self.round_radius = 0
        self.aspect_ratio = 0.0

    def setImage(self, *args, **kwargs):
        return None

    def setRoundRadius(self, value):
        self.round_radius = int(value or 0)
        return None

    def setAspectRatio(self, value):
        self.aspect_ratio = float(value or 0)
        return None

    def setSize(self, width, height=None):
        self.image_width = int(width or 0)
        self.image_height = int(height or width or 0)
        return None

    def setForUser(self, *args, **kwargs):
        return None

    def setForChat(self, *args, **kwargs):
        return None

    def setImageLocation(self, *args, **kwargs):
        return None

    def setImageMedia(self, *args, **kwargs):
        return None

    def setPlaceholderImage(self, *args, **kwargs):
        return None

    def setLegacyImage(self, *args, **kwargs):
        return None


class GiftSheet:
    def __init__(self, context=None, account=0, user_id=0, *args, **kwargs):
        self.context = context
        self.account = int(account or 0)
        self.user_id = int(user_id or 0)
        self._showing = False
        self._dismiss_listener = None

    def show(self):
        self._showing = True
        return None

    def dismiss(self):
        self._showing = False
        return None

    def isShowing(self):
        return self._showing

    def setOnDismissListener(self, listener):
        self._dismiss_listener = listener
        return self

    def setDelegate(self, delegate):
        return self


class ProxyListActivity(Activity):
    class TextDetailProxyCell(View):
        def __init__(self, context=None):
            super().__init__(context)

        def setProxy(self, *args, **kwargs):
            return None

        def setTextAndValue(self, *args, **kwargs):
            return None

    def __init__(self, *args, **kwargs):
        super().__init__()


def exports():
    mapping = {
        "org.telegram.messenger.UserConfig": UserConfig,
        "org.telegram.messenger.MessagesController": MessagesController,
        "org.telegram.messenger.AccountInstance": AccountInstance,
        "org.telegram.tgnet.ConnectionsManager": ConnectionsManager,
        "org.telegram.messenger.FileLoader": FileLoader,
        "org.telegram.messenger.ApplicationLoader": ApplicationLoader,
        "org.telegram.messenger.browser.Browser": Browser,
        "org.telegram.messenger.LocaleController": LocaleController,
        "org.telegram.messenger.AndroidUtilities": AndroidUtilities,
        "org.telegram.messenger.Utilities": Utilities,
        "org.telegram.messenger.ContactsController": ContactsController,
        "org.telegram.messenger.SendMessagesHelper": SendMessagesHelper,
        "org.telegram.messenger.SendMessageParams": SendMessageParams,
        "org.telegram.messenger.ImageLocation": ImageLocation,
        "org.telegram.messenger.MediaController": MediaController,
        "org.telegram.messenger.MediaDataController": MediaDataController,
        "org.telegram.messenger.NotificationsController": NotificationsController,
        "org.telegram.messenger.NotificationsSettings": NotificationsSettings,
        "org.telegram.messenger.MessagesStorage": MessagesStorage,
        "org.telegram.messenger.DownloadController": DownloadController,
        "org.telegram.messenger.SecretChatHelper": SecretChatHelper,
        "org.telegram.messenger.LocationController": LocationController,
        "org.telegram.messenger.NotificationCenter": NotificationCenter,
        "org.telegram.messenger.MessageObject": MessageObject,
        "com.exteragram.messenger.plugins.PluginsConstants": PluginsConstants,
        "com.exteragram.messenger.plugins.PluginsController": PluginsController,
        "com.exteragram.messenger.plugins.PythonPluginsEngine": PythonPluginsEngine,
        "com.exteragram.messenger.plugins.pip.PipController": PipController,
        "com.exteragram.messenger.ExteraConfig": ExteraConfig,
        "com.exteragram.messenger.utils.AppUtils": AppUtils,
        "com.exteragram.messenger.utils.IntentsController": IntentsController,
        "org.mvel2.MVEL": MVEL,
        "org.telegram.messenger.ChatObject": ChatObject,
        "org.telegram.messenger.UserObject": UserObject,
        "org.telegram.messenger.DialogObject": DialogObject,
        "org.telegram.messenger.BuildVars": BuildVars,
        "org.telegram.tgnet.RequestDelegate": RequestDelegate,
        "org.telegram.tgnet.RequestTimeDelegate": RequestTimeDelegate,
        "org.telegram.ui.Components.LayoutHelper": LayoutHelper,
        "org.telegram.ui.Components.EditTextBoldCursor": EditTextBoldCursor,
        "org.telegram.ui.Components.OutlineTextContainerView": OutlineTextContainerView,
        "org.telegram.ui.Components.RLottieImageView": RLottieImageView,
        "org.telegram.ui.Components.BackupImageView": BackupImageView,
        "org.telegram.ui.Components.Premium.StarParticlesView": StarParticlesView,
        "org.telegram.ui.Gifts.GiftSheet": GiftSheet,
        "androidx.core.widget.NestedScrollView": NestedScrollView,
        "org.telegram.ui.ProxyListActivity": ProxyListActivity,
        "org.telegram.ui.ProxyListActivity$TextDetailProxyCell": ProxyListActivity.TextDetailProxyCell,
        "org.telegram.ui.ActionBar.BottomSheet": BottomSheet,
        "org.telegram.ui.Components.VideoPlayer": VideoPlayer,
        "org.telegram.ui.Stories.recorder.ButtonWithCounterView": ButtonWithCounterView,
        "org.telegram.messenger.SvgHelper": SvgHelper,
        "org.telegram.ui.LaunchActivity": LaunchActivity,
        "org.telegram.ui.ChatActivity": ChatActivity,
        "org.telegram.ui.Components.RecyclerListView": RecyclerView,
        "org.telegram.ui.Components.MediaActionDrawable": MediaActionDrawable,
        "org.telegram.ui.Components.RLottieDrawable": RLottieDrawable,
        "org.telegram.ui.Components.UniversalAdapter": UniversalAdapter,
        "org.telegram.ui.ActionBar.BaseFragment": BaseFragment,
        "androidx.recyclerview.widget.RecyclerView": RecyclerView,
        "androidx.recyclerview.widget.RecyclerView$Adapter": RecyclerView.Adapter,
        "androidx.recyclerview.widget.RecyclerView$LayoutManager": RecyclerView.LayoutManager,
        "androidx.recyclerview.widget.RecyclerView$ItemAnimator": RecyclerView.ItemAnimator,
        "androidx.recyclerview.widget.RecyclerView$ItemDecoration": RecyclerView.ItemDecoration,
        "androidx.recyclerview.widget.LinearLayoutManager": LinearLayoutManager,
        "androidx.recyclerview.widget.GridLayoutManager": GridLayoutManager,
        "androidx.core.graphics.drawable.DrawableCompat": DrawableCompat,
        "androidx.core.view.ViewCompat": ViewCompat,
        "androidx.viewpager.widget.ViewPager": ViewPager,
        "com.chaquo.python.PyObject": PyObject,
        "com.chaquo.python.Python": Python,
        "java.lang.ref.WeakReference": WeakReference,
        "java.util.Collection": list,
        "java.util.Map": dict,
        "java.util.Scanner": Scanner,
        "android.app.Activity": Activity,
        "android.app.Service": Service,
        "android.app.NotificationManager": NotificationManager,
        "android.app.NotificationChannel": NotificationChannel,
        "android.app.Notification": Notification,
        "android.app.Notification$Builder": Notification.Builder,
        "androidx.core.app.NotificationCompat": NotificationCompat,
        "androidx.core.app.NotificationCompat$Builder": NotificationCompat.Builder,
        "android.content.DialogInterface": DialogInterface,
        "android.view.View": View,
        "android.view.ViewTreeObserver": ViewTreeObserver,
        "android.view.ViewTreeObserver$OnGlobalLayoutListener": ViewTreeObserver.OnGlobalLayoutListener,
        "android.view.ViewTreeObserver$OnPreDrawListener": ViewTreeObserver.OnPreDrawListener,
        "android.view.ViewTreeObserver$OnScrollChangedListener": ViewTreeObserver.OnScrollChangedListener,
        "android.view.ViewTreeObserver$OnTouchModeChangeListener": ViewTreeObserver.OnTouchModeChangeListener,
        "android.view.WindowManager": WindowManager,
        "android.view.Window": Window,
        "android.view.Display": Display,
        "android.view.LayoutInflater": LayoutInflater,
        "android.view.MotionEvent": MotionEvent,
        "android.view.KeyEvent": KeyEvent,
        "android.view.GestureDetector": GestureDetector,
        "android.view.GestureDetector$SimpleOnGestureListener": GestureDetector.SimpleOnGestureListener,
        "android.view.ScaleGestureDetector": ScaleGestureDetector,
        "android.view.Choreographer": Choreographer,
        "android.view.Choreographer$FrameCallback": Choreographer.FrameCallback,
        "android.view.ViewPropertyAnimator": ViewPropertyAnimator,
        "android.view.animation.TimeInterpolator": TimeInterpolator,
        "android.view.animation.LinearInterpolator": LinearInterpolator,
        "android.view.animation.AccelerateInterpolator": AccelerateInterpolator,
        "android.view.animation.DecelerateInterpolator": DecelerateInterpolator,
        "android.view.animation.AccelerateDecelerateInterpolator": AccelerateDecelerateInterpolator,
        "android.view.animation.OvershootInterpolator": OvershootInterpolator,
        "android.view.animation.AnticipateInterpolator": AnticipateInterpolator,
        "android.view.animation.AnticipateOvershootInterpolator": AnticipateOvershootInterpolator,
        "android.view.animation.BounceInterpolator": BounceInterpolator,
        "android.view.animation.CycleInterpolator": CycleInterpolator,
        "android.view.animation.PathInterpolator": PathInterpolator,
        "android.view.animation.Animation": Animation,
        "android.view.animation.AlphaAnimation": AlphaAnimation,
        "android.view.animation.ScaleAnimation": ScaleAnimation,
        "android.view.animation.TranslateAnimation": TranslateAnimation,
        "android.view.animation.RotateAnimation": RotateAnimation,
        "android.view.animation.AnimationSet": AnimationSet,
        "android.view.animation.AnimationUtils": AnimationUtils,
        "android.animation.Animator": Animator,
        "android.animation.AnimatorListenerAdapter": AnimatorListenerAdapter,
        "android.animation.AnimatorInflater": AnimatorInflater,
        "android.animation.ValueAnimator": ValueAnimator,
        "android.animation.ObjectAnimator": ObjectAnimator,
        "android.animation.AnimatorSet": AnimatorSet,
        "android.transition.Scene": Scene,
        "android.transition.Transition": Transition,
        "android.transition.Fade": Fade,
        "android.transition.Slide": Slide,
        "android.transition.ChangeBounds": ChangeBounds,
        "android.transition.ChangeTransform": ChangeTransform,
        "android.transition.ChangeImageTransform": ChangeImageTransform,
        "android.transition.Explode": Explode,
        "android.transition.TransitionSet": TransitionSet,
        "android.transition.TransitionManager": TransitionManager,
        "android.view.ViewGroup": ViewGroup,
        "android.view.ViewGroup$LayoutParams": ViewGroup.LayoutParams,
        "android.view.ViewGroup$MarginLayoutParams": ViewGroup.MarginLayoutParams,
        "android.view.Gravity": Gravity,
        "android.view.HapticFeedbackConstants": HapticFeedbackConstants,
        "android.view.inputmethod.EditorInfo": EditorInfo,
        "android.util.AttributeSet": AttributeSet,
        "android.webkit.MimeTypeMap": MimeTypeMap,
        "android.webkit.WebView": WebView,
        "android.webkit.WebSettings": WebSettings,
        "android.webkit.WebViewClient": WebViewClient,
        "android.webkit.WebChromeClient": WebChromeClient,
        "android.webkit.CookieManager": CookieManager,
        "android.webkit.WebResourceRequest": WebResourceRequest,
        "android.webkit.WebResourceResponse": WebResourceResponse,
        "android.app.Dialog": Dialog,
        "android.widget.TextView": TextView,
        "android.widget.TextView$OnEditorActionListener": TextView.OnEditorActionListener,
        "android.widget.EditText": EditText,
        "android.widget.Button": Button,
        "android.widget.ImageView": ImageView,
        "android.widget.ImageView$ScaleType": ImageView.ScaleType,
        "android.widget.Switch": Switch,
        "android.widget.CompoundButton": CompoundButton,
        "android.widget.CompoundButton$OnCheckedChangeListener": CompoundButton.OnCheckedChangeListener,
        "android.widget.CheckBox": CheckBox,
        "android.widget.RadioButton": RadioButton,
        "android.widget.ProgressBar": ProgressBar,
        "android.widget.SeekBar": SeekBar,
        "android.widget.SeekBar$OnSeekBarChangeListener": SeekBar.OnSeekBarChangeListener,
        "android.widget.Spinner": Spinner,
        "android.widget.PopupWindow": PopupWindow,
        "android.widget.ListPopupWindow": ListPopupWindow,
        "android.widget.BaseAdapter": BaseAdapter,
        "android.widget.ArrayAdapter": ArrayAdapter,
        "android.widget.SimpleAdapter": SimpleAdapter,
        "android.widget.ListView": ListView,
        "android.widget.GridView": GridView,
        "android.widget.AbsListView": AbsListView,
        "android.widget.AdapterView": AdapterView,
        "android.widget.AdapterView$OnItemClickListener": AdapterView.OnItemClickListener,
        "android.widget.AdapterView$OnItemLongClickListener": AdapterView.OnItemLongClickListener,
        "android.widget.AdapterView$OnItemSelectedListener": AdapterView.OnItemSelectedListener,
        "android.widget.LinearLayout": LinearLayout,
        "android.widget.FrameLayout": FrameLayout,
        "android.widget.ScrollView": ScrollView,
        "android.widget.HorizontalScrollView": HorizontalScrollView,
        "android.widget.RelativeLayout": RelativeLayout,
        "android.widget.Toolbar": Toolbar,
        "android.widget.LinearLayout$LayoutParams": LayoutParams,
        "android.widget.FrameLayout$LayoutParams": LayoutParams,
        "android.widget.RelativeLayout$LayoutParams": LayoutParams,
        "android.graphics.drawable.Drawable": Drawable,
        "android.graphics.drawable.BitmapDrawable": BitmapDrawable,
        "android.graphics.drawable.ColorDrawable": ColorDrawable,
        "android.graphics.drawable.GradientDrawable": GradientDrawable,
        "android.graphics.drawable.StateListDrawable": StateListDrawable,
        "android.graphics.drawable.LayerDrawable": LayerDrawable,
        "android.graphics.drawable.RippleDrawable": RippleDrawable,
        "android.graphics.drawable.InsetDrawable": InsetDrawable,
        "android.graphics.drawable.ClipDrawable": ClipDrawable,
        "android.graphics.drawable.PaintDrawable": PaintDrawable,
        "android.graphics.Paint": Paint,
        "android.graphics.Paint$FontMetrics": Paint.FontMetrics,
        "android.graphics.Paint$Style": Paint.Style,
        "android.graphics.Paint$Cap": Paint.Cap,
        "android.graphics.Paint$Join": Paint.Join,
        "android.graphics.Paint$Align": Paint.Align,
        "android.graphics.Canvas": Canvas,
        "android.graphics.Path": Path,
        "androidx.core.graphics.PathParser": PathParser,
        "android.graphics.PathMeasure": PathMeasure,
        "android.graphics.Rect": Rect,
        "android.graphics.RectF": RectF,
        "android.graphics.Matrix": Matrix,
        "android.graphics.Shader": Shader,
        "android.graphics.Shader$TileMode": Shader.TileMode,
        "android.graphics.LinearGradient": LinearGradient,
        "android.graphics.RadialGradient": RadialGradient,
        "android.graphics.BitmapShader": BitmapShader,
        "android.graphics.ComposeShader": ComposeShader,
        "android.graphics.SweepGradient": SweepGradient,
        "android.graphics.PathEffect": PathEffect,
        "android.graphics.DashPathEffect": DashPathEffect,
        "android.graphics.CornerPathEffect": CornerPathEffect,
        "android.graphics.ComposePathEffect": ComposePathEffect,
        "android.graphics.SumPathEffect": SumPathEffect,
        "android.graphics.ColorMatrix": ColorMatrix,
        "android.graphics.ColorMatrixColorFilter": ColorMatrixColorFilter,
        "android.graphics.PixelFormat": PixelFormat,
        "android.graphics.ImageFormat": ImageFormat,
        "android.graphics.BlendMode": BlendMode,
        "android.graphics.Xfermode": Xfermode,
        "android.graphics.PorterDuff": PorterDuff,
        "android.graphics.PorterDuff$Mode": PorterDuff.Mode,
        "android.graphics.PorterDuffXfermode": PorterDuffXfermode,
        "android.graphics.ColorFilter": ColorFilter,
        "android.graphics.PorterDuffColorFilter": PorterDuffColorFilter,
        "android.graphics.LightingColorFilter": LightingColorFilter,
        "androidx.core.content.ContextCompat": ContextCompat,
        "android.text.InputType": InputType,
        "android.text.TextWatcher": TextWatcher,
        "org.telegram.messenger.SharedConfig": SharedConfig,
        "org.telegram.messenger.FileLog": FileLog,
        "org.telegram.messenger.Utilities$IndexedConsumer": IndexedConsumer,
        "java.lang.Runnable": Runnable,
        "java.lang.Thread": Thread,
        "com.chaquo.python.PyException": PyException,
        "android.os.Build": Build,
        "android.os.StatFs": StatFs,
        "android.os.BatteryManager": BatteryManager,
        "android.text.TextUtils": TextUtils,
        "android.util.Log": Log,
        "android.os.SystemClock": SystemClock,
        "android.text.Html": Html,
        "android.text.method.LinkMovementMethod": LinkMovementMethod,
        "android.text.method.ScrollingMovementMethod": ScrollingMovementMethod,
        "android.text.method.ArrowKeyMovementMethod": ArrowKeyMovementMethod,
        "android.text.method.MovementMethod": MovementMethod,
        "android.text.method.BaseMovementMethod": BaseMovementMethod,
        "android.text.method.InputFilter": InputFilter,
        "android.text.method.InputFilter$AllCaps": InputFilter.AllCaps,
        "android.text.method.InputFilter$LengthFilter": InputFilter.LengthFilter,
        "android.text.method.NumberKeyListener": NumberKeyListener,
        "android.text.method.DigitsKeyListener": DigitsKeyListener,
        "android.text.method.TransformationMethod": TransformationMethod,
        "android.text.method.PasswordTransformationMethod": PasswordTransformationMethod,
        "android.text.method.HideReturnsTransformationMethod": HideReturnsTransformationMethod,
        "android.text.method.SingleLineTransformationMethod": SingleLineTransformationMethod,
        "android.text.method.MetaKeyKeyListener": MetaKeyKeyListener,
        "android.util.Base64": Base64,
        "java.lang.Integer": Integer,
        "java.lang.Long": Long,
        "java.lang.Short": Short,
        "java.lang.Byte": Byte,
        "java.lang.Void": Void,
        "java.lang.reflect.Modifier": Modifier,
        "java.lang.Double": Double,
        "java.lang.Float": Float,
        "java.lang.Boolean": Boolean,
        "java.lang.String": String,
        "java.lang.Math": Math,
        "java.lang.System": System,
        "java.lang.Character": Character,
        "java.util.Random": Random,
        "java.util.UUID": UUID,
        "java.util.concurrent.atomic.AtomicInteger": AtomicInteger,
        "java.util.concurrent.atomic.AtomicLong": AtomicLong,
        "java.util.concurrent.atomic.AtomicBoolean": AtomicBoolean,
        "java.util.concurrent.TimeUnit": TimeUnit,
        "java.util.concurrent.Executors": Executors,
        "android.os.AsyncTask": AsyncTask,
        "java.util.Locale": Locale,
        "java.util.Calendar": Calendar,
        "java.util.TimeZone": TimeZone,
        "java.text.DateFormat": JavaDateFormat,
        "android.text.format.DateFormat": DateFormat,
        "android.os.Bundle": Bundle,
        "android.os.Message": Message,
        "android.os.Parcel": Parcel,
        "android.os.Parcelable": Parcelable,
        "android.os.Parcelable$Creator": Parcelable.Creator,
        "android.os.IBinder": IBinder,
        "android.os.Binder": Binder,
        "android.net.Uri": Uri,
        "android.net.NetworkInfo": NetworkInfo,
        "android.net.NetworkCapabilities": NetworkCapabilities,
        "android.net.ConnectivityManager": ConnectivityManager,
        "android.net.ConnectivityManager$NetworkCallback": ConnectivityManager.NetworkCallback,
        "android.net.nsd.NsdManager": NsdManager,
        "android.net.nsd.NsdServiceInfo": NsdServiceInfo,
        "android.net.nsd.NsdManager$RegistrationListener": NsdManager.RegistrationListener,
        "android.net.nsd.NsdManager$DiscoveryListener": NsdManager.DiscoveryListener,
        "android.net.nsd.NsdManager$ResolveListener": NsdManager.ResolveListener,
        "android.net.wifi.WifiManager": WifiManager,
        "android.net.wifi.WifiInfo": WifiInfo,
        "android.net.wifi.ScanResult": ScanResult,
        "android.net.wifi.WifiConfiguration": WifiConfiguration,
        "android.net.Uri$Builder": UriBuilder,
        "android.location.Location": Location,
        "android.location.LocationManager": LocationManager,
        "android.location.LocationListener": LocationListener,
        "android.location.Criteria": Criteria,
        "android.location.Geocoder": Geocoder,
        "android.hardware.Sensor": Sensor,
        "android.hardware.SensorEvent": SensorEvent,
        "android.hardware.SensorEventListener": SensorEventListener,
        "android.hardware.SensorManager": SensorManager,
        "android.telephony.TelephonyManager": TelephonyManager,
        "android.app.ActivityManager": ActivityManager,
        "android.app.ActivityManager$TaskDescription": ActivityManager.TaskDescription,
        "android.app.ActivityManager$AppTask": ActivityManager.AppTask,
        "android.app.ActivityManager$MemoryInfo": ActivityManager.MemoryInfo,
        "android.content.pm.ShortcutInfo": ShortcutInfo,
        "android.content.pm.ShortcutInfo$Builder": ShortcutInfo.Builder,
        "android.content.pm.ShortcutManager": ShortcutManager,
        "android.graphics.drawable.Icon": Icon,
        "android.os.Environment": Environment,
        "android.os.PowerManager": PowerManager,
        "android.os.Vibrator": Vibrator,
        "android.os.HandlerThread": HandlerThread,
        "android.os.Process": Process,
        "android.provider.Settings": Settings,
        "android.content.ContentResolver": ContentResolver,
        "androidx.core.content.FileProvider": FileProvider,
        "android.support.v4.content.FileProvider": FileProvider,
        "android.os.Looper": Looper,
        "android.os.Handler": Handler,
        "android.os.CountDownTimer": CountDownTimer,
        "android.util.SparseArray": SparseArray,
        "android.util.LongSparseArray": SparseArray,
        "android.util.SparseIntArray": SparseArray,
        "android.util.SparseLongArray": SparseArray,
        "android.util.SparseBooleanArray": SparseArray,
        "android.util.DisplayMetrics": DisplayMetrics,
        "android.util.TypedValue": TypedValue,
        "android.content.res.Resources": Resources,
        "android.content.res.AssetManager": AssetManager,
        "android.content.res.ColorStateList": ColorStateList,
        "android.content.res.Configuration": Configuration,
        "android.graphics.Typeface": Typeface,
        "android.os.VibrationEffect": VibrationEffect,
        "android.media.MediaMetadataRetriever": MediaMetadataRetriever,
        "org.telegram.messenger.MediaMetadataRetriever": MediaMetadataRetriever,
        "android.media.MediaPlayer": MediaPlayer,
        "android.media.AudioManager": AudioManager,
        "android.media.SoundPool": SoundPool,
        "android.media.SoundPool$OnLoadCompleteListener": SoundPool.OnLoadCompleteListener,
        "androidx.collection.SparseArrayCompat": SparseArray,
        "androidx.collection.LongSparseArray": SparseArray,
        "android.util.ArrayMap": ArrayMap,
        "androidx.collection.ArrayMap": ArrayMap,
        "android.util.ArraySet": ArraySet,
        "androidx.collection.ArraySet": ArraySet,
        "android.util.Pair": Pair,
        "androidx.core.util.Pair": Pair,
        "android.text.SpannableString": SpannableString,
        "android.text.style.CharacterStyle": CharacterStyle,
        "android.text.style.MetricAffectingSpan": MetricAffectingSpan,
        "android.text.style.ReplacementSpan": ReplacementSpan,
        "android.text.style.ForegroundColorSpan": ForegroundColorSpan,
        "android.text.style.BackgroundColorSpan": BackgroundColorSpan,
        "android.text.style.StyleSpan": StyleSpan,
        "android.text.style.TypefaceSpan": TypefaceSpan,
        "android.text.style.RelativeSizeSpan": RelativeSizeSpan,
        "android.text.style.AbsoluteSizeSpan": AbsoluteSizeSpan,
        "android.text.style.ScaleXSpan": ScaleXSpan,
        "android.text.style.UnderlineSpan": UnderlineSpan,
        "android.text.style.StrikethroughSpan": StrikethroughSpan,
        "android.text.style.SuperscriptSpan": SuperscriptSpan,
        "android.text.style.SubscriptSpan": SubscriptSpan,
        "android.text.style.MaskFilterSpan": MaskFilterSpan,
        "android.text.style.ClickableSpan": ClickableSpan,
        "android.text.style.URLSpan": URLSpan,
        "android.text.style.ImageSpan": ImageSpan,
        "android.text.style.TextAppearanceSpan": TextAppearanceSpan,
        "android.text.style.LocaleSpan": LocaleSpan,
        "android.text.SpannableStringBuilder": SpannableStringBuilder,
        "android.text.Editable": Editable,
        "android.text.Selection": Selection,
        "android.text.TextPaint": TextPaint,
        "android.text.Layout": Layout,
        "android.text.StaticLayout": StaticLayout,
        "android.text.DynamicLayout": DynamicLayout,
        "android.text.SpannedString": SpannableString,
        "java.io.FileInputStream": FileInputStream,
        "java.io.FileOutputStream": FileOutputStream,
        "java.io.ByteArrayOutputStream": ByteArrayOutputStream,
        "java.io.DataInputStream": DataInputStream,
        "java.io.DataOutputStream": DataOutputStream,
        "java.io.RandomAccessFile": RandomAccessFile,
        "java.io.FileReader": FileReader,
        "java.io.FileWriter": FileWriter,
        "java.io.InputStreamReader": InputStreamReader,
        "java.io.BufferedReader": BufferedReader,
        "java.net.URL": URL,
        "java.net.URI": URI,
        "java.net.URLConnection": URLConnection,
        "java.net.HttpURLConnection": HttpURLConnection,
        "java.net.Socket": Socket,
        "java.net.ServerSocket": ServerSocket,
        "java.net.InetAddress": InetAddress,
        "java.net.InetSocketAddress": InetSocketAddress,
        "javax.net.ssl.HttpsURLConnection": HttpsURLConnection,
        "javax.crypto.Cipher": JavaCipher,
        "javax.crypto.Mac": JavaMac,
        "javax.crypto.spec.SecretKeySpec": JavaSecretKeySpec,
        "javax.crypto.spec.IvParameterSpec": JavaIvParameterSpec,
        "java.security.MessageDigest": JavaMessageDigest,
        "java.security.SecureRandom": SecureRandom,
        "java.security.KeyFactory": JavaKeyFactory,
        "java.security.Signature": JavaSignature,
        "java.security.spec.X509EncodedKeySpec": JavaX509EncodedKeySpec,
        "dalvik.system.DexClassLoader": JavaDexClassLoader,
        "java.io.BufferedWriter": BufferedWriter,
        "android.util.LruCache": LruCache,
        "java.util.regex.Pattern": Pattern,
        "java.util.regex.Matcher": Matcher,
        "java.lang.StringBuilder": StringBuilder,
        "java.util.Date": Date,
        "java.util.Base64": JavaBase64,
        "java.nio.charset.StandardCharsets": StandardCharsets,
        "java.nio.charset.Charset": Charset,
        "java.nio.ByteBuffer": ByteBuffer,
        "java.util.Timer": Timer,
        "java.util.TimerTask": TimerTask,
        "android.graphics.Color": Color,
        "android.graphics.Bitmap": Bitmap,
        "android.graphics.Bitmap$CompressFormat": Bitmap.CompressFormat,
        "android.graphics.BitmapFactory": BitmapFactory,
        "android.graphics.BitmapFactory$Options": _BitmapFactoryOptions,
        "android.content.ContentValues": ContentValues,
        "android.content.ComponentName": ComponentName,
        "android.content.BroadcastReceiver": BroadcastReceiver,
        "android.content.IntentFilter": IntentFilter,
        "android.content.ContextWrapper": ContextWrapper,
        "android.database.Cursor": AndroidCursor,
        "android.database.sqlite.SQLiteDatabase": AndroidSQLiteDatabase,
        "android.database.sqlite.SQLiteOpenHelper": AndroidSQLiteOpenHelper,
        "android.database.sqlite.SQLiteStatement": AndroidSQLiteStatement,
        "android.content.pm.PackageManager": PackageManager,
        "android.content.pm.PackageInfo": PackageInfo,
        "android.content.pm.ApplicationInfo": ApplicationInfo,
        "org.telegram.messenger.BuildConfig": BuildConfig,
        "android.widget.Toast": Toast,
        "org.telegram.ui.ActionBar.Theme": Theme,
        "org.telegram.ui.Components.BulletinFactory": BulletinFactory,
        "org.telegram.ui.Components.ItemOptions": ItemOptions,
        "android.content.SharedPreferences": SharedPreferences,
        "android.preference.PreferenceManager": PreferenceManager,
        "android.content.Context": Context,
        "android.content.Intent": Intent,
        "android.content.ClipData": ClipData,
        "android.content.ClipboardManager": ClipboardManager,
        "android.util.Patterns": Patterns,
        "java.text.SimpleDateFormat": SimpleDateFormat,
        "java.text.DecimalFormat": DecimalFormat,
        "java.text.MessageFormat": MessageFormat,
        "java.time.Instant": JavaInstant,
        "java.time.Duration": JavaDuration,
        "java.time.LocalDate": JavaLocalDate,
        "java.time.LocalDateTime": JavaLocalDateTime,
        "java.time.LocalTime": JavaLocalTime,
        "java.time.ZoneId": JavaZoneId,
        "java.time.ZoneOffset": JavaZoneOffset,
        "java.time.format.DateTimeFormatter": JavaDateTimeFormatter,
        "org.json.JSONObject": JSONObject,
        "org.json.JSONArray": JSONArray,
        "org.json.JSONException": JSONException,
    }
    try:
        from ui.alert import AlertDialog as _AlertDialogClass

        mapping["org.telegram.ui.ActionBar.AlertDialog"] = _AlertDialogClass
    except Exception:
        pass
    try:
        from ui.bulletin import Bulletin as _BulletinMarker

        mapping["org.telegram.ui.Components.Bulletin"] = _BulletinMarker
    except Exception:
        pass
    mapping.update({
        "org.telegram.messenger.DispatchQueue": DispatchQueue,
        "org.telegram.messenger.ImageLoader": ImageLoader,
        "org.telegram.messenger.R": R,
        "org.telegram.ui.Cells.ChatMessageCell": ChatMessageCell,
        "com.exteragram.messenger.plugins.Plugin": Plugin,
        "com.exteragram.messenger.plugins.hooks.PluginsHooks": PluginsHooks,
        "com.exteragram.messenger.plugins.ui.components.RequiredPluginInfo": RequiredPluginInfo,
        "com.exteragram.messenger.plugins.ui.components.PluginCellDelegate": PluginCellDelegate,
        "com.exteragram.messenger.plugins.ui.components.InstallPluginBottomSheet": InstallPluginBottomSheet,
        "com.exteragram.messenger.plugins.ui.PluginsInfoActivity": PluginsInfoActivity,
        "com.exteragram.messenger.plugins.ui.PluginsActivity": PluginsActivity,
        "com.exteragram.messenger.plugins.ui.PluginSettingsActivity": PluginSettingsActivity,
        "com.exteragram.messenger.plugins.xposed.PyMethodHook": PyMethodHook,
        "com.exteragram.messenger.plugins.xposed.PyMethodReplacement": PyMethodReplacement,
    })
    # Keep the Java name visible, as plugins and the hook layer look classes up
    # by `__name__` (or print it in a log).
    for java_name, value in mapping.items():
        try:
            value.__name__ = java_name
        except (AttributeError, TypeError):
            pass
    return mapping
