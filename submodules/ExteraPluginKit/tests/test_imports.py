"""Imports every SDK module and exercises the Android compatibility surface.

Run with: python tests/test_imports.py
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "PythonSupport", "sdk"))

import _extera_runtime
import android_utils
import base_plugin
import client_utils
import compat
import dev_server
import extera_analyzer
import extera_ios
import file_utils
import hook_utils
import intents
import log_utils
import markdown_utils
import plugin_settings
import ui.alert
import ui.bulletin
import ui.settings
import extera_utils.classes
import extera_utils.get_caller
import extera_utils.iosruntime
import extera_utils.lifecycle
import extera_utils.metadata_parser
import extera_utils.text_formatting


def main():
    compat.install()

    # Android imports that a real plugin does at module level.
    from java.lang import Object, String
    from java.util import ArrayList, HashMap, Arrays
    from org.telegram.messenger import UserConfig, MessageObject, AndroidUtilities
    from org.telegram.tgnet import TLRPC
    from org.telegram.ui.ActionBar import AlertDialog, Theme, BaseFragment
    from de.robv.android.xposed import XposedBridge, XC_MethodHook

    values = ArrayList()
    values.add("x")
    assert values.size() == 1
    assert String("abc") == "abc"
    mapping = HashMap()
    mapping.put("a", 1)
    assert mapping.get("a") == 1
    assert list(Arrays.asList([1, 2])) == [1, 2]

    assert UserConfig.__name__ == "org.telegram.messenger.UserConfig"
    assert MessageObject.__name__ == "org.telegram.messenger.MessageObject"
    assert XposedBridge is not None
    assert XC_MethodHook.MethodHookParam is not None
    assert TLRPC.TL_photo.__name__.endswith("TL_photo")

    # Settings descriptors, including the declarative custom view.
    controls = [
        ui.settings.Switch("a", "A", True),
        ui.settings.Selector("b", "B", 0, ["x", "y"]),
        ui.settings.Input("c", "C", "v"),
        ui.settings.EditText("d", "D"),
        ui.settings.Custom(view={"type": "slider", "min": 0, "max": 10, "value": 3}),
    ]
    with tempfile.TemporaryDirectory() as work:
        plugins = os.path.join(work, "plugins")
        os.makedirs(plugins)
        plugin_settings.init(plugins)
        plugin_settings.set_setting("p", "a", True)
        assert plugin_settings.get_setting("p", "a") is True
        plugin_settings.set_setting("p", "a", False)
        assert plugin_settings.get_setting("p", "a") is False
        settings_path = os.path.join(plugins, "plugin_settings.json")
        assert os.path.exists(settings_path)
        with open(settings_path, encoding="utf-8") as handle:
            assert json.load(handle)["p"]["a"] is False

    # Text entities.
    from extera_utils.text_formatting import parse_text

    parsed = parse_text("<b>Hello</b> <a href='https://x'>link</a>", "html")
    assert parsed["message"] == "Hello link"
    assert {item["type"] for item in parsed["entities"]} == {"bold", "text_link"}

    # Analyzer rules.
    report = extera_analyzer.analyze_source(
        "import socket\n__id__='x'\n__name__='X'\ndef pre_request_hook(self, n, a, r):\n    return r\nexec('bad')\n",
        "x.plugin",
    )
    assert report["max_severity"] == "critical"
    rules = {finding["rule"] for finding in report["findings"]}
    assert "py.dynamic_exec" in rules
    assert "intercepts.requests" in rules

    # Hook param API.
    param = extera_ios._AttrDict({"__param__": True, "id": "p", "args": [], "result": None})
    param.setResult("changed")
    assert param.getResult() == "changed"
    param.setObjectExtra("k", 1)
    assert param.getObjectExtra("k") == 1

    # Module imports that used to fail on Android-only imports.
    assert android_utils.R(lambda: 1).run() == 1
    assert log_utils._split_for_logcat("abc") == ["abc"]

    # The development server really serves the Android JSON protocol on
    # loopback; a ping round-trip proves the socket path, not just the import.
    import socket
    import time

    server = dev_server.DevServer(port=0)
    assert server.start() is True
    for _ in range(100):
        if dev_server.DevServer._is_running and dev_server.DevServer.address()[1]:
            break
        time.sleep(0.02)
    host, port = dev_server.DevServer.address()
    connection = socket.create_connection((host, port), timeout=5)
    connection.sendall(json.dumps({"@": "ping", "#": 7}).encode("utf-8"))
    response = json.loads(connection.recv(4096).decode("utf-8"))
    connection.close()
    assert response == {"#": 7, "pong": True}, response
    assert server.stop() is True

    print("ALL IMPORTS OK")


if __name__ == "__main__":
    main()
