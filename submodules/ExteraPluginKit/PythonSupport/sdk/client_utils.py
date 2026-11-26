# This is the iOS counterpart of the exteraGram plugins SDK.
#
# The module keeps every public name of `client_utils`: send helpers, account
# lookups, `AccountClient` and the controller getters.  On Android the getters
# return Java controllers; here they return `ObjectProxy` values that forward a
# known set of methods to the Swift host (`java.call`).  A method the host does
# not implement raises a precise `PluginError` rather than returning a silent
# None.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import contextlib
import contextvars
import os
import threading
import traceback
from typing import Optional

import _sdk_version
import extera_ios
from extera_utils.classes import ObjectProxy
from extera_utils.get_caller import get_plugin_id
from extera_utils.lifecycle import bind_request, bind_task, capture_scope
from extera_utils.text_formatting import parse_text
from log_utils import log


STAGE_QUEUE = "stageQueue"
GLOBAL_QUEUE = "globalQueue"
CACHE_CLEAR_QUEUE = "cacheClearQueue"
SEARCH_QUEUE = "searchQueue"
PHONE_BOOK_QUEUE = "phoneBookQueue"
THEME_QUEUE = "themeQueue"
EXTERNAL_NETWORK_QUEUE = "externalNetworkQueue"
PLUGINS_QUEUE = "pluginsQueue"

_hook_account = contextvars.ContextVar("extera_hook_account", default=None)
_warned_account_mismatches = set()


def get_selected_account():
    return extera_ios.current_account()


def get_hook_account():
    return _hook_account.get()


@contextlib.contextmanager
def account_scope(account):
    token = _hook_account.set(account)
    try:
        yield
    finally:
        _hook_account.reset(token)


def _resolve_account(account, helper):
    if account is not None:
        return int(account)
    selected = extera_ios.current_account()
    hook_account = _hook_account.get()
    if hook_account is not None and hook_account != selected:
        key = (helper, hook_account, selected)
        if key not in _warned_account_mismatches:
            _warned_account_mismatches.add(key)
            log(
                "%s() is using account %s because it is the one selected in the UI, "
                "but it was called while handling account %s. Pass account=%s, or use "
                "get_client(%s), if you meant that account. Logged once per helper."
                % (helper, selected, hook_account, hook_account, hook_account)
            )
    return selected


class _QueueHandle:
    """Handle returned by `_Queue.postRunnable`, with Android-style `cancel`."""

    def __init__(self, event, thread):
        self._event = event
        self._thread = thread

    def cancel(self):
        self._event.set()

    def isCancelled(self):
        return self._event.is_set()

    def join(self, timeout=None):
        self._thread.join(timeout)


class _Queue:
    """Android's `DispatchQueue`: a background worker, not the UI thread."""

    def __init__(self, name):
        self.name = str(name or "extera-queue")

    def postRunnable(self, runnable, delay=0):
        function = runnable.run if hasattr(runnable, "run") else runnable
        if not callable(function):
            return None
        event = threading.Event()

        def runner():
            delay_seconds = max(0.0, float(delay or 0) / 1000.0)
            if delay_seconds and event.wait(delay_seconds):
                return
            if event.is_set():
                return
            try:
                function()
            except Exception:
                log("Error in queue task: %s" % traceback.format_exc())

        thread = threading.Thread(target=runner, daemon=True, name=self.name)
        thread.start()
        return _QueueHandle(event, thread)

    def cancelRunnable(self, handle):
        if hasattr(handle, "cancel"):
            handle.cancel()
        elif hasattr(handle, "set"):
            handle.set()

    def getQueueName(self):
        return self.name

    def recycle(self):
        return None


def get_queue_by_name(queue_name):
    return _Queue(queue_name)


def run_on_queue(fn, queue_name=PLUGINS_QUEUE, delay=0):
    """Runs `fn` on a background queue, like Android's `DispatchQueue`."""
    if not callable(fn):
        return None
    _, plugin_id = get_plugin_id(fn)
    scheduled_account = _hook_account.get()

    def wrapped():
        with account_scope(scheduled_account):
            import _extera_runtime

            _extera_runtime.execute_plugin_callback(plugin_id, fn)

    callback = bind_task(wrapped, once=True, scope=capture_scope(fn))
    queue = get_queue_by_name(queue_name)
    handle = queue.postRunnable(callback, delay)
    if handle is not None:
        callback.set_cancel(handle.cancel)
    return callback


def _account_instance(account, helper):
    return ObjectProxy("org.telegram.messenger.AccountInstance", data={
        "account": _resolve_account(account, helper),
    })


def get_account_instance(account=None):
    return _account_instance(account, "get_account_instance")


def _controller(account, helper, class_name):
    value = _account_instance(account, helper)
    return ObjectProxy(class_name, data={"account": value.to_dict()["account"]})


def get_messages_controller(account=None):
    return _controller(account, "get_messages_controller", "org.telegram.messenger.MessagesController")


def get_contacts_controller(account=None):
    return _controller(account, "get_contacts_controller", "org.telegram.messenger.ContactsController")


def get_media_data_controller(account=None):
    return _controller(account, "get_media_data_controller", "org.telegram.messenger.MediaDataController")


def get_connections_manager(account=None):
    return _controller(account, "get_connections_manager", "org.telegram.tgnet.ConnectionsManager")


def get_location_controller(account=None):
    return _controller(account, "get_location_controller", "org.telegram.messenger.LocationController")


def get_notifications_controller(account=None):
    return _controller(account, "get_notifications_controller", "org.telegram.messenger.NotificationsController")


def get_messages_storage(account=None):
    return _controller(account, "get_messages_storage", "org.telegram.messenger.MessagesStorage")


def get_send_messages_helper(account=None):
    return _controller(account, "get_send_messages_helper", "org.telegram.messenger.SendMessagesHelper")


def get_file_loader(account=None):
    return _controller(account, "get_file_loader", "org.telegram.messenger.FileLoader")


def get_secret_chat_helper(account=None):
    return _controller(account, "get_secret_chat_helper", "org.telegram.messenger.SecretChatHelper")


def get_download_controller(account=None):
    return _controller(account, "get_download_controller", "org.telegram.messenger.DownloadController")


def get_notifications_settings(account=None):
    resolved = _resolve_account(account, "get_notifications_settings")
    try:
        from telegram_compat import NotificationsSettings

        return NotificationsSettings.getInstance(resolved)
    except Exception:
        return _controller(account, "get_notifications_settings", "org.telegram.messenger.NotificationsSettings")


def get_notification_center(account=None):
    resolved = _resolve_account(account, "get_notification_center")
    try:
        from telegram_compat import NotificationCenter

        return NotificationCenter.getInstance(resolved)
    except Exception:
        return extera_ios.host("client.notification_center", account=resolved)


def get_media_controller():
    return ObjectProxy("org.telegram.messenger.MediaController")


def get_user_config(account=None):
    return _controller(account, "get_user_config", "org.telegram.messenger.UserConfig")


def get_last_fragment():
    value = extera_ios.host("client.last_fragment")
    if isinstance(value, dict):
        try:
            from telegram_compat import ChatActivity

            return ChatActivity(value)
        except Exception:
            return value
    return value


# ---------------------------------------------------------------------------
# Sending


def _entities_to_host(entities):
    if not entities:
        return []
    result = []
    for entity in entities:
        if hasattr(entity, "to_json"):
            result.append(entity.to_json())
        elif isinstance(entity, dict):
            result.append(entity)
        else:
            driver = getattr(entity, "to_native", None)
            result.append(driver() if driver else {
                "type": getattr(entity, "type", "unknown"),
                "offset": getattr(entity, "offset", 0),
                "length": getattr(entity, "length", 0),
            })
    return result


def _location_coordinates(value):
    """Extracts `(lat, long)` from a location dict/TL object."""
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if isinstance(data, dict):
        latitude = data.get("lat", data.get("latitude"))
        longitude = data.get("long", data.get("longitude", data.get("lon")))
        if latitude is not None and longitude is not None:
            return float(latitude), float(longitude)
        nested = data.get("geo")
        if isinstance(nested, dict):
            return _location_coordinates(nested)
    latitude = getattr(value, "lat", None)
    if latitude is None:
        latitude = getattr(value, "latitude", None)
    longitude = getattr(value, "long", None)
    if longitude is None:
        longitude = getattr(value, "longitude", None)
    if latitude is not None and longitude is not None:
        return float(latitude), float(longitude)
    return None, None


def _reply_markup_payload(value):
    """Normalizes `TLRPC.TL_replyInlineMarkup` into the host's JSON shape."""
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if not isinstance(data, dict):
        return None
    rows = data.get("rows")
    if not isinstance(rows, list):
        buttons = data.get("buttons")
        rows = [buttons] if isinstance(buttons, list) else []
    result_rows = []
    for row in rows:
        row_data = row if isinstance(row, dict) else getattr(row, "_value", None)
        if not isinstance(row_data, dict):
            continue
        buttons = row_data.get("buttons")
        if not isinstance(buttons, list):
            buttons = [row_data]
        result_buttons = []
        for button in buttons:
            button_data = button if isinstance(button, dict) else getattr(button, "_value", None)
            if not isinstance(button_data, dict):
                continue
            raw_data = button_data.get("data")
            if isinstance(raw_data, (bytes, bytearray)):
                raw_data = bytes(raw_data).decode("utf-8", "ignore")
            result_buttons.append({
                "text": str(button_data.get("text") or ""),
                "url": button_data.get("url") if isinstance(button_data.get("url"), str) else None,
                "data": raw_data if isinstance(raw_data, str) else None,
            })
        if result_buttons:
            result_rows.append(result_buttons)
    return {"rows": result_rows} if result_rows else None


def _message_id(value):
    """Extracts an Android message id from an int/dict/MessageObject."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = "".join(character for character in value if character.isdigit())
        return int(digits) if digits else 0
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if isinstance(data, dict):
        for key in ("id", "message_id", "msg_id"):
            if data.get(key) is not None:
                try:
                    return int(data[key])
                except (TypeError, ValueError):
                    return 0
    for attribute in ("getId", "get_id", "id", "message_id"):
        try:
            candidate = getattr(value, attribute)
            if callable(candidate):
                candidate = candidate()
            if candidate is not None:
                return int(candidate)
        except Exception:
            continue
    return 0


def cast_to_array_list(values):
    """Android's `ArrayList` cast used by `SendMessageParams`."""
    from extera_utils.classes import NativeList

    result = NativeList()
    for value in values or []:
        result.add(value)
    return result


def cast_to_hash_map(values):
    """Android's `HashMap` cast used by `SendMessageParams.params`."""
    from extera_utils.classes import NativeMap

    if not values:
        return None
    result = NativeMap()
    for key, value in values.items():
        result.put(str(key), str(value))
    return result


def _poll_payload(value):
    """Normalizes a `TL_poll`/`TL_messageMediaPoll`/`TL_inputMediaPoll` value.

    The returned dictionary is the shape `messages.sendMedia` expects:
    `{"question": ..., "question_entities": [...], "answers": [...]}` plus the
    poll's flags, deadline, countries and solution.
    """
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if isinstance(data, dict) and str(data.get("_") or "").lower() in (
        "inputmediapoll", "tl_inputmediapoll",
    ):
        nested = data.get("poll")
        if isinstance(nested, dict):
            data = nested
    if isinstance(data, dict) and str(data.get("_") or "").lower() in (
        "messagemediapoll", "tl_messagemediapoll",
    ):
        nested = data.get("poll")
        if isinstance(nested, dict):
            data = nested
    if not isinstance(data, dict):
        inner = getattr(value, "poll", None)
        if inner is not None:
            data = inner if isinstance(inner, dict) else getattr(inner, "_value", None)
    if not isinstance(data, dict):
        return None

    question = data.get("question")
    if isinstance(question, dict):
        question = question.get("text") or question.get("message") or ""
    question_text = str(question or data.get("text") or data.get("message") or "")
    question_entities = _entities_to_host(
        data.get("question_entities") or data.get("entities") or []
    )

    answers_value = data.get("answers")
    if not isinstance(answers_value, list):
        answers_value = data.get("options")
    answers = []
    for answer in answers_value or []:
        item = answer if isinstance(answer, dict) else getattr(answer, "_value", None)
        if not isinstance(item, dict):
            item = {
                "text": getattr(answer, "text", None),
                "option": getattr(answer, "option", None),
                "entities": getattr(answer, "entities", None),
            }
        text = item.get("text")
        if isinstance(text, dict):
            text = text.get("text") or ""
        option = item.get("option")
        if isinstance(option, (bytes, bytearray)):
            import base64

            option = base64.b64encode(bytes(option)).decode("ascii")
        answers.append({
            "text": str(text or ""),
            "entities": _entities_to_host(item.get("entities") or []),
            "option": option if isinstance(option, str) else "",
            "correct": bool(item.get("correct")),
        })

    payload = {
        "question": question_text,
        "question_entities": question_entities,
        "answers": answers,
    }
    for key in (
        "closed",
        "public_voters",
        "multiple_choice",
        "quiz",
        "open_answers",
        "revoting_disabled",
        "shuffle_answers",
        "hide_results_until_close",
        "subscribers_only",
    ):
        if data.get(key) is not None:
            payload[key] = bool(data.get(key))
    for key in ("close_period", "close_date"):
        if data.get(key) is not None:
            payload[key] = int(data.get(key))
    countries = data.get("countries_iso2") or data.get("countries")
    if countries:
        payload["countries_iso2"] = [str(item) for item in countries]
    solution = data.get("solution")
    if solution:
        payload["solution"] = str(solution)
        payload["solution_entities"] = _entities_to_host(
            data.get("solution_entities") or []
        )
    correct = data.get("correct_answers")
    if isinstance(correct, (list, tuple)):
        for index in correct:
            try:
                payload["answers"][int(index)]["correct"] = True
            except (IndexError, TypeError, ValueError):
                pass
    return payload


def send_poll(peer, poll, caption="", *, account=None, entities=None, notify=True,
              schedule_date=0, reply_to=0, reply_markup=None, **kwargs):
    """Sends an `inputMediaPoll` through raw `messages.sendMedia`."""
    payload = _poll_payload(poll)
    if payload is None:
        return None
    resolved = _resolve_account(account, "send_poll")
    request = {
        "peer": int(peer or 0),
        "message": str(caption or ""),
        "entities": _entities_to_host(entities or []),
        "media": {"_": "inputMediaPoll", "poll": payload},
        "silent": not bool(notify),
        "schedule_date": int(schedule_date or 0),
        "reply_to_msg_id": int(reply_to) if isinstance(reply_to, int) else 0,
    }
    markup = _reply_markup_payload(reply_markup)
    if markup:
        request["reply_markup"] = markup
    return extera_ios.send_request(resolved, "messages.sendMedia", request)


def send_message(params, parse_mode=None, *, account=None):
    resolved = _resolve_account(account, "send_message")
    values = dict(params or {})

    if parse_mode:
        if parse_mode.lower() not in ("html", "markdown"):
            raise ValueError("Invalid parse mode: %s. Must be 'html' or 'markdown'." % parse_mode)
        text = values.get("message")
        caption = values.get("caption")
        if text:
            parsed = parse_text(text, parse_mode)
            values["message"] = parsed["message"]
            values["entities"] = parsed["entities"]
        elif caption:
            parsed = parse_text(caption, parse_mode)
            values["caption"] = parsed["message"]
            values["entities"] = parsed["entities"]

    location = values.get("location")
    if location is not None:
        latitude, longitude = _location_coordinates(location)
        if latitude is not None and longitude is not None:
            return send_location(
                values.get("peer"),
                latitude,
                longitude,
                account=resolved,
                accuracy_radius=values.get("accuracyRadius"),
                silent=not bool(values.get("notify", True)),
            )

    shared_user = values.get("user")
    if shared_user is not None:
        user_data = (
            shared_user
            if isinstance(shared_user, dict)
            else getattr(shared_user, "_value", None)
        )
        if isinstance(user_data, dict):
            phone = user_data.get("phone")
            if phone:
                return send_contact(
                    values.get("peer"),
                    phone,
                    user_data.get("first_name") or "",
                    user_data.get("last_name") or "",
                    account=resolved,
                )

    kind = "text"
    poll_value = values.get("poll")
    if poll_value is None:
        poll_params = values.get("pollSendParams")
        if poll_params is not None:
            poll_value = getattr(poll_params, "inputMediaPoll", None) or getattr(
                poll_params, "poll", None
            )
            if poll_value is None and isinstance(poll_params, dict):
                poll_value = poll_params.get("inputMediaPoll") or poll_params.get(
                    "poll"
                )
    if poll_value is not None:
        return send_poll(
            values.get("peer"),
            poll_value,
            values.get("message") or values.get("caption") or "",
            account=resolved,
            entities=values.get("entities"),
            notify=values.get("notify", True),
            schedule_date=values.get("scheduleDate") or 0,
            reply_to=values.get("replyToMsg") or 0,
            reply_markup=values.get("replyMarkup"),
        )

    path = values.get("path")
    if values.get("photo") is not None or (path and os.path.splitext(str(path))[1].lower()
                                           in (".jpg", ".jpeg", ".png", ".webp", ".heic")):
        kind = "photo"
    elif values.get("document") is not None or values.get("videoEditedInfo") is not None:
        kind = "document"
        extension = os.path.splitext(str(path or ""))[1].lower()
        if extension in (".mp4", ".mov", ".mkv"):
            kind = "video"
        elif extension in (".mp3", ".m4a", ".ogg", ".opus", ".flac"):
            kind = "audio"
    elif values.get("poll") is not None:
        kind = "poll"

    result = extera_ios.host(
        "client.send",
        account=resolved,
        kind=kind,
        peer=int(values.get("peer") or 0),
        text=values.get("message"),
        caption=values.get("caption"),
        entities=_entities_to_host(values.get("entities")),
        reply_markup=_reply_markup_payload(values.get("replyMarkup")),
        path=str(path) if path else None,
        reply_to=_message_id(values.get("replyToMsg")),
        reply_to_top=_message_id(values.get("replyToTopMsg")),
        silent=not bool(values.get("notify", True)),
        schedule_date=int(values.get("scheduleDate") or 0),
        schedule_repeat_period=int(values.get("scheduleRepeatPeriod") or 0),
        ttl=int(values.get("ttl") or 0),
        effect_id=int(values.get("effect_id") or 0),
        quick_reply_shortcut_id=int(values.get("quick_reply_shortcut_id") or 0),
        invert_media=bool(values.get("invert_media", False)),
        stars=int(values.get("stars") or 0),
        pay_stars=int(values.get("payStars") or 0),
        dice_stake=int(values.get("dice_stake") or 0),
        mono_forum_peer=int(values.get("monoForumPeer") or 0),
        sending_high_quality=bool(values.get("sendingHighQuality", False)),
        has_media_spoilers=bool(values.get("hasMediaSpoilers", False)),
        extra={key: value for key, value in values.items() if key not in {
            "peer", "message", "caption", "entities", "path", "notify", "scheduleDate",
            "replyToMsg", "replyToTopMsg", "photo", "document", "videoEditedInfo",
            "poll", "pollSendParams", "params", "scheduleRepeatPeriod", "ttl",
            "effect_id", "quick_reply_shortcut_id", "invert_media", "stars",
            "payStars", "dice_stake", "monoForumPeer", "sendingHighQuality",
            "hasMediaSpoilers",
        } and isinstance(value, (str, int, float, bool, type(None)))},
    )
    if not isinstance(result, dict):
        return result
    if not result.get("ok", False):
        log("Could not send the message: %s" % result.get("error", "unknown error"))
    return result


def send_text(peer, text, *, account=None, parse_mode=None, **kwargs):
    params = {"peer": peer, "message": text}
    params.update(kwargs)
    return send_message(params, parse_mode, account=_resolve_account(account, "send_text"))


def send_photo(peer, file_path, caption="", high_quality=False, *, account=None,
               parse_mode=None, **kwargs):
    params = {
        "peer": peer,
        "path": file_path,
        "caption": caption,
        "sendingHighQuality": bool(high_quality),
    }
    params.update(kwargs)
    return send_message(params, parse_mode, account=_resolve_account(account, "send_photo"))


def send_document(peer, file_path, caption="", *, account=None, parse_mode=None, **kwargs):
    params = {"peer": peer, "path": file_path, "caption": caption, "document": True}
    params.update(kwargs)
    return send_message(params, parse_mode, account=_resolve_account(account, "send_document"))


def send_video(peer, file_path, caption="", *, account=None, parse_mode=None, **kwargs):
    params = {"peer": peer, "path": file_path, "caption": caption, "document": True}
    params.update(kwargs)
    return send_message(params, parse_mode, account=_resolve_account(account, "send_video"))


def send_audio(peer, file_path, caption="", *, account=None, parse_mode=None, **kwargs):
    params = {"peer": peer, "path": file_path, "caption": caption, "document": True}
    params.update(kwargs)
    return send_message(params, parse_mode, account=_resolve_account(account, "send_audio"))


def _send_media_request(peer, media, helper, account=None, **kwargs):
    payload = {"peer": peer, "media": media}
    payload.update(kwargs)
    return extera_ios.send_request(
        _resolve_account(account, helper), "messages.sendMedia", payload
    )


def send_location(peer, latitude, longitude, *, account=None, accuracy_radius=None,
                  **kwargs):
    point = {"lat": float(latitude), "long": float(longitude)}
    if accuracy_radius is not None:
        point["accuracy_radius"] = int(accuracy_radius)
    media = {"_": "inputMediaGeoPoint", "geo_point": point}
    return _send_media_request(peer, media, "send_location", account=account, **kwargs)


def send_venue(peer, latitude, longitude, title, address="", *, account=None,
               provider="", venue_id="", venue_type="", **kwargs):
    media = {
        "_": "inputMediaVenue",
        "geo_point": {"lat": float(latitude), "long": float(longitude)},
        "title": str(title or ""),
        "address": str(address or ""),
        "provider": str(provider or ""),
        "venue_id": str(venue_id or ""),
        "venue_type": str(venue_type or ""),
    }
    return _send_media_request(peer, media, "send_venue", account=account, **kwargs)


def send_contact(peer, phone_number, first_name, last_name="", *, account=None,
                 vcard="", **kwargs):
    media = {
        "_": "inputMediaContact",
        "phone_number": str(phone_number or ""),
        "first_name": str(first_name or ""),
        "last_name": str(last_name or ""),
        "vcard": str(vcard or ""),
    }
    return _send_media_request(peer, media, "send_contact", account=account, **kwargs)


def send_dice(peer, emoticon="🎲", *, account=None, **kwargs):
    media = {"_": "inputMediaDice", "emoticon": str(emoticon or "🎲")}
    return _send_media_request(peer, media, "send_dice", account=account, **kwargs)


def _document_media_payload(document, query=""):
    data = document if isinstance(document, dict) else getattr(document, "_value", None)
    if not isinstance(data, dict):
        return None
    nested = data.get("document")
    if isinstance(nested, dict):
        data = nested
    identifier = data.get("id")
    if identifier is None:
        return None
    payload = {
        "_": "inputMediaDocument",
        "id": int(identifier),
        "access_hash": int(data.get("access_hash") or 0),
        "query": str(query or ""),
    }
    reference = data.get("file_reference")
    if isinstance(reference, (bytes, bytearray)):
        import base64

        payload["file_reference"] = base64.b64encode(bytes(reference)).decode("ascii")
    elif isinstance(reference, str) and reference:
        payload["file_reference"] = reference
    return payload


def _photo_media_payload(photo):
    data = photo if isinstance(photo, dict) else getattr(photo, "_value", None)
    if not isinstance(data, dict):
        return None
    nested = data.get("photo")
    if isinstance(nested, dict):
        data = nested
    identifier = data.get("id")
    if identifier is None:
        return None
    payload = {
        "_": "inputMediaPhoto",
        "id": int(identifier),
        "access_hash": int(data.get("access_hash") or 0),
    }
    reference = data.get("file_reference")
    if isinstance(reference, (bytes, bytearray)):
        import base64

        payload["file_reference"] = base64.b64encode(bytes(reference)).decode("ascii")
    elif isinstance(reference, str) and reference:
        payload["file_reference"] = reference
    return payload


def send_sticker(peer, sticker, query="", *, account=None, **kwargs):
    payload = _document_media_payload(sticker, query)
    if payload is None:
        return None
    return _send_media_request(peer, payload, "send_sticker", account=account, **kwargs)


def send_existing_photo(peer, photo, *, account=None, **kwargs):
    payload = _photo_media_payload(photo)
    if payload is None:
        return None
    return _send_media_request(
        peer, payload, "send_existing_photo", account=account, **kwargs
    )


def edit_message(message_obj, text=None, file_path=None, with_spoiler=False, *,
                 account=None, parse_mode=None, **kwargs):
    if message_obj is None:
        log("'message_obj' must be a valid message object.")
        return None
    if text is None and file_path is None:
        log("edit_message called with no changes (text or file_path). Cancelled.")
        return None
    if file_path and not os.path.exists(file_path):
        log("Media file not found at path: %s" % file_path)
        return None

    message_id = message_obj
    peer = 0
    if hasattr(message_obj, "get_id"):
        message_id = message_obj.get_id()
        peer = getattr(message_obj, "peer_id", 0) or 0
    elif hasattr(message_obj, "getId"):
        message_id = message_obj.getId()
        peer = getattr(message_obj, "dialogId", 0) or getattr(message_obj, "dialog_id", 0) or 0
    elif isinstance(message_obj, dict):
        message_id = message_obj.get("id") or message_obj.get("message_id")
        peer = message_obj.get("peer") or message_obj.get("peer_id") or 0

    entities = None
    if text is not None and parse_mode:
        parsed = parse_text(text, parse_mode)
        text = parsed["message"]
        entities = parsed["entities"]

    return extera_ios.edit_message(
        _resolve_account(account, "edit_message"),
        peer,
        message_id,
        text=text,
        entities=entities,
        path=file_path,
        extra=kwargs,
    )


def _tl_name(value):
    if isinstance(value, dict):
        return str(value.get("_") or "").lower()
    return ""


def _dialog_id_from_input_peer(value, account=0):
    """Converts a TL `InputPeer` into Android's signed dialog id."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if not isinstance(data, dict):
        return None
    constructor = _tl_name(data)
    if constructor.endswith("inputpeeruser"):
        return int(data.get("user_id") or 0)
    if constructor.endswith("inputpeerchat"):
        return -int(data.get("chat_id") or 0)
    if constructor.endswith("inputpeerchannel"):
        return -1000000000000 - int(data.get("channel_id") or 0)
    if constructor.endswith("inputpeerself"):
        try:
            import extera_ios

            user = extera_ios.get_me(account) or {}
            return int(user.get("id") or account)
        except Exception:
            return account
    if constructor.endswith("inputpeerempty"):
        return 0
    return None


def _normalize_reply(payload):
    reply = payload.get("reply_to")
    if isinstance(reply, dict):
        message_id = reply.get("reply_to_msg_id") or reply.get("reply_to_id")
        if message_id is not None and payload.get("reply_to_msg_id") is None:
            payload["reply_to_msg_id"] = int(message_id)
        top = reply.get("reply_to_top_id")
        if top is not None and payload.get("reply_to_top_id") is None:
            payload["reply_to_top_id"] = int(top)
    return payload


def _normalize_input_media(value):
    """Flattens `InputMediaPhoto`/`InputMediaDocument` for the host handlers."""
    data = value if isinstance(value, dict) else getattr(value, "_value", None)
    if not isinstance(data, dict):
        return value
    constructor = _tl_name(data)
    result = dict(data)
    if constructor.endswith("inputmediaphoto") or constructor.endswith(
        "inputmediadocument"
    ):
        nested = data.get("id")
        if isinstance(nested, dict):
            result["id"] = nested.get("id") or 0
            result["access_hash"] = nested.get("access_hash") or 0
            result["file_reference"] = nested.get("file_reference") or ""
    return result


def send_request(request, fn, *, account=None):
    resolved = _resolve_account(account, "send_request")
    name = None
    payload = {}
    if isinstance(request, dict):
        name = request.get("_") or request.get("name")
        payload = dict(request)
    elif hasattr(request, "to_native"):
        name, payload = request.to_native()
    elif hasattr(request, "get_name"):
        name = request.get_name()
        payload = dict(getattr(request, "fields", {}) or {})
    if not name:
        raise ValueError("send_request expects a request object with a constructor name")
    payload = dict(payload or {})

    # TL requests carry `InputPeer` values; the iOS request handlers use the
    # signed dialog id, so normalize every peer-shaped field.
    for key in ("peer", "to_peer", "from_peer"):
        if key in payload:
            converted = _dialog_id_from_input_peer(payload[key], resolved)
            if converted is not None:
                payload[key] = converted
    _normalize_reply(payload)

    callback = bind_request(fn)
    if name in ("messages.sendMessage", "messages.sendText"):
        result = send_message({
            "peer": payload.get("peer", 0),
            "message": payload.get("message"),
            "replyToMsg": payload.get("reply_to_msg_id")
            or payload.get("reply_to"),
            "entities": payload.get("entities"),
            "notify": not bool(payload.get("silent", False)),
        }, account=resolved)
        callback(result, None)
        return 0

    if name in ("messages.sendMedia", "messages.send_media"):
        payload["media"] = _normalize_input_media(payload.get("media"))
        result = extera_ios.send_request(resolved, "messages.sendMedia", payload)
        if isinstance(result, dict) and result.get("error"):
            callback(result.get("response"), result["error"])
        else:
            callback(
                result.get("response") if isinstance(result, dict) else result,
                None,
            )
        return result.get("id", 0) if isinstance(result, dict) else 0

    if name in ("messages.sendMultiMedia", "messages.send_multi_media"):
        # Albums are sent one media at a time; the host has no multi-media
        # handler and a split album is the closest behaviour iOS can offer.
        media_items = payload.get("multi_media") or payload.get("media") or []
        peer = payload.get("peer", 0)
        results = []
        for item in media_items:
            data = item if isinstance(item, dict) else getattr(item, "_value", None)
            if not isinstance(data, dict):
                continue
            request_payload = {
                "peer": peer,
                "media": _normalize_input_media(data.get("media")),
                "message": data.get("message") or "",
                "entities": data.get("entities") or [],
                "random_id": data.get("random_id"),
                "silent": bool(payload.get("silent", False)),
                "schedule_date": payload.get("schedule_date") or 0,
            }
            reply = data.get("reply_to") or payload.get("reply_to")
            if isinstance(reply, dict):
                request_payload["reply_to_msg_id"] = (
                    reply.get("reply_to_msg_id") or 0
                )
            results.append(
                extera_ios.send_request(
                    resolved, "messages.sendMedia", request_payload
                )
            )
        callback(results, None)
        return (
            results[0].get("id", 0)
            if results and isinstance(results[0], dict)
            else 0
        )

    result = extera_ios.send_request(resolved, name, payload)
    if isinstance(result, dict) and result.get("error"):
        callback(result.get("response"), result["error"])
    else:
        callback(result.get("response") if isinstance(result, dict) else result, None)
    return result.get("id", 0) if isinstance(result, dict) else 0


class AccountClient:
    __slots__ = ("account",)

    def __init__(self, account):
        if account is None:
            raise ValueError("AccountClient requires an account; use the module level helpers "
                             "for the selected one")
        self.account = int(account)

    def __repr__(self):
        return "AccountClient(account=%s)" % self.account

    def __eq__(self, other):
        return isinstance(other, AccountClient) and other.account == self.account

    def __hash__(self):
        return hash((AccountClient, self.account))

    def get_account_instance(self):
        return get_account_instance(self.account)

    def get_messages_controller(self):
        return get_messages_controller(self.account)

    def get_contacts_controller(self):
        return get_contacts_controller(self.account)

    def get_media_data_controller(self):
        return get_media_data_controller(self.account)

    def get_connections_manager(self):
        return get_connections_manager(self.account)

    def get_location_controller(self):
        return get_location_controller(self.account)

    def get_notifications_controller(self):
        return get_notifications_controller(self.account)

    def get_messages_storage(self):
        return get_messages_storage(self.account)

    def get_send_messages_helper(self):
        return get_send_messages_helper(self.account)

    def get_file_loader(self):
        return get_file_loader(self.account)

    def get_secret_chat_helper(self):
        return get_secret_chat_helper(self.account)

    def get_download_controller(self):
        return get_download_controller(self.account)

    def get_notifications_settings(self):
        return get_notifications_settings(self.account)

    def get_notification_center(self):
        return get_notification_center(self.account)

    def get_user_config(self):
        return get_user_config(self.account)

    def send_request(self, request, fn):
        return send_request(request, fn, account=self.account)

    def send_message(self, params, parse_mode=None):
        return send_message(params, parse_mode, account=self.account)

    def send_text(self, peer, text, *, parse_mode=None, **kwargs):
        return send_text(peer, text, account=self.account, parse_mode=parse_mode, **kwargs)

    def send_photo(self, peer, file_path, caption="", high_quality=False, *,
                   parse_mode=None, **kwargs):
        return send_photo(peer, file_path, caption, high_quality, account=self.account,
                          parse_mode=parse_mode, **kwargs)

    def send_document(self, peer, file_path, caption="", *, parse_mode=None, **kwargs):
        return send_document(peer, file_path, caption, account=self.account,
                             parse_mode=parse_mode, **kwargs)

    def send_video(self, peer, file_path, caption="", *, parse_mode=None, **kwargs):
        return send_video(peer, file_path, caption, account=self.account,
                          parse_mode=parse_mode, **kwargs)

    def send_audio(self, peer, file_path, caption="", *, parse_mode=None, **kwargs):
        return send_audio(peer, file_path, caption, account=self.account,
                          parse_mode=parse_mode, **kwargs)

    def send_location(self, peer, latitude, longitude, *, accuracy_radius=None, **kwargs):
        return send_location(peer, latitude, longitude, account=self.account,
                             accuracy_radius=accuracy_radius, **kwargs)

    def send_venue(self, peer, latitude, longitude, title, address="", *, provider="",
                   venue_id="", venue_type="", **kwargs):
        return send_venue(peer, latitude, longitude, title, address, account=self.account,
                          provider=provider, venue_id=venue_id, venue_type=venue_type,
                          **kwargs)

    def send_contact(self, peer, phone_number, first_name, last_name="", *, vcard="",
                     **kwargs):
        return send_contact(peer, phone_number, first_name, last_name, account=self.account,
                            vcard=vcard, **kwargs)

    def send_dice(self, peer, emoticon="🎲", **kwargs):
        return send_dice(peer, emoticon, account=self.account, **kwargs)

    def send_sticker(self, peer, sticker, query="", **kwargs):
        return send_sticker(peer, sticker, query, account=self.account, **kwargs)

    def send_existing_photo(self, peer, photo, **kwargs):
        return send_existing_photo(peer, photo, account=self.account, **kwargs)

    def edit_message(self, message_obj, text=None, file_path=None, with_spoiler=False, *,
                     parse_mode=None, **kwargs):
        return edit_message(message_obj, text, file_path, with_spoiler,
                            account=self.account, parse_mode=parse_mode, **kwargs)


def get_client(account=None):
    if account is None:
        account = _hook_account.get()
    if account is None:
        account = extera_ios.current_account()
    return AccountClient(account)


def _generate_photo_sizes(file_path, high_quality=False):
    """Analogue of the Android helper: the host uploads the file by path."""
    if not os.path.exists(file_path):
        log("Photo file not found: %s" % file_path)
        return None
    return {"_": "photo", "path": str(file_path), "high_quality": bool(high_quality)}


def _prepare_document(file_path, mime_type_str=None):
    if not os.path.exists(file_path):
        log("File not found: %s" % file_path)
        return None
    return {
        "_": "document",
        "path": str(file_path),
        "mime_type": mime_type_str or "application/octet-stream",
        "file_name": os.path.basename(file_path),
        "size": os.path.getsize(file_path),
    }


def _add_video_attributes(document, file_path):
    if isinstance(document, dict):
        document.setdefault("attributes", []).append({"type": "video", "path": str(file_path)})
    return document


def _add_audio_attributes(document, file_path):
    if isinstance(document, dict):
        document.setdefault("attributes", []).append({"type": "audio", "path": str(file_path)})
    return document


class RequestCallback:
    """Compatibility wrapper for the Android `RequestDelegate` proxy."""

    def __init__(self, fn, account=None):
        self._fn = bind_request(fn)
        self._account = account

    def run(self, response, error):
        try:
            with account_scope(self._account):
                self._fn(response, error)
        except Exception:
            # Android's RequestDelegate proxy logs and swallows callback
            # failures; keeping them inside Python matches that.
            log("Error in RequestDelegate: %s" % traceback.format_exc())


try:
    from telegram_compat import NotificationCenterDelegate as _NotificationCenterDelegateBase
except Exception:
    _NotificationCenterDelegateBase = object


class NotificationCenterDelegate(_NotificationCenterDelegateBase):
    """Base class for plugins that register notification observers.

    `get_notification_center(account).addObserver(self, NotificationCenter.updateNewMessage)`
    works as on Android: the host posts every update it receives into the same
    bus, in the delegate's `didReceivedNotification(identifier, account, args)`
    signature.
    """

    def __init__(self):
        super().__init__()

    def didReceivedNotification(self, id, account, args):
        pass

