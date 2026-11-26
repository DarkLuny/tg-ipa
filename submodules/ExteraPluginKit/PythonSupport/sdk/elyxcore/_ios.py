# This is the iOS counterpart of the exteraGram plugins SDK.
#
# ElyxCore's Android code talks to the Kotlin plugin registry
# (`PluginsController`, `Plugin`, preferences).  On iOS the registry lives in
# Python: `ElyxMetadata` carries the same fields and getters, and enabled state
# is stored in `plugin_settings` under the plugin id.
#
# Licensed under the GPL v2 or later, like the rest of this repository.

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import plugin_settings
except Exception:
    plugin_settings = None

try:
    import extera_ios
except Exception:
    extera_ios = None


def _version_parts(value):
    parts = []
    for piece in str(value or "0").split("."):
        digits = "".join(character for character in piece if character.isdigit())
        parts.append(int(digits or 0))
    return parts


def version_at_least(actual, required):
    left = _version_parts(actual)
    right = _version_parts(required)
    length = max(len(left), len(right))
    left += [0] * (length - len(left))
    right += [0] * (length - len(right))
    return left >= right


def plugins_dir():
    value = os.environ.get("EXTERA_ELYX_DIR", "")
    if not value and extera_ios is not None:
        try:
            value = extera_ios.host("paths.dir", kind="plugins") or ""
        except Exception:
            value = ""
    if not value:
        value = os.path.expanduser("~/Documents/plugins")
    path = os.path.join(str(value), "ElyxPlugins")
    os.makedirs(path, exist_ok=True)
    return path


def is_enabled(plugin_id):
    if plugin_settings is not None:
        return bool(plugin_settings.get_setting(plugin_id, "enabled", False))
    return False


def set_enabled(plugin_id, value):
    if plugin_settings is not None:
        plugin_settings.set_setting(plugin_id, "enabled", bool(value))


@dataclass
class ElyxMetadata:
    id: str
    name: str
    description: str = ""
    author: str = "Unknown author"
    version: str = "1.0.0"
    icon: Optional[str] = None
    app_version: Optional[str] = None
    sdk_version: Optional[str] = None
    requirements: List[str] = field(default_factory=list)
    required_plugins: List[str] = field(default_factory=list)
    enabled: bool = False
    error: Optional[str] = None
    engine: str = "elyx-py"

    def getId(self):
        return self.id

    def getName(self):
        return self.name

    def getDescription(self):
        return self.description

    def setDescription(self, value):
        self.description = value or ""

    def getAuthor(self):
        return self.author

    def setAuthor(self, value):
        self.author = value or ""

    def getVersion(self):
        return self.version

    def setVersion(self, value):
        self.version = value or "1.0.0"

    def getIcon(self):
        return self.icon

    def setIcon(self, value):
        self.icon = value

    def getAppVersion(self):
        return self.app_version

    def setAppVersion(self, value):
        self.app_version = value

    def getSdkVersion(self):
        return self.sdk_version

    def setSdkVersion(self, value):
        self.sdk_version = value

    def getRequirements(self):
        return list(self.requirements)

    def setRequirements(self, value):
        self.requirements = list(value or [])

    def getRequiredPlugins(self):
        return list(self.required_plugins)

    def setRequiredPlugins(self, value):
        self.required_plugins = list(value or [])

    def isEnabled(self):
        return self.enabled

    def setEnabled(self, value):
        self.enabled = bool(value)

    def hasError(self):
        return self.error is not None

    def getError(self):
        return self.error

    def setError(self, value):
        self.error = value

    def getEngine(self):
        return self.engine

    def setEngine(self, value):
        self.engine = value


class PluginRegistry:
    def __init__(self):
        self._items = {}

    def containsKey(self, plugin_id):
        return plugin_id in self._items

    def get(self, plugin_id):
        return self._items.get(plugin_id)

    def put(self, plugin_id, value):
        self._items[plugin_id] = value
        return value

    def remove(self, plugin_id):
        return self._items.pop(plugin_id, None)

    def keys(self):
        return list(self._items.keys())

    def values(self):
        return list(self._items.values())

    def items(self):
        return list(self._items.items())

    def clear(self):
        self._items.clear()


plugins = PluginRegistry()


@dataclass
class ElyxValidationResult:
    plugin: Optional[ElyxMetadata]
    error: Optional[str]


class _Preferences:
    def getBoolean(self, key, default=False):
        if key.startswith("plugin_enabled_"):
            return is_enabled(key[len("plugin_enabled_"):])
        return default

    def edit(self):
        return _PreferencesEditor()


class _PreferencesEditor:
    def __init__(self):
        self._values = {}

    def putBoolean(self, key, value):
        self._values[key] = bool(value)
        return self

    def putString(self, key, value):
        self._values[key] = value
        return self

    def apply(self):
        for key, value in self._values.items():
            if key.startswith("plugin_enabled_"):
                set_enabled(key[len("plugin_enabled_"):], value)
        return True


class _Controller:
    @property
    def plugins(self):
        return plugins

    @property
    def preferences(self):
        return _Preferences()

    @property
    def pluginsDir(self):
        from extera_utils.classes import NativeFile

        return NativeFile(plugins_dir())

    def isInitialized(self):
        return True

    def loadPluginSettings(self, plugin_id):
        return None

    def cleanupPlugin(self, plugin_id):
        return None


_instance = _Controller()


class PluginsController:
    @staticmethod
    def getInstance():
        return _instance

    @staticmethod
    def getEngines():
        return {}

    @staticmethod
    def PluginValidationResult(plugin, error):
        return ElyxValidationResult(plugin, error)
