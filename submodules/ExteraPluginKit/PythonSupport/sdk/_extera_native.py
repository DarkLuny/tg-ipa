# This is the iOS counterpart of the exteraGram plugins SDK.
#
# The module is normally provided by the app as a CPython extension
# (PluginPython.c).  This file is the fallback used when the SDK is imported
# outside the app - by the host tests or by a desktop debug session - so that
# `import extera_ios` keeps working and every host call is visible in the log.
#
# The two functions below are the whole native surface:
#
#   host(method, payload) -> json
#   invoke(handle, payload) -> json
#
# `host` is a remote call into the Swift host.  `invoke` is called by the host
# when it needs to run a Python callback (an alert button, a settings row, a
# menu item) that the SDK retained earlier.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import json
import sys
import time
import traceback


_HOST_CALLS = []
_VERBOSE = False


def _dispatch(method, payload):
    try:
        data = json.loads(payload) if payload else {}
    except Exception:
        data = payload
    _HOST_CALLS.append((method, data))
    if _VERBOSE:
        sys.stderr.write("[extera-ios] host call: %s %r\n" % (method, data))

    # A tiny amount of behaviour is needed for the SDK to be usable in tests:
    # settings, logging and account queries have no side effects.
    if method == "app.info":
        return {
            "version": "13.2",
            "build": "0",
            "sdk_version": "1.4.6.5",
            "platform": "ios",
            "engine": "python",
        }
    if method == "account.list":
        return [0]
    if method == "account.current":
        return 0
    if method == "settings.get":
        return data.get("default")
    if method == "device.info":
        return {"model": "test", "system": "test", "locale": "en"}
    if method == "ui.alert":
        return {"id": "stub-alert-%d" % int(time.time() * 1000)}
    if method in ("alert.create", "alert.show"):
        return {"id": "stub-alert-%d" % int(time.time() * 1000)}
    if method == "menu.add":
        return (data.get("data") or {}).get("item_id") or "stub-item"
    if method in ("menu.update", "menu.remove", "hooks.add", "hooks.remove", "hooks.add_xposed"):
        return True
    if method == "client.send_text":
        return {"ok": True}
    if method == "analyze.file":
        return {"status": "unavailable", "message": "analyzer is not available in the SDK stub"}
    return None


def host(method, payload=None):
    if payload is None:
        payload = ""
    elif not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False)
    result = _dispatch(str(method), payload)
    if result is None:
        return ""
    return json.dumps(result, ensure_ascii=False)


def invoke(handle, payload=None):
    # In the app the C module forwards to extera_ios._invoke; the fallback only
    # needs to be callable so tests can simulate a host callback.
    if payload is None:
        payload = "{}"
    try:
        import extera_ios

        return extera_ios._invoke(str(handle), payload)
    except Exception:
        traceback.print_exc()
        return "null"


def set_verbose(value):
    global _VERBOSE
    _VERBOSE = bool(value)


def calls():
    return list(_HOST_CALLS)


def reset():
    del _HOST_CALLS[:]
