"""Host-side smoke test for the iOS exteraGram plugin SDK.

Run with:  python tests/test_sdk.py
"""

import json
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "PythonSupport", "sdk")
sys.path.insert(0, SDK)

import _extera_runtime
import compat
import plugin_settings


PLUGIN_SOURCE = '''
from base_plugin import BasePlugin, HookResult, HookStrategy, MenuItemData, MenuItemType
from ui import settings

__id__ = "smoke_test"
__name__ = "Smoke Test"
__description__ = "checks the iOS runtime"
__author__ = "tests"
__version__ = "1.2.3"
__icon__ = "exteraPlugins/1"

class SmokeTest(BasePlugin):
    def on_plugin_load(self):
        self.loaded = True
        self.add_hook("updateNewMessage")

    def create_settings(self):
        return [
            settings.Header("Main"),
            settings.Switch("enabled", "Enable", True),
            settings.Selector("mode", "Mode", 0, ["A", "B"]),
            settings.Input("name", "Name", "x"),
            settings.EditText("note", "Note", multiline=True),
            settings.Text("Open", on_click=lambda view: None),
        ]

    def on_update_hook(self, update_name, account, update):
        update["seen"] = True
        return HookResult(strategy=HookStrategy.MODIFY, update=update)

    def on_send_message_hook(self, account, params):
        params["message"] = (params.get("message") or "") + "!"
        return HookResult(strategy=HookStrategy.MODIFY, params=params)
'''


def main():
    work = tempfile.mkdtemp(prefix="extera-plugin-test-")
    plugins_dir = os.path.join(work, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)
    plugin_path = os.path.join(plugins_dir, "smoke_test.plugin")
    with open(plugin_path, "w", encoding="utf-8") as handle:
        handle.write(PLUGIN_SOURCE)

    print("initialize:", _extera_runtime.initialize(SDK, plugins_dir, work))
    metadata = json.loads(_extera_runtime.parse_metadata(plugin_path))
    print("metadata:", metadata)
    assert metadata["metadata"]["id"] == "smoke_test"

    loaded = json.loads(_extera_runtime.load_plugin("smoke_test", plugin_path))
    print("loaded:", loaded)
    assert loaded["ok"], loaded

    settings_payload = json.loads(_extera_runtime.load_settings("smoke_test"))
    print("settings:", json.dumps(settings_payload, indent=2))
    assert settings_payload["ok"]
    assert [item["type"] for item in settings_payload["settings"]] == [
        "header", "switch", "selector", "input", "edit_text", "text"
    ]

    hook = json.loads(_extera_runtime.call_hook(
        "smoke_test", "on_update_hook",
        json.dumps(["updateNewMessage", 0, {"_": "updateNewMessage", "pts": 1}]),
    ))
    print("hook:", hook)
    assert hook["strategy"] == "MODIFY"
    assert hook["update"]["seen"] is True

    send = json.loads(_extera_runtime.call_hook(
        "smoke_test", "on_send_message_hook",
        json.dumps([0, {"peer": 1, "message": "hi"}]),
    ))
    print("send:", send)
    assert send["params"]["message"] == "hi!"

    info = json.loads(_extera_runtime.plugin_info("smoke_test"))
    assert info["metadata"]["version"] == "1.2.3"

    report = json.loads(_extera_runtime.analyze(plugin_path))
    print("analysis:", json.dumps(report, indent=2)[:2000])
    assert report["analyzer"]["version"]
    rule_ids = {finding["rule"] for finding in report["findings"]}
    assert "hooks.java" in rule_ids or "intercept.requests" in rule_ids or rule_ids

    unloaded = json.loads(_extera_runtime.unload_plugin("smoke_test"))
    assert unloaded["ok"], unloaded

    # Import compatibility: a plugin that imports Java packages must load.
    compat.install()
    from org.telegram.messenger import UserConfig, MessageObject
    from java.util import ArrayList
    from de.robv.android.xposed import XposedBridge
    values = ArrayList()
    values.add(1)
    assert values.size() == 1
    assert UserConfig.__name__ == "org.telegram.messenger.UserConfig"
    print("compat: ok", UserConfig, MessageObject, XposedBridge)

    print("ALL OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
