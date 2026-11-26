# This is the iOS counterpart of the exteraGram plugins SDK.
#
# `extera_ios` is the Python face of the app.  Every call goes through one
# JSON-encoded ABI (`_extera_native.host`), so the Swift side never has to know
# about Python objects and a plugin cannot reach a host object it was not given.
#
# The same API names as on Android are used wherever the operation exists on
# iOS (send_text, log, run_on_ui_thread, ...).  Where the platform has no direct
# equivalent the call is routed to the closest iOS surface and the result is
# reported in the same shape, so plugin code does not grow a second branch.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import itertools
import json
import os
import threading
import traceback

import _extera_native


_LOCK = threading.RLock()
_CALLBACKS = {}
_NEXT_CALLBACK = itertools.count(1)


def _decode(text, fallback=None):
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


class _AttrDict(dict):
    """JSON objects whose keys are also readable as attributes."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    # -- Xposed MethodHookParam compatibility ------------------------------
    def getResult(self):
        return self.get("result")

    def setResult(self, value):
        self["result"] = value
        if self.get("__param__") and self.get("id"):
            try:
                host("hook.param.set", id=self["id"], value=value)
            except Exception:
                pass

    def getObjectExtra(self, key):
        return self.get("extra", {}).get(key)

    def setObjectExtra(self, key, value):
        extra = self.setdefault("extra", {})
        extra[key] = value
        if self.get("__param__") and self.get("id"):
            try:
                host("hook.param.extra", id=self["id"], key=key, value=value)
            except Exception:
                pass

    def hasThrowable(self):
        return False

    def getThrowable(self):
        return None

    def setThrowable(self, value):
        self["throwable"] = value


def _wrap_json(value):
    if isinstance(value, dict):
        if "__handle__" in value:
            try:
                from extera_utils.classes import ObjectProxy

                return ObjectProxy(
                    str(value.get("__class__") or "java.lang.Object"),
                    handle=str(value.get("__handle__")),
                    data={key: _wrap_json(item) for key, item in value.items()
                          if not key.startswith("__")},
                )
            except Exception:
                return value
        wrapped = {key: _wrap_json(item) for key, item in value.items()}
        if value.get("__param__"):
            return _Param(wrapped)
        return _AttrDict(wrapped)
    if isinstance(value, list):
        return [_wrap_json(item) for item in value]
    return value


class _ArgList(list):
    """A live argument list for a method hook.

    Assigning an item writes through to the Objective-C invocation, so a
    `before_hooked_method` callback can change an argument the way Xposed can.
    """

    def __init__(self, values, param_id):
        super().__init__(values)
        self._param_id = param_id

    def __setitem__(self, index, value):
        super().__setitem__(index, value)
        if self._param_id:
            try:
                host("hook.param.set_argument", id=self._param_id, index=int(index), value=value)
            except Exception:
                pass


class _Param(_AttrDict):
    def __init__(self, value):
        super().__init__(value)
        param_id = self.get("id")
        self["args"] = _ArgList(self.get("args", []), param_id)


def _decode_args(payload):
    try:
        return _wrap_json(json.loads(payload, object_hook=_AttrDict))
    except Exception:
        return []


def _encode(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=_encode_default)
    except Exception:
        return "null"


def _encode_default(value):
    if hasattr(value, "to_json"):
        return value.to_json()
    if hasattr(value, "__dict__"):
        return {k: v for k, v in value.__dict__.items() if not k.startswith("_")}
    return str(value)


def host(_method=None, **payload):
    """Performs one host call and returns the decoded result.

    The first parameter is deliberately not named `method`: `java.call` and
    other host payloads carry a `method` key of their own, and a parameter with
    that name would make `host("java.call", method="...")` fail before the
    payload is encoded.
    """
    if _method is None:
        _method = payload.pop("method", None)
    if _method is None:
        raise TypeError("host() is missing the host method name")
    with _LOCK:
        raw = _extera_native.host(str(_method), _encode(payload))
    return _wrap_json(_decode(raw, None))


def host_json(_method, _payload):
    with _LOCK:
        raw = _extera_native.host(
            str(_method),
            _payload if isinstance(_payload, str) else _encode(_payload),
        )
    return _wrap_json(_decode(raw, None))


def retain(callback):
    """Keeps a Python callable alive for the host.

    Returns an opaque string the Swift side can pass back with `invoke`.
    """
    if callback is None:
        return None
    handle = "cb-%d" % next(_NEXT_CALLBACK)
    with _LOCK:
        _CALLBACKS[handle] = callback
    return handle


def release(handle):
    if not handle:
        return
    with _LOCK:
        _CALLBACKS.pop(handle, None)


def callback(handle, args=None):
    """Returns a callable that invokes a retained callback with fixed args."""
    if handle is None:
        return None

    def invoke(*extra):
        payload = list(args or [])
        payload.extend(extra)
        return _invoke(handle, _encode(payload))

    return invoke


def _invoke(handle, payload):
    with _LOCK:
        callback = _CALLBACKS.get(handle)
    if callback is None:
        return "null"
    args = _decode_args(payload)
    if not isinstance(args, list):
        args = [args]
    try:
        return _encode(callback(*args))
    except Exception:
        log("[callback %s] %s" % (handle, traceback.format_exc()))
        return "null"


# ---------------------------------------------------------------------------
# General helpers


def log(text):
    try:
        _extera_native.host("log", _encode({"text": str(text)}))
    except Exception:
        print(text)


def app_info():
    return host("app.info") or {}


def app_version():
    info = app_info()
    return str(info.get("engine_version") or info.get("version") or "13.2.1")


def sdk_version():
    return str(app_info().get("sdk_version") or "1.4.6.5")


def device_info():
    return host("device.info") or {}


def current_account():
    value = host("account.current")
    return int(value) if isinstance(value, (int, float)) else 0


def accounts():
    value = host("account.list")
    return [int(item) for item in value] if isinstance(value, list) else [0]


def run_on_ui_thread(function, delay=0):
    """Runs `function` on the main queue.

    The call itself returns immediately; the returned handle can be passed to
    `cancel_ui_task`.
    """
    handle = retain(function)
    result = host("ui.run", handle=handle, delay=int(delay or 0))
    return result if result is not None else handle


def cancel_ui_task(handle):
    if handle:
        release(handle)
        host("ui.cancel", handle=handle)


def copy_to_clipboard(text):
    return host("ui.copy", text=str(text))


def get_clipboard():
    return host("ui.clipboard") or ""


def toast(text, duration=2000):
    return host("ui.toast", text=str(text), duration=int(duration))


def notify(title, text, timeout=0):
    return host("ui.notify", title=str(title), text=str(text), timeout=int(timeout))


def open_url(url, external=False):
    return host("ui.open_url", url=str(url), external=bool(external))


def present_controller(spec):
    """Presents a controller described by `spec`.

    Used by `ui.settings.create_sub_fragment` and by plugins that build a
    settings screen from Python descriptors.
    """
    return host("ui.present", spec=spec)


def dismiss_controller(identifier):
    return host("ui.dismiss", id=identifier)


def pick_file(extensions=None, multiple=False):
    return host("ui.pick_file", extensions=list(extensions or []), multiple=bool(multiple))


def http_request(url, method="GET", headers=None, body=None, timeout=30):
    """Synchronous HTTP request, executed off the main thread by the host."""
    return host(
        "http.request",
        url=str(url),
        method=str(method).upper(),
        headers=dict(headers or {}),
        body=body,
        timeout=float(timeout),
    ) or {}


def http_download(url, path, max_bytes=250 * 1024 * 1024, timeout=120):
    """Downloads a binary file to `path` through the host (system trust store)."""
    return host(
        "http.download",
        url=str(url),
        path=str(path),
        max_bytes=int(max_bytes),
        timeout=float(timeout),
    ) or {}


# ---------------------------------------------------------------------------
# Telegram data


def send_text(account, peer, text, entities=None, reply_to=None, silent=False,
              schedule_date=0, parse_mode=None, extra=None):
    from extera_utils.text_formatting import parse_text

    if parse_mode:
        parsed = parse_text(text, parse_mode)
        text = parsed.get("message", text)
        entities = parsed.get("entities")
    payload = {
        "account": int(account),
        "peer": int(peer),
        "text": text,
        "entities": entities or [],
        "reply_to": int(reply_to) if reply_to else 0,
        "silent": bool(silent),
        "schedule_date": int(schedule_date or 0),
    }
    if extra:
        payload.update(extra)
    return host("client.send_text", **payload)


def send_media(account, peer, path, kind, caption="", entities=None, reply_to=None,
               silent=False, schedule_date=0, parse_mode=None, extra=None):
    from extera_utils.text_formatting import parse_text

    if parse_mode and caption:
        parsed = parse_text(caption, parse_mode)
        caption = parsed.get("message", caption)
        entities = parsed.get("entities")
    payload = {
        "account": int(account),
        "peer": int(peer),
        "path": str(path),
        "kind": str(kind),
        "caption": caption,
        "entities": entities or [],
        "reply_to": int(reply_to) if reply_to else 0,
        "silent": bool(silent),
        "schedule_date": int(schedule_date or 0),
    }
    if extra:
        payload.update(extra)
    return host("client.send_media", **payload)


def edit_message(account, peer, message_id, text=None, entities=None, path=None,
                 parse_mode=None, extra=None):
    from extera_utils.text_formatting import parse_text

    if parse_mode and text:
        parsed = parse_text(text, parse_mode)
        text = parsed.get("message", text)
        entities = parsed.get("entities")
    kind = None
    if path:
        extension = os.path.splitext(str(path))[1].lower()
        if extension in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic",
                         ".heif", ".bmp"):
            kind = "photo"
        else:
            kind = "document"
    payload = {
        "account": int(account),
        "peer": int(peer),
        "message_id": int(message_id),
        "text": text,
        "entities": entities or [],
        "path": str(path) if path else None,
        "kind": kind,
    }
    if extra:
        payload.update(extra)
    return host("client.edit_message", **payload)


def delete_messages(account, message_ids, revoke=True, peer=0):
    return host("client.delete_messages", account=int(account), peer=int(peer or 0),
                message_ids=[int(i) for i in message_ids], revoke=bool(revoke))


def send_request(account, request_name, payload=None, timeout=30):
    return host("client.request", account=int(account), name=str(request_name),
                payload=payload or {}, timeout=float(timeout)) or {}


def get_peer(account, peer_id):
    return host("client.peer", account=int(account), peer=int(peer_id)) or {}


def get_chats(account, limit=100, offset=0):
    value = host("client.chats", account=int(account), limit=int(limit), offset=int(offset))
    return value if isinstance(value, list) else []


def get_contacts(account):
    value = host("client.contacts", account=int(account))
    return value if isinstance(value, list) else []


def get_me(account):
    return host("client.me", account=int(account)) or {}


# ---------------------------------------------------------------------------
# Plugin host operations


def register_event_hook(plugin_id, name, match_substring=False, priority=0):
    return host("hooks.add", plugin_id=plugin_id, name=name,
                match_substring=bool(match_substring), priority=int(priority))


def remove_event_hook(plugin_id, name):
    return host("hooks.remove", plugin_id=plugin_id, name=name)


def add_menu_item(plugin_id, data):
    return host("menu.add", plugin_id=plugin_id, data=data)


def update_menu_item(plugin_id, item_id, data):
    return host("menu.update", plugin_id=plugin_id, item_id=item_id, data=data)


def remove_menu_item(plugin_id, item_id):
    return host("menu.remove", plugin_id=plugin_id, item_id=item_id)


def reload_plugin_settings(plugin_id):
    return host("settings.reload", plugin_id=plugin_id)


def open_plugin_settings(plugin_id, link_alias=None):
    return host("settings.open", plugin_id=plugin_id, link=link_alias)


def register_file_handler(plugin_id, extension, description, handle, icon=None):
    return host("file.register", plugin_id=plugin_id, extension=extension,
                description=description, handle=handle, icon=icon)


def unregister_file_handler(plugin_id, extension):
    return host("file.unregister", plugin_id=plugin_id, extension=extension)


def register_intent_handler(plugin_id, spec, handle, before=True):
    return host("intent.register", plugin_id=plugin_id, spec=spec,
                handle=handle, before=bool(before))


def unregister_intent_handler(plugin_id, handler_id):
    return host("intent.unregister", plugin_id=plugin_id, id=handler_id)


def resolve_symbol(symbol):
    return host("runtime.resolve", symbol=symbol) or {}


def call_telegram(target, method, args=None):
    return host("telegram.call", target=target, method=method, args=list(args or []))


# ---------------------------------------------------------------------------
# Alerts


class AlertHandle:
    """The object returned by `AlertDialogBuilder.show()` on iOS.

    On Android this is a `org.telegram.ui.ActionBar.AlertDialog`; on iOS there
    is no UIKit class exposed to Python, so the handle carries the same
    operations and forwards them to the host.
    """

    def __init__(self, identifier):
        self._id = identifier
        self._showing = True

    def get_id(self):
        return self._id

    def is_showing(self):
        return self._showing

    def isShowing(self):
        return self.is_showing()

    def dismiss(self):
        self._showing = False
        host("alert.dismiss", id=self._id)

    def set_progress(self, progress):
        return host("alert.update", id=self._id, progress=int(progress))

    def setProgress(self, progress):
        return self.set_progress(progress)

    def set_cancelable(self, cancelable):
        return host("alert.update", id=self._id, cancelable=bool(cancelable))

    def setCancelable(self, cancelable):
        return self.set_cancelable(cancelable)

    def set_canceled_on_touch_outside(self, cancel):
        return host("alert.update", id=self._id, cancel=bool(cancel))

    def setCanceledOnTouchOutside(self, cancel):
        return self.set_canceled_on_touch_outside(cancel)

    def get_button(self, button):
        return None

    def getButton(self, button):
        return self.get_button(button)

    def get_themed_color(self, key):
        return 0

    def getThemedColor(self, key):
        return self.get_themed_color(key)
