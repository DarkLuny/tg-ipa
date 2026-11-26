"""Parity tests for the iOS exteraGram plugin SDK.

These cover behaviour that must stay identical to the Android SDK but does not
need the app: text parsers, the managed-class API, lifecycle, logging, hook
filters and menu invocation.  Run with:

    python tests/test_parity.py
"""

import json
import os
import shutil
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "PythonSupport", "sdk")
sys.path.insert(0, SDK)

# SharedPreferences is persisted on disk; keep each test run hermetic so a
# previous run's download/notification settings cannot leak into assertions.
os.environ.setdefault(
    "EXTERA_PREFS_DIR", tempfile.mkdtemp(prefix="extera-prefs-")
)

import _extera_runtime
import _extera_native as _native
import compat
import partial_hooks


PLUGIN_SOURCE = '''
from base_plugin import BasePlugin, MenuItemData, MenuItemType

__id__ = "parity"
__name__ = "Parity"
__description__ = "menu and settings parity"
__author__ = "tests"
__version__ = "1.0"

class Parity(BasePlugin):
    def on_plugin_load(self):
        self.add_menu_item(MenuItemData(
            menu_type=MenuItemType.MESSAGE_CONTEXT_MENU,
            text = "Act",
            on_click = self.on_act,
        ))

    def on_act(self, context):
        self.seen = context.get("x")
'''


def test_text_formatting():
    from extera_utils.text_formatting import (
        HTML, Markdown, RawEntity, TLEntityType, parse_text,
    )

    parsed = parse_text("<b>Hello</b> <a href='https://x'>link</a>", "html")
    assert parsed["message"] == "Hello link"
    assert {item["type"] for item in parsed["entities"]} == {"bold", "text_link"}

    emoji = HTML.parse("<emoji id=42>\U0001F600</emoji>")
    assert emoji["message"] == "\U0001F600"
    assert emoji["entities"][0].type == TLEntityType.CUSTOM_EMOJI
    assert emoji["entities"][0].length == 2
    assert HTML.unparse(emoji["message"], emoji["entities"]) == "<emoji id=42>\U0001F600</emoji>"

    nested = HTML.parse("<b>a <i>b</i> c</b>")
    assert nested["message"] == "a b c"
    assert {item.type for item in nested["entities"]} == {TLEntityType.BOLD, TLEntityType.ITALIC}
    restored = HTML.unparse(nested["message"], nested["entities"])
    assert "<b>a <i>b</i> c</b>" == restored

    markdown = Markdown.parse("*bold* _it_ __u__ ~s~ ||sp|| `code` [l](https://x)")
    assert markdown["message"] == "bold it u s sp code l"
    kinds = {item.type for item in markdown["entities"]}
    assert kinds == {
        TLEntityType.BOLD, TLEntityType.ITALIC, TLEntityType.UNDERLINE,
        TLEntityType.STRIKETHROUGH, TLEntityType.SPOILER, TLEntityType.CODE,
        TLEntityType.TEXT_LINK,
    }
    round_trip = Markdown.unparse(markdown["message"], markdown["entities"])
    assert round_trip.startswith("*bold*")
    assert "[l](https://x)" in round_trip


def test_markdown_utils():
    from markdown_utils import TLRPC_ENTITIES_MAP, TLEntityType as MarkdownEntity, parse_markdown

    assert MarkdownEntity.BOLD in TLRPC_ENTITIES_MAP
    assert MarkdownEntity.CUSTOM_EMOJI in TLRPC_ENTITIES_MAP

    parsed = parse_markdown("\U0001F600 *b*")
    assert parsed.text == "\U0001F600 b"
    assert len(parsed.entities) == 1
    assert parsed.entities[0].type == MarkdownEntity.BOLD
    assert parsed.entities[0].offset == 3
    assert parsed.entities[0].length == 1

    link = parse_markdown("[label](https://x)")
    assert link.text == "label"
    assert link.entities[0].url == "https://x"

    emoji = parse_markdown("![\U0001F600](123)")
    assert emoji.entities[0].document_id == 123

    for broken in ("*unclosed", "`unclosed"):
        try:
            parse_markdown(broken)
        except ValueError:
            pass
        else:
            raise AssertionError("parse_markdown accepted %r" % broken)


def test_managed_classes():
    from extera_utils.classes import Base, ClassRef, JField, JHelper, class_proxy

    class Demo(Base):
        __jbaseclass__ = ClassRef("java.lang.Object")

        @JHelper.Method("ping", return_type="int", arg_types=[])
        def ping(self):
            return 7

        @JHelper.Override("onClick", arg_types=["android.view.View"])
        def on_click(self, view):
            return True

        value = JField("int", default=3)

    instance = Demo()
    assert instance.ping() == 7
    assert instance.on_click(None) is True
    assert instance.value == 3
    instance.value = 4
    assert instance.value == 4
    assert "ping" in Demo._resolved_jmethods()
    assert Demo._resolved_jfields()["value"].field_type == "int"

    proxy = class_proxy(ClassRef("java.lang.Object"), fn=lambda obj, name, args: name.upper())
    peer = proxy.new_instance()
    assert peer._intercept("hello", ()) == "HELLO"


def test_logging():
    import log_utils

    records = []
    logger = log_utils.get_logger("parity.test")
    logger.level = log_utils.LogLevel.DEBUG
    logger.add_handler(records.append)
    logger.info("hello %s", "world")
    logger.debug("hidden?", stacklevel=1)
    assert records
    assert records[0].level == log_utils.LogLevel.INFO
    assert "hello world" in records[0].text

    logger.level = log_utils.LogLevel.WARNING
    records.clear()
    logger.info("not emitted")
    assert not records
    logger.warning("emitted")
    assert len(records) == 1

    assert "list" in log_utils.dump([1, 2, 3])
    assert log_utils._split_for_logcat("abc") == ["abc"]


def test_lifecycle():
    from extera_utils import lifecycle

    calls = []
    scope = lifecycle.begin("parity")
    callback = lifecycle.bind_task(lambda: calls.append(1), scope=scope)
    callback()
    assert calls == [1]

    assert lifecycle.scope_for("parity") is scope
    lifecycle.stop("parity")
    callback()
    assert calls == [1]

    stopped = lifecycle.ManagedCallback(lambda: calls.append(2), scope)
    stopped()
    assert calls == [1]


def test_settings_factory():
    from ui import settings

    factory = settings.SimpleSettingFactory(
        lambda *args: None,
        lambda *args: None,
        is_clickable=True,
        on_click=lambda *args: None,
    )
    control = factory("a", 1)
    assert control.factory.viewType == "extera_custom_setting"
    assert control.factory.isClickableValue is True
    assert control.factory.to_json()["handlers"] == ["on_click_handler"]
    assert factory.release() is True


def test_hook_filters():
    from base_plugin import BaseHook, BasePlugin, HookFilter

    plugin = BasePlugin()
    plugin.id = "parity"
    hook = BaseHook(
        plugin,
        before=lambda param: None,
        after=lambda param: None,
        before_filters=[HookFilter.ArgumentNotNull(0)],
        after_filters=[HookFilter.RESULT_IS_TRUE.filter_data],
    )
    before, after = plugin._hook_filters_for(hook)
    assert before == [{"type": "argument_not_null", "arg_index": 0}]
    assert after == [{"type": "result_is_true"}]


def test_conditions():
    import _extera_runtime

    def condition(expression, context=None):
        return json.loads(_extera_runtime.evaluate_condition(
            expression, json.dumps(context or {})))

    assert condition("true") is True
    assert condition("false") is False
    assert condition("message.out == false", {"message": {"out": False}}) is True
    assert condition("message.out == false", {"message": {"out": True}}) is False
    assert condition("peer_id > 0 && !is_bot", {"peer_id": 5, "is_bot": False}) is True
    assert condition("peer_id > 0 || is_bot", {"peer_id": 0, "is_bot": True}) is True
    assert condition("context.get('kind') == 'chat'", {"kind": "chat"}) is True
    assert condition("flags & 4", {"flags": 4}) is True
    assert condition("flags & 4", {"flags": 2}) is False
    assert condition("param.getResult() == null", {"param": {"result": None}}) is True
    assert condition("missing") is False


def test_tl_objects():
    from org.telegram.tgnet import TLRPC

    media = TLRPC.TL_inputMediaPhoto()
    media.id = "photo-id"
    assert media["_"] == "inputMediaPhoto"
    assert media.id == "photo-id"
    assert media.to_native() == (
        "inputMediaPhoto",
        {"_": "inputMediaPhoto", "id": "photo-id"},
    )

    request = TLRPC.TL_messages_getHistory(peer={"user_id": 1}, limit=10)
    assert request.get_name() == "messages.getHistory", request
    assert request["limit"] == 10

    entity = TLRPC.TL_messageEntityBold(offset=0, length=4)
    assert entity.get_name() == "messageEntityBold"
    assert entity.to_json()["length"] == 4


def test_android_ui_shims():
    from org.telegram.ui.ActionBar import AlertDialog, Theme
    from org.telegram.ui.Components import BulletinFactory
    from android.text import TextUtils
    from android.os import Build
    from android.graphics import Color

    builder = AlertDialog.Builder()
    builder.setTitle("Title").setMessage("Message").setPositiveButton("OK", lambda: None)
    assert builder._title == "Title"
    assert builder._positive[0] == "OK"
    assert Theme.getColor("key_windowBackgroundWhite") == 0xFFFFFFFF
    assert Theme.getColor("key_windowBackgroundWhiteBlackText") == 0xFF000000
    assert Theme.getColor("key_text_RedBold") == 0xFFFF3B30
    assert Theme.getColor("key_windowBackgroundWhiteHintText") == 0xFF8E8E93
    assert Theme.getColor("key_windowBackgroundWhiteInputFieldActivated") == 0xFF007AFF
    assert Theme.key_windowBackgroundWhite == "key_windowBackgroundWhite"

    bulletin = BulletinFactory.of().createSuccessBulletin("Saved")
    assert bulletin.text == "Saved"
    assert BulletinFactory.of().createErrorBulletin("Failed").kind == "error"

    assert TextUtils.isEmpty("") is True
    assert TextUtils.isEmpty("x") is False
    assert TextUtils.join(",", [1, 2]) == "1,2"
    assert Build.VERSION.SDK_INT >= 30
    assert Color.parseColor("#ff0000") == 0xFFFF0000
    assert Color.red(0xFF112233) == 0x11

    from org.telegram.messenger import ApplicationLoader
    from android.preference import PreferenceManager

    prefs_dir = tempfile.mkdtemp(prefix="extera-prefs-")
    previous = os.environ.get("EXTERA_PREFS_DIR")
    os.environ["EXTERA_PREFS_DIR"] = prefs_dir
    try:
        prefs = ApplicationLoader.getApplicationContext().getSharedPreferences("compat", 0)
        prefs.edit().putString("key", "value").putInt("n", 3).putBoolean("flag", True).putStringSet("letters", ["a", "b"]).apply()
        assert prefs.getString("key", "") == "value"
        assert prefs.getInt("n", 0) == 3
        assert prefs.getBoolean("flag", False) is True
        assert prefs.getStringSet("letters") == {"a", "b"}
        assert prefs.contains("key")
        again = ApplicationLoader.getApplicationContext().getSharedPreferences("compat", 0)
        assert again.getString("key", "") == "value"
        again.edit().remove("key").apply()
        assert not again.contains("key")
        assert PreferenceManager.getDefaultSharedPreferences() is not None
    finally:
        if previous is None:
            os.environ.pop("EXTERA_PREFS_DIR", None)
        else:
            os.environ["EXTERA_PREFS_DIR"] = previous
        shutil.rmtree(prefs_dir, ignore_errors=True)


def test_compat_plugin():
    source = '''
from base_plugin import BasePlugin
from org.telegram.messenger import (
    UserConfig, MessagesController, FileLoader, LocaleController,
    AndroidUtilities, Utilities, NotificationCenter, BuildVars,
    SharedConfig, FileLog, MessageObject, ContactsController,
    SendMessagesHelper, SendMessageParams, ImageLocation, MediaController,
    MediaDataController, NotificationsController, MessagesStorage,
    DownloadController, SecretChatHelper, LocationController,
)
from org.telegram.ui.ActionBar import AlertDialog, Theme
from org.telegram.ui.Components import BulletinFactory
from android.os import Build
from android.text import TextUtils
from android.graphics import Color
from android.widget import Toast
from org.telegram.tgnet import TLRPC

class CompatPlugin(BasePlugin):
    def on_plugin_load(self):
        account = UserConfig.selectedAccount
        MessagesController.getInstance(account).getUser(1)
        assert hasattr(MessagesController.getInstance(account), "getChatFull")
        assert MessagesController.getInstance(account).getChatFull(1) is not None
        FileLoader.getDirectory(FileLoader.MEDIA_DIR_CACHE).getAbsolutePath()
        LocaleController.getString("TextCopied", 0)
        assert TextUtils.isEmpty("") is True
        assert TextUtils.join(",", [1, 2]) == "1,2"
        assert Build.VERSION.SDK_INT >= 30
        assert Color.red(0xFF112233) == 0x11
        Theme.getColor(Theme.key_windowBackgroundWhite)
        Toast.makeText(None, "hello").show()
        BulletinFactory.of().createSuccessBulletin("ok")
        FileLog.d("compat plugin loaded")
        assert SharedConfig.versionBiggerOrEqual("13.2.1", "12.5.1")
        request = TLRPC.TL_messages_getHistory(peer={"user_id": 1}, limit=1)
        assert request.get_name() == "messages.getHistory"
        assert isinstance({"id": 1, "message": "hello"}, MessageObject)
        builder = AlertDialog.Builder()
        builder.setTitle("t").setMessage("m").setPositiveButton("ok", lambda: None)
        assert MediaController.getInstance(account).isPlayingAudio() is False
        assert MediaDataController.getInstance(account).getStickerSets() == []
        assert MessagesStorage.getInstance(account).getChats() == {}
        assert MessagesStorage.getInstance(account).getUsers() == {}
        assert MessagesStorage.getInstance(account).getDialogs() == []
        assert MessagesController.getInstance(account).getMessage(1, 1) is None
        assert isinstance(UserConfig.isPremium, bool)
        assert DownloadController.getInstance(account).getAutoDownloadSettings() == {}
        assert LocationController.getInstance(account).isSharingLocation() is False
        assert ContactsController.getInstance(account) is not None
        assert SendMessagesHelper.getInstance(account) is not None
        params = SendMessageParams()
        params.dialogId = 1
        params.message = MessageObject({"message": "hi", "entities": []})
        SendMessagesHelper.getInstance(account).sendMessage(params)
        assert ImageLocation.getForPath("/tmp/x").getPath() == "/tmp/x"
        assert NotificationsController.getInstance(account) is not None
        assert SecretChatHelper.getInstance(account) is not None
        self.compat_ok = True
'''
    work = tempfile.mkdtemp(prefix="extera-compat-")
    plugins = os.path.join(work, "plugins")
    os.makedirs(plugins, exist_ok=True)
    path = os.path.join(plugins, "compat.plugin")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)

    _extera_runtime.initialize(SDK, plugins, work)
    loaded = json.loads(_extera_runtime.load_plugin("compat", path))
    assert loaded["ok"], loaded
    instance = _extera_runtime._PLUGINS["compat"].instance
    assert getattr(instance, "compat_ok", False) is True
    assert json.loads(_extera_runtime.unload_plugin("compat"))["ok"] is True


def test_menu_runtime():
    work = tempfile.mkdtemp(prefix="extera-parity-")
    plugins = os.path.join(work, "plugins")
    os.makedirs(plugins, exist_ok=True)
    path = os.path.join(plugins, "parity.plugin")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(PLUGIN_SOURCE)

    _extera_runtime.initialize(SDK, plugins, work)
    loaded = json.loads(_extera_runtime.load_plugin("parity", path))
    assert loaded["ok"], loaded

    info = json.loads(_extera_runtime.plugin_info("parity"))
    instance = _extera_runtime._PLUGINS["parity"].instance
    assert instance is not None
    assert info["loaded"] is True
    assert "parity.1" in instance._menu_items

    invoked = json.loads(_extera_runtime.call_menu_item(
        "parity", "parity.1", json.dumps({"x": 5})
    ))
    assert invoked is True
    assert instance.seen == 5

    assert instance.update_menu_item("parity.1", text="Renamed") is True
    assert instance._menu_items["parity.1"]["data"]["text"] == "Renamed"
    assert instance.remove_menu_item("parity.1") is True
    assert "parity.1" not in instance._menu_items

    assert json.loads(_extera_runtime.unload_plugin("parity"))["ok"] is True


def test_file_and_intent_hooks():
    from file_utils import FilesController

    seen = []
    info = FilesController.FileInfo(ext="txt", on_click=lambda args: seen.append(args))
    secret = FilesController.register(info)
    assert secret
    try:
        FilesController.register(FilesController.FileInfo(ext="txt", on_click=lambda args: None))
    except FilesController.ExtensionAlreadyRegistered:
        pass
    else:
        raise AssertionError("duplicate extension was accepted")
    try:
        FilesController.unregister("txt", "wrong")
    except FilesController.SecretInvalid:
        pass
    else:
        raise AssertionError("invalid secret was accepted")
    FilesController.unregister("txt", secret)
    assert "txt" not in FilesController._config
    assert "txt" not in FilesController._owners

    from intents import IntentsManager

    received = []
    entry = IntentsManager.HandlerInfo(callback=lambda payload: received.append(payload) or "handled")
    handle = IntentsManager.new_global_before_handler(entry)
    assert handle is not None
    assert IntentsManager._dispatch(handle.handler_id, {"x": 1}) == "handled"
    assert received == [{"x": 1}]
    handle.unhandle()
    assert IntentsManager._dispatch(handle.handler_id, {}) is None

    parsed = IntentsManager.parse("https://example.com/path?a=1")
    assert parsed["scheme"] == "https"
    assert parsed["host"] == "example.com"
    assert parsed["path"] == "path?a=1"
    assert parsed["query"] == "a=1"

    # The full Android filter: scheme, host, path template, required query
    # parameter, and a callback that receives the standard context.
    calls = []

    def on_tg(intent, scheme, host, path, query_args, action, flags, type, categories):
        calls.append((intent, scheme, host, path, query_args, action, flags, type, categories))
        return True

    handle = IntentsManager.new_global_before_handler(IntentsManager.HandlerInfo(
        callback=on_tg,
        scheme="tg",
        host="resolve",
        path="/{username}",
        required_path_args_names=["ref"],
    ))
    payload = {
        "url": "tg://resolve/alice?ref=1",
        "action": "android.intent.action.VIEW",
        "flags": 0,
        "categories": ["android.intent.category.BROWSABLE"],
    }
    assert IntentsManager._host_dispatch(payload, "before") is True
    assert calls and calls[-1][1] == "tg" and calls[-1][2] == "resolve"
    assert calls[-1][3] == "/alice"
    assert calls[-1][4]["ref"] == "1"
    handle.unhandle()

    # A path argument is bound by name.
    names = []
    handle = IntentsManager.new_global_before_handler(IntentsManager.HandlerInfo(
        callback=lambda username: names.append(username),
        scheme="tg",
        host="resolve",
        path="/{username}",
    ))
    IntentsManager._host_dispatch({"url": "tg://resolve/bob"}, "before")
    assert names == ["bob"], names
    handle.unhandle()

    # Flags and categories filter the same way as Android.
    matched = []
    handle = IntentsManager.new_global_before_handler(IntentsManager.HandlerInfo(
        callback=lambda: matched.append(True),
        whitelist_flags=[1],
        categories=["android.intent.category.BROWSABLE"],
    ))
    IntentsManager._host_dispatch({"url": "tg://resolve/x", "flags": 1,
                                   "categories": ["android.intent.category.BROWSABLE"]}, "before")
    assert matched == [True]
    IntentsManager._host_dispatch({"url": "tg://resolve/x", "flags": 0,
                                   "categories": ["android.intent.category.BROWSABLE"]}, "before")
    assert matched == [True]
    handle.unhandle()

    # Lower priorities run first.
    order = []
    low = IntentsManager.new_global_before_handler(IntentsManager.HandlerInfo(
        callback=lambda: order.append("low"), priority=10))
    high = IntentsManager.new_global_before_handler(IntentsManager.HandlerInfo(
        callback=lambda: order.append("high"), priority=-10))
    IntentsManager._host_dispatch({"url": "https://example.com/"}, "before")
    assert order == ["high", "low"], order
    low.unhandle()
    high.unhandle()


def test_alert_builder():
    from ui.alert import AlertDialogBuilder

    dialog = AlertDialogBuilder()
    dialog.set_title("Title")
    dialog.set_message("Message")
    dialog.set_positive_button("OK", lambda *args: None)
    dialog.set_items(["One", "Two"], lambda index: None)
    dialog.show()

    handle = dialog.get_dialog()
    assert handle is not None
    assert isinstance(handle.get_id(), str) and handle.get_id().startswith("stub-alert-")
    assert handle.is_showing() is True
    dialog.dismiss()
    assert handle.is_showing() is False


def test_dependency_directory():
    work = tempfile.mkdtemp(prefix="extera-deps-")
    plugins = os.path.join(work, "plugins")
    deps = os.path.join(plugins, ".deps", "deps_demo")
    os.makedirs(deps, exist_ok=True)
    with open(os.path.join(deps, "helper.py"), "w", encoding="utf-8") as handle:
        handle.write("VALUE = 42\n")
    source = '''
import helper
from base_plugin import BasePlugin

__id__ = "deps_demo"
__name__ = "Deps"
__version__ = "1.0"

class DepsDemo(BasePlugin):
    def on_plugin_load(self):
        self.value = helper.VALUE
'''
    path = os.path.join(plugins, "deps_demo.plugin")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)

    _extera_runtime.initialize(SDK, plugins, work)
    loaded = json.loads(_extera_runtime.load_plugin("deps_demo", path))
    assert loaded["ok"], loaded
    instance = _extera_runtime._PLUGINS["deps_demo"].instance
    assert instance.value == 42
    deps_dir = os.path.abspath(deps)
    assert deps_dir in sys.path
    assert json.loads(_extera_runtime.unload_plugin("deps_demo"))["ok"] is True
    assert deps_dir not in sys.path


def test_notification_center():
    import client_utils
    import telegram_compat

    received = []

    class Observer(telegram_compat.NotificationCenterDelegate):
        def didReceivedNotification(self, id, account, args):
            received.append((id, account, list(args)))

    account = 7
    center = client_utils.get_notification_center(account)
    observer = Observer()
    center.addObserver(observer, telegram_compat.NotificationCenter.updateNewMessage)
    telegram_compat.notify_update(
        "updateNewMessage", account, {"_": "updateNewMessage", "message": 1}
    )
    assert received and received[0][0] == "updateNewMessage", received
    assert received[0][1] == account, received
    assert received[0][2][0]["message"] == 1, received

    # Another account's updates do not reach this observer.
    telegram_compat.notify_update(
        "updateNewMessage", account + 1, {"_": "updateNewMessage"}
    )
    assert len(received) == 1, received

    center.removeObserver(observer)
    telegram_compat.notify_update(
        "updateNewMessage", account, {"_": "updateNewMessage"}
    )
    assert len(received) == 1, received

    assert center.hasObservers(
        telegram_compat.NotificationCenter.updateNewMessage
    ) is False
    center.addObserver(observer, telegram_compat.NotificationCenter.updateNewMessage)
    assert center.hasObservers(
        telegram_compat.NotificationCenter.updateNewMessage
    ) is True
    assert observer in center.getObservers(
        telegram_compat.NotificationCenter.updateNewMessage
    )
    center.removeAllObservers(observer)
    assert center.hasObservers(
        telegram_compat.NotificationCenter.updateNewMessage
    ) is False

    center.setAnimationInProgress(True)
    assert center.isAnimationInProgress() is True
    finished = []
    center.performOnAnimationFinish(lambda: finished.append(True))
    assert finished == []
    center.finishAnimation()
    assert finished == [True]
    assert center.isAnimationInProgress() is False

    assert center.listenForNotifications(True) is None
    assert center.stopListeningForNotifications() is None
    callback = lambda: None
    assert center.addPostponeNotificationsCallback(callback) is None
    assert center.removePostponeNotificationsCallback(callback) is None
    assert center.runDelayedNotifications() is None

    received_plugins = []

    class PluginsObserver(telegram_compat.NotificationCenterDelegate):
        def didReceivedNotification(self, id, account, args):
            received_plugins.append((id, account, list(args)))

    plugins_observer = PluginsObserver()
    center.addObserver(
        plugins_observer,
        [
            telegram_compat.NotificationCenter.pluginsUpdated,
            telegram_compat.NotificationCenter.pluginMenuItemsUpdated,
            telegram_compat.NotificationCenter.pluginSettingsRegistered,
            telegram_compat.NotificationCenter.pluginIsNotResponding,
        ],
    )
    import _extera_runtime

    # Android's update runnable posts both names together.
    assert json.loads(_extera_runtime.notify_plugins_updated()) is True
    names = [item[0] for item in received_plugins]
    assert "pluginsUpdated" in names, received_plugins
    assert "pluginMenuItemsUpdated" in names, received_plugins

    # Settings, watchdog and catalog events carry their Android arguments.
    assert json.loads(_extera_runtime.notify_plugin_event("pluginSettingsRegistered", "demo")) is True
    registered = [item for item in received_plugins if item[0] == "pluginSettingsRegistered"]
    assert registered and registered[-1][2] == ["demo"], registered

    assert json.loads(_extera_runtime.notify_plugin_event("pluginIsNotResponding")) is True
    assert any(item[0] == "pluginIsNotResponding" for item in received_plugins), received_plugins
    center.removeObserver(plugins_observer)

    assert issubclass(
        client_utils.NotificationCenterDelegate,
        telegram_compat.NotificationCenterDelegate,
    )


def test_file_utils_list_dir():
    import file_utils

    root = tempfile.mkdtemp(prefix="extera-list-dir-")
    try:
        os.makedirs(os.path.join(root, "sub"))
        for relative in ["a.py", "b.txt", os.path.join("sub", "c.py")]:
            with open(os.path.join(root, relative), "w", encoding="utf-8") as handle:
                handle.write("")
        names = sorted(os.path.basename(item) for item in file_utils.list_dir(root))
        assert names == ["a.py", "b.txt"], names
        names = sorted(os.path.basename(item) for item in file_utils.list_dir(root, False, True, True))
        assert names == ["a.py", "b.txt", "sub"], names
        names = sorted(os.path.basename(item) for item in file_utils.list_dir(root, True))
        assert names == ["a.py", "b.txt", "c.py"], names
        names = sorted(os.path.basename(item) for item in file_utils.list_dir(root, extensions=[".txt"]))
        assert names == ["b.txt"], names
        names = sorted(os.path.basename(item) for item in file_utils.list_dir(root, True, True, True))
        assert names == ["a.py", "b.txt", "c.py", "sub"], names
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_file_loader_paths():
    from telegram_compat import FileLoader, MessageObject

    message = MessageObject({
        "media": {
            "_": "messageMediaDocument",
            "document": {"id": 7, "file_name": "report.pdf"},
        }
    })
    path = FileLoader.getPathToMessage(message).getPath()
    assert path.endswith("report.pdf"), path
    direct = FileLoader.getPathToAttach({"path": "/tmp/photo.jpg"}).getPath()
    assert direct == "/tmp/photo.jpg"


def test_android_java_shims():
    from android.util import Base64, Log, Patterns, SparseArray
    from android.os import Bundle, Environment, Handler, Looper, SystemClock
    from android.text import Html
    from android.net import Uri
    from android.content import Intent
    from java.io import FileInputStream, FileOutputStream
    from java.util import Base64 as JavaBase64
    from java.nio.charset import Charset, StandardCharsets
    from java.text import SimpleDateFormat

    Log.d("parity", "hello")
    assert SystemClock.uptimeMillis() >= 0
    assert Html.fromHtml("<b>hi</b><br>x") == "hi\nx"
    assert JavaBase64.getEncoder().encodeToString(b"hi") == "aGk="
    assert JavaBase64.getDecoder().decode("aGk=") == b"hi"
    assert StandardCharsets.UTF_8 == "utf-8"
    assert Charset.forName("UTF-8") == "UTF-8"
    intent = Intent(Intent.ACTION_VIEW, "https://example.com")
    assert intent.getAction() == Intent.ACTION_VIEW
    assert intent.getData() == "https://example.com"
    assert Patterns.EMAIL_ADDRESS.matcher("a@b.co").matches()
    assert SimpleDateFormat("yyyy-MM-dd").format(0).startswith("19")

    assert Base64.encodeToString(b"hi", Base64.NO_WRAP) == "aGk="
    assert Base64.decode("aGk=") == b"hi"

    from java.lang import Integer, Long, Boolean, String, Math, System, Character
    from java.util import Locale, Calendar, TimeZone, Random, UUID
    from android.text.format import DateFormat

    assert Integer.parseInt("42") == 42
    assert Long.parseLong("1000000000000") == 1000000000000
    assert Boolean.parseBoolean("true") is True
    assert String.valueOf(5) == "5"
    assert String.format("%s-%d", "a", 2) == "a-2"
    assert Math.max(2, 3) == 3
    assert System.currentTimeMillis() > 0
    assert Character.isDigit("7") is True
    assert Locale.US.getLanguage() == "en"
    assert DateFormat.getTimeFormat().format(0)
    assert 0 <= Random().nextInt(10) < 10
    assert len(UUID.randomUUID().toString()) == 36

    from java.util.concurrent.atomic import AtomicBoolean, AtomicInteger
    from java.util.concurrent import Executors, TimeUnit
    from android.os import AsyncTask

    counter = AtomicInteger(0)
    assert counter.incrementAndGet() == 1
    assert counter.get() == 1
    assert AtomicBoolean(False).compareAndSet(False, True) is True
    executor = Executors.newSingleThreadExecutor()
    future = executor.submit(lambda: 5)
    assert future.get() == 5
    executor.shutdown()
    assert TimeUnit.MILLISECONDS.toSeconds(1000) == 1

    class Task(AsyncTask):
        def doInBackground(self, *args):
            return 7

    task = Task()
    task.execute()
    assert task is not None
    assert task.isCancelled() is False
    calendar = Calendar.getInstance()
    calendar.setTimeInMillis(0)
    assert 0 <= calendar.get(Calendar.MINUTE) <= 59
    before = calendar.getTimeInMillis()
    calendar.add(Calendar.DATE, 1)
    assert calendar.getTimeInMillis() > before
    assert TimeZone.getDefault().getID() == "UTC"

    bundle = Bundle()
    bundle.putString("k", "v").putInt("n", 3)
    assert bundle.getString("k") == "v"
    assert bundle.getInt("n") == 3
    assert bundle.containsKey("k")

    assert Uri.parse("file:///tmp/x").getPath() == "/tmp/x"
    parsed_uri = Uri.parse("https://example.com/path?a=1&b=2")
    assert parsed_uri.getScheme() == "https"
    assert parsed_uri.getHost() == "example.com"
    assert parsed_uri.getQueryParameter("a") == "1"
    assert parsed_uri.buildUpon().appendQueryParameter("c", "3").build().getQueryParameter("c") == "3"

    from android.graphics import Color

    assert Color.rgb(1, 2, 3) == 0xFF010203
    hsv = Color.colorToHSV(0xFFFF0000)
    assert round(hsv[0]) == 0
    assert Color.alpha(Color.HSVToColor(hsv)) == 255

    array = SparseArray()
    array.put(2, "b")
    array.put(1, "a")
    assert array.size() == 2
    assert array.get(1) == "a"
    assert array.keyAt(0) == 1

    from android.util import DisplayMetrics, TypedValue

    assert DisplayMetrics().density > 0
    assert TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 16) == 16.0

    from android.content.res import Configuration, Resources
    from android.graphics import Typeface
    from android.os import Build, VibrationEffect

    resources = Resources()
    assert resources.getDisplayMetrics().density > 0
    assert resources.getConfiguration().orientation == Configuration.ORIENTATION_PORTRAIT
    assert Typeface.DEFAULT
    assert VibrationEffect.createOneShot(10)["duration"] == 10
    assert Build.VERSION_CODES.M == 23

    from android.util import ArrayMap, ArraySet, Pair
    from android.text import SpannableString

    mapping = ArrayMap()
    mapping.put("k", 1)
    assert mapping.get("k") == 1 and mapping.keyAt(0) == "k"
    array_set = ArraySet()
    array_set.add("x")
    assert array_set.contains("x") and array_set.size() == 1
    pair = Pair.create("a", 2)
    assert pair.first == "a" and pair.second == 2
    assert SpannableString("hello").length() == 5

    work = tempfile.mkdtemp(prefix="extera-java-shims-")
    try:
        path = os.path.join(work, "data.bin")
        stream = FileOutputStream(path)
        stream.write(b"hello")
        stream.close()
        source = FileInputStream(path)
        buffer = bytearray(5)
        assert source.read(buffer) == 5
        assert bytes(buffer) == b"hello"
        source.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    handler = Handler(Looper.getMainLooper())
    handler.post(lambda: None)
    assert Environment.getExternalStorageDirectory() is not None

    from org.telegram.messenger import AndroidUtilities, Utilities, LocaleController

    assert AndroidUtilities.getPhotoSize() > 0
    assert AndroidUtilities.displaySize.x > 0
    assert AndroidUtilities.addToClipboard("x") in (True, False)
    assert 0 <= Utilities.random.nextInt(10) < 10
    assert Utilities.random(1, 4) in (1, 2, 3, 4)
    assert AndroidUtilities.getMinuteOfDay(1, 30) == 90
    assert LocaleController.formatString("Hello %s", "world") == "Hello world"
    assert LocaleController.formatPluralString("Items %d", 2, 2) == "Items 2"
    assert LocaleController.formatShortNumber(1500).endswith("K")
    assert LocaleController.formatDate(0)

    from android.text import TextUtils as CompatTextUtils

    assert CompatTextUtils.concat("a", None, "b") == "ab"
    assert CompatTextUtils.getReverse("abc") == "cba"
    assert CompatTextUtils.indexOf("abc", "b") == 1
    assert Utilities.clamp(5, 0, 3) == 3
    assert Utilities.lerp(0, 10, 0.5) == 5.0

    from android.os import PowerManager, Vibrator

    lock = PowerManager().newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "tag")
    lock.acquire()
    assert lock.isHeld() is True
    lock.release()
    assert lock.isHeld() is False
    Vibrator().vibrate(10)

    from android.provider import Settings
    from android.content import ContentResolver
    from android.os import HandlerThread, Process
    from androidx.core.content import FileProvider

    assert Settings.Secure.getString(None, "android_id")
    assert Process.myPid() > 0
    assert HandlerThread("x").getLooper() is not None
    shared_uri = FileProvider.getUriForFile(None, "authority", "/tmp/x")
    assert shared_uri.getPath() == "/tmp/x"
    assert ContentResolver() is not None

    from android.graphics import BitmapFactory
    from android.content import ContentValues

    png = (
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        + (2).to_bytes(4, "big") + (3).to_bytes(4, "big")
    )
    bitmap = BitmapFactory.decodeByteArray(png)
    assert bitmap.getWidth() == 2 and bitmap.getHeight() == 3
    options = BitmapFactory.Options()
    options.inJustDecodeBounds = True
    assert BitmapFactory.decodeByteArray(png, 0, len(png)) is not None
    values = ContentValues()
    values.put("k", "v")
    assert values.getAsString("k") == "v"

    from android.content.pm import PackageManager
    from org.telegram.messenger import BuildConfig

    package_info = PackageManager().getPackageInfo("org.telegram.Telegram")
    assert package_info.versionName
    assert BuildConfig.VERSION_CODE == 66999

    from android.media import AudioManager, MediaMetadataRetriever, MediaPlayer

    retriever = MediaMetadataRetriever()
    assert retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION) is None
    retriever.release()
    player = MediaPlayer()
    player.start()
    assert player.isPlaying() is False
    assert AudioManager().getStreamVolume(AudioManager.STREAM_MUSIC) == 0

    def scheduled():
        return None

    AndroidUtilities.runOnUIThread(scheduled, 0)
    AndroidUtilities.cancelRunOnUIThread(scheduled)

    from org.telegram.messenger import FileLoader, ImageLocation
    from org.telegram.messenger import AndroidUtilities as CompatAndroidUtilities
    from org.telegram.messenger import Utilities as CompatUtilities

    assert FileLoader.MEDIA_DIR_DATABASE == 6
    assert FileLoader.getInstance(0) is FileLoader
    assert FileLoader.getAttachFileName({"file_name": "song.mp3"}) == "song.mp3"
    assert FileLoader.isLoadingFile("x") is False
    assert FileLoader.getFileProgress("x") == 0.0
    assert ImageLocation.getForPath("/tmp/photo.jpg").getPath() == "/tmp/photo.jpg"
    assert ImageLocation.getForDocument({"file_name": "doc.pdf"}).getPath() == "doc.pdf"
    assert CompatAndroidUtilities.getDurationString(65) == "1:05"
    assert CompatAndroidUtilities.replaceTags("<b>hello</b>") == "hello"
    assert CompatAndroidUtilities.isEmpty("") is True
    assert CompatUtilities.parseDouble("1.5") == 1.5
    assert CompatUtilities.parseBoolean("true") is True
    assert CompatUtilities.getFileName("/tmp/a.txt") == "a.txt"

    copy_source = os.path.join(tempfile.gettempdir(), "extera-copy-source.txt")
    copy_target = os.path.join(tempfile.gettempdir(), "extera-copy-target.txt")
    try:
        with open(copy_source, "w", encoding="utf-8") as handle:
            handle.write("payload")
        assert CompatUtilities.copyFile(copy_source, copy_target) is True
        with open(copy_target, "r", encoding="utf-8") as handle:
            assert handle.read() == "payload"
    finally:
        for path in (copy_source, copy_target):
            try:
                os.remove(path)
            except OSError:
                pass


def test_androidx_stubs():
    from androidx.recyclerview.widget import GridLayoutManager, LinearLayoutManager, RecyclerView
    from androidx.core.graphics.drawable import DrawableCompat
    from androidx.core.view import ViewCompat
    from androidx.viewpager.widget import ViewPager
    from org.telegram.ui.Components import MediaActionDrawable, RLottieDrawable, UniversalAdapter
    from org.telegram.ui.ActionBar import BaseFragment

    recycler = RecyclerView(None)
    adapter = RecyclerView.Adapter()
    layout = LinearLayoutManager(None, LinearLayoutManager.VERTICAL)
    recycler.setAdapter(adapter)
    recycler.setLayoutManager(layout)
    assert recycler.getAdapter() is adapter
    assert recycler.getLayoutManager() is layout
    assert layout.getOrientation() == LinearLayoutManager.VERTICAL
    assert GridLayoutManager(None, 3).getSpanCount() == 3

    assert DrawableCompat.wrap(None) is None
    assert ViewCompat.isAttachedToWindow(recycler) is True

    pager = ViewPager(None)
    pager.setCurrentItem(2)
    assert pager.getCurrentItem() == 2

    icon = MediaActionDrawable()
    icon.setIcon(MediaActionDrawable.ICON_PLAY)
    assert icon.icon == MediaActionDrawable.ICON_PLAY

    lottie = RLottieDrawable()
    lottie.setCurrentFrame(5)
    lottie.start()
    assert lottie.currentFrame == 5
    assert lottie.playing is True

    items = UniversalAdapter()
    items.setItems([1, 2])
    assert items.getItemCount() == 2
    assert items.getItem(1) == 2

    assert BaseFragment().getParentActivity() is None


def test_mvel_facade():
    from org.mvel2 import MVEL

    assert MVEL.eval("1 == 1") is True
    assert MVEL.eval("context.get('value') == 3", {"value": 3}) is True
    assert MVEL.eval("false") is False


def test_app_facades():
    """The app classes Elyx/advanced plugins import have native facades."""
    from com.exteragram.messenger.plugins import PluginsController, PythonPluginsEngine
    from com.exteragram.messenger.plugins.pip import PipController
    from com.exteragram.messenger.utils import IntentsController

    controller = PluginsController.getInstance()
    assert controller is PluginsController.getInstance()
    assert isinstance(controller.plugins, dict)
    assert isinstance(controller.pluginsDir, str)
    assert PythonPluginsEngine.getSDKVersion() == "1.4.6.5"
    assert "python" in PluginsController.getEngines()
    assert PipController.INSTANCE is not None
    assert IntentsController.PLUGIN_REPOSITORY_LINK == "exteraPluginRepo"
    assert IntentsController.PLUGIN_REPOSITORY_QUERY_KEY == "c"
    assert IntentsController.PLUGIN_REPOSITORY_GIT_QUERY_KEY == "git"


def test_elyx_ui_stubs():
    """The widgets Elyx's password sheet builds are native, not host proxies."""
    from org.telegram.ui.Components import (
        EditTextBoldCursor,
        OutlineTextContainerView,
        RLottieImageView,
    )
    from org.telegram.ui.Stories.recorder import ButtonWithCounterView

    edit = EditTextBoldCursor(None)
    edit.setText("secret")
    assert edit.getText().toString() == "secret"
    assert edit.length() == 6

    outline = OutlineTextContainerView(None)
    outline.setText("Password")
    outline.addView(edit)
    assert outline.editText is edit
    outline.attachEditText(edit)
    outline.animateError(1)
    outline.animateSelection(1, False)

    image = RLottieImageView(None)
    image.setAnimation(1, 100, 100)
    image.playAnimation()
    assert image.animation == 1

    button = ButtonWithCounterView(None, True, None)
    button.setRound()
    button.setText("Decrypt", False)
    assert button.text == "Decrypt"
    assert button.round is True


def test_plugins_constants():
    from com.exteragram.messenger import ExteraConfig
    from com.exteragram.messenger.plugins import PluginsConstants
    from com.exteragram.messenger.utils import AppUtils

    assert PluginsConstants.Strategy.CANCEL == "CANCEL"
    assert PluginsConstants.Strategy.MODIFY_FINAL == "MODIFY_FINAL"
    assert PluginsConstants.APP_START == "app_start"
    assert PluginsConstants.MenuItemTypes.MAIN_MENU == "main_menu"
    assert PluginsConstants.HookFilterTypes.RESULT_IS_TRUE == "result_is_true"
    assert ExteraConfig.pluginsEngine is True
    assert ExteraConfig.pluginsSafeMode is False
    assert AppUtils is not None

    # The Android object exposes both properties and Kotlin-style accessors.
    # The host bridge is absent in this desktop test, so the facade falls back
    # to its in-memory override, exactly as it does before the app starts.
    ExteraConfig._OVERRIDES.clear()
    assert ExteraConfig.downloadSpeedBoost == 0
    ExteraConfig.downloadSpeedBoost = 2
    assert ExteraConfig.downloadSpeedBoost == 2
    assert ExteraConfig.getDownloadSpeedBoost() == 2
    ExteraConfig.setDownloadSpeedBoost(1)
    assert ExteraConfig.downloadSpeedBoost == 1
    ExteraConfig._OVERRIDES.clear()


def test_uitem_facade():
    """Android's UItem static builders produce host-readable settings rows."""
    from org.telegram.ui.Components import UItem

    item = UItem.asSwitch(1, True, "Enable")
    assert item["type"] == "switch"
    assert item["key"] == 1
    assert item["default"] is True
    assert item["text"] == "Enable"
    item.checked = False
    assert item["default"] is False
    assert item.checked is False

    calls = []
    item.setOnChangeListener(lambda value: calls.append(value))
    assert callable(item["on_change"])
    item.linkAlias = "plugins/demo"
    assert item["link_alias"] == "plugins/demo"

    header = UItem.asHeader("Title")
    assert header["type"] == "header"
    assert header.text == "Title"

    button = UItem.asButton(2, None, "Do")
    assert button["type"] == "text"
    assert button["accent"] is True

    selector = UItem.asSelector(3, "Choice", ["a", "b"], 1)
    assert selector["type"] == "selector"
    assert selector["items"] == ["a", "b"]
    assert selector["default"] == 1

    disabled = UItem.asEditText(4, "Value").setEnabled(False)
    assert disabled["enabled"] is False


def test_android_graphics_stubs():
    from android.graphics import (
        Canvas,
        LinearGradient,
        Paint,
        Path,
        PorterDuff,
        PorterDuffXfermode,
        Rect,
        RectF,
    )
    from android.view import ViewGroup

    paint = Paint(Paint.ANTI_ALIAS_FLAG)
    paint.setColor(0xFF112233)
    paint.setStrokeWidth(2)
    paint.setStyle(Paint.Style.STROKE)
    assert paint.getColor() == 0xFF112233
    assert paint.getStrokeWidth() == 2.0
    assert paint.getStyle() == Paint.Style.STROKE
    assert paint.measureText("abc") > 0

    canvas = Canvas()
    assert canvas.save() == 1
    canvas.restore()
    assert canvas.getWidth() > 0

    path = Path()
    path.moveTo(0, 0)
    path.lineTo(10, 10)
    path.close()
    assert path.isEmpty() is False
    path.reset()
    assert path.isEmpty() is True

    rect = Rect(0, 0, 10, 20)
    assert rect.width() == 10 and rect.height() == 20
    assert rect.contains(5, 5) is True

    rectf = RectF(0, 0, 10.5, 20.5)
    assert rectf.width() == 10.5

    mode = PorterDuffXfermode(PorterDuff.Mode.SRC_OVER)
    assert mode.mode == PorterDuff.Mode.SRC_OVER
    assert LinearGradient(0, 0, 1, 1, 0, 0, 0) is not None

    params = ViewGroup.MarginLayoutParams(100, 50)
    params.setMargins(1, 2, 3, 4)
    assert params.leftMargin == 1
    assert params.bottomMargin == 4


def test_android_widget_stubs():
    """View/widget objects keep plugin code running even without a renderer."""
    from android.view import Gravity, HapticFeedbackConstants, View
    from android.widget import LinearLayout, Switch, TextView
    from android.content import DialogInterface
    from android.graphics.drawable import GradientDrawable
    from org.telegram.ui.Components import LayoutHelper
    from com.chaquo.python import PyObject
    from java.lang.ref import WeakReference

    view = View()
    view.setVisibility(View.GONE)
    assert view.getVisibility() == View.GONE
    clicked = []
    view.setOnClickListener(lambda v: clicked.append(True))
    view.performClick()
    assert clicked == [True]

    text = TextView()
    text.setText("hello")
    assert text.getText() == "hello"
    assert text.length() == 5
    assert text.requestFocus() is True

    layout = LinearLayout()
    layout.setOrientation(LinearLayout.VERTICAL)
    layout.addView(text)
    assert layout.getChildCount() == 1
    assert layout.getChildAt(0) is text

    toggle = Switch()
    toggle.setChecked(True)
    assert toggle.isChecked() is True

    params = LayoutHelper.createFrame(-1, -2, Gravity.CENTER_HORIZONTAL, 24, 8, 24, 0)
    assert params.width == -1
    assert params.height == -2
    assert params.margins == (24, 8, 24, 0)
    assert LayoutHelper.createLinear(100, 100, Gravity.CENTER).width == 100

    assert DialogInterface.BUTTON_POSITIVE == -1
    assert DialogInterface.OnDismissListener() is not None
    assert HapticFeedbackConstants.FLAG_IGNORE_GLOBAL_SETTING == 1
    assert TextView.OnEditorActionListener().onEditorAction(None, 0, None) is False

    drawable = GradientDrawable()
    drawable.setColor(0xFF00FF00)
    assert drawable.color == 0xFF00FF00

    reference = WeakReference(text)
    assert reference.get() is text
    reference.clear()
    assert reference.get() is None

    holder = PyObject({"value": 3})
    assert holder.toJava() == {"value": 3}


def test_messages_controller_fallbacks():
    """Common controller getters answer instead of raising AttributeError."""
    from org.telegram.messenger import MessagesController

    controller = MessagesController.getInstance(3)
    assert controller.getSponsoredMessages(1) == {
        "messages": [],
        "chats": [],
        "users": [],
    }
    assert controller.getTopicsController() is not None
    assert controller.isSupportChat({"id": 1}) is False
    assert controller.checkCanOpenChat(1) is True
    assert controller.canSendMessage({"id": 1}) is True
    assert controller.getUnknownControllerValue() is None
    assert controller.isUnknownControllerFlag() is False


def test_send_message_params_media():
    """SendMessageParams carries a local path into the media send path."""
    import extera_ios
    from org.telegram.messenger import SendMessageParams, SendMessagesHelper

    calls = []
    original = extera_ios.host

    def fake_host(name, **kwargs):
        if name == "client.send":
            calls.append(kwargs)
            return {"ok": True}
        return original(name, **kwargs)

    extera_ios.host = fake_host
    try:
        params = SendMessageParams()
        params.dialogId = 42
        params.path = "/tmp/photo.jpg"
        params.caption = "hello"
        result = SendMessagesHelper.getInstance(0).sendMessage(params)
        assert result == {"ok": True}
        assert calls and calls[0]["kind"] == "photo", calls
        assert calls[0]["peer"] == 42
        assert calls[0]["caption"] == "hello"

        text_params = SendMessageParams()
        text_params.dialogId = 43
        text_params.message = "plain"
        calls.clear()
        SendMessagesHelper.getInstance(0).sendMessage(text_params)
        assert calls and calls[0]["kind"] == "text", calls
        assert calls[0]["text"] == "plain"

        extra_params = SendMessageParams()
        extra_params.dialogId = 44
        extra_params.message = "with options"
        extra_params.replyToMsg = {"id": 7}
        extra_params.replyToTopMsg = {"id": 3}
        extra_params.ttl = 60
        extra_params.effect_id = 9
        extra_params.invert_media = True
        calls.clear()
        SendMessagesHelper.getInstance(0).sendMessage(extra_params)
        assert calls and calls[0]["reply_to"] == 7, calls
        assert calls[0]["reply_to_top"] == 3
        assert calls[0]["ttl"] == 60
        assert calls[0]["effect_id"] == 9
        assert calls[0]["invert_media"] is True
    finally:
        extera_ios.host = original


def test_send_message_param_helpers():
    """`cast_to_array_list`/`cast_to_hash_map` mirror Android's Java casts."""
    from client_utils import cast_to_array_list, cast_to_hash_map

    values = cast_to_array_list([1, 2])
    assert values.get(0) == 1
    assert values.size() == 2
    empty = cast_to_array_list([])
    assert empty is not None and empty.size() == 0

    mapping = cast_to_hash_map({"a": 1})
    assert mapping.get("a") == "1"
    assert cast_to_hash_map({}) is None


def test_file_loader_photo_cache():
    """Photos use the same `photo_<id>.jpg` name for the cache path and writes."""
    import telegram_compat

    work = tempfile.mkdtemp(prefix="extera-photo-")
    original = telegram_compat._path_for
    telegram_compat._path_for = lambda kind: work
    try:
        path = os.path.join(work, "photo_9.jpg")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xd8\xff")
        media = {
            "_": "messageMediaPhoto",
            "photo": {
                "id": 9,
                "access_hash": 1,
                "file_reference": "",
                "sizes": [
                    {"_": "photoSize", "type": "m", "w": 100, "h": 100, "size": 1000},
                    {"_": "photoSize", "type": "x", "w": 200, "h": 200, "size": 4000},
                ],
            },
        }
        assert telegram_compat.FileLoader.getAttachFileName(media) == "photo_9.jpg"
        assert telegram_compat.FileLoader.getPathToAttach(media).getPath() == path
        cached = telegram_compat.FileLoader.loadFile(media)
        assert cached is not None
        assert cached.getPath() == path
        assert telegram_compat.FileLoader.getFileProgress("photo_9.jpg") == 1.0
    finally:
        telegram_compat._path_for = original
        shutil.rmtree(work, ignore_errors=True)


def test_file_loader_download_cache():
    """A cached document is returned without starting a download."""
    import telegram_compat

    work = tempfile.mkdtemp(prefix="extera-download-")
    original = telegram_compat._path_for
    telegram_compat._path_for = lambda kind: work
    try:
        path = os.path.join(work, "photo.jpg")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xd8\xff")
        media = {
            "_": "messageMediaDocument",
            "document": {"id": 1, "file_name": "photo.jpg", "size": 3},
        }
        cached = telegram_compat.FileLoader.loadFile(media)
        assert cached is not None
        assert cached.getPath() == path
        assert telegram_compat.FileLoader.isLoadingFile("photo.jpg") is False
        assert telegram_compat.FileLoader.getFileProgress("photo.jpg") == 1.0
        assert telegram_compat.FileLoader.getAttachFileName(media) == "photo.jpg"
    finally:
        telegram_compat._path_for = original
        shutil.rmtree(work, ignore_errors=True)


def test_connections_manager():
    from org.telegram.tgnet import ConnectionsManager

    manager = ConnectionsManager.getInstance(3)
    assert manager.isConnected() is True
    assert manager.getConnectionState() == 3
    assert manager.getCurrentDatacenterId() == 1
    assert isinstance(manager.getCurrentTime(), int)
    assert manager.cancelRequest(1) is None
    assert manager.bindRequestToGuid(1, 2) is None
    assert manager.getPingTime() == 0
    assert manager.getLangCode() == "en"
    manager.setLangCode("de")
    assert manager.getLangCode() == "de"
    assert manager.isTestBackend() is False
    manager.setTestBackend(True)
    manager.pauseNetwork()
    manager.resumeNetwork()
    assert manager.getProxySettings() is None
    manager.setProxySettings(None)

    from org.telegram.messenger import AccountInstance

    account = AccountInstance.getInstance(0)
    assert account.getLocationController() is not None
    assert account.getMediaController() is not None
    assert account.getTopicsController() is not None


def test_chat_user_dialog_objects():
    """ChatObject/UserObject/DialogObject read TL shapes like Android's."""
    from org.telegram.messenger import ChatObject, DialogObject, UserObject

    channel = {
        "id": -1000000000000 - 200,
        "title": "Channel",
        "_": "channel",
        "broadcast": True,
        "username": "chan",
    }
    assert ChatObject.isChannel(channel) is True
    assert ChatObject.isBroadcast(channel) is True
    assert ChatObject.isMegagroup(channel) is False
    assert ChatObject.isChannelAndNotMegaGroup(channel) is True
    assert ChatObject.getPublicUsername(channel) == "chan"
    assert ChatObject.isPublic(channel) is True

    group = {"_": "chat", "chat_id": 77, "title": "Group", "megagroup": True}
    assert ChatObject.isGroup(group) is True
    assert ChatObject.isMegagroup(group) is True
    assert ChatObject.isChannel(group) is False
    assert ChatObject.isPublic(group) is False

    user = {
        "id": 501,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "username": "ada",
        "premium": True,
    }
    assert UserObject.getUserName(user) == "Ada Lovelace"
    assert UserObject.getFirstName(user) == "Ada"
    assert UserObject.getLastName(user) == "Lovelace"
    assert UserObject.getPublicUsername(user) == "ada"
    assert UserObject.isPremium(user) is True
    assert UserObject.isBot(user) is False

    channel_dialog_id = -1000000000000 - 200
    assert DialogObject.isUserDialog(501) is True
    assert DialogObject.isChatDialog(-77) is True
    assert DialogObject.isChannelDialog(channel_dialog_id) is True
    assert DialogObject.isChatDialog(channel_dialog_id) is True
    assert DialogObject.makeChannelDialogId(200) == channel_dialog_id
    assert DialogObject.makeChatDialogId(77) == -77
    assert DialogObject.makeUserDialogId(501) == 501

    folder_id = DialogObject.makeFolderDialogId(5)
    assert DialogObject.isFolderDialogId(folder_id) is True
    assert DialogObject.getFolderId(folder_id) == 5
    assert DialogObject.isUserDialog(folder_id) is False
    assert DialogObject.isChatDialog(folder_id) is False

    encrypted_id = DialogObject.makeEncryptedDialogId(9)
    assert DialogObject.isEncryptedDialog(encrypted_id) is True
    assert DialogObject.getEncryptedChatId(encrypted_id) == 9
    assert DialogObject.isUserDialog(encrypted_id) is False
    assert DialogObject.isChatDialog(encrypted_id) is False

    assert DialogObject.getPeerDialogId({"user_id": 5}) == 5
    assert DialogObject.getPeerDialogId({"chat_id": 7}) == -7
    assert DialogObject.getPeerDialogId({"channel_id": 9}) == -9
    assert DialogObject.getDialogId({"_": "user", "id": 5}) == 5
    assert DialogObject.getDialogId({"_": "chat", "id": 7}) == -7
    assert DialogObject.getShortTitle({"first_name": "Ada"}) == "Ada"
    assert DialogObject.getDialogTitle({"title": "Group"}) == "Group"

    dialog = {"_": "dialog", "id": 0, "peer": {"user_id": 5}}
    assert DialogObject.initDialog(dialog) == 5
    assert dialog["id"] == 5


def test_messages_controller_overlay():
    """Users/chats a plugin registers are visible through every getter."""
    from org.telegram.messenger import MessagesController, MessagesStorage

    account = 3
    controller = MessagesController.getInstance(account)

    user = {"id": 501, "first_name": "Ada", "last_name": "Lovelace", "username": "ada"}
    controller.putUser(user, False)
    assert controller.getUser(501) == user
    assert controller.getUserOrChat(501) == user

    chat = {"id": -100200, "title": "Channel"}
    controller.putChat(chat, False)
    assert controller.getChat(-100200) == chat
    assert controller.getPeer(-100200) == chat

    storage = MessagesStorage.getInstance(account)
    storage.putUsersAndChats(
        [{"id": 502, "first_name": "Grace"}],
        [{"id": -100201, "title": "Group"}],
    )
    assert controller.getUser(502)["first_name"] == "Grace"
    assert controller.getChat(-100201)["title"] == "Group"
    assert 502 in storage.getUsers()
    assert -100201 in storage.getChats()


def test_message_object_payload_methods():
    """A wrapped message answers the same getters as Android's MessageObject."""
    import telegram_compat

    message = telegram_compat.MessageObject({
        "id": 7,
        "peer_id": -100123,
        "from_id": 42,
        "message": "hello",
        "media": None,
        "date": 100,
        "out": True,
    })
    assert message.getId() == 7
    assert message.getDialogId() == -100123
    assert message.getSenderId() == 42
    assert message.isOutOwner() is True
    assert message.isMediaEmpty() is True
    assert message.getMedia() is None
    assert message.getMessageText() == "hello"
    assert message.getDate() == 100
    assert message.isReply() is False
    assert message.isUnknownFlag() is False
    assert message.getUnknownValue() is None
    assert message.messageOwner["id"] == 7

    media_message = telegram_compat.MessageObject({
        "id": 8,
        "peer_id": 5,
        "media": {"_": "messageMediaPhoto"},
        "reply_to": {"reply_to_msg_id": 3},
    })
    assert media_message.isMediaEmpty() is False
    assert media_message.getMedia()["_"] == "messageMediaPhoto"
    assert media_message.isReply() is True
    assert media_message.getReplyMsgId() == 3

    channel_message = telegram_compat.MessageObject({
        "id": 9,
        "peer_id": -1001234567890,
        "from_id": 42,
        "post": True,
        "edit_date": 55,
        "grouped_id": 77,
        "media": {
            "_": "messageMediaDocument",
            "document": {
                "id": 1,
                "attributes": [
                    {"_": "documentAttributeAudio", "duration": 12,
                     "title": "Song", "performer": "Artist"},
                    {"_": "documentAttributeSticker", "alt": "🙂",
                     "stickerset": {"id": 5, "short_name": "cats"}},
                ],
            },
        },
    })
    assert channel_message.getChatId() == -1001234567890
    assert channel_message.getChannelId() == 1001234567890
    assert channel_message.isFromChannel() is True
    assert channel_message.isFromUser() is False
    assert channel_message.isEdited() is True
    assert channel_message.getMaxEditDate() == 55
    assert channel_message.hasValidGroupId() is True
    assert channel_message.getGroupId() == 77
    assert channel_message.getDocumentDuration() == 12
    assert channel_message.getMusicTitle() == "Song"
    assert channel_message.getMusicAuthor() == "Artist"
    assert channel_message.getStickerChar() == "🙂"
    assert channel_message.getStickerSetName() == "cats"
    assert channel_message.getStickerSetId() == 5
    assert channel_message.getDuration() == 12
    assert channel_message.isSticker() is True
    assert channel_message.isStickerDocument() is True
    assert channel_message.hasAttachedStickers() is True
    assert channel_message.isAnyKindOfSticker() is True
    assert channel_message.getInputStickerSet()["id"] == 5
    assert channel_message.getFromPeer() == 42
    assert channel_message.isSent() is True
    assert channel_message.isForwardedMessage() is False
    assert channel_message.getMimeType() == ""

    from org.telegram.messenger import FileLoader

    assert channel_message.getMediaType() == FileLoader.MEDIA_DIR_DOCUMENT

    poll_message = telegram_compat.MessageObject({
        "id": 10,
        "peer_id": 5,
        "media": {
            "_": "messageMediaPoll",
            "poll": {"id": 4, "hash": 9, "quiz": True, "closed": True},
            "results": {"results": [{"option": b"a", "voters": 1}]},
        },
    })
    assert poll_message.isPoll() is True
    assert poll_message.isQuiz() is True
    assert poll_message.getPollId() == 4
    assert poll_message.getPollHash() == 9
    assert poll_message.isPollClosed() is True
    assert poll_message.isVoted() is True
    assert poll_message.hasVoteResults() is True

    replies_message = telegram_compat.MessageObject({
        "id": 11,
        "peer_id": 5,
        "replies": {"replies": 3, "comments": True},
        "reply_to": {"reply_to_msg_id": 1, "reply_to_top_id": 2,
                     "reply_to_peer_id": {"id": 5}},
    })
    assert replies_message.hasReplies() is True
    assert replies_message.getRepliesCount() == 3
    assert replies_message.isComments() is True
    assert replies_message.getReplyAnyMsgId() == 1
    assert replies_message.getReplyTopMsgId() == 2
    assert replies_message.getReplyToDialogId() == 5

    forwarded = telegram_compat.MessageObject({
        "id": 12,
        "peer_id": 5,
        "fwd_from": {"from_id": {"id": 9}, "from_name": "Channel",
                     "channel_post": 3},
    })
    assert forwarded.isPrivateForward() is True
    assert forwarded.isForwardedChannelPost() is True
    assert forwarded.getForwardedFromId() == 9
    assert forwarded.getForwardedName() == "Channel"

    video_message = telegram_compat.MessageObject({
        "id": 13,
        "peer_id": 5,
        "media": {
            "_": "messageMediaDocument",
            "document": {
                "id": 2,
                "attributes": [
                    {"_": "documentAttributeVideo", "w": 640, "h": 360,
                     "video_codec": "h264", "video_start_ts": 2,
                     "duration": 30},
                ],
            },
        },
    })
    assert video_message.getVideoWidth() == 640
    assert video_message.getVideoHeight() == 360
    assert video_message.getVideoCodec() == "h264"
    assert video_message.getVideoStartsTimestamp() == 2
    assert video_message.getMediaType() == FileLoader.MEDIA_DIR_VIDEO
    assert video_message.getDuration() == 30

    audio_message = telegram_compat.MessageObject({
        "id": 15,
        "peer_id": 5,
        "media": {
            "_": "messageMediaDocument",
            "document": {
                "id": 3,
                "attributes": [
                    {"_": "documentAttributeAudio", "voice": True,
                     "waveform": b"\x01\x02", "duration": 4},
                ],
            },
        },
    })
    assert audio_message.getWaveform() == b"\x01\x02"
    assert audio_message.getMediaType() == FileLoader.MEDIA_DIR_AUDIO

    misc = telegram_compat.MessageObject({
        "id": 14,
        "peer_id": 5,
        "quick_reply_shortcut_id": 7,
        "factcheck": {"text": "checked"},
        "ttl_seconds": 60,
    })
    assert misc.getQuickReplyId() == 7
    assert misc.getFactCheckText() == "checked"
    assert misc.getSecretTimeLeft() >= 0
    assert misc.getSecretTimeString()
    assert misc.isEphemeral() is False


def test_plugin_execution_watchdog():
    """Queued callbacks report start/finish to Android's watchdog."""
    import extera_ios

    calls = []
    original = extera_ios.host

    def fake_host(name, **kwargs):
        if name in ("runtime.plugin_started", "runtime.plugin_finished"):
            calls.append((name, kwargs.get("plugin_id")))
            return None
        return original(name, **kwargs)

    extera_ios.host = fake_host
    try:
        ran = []
        result = _extera_runtime.execute_plugin_callback(
            "watchdog_demo", lambda: (ran.append(True), 42)[1]
        )
        assert result == 42
        assert ran == [True]
        assert calls == [
            ("runtime.plugin_started", "watchdog_demo"),
            ("runtime.plugin_finished", "watchdog_demo"),
        ], calls
    finally:
        extera_ios.host = original


def test_analyzer_diff():
    """An update is compared with the installed copy like Android's analyzer."""
    import extera_analyzer

    old = "import socket\n"
    new = "import socket\nimport subprocess\n" + "subprocess.run('id')\n" * 6
    diff = extera_analyzer.diff_reports(
        extera_analyzer.analyze_source(old, "demo.plugin"),
        extera_analyzer.analyze_source(new, "demo.plugin"),
    )
    statement_ids = {item["id"] for item in diff["new_statements"]}
    assert "native_code" in statement_ids, diff
    changed = {item["rule"]: item["new_values"] for item in diff["new_findings"]}
    assert changed.get("py.native") == ["subprocess"], changed
    assert changed.get("py.subprocess"), changed

    # Evidence is capped for display but the total is not.
    native = next(
        finding for finding in extera_analyzer.analyze_source(new, "demo.plugin")["findings"]
        if finding["rule"] == "py.subprocess"
    )
    assert native["evidence_total"] > len(native["evidence"]), native
    assert native["evidence_total"] >= 6, native

    work = tempfile.mkdtemp(prefix="extera-diff-")
    try:
        old_path = os.path.join(work, "old.plugin")
        new_path = os.path.join(work, "new.plugin")
        with open(old_path, "w", encoding="utf-8") as handle:
            handle.write(old)
        with open(new_path, "w", encoding="utf-8") as handle:
            handle.write(new)
        compare = extera_analyzer.analyze_compare(old_path, new_path, "demo.plugin")
        assert compare["report"]["max_severity"] in ("danger", "critical"), compare
        assert compare["diff"]["new_findings"], compare
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_android_constant_parity():
    """Enum and notification values are the strings Android's SDK sends."""
    from base_plugin import (
        AppEvent,
        HookFilter,
        HookResult,
        HookStrategy,
        IntentHookType,
        MenuItemType,
    )
    import base_plugin

    assert {item.value for item in AppEvent} == {
        "app_start", "app_stop", "app_pause", "app_resume",
    }
    assert {item.value for item in MenuItemType} == {
        "message_context_menu", "drawer_menu", "main_menu",
        "chat_action_menu", "profile_action_menu",
    }
    assert {item.value for item in HookStrategy} == {
        "CANCEL", "MODIFY", "DEFAULT", "MODIFY_FINAL",
    }
    assert {item.value for item in HookFilter} == {
        "result_is_null", "result_is_true", "result_is_false", "result_not_null",
    }
    assert IntentHookType.BEFORE.value == 0
    assert IntentHookType.AFTER.value == 1
    assert HookResult().strategy is HookStrategy.DEFAULT
    assert base_plugin.HookFilterData("result_is_true").to_native()["type"] == "result_is_true"

    import telegram_compat

    # The metaclass resolves every Android notification constant to its name.
    assert telegram_compat.NotificationCenter.pluginsUpdated == "pluginsUpdated"
    assert telegram_compat.NotificationCenter.pluginCatalogUpdated == "pluginCatalogUpdated"
    assert telegram_compat.NotificationCenter.pluginSettingsRegistered == "pluginSettingsRegistered"


def test_android_partial_hooks_example():
    """The Android SDK's own `partial_hooks_demo.plugin` loads unchanged."""
    work = tempfile.mkdtemp(prefix="extera-android-example-")
    plugins = os.path.join(work, "plugins")
    os.makedirs(plugins, exist_ok=True)
    source = os.path.join(ROOT, "Examples", "partial_hooks_demo.plugin")
    path = os.path.join(plugins, "partial_hooks_demo.plugin")
    shutil.copyfile(source, path)

    _extera_runtime.initialize(SDK, plugins, work)
    loaded = json.loads(_extera_runtime.load_plugin("partial_hooks_demo", path))
    assert loaded["ok"], loaded
    instance = _extera_runtime._PLUGINS["partial_hooks_demo"].instance
    assert instance.name == "Partial Hooks Demo"
    assert instance.version == "1.0.0"
    assert instance.author == "exteraGram"
    unloaded = json.loads(_extera_runtime.unload_plugin("partial_hooks_demo"))
    assert unloaded["ok"] is True
    shutil.rmtree(work, ignore_errors=True)


ANDROID_IMPORT_SURFACE = {
    "android.app": ["Activity"],
    "android.content": ["Context", "DialogInterface", "Intent"],
    "android.graphics": ["Bitmap", "Typeface"],
    "android.graphics.drawable": ["BitmapDrawable", "Drawable"],
    "android.media": ["MediaMetadataRetriever"],
    "android.net": ["Uri"],
    "android.text": ["InputType", "TextWatcher"],
    "android.util": ["Log", "TypedValue"],
    "android.view": ["Gravity", "HapticFeedbackConstants", "View"],
    "android.view.inputmethod": ["EditorInfo"],
    "android.webkit": ["MimeTypeMap"],
    "android.widget": ["FrameLayout", "LinearLayout", "ScrollView", "TextView"],
    "androidx.core.content": ["ContextCompat"],
    "com.exteragram.hook": [
        "ExteraHook", "HookTarget", "InstructionMatcher", "Interceptor",
    ],
    "com.exteragram.messenger": ["ExteraConfig"],
    "com.exteragram.messenger.plugins": [
        "Plugin", "PluginsConstants", "PluginsController", "PythonPluginsEngine",
    ],
    "com.exteragram.messenger.plugins.hooks": ["HookFilter", "PluginsHooks"],
    "com.exteragram.messenger.plugins.models": [
        "CustomSetting", "DividerSetting", "EditTextSetting", "HeaderSetting",
    ],
    "com.exteragram.messenger.plugins.pip": ["PipController"],
    "com.exteragram.messenger.plugins.ui": [
        "PluginSettingsActivity", "PluginsActivity", "PluginsInfoActivity",
    ],
    "com.exteragram.messenger.plugins.ui.components": [
        "InstallPluginBottomSheet", "PluginCellDelegate", "RequiredPluginInfo",
    ],
    "com.exteragram.messenger.plugins.utils": ["ClassProxy"],
    "com.exteragram.messenger.plugins.xposed": [
        "PyMethodHook", "PyMethodReplacement",
    ],
    "com.exteragram.messenger.utils": ["AppUtils", "IntentsController"],
    "org.telegram.messenger": [
        "AccountInstance", "AndroidUtilities", "ApplicationLoader", "BuildVars",
        "DispatchQueue", "FileLoader", "ImageLoader", "ImageLocation",
        "LocaleController", "MediaController", "MessageObject",
        "NotificationCenter", "R", "SendMessagesHelper", "SharedConfig",
        "SvgHelper", "UserConfig", "Utilities",
    ],
    "org.telegram.tgnet": ["RequestDelegate", "TLObject", "TLRPC"],
    "org.telegram.ui": ["LaunchActivity"],
    "org.telegram.ui.ActionBar": ["AlertDialog", "BaseFragment", "Theme"],
    "org.telegram.ui.Cells": ["ChatMessageCell"],
    "org.telegram.ui.Components": [
        "Bulletin", "BulletinFactory", "EditTextBoldCursor", "LayoutHelper",
        "MediaActionDrawable", "RLottieDrawable", "UItem", "UniversalAdapter",
    ],
    "org.telegram.ui.Stories.recorder": ["ButtonWithCounterView"],
}


def test_android_import_surface():
    """Every class the Android SDK itself imports is importable from iOS."""
    import importlib

    imported = []
    for module_name, names in ANDROID_IMPORT_SURFACE.items():
        module = importlib.import_module(module_name)
        for name in names:
            assert hasattr(module, name), "%s.%s is missing" % (module_name, name)
            imported.append(name)
    assert len(imported) == 86


def test_partial_hook_api():
    """`com.exteragram.hook` maps Android's instruction hooks onto iOS hooks."""
    from com.exteragram.hook import (
        ExteraHook,
        HookTarget,
        InstructionMatcher,
        Interceptor,
    )
    from extera_utils.classes import MemberRef

    outer = MemberRef("Example", "outer")
    callee = MemberRef("Example", "inner")

    assert HookTarget.callSite(outer, callee).resolve()[:2] == ("Example", "inner")
    assert HookTarget.fieldRead(outer, MemberRef("Example", "value")).resolve()[:2] == (
        "Example",
        "value",
    )
    assert HookTarget.fieldWrite(outer, MemberRef("Example", "value")).resolve()[:2] == (
        "Example",
        "setValue",
    )
    assert HookTarget.instruction(
        outer, InstructionMatcher.returnValue()
    ).resolve()[:2] == ("Example", "outer")

    # String-literal hooks are bytecode targets; iOS reports "not installed".
    assert (
        HookTarget.instruction(
            outer, InstructionMatcher.constString("hello")
        ).resolve()
        is None
    )

    class Demo(Interceptor):
        def intercept(self, chain):
            return chain.proceed()

    builder = ExteraHook.hook(HookTarget.callSite(outer, callee))
    assert builder.priority(5) is builder
    # Without the app there is no class to swizzle, so installing degrades to None.
    assert builder.intercept(Demo()) is None

    chain = partial_hooks.PartialChain(
        HookTarget.callSite(outer, callee), {"id": None, "this": None, "args": [1, 2]}
    )
    assert chain.getThisObject() is None
    assert chain.getCaller() is None
    assert chain.getArgs() == [1, 2]
    assert chain.arg(1) == 2
    assert chain.proceed() is None
    assert chain.proceeded is True


def test_partial_hook_registration():
    """`PluginsController` tracks Xposed and partial handles per plugin."""
    from com.exteragram.messenger.plugins import PluginsController

    class FakeUnhook:
        def __init__(self, handle):
            self._handle = handle

    class FakePartial:
        def __init__(self, handle):
            self.handle = handle
            self.unhooked = False

        def unhook(self):
            self.unhooked = True

    controller = PluginsController.getInstance()
    xposed = FakeUnhook("hook-fake")
    assert controller.addXposedHook("test-plugin", xposed) is True
    assert xposed in controller._xposed_hooks["test-plugin"]
    assert controller.removeXposedHook("test-plugin", xposed) is True
    assert xposed not in controller._xposed_hooks["test-plugin"]

    partial = FakePartial("hook-fake")
    assert controller.addPartialHook("test-plugin", partial) is True
    assert partial in controller._partial_hooks["test-plugin"]
    assert controller.removePartialHook("test-plugin", partial) is True
    assert partial.unhooked is True
    assert partial not in controller._partial_hooks["test-plugin"]


def test_android_member_surface():
    """Members the Android SDK calls on those classes exist on iOS too."""
    from android.app import Activity
    from android.content import Intent
    from android.graphics import Bitmap
    from android.graphics.drawable import Drawable
    from android.net import Uri
    from com.exteragram.messenger.plugins import (
        PluginsConstants,
        PluginsController,
        PythonPluginsEngine,
    )
    from com.exteragram.messenger.plugins.models import CustomSetting
    from com.exteragram.messenger.utils import IntentsController
    from org.telegram.messenger import (
        AndroidUtilities,
        ApplicationLoader,
        FileLoader,
        MediaMetadataRetriever,
        MessageObject,
        SendMessageParams,
        SendMessagesHelper,
        SvgHelper,
        Utilities,
    )
    from org.telegram.ui.ActionBar import AlertDialog, Theme
    from org.telegram.ui.Components import (
        Bulletin,
        BulletinFactory,
        UItem,
        UniversalAdapter,
    )

    assert Intent.EXTRA_STREAM == "android.intent.extra.STREAM"
    assert Intent.FLAG_GRANT_READ_URI_PERMISSION == 1
    chooser = Intent.createChooser(Intent(Intent.ACTION_SEND), "Share")
    assert chooser.getAction() == Intent.ACTION_CHOOSER
    assert Intent.getClass().getName() == "android.content.Intent"
    assert Uri.getClass().getName() == "android.net.Uri"

    assert Activity.getClass().getName() == "android.app.Activity"
    assert Utilities.getClass().getName() == "org.telegram.messenger.Utilities"
    assert (
        AndroidUtilities.getClass().getName()
        == "org.telegram.messenger.AndroidUtilities"
    )
    assert ApplicationLoader.getApplicationId()
    assert FileLoader.MEDIA_DIR_DOCUMENT == FileLoader.MEDIA_DIR_DOCUMENTS == 3
    assert MediaMetadataRetriever.METADATA_KEY_TITLE == 7
    assert MediaMetadataRetriever.METADATA_KEY_ARTIST == 2
    assert SendMessagesHelper.SendMessageParams is SendMessageParams
    assert MessageObject.getClass().getName() == "org.telegram.messenger.MessageObject"

    scaled = Bitmap.createScaledBitmap(None, 10, 20, True)
    assert (scaled.getWidth(), scaled.getHeight()) == (10, 20)
    assert Drawable.createFromPath("/tmp/x").path == "/tmp/x"
    assert Drawable.createFromStream(None, "x").name == "x"
    assert isinstance(SvgHelper.getDrawable(b"<svg/>"), SvgHelper.SvgDrawable)
    assert SvgHelper.getBitmap(b"", 3, 4).getWidth() == 3

    assert Theme.ResourcesProvider.getClass().getName().endswith("ResourcesProvider")
    assert PluginsConstants.Settings.TYPE_SWITCH == "switch"
    assert PluginsController.getClass().getName().endswith("PluginsController")
    assert PythonPluginsEngine.getClass().getName().endswith("PythonPluginsEngine")
    assert IntentsController.getClass().getName().endswith("IntentsController")
    assert CustomSetting.Factory is not None

    factory = object()
    UItem.registerFactory(77, factory)
    assert UItem.findFactory(77) is factory
    assert UItem.getClass().getName() == "org.telegram.ui.Components.UItem"
    assert UItem.UItemFactory.setup(None) is None

    assert Bulletin.DURATION_SHORT == 1500
    assert Bulletin.DURATION_LONG == 3200
    assert Bulletin.EmptyBulletin is not None
    assert BulletinFactory.FileType.PHOTO == "PHOTO"
    assert UniversalAdapter.getClass().getName().endswith("UniversalAdapter")
    assert AlertDialog.OnButtonClickListener is not None

    # `X.getClass().getDeclaredMethod(...)` returns a hookable member handle.
    method = Activity.getClass().getDeclaredMethod(
        "openForView", MessageObject.getClass(), Activity.getClass()
    )
    assert method.getName() == "openForView"
    assert method.getDeclaringClass().getName() == "android.app.Activity"


def test_runtime_services():
    """DispatchQueue/ImageLoader/R and the plugin model are functional."""
    import tempfile as _tempfile

    from com.exteragram.messenger.plugins import Plugin
    from com.exteragram.messenger.plugins.hooks import PluginsHooks
    from com.exteragram.messenger.plugins.ui.components import RequiredPluginInfo
    from com.exteragram.messenger.plugins.xposed import (
        PyMethodHook,
        PyMethodReplacement,
    )
    from org.telegram.messenger import DispatchQueue, ImageLoader, R
    from org.telegram.ui.Cells import ChatMessageCell

    seen = []
    queue = DispatchQueue("parity-queue")
    queue.runOnQueue(lambda: seen.append(queue.getQueueName()))
    import time as _time

    for _ in range(50):
        if seen:
            break
        _time.sleep(0.01)
    assert seen == ["parity-queue"]

    work = _tempfile.mkdtemp(prefix="image-loader-")
    path = os.path.join(work, "photo.bin")
    with open(path, "wb") as handle:
        handle.write(b"not-a-real-image")
    bitmap = ImageLoader.loadBitmap(path, None, 128, 128, True)
    assert bitmap is not None and bitmap.getWidth() == 0
    size = ImageLoader.scaleAndSaveImage(bitmap, 90, 90, 55, True)
    assert size is not None and size.w == 90 and size.h == 90
    assert size.to_json()["_"] == "photoSize"
    shutil.rmtree(work, ignore_errors=True)

    assert R.string.TextCopied == "R.string.TextCopied"
    assert R.raw.info == "R.raw.info"

    plugin = Plugin("demo", "Demo", {"version": "1.0"})
    assert (plugin.getId(), plugin.getName()) == ("demo", "Demo")
    plugin.setEnabled(True)
    assert plugin.isEnabled() is True

    info = RequiredPluginInfo("base")
    info.state = RequiredPluginInfo.STATE_SATISFIED
    assert info.isSatisfied() is True
    assert RequiredPluginInfo.STATE_MISSING != RequiredPluginInfo.STATE_SATISFIED

    result = PluginsHooks.PostRequestResult("response", "error")
    assert (result.getResponse(), result.getError()) == ("response", "error")

    calls = []

    class Hook:
        def before_hooked_method(self, param):
            calls.append(("before", param))

        def after_hooked_method(self, param):
            calls.append(("after", param))

    callback = PyMethodHook("demo", Hook())
    callback.before_hooked_method({"result": 1})
    callback.after_hooked_method({"result": 2})
    assert calls == [("before", {"result": 1}), ("after", {"result": 2})]
    assert PyMethodHook.getClass().getName().endswith("PyMethodHook")
    assert PyMethodReplacement.getClass().getName().endswith("PyMethodReplacement")

    assert ChatMessageCell.getClass().getName() == "org.telegram.ui.Cells.ChatMessageCell"


def test_partial_hook_install_path():
    """`hook_call_site`/`hook_return_value` reach the ObjC swizzle host call."""
    work = tempfile.mkdtemp(prefix="extera-partial-install-")
    plugins = os.path.join(work, "plugins")
    os.makedirs(plugins, exist_ok=True)
    path = os.path.join(plugins, "partial_install.plugin")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "from base_plugin import BasePlugin\n"
            "__id__ = \"partial_install\"\n"
            "__name__ = \"Partial install\"\n"
            "__description__ = \"partial hook install path\"\n"
            "__author__ = \"tests\"\n"
            "__version__ = \"1.0\"\n"
            "class PartialInstall(BasePlugin):\n"
            "    pass\n"
        )

    _extera_runtime.initialize(SDK, plugins, work)
    loaded = json.loads(_extera_runtime.load_plugin("partial_install", path))
    assert loaded["ok"], loaded
    plugin = _extera_runtime._PLUGINS["partial_install"].instance

    from extera_utils.classes import MemberRef

    _native.reset()
    outer = MemberRef("Example", "outer")
    callee = MemberRef("Example", "inner")
    assert plugin.hook_call_site(outer, callee, lambda chain: chain.proceed()) is None
    swizzles = [
        data for method, data in _native.calls() if method == "runtime.swizzle"
    ]
    assert any(data.get("selector") == "inner" for data in swizzles), swizzles
    assert any(data.get("class_name") == "Example" for data in swizzles)

    _native.reset()
    assert plugin.hook_return_value(outer, lambda chain: chain.proceed()) is None
    swizzles = [
        data for method, data in _native.calls() if method == "runtime.swizzle"
    ]
    assert any(data.get("selector") == "outer" for data in swizzles), swizzles

    # A string literal is bytecode; the hook reports "not installed".
    _native.reset()
    assert plugin.hook_string_constant(outer, "hello", lambda chain: "x") is None
    assert not [
        data for method, data in _native.calls() if method == "runtime.swizzle"
    ]

    assert json.loads(_extera_runtime.unload_plugin("partial_install"))["ok"] is True
    shutil.rmtree(work, ignore_errors=True)


def test_edit_message_media_payload():
    """`extera_ios.edit_message(path=...)` carries the media path and its kind."""
    from extera_ios import edit_message

    work = tempfile.mkdtemp(prefix="edit-media-")
    photo = os.path.join(work, "photo.jpg")
    with open(photo, "wb") as handle:
        handle.write(b"jpeg")
    document = os.path.join(work, "file.pdf")
    with open(document, "wb") as handle:
        handle.write(b"pdf")
    try:
        _native.reset()
        edit_message(0, 1, 2, text="caption", path=photo)
        calls = [
            data for method, data in _native.calls()
            if method == "client.edit_message"
        ]
        assert calls and calls[-1]["path"] == photo
        assert calls[-1]["kind"] == "photo"

        _native.reset()
        edit_message(0, 1, 2, text="caption", path=document)
        calls = [
            data for method, data in _native.calls()
            if method == "client.edit_message"
        ]
        assert calls and calls[-1]["kind"] == "document"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_send_media_helpers():
    """`send_location`/`send_contact`/`send_dice` build `messages.sendMedia` payloads."""
    import client_utils

    _native.reset()
    result = client_utils.send_location(1, 55.75, 37.61, account=0, accuracy_radius=10)
    assert isinstance(result, dict)
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls and calls[-1]["name"] == "messages.sendMedia"
    payload = calls[-1]["payload"]
    assert payload["peer"] == 1
    assert payload["media"]["_"] == "inputMediaGeoPoint"
    assert payload["media"]["geo_point"]["lat"] == 55.75
    assert payload["media"]["geo_point"]["long"] == 37.61
    assert payload["media"]["geo_point"]["accuracy_radius"] == 10

    _native.reset()
    client_utils.send_contact(1, "+100", "Ann", "Lee", account=0)
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    media = calls[-1]["payload"]["media"]
    assert media["_"] == "inputMediaContact"
    assert media["phone_number"] == "+100"
    assert media["first_name"] == "Ann"
    assert media["last_name"] == "Lee"

    _native.reset()
    client_utils.send_venue(1, 1.5, 2.5, "Cafe", "Street 1", account=0)
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    media = calls[-1]["payload"]["media"]
    assert media["_"] == "inputMediaVenue"
    assert media["title"] == "Cafe"
    assert media["address"] == "Street 1"

    _native.reset()
    client_utils.send_dice(1, "🎯", account=0)
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["payload"]["media"] == {
        "_": "inputMediaDice",
        "emoticon": "🎯",
    }

    _native.reset()
    client_utils.send_message({"peer": 9, "location": {"lat": 3.5, "long": 4.5}})
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["name"] == "messages.sendMedia"
    media = calls[-1]["payload"]["media"]
    assert media["_"] == "inputMediaGeoPoint"
    assert media["geo_point"]["lat"] == 3.5
    assert media["geo_point"]["long"] == 4.5

    _native.reset()
    client_utils.send_message({
        "peer": 9,
        "location": {
            "_": "messageMediaGeo",
            "geo": {"_": "geoPoint", "lat": 5.0, "long": 6.0},
        },
    })
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["payload"]["media"]["geo_point"]["long"] == 6.0

    _native.reset()
    client_utils.send_message({
        "peer": 3,
        "message": "choose",
        "replyMarkup": {
            "_": "replyInlineMarkup",
            "rows": [
                {
                    "_": "keyboardButtonRow",
                    "buttons": [
                        {
                            "_": "keyboardButtonUrl",
                            "text": "Open",
                            "url": "https://example.com",
                        },
                        {
                            "_": "keyboardButtonCallback",
                            "text": "Press",
                            "data": b"cb",
                        },
                    ],
                }
            ],
        },
    })
    calls = [
        data for method, data in _native.calls() if method == "client.send"
    ]
    assert calls and calls[-1]["reply_markup"] == {
        "rows": [[
            {"text": "Open", "url": "https://example.com", "data": None},
            {"text": "Press", "url": None, "data": "cb"},
        ]]
    }

    _native.reset()
    client_utils.send_message({
        "peer": 4,
        "user": {"phone": "+123", "first_name": "Ann", "last_name": "Lee"},
    })
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["name"] == "messages.sendMedia"
    media = calls[-1]["payload"]["media"]
    assert media["_"] == "inputMediaContact"
    assert media["phone_number"] == "+123"
    assert media["first_name"] == "Ann"
    assert media["last_name"] == "Lee"

    _native.reset()
    client_utils.send_sticker(
        2, {"id": 7, "access_hash": 8, "file_reference": b"\x01"}, "q"
    )
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["name"] == "messages.sendMedia"
    media = calls[-1]["payload"]["media"]
    assert media["_"] == "inputMediaDocument"
    assert media["id"] == 7
    assert media["access_hash"] == 8
    assert media["file_reference"] == "AQ=="
    assert media["query"] == "q"

    _native.reset()
    client_utils.send_existing_photo(2, {"id": 11, "access_hash": 12})
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    media = calls[-1]["payload"]["media"]
    assert media["_"] == "inputMediaPhoto"
    assert media["id"] == 11
    assert media["access_hash"] == 12

    from org.telegram.messenger import SendMessagesHelper

    helper = SendMessagesHelper.getInstance(0)
    _native.reset()
    helper.sendSticker({"id": 13, "access_hash": 14}, "", 2)
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    media = calls[-1]["payload"]["media"]
    assert media["_"] == "inputMediaDocument"
    assert media["id"] == 13

    from org.telegram.messenger import FileLoader

    assert FileLoader.getFileReference({"file_reference": b"\x01\x02"}) == b"\x01\x02"
    assert (
        FileLoader.getFileReference({"document": {"file_reference": "abc"}})
        == "abc"
    )
    assert FileLoader.getFileReference({"id": 1}) == ""
    assert FileLoader.isFileLoading("missing") is False
    assert FileLoader.getFileLoadingPriority("x") == 0

    _native.reset()
    helper.sendVote({"id": 5}, 9, [b"\x01", b"\x02"])
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["name"] == "messages.sendVote"
    assert calls[-1]["payload"] == {
        "peer": 5,
        "msg_id": 9,
        "options": ["AQ==", "Ag=="],
    }

    _native.reset()
    helper.sendCallback({"id": 5}, 9, b"cb")
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["name"] == "messages.getBotCallbackAnswer"
    assert calls[-1]["payload"] == {"peer": 5, "msg_id": 9, "data": "Y2I="}

    _native.reset()
    helper.sendReaction({"id": 5, "peer": 5}, ["👍"], "❤", big=True)
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["name"] == "messages.sendReaction"
    assert calls[-1]["payload"]["reaction"] == ["👍", "❤"]
    assert calls[-1]["payload"]["big"] is True

    _native.reset()
    helper.sendVote(
        {"id": 9, "peer": 5},
        [{"_": "pollAnswer", "option": b"\x01"}],
        None,
    )
    calls = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert calls[-1]["name"] == "messages.sendVote"
    assert calls[-1]["payload"]["options"] == ["AQ=="]


def test_class_proxy_facade():
    """`ClassProxy` builds a Python class with Android's handler contract."""
    from com.exteragram.messenger.plugins.utils import ClassProxy as CP
    from extera_utils.classes import MemberRef

    calls = []

    def handler(instance, signature, args):
        calls.append((signature, list(args)))
        return "handled:" + signature.split(":")[0]

    class Base:
        def __init__(self, value=0):
            self.value = value

    method = MemberRef("Base", "foo", ("java.lang.String",))
    spec = CP.ProxyMethodSpec("ping", "java.lang.String", ["java.lang.String"], 1, True)
    field = CP.FieldSpec(
        "title",
        "java.lang.String",
        1,
        [
            CP.FieldMethodSpec("getTitle", 1, True),
            CP.FieldMethodSpec("setTitle", 1, False),
        ],
    )
    Proxy = CP.createProxyClass(Base, handler, [method], [], [spec], [field])
    obj = Proxy(7)
    assert obj.value == 7
    assert obj.foo("x") == "handled:foo"
    assert obj.ping("y") == "handled:ping"
    obj.setTitle("hello")
    assert obj.title == "hello"
    assert obj.getTitle() == "hello"
    assert calls == [
        ("foo:java.lang.String", ["x"]),
        ("ping:java.lang.String", ["y"]),
    ]

    assert CP.runPythonRunnable(lambda: "ok") == "ok"
    assert CP.TypeHelper.unboxInt("42") == 42
    assert CP.TypeHelper.unboxBool(1) is True
    assert CP.TypeHelper.unboxDouble("2.5") == 2.5

    mvel = CP.ProxyMethodSpec(
        "isReady", implementation="mvel", mvelCode="1 == 1"
    )
    assert mvel.isMvel() is True
    MvelProxy = CP.createProxyClass(
        Base, handler, [MemberRef("Base", "ignored", ())], [], [mvel], []
    )
    assert MvelProxy().isReady() is True

    assert CP.ProxyMethodSpec("plain").isMvel() is False
    assert CP.FieldSpec("name").methods == []
    assert CP.DexMakerHook().apply(None, None, None, []) is None


def test_media_controller_playback():
    """`MediaController` plays a cached file through the host audio bridge."""
    from org.telegram.messenger import MediaController

    work = tempfile.mkdtemp(prefix="media-controller-")
    path = os.path.join(work, "track.m4a")
    with open(path, "wb") as handle:
        handle.write(b"audio")
    try:
        controller = MediaController.getInstance(0)
        message = {"id": 42, "path": path}

        _native.reset()
        assert controller.playMessage(message) is True
        plays = [
            data for method, data in _native.calls() if method == "audio.play"
        ]
        assert plays and plays[-1]["path"] == path
        assert controller.getPlayingMessageObject() is message
        assert controller.isPlayingMessage(message) is True
        assert controller.isPlayingMessage({"id": 7}) is False

        assert controller.isPlayingAudio() is False
        assert controller.getPlaybackPosition() == 0
        assert controller.getPlaybackDuration() == 0
        assert controller.getPlaybackSpeed() == 1.0

        controller.pauseAudio()
        controller.resumeAudio()
        controller.seekToProgress(0.5)
        controller.setPlaybackSpeed(1.5)
        controller.setPlaybackOrder(2)
        assert controller.getPlaybackOrder() == 2

        controller.setPlaylist([message])
        assert controller.getPlaylist() == [message]
        assert controller.getPlaylist() is controller.getPlaylist()
        controller.getPlaylist().clear()
        assert controller.getPlaylist() == []
        controller.setPlaylist([message])

        second = {"id": 43, "path": path}
        controller.setPlaylist([message, second])
        controller.playNextMessage()
        assert controller.getPlayingMessageObject() is second
        controller.playPreviousMessage()
        assert controller.getPlayingMessageObject() is message

        controller.stopPlayingMessage()
        assert controller.getPlayingMessageObject() is None
        assert controller.isPlayingMessage(message) is False

        player = controller.getVideoPlayer()
        assert player is not None
        player.setVolume(0.3)
        assert player.getVolume() == 0.3
        player.play()
        assert player.isPlaying() is True
        player.pause()
        assert player.isPlaying() is False
        player.releasePlayer()
        assert player.isPlaying() is False

        controller.audioVolume = 0.5
        assert isinstance(controller.audioVolume, float)
        controller.setPlaylist([message])
        assert controller.playMessage(message) is True
        assert controller.pauseMessage(message) is True
        controller.cleanupPlayer()
        assert controller.getPlaylist() == []
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_java_native_classes():
    """Java collections/IO/reflection names resolve to real Python objects."""
    from java.io import ByteArrayInputStream, File
    from java.lang import Class
    from java.lang.reflect import Member, Method
    from java.util import ArrayList, Arrays, HashMap
    from java.util.concurrent import ConcurrentHashMap

    values = ArrayList()
    values.add(1)
    values.add("two")
    assert isinstance(values, list)
    assert values.size() == 2
    assert values.get(0) == 1
    assert values.contains("two") is True
    assert ArrayList.getClass().getName() == "java.util.ArrayList"
    assert ArrayList(3) == []
    assert ArrayList([1, 2]) == [1, 2]

    mapping = HashMap()
    mapping.put("a", 1)
    assert mapping.get("a") == 1
    assert mapping.containsKey("a") is True
    assert ConcurrentHashMap(4).isEmpty() is True
    assert HashMap.getClass().getName() == "java.util.HashMap"

    assert Arrays.asList([1, 2]) == [1, 2]
    assert Arrays.toString([1, 2]) == "[1, 2]"
    assert Arrays.sort([2, 1]) == [1, 2]
    assert Arrays.equals([1], [1]) is True
    assert Arrays.copyOf([1, 2], 4) == [1, 2, None, None]

    file = File("/tmp/example.txt")
    assert file.getPath() == "/tmp/example.txt"
    assert File.getClass().getName() == "java.io.File"

    stream = ByteArrayInputStream(b"abc")
    assert stream.available() == 3
    assert stream.read() == 97
    assert stream.available() == 2
    stream.close()
    assert stream.read() == -1

    assert Class.forName("java.lang.String").getName() == "java.lang.String"
    assert Class.getName() == "java.lang.Class"

    member = Method("Example", "foo")
    assert member.getName() == "foo"
    assert Method.getClass().getName() == "java.lang.reflect.Method"
    assert Member is Method


def test_chaquopy_facade():
    """`com.chaquo.python` names wrap plain Python values."""
    from com.chaquo.python import PyException, PyObject, Python

    assert PyObject.getClass().getName() == "com.chaquo.python.PyObject"
    assert PyException("boom").getMessage() == "boom"
    assert isinstance(PyException("x"), Exception)

    obj = PyObject(lambda value: value + 1)
    assert obj.call(1).toJava(int) == 2
    assert PyObject({"a": 1}).get("a").toJava(int) == 1

    mapping = PyObject({})
    mapping.put("k", 2)
    assert mapping.get("k").toJava(int) == 2

    assert str(PyObject(5)) == "5"
    assert bool(PyObject([])) is False
    assert PyObject.fromJava(7).toJava(int) == 7

    module = Python.getInstance().getModule("math")
    assert abs(module.callAttr("sqrt", 9).toJava(float) - 3.0) < 1e-9
    assert Python.getInstance().getPlatform() == "ios"
    assert Python.getInstance().getVersion()

    try:
        PyObject(1).call()
        raise AssertionError("expected PyException")
    except PyException:
        pass


def test_messages_controller_loaders():
    """`MessagesController.load*` reaches the raw request handlers."""
    from org.telegram.messenger import MessagesController

    controller = MessagesController.getInstance(0)

    _native.reset()
    result = controller.loadFullUser({"id": 100})
    assert isinstance(result, dict)
    requests = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert requests and requests[-1]["name"] == "users.getFullUser"
    assert requests[-1]["payload"]["id"] == 100

    _native.reset()
    controller.loadFullChat({"id": 200, "kind": "channel"})
    requests = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert requests[-1]["name"] == "channels.getFullChannel"
    assert requests[-1]["payload"]["channel"] == 200

    _native.reset()
    controller.loadFullChat({"id": 300})
    requests = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert requests[-1]["name"] == "messages.getFullChat"
    assert requests[-1]["payload"]["chat_id"] == 300

    _native.reset()
    controller.loadMessages({"id": 400})
    requests = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert requests[-1]["name"] == "messages.getHistory"
    assert requests[-1]["payload"]["peer"] == 400

    _native.reset()
    controller.loadPeerSettings({"id": 500})
    requests = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert requests[-1]["name"] == "messages.getPeerSettings"
    assert requests[-1]["payload"]["peer"] == 500

    _native.reset()
    controller.loadUserPhotos({"id": 600})
    requests = [
        data for method, data in _native.calls() if method == "client.request"
    ]
    assert requests[-1]["name"] == "photos.getUserPhotos"
    assert requests[-1]["payload"]["id"] == 600

    assert controller.isSupportChat({"id": 777000}) is True
    assert controller.isSupportChat({"id": 1, "support": True}) is True
    assert controller.isSupportChat({"id": 1}) is False
    assert controller.canSendMessage({"left": True}) is False
    assert controller.canSendMessage({"id": 1}) is True


def test_messages_controller_actions():
    """`sendTyping`/`deleteMessages`/read/join/leave reach raw handlers."""
    from org.telegram.messenger import MessagesController

    controller = MessagesController.getInstance(0)

    def requests():
        return [
            data for method, data in _native.calls()
            if method == "client.request"
        ]

    _native.reset()
    controller.sendTyping({"id": 10}, "record")
    assert requests()[-1]["name"] == "messages.setTyping"
    assert requests()[-1]["payload"] == {"peer": 10, "action": "record"}

    _native.reset()
    controller.deleteMessages([{"id": 1}, {"id": 2}, 3], revoke=True)
    assert requests()[-1]["name"] == "messages.deleteMessages"
    assert requests()[-1]["payload"]["id"] == [1, 2, 3]
    assert requests()[-1]["payload"]["revoke"] is True

    _native.reset()
    controller.markDialogAsRead({"id": 20}, max_id=99)
    assert requests()[-1]["name"] == "messages.readHistory"
    assert requests()[-1]["payload"] == {"peer": 20, "max_id": 99}

    _native.reset()
    controller.readMentions({"id": 30})
    assert requests()[-1]["name"] == "messages.readMentions"

    _native.reset()
    controller.readReactions({"id": 30})
    assert requests()[-1]["name"] == "messages.readReactions"

    _native.reset()
    controller.joinChannel({"id": 40, "kind": "channel"})
    assert requests()[-1]["name"] == "channels.joinChannel"
    assert requests()[-1]["payload"]["channel"] == 40

    _native.reset()
    controller.leaveChannel({"id": 40, "kind": "channel"})
    assert requests()[-1]["name"] == "channels.leaveChannel"
    assert requests()[-1]["payload"]["channel"] == 40

    _native.reset()
    controller.deleteHistory({"id": 10}, revoke=True)
    assert requests()[-1]["name"] == "messages.deleteHistory"
    assert requests()[-1]["payload"]["peer"] == 10
    assert requests()[-1]["payload"]["revoke"] is True

    _native.reset()
    controller.markDialogAsUnread({"id": 10})
    assert requests()[-1]["name"] == "messages.markDialogUnread"
    assert requests()[-1]["payload"] == {"peer": 10, "unread": True}

    _native.reset()
    controller.mutePeer({"id": 12})
    assert requests()[-1]["name"] == "account.updateNotifySettings"
    assert requests()[-1]["payload"] == {
        "peer": 12,
        "mute_until": 2147483647,
        "show_previews": True,
    }

    _native.reset()
    controller.unmutePeer({"id": 12})
    assert requests()[-1]["payload"]["mute_until"] == 0

    _native.reset()
    controller.deleteDialog({"id": 15}, 1)
    assert requests()[-1]["name"] == "messages.deleteHistory"
    assert requests()[-1]["payload"]["peer"] == 15
    assert requests()[-1]["payload"]["just_clear"] is True

    assert controller.getDialogUnreadCount({"unread_count": 4}) == 4
    assert controller.isDialogPinned({"pinned": True}) is True
    assert controller.isDialogPinned({"id": 1}) is False
    assert controller.isPeerStoriesBlocked() is False

    _native.reset()
    controller.getPinnedDialogs(1)
    assert requests()[-1]["name"] == "messages.getPinnedDialogs"
    assert requests()[-1]["payload"]["folder_id"] == 1


def test_controller_settings():
    """Notifications/Download/Location controllers keep real state."""
    from org.telegram.messenger import (
        DownloadController,
        LocationController,
        NotificationsController,
    )

    notifications = NotificationsController.getInstance(0)
    notifications.setNotificationsSettings({"enabled": False, "sound": "default"})
    settings = notifications.getNotificationsSettings()
    assert settings["enabled"] is False
    assert settings["sound"] == "default"
    assert notifications.isGlobalNotificationsEnabled() is False
    assert notifications.getCurrentNotificationSettings()["enabled"] is False
    notifications.setDialogNotificationsSettings({"id": 77}, {"muted": True})
    assert notifications.getDialogNotificationsSettings({"id": 77}) == {
        "muted": True
    }

    downloads = DownloadController.getInstance(0)
    downloads.setAutoDownloadSettings({"photos": True, "videos": False})
    assert downloads.getAutoDownloadSettings() == {
        "photos": True,
        "videos": False,
    }
    downloads.setAutoDownloadEnabled(False)
    assert downloads.isAutoDownloadEnabled() is False
    downloads.setCurrentDownloadMask(3)
    assert downloads.getCurrentDownloadMask() == 3
    assert downloads.isStreamingMediaEnabled() is True
    assert downloads.isDownloadingMedia() is False
    assert downloads.canDownloadMedia(1, 100) is False  # auto-download disabled above
    assert downloads.isDownloading() is False
    assert downloads.loadDownloadingFiles() == []
    assert downloads.generateObserverTag() != downloads.generateObserverTag()
    assert downloads.getMaxVideoBitrate() == 0
    assert downloads.getAutodownloadMask() == 3

    notifications.muteDialog({"id": 88}, True)
    assert notifications.getDialogNotificationsSettings({"id": 88})[
        "mute_until"
    ] > 0
    notifications.muteUntil({"id": 88}, 0)
    assert notifications.getDialogNotificationsSettings({"id": 88})[
        "mute_until"
    ] == 0
    notifications.setOpenedDialogId({"id": 88})
    assert notifications.getOpenedDialogId() == 88
    assert notifications.getTotalUnreadCount() >= 0

    location = LocationController.getInstance(0)
    peer = {"id": 77, "kind": "user"}
    assert location.isSharingLocation() is False
    point = location.startSharingLocation(peer, 55.75, 37.61)
    assert point["lat"] == 55.75
    assert location.isSharingLocation(peer) is True
    assert location.getSharingLocations() == [point]
    assert location.getUserLocation(peer) == point
    assert location.isLocationVisible(peer) is True
    assert location.getSharingLocationInfo(peer) == point
    assert location.getLocationsCount() == 1
    assert LocationController.countryCodeToEmoji("ru") == "\U0001F1F7\U0001F1FA"
    location.stopSharingLocation(peer)
    assert location.isSharingLocation(peer) is False


def test_messages_controller_pins_and_blocks():
    """Pin/unpin and block/unblock map to their raw requests."""
    from org.telegram.messenger import MessagesController, SendMessagesHelper

    controller = MessagesController.getInstance(0)

    def requests():
        return [
            data for method, data in _native.calls()
            if method == "client.request"
        ]

    _native.reset()
    controller.pinMessage({"id": 5, "peer": 10})
    assert requests()[-1]["name"] == "messages.updatePinnedMessage"
    assert requests()[-1]["payload"] == {
        "peer": 10,
        "id": 5,
        "silent": False,
        "unpin": False,
    }

    _native.reset()
    controller.unpinMessage({"id": 5, "peer": 10})
    assert requests()[-1]["name"] == "messages.updatePinnedMessage"
    assert requests()[-1]["payload"]["unpin"] is True

    _native.reset()
    controller.blockUser({"id": 11})
    assert requests()[-1]["name"] == "contacts.block"
    assert requests()[-1]["payload"] == {"id": 11}

    _native.reset()
    controller.unblockUser({"id": 11})
    assert requests()[-1]["name"] == "contacts.unblock"
    assert requests()[-1]["payload"] == {"id": 11}

    helper = SendMessagesHelper.getInstance(0)
    _native.reset()
    helper.sendLocation(7, 1.0, 2.0)
    assert requests()[-1]["name"] == "messages.sendMedia"
    assert requests()[-1]["payload"]["media"]["_"] == "inputMediaGeoPoint"
    assert requests()[-1]["payload"]["media"]["geo_point"]["lat"] == 1.0

    _native.reset()
    helper.sendContact(7, "+1", "A", "B")
    assert requests()[-1]["name"] == "messages.sendMedia"
    assert requests()[-1]["payload"]["media"]["_"] == "inputMediaContact"
    assert requests()[-1]["payload"]["media"]["phone_number"] == "+1"


def test_message_media_kinds():
    """`MessageObject` and hook payloads classify media from attributes."""
    import _extera_runtime
    from org.telegram.messenger import MessageObject

    def audio(voice=True, duration=12):
        return {
            "id": 1,
            "media": {
                "_": "messageMediaDocument",
                "document": {
                    "_": "document",
                    "file_name": "voice.ogg",
                    "size": 123,
                    "attributes": [
                        {
                            "_": "documentAttributeAudio",
                            "voice": voice,
                            "duration": duration,
                        }
                    ],
                },
            },
        }

    message = MessageObject(audio())
    assert message.isVoice() is True
    assert message.isMusic() is False
    assert message.isDocument() is True
    assert message.getMediaDuration() == 12
    assert message.getFileName() == "voice.ogg"
    assert message.getFileSize() == 123
    assert message.getMediaSize() == 123
    assert message.getDocumentSize() == 123
    assert message.hasDocument() is True

    music = MessageObject(audio(voice=False, duration=200))
    assert music.isMusic() is True
    assert music.isVoice() is False

    video = MessageObject({
        "media": {
            "_": "messageMediaDocument",
            "document": {
                "attributes": [
                    {"_": "documentAttributeVideo", "round_message": True, "duration": 5}
                ]
            },
        }
    })
    assert video.isRoundVideo() is True
    assert video.isVideo() is False

    gif = MessageObject({
        "media": {
            "_": "messageMediaDocument",
            "document": {"attributes": [{"_": "documentAttributeAnimated"}]},
        }
    })
    assert gif.isGif() is True

    sticker = MessageObject({
        "media": {
            "_": "messageMediaDocument",
            "document": {"attributes": [{"_": "documentAttributeSticker"}]},
        }
    })
    assert sticker.isSticker() is True

    photo = MessageObject({
        "media": {"_": "messageMediaPhoto", "photo": {"_": "photo", "id": 1}}
    })
    assert photo.isPhoto() is True
    assert photo.hasPhoto() is True
    assert photo.isDocument() is False

    payload = _extera_runtime.AttrDict(audio())
    assert payload.isVoice() is True
    assert payload.getMediaDuration() == 12
    assert payload.getFileName() == "voice.ogg"
    assert payload.getMessageOwner() is payload

    assert message.canForwardMessage() is True
    assert message.canEditMessage() is True
    hidden = MessageObject({"edit_hide": True, "noforwards": True})
    assert hidden.canEditMessage() is False
    assert hidden.canForwardMessage() is False
    assert MessageObject({"scheduled": True}).isScheduled() is True
    assert MessageObject({"sponsored": True}).isSponsored() is True
    assert MessageObject({"secret": True}).isSecret() is True

    hidden_payload = _extera_runtime.AttrDict({"noforwards": True})
    assert hidden_payload.canForwardMessage() is False
    assert hidden_payload.canEditMessage() is True

    constructed = MessageObject(0, audio())
    assert constructed.isVoice() is True
    copied = MessageObject(message)
    assert copied.getId() == 1


def test_contacts_and_storage():
    """Contact add/delete and the message cache keep Android's shape."""
    from org.telegram.messenger import ContactsController, MessagesStorage

    contacts = ContactsController.getInstance(0)

    def requests():
        return [
            data for method, data in _native.calls()
            if method == "client.request"
        ]

    _native.reset()
    contacts.addContact({"id": 15}, "Ann", "Lee", "+100")
    assert requests()[-1]["name"] == "contacts.addContact"
    assert requests()[-1]["payload"]["id"] == 15
    assert requests()[-1]["payload"]["first_name"] == "Ann"
    assert requests()[-1]["payload"]["phone"] == "+100"

    _native.reset()
    contacts.deleteContact({"id": 15})
    assert requests()[-1]["name"] == "contacts.deleteContacts"
    assert requests()[-1]["payload"]["id"] == [15]

    _native.reset()
    contacts.addContact("A", "B", "+200")
    assert requests()[-1]["name"] == "contacts.importContacts"
    contact = requests()[-1]["payload"]["contacts"][0]
    assert contact["first_name"] == "A"
    assert contact["last_name"] == "B"
    assert contact["phone"] == "+200"

    storage = MessagesStorage.getInstance(0)
    storage.putMessages([
        {"id": 1, "peer": 50, "message": "one"},
        {"id": 2, "peer": 50, "message": "two"},
    ])
    assert storage.getMessagesCount(50) == 2
    assert storage.getMessage(50, 1)["message"] == "one"
    assert set(storage.getMessages(50).keys()) == {1, 2}
    assert storage.getMessages(50, [1])[1]["message"] == "one"
    assert storage.getUnreadMessagesCount() == 0

    _native.reset()
    storage.getDialogs(2)
    requests = [
        data for method, data in _native.calls()
        if method == "client.request"
    ]
    assert requests and requests[-1]["payload"]["folder_id"] == 2

    assert storage.getMainUnreadCount() == 0
    assert storage.getArchiveUnreadCount() == 0
    assert storage.getDatabaseSize() == 0
    assert storage.getDatabaseFiles() == []
    assert storage.getDatabase() is None
    assert storage.getStorageQueue() is not None
    assert storage.getWallpapers() == []
    storage.readAllDialogs()
    storage.loadUnreadMessages()

    _native.reset()
    storage.deleteUserChatHistory({"id": 50})
    requests = [
        data for method, data in _native.calls()
        if method == "client.request"
    ]
    assert requests[-1]["name"] == "messages.deleteHistory"
    assert requests[-1]["payload"]["peer"] == 50

    storage.setLastPtsValue(123)
    assert storage.getLastPtsValue() == 123
    storage.setLastDateValue(456)
    assert storage.getLastDateValue() == 456
    storage.setLastQtsValue(7)
    assert storage.getLastQtsValue() == 7
    storage.setLastSeqValue(8)
    assert storage.getLastSeqValue() == 8
    storage.setLastSecretVersion(9)
    assert storage.getLastSecretVersion() == 9
    storage.setSecretPBytes(b"\x01\x02")
    assert storage.getSecretPBytes() == b"\x01\x02"
    storage.setSecretG(3)
    assert storage.getSecretG() == 3

    assert storage.getWidgetState() is None
    storage.putWidgetStorage()
    storage.saveTopics()
    storage.removeAllTopics()
    storage.setDialogTtl()
    storage.saveDialogFiltersOrder()
    assert storage.getSavedDialogMaxMessageId() == 0


def test_media_data_controller():
    """Sticker loading and faving reach the raw sticker requests."""
    from org.telegram.messenger import MediaDataController

    controller = MediaDataController.getInstance(0)

    def requests():
        return [
            data for method, data in _native.calls()
            if method == "client.request"
        ]

    _native.reset()
    assert controller.loadStickers() == []
    assert requests()[-1]["name"] == "messages.getAllStickers"

    _native.reset()
    assert controller.loadFeaturedStickers() == []
    assert requests()[-1]["name"] == "messages.getFeaturedStickers"

    _native.reset()
    assert controller.loadRecentStickers() == []
    assert requests()[-1]["name"] == "messages.getRecentStickers"

    _native.reset()
    assert controller.getArchivedStickersCount() == 0
    assert requests()[-1]["name"] == "messages.getArchivedStickers"

    _native.reset()
    controller.getStickerSetByName("cats")
    assert requests()[-1]["name"] == "messages.getStickerSet"
    assert requests()[-1]["payload"]["short_name"] == "cats"

    _native.reset()
    controller.getStickerSetById(5, 9)
    assert requests()[-1]["payload"] == {"id": 5, "access_hash": 9}

    _native.reset()
    controller.addRecentSticker({"document": {"id": 7, "access_hash": 8}})
    assert requests()[-1]["name"] == "messages.saveRecentSticker"
    assert requests()[-1]["payload"] == {
        "id": 7,
        "access_hash": 8,
        "unsave": False,
    }

    _native.reset()
    controller.removeRecentSticker({"id": 7, "access_hash": 8})
    assert requests()[-1]["payload"]["unsave"] is True

    _native.reset()
    controller.toggleStickerSet({"short_name": "cats"}, True)
    assert requests()[-1]["name"] == "messages.installStickerSet"
    assert requests()[-1]["payload"]["archived"] is False

    _native.reset()
    controller.toggleStickerSet({"short_name": "cats"}, False)
    assert requests()[-1]["name"] == "messages.uninstallStickerSet"

    _native.reset()
    assert controller.loadEmojiKeywords("en", 0) == []
    assert requests()[-1]["name"] == "messages.getEmojiKeywordsDifference"
    assert requests()[-1]["payload"] == {
        "lang_code": "en",
        "from_version": 0,
    }
    assert controller.getEmojiKeywords() == []

    assert controller.areStickersLoaded() is False
    assert controller.isLoadingStickers() is False
    assert controller.getRecentStickersNoCopy() == []
    assert controller.getRecentGifs() == []
    assert controller.hasRecentGif() is False
    assert controller.canAddStickerToFavorites() is False
    assert controller.getReactionsList() == []
    assert controller.getStickerByIds() == {}
    assert controller.getFeaturedStickerSets() == []
    assert controller.getUnreadStickerSets() == []
    assert controller.getInputStickerSet({"short_name": "cats"}) == {
        "short_name": "cats"
    }
    assert controller.getInputStickerSetItem({"id": 7, "access_hash": 8})["id"] == 7


def test_user_object_fields():
    """`UserObject` reads the same user flags as Android."""
    from org.telegram.messenger import UserObject

    user = {
        "id": 9,
        "first_name": "Ann",
        "last_name": "Lee",
        "username": "ann",
        "mutual_contact": True,
        "scam": True,
    }
    assert UserObject.getFullName(user) == "Ann Lee"
    assert UserObject.isMutualContact(user) is True
    assert UserObject.isScam(user) is True
    assert UserObject.isFake(user) is False
    assert UserObject.isRisky(user) is True
    assert UserObject.isSelf(user) is False
    assert UserObject.getPublicUsername(user) == "ann"


def test_media_metadata_retriever():
    """`MediaMetadataRetriever` reads WAV/FLAC/OGG/MP4/MP3/image metadata."""
    import struct

    from org.telegram.messenger import MediaMetadataRetriever

    work = tempfile.mkdtemp(prefix="media-meta-")
    try:
        retriever = MediaMetadataRetriever()

        wav = os.path.join(work, "tone.wav")
        payload = b"\x00" * 8000
        fmt = struct.pack("<HHIIHH", 1, 1, 8000, 8000, 1, 8)
        body = (
            b"WAVE"
            + b"fmt "
            + struct.pack("<I", len(fmt))
            + fmt
            + b"data"
            + struct.pack("<I", len(payload))
            + payload
        )
        with open(wav, "wb") as handle:
            handle.write(b"RIFF" + struct.pack("<I", len(body)) + body)
        retriever.setDataSource(wav)
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
            == "1000"
        )
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_MIMETYPE)
            == "audio/x-wav"
        )

        flac = os.path.join(work, "tone.flac")
        packed = (44100 << 44) | 44100
        streaminfo = bytes(10) + packed.to_bytes(8, "big") + bytes(16)
        with open(flac, "wb") as handle:
            handle.write(
                b"fLaC" + bytes([0]) + len(streaminfo).to_bytes(3, "big") + streaminfo
            )
        retriever.setDataSource(flac)
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
            == "1000"
        )

        ogg = os.path.join(work, "tone.opus")
        packet = b"OpusHead" + bytes(4) + struct.pack("<I", 48000) + bytes(4)
        page = (
            b"OggS"
            + bytes(2)
            + (48000).to_bytes(8, "little")
            + bytes(12)
            + bytes([1, len(packet)])
            + packet
        )
        with open(ogg, "wb") as handle:
            handle.write(page)
        retriever.setDataSource(ogg)
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
            == "1000"
        )

        def box(kind, payload):
            return struct.pack(">I", len(payload) + 8) + kind + payload

        matrix = struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
        mvhd = bytes(12) + struct.pack(">II", 1000, 2000) + bytes(80)
        tkhd = bytes(40) + matrix + struct.pack(">II", 640 << 16, 480 << 16)
        hdlr = bytes(8) + b"vide" + bytes(12)
        trak = box(b"trak", box(b"tkhd", tkhd) + box(b"mdia", box(b"hdlr", hdlr)))
        moov = box(b"moov", box(b"mvhd", mvhd) + trak)
        mp4 = os.path.join(work, "clip.mp4")
        with open(mp4, "wb") as handle:
            handle.write(box(b"ftyp", b"isom" + bytes(4)) + moov)
        retriever.setDataSource(mp4)
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
            == "2000"
        )
        _native.reset()
        assert retriever.getFrameAtTime(500000) is None
        frames = [
            data for method, data in _native.calls() if method == "media.frame"
        ]
        assert frames and frames[-1]["time"] == 0.5
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
            == "640"
        )
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
            == "480"
        )
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_VIDEO)
            == "yes"
        )

        mp3 = os.path.join(work, "song.mp3")
        title = b"\x03Song"
        frame = b"TIT2" + struct.pack(">I", len(title)) + b"\x00\x00" + title
        size = len(frame)
        syncsafe = bytes([
            (size >> 21) & 0x7F,
            (size >> 14) & 0x7F,
            (size >> 7) & 0x7F,
            size & 0x7F,
        ])
        with open(mp3, "wb") as handle:
            handle.write(
                b"ID3\x03\x00\x00"
                + syncsafe
                + frame
                + b"\xff\xfb\x90\x00"
                + b"\x00" * 1000
            )
        retriever.setDataSource(mp3)
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE)
            == "Song"
        )
        assert int(
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
        ) > 0

        png = os.path.join(work, "image.png")
        with open(png, "wb") as handle:
            handle.write(
                b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", 5, 7) + bytes(8)
            )
        retriever.setDataSource(png)
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
            == "5"
        )
        assert (
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
            == "7"
        )
        assert retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_VIDEO) == "no"

        retriever.release()
        assert retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION) is None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_utilities_helpers():
    """`Utilities` exposes the helpers plugins use on Android."""
    from org.telegram.messenger import AndroidUtilities, Utilities

    assert Utilities.parseBoolean("true") is True
    assert Utilities.parseBoolean("no") is False
    assert Utilities.isValidPhone("+1 (555) 123-4567") is True
    assert Utilities.isValidPhone("12") is False
    assert Utilities.join("-", ["a", "b"]) == "a-b"
    assert isinstance(Utilities.random.nextInt(5), int)
    assert isinstance(Utilities.random.nextFloat(), float)
    assert Utilities.currentTimeMillis() > 0
    assert Utilities.getDurationString(65) == AndroidUtilities.getDurationString(65)
    assert Utilities.getMD5("abc")
    assert Utilities.getFileSize(__file__) > 0


def test_chat_object_rights():
    """`ChatObject` send/manage helpers follow banned rights like Android."""
    from org.telegram.messenger import ChatObject

    channel = {
        "_": "channel",
        "id": -1000000000000 - 200,
        "broadcast": True,
        "creator": False,
        "admin_rights": {"post_messages": True},
        "banned_rights": {"send_messages": True, "send_photos": True},
    }
    assert ChatObject.canSendMessages(channel) is False
    assert ChatObject.canSendPhoto(channel) is False
    assert ChatObject.canSendVideo(channel) is True
    assert ChatObject.canSendAnyMedia(channel) is True
    assert ChatObject.isActionBanned(channel, "send_photos") is True
    assert ChatObject.isActionBannedByDefault(channel, "send_messages") is False

    group = {
        "_": "chat",
        "id": 77,
        "megagroup": True,
        "creator": True,
    }
    assert ChatObject.isInChat(group) is True
    assert ChatObject.isCreator(group) is True
    assert ChatObject.hasAdminRights(group) is True
    assert ChatObject.canSendMessages(group) is True
    assert ChatObject.canPinMessages(group) is True

    restricted = {
        "_": "chat",
        "id": 88,
        "megagroup": True,
        "left": True,
    }
    assert ChatObject.isNotInChat(restricted) is True
    assert ChatObject.canWriteToChat(restricted) is False

    forum = {
        "_": "channel",
        "forum": True,
        "megagroup": True,
        "admin_rights": {"manage_topics": True},
    }
    assert ChatObject.isForum(forum) is True
    assert ChatObject.canManageTopics(forum) is True
    assert ChatObject.canCreateTopic(forum) is True

    assert ChatObject.isChannelOrGiga({"megagroup": True}) is True
    assert ChatObject.hasPublicLink({"username": "chan"}, "chan") is True
    assert ChatObject.hasPublicLink({"username": "chan"}, "other") is False
    assert ChatObject.reactionIsAvailable({"available_reactions": ["👍"]}, "👍") is True
    assert ChatObject.reactionIsAvailable({"available_reactions": ["👍"]}, "❤") is False
    assert (
        ChatObject.getBannedRightsString(
            {"send_messages": True, "pin_messages": False}
        )
        == "send_messages"
    )


def test_topics_controller_facade():
    """`getTopicsController` returns a controller instead of None."""
    from org.telegram.messenger import MessagesController

    controller = MessagesController.getInstance(0)
    topics = controller.getTopicsController()
    assert topics is not None
    assert topics is controller.getTopicsController()
    assert topics.getTopics() == []
    assert topics.getTopicsCount() == 0
    assert topics.getForumUnreadCount(1) == [0, 0]
    assert topics.isLoading() is False
    assert topics.endIsReached() is True
    assert controller.getSponsoredMessages(1) == {
        "messages": [],
        "chats": [],
        "users": [],
    }
    assert controller.getChannelRecommendations(1) == []


def test_build_and_shared_config():
    """`BuildVars`/`SharedConfig` expose Android's flags with safe defaults."""
    from org.telegram.messenger import BuildVars, SharedConfig

    assert BuildVars.BUILD_VERSION_STRING
    assert BuildVars.getExteraAppId() == 0
    assert BuildVars.getExteraAppHash() == ""
    assert BuildVars.SUPPORTS_PASSKEYS is True
    assert BuildVars.GITHUB_APP_URL.startswith("https://")

    assert SharedConfig.versionBiggerOrEqual("13.2.1", "13.2") is True
    assert SharedConfig.versionBiggerOrEqual("13.1", "13.2") is False
    assert SharedConfig.loopStickers() is False
    assert SharedConfig.allowPreparingHevcPlayers() is False
    assert SharedConfig.findGoodHevcEncoder() is None
    assert SharedConfig.appLocked is False
    assert SharedConfig.autoLockIn > 0
    assert SharedConfig.updateStickersOrderOnSend is True
    assert SharedConfig.photoViewerBlur is True
    assert SharedConfig.togglePhotoViewerBlur() is None


def test_locale_helpers():
    """`LocaleController` formats numbers/dates/durations like Android."""
    from org.telegram.messenger import AndroidUtilities, LocaleController

    assert LocaleController.formatNumber(12345)
    assert LocaleController.formatShortDuration(65) == "1:05"
    assert LocaleController.formatShortDuration(3665) == "1:01:05"
    assert LocaleController.fixNumbers("١٢٣") == "123"
    assert LocaleController.isRTLCharacter("ع") is True
    assert LocaleController.isRTLCharacter("A") is False
    assert LocaleController.addNbsp("a b") == "a\u00a0b"
    assert LocaleController.getLocaleStringIso639()
    assert LocaleController.formatDateChat(0) == "01.01.1970"
    assert AndroidUtilities.removeDiacritics("café") == "cafe"
    assert AndroidUtilities.removeRTL("a\u0590b") == "ab"
    assert AndroidUtilities.getOffset(2, 3) == 5
    assert LocaleController.formatPluralStringComma("x", 3)
    assert LocaleController.getLangCode()
    assert LocaleController.getBaseLangCode()
    assert LocaleController.getCurrentLocale()
    assert LocaleController.getTimeZoneName()
    assert LocaleController.quantityForNumber("x", 1) == 0
    assert LocaleController.quantityForNumber("x", 5) == 3
    assert LocaleController.getTranslitString("café") == "cafe"
    assert LocaleController.getCountryName("US") == "United States"
    assert "United States" in LocaleController.getCountryWithFlag("US")
    assert LocaleController.formatDistance(1500).endswith("km")
    assert LocaleController.formatDateAudio(0)
    assert LocaleController.formatPmSeenDate(0)
    assert LocaleController.formatPollEndTime(0)

    assert AndroidUtilities.dp2(2) == 4.0
    assert AndroidUtilities.formatCount(1500) == "1.5K"
    assert AndroidUtilities.formatWholeNumber(1234) == "1 234"
    assert AndroidUtilities.formatLongDuration(3665) == "1:01:05"
    assert AndroidUtilities.formatShortDuration(65) == "1:05"
    assert AndroidUtilities.formatVideoDuration(65) == "1:05"
    assert AndroidUtilities.formatFullDuration(65) == "1:05"
    assert AndroidUtilities.formatDurationNoHours(65) == "1:05"
    assert AndroidUtilities.ellipsize("abcdef", 4) == "a..."
    assert AndroidUtilities.ellipsize("abc", 10) == "abc"
    assert AndroidUtilities.ellipsizeCenterEnd("abcdefgh", 7) == "ab...gh"
    assert AndroidUtilities.generateFileName("txt").endswith(".txt")
    assert AndroidUtilities.generatePicturePath().endswith(".jpg")
    assert AndroidUtilities.generateVideoPath().endswith(".mp4")
    assert AndroidUtilities.getCacheDir() is not None
    assert AndroidUtilities.distance(0, 0, 3, 4) == 5
    assert AndroidUtilities.compare(1, 2) == -1
    assert 0.0 <= AndroidUtilities.computePerceivedBrightness(0xFFFFFF) <= 1.0

    work = tempfile.mkdtemp(prefix="extera-androidutils-")
    source = os.path.join(work, "a.txt")
    destination = os.path.join(work, "b.txt")
    assert AndroidUtilities.createEmptyFile(source) is True
    with open(source, "wb") as handle:
        handle.write(b"data")
    assert AndroidUtilities.copyFile(source, destination) is True
    with open(destination, "rb") as handle:
        assert handle.read() == b"data"
    shutil.rmtree(work, ignore_errors=True)


def test_user_config_facade():
    """`UserConfig` exposes the account/config surface plugins read."""
    from org.telegram.messenger import UserConfig

    config = UserConfig.getInstance(0)
    assert config.isConfigLoaded() is True
    first = config.getNewMessageId()
    second = config.getNewMessageId()
    assert second == first + 1
    assert config.getPreferences() is not None
    assert config.getSaveGalleryExceptions() == {}

    config.setPinnedDialogsLoaded(0, True)
    assert config.isPinnedDialogsLoaded(0) is True
    config.clearPinnedDialogsLoaded()
    assert config.isPinnedDialogsLoaded(0) is False
    assert config.getTotalDialogsCount(0) >= 0
    assert config.getClientPhone() == ""

    config.savePassword(b"\x01", b"\x02")
    assert config.savedPasswordHash == b"\x01"
    assert config.savedPasswordTime > 0
    config.resetSavedPassword()
    assert config.savedPasswordHash is None

    assert UserConfig.getMaxAccountCount() > 0
    assert UserConfig.isValidAccount(0) is True
    assert UserConfig.isValidAccount(99) is False
    assert UserConfig.getActivatedAccountsCount() >= 1


def test_android_facade_surface():
    """The Java controller facades answer Android's public methods."""
    from org.telegram.messenger import (
        ApplicationLoader,
        BuildVars,
        ContactsController,
        FileLoader,
        LocaleController,
        MediaController,
        MessagesController,
        MessagesStorage,
        SecretChatHelper,
        SendMessagesHelper,
        SharedConfig,
    )
    from org.telegram.ui.ActionBar import Theme

    def requests():
        return [
            data for method, data in _native.calls()
            if method == "client.request"
        ]

    _native.reset()
    controller = MessagesController.getInstance(0)
    controller.blockPeer({"id": 9})
    assert requests()[-1]["name"] == "contacts.block"
    assert requests()[-1]["payload"]["id"] == 9

    _native.reset()
    controller.addUserToChat(5, {"id": 9})
    assert requests()[-1]["name"] == "messages.addChatUser"
    assert requests()[-1]["payload"]["user_id"] == 9

    _native.reset()
    controller.createChat("title", [{"id": 9}, 10])
    assert requests()[-1]["name"] == "messages.createChat"
    assert requests()[-1]["payload"]["users"] == [9, 10]

    _native.reset()
    controller.convertToMegaGroup(5)
    assert requests()[-1]["name"] == "messages.migrateChat"
    controller.changeChatTitle(5, "new")
    assert requests()[-1]["name"] == "messages.editChatTitle"

    _native.reset()
    controller.deleteUserPhoto({"id": 12})
    assert requests()[-1]["name"] == "photos.deletePhotos"
    assert requests()[-1]["payload"]["id"] == [12]

    assert controller.getDialogFolderId({"id": 4}) == 0
    assert controller.isDialogUnread({"unread_count": 2}) is True
    assert controller.isDialogUnread({"unread_count": 0}) is False
    controller.markMessageAsRead({"id": 4}, 10)

    helper = SendMessagesHelper.getInstance(0)
    assert helper.isSendingMessage(1) is False
    assert helper.getSendingMessageId() is None
    assert helper.canSendMessageToChat({"id": 4}) is True
    first = helper.getNextRandomId()
    assert helper.getNextRandomId() == first + 1
    assert helper.prepareSendingDocuments([], 4) == []
    assert helper.prepareSendingAudioDocuments([], 4) == []

    _native.reset()
    helper.prepareSendingText("hello", 4)
    assert any(
        method == "client.send" for method, _ in _native.calls()
    ), _native.calls()

    assert FileLoader.getDocumentFileName(
        {"file_name": "clip.mp4"}
    ) == "clip.mp4"
    assert FileLoader.getDocumentExtension(
        {"file_name": "clip.mp4"}
    ) == "mp4"
    assert FileLoader.getDocumentExtension(
        {"attributes": [{"file_name": "song.flac"}]}
    ) == "flac"
    assert FileLoader.getExtensionByMimeType("video/mp4") == "mp4"
    assert FileLoader.getMimeTypePart("audio/ogg") == "audio"
    assert FileLoader.isVideoMimeType("video/quicktime") is True
    assert FileLoader.isVideoMimeType("image/png") is False
    assert FileLoader.fixFileName("/tmp/a b.txt") == "a b.txt"
    assert FileLoader.getPhotoId({"_": "photo", "id": 3}) == 3
    assert FileLoader.isSamePhoto({"_": "photo", "id": 3},
                                  {"photo": {"id": 3}}) is True
    assert FileLoader.getLocalFile("/tmp/x").getPath() == "/tmp/x"
    assert FileLoader.getClosestPhotoSizeWithSize(
        [{"w": 10, "h": 10}, {"w": 100, "h": 100}], 90
    ) == {"w": 100, "h": 100}

    storage = MessagesStorage.getInstance(0)
    storage.putMessages([{"id": 7, "peer": 4, "media": {"_": "messageMediaPhoto"}}])
    assert storage.checkMessageId(4, 7) is True
    assert storage.getDialogMaxMessageId(4) == 7
    assert storage.getDialogReadMax(False, 4) == 0
    assert storage.getUnsentMessages() == []
    assert storage.getSmallGroupsParticipantsCount(4) >= 0
    assert storage.getMessageMediaType({"media": {"_": "messageMediaPhoto"}}) == 1

    contacts = ContactsController.getInstance(0)
    assert contacts.hasContactsPermission() is True
    assert isinstance(contacts.getContactsCopy(), dict)
    assert contacts.getContactsCount() >= 0

    assert SecretChatHelper.getInstance(0).sendNoopMessage({"id": 1}) is None
    assert SecretChatHelper.getInstance(0).isSecretVisibleMessage(
        {"action": None}
    ) is True

    assert SharedConfig.deviceIsAverage() is True
    assert SharedConfig.getDevicePerformanceClass() == 2
    assert SharedConfig.isAutoplayGifs() is True
    assert SharedConfig.chatBlurEnabled() is True
    assert SharedConfig.getLastLocalId() > 0
    SharedConfig.setAnimationsEnabled(False)
    assert SharedConfig.animationsEnabled is False
    SharedConfig.setAnimationsEnabled(True)

    assert BuildVars.getSmsHash() == ""
    assert BuildVars.isBetaApp() is False
    assert BuildVars.useInvoiceBilling() is False

    assert ApplicationLoader.isNetworkOnline() is True
    assert ApplicationLoader.isRoaming() is False
    assert ApplicationLoader.getCurrentNetworkType() == 1

    media = MediaController.getInstance(0)
    assert media.isMessagePaused() is False
    assert media.isPaused() is False
    assert media.getMusicList() == []
    assert media.getPlayingMessageObjectNum() == -1
    assert media.getCurrentPlaybackPosition() >= 0

    # Unmapped members answer the Java default instead of raising.
    assert helper.getUnmappedHelperValue() is None
    assert helper.isUnmappedHelperFlag() is False
    assert helper.doUnmappedThing() is None
    assert media.isUnmappedMediaFlag() is False
    assert media.getUnmappedMediaValue() is None
    assert MessagesStorage.getInstance(0).getUnmappedStorageValue() is None
    assert FileLoader.getUnmappedLoaderValue() is None
    assert FileLoader.isUnmappedLoaderFlag() is False
    assert SharedConfig.isUnmappedConfigFlag() is False
    assert LocaleController.getUnmappedLocaleValue() is None
    assert Theme.applyUnmappedTheme() is None


def test_android_facade_extras():
    """Theme, Utilities, ImageLoader, notifications and object helpers."""
    import hashlib

    from org.telegram.messenger import (
        ChatObject,
        DialogObject,
        ImageLoader,
        MediaDataController,
        MessagesController,
        NotificationsSettings,
        UserConfig,
        UserObject,
        Utilities,
    )
    from org.telegram.ui.ActionBar import Theme

    key = "test_parity_custom_color"
    Theme.setColor(key, 0xFF112233)
    assert Theme.getColor(key) == 0xFF112233
    assert Theme.getColor("windowBackgroundWhite") != 0
    assert Theme.isCurrentThemeDark() is False
    round_rect = Theme.createRoundRectDrawable(8, 0xFF00FF00)
    assert round_rect.cornerRadius == 8.0
    assert round_rect.color == 0xFF00FF00
    selector = Theme.createSelectorDrawable(0xFF123456)
    assert selector.color == 0xFF123456
    circle = Theme.createCircleDrawable(40, 0xFF000000)
    assert circle.size == 40
    assert Theme.createSelectorDrawableFromDrawables(None, circle) is circle
    assert Theme.createEditTextDrawable() is not None
    assert Theme.applyDefaultShadow(None) is None

    assert Utilities.MD5("x") == hashlib.md5(b"x").digest()
    assert Utilities.SHA256("x") == hashlib.sha256(b"x").hexdigest()
    assert Utilities.bytesToHex(b"\x01\xab") == "01ab"
    assert Utilities.hexToBytes("01ab") == b"\x01\xab"
    assert Utilities.bytesToInt(Utilities.intToBytes(1234)) == 1234
    assert Utilities.bytesToLong(b"\x01" + b"\x00" * 7) == 1
    assert Utilities.getExtension("a/b/c.mp4") == "mp4"
    assert Utilities.isNullOrEmpty([]) is True
    assert Utilities.parseIntToString("12") == "12"
    assert Utilities.clamp01(1.5) == 1.0
    assert Utilities.divCeil(7, 2) == 4
    assert Utilities.dist(0, 0, 3, 4) == 5
    assert len(Utilities.generateRandomString(6)) == 6
    assert len(Utilities.computeSHA1(b"x")) == 20
    assert len(Utilities.computeSHA256(b"x")) == 32
    assert len(Utilities.computeSHA512(b"x")) == 64
    assert Utilities.tryParseLong("9", 0) == 9
    assert Utilities.arraysEquals(b"abc", 1, b"bc", 0) is True
    values = [1, 2]
    Utilities.swapItems(values, 0, 1)
    assert values == [2, 1]
    work = tempfile.mkdtemp(prefix="extera-utils-")
    with open(os.path.join(work, "a.bin"), "wb") as handle:
        handle.write(b"12345")
    assert Utilities.getDirSize(work) == 5
    Utilities.clearDir(work)
    assert os.listdir(work) == []
    shutil.rmtree(work, ignore_errors=True)

    ImageLoader.clearMemory()
    ImageLoader.putImageToCache("bitmap", "key")
    assert ImageLoader.getFromMemCache("key") == "bitmap"
    assert ImageLoader.isInMemCache("key") is True
    ImageLoader.removeImage("key")
    assert ImageLoader.isInMemCache("key") is False
    assert ImageLoader.getHttpFileName("https://x/y.jpg") == (
        ImageLoader.getHttpFileName("https://x/y.jpg")
    )
    assert ImageLoader.getHttpUrlExtension("https://x/y.jpg?z=1") == "jpg"
    assert ImageLoader.getHttpFilePath("https://x/y.jpg", "jpg").endswith(".jpg")
    assert ImageLoader.getInstance() is ImageLoader

    notifications = NotificationsSettings.getInstance(0)
    notifications.clearPreference(555, 0)
    assert notifications.isDefault(555, 0) is True
    assert notifications.getProperty(
        NotificationsSettings.PROPERTY_NOTIFY_UNTIL, 555, 0, 0
    ) == 0
    notifications.applyDialogNotificationsSettings(
        555, 0, {"mute_until": 123, "silent": True, "preview": False}
    )
    assert notifications.isDefault(555, 0) is False
    assert notifications.getProperty(
        NotificationsSettings.PROPERTY_NOTIFY_UNTIL, 555, 0, 0
    ) == 123
    assert notifications.getProperty(
        NotificationsSettings.PROPERTY_SILENT, 555, 0, False
    ) is True
    assert notifications.getPropertyString(
        NotificationsSettings.PROPERTY_CUSTOM, 555, 0, "x"
    ) == "x"
    notifications.removeProperty(
        NotificationsSettings.PROPERTY_NOTIFY_UNTIL, 555, 0
    )
    notifications.clearPreference(555, 0)
    assert notifications.isDefault(555, 0) is True

    assert DialogObject.isEmpty({}) is True
    assert DialogObject.isEmpty({"id": 1, "title": "x"}) is False
    assert DialogObject.hasPhoto({"id": 1, "photo": {"id": 2}}) is True
    assert DialogObject.getPublicUsername({"username": "u"}) == "u"
    assert DialogObject.getEmojiStatusDocumentId(
        {"emoji_status": {"document_id": 7}}
    ) == 7
    assert DialogObject.getEmojiStatusUntil(
        {"emoji_status": {"until": 8}}
    ) == 8
    assert DialogObject.isEmojiStatusCollectible(
        {"emoji_status": {"collectible_id": 9}}
    ) is True
    assert DialogObject.getBotVerificationIcon(
        {"bot_verification": {"icon": 3}}
    ) == 3
    assert DialogObject.editDistance("kitten", "sitting") == 3
    assert DialogObject.similarity("abc", "abc") == 1.0
    assert DialogObject.emojiStatusesEqual(
        {"emoji_status": {"document_id": 1, "until": 2}},
        {"emoji_status": {"document_id": 1, "until": 2}},
    ) is True

    user = {"id": 1, "contact_requirement": 4, "profile_color": 2,
            "gifts_disabled": True}
    assert UserObject.getRequirementToContact(user) == 4
    assert UserObject.getPeerColorForAvatar(user) == 2
    assert UserObject.areGiftsDisabled(user) is True
    assert UserObject.eq({"id": 1}, {"id": 1}) is True
    assert UserObject.eq({"id": 1}, {"id": 2}) is False

    assert ChatObject.canPost({"id": 1}) is True
    assert ChatObject.equals({"id": 1}, {"id": 1}) is True
    assert ChatObject.getColorId({"color": 3}) == 3
    assert ChatObject.getProfileColorId({"profile_color": 4}) == 4
    assert ChatObject.getRestrictedErrorText({"restricted_text": "no"}) == "no"
    assert ChatObject.getParticipantVolume(
        {"participant_volumes": {"5": 30}}, 5
    ) == 30
    assert ChatObject.canUserDoAdminAction({"id": 1}, 0) is False

    media_data = MediaDataController.getInstance(0)
    media_data.clearAllDrafts()
    assert media_data.getDraft(42) is None
    media_data.saveDraft(42, "hello")
    assert media_data.getDraft(42) == "hello"
    media_data.clearDraft(42)
    assert media_data.getDraft(42) is None
    media_data.clearRecentReactions()
    media_data.addRecentReaction("👍")
    assert media_data.getRecentReactions() == ["👍"]
    media_data.setDoubleTapReaction("❤")
    assert media_data.getDoubleTapReaction() == "❤"
    assert media_data.isStickerPackInstalled(1) is False
    assert media_data.getStickerSetName({"short_name": "cats"}) == "cats"
    assert media_data.stringsEqual("a", "a") is True
    assert media_data.substring("abcdef", 1, 3) == "bc"
    assert media_data.getMask("3") == 3
    assert media_data.getMediaType(
        {"media": {"_": "messageMediaPhoto"}}
    ) == 1

    config = UserConfig.getInstance(0)
    config.setShowCallsTab(False)
    assert config.showCallsTab is False
    config.setShowCallsTab(True)
    config.setGlobalTtl(1234)
    assert config.getGlobalTTl() == 1234
    config.setDialogsLoadOffset(0, 1, 2, 3)
    assert config.getDialogLoadOffsets(0) == [1, 2, 3]
    assert config.getLoggedInAccountIds()
    assert config.getProductionAccount() == 0

    saved_music = MessagesController.SavedMusicList
    saved_music.clear()
    saved_music.add({"id": 1})
    assert saved_music.size() == 1
    assert saved_music.get(0)["id"] == 1
    assert saved_music.isEmpty() is False
    saved_music.clear()
    assert saved_music.isEmpty() is True


def test_send_poll_payload():
    """Polls go through `messages.sendMedia` with an `inputMediaPoll`."""
    from client_utils import send_message, send_poll
    from org.telegram.messenger import SendMessagesHelper

    def last_request():
        return [
            data for method, data in _native.calls()
            if method == "client.request"
        ][-1]

    _native.reset()
    send_poll(42, {
        "question": "Best?",
        "answers": [
            {"text": "A", "option": b"\x01"},
            {"text": "B", "option": b"\x02", "correct": True},
        ],
        "quiz": True,
        "public_voters": False,
        "multiple_choice": True,
        "close_period": 60,
        "countries_iso2": ["ru"],
    }, caption="caption")
    call = last_request()
    assert call["name"] == "messages.sendMedia"
    payload = call["payload"]
    assert payload["peer"] == 42
    assert payload["message"] == "caption"
    assert payload["media"]["_"] == "inputMediaPoll"
    poll = payload["media"]["poll"]
    assert poll["question"] == "Best?"
    assert poll["quiz"] is True
    assert poll["multiple_choice"] is True
    assert poll["close_period"] == 60
    assert poll["countries_iso2"] == ["ru"]
    assert poll["answers"][0]["option"] == "AQ=="
    assert poll["answers"][1]["correct"] is True

    _native.reset()
    send_message({
        "peer": 43,
        "poll": {
            "question": "Q",
            "answers": [{"text": "X"}, {"text": "Y"}],
            "correct_answers": [1],
        },
    })
    call = last_request()
    assert call["name"] == "messages.sendMedia"
    assert call["payload"]["media"]["poll"]["answers"][1]["correct"] is True

    _native.reset()
    helper = SendMessagesHelper.getInstance(0)
    helper.prepareSendingPoll({
        "poll": {"question": "H", "answers": [{"text": "A"}]},
        "caption": "cap",
    }, 44)
    call = last_request()
    assert call["name"] == "messages.sendMedia"
    assert call["payload"]["peer"] == 44
    assert call["payload"]["message"] == "cap"
    assert call["payload"]["media"]["poll"]["question"] == "H"

    poll_message = {
        "id": 9,
        "peer": 45,
        "media": {
            "_": "messageMediaPoll",
            "poll": {
                "question": "Q",
                "answers": [
                    {"text": "A", "option": b"\x01"},
                    {"text": "B", "option": b"\x02"},
                ],
            },
        },
    }
    _native.reset()
    helper.addPollOption(poll_message, "C")
    call = last_request()
    assert call["name"] == "messages.editMessage"
    assert call["payload"]["peer"] == 45
    assert call["payload"]["id"] == 9
    answers = call["payload"]["media"]["poll"]["answers"]
    assert len(answers) == 3
    assert answers[-1]["text"] == "C"

    _native.reset()
    helper.deletePollOption(poll_message, b"\x01")
    call = last_request()
    answers = call["payload"]["media"]["poll"]["answers"]
    assert len(answers) == 1
    assert answers[0]["text"] == "B"


def test_raw_tl_request_normalization():
    """TL objects built by real plugins serialize and normalize for the host."""
    from client_utils import send_request
    from org.telegram.messenger import MessagesController
    from org.telegram.tgnet import TLRPC

    controller = MessagesController.getInstance(0)
    user_peer = controller.getInputPeer(123)
    assert user_peer["_"] == "inputPeerUser"
    assert user_peer["user_id"] == 123
    channel_peer = controller.getInputPeer(-1001234567890)
    assert channel_peer["_"] == "inputPeerChannel"
    assert channel_peer["channel_id"] == 1234567890
    chat_peer = controller.getInputPeer(-55)
    assert chat_peer["_"] == "inputPeerChat"
    assert chat_peer["chat_id"] == 55

    media = TLRPC.TL_inputSingleMedia()
    media.media = TLRPC.TL_inputMediaPhoto()
    media.media.id = TLRPC.TL_inputPhoto()
    media.media.id.id = 10
    media.media.id.access_hash = 20
    payload = media.to_native()[1]
    assert payload["media"]["id"]["id"] == 10

    request = TLRPC.TL_messages_sendMedia()
    request.peer = controller.getInputPeer(123)
    request.media = TLRPC.TL_inputMediaPhoto()
    request.media.id = TLRPC.TL_inputPhoto()
    request.media.id.id = 10
    request.media.id.access_hash = 20
    request.message = "hi"
    _native.reset()
    send_request(request, lambda result, error: None)
    calls = [
        data for method, data in _native.calls()
        if method == "client.request"
    ]
    assert calls and calls[-1]["name"] == "messages.sendMedia"
    assert calls[-1]["payload"]["peer"] == 123
    assert calls[-1]["payload"]["media"]["id"] == 10
    assert calls[-1]["payload"]["media"]["access_hash"] == 20

    request = TLRPC.TL_messages_sendMessage()
    request.peer = controller.getInputPeer(-1001234567890)
    request.message = "hello"
    request.reply_to = TLRPC.TL_inputReplyToMessage()
    request.reply_to.reply_to_msg_id = 7
    _native.reset()
    send_request(request, lambda result, error: None)
    calls = [
        data for method, data in _native.calls()
        if method == "client.send"
    ]
    assert calls and calls[-1]["peer"] == -1001234567890
    assert calls[-1]["reply_to"] == 7

    album = TLRPC.TL_messages_sendMultiMedia()
    album.peer = controller.getInputPeer(123)
    item = TLRPC.TL_inputSingleMedia()
    item.media = TLRPC.TL_inputMediaPhoto()
    item.media.id = TLRPC.TL_inputPhoto()
    item.media.id.id = 11
    album.multi_media = [item]
    _native.reset()
    send_request(album, lambda result, error: None)
    calls = [
        data for method, data in _native.calls()
        if method == "client.request"
    ]
    assert calls and calls[-1]["name"] == "messages.sendMedia"
    assert calls[-1]["payload"]["peer"] == 123


def test_java_crypto_and_network_facades():
    """Crypto, HTTP, proxy and browser facades used by real plugins."""
    import hashlib

    from java_crypto import AES, Cipher, MessageDigest, IvParameterSpec, SecretKeySpec
    from org.telegram.messenger import (
        ChatObject,
        ConnectionsManager,
        MessagesController,
        SharedConfig,
        UserConfig,
    )
    from org.telegram.messenger.browser import Browser
    from com.exteragram.messenger.plugins import PluginsController
    from android.content import Intent
    from java.net import HttpURLConnection, URL

    assert AES(bytes.fromhex("000102030405060708090a0b0c0d0e0f")).encrypt_block(
        bytes.fromhex("00112233445566778899aabbccddeeff")
    ) == bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")

    cipher = Cipher.getInstance("AES/CTR/NoPadding")
    cipher.init(
        Cipher.ENCRYPT_MODE,
        SecretKeySpec(bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c"), "AES"),
        IvParameterSpec(bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")),
    )
    assert cipher.update(
        bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    ).hex() == "874d6191b620e3261bef6864990db6ce"

    assert MessageDigest.getInstance("SHA-256").digest(b"x") == hashlib.sha256(b"x").digest()

    assert HttpURLConnection.HTTP_OK == 200
    assert HttpURLConnection.HTTP_NOT_FOUND == 404
    url = URL("https://example.com/path/file.jpg?x=1")
    assert url.getHost() == "example.com"
    assert url.getPath() == "/path/file.jpg"
    assert url.getQuery() == "x=1"

    assert Intent.ACTION_GET_CONTENT.endswith("GET_CONTENT")
    assert Intent.CATEGORY_OPENABLE.endswith("OPENABLE")
    assert Intent.ACTION_VIEW.endswith("VIEW")

    assert UserConfig.MAX_ACCOUNT_COUNT == 4
    assert PluginsController.getInstance(0) is PluginsController.getInstance()

    proxy = SharedConfig.addProxy("127.0.0.1", 1443, "", "", "secret")
    assert proxy.address == "127.0.0.1"
    assert proxy.port == 1443
    assert SharedConfig.proxyList.size() >= 1
    assert SharedConfig.currentProxyInfo is proxy
    assert SharedConfig.currentProxy is proxy
    SharedConfig.deleteProxy(proxy)
    assert all(item is not proxy for item in SharedConfig.proxyList)

    assert ChatObject.getTitle({"title": "Chat"}) == "Chat"
    assert ChatObject.getTitle(
        {"first_name": "A", "last_name": "B"}
    ) == "A B"

    settings = MessagesController.getGlobalMainSettings()
    settings.edit().putInt("parity_global", 7).apply()
    assert settings.getInt("parity_global", 0) == 7
    account_settings = MessagesController.getInstance(0).getSharedPreferences(
        "mainconfig", 0
    )
    account_settings.edit().putInt("parity_account", 8).apply()
    assert account_settings.getInt("parity_account", 0) == 8

    assert ConnectionsManager.getProxySettings() is None
    assert ConnectionsManager.setProxySettings(None) is None
    assert Browser.openUrl("https://example.com") in (True, False)
    assert Browser.openUrl(None, "https://example.com") in (True, False)

    from android.graphics import Bitmap
    from androidx.core.graphics import PathParser
    from hook_utils import cast, jarray
    from java.util import Arrays

    assert Bitmap.Config.ARGB_8888 == 4
    bitmap = Bitmap.createBitmap(10, 20, Bitmap.Config.ARGB_8888)
    assert bitmap.getWidth() == 10
    assert bitmap.getHeight() == 20
    path = PathParser.createPathFromPathData("M0 0 L10 10 Z")
    assert path.commands
    array = jarray("java.lang.String")(["a", "b"])
    assert Arrays.asList(array).size() == 2
    assert cast("java.lang.String", "x") == "x"


def test_json_sqlite_and_format_facades():
    """JSON, SQLite and format facades used by real plugins."""
    from org.json import JSONArray, JSONObject
    from java.text import DecimalFormat, MessageFormat
    from android.graphics import Path, PathMeasure
    from android.database.sqlite import SQLiteDatabase

    obj = JSONObject('{"a": 1, "b": [2, 3]}')
    assert obj.getInt("a") == 1
    assert obj.getJSONArray("b").getInt(1) == 3
    assert obj.optString("missing", "x") == "x"
    obj.put("c", True)
    assert JSONObject(obj.toString()).getBoolean("c") is True
    assert "a" in obj.keySet()
    assert obj.names() == ["a", "b", "c"]

    array = JSONArray('[1, "two", {"x": 3}]')
    assert array.length() == 3
    assert array.getString(1) == "two"
    assert array.getJSONObject(2).getInt("x") == 3

    assert DecimalFormat("#,##0.00").format(1234.5) == "1,234.50"
    assert DecimalFormat("#,##0").format(1234) == "1,234"
    assert DecimalFormat("#,##0.00").parse("1,234.50") == 1234.5
    assert MessageFormat.format("Hello, {0}!", "world") == "Hello, world!"

    path = Path()
    path.moveTo(0, 0)
    path.lineTo(3, 4)
    measure = PathMeasure(path)
    assert measure.getLength() == 5.0
    position = [0.0, 0.0]
    tangent = [0.0, 0.0]
    assert measure.getPosTan(0, position, tangent) is True
    assert position == [0.0, 0.0]
    assert measure.getPosTan(3, position, tangent) is True
    assert position[0] > 0

    db = SQLiteDatabase(":memory:")
    db.execSQL("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    assert db.insert("t", None, {"name": "a"}) == 1
    cursor = db.rawQuery("SELECT name FROM t")
    assert cursor.moveToFirst() is True
    assert cursor.getString(0) == "a"
    assert cursor.getCount() == 1
    cursor.close()
    assert db.update("t", {"name": "b"}, "id = ?", [1]) == 1
    cursor = db.rawQuery("SELECT name FROM t")
    assert cursor.moveToFirst() and cursor.getString(0) == "b"
    assert db.delete("t", "id = ?", [1]) == 1
    db.close()


def test_launcher_and_shortcut_stubs():
    """Launcher/shortcut classes used by app-icon plugins resolve."""
    from android.app import ActivityManager
    from android.content import Context, Intent
    from android.content.pm import ShortcutInfo, ShortcutManager
    from android.graphics.drawable import Icon

    assert Context.SHORTCUT_SERVICE == "shortcut"
    assert Context.ACTIVITY_SERVICE == "activity"
    assert Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED == 0x00200000

    icon = Icon.createWithBitmap({"id": 1})
    assert icon.kind == "bitmap"
    resource_icon = Icon.createWithResource(None, 123)
    assert resource_icon.kind == "resource"
    assert resource_icon.resource == 123

    builder = ShortcutInfo.Builder(None, "shortcut-id")
    shortcut = builder.setShortLabel("Short").setLongLabel("Long").setIcon(
        icon
    ).setIntent(Intent(Intent.ACTION_VIEW)).build()
    assert shortcut.getId() == "shortcut-id"
    assert shortcut.getShortLabel() == "Short"
    assert shortcut.getLongLabel() == "Long"
    assert shortcut.getIcon() is icon
    assert shortcut.getIntent() is not None

    manager = ShortcutManager()
    assert manager.setDynamicShortcuts([shortcut]) is True
    assert manager.getDynamicShortcuts() == [shortcut]
    manager.removeAllDynamicShortcuts()
    assert manager.getDynamicShortcuts() == []

    description = ActivityManager.TaskDescription("Name", icon, 0xFF000000)
    assert description.getLabel() == "Name"
    assert description.getIcon() is icon
    assert description.getPrimaryColor() == 0xFF000000
    assert ActivityManager().getRunningTasks() == []
    assert ActivityManager().getAppTasks() == []


def test_java_time_facade():
    """`java.time` value types resolve and format through datetime."""
    from java.time import Duration, Instant, LocalDate, LocalDateTime
    from java.time.format import DateTimeFormatter

    assert Instant.now().toEpochMilli() > 0
    assert Instant.ofEpochSecond(5).toEpochMilli() == 5000
    assert Duration.ofSeconds(5).toMillis() == 5000
    assert LocalDate.of(2024, 1, 2).toString() == "2024-01-02"
    assert LocalDate.parse("2024-01-02").toString() == "2024-01-02"
    assert DateTimeFormatter.ofPattern("yyyy-MM-dd").format(
        LocalDate.of(2024, 1, 2)
    ) == "2024-01-02"
    assert LocalDateTime.of(2024, 1, 2, 3, 4, 5).toString() == (
        "2024-01-02T03:04:05"
    )


def test_chat_activity_facade():
    """`ChatActivity` exposes the chat id/controllers used by cleanup plugins."""
    from org.telegram.ui import ChatActivity
    from client_utils import get_last_fragment

    activity = ChatActivity({"dialog_id": -1001234567890, "topic_id": 7})
    assert activity.getDialogId() == -1001234567890
    assert activity.getTopicId() == 7
    assert activity.getChatMode() == 0
    assert activity.getSavedDialogId() == 0
    assert activity.getMergeDialogId() == 0
    assert activity.getCurrentEncryptedChat() is None
    assert activity.getParentActivity() is not None
    assert activity.getFragmentView() is not None
    assert activity.getMessagesController() is not None
    assert activity.getConnectionsManager() is not None
    assert activity.getUserConfig() is not None
    assert activity.getCurrentChat() is not None
    value = get_last_fragment()
    assert value is None or hasattr(value, "getDialogId")


def test_spans_and_drawable_extras():
    """Spans, ColorStateList and the drawable containers plugins build."""
    from android.text import SpannableString
    from android.text.style import (
        ForegroundColorSpan,
        RelativeSizeSpan,
        StyleSpan,
        URLSpan,
    )
    from android.content.res import ColorStateList
    from android.graphics.drawable import (
        ClipDrawable,
        GradientDrawable,
        InsetDrawable,
        LayerDrawable,
        PaintDrawable,
        RippleDrawable,
        StateListDrawable,
    )

    text = SpannableString("hello")
    span = ForegroundColorSpan(0xFFFF0000)
    text.setSpan(span, 0, 2, 0)
    assert text.getSpans(0, 2) == [span]
    assert text.getSpanStart(span) == 0
    assert text.getSpanEnd(span) == 2
    text.removeSpan(span)
    assert text.getSpans(0, 2) == []
    assert StyleSpan(1).getStyle() == 1
    assert URLSpan("https://x").getURL() == "https://x"
    assert RelativeSizeSpan(1.5).getSizeChange() == 1.5

    colors = ColorStateList.valueOf(0xFF112233)
    assert colors.getDefaultColor() == 0xFF112233
    assert colors.isStateful() is False
    assert colors.withAlpha(0x80).getDefaultColor() == 0x80112233

    gradient = GradientDrawable()
    gradient.setCornerRadii([1, 2, 3, 4, 5, 6, 7, 8])
    gradient.setStroke(2, 0xFF000000)
    gradient.setSize(10, 20)
    assert gradient.cornerRadii == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    assert gradient.strokeWidth == 2
    assert gradient.size == (10, 20)

    states = StateListDrawable()
    states.addState([], gradient)
    assert states.getStateCount() == 1
    assert states.getStateDrawable(0) is gradient

    layers = LayerDrawable([gradient])
    assert layers.getNumberOfLayers() == 1
    assert layers.getDrawable(0) is gradient

    ripple = RippleDrawable(0xFF000000, gradient)
    assert ripple.getDrawable(0) is gradient
    assert InsetDrawable(gradient, 4).getDrawable() is gradient
    assert ClipDrawable(gradient).drawable is gradient
    assert PaintDrawable(0xFF00FF00).color == 0xFF00FF00


def test_view_animation_facades():
    """`View.animate()` and the animator classes plugins drive."""
    from android.view import View
    from android.animation import AnimatorSet, ObjectAnimator, ValueAnimator

    view = View()
    ended = []
    view.animate().alpha(0.5).setDuration(200).withEndAction(
        lambda: ended.append(True)
    ).start()
    assert ended == [True]

    updates = []
    animator = ValueAnimator.ofFloat(0, 1).setDuration(100)
    animator.addUpdateListener(
        lambda value: updates.append(value.getAnimatedValue())
    )
    animator.start()
    assert updates == [1]
    assert animator.isRunning() is True

    target = {}
    object_animator = ObjectAnimator.ofFloat(target, "alpha", 0, 1)
    assert object_animator.getPropertyName() == "alpha"
    object_animator.start()

    group = AnimatorSet().playTogether(animator)
    group.start()
    group.cancel()


def test_interpolators_and_legacy_animations():
    """Interpolators, legacy animations and `ImageView.ScaleType`."""
    from android.view.animation import (
        AccelerateInterpolator,
        AlphaAnimation,
        AnimationSet,
        BounceInterpolator,
        DecelerateInterpolator,
        LinearInterpolator,
        OvershootInterpolator,
    )
    from android.widget import ImageView

    assert LinearInterpolator().getInterpolation(0.5) == 0.5
    assert 0.0 <= AccelerateInterpolator().getInterpolation(0.5) <= 1.0
    assert 0.0 <= DecelerateInterpolator().getInterpolation(0.5) <= 1.0
    assert 0.0 <= BounceInterpolator().getInterpolation(0.5) <= 1.0
    assert OvershootInterpolator().getInterpolation(0.5) >= 0.0

    animation = AlphaAnimation(0.0, 1.0).setDuration(200)
    assert animation.getDuration() == 200
    group = AnimationSet(True)
    group.addAnimation(animation)
    assert group.getAnimations() == [animation]
    assert ImageView.ScaleType.CENTER_CROP == 6
    image = ImageView()
    image.setScaleType(ImageView.ScaleType.CENTER_CROP)
    assert image.getScaleType() == ImageView.ScaleType.CENTER_CROP


def test_android_text_content_network_web_facades():
    """Text, content, network and WebView facades resolvable by plugins."""
    from android.text import Editable, Selection, StaticLayout, TextPaint
    from android.content import (
        BroadcastReceiver,
        ComponentName,
        ContextWrapper,
        IntentFilter,
    )
    from android.app import Service
    from android.net import ConnectivityManager, NetworkCapabilities, NetworkInfo
    from android.webkit import (
        CookieManager,
        WebResourceRequest,
        WebResourceResponse,
        WebView,
        WebViewClient,
    )

    editable = Editable("hello")
    Selection.setSelection(editable, 1, 3)
    assert Selection.getSelectionStart(editable) == 1
    assert Selection.getSelectionEnd(editable) == 3
    layout = StaticLayout("a\nb", TextPaint(), 100)
    assert layout.getLineCount() == 2
    assert layout.getWidth() == 100

    component = ComponentName("pkg", "pkg.Main")
    assert component.flattenToString() == "pkg/pkg.Main"
    assert ComponentName.unflattenFromString("pkg/pkg.Main").getClassName() == "pkg.Main"
    filter_ = IntentFilter("android.intent.action.VIEW")
    assert filter_.hasAction("android.intent.action.VIEW") is True
    assert filter_.match("android.intent.action.VIEW") == 0
    receiver = BroadcastReceiver()
    receiver.setResultCode(3)
    assert receiver.getResultCode() == 3
    wrapper = ContextWrapper()
    assert wrapper.getPackageName() == "org.telegram.Telegram"
    assert Service().onStartCommand() == Service.START_STICKY

    info = NetworkInfo(NetworkInfo.TYPE_WIFI, True)
    assert info.isConnected() is True
    assert info.getTypeName() == "WIFI"
    capabilities = NetworkCapabilities().addTransportType(
        NetworkCapabilities.TRANSPORT_WIFI
    ).addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    assert capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) is True
    assert capabilities.hasCapability(
        NetworkCapabilities.NET_CAPABILITY_INTERNET
    ) is True
    manager = ConnectivityManager()
    assert manager.getActiveNetworkInfo().isConnected() is True
    assert manager.getNetworkCapabilities().hasTransport(1) is True

    web = WebView()
    settings = web.getSettings()
    settings.setJavaScriptEnabled(False)
    assert settings.getJavaScriptEnabled() is False
    web.loadUrl("https://example.com")
    assert web.getUrl() == "https://example.com"
    web.setWebViewClient(WebViewClient())
    assert CookieManager.getInstance() is CookieManager.getInstance()
    request = WebResourceRequest("https://example.com", "GET")
    assert request.getMethod() == "GET"
    assert request.getUrl().toString() == "https://example.com"
    response = WebResourceResponse("text/html", "utf-8")
    assert response.getMimeType() == "text/html"


def test_assets_and_animation_extras():
    """AssetManager, animator inflaters and Choreographer."""
    from android.content.res import AssetManager
    from android.animation import (
        AnimatorInflater,
        AnimatorListenerAdapter,
        ValueAnimator,
    )
    from android.view.animation import AnimationUtils
    from android.view import Choreographer

    assets = AssetManager()
    assert isinstance(assets.list(), list)
    assert assets.open("missing-asset") is not None
    assert isinstance(AnimatorInflater.loadAnimator(None, 0), ValueAnimator)
    assert AnimationUtils.loadAnimation(None, 0) is not None
    assert AnimationUtils.currentAnimationTimeMillis() > 0
    listener = AnimatorListenerAdapter()
    assert listener.onAnimationEnd() is None
    frames = []
    Choreographer.getInstance().postFrameCallback(
        lambda value: frames.append(value)
    )
    assert frames


def test_graphics_transition_and_adapter_facades():
    """Graphics matrices, transitions and list adapters used by plugin UI."""
    from android.graphics import (
        BlendMode,
        ColorMatrix,
        ColorMatrixColorFilter,
        DashPathEffect,
        PixelFormat,
        SweepGradient,
    )
    from android.transition import Fade, Slide, TransitionManager, TransitionSet
    from android.widget import ArrayAdapter, ListView

    matrix = ColorMatrix()
    assert len(matrix.getArray()) == 20
    assert ColorMatrixColorFilter(matrix).values == matrix.getArray()
    assert PixelFormat.RGBA_8888 == 1
    assert BlendMode.SRC_OVER == 3
    assert DashPathEffect([2, 2], 0).intervals == [2, 2]
    assert SweepGradient(0, 0, 0, 0) is not None

    transition = Fade(Fade.IN)
    group = TransitionSet().addTransition(transition)
    assert group.getTransitionCount() == 1
    assert Slide(Slide.LEFT).gravity == Slide.LEFT
    assert TransitionManager.beginDelayedTransition(None, group) is None

    adapter = ArrayAdapter(None, 0, ["a", "b"])
    adapter.add("c")
    assert adapter.getCount() == 3
    assert adapter.getItem(1) == "b"
    list_view = ListView()
    list_view.setAdapter(adapter)
    assert list_view.getCount() == 3
    list_view.setSelection(1)


def test_parcel_notification_window_gesture_facades():
    """Parcel, notification, window, gesture and Bitmap extras."""
    from android.os import Binder, Parcel, Parcelable
    from android.app import Notification, NotificationChannel, NotificationManager
    from android.view import (
        GestureDetector,
        KeyEvent,
        LayoutInflater,
        MotionEvent,
        WindowManager,
    )
    from android.widget import ListPopupWindow, PopupWindow
    from android.graphics import Bitmap

    parcel = Parcel.obtain()
    parcel.writeString("x")
    parcel.writeInt(3)
    assert parcel.dataSize() == 2
    assert Parcelable().describeContents() == 0
    assert Binder().pingBinder() is True

    manager = NotificationManager()
    channel = NotificationChannel(
        "id", "Name", NotificationManager.IMPORTANCE_DEFAULT
    )
    manager.createNotificationChannel(channel)
    assert manager.getNotificationChannel("id") is channel
    notification = Notification.Builder(None, "id").setContentTitle("T").build()
    manager.notify(1, notification)
    assert manager.getActiveNotifications() == [notification]
    manager.cancel(1)
    assert manager.getActiveNotifications() == []

    assert WindowManager().getDefaultDisplay().getWidth() > 0
    assert LayoutInflater.from_().inflate(0) is not None
    assert KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_BACK).getKeyCode() == 4
    assert MotionEvent.obtain().getAction() == 0
    assert GestureDetector().onTouchEvent(None) is False

    popup = PopupWindow()
    assert popup.isShowing() is False
    popup.showAtLocation()
    assert popup.isShowing() is True
    popup.dismiss()
    assert popup.isShowing() is False
    assert ListPopupWindow().getSelectedItemPosition() == -1

    bitmap = Bitmap(b"", 2, 2)
    assert bitmap.copy().getWidth() == 2
    assert bitmap.getRowBytes() == 8
    assert bitmap.isMutable() is False


def test_location_sensor_telephony_and_text_methods():
    """android.location, hardware, telephony and text.method facades."""
    from android.location import Criteria, Location, LocationManager
    from android.hardware import Sensor, SensorManager
    from android.telephony import TelephonyManager
    from android.text.method import (
        DigitsKeyListener,
        InputFilter,
        LinkMovementMethod,
        MetaKeyKeyListener,
        MovementMethod,
        PasswordTransformationMethod,
    )

    location = Location("gps")
    location.setLatitude(55.75)
    location.setLongitude(37.61)
    location.setAccuracy(5.0)
    assert location.getProvider() == "gps"
    assert location.hasAccuracy() is True
    assert location.distanceTo(location) == 0.0
    assert 0.0 <= location.bearingTo(location) < 360.0
    assert Location.distanceBetween(0, 0, 0, 1) > 100000

    manager = LocationManager()
    assert manager.isProviderEnabled(LocationManager.GPS_PROVIDER) is True
    assert manager.getAllProviders()
    assert manager.getLastKnownLocation("gps") is None
    assert Criteria().getAccuracy() == Criteria.ACCURACY_COARSE

    assert Sensor("accel", Sensor.TYPE_ACCELEROMETER).getType() == 1
    assert SensorManager().getDefaultSensor(Sensor.TYPE_LIGHT) is not None
    phone = TelephonyManager()
    assert phone.getPhoneType() == TelephonyManager.PHONE_TYPE_NONE
    assert phone.getNetworkType() == TelephonyManager.NETWORK_TYPE_UNKNOWN
    assert phone.isNetworkRoaming() is False

    assert isinstance(LinkMovementMethod.getInstance(), MovementMethod)
    assert MovementMethod().onTouchEvent(None) is False
    assert InputFilter.LengthFilter(3).filter("abcd") is None
    assert DigitsKeyListener(True, False).getInputType() == 2
    assert PasswordTransformationMethod.getInstance() is not None
    assert MetaKeyKeyListener.getMetaState() == 0


def test_queue_aslist_and_last_fragment():
    """Background queues, Java varargs and the current-fragment bridge."""
    import threading
    import time

    import extera_ios
    from java.util import Arrays
    from org.telegram.messenger import DispatchQueue
    from org.telegram.ui import ChatActivity, LaunchActivity
    from client_utils import _Queue, get_last_fragment

    values = Arrays.asList(1, 2, 3)
    assert values.size() == 3
    assert values.get(1) == 2

    main_thread = threading.get_ident()
    seen = []
    queue = DispatchQueue("parity-bg")
    queue.runOnQueue(lambda: seen.append(threading.get_ident()))
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    assert seen and seen[0] != main_thread

    cancelled = []
    delayed = _Queue("parity-delay")
    handle = delayed.postRunnable(lambda: cancelled.append(True), 250)
    handle.cancel()
    time.sleep(0.4)
    assert not cancelled

    original = extera_ios.host

    def fake_host(name, **kwargs):
        if name in ("client.last_fragment", "ui.last_fragment"):
            return {
                "__class__": "org.telegram.ui.ChatActivity",
                "dialog_id": -1001234567890,
                "topic_id": 9,
            }
        return original(name, **kwargs)

    extera_ios.host = fake_host
    try:
        fragment = get_last_fragment()
        assert isinstance(fragment, ChatActivity)
        assert fragment.getDialogId() == -1001234567890
        assert fragment.getTopicId() == 9
        safe = LaunchActivity.getSafeLastFragment()
        assert isinstance(safe, ChatActivity)
        assert safe.getDialogId() == -1001234567890
    finally:
        extera_ios.host = original


def test_android_extended_facade_surface():
    """Build/NSD/animation/byte-buffer members used by real plugins."""
    import extera_ios
    from android.os import Build, BatteryManager, Handler, Message, Process
    from android.content import Context, Intent
    from android.app import Activity
    from android.view import View, ViewTreeObserver, animation
    from android.graphics.drawable import GradientDrawable
    from android.text import SpannableString, TextUtils
    from android.net.nsd import NsdManager, NsdServiceInfo
    from android.net.wifi import WifiManager
    from java.nio import ByteBuffer
    from org.telegram.messenger import (
        ApplicationLoader,
        FileLoader,
        LaunchActivity,
        LocaleController,
        SendMessagesHelper,
    )
    from org.telegram.ui.Components import ItemOptions
    from com.exteragram.messenger.plugins import PluginsController
    from org.telegram.tgnet import TLRPC

    assert Build.FINGERPRINT
    assert Build.SUPPORTED_ABIS
    assert BatteryManager().isCharging() is True
    assert Process.myUid() >= 0
    message = Message.obtain(None, 7)
    assert message.what == 7
    Handler().removeCallbacksAndMessages(None)
    import requests

    assert requests.Session().get is not None
    assert Intent.ACTION_BATTERY_CHANGED.endswith("BATTERY_CHANGED")
    assert Context.NSD_SERVICE == "servicediscovery"
    assert animation.Animation.ABSOLUTE == 0
    assert animation.Animation.RELATIVE_TO_SELF == 1
    assert View.FOCUS_DOWN == 130
    assert ViewTreeObserver().isAlive() is True
    assert SpannableString.SPAN_EXCLUSIVE_EXCLUSIVE == 33
    assert TextUtils.TruncateAt.END == "end"
    assert GradientDrawable.RECTANGLE == 0
    assert ByteBuffer.allocate(4).putInt(7).flip().getInt() == 7
    assert len(ItemOptions.makeOptions("one", "two")) == 2
    entity = TLRPC.MessageEntity()
    entity.offset = 1
    entity.length = 3
    assert entity.offset == 1 and entity.length == 3
    message = TLRPC.Message()
    message.id = 7
    assert message.id == 7

    service = NsdServiceInfo("ADB", "_adb._tcp.", 5555)
    assert service.getServiceName() == "ADB"
    NsdManager().registerService(
        service, NsdManager.PROTOCOL_DNS_SD, NsdManager.RegistrationListener()
    )
    manager = ApplicationLoader.getApplicationContext().getSystemService(
        Context.NSD_SERVICE
    )
    assert isinstance(manager, NsdManager)
    wifi = ApplicationLoader.getApplicationContext().getSystemService(
        Context.WIFI_SERVICE
    )
    assert isinstance(wifi, WifiManager)
    assert wifi.isWifiEnabled() is True
    activity = Activity()
    assert isinstance(
        activity.getSystemService(Context.WIFI_SERVICE), WifiManager
    )
    assert activity.getResources() is not None
    assert activity.getWindow() is not None
    assert activity.getLayoutInflater() is not None
    assert activity.getParentActivity() is activity
    assert activity.isFinishing() is False

    locale = LocaleController.getCurrentLocale()
    assert locale is not None and locale.getLanguage()
    info = LocaleController.getCurrentLocaleInfo()
    assert info.getLanguageCode()

    assert LaunchActivity.instance is not None
    assert SendMessagesHelper.getClass() is not None
    assert PluginsController.getInstance().engines
    assert FileLoader.getInstance(0).getDirectory(FileLoader.MEDIA_DIR_FILES) is not None
    assert FileLoader.getInstance(0).getPathToAttach({"path": "/tmp/a"}) is not None


def test_real_plugin_ui_facades():
    """Sheets, particles, scroll views, gifts and set/scanner helpers."""
    from org.telegram.ui.ActionBar import BottomSheet
    from org.telegram.ui.Components.Premium import StarParticlesView
    from androidx.core.widget import NestedScrollView
    from org.telegram.ui.Components import BackupImageView
    from org.telegram.ui.Gifts import GiftSheet
    from org.telegram.ui import ProxyListActivity
    from org.telegram.tgnet import RequestTimeDelegate
    from android.os import StatFs
    from java.util import Scanner, HashSet

    sheet = BottomSheet(None, False)
    sheet.setTitle("Title").setCustomView(StarParticlesView(None, 160))
    sheet.show()
    assert sheet.isShowing() is True
    sheet.dismiss()
    assert sheet.isShowing() is False
    assert StarParticlesView(None, 160).size == 160
    assert NestedScrollView(None).isNestedScrollingEnabled() is True
    assert BackupImageView(None).round_radius == 0
    assert GiftSheet(None, 0, 1).isShowing() is False
    assert ProxyListActivity.TextDetailProxyCell is not None
    assert RequestTimeDelegate().run(0) is None
    assert StatFs(".").getTotalBytes() >= 0
    assert Scanner("a b").next() == "a"
    values = HashSet([1, 2])
    values.add(3)
    assert values.size() == 3
    assert values.contains(2) is True


def test_java_networking_facades():
    """Threads, sockets, HTTP, byte streams and SoundPool used by plugins."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from java.lang import Thread
    from java.io import ByteArrayOutputStream
    from java.net import URL, InetAddress, InetSocketAddress, ServerSocket
    from java import jclass
    from android.media import SoundPool
    from hook_utils import find_class

    Thread.currentThread().setPriority(3)
    assert Thread.currentThread().getPriority() == 3
    assert jclass("java.lang.Thread") is Thread

    stream = ByteArrayOutputStream()
    stream.write(b"abc")
    assert stream.toByteArray() == b"abc"
    assert stream.size() == 3

    assert InetAddress.getByName("127.0.0.1").getHostAddress() == "127.0.0.1"
    address = InetSocketAddress("127.0.0.1", 80)
    assert address.getPort() == 80
    server = ServerSocket(0)
    assert server.getLocalPort() > 0
    server.close()

    assert find_class("android.media.SoundPool") is SoundPool
    pool = SoundPool(3, 3, 0)
    sound_id = pool.load(None, 1)
    assert pool.play(sound_id) == sound_id
    pool.release()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b"hi"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.handle_request, daemon=True)
    worker.start()
    connection = URL("http://127.0.0.1:%d/" % httpd.server_port).openConnection()
    assert connection.getResponseCode() == 200
    assert connection.getHeaderField("Content-Type") == "text/plain"
    assert connection.getContentLength() == 2
    assert connection.getInputStream().read() == b"hi"
    httpd.server_close()


def test_dev_server_tcp_commands():
    """The iOS dev server answers the Android JSON protocol over loopback TCP."""
    import json
    import socket
    import time

    from dev_server import DevServer

    if DevServer.is_server_running():
        DevServer.stop_server()

    thread = DevServer.start_server("127.0.0.1", 0)
    deadline = time.time() + 3.0
    while DevServer._port <= 0 and time.time() < deadline:
        time.sleep(0.01)
    assert DevServer._port > 0
    assert thread is not None

    def read_response(client):
        buffer = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                raise AssertionError("server closed the connection")
            buffer += chunk
            try:
                return json.loads(buffer.decode("utf-8"))
            except ValueError:
                continue

    try:
        client = socket.create_connection(
            ("127.0.0.1", DevServer._port), timeout=3
        )
        try:
            client.sendall(json.dumps({"@": "ping", "#": 1}).encode("utf-8") + b"\n")
            pong = read_response(client)
            assert pong.get("#") == 1, pong
            assert pong.get("pong") is True, pong

            client.sendall(
                json.dumps({"@": "get_plugins", "#": 2}).encode("utf-8") + b"\n"
            )
            plugins = read_response(client)
            assert plugins.get("#") == 2, plugins
            assert isinstance(plugins, dict), plugins
        finally:
            client.close()
    finally:
        DevServer.stop_server()


def test_java_uri_file_crypto_facades():
    """URI, random-access files, data streams, SecureRandom and HMAC."""
    import hashlib
    import hmac
    import io
    import os
    import tempfile

    from java.net import URI
    from java.io import (
        ByteArrayOutputStream,
        DataInputStream,
        DataOutputStream,
        RandomAccessFile,
    )
    from java.security import SecureRandom
    from javax.crypto import Mac
    from javax.crypto.spec import SecretKeySpec

    uri = URI("https://example.com:8443/a?b=1#frag")
    assert uri.getScheme() == "https"
    assert uri.getHost() == "example.com"
    assert uri.getPort() == 8443
    assert uri.getPath() == "/a"
    assert uri.getQuery() == "b=1"
    assert uri.getFragment() == "frag"
    assert uri.toURL().getHost() == "example.com"

    path = tempfile.mktemp(prefix="extera-raf-")
    try:
        handle = RandomAccessFile(path, "rw")
        handle.write(b"abc")
        handle.writeInt(7)
        handle.seek(0)
        assert handle.read(3) == list(b"abc")
        handle.seek(3)
        assert handle.readInt() == 7
        handle.close()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    buffer = ByteArrayOutputStream()
    output = DataOutputStream(buffer)
    output.writeInt(5)
    output.writeUTF("hi")
    output.flush()
    source = DataInputStream(io.BytesIO(buffer.toByteArray()))
    assert source.readInt() == 5
    assert source.readUTF() == "hi"

    values = [0] * 8
    SecureRandom().nextBytes(values)
    assert any(values)

    mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(b"key", "HmacSHA256"))
    assert bytes(mac.doFinal(b"data")) == hmac.new(
        b"key", b"data", hashlib.sha256
    ).digest()


def main():
    compat.install()
    test_text_formatting()
    test_markdown_utils()
    test_managed_classes()
    test_logging()
    test_lifecycle()
    test_settings_factory()
    test_hook_filters()
    test_conditions()
    test_tl_objects()
    test_android_ui_shims()
    test_android_java_shims()
    test_compat_plugin()
    test_file_and_intent_hooks()
    test_alert_builder()
    test_menu_runtime()
    test_dependency_directory()
    test_notification_center()
    test_file_utils_list_dir()
    test_file_loader_paths()
    test_androidx_stubs()
    test_mvel_facade()
    test_app_facades()
    test_elyx_ui_stubs()
    test_plugins_constants()
    test_uitem_facade()
    test_android_graphics_stubs()
    test_android_widget_stubs()
    test_messages_controller_fallbacks()
    test_send_message_params_media()
    test_send_message_param_helpers()
    test_file_loader_download_cache()
    test_file_loader_photo_cache()
    test_connections_manager()
    test_chat_user_dialog_objects()
    test_messages_controller_overlay()
    test_message_object_payload_methods()
    test_plugin_execution_watchdog()
    test_analyzer_diff()
    test_android_constant_parity()
    test_android_import_surface()
    test_android_member_surface()
    test_partial_hook_api()
    test_partial_hook_registration()
    test_partial_hook_install_path()
    test_runtime_services()
    test_edit_message_media_payload()
    test_send_media_helpers()
    test_class_proxy_facade()
    test_media_controller_playback()
    test_java_native_classes()
    test_chaquopy_facade()
    test_messages_controller_loaders()
    test_messages_controller_actions()
    test_messages_controller_pins_and_blocks()
    test_topics_controller_facade()
    test_controller_settings()
    test_message_media_kinds()
    test_contacts_and_storage()
    test_media_data_controller()
    test_user_object_fields()
    test_chat_object_rights()
    test_build_and_shared_config()
    test_locale_helpers()
    test_user_config_facade()
    test_android_facade_surface()
    test_android_facade_extras()
    test_send_poll_payload()
    test_raw_tl_request_normalization()
    test_java_crypto_and_network_facades()
    test_android_extended_facade_surface()
    test_real_plugin_ui_facades()
    test_java_networking_facades()
    test_java_uri_file_crypto_facades()
    test_dev_server_tcp_commands()
    test_queue_aslist_and_last_fragment()
    test_json_sqlite_and_format_facades()
    test_launcher_and_shortcut_stubs()
    test_java_time_facade()
    test_chat_activity_facade()
    test_spans_and_drawable_extras()
    test_view_animation_facades()
    test_interpolators_and_legacy_animations()
    test_android_text_content_network_web_facades()
    test_assets_and_animation_extras()
    test_graphics_transition_and_adapter_facades()
    test_parcel_notification_window_gesture_facades()
    test_location_sensor_telephony_and_text_methods()
    test_media_metadata_retriever()
    test_utilities_helpers()
    test_android_partial_hooks_example()
    print("ALL PARITY OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
