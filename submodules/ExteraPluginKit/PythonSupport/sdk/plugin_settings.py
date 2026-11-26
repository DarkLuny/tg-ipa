# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Plugin settings live in `plugin_settings.json` next to the installed plugins.
# The file format and the public functions are identical to the Android SDK, so
# a setting written by exteraGram can be imported on iOS and back.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import copy
import json
import os
import tempfile
import threading
import traceback

from log_utils import log

_settings_cache = {}
_settings_file_path = None
_lock = threading.RLock()
_MISSING = object()


def init(plugins_dir_path, all_shared_prefs=None):
    """Initialises the store.

    `all_shared_prefs` exists for source compatibility with the Android SDK;
    on iOS there are no SharedPreferences, so a mapping is accepted and used
    only when no JSON file exists yet.
    """
    global _settings_file_path, _settings_cache
    _settings_file_path = os.path.join(plugins_dir_path, "plugin_settings.json")

    with _lock:
        if os.path.exists(_settings_file_path):
            _load_settings_from_file()
        elif all_shared_prefs:
            _settings_cache = _migrate(all_shared_prefs)
            _save_settings_to_file()
    return []


def _migrate(source):
    migrated = {}
    try:
        items = source.items() if hasattr(source, "items") else source
        for key, value in items:
            if not key.startswith("plugin_setting_"):
                continue
            parts = key[len("plugin_setting_"):].split("_", 1)
            if len(parts) != 2:
                continue
            plugin_id, setting_key = parts
            migrated.setdefault(plugin_id, {})[setting_key] = value
    except Exception:
        log("Error migrating plugin settings: %s" % traceback.format_exc())
    return migrated


def _load_settings_from_file():
    global _settings_cache
    with _lock:
        if _settings_file_path and os.path.exists(_settings_file_path):
            try:
                with open(_settings_file_path, "r", encoding="utf-8") as handle:
                    _settings_cache = json.load(handle)
            except Exception:
                log("Error loading plugin settings from JSON: %s" % traceback.format_exc())
                _settings_cache = {}


def _save_settings_to_file():
    with _lock:
        if not _settings_file_path:
            return False

        temp_path = None
        try:
            settings_dir = os.path.dirname(_settings_file_path)
            if settings_dir and not os.path.isdir(settings_dir):
                os.makedirs(settings_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=settings_dir or None,
                prefix=".%s." % os.path.basename(_settings_file_path),
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = handle.name
                json.dump(_settings_cache, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, _settings_file_path)
            temp_path = None
            return True
        except Exception:
            log("Error saving plugin settings to JSON: %s" % traceback.format_exc())
            return False
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def get_setting(plugin_id, key, default=None):
    with _lock:
        plugin_settings = _settings_cache.get(plugin_id, {})
        if key not in plugin_settings:
            return default
        return copy.deepcopy(plugin_settings[key])


def _restore_plugin_settings(plugin_id, previous_settings):
    if previous_settings is _MISSING:
        _settings_cache.pop(plugin_id, None)
    else:
        _settings_cache[plugin_id] = previous_settings


def set_setting(plugin_id, key, value):
    with _lock:
        previous = _settings_cache.get(plugin_id, _MISSING)
        updated = {} if previous is _MISSING else dict(previous)
        updated[key] = copy.deepcopy(value)
        _settings_cache[plugin_id] = updated
        if not _save_settings_to_file():
            _restore_plugin_settings(plugin_id, previous)


def clear_settings(plugin_id):
    with _lock:
        previous = _settings_cache.pop(plugin_id, _MISSING)
        if previous is not _MISSING and not _save_settings_to_file():
            _restore_plugin_settings(plugin_id, previous)


def get_all_settings(plugin_id):
    with _lock:
        return copy.deepcopy(_settings_cache.get(plugin_id, {}))


def set_all_settings(plugin_id, settings):
    with _lock:
        previous = _settings_cache.get(plugin_id, _MISSING)
        _settings_cache[plugin_id] = copy.deepcopy(settings)
        if not _save_settings_to_file():
            _restore_plugin_settings(plugin_id, previous)


def prune(plugin_ids):
    """Drops settings of plugins that no longer exist.

    Android migrates settings out of SharedPreferences at startup; keeping only
    installed ids prevents a deleted plugin's values from coming back after a
    reinstall with the same id.
    """
    keep = set(str(item) for item in (plugin_ids or ()))
    with _lock:
        removed = [key for key in _settings_cache if key not in keep]
        if not removed:
            return []
        previous = {}
        for key in removed:
            previous[key] = _settings_cache.pop(key)
        if not _save_settings_to_file():
            _settings_cache.update(previous)
            return []
        return removed


def reload():
    with _lock:
        _load_settings_from_file()
