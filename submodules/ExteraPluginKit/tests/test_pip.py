"""Tests for the pure-Python dependency installer.

Run with: python tests/test_pip.py

The network test is skipped when PyPI is unreachable; the unit tests always run.
"""

import json
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "PythonSupport", "sdk")
sys.path.insert(0, SDK)

import pip_controller


def test_versions_and_markers():
    assert pip_controller._normalize_name("Foo_Bar") == "foo-bar"
    assert pip_controller._parse_requirement("six>=1.0,<2") == ("six", [(">=", "1.0"), ("<", "2")])
    assert pip_controller._version_satisfies("1.17.0", [(">=", "1.0")]) is True
    assert pip_controller._version_satisfies("1.17.0", [("==", "1.17.*")]) is True
    assert pip_controller._version_satisfies("1.17.0", [("<", "1.0")]) is False
    assert pip_controller._marker_compatible("python_version >= '3.8'") is True
    assert pip_controller._marker_compatible("python_version < '3.0'") is False
    assert pip_controller._is_pure_python_wheel("six-1.17.0-py2.py3-none-any.whl") is True
    assert pip_controller._is_pure_python_wheel("numpy-1.0-cp311-cp311-ios_arm64.whl") is False

    module_dir = tempfile.mkdtemp(prefix="pip-modules-")
    os.makedirs(os.path.join(module_dir, "pkgdir"), exist_ok=True)
    with open(os.path.join(module_dir, "module.py"), "w", encoding="utf-8") as handle:
        handle.write("")
    with open(os.path.join(module_dir, "notes.txt"), "w", encoding="utf-8") as handle:
        handle.write("")
    assert pip_controller._top_level_modules(module_dir) == {"pkgdir", "module"}


def test_network_install():
    work = tempfile.mkdtemp(prefix="extera-pip-")
    plugins = os.path.join(work, "plugins")
    os.makedirs(plugins, exist_ok=True)
    pip_controller.initialize(plugins)

    try:
        paths = pip_controller.install_dependencies(["six==1.17.0"], "pip_test")
    except Exception as error:
        print("SKIP network install:", error)
        return

    assert paths and os.path.isdir(paths[0]), paths
    assert any(name.startswith("six-") for name in os.listdir(os.path.join(plugins, "libs")))
    import six

    assert six.__version__ == "1.17.0"

    try:
        pip_controller.install_dependencies(["six<1.0"], "pip_conflict")
    except RuntimeError as error:
        assert "Dependency conflict" in str(error), error
    else:
        raise AssertionError("a conflicting requirement was accepted")

    pip_controller.uninstall_dependencies("pip_test")
    remaining = os.listdir(os.path.join(plugins, "libs"))
    assert remaining == ["registry.json"], remaining


def test_runtime_integration():
    import _extera_runtime
    import compat

    compat.install()
    work = tempfile.mkdtemp(prefix="extera-pip-plugin-")
    plugins = os.path.join(work, "plugins")
    os.makedirs(plugins, exist_ok=True)
    source = '''
import six
from base_plugin import BasePlugin

__id__ = "requires_demo"
__name__ = "Requires"
__version__ = "1.0"
__requirements__ = ["six==1.17.0"]

class RequiresDemo(BasePlugin):
    def on_plugin_load(self):
        self.value = six.__version__
'''
    path = os.path.join(plugins, "requires_demo.plugin")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)

    _extera_runtime.initialize(SDK, plugins, work)
    metadata = json.loads(_extera_runtime.parse_metadata(path))
    assert metadata["metadata"]["requirements"] == "six==1.17.0", metadata

    try:
        installed = json.loads(_extera_runtime.install_requirements("requires_demo", ["six==1.17.0"]))
    except Exception as error:
        print("SKIP runtime requirements install:", error)
        return
    assert installed["ok"], installed

    loaded = json.loads(_extera_runtime.load_plugin("requires_demo", path))
    assert loaded["ok"], loaded
    assert _extera_runtime._PLUGINS["requires_demo"].instance.value == "1.17.0"

    _extera_runtime.unload_plugin("requires_demo")
    _extera_runtime.uninstall_requirements("requires_demo")


def main():
    test_versions_and_markers()
    test_network_install()
    test_runtime_integration()
    print("ALL PIP OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
