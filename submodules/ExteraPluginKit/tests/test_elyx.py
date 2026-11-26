"""Elyx (`.elyx`) plugin engine parity tests.

Run with: python tests/test_elyx.py
"""

import json
import os
import sys
import tempfile
import traceback
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "PythonSupport", "sdk")
sys.path.insert(0, os.path.join(SDK, "_vendor"))
sys.path.insert(0, SDK)

import compat  # noqa: E402

compat.install()


PLUGIN_SOURCE = """
from base_plugin import BasePlugin, HookResult
from elyx import assets, strings
import helper

class TestPlugin(BasePlugin):
    def on_plugin_load(self):
        self.loaded = True
        self.helper_value = helper.VALUE
        self.asset_value = assets.get("data").content()["answer"]
        self.string_value = strings.get("hello")

    def on_plugin_unload(self):
        self.unloaded = True

    def on_update_hook(self, name, account, update):
        self.updates = getattr(self, "updates", [])
        self.updates.append((name, account))
        return HookResult()

    def create_settings(self):
        return []
"""


def write_plugin(directory, plugin_id, name="Test Elyx"):
    os.makedirs(os.path.join(directory, "assets"), exist_ok=True)
    os.makedirs(os.path.join(directory, "strings"), exist_ok=True)
    with open(os.path.join(directory, "metainfo.yaml"), "w", encoding="utf-8") as handle:
        handle.write(
            "id: %s\nname: %s\nversion: 1.2.3\ndescription: A test plugin\n"
            "author: Tester\n" % (plugin_id, name)
        )
    with open(os.path.join(directory, "refmap.yaml"), "w", encoding="utf-8") as handle:
        handle.write("main: main.py\nassets: assets\nstrings: strings\n")
    with open(os.path.join(directory, "main.py"), "w", encoding="utf-8") as handle:
        handle.write(PLUGIN_SOURCE)
    with open(os.path.join(directory, "helper.py"), "w", encoding="utf-8") as handle:
        handle.write("VALUE = 42\n")
    with open(os.path.join(directory, "assets", "data.json"), "w", encoding="utf-8") as handle:
        handle.write('{"answer": 42}')
    with open(os.path.join(directory, "strings", "strings_en.json"), "w", encoding="utf-8") as handle:
        json.dump({"hello": "Hello"}, handle)


def test_parser_and_facade():
    from elyxcore._plugin import ElyxPlugin

    root = tempfile.mkdtemp(prefix="elyx-parser-")
    directory = os.path.join(root, "test_elyx")
    write_plugin(directory, "test_elyx")

    plugin = ElyxPlugin(directory, raise_errors=True)
    metadata = plugin.get_metainfo()
    assert metadata["id"] == "test_elyx", metadata
    assert metadata["name"] == "Test Elyx", metadata
    assert metadata["version"] == "1.2.3", metadata
    assert plugin.get_strings()["en"]["hello"] == "Hello"
    assert plugin.structure.main_file_path == "main.py"
    assert plugin.validation_result.error is None

    import elyx

    assets = elyx.Assets(os.path.join(directory, "assets"))
    assert assets.get("data").content()["answer"] == 42
    assert elyx.Strings({"en": {"hello": "Hello"}}).get("hello") == "Hello"
    assert elyx.mvel_execute("a + b", {"a": 1, "b": 2}) == 3


def test_archive_and_engine():
    root = tempfile.mkdtemp(prefix="elyx-engine-")
    os.environ["EXTERA_ELYX_DIR"] = root
    import plugin_settings

    plugin_settings.init(root)
    import _extera_runtime

    _extera_runtime.initialize(SDK, root, root)
    setup = json.loads(_extera_runtime.elyx_setup())
    assert setup["ok"], setup

    archive = os.path.join(root, "sample.elyx")
    staging = tempfile.mkdtemp(prefix="elyx-archive-")
    source = os.path.join(staging, "sample_elyx")
    write_plugin(source, "sample_elyx", "Sample Elyx")
    with zipfile.ZipFile(archive, "w") as handle:
        for base, _dirs, files in os.walk(source):
            for name in files:
                path = os.path.join(base, name)
                handle.write(path, os.path.relpath(path, source))

    installed = json.loads(_extera_runtime.elyx_install_archive(archive))
    assert installed["ok"], installed
    inspected = json.loads(_extera_runtime.elyx_inspect_archive(archive))
    assert inspected["ok"] is True, inspected
    assert inspected["metadata"]["id"] == "sample_elyx", inspected
    assert inspected["main"] == "main.py", inspected
    assert inspected["required_plugins"] == [], inspected
    assert installed["plugin_id"] == "sample_elyx", installed
    extracted = os.path.join(root, "ElyxPlugins", "sample_elyx")
    assert os.path.isdir(os.path.join(extracted, "assets")), os.listdir(extracted)

    enabled = json.loads(_extera_runtime.elyx_set_enabled("sample_elyx", True))
    assert enabled["ok"], enabled
    assert enabled["plugin"]["enabled"] is True

    from elyxcore import _ios_engine

    instance = _ios_engine.engine.plugins_instances.get("sample_elyx")
    assert instance is not None
    assert getattr(instance, "loaded", False) is True
    assert getattr(instance, "helper_value", None) == 42
    assert getattr(instance, "asset_value", None) == 42
    assert getattr(instance, "string_value", None) == "Hello"
    assert json.loads(_extera_runtime.elyx_app_event("sample_elyx", "app_resume")) is True
    assert json.loads(_extera_runtime.elyx_settings("sample_elyx"))["ok"] is True

    exported = json.loads(_extera_runtime.elyx_export_archive("sample_elyx"))
    assert exported["ok"], exported
    assert os.path.isfile(exported["path"]), exported
    with zipfile.ZipFile(exported["path"]) as archive:
        assert "metainfo.yaml" in archive.namelist(), archive.namelist()

    malicious = os.path.join(root, "malicious.elyx")
    with zipfile.ZipFile(malicious, "w") as handle:
        handle.writestr("metainfo.yaml", "id: malicious\nname: Malicious\nversion: 1.0.0\n")
        handle.writestr("main.py", "import os\nexec(open('/tmp/payload').read())\n")
    analysis = json.loads(_extera_runtime.analyze_archive(malicious))
    assert analysis["artifacts"][0]["name"] == "malicious.elyx", analysis
    assert any(
        item["rule"].startswith("py.dynamic_exec") or item["rule"].startswith("py.native")
        for item in analysis["findings"]
    ) or analysis["max_severity"] not in ("none", None), analysis

    # Elyx instances are not in `_PLUGINS`; the dispatcher must still find them.
    hook = json.loads(_extera_runtime.call_hook(
        "sample_elyx", "on_update_hook",
        json.dumps(["updateNewMessage", 1, {"_": "updateNewMessage"}]),
    ))
    assert hook["strategy"] == "DEFAULT", hook
    assert instance.updates[-1][0] == "updateNewMessage"
    assert _extera_runtime.is_loaded("sample_elyx") is True
    assert json.loads(_extera_runtime.plugin_info("sample_elyx"))["loaded"] is True
    assert _extera_runtime.call_lifecycle(
        "sample_elyx", "on_app_event", json.dumps("app_resume")) is not None

    # Elyx dev-server commands used by the IDE plugin.
    from elyxcore._dev_server import ElyxDevServer
    from elyxcore._plugin import ElyxPlugin

    ElyxDevServer.setup()
    assert ElyxDevServer._patched is True
    ping = {}
    ElyxDevServer._handle_elyx_ping(None, lambda value: ping.update(value))
    assert ping == {"pong": True}

    plugins_response = {}
    ElyxDevServer._handle_get_elyx_plugins(None, lambda value: plugins_response.update(value))
    assert "sample_elyx" in plugins_response, plugins_response

    plugin = ElyxPlugin.instances_by_id.get("sample_elyx")
    if plugin is not None and plugin.dir_path:
        path = os.path.join(plugin.dir_path, "metainfo.yaml")
        compare = {}
        ElyxDevServer._handle_elyx_compare_folder(
            {
                "plugin_id": "sample_elyx",
                "data": {"metainfo.yaml": ElyxDevServer.get_file_hash(path)},
            },
            lambda value: compare.update(value),
        )
        assert "metainfo.yaml" not in compare.get("created", []), compare
        assert "metainfo.yaml" not in compare.get("modified", []), compare

    ElyxDevServer.teardown()
    assert ElyxDevServer._patched is False

    disabled = json.loads(_extera_runtime.elyx_set_enabled("sample_elyx", False))
    assert disabled["ok"], disabled
    assert getattr(instance, "unloaded", False) is True

    # A required plugin listed with an https link is downloaded and installed
    # before the dependent plugin is registered.
    import http.server
    import socketserver
    import threading

    serving = tempfile.mkdtemp(prefix="elyx-required-serve-")
    required_source = os.path.join(serving, "required_dep")
    write_plugin(required_source, "required_dep", "Required Dep")
    required_archive = os.path.join(serving, "required_dep.elyx")
    with zipfile.ZipFile(required_archive, "w") as handle:
        for base, _dirs, files in os.walk(required_source):
            for name in files:
                full = os.path.join(base, name)
                handle.write(full, os.path.relpath(full, required_source))

    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    handler = lambda *args, **kwargs: _QuietHandler(  # noqa: E731
        *args, directory=serving, **kwargs
    )
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        dependent = os.path.join(serving, "needs_dep")
        write_plugin(dependent, "needs_dep", "Needs Dep")
        metainfo_path = os.path.join(dependent, "metainfo.yaml")
        with open(metainfo_path, "w", encoding="utf-8") as handle:
            handle.write(
                "id: needs_dep\nname: Needs Dep\nversion: 1.0.0\n"
                "requires:\n  required_dep: http://127.0.0.1:%d/required_dep.elyx\n"
                % server.server_address[1]
            )
        dependent_archive = os.path.join(serving, "needs_dep.elyx")
        with zipfile.ZipFile(dependent_archive, "w") as handle:
            for base, _dirs, files in os.walk(dependent):
                for name in files:
                    full = os.path.join(base, name)
                    handle.write(full, os.path.relpath(full, dependent))
        installed_dependent = json.loads(_extera_runtime.elyx_install_archive(dependent_archive))
        assert installed_dependent["ok"], installed_dependent
        assert "required_dep" in _ios_engine.engine.plugins_instances, installed_dependent
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    # A plugin that requires a missing plugin is listed with its error and is
    # not loaded.
    required_dir = os.path.join(root, "ElyxPlugins", "requires_demo")
    os.makedirs(required_dir, exist_ok=True)
    with open(os.path.join(required_dir, "metainfo.yaml"), "w", encoding="utf-8") as handle:
        handle.write(
            "id: requires_demo\nname: Requires Demo\nversion: 1.0.0\n"
            "requires:\n  missing_plugin: https://example.com/missing.plugin\n"
        )
    with open(os.path.join(required_dir, "refmap.yaml"), "w", encoding="utf-8") as handle:
        handle.write("main: main.py\n")
    with open(os.path.join(required_dir, "main.py"), "w", encoding="utf-8") as handle:
        handle.write("from base_plugin import BasePlugin\n\nclass RequiredPlugin(BasePlugin):\n    pass\n")
    scan = json.loads(_extera_runtime.elyx_scan())
    requires = next((item for item in scan["plugins"] if item["id"] == "requires_demo"), None)
    assert requires is not None, scan
    assert requires["required_plugins"], requires
    assert "missing_plugin" in (requires["error"] or ""), requires
    assert "requires_demo" not in _ios_engine.engine.plugins_instances
    enabled_required = json.loads(_extera_runtime.elyx_set_enabled("requires_demo", True))
    assert enabled_required["ok"] is False, enabled_required
    assert json.loads(_extera_runtime.elyx_delete("requires_demo"))["ok"] is True

    deleted = json.loads(_extera_runtime.elyx_delete("sample_elyx"))
    assert deleted["ok"], deleted
    assert not os.path.exists(extracted)


def test_quick_start_yaml_package():
    root = tempfile.mkdtemp(prefix="elyx-quick-")
    os.environ["EXTERA_ELYX_DIR"] = root
    import plugin_settings

    plugin_settings.init(root)
    import _extera_runtime

    _extera_runtime.initialize(SDK, root, root)

    project = os.path.join(root, "elyx_hello")
    os.makedirs(os.path.join(project, "src"))
    os.makedirs(os.path.join(project, "assets"))
    os.makedirs(os.path.join(project, "strings"))
    with open(os.path.join(project, "refmap.yml"), "w", encoding="utf-8") as handle:
        handle.write(
            "metainfo: metainfo.yml\nmain: main.py\nassets: assets\nstrings: strings\n"
        )
    with open(os.path.join(project, "metainfo.yml"), "w", encoding="utf-8") as handle:
        handle.write(
            "id: elyx_hello\n"
            "name: Elyx Hello\n"
            "description: \"{plugin_description}\"\n"
            "author: Tester\n"
            "version: \"1.0.0\"\n"
            "icon: exteraPlugins/1\n"
            "app_version: \">=12.5.1\"\n"
            "sdk_version: \">=1.4.5.3\"\n"
        )
    with open(os.path.join(project, "main.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "from typing import Any, List\n"
            "from base_plugin import BasePlugin\n"
            "from elyx import assets, settings, strings\n"
            "from src.greeting import build_greeting\n"
            "from ui.settings import Header, Input, Text\n"
            "\n"
            "class ElyxHelloPlugin(BasePlugin):\n"
            "    def on_plugin_load(self):\n"
            "        self.loaded = True\n"
            "        self.asset_path = assets.wave.path_str\n"
            "\n"
            "    def create_settings(self) -> List[Any]:\n"
            "        name = settings.get('name', 'Alice')\n"
            "        return [\n"
            "            Header(text=strings('settings_title')),\n"
            "            Input(key='name', text=strings('name_label'), subtext=strings('name_hint'), default='Alice', icon='msg_edit'),\n"
            "            Text(text=build_greeting(name), subtext='generated', icon='msg_info'),\n"
            "        ]\n"
        )
    with open(os.path.join(project, "src", "__init__.py"), "w", encoding="utf-8") as handle:
        handle.write("")
    with open(os.path.join(project, "src", "greeting.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "from elyx import strings\n"
            "\n"
            "def build_greeting(name: str) -> str:\n"
            "    return strings('greeting', name=name)\n"
        )
    with open(os.path.join(project, "assets", "wave.svg"), "w", encoding="utf-8") as handle:
        handle.write(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path fill="#4A90E2" d="M7 11V4a1 1 0 0 1 2 0v5h1V3a1 1 0 0 1 2 0v6h1V4a1 1 0 0 1 2 0v6h1V6a1 1 0 0 1 2 0v7c0 5-3 8-8 8s-7-3-7-7v-3a2 2 0 0 1 4 0Z"/>'
            "</svg>"
        )
    with open(
        os.path.join(project, "strings", "strings_en.yml"), "w", encoding="utf-8"
    ) as handle:
        handle.write(
            "plugin_description: A small structured Elyx plugin\n"
            "loaded: Elyx Hello loaded\n"
            "greeting: \"Hello, {name}!\"\n"
            "settings_title: Greeting\n"
            "name_label: Name\n"
            "name_hint: Who should be greeted?\n"
        )
    with open(
        os.path.join(project, "strings", "strings_ru.yml"), "w", encoding="utf-8"
    ) as handle:
        handle.write(
            "plugin_description: Небольшой структурированный плагин Elyx\n"
            "loaded: Elyx Hello загружен\n"
            "greeting: \"Привет, {name}!\"\n"
            "settings_title: Приветствие\n"
            "name_label: Имя\n"
            "name_hint: Кого нужно поприветствовать?\n"
        )

    archive = os.path.join(root, "elyx_hello.elyx")
    with zipfile.ZipFile(archive, "w") as handle:
        for base, _dirs, files in os.walk(project):
            for name in files:
                path = os.path.join(base, name)
                handle.write(path, os.path.relpath(path, project))

    installed = json.loads(_extera_runtime.elyx_install_archive(archive))
    assert installed["ok"], installed
    assert installed["plugin_id"] == "elyx_hello"
    inspected = json.loads(_extera_runtime.elyx_inspect_archive(archive))
    assert inspected["ok"], inspected
    assert inspected["metadata"]["id"] == "elyx_hello"
    assert inspected["main"] == "main.py"

    enabled = json.loads(_extera_runtime.elyx_set_enabled("elyx_hello", True))
    assert enabled["ok"], enabled
    from elyxcore import _ios_engine

    instance = _ios_engine.engine.plugins_instances.get("elyx_hello")
    assert instance is not None
    assert getattr(instance, "loaded", False) is True
    assert getattr(instance, "asset_path", None)
    settings = json.loads(_extera_runtime.elyx_settings("elyx_hello"))
    assert settings["ok"], settings
    assert len(settings["settings"]) == 3, settings
    assert json.loads(_extera_runtime.elyx_app_event("elyx_hello", "app_resume")) is True
    assert json.loads(_extera_runtime.elyx_delete("elyx_hello"))["ok"] is True

    eaf = os.path.join(root, "elyx_hello.eaf")
    with open(archive, "rb") as source, open(eaf, "wb") as target:
        target.write(source.read())
    installed_eaf = json.loads(_extera_runtime.elyx_install_archive(eaf))
    assert installed_eaf["ok"], installed_eaf
    assert installed_eaf["plugin_id"] == "elyx_hello"
    assert json.loads(_extera_runtime.elyx_set_enabled("elyx_hello", True))["ok"] is True
    assert json.loads(_extera_runtime.elyx_delete("elyx_hello"))["ok"] is True


def main():
    test_parser_and_facade()
    test_archive_and_engine()
    test_quick_start_yaml_package()
    print("ALL ELYX OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
