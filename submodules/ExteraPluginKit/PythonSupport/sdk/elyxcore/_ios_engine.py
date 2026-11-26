# This is the iOS counterpart of the exteraGram plugins SDK's `ElyxEngine`.
#
# The Android engine implements the Kotlin `PluginsEngine` interface and talks
# to `PluginsController`.  On iOS the registry lives in Python (`elyxcore._ios`),
# plugins live in `<plugins>/ElyxPlugins/<id>/`, and the engine is driven by
# `_extera_runtime` functions the Swift host calls.
#
# Licensed under the GPL v2 or later, like the rest of this repository.

import importlib
import os
import shutil
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

from android_utils import log as logcat
from base_plugin import BasePlugin
from extera_utils import lifecycle
from elyxcore import _ios
from elyxcore._importer import importer, setup as setup_importer, stop as stop_importer
from elyxcore._plugin import (
    ElyxPlugin,
    ValidationError,
    _clear_local_wheels,
    _install_local_wheels,
)

MAX_ARCHIVE_ENTRIES = 10000
MAX_ARCHIVE_TOTAL = 256 * 1024 * 1024
MAX_ARCHIVE_FILE = 64 * 1024 * 1024


def _safe_members(archive):
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise ValidationError("Archive has too many entries")
    total = 0
    for member in members:
        name = member.filename
        if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
            raise ValidationError("Unsafe path in archive: %s" % name)
        if member.file_size > MAX_ARCHIVE_FILE:
            raise ValidationError("Archive entry is too large: %s" % name)
        total += member.file_size
    if total > MAX_ARCHIVE_TOTAL:
        raise ValidationError("Archive is too large")
    return members


class IOSPluginEngine:
    ID = "elyx-py"
    instance = None

    def __init__(self):
        IOSPluginEngine.instance = self
        self.plugins_instances = {}
        self.inited = False
        self._generation = 0

    @property
    def plugins_dir_path(self):
        return _ios.plugins_dir()

    # -- Lifecycle ------------------------------------------------------------

    def init(self, callback=None, force=False):
        if self.inited and not force:
            self._run(callback)
            return
        setup_importer()
        self.inited = True
        self.loadPlugins(callback)

    def shutdown(self, callback=None):
        self.inited = False
        self.unloadPlugins()
        try:
            stop_importer()
        except Exception:
            logcat("[ERROR] [ElyxPlugin] stop importer: " + traceback.format_exc())
        self._run(callback)

    @staticmethod
    def _run(callback, value=None):
        if callback is None:
            return value
        try:
            if callable(callback):
                return callback(value)
            run = getattr(callback, "run", None)
            if callable(run):
                return run(value)
        except Exception:
            logcat("[ERROR] [ElyxPlugin] callback: " + traceback.format_exc())
        return value

    def _plugin_dir(self, plugin_id):
        return Path(self.plugins_dir_path) / plugin_id

    def plugin_dir(self, plugin_id):
        return self._plugin_dir(plugin_id)

    # -- Discovery ------------------------------------------------------------

    def scan(self):
        root = Path(self.plugins_dir_path)
        root.mkdir(parents=True, exist_ok=True)
        results = []
        for directory in sorted(root.iterdir()):
            if not directory.is_dir():
                continue
            if directory.name in ("archives", "elyx_local_libs"):
                continue
            if not ElyxPlugin.is_plugin_dir(directory):
                continue
            try:
                plugin = ElyxPlugin(str(directory), raise_errors=False)
                metadata = plugin.get_validation_result().plugin
                if metadata is None:
                    continue
                errors = [str(error) for error, _ in plugin.errors]
                if errors:
                    metadata.setError("\n".join(errors))
                    metadata.setEnabled(False)
                else:
                    metadata.setEnabled(_ios.is_enabled(directory.name))
                _ios.plugins.put(directory.name, metadata)
                results.append(metadata)
            except Exception:
                logcat("[ERROR] [ElyxPlugin] Failed to inspect %s: %s"
                       % (directory.name, traceback.format_exc()))
        return results

    def loadPlugins(self, callback=None):
        for metadata in self.scan():
            if metadata.getError():
                continue
            plugin_id = metadata.getId()
            try:
                self.loadPlugin(plugin_id)
            except Exception:
                logcat("[ERROR] [ElyxPlugin] Failed to load %s: %s"
                       % (plugin_id, traceback.format_exc()))
        self._run(callback)

    # -- Load / unload --------------------------------------------------------

    def loadPlugin(self, plugin_id, file_path=None, enable_after_install=None,
                   callback=None, delegate=None, callback_on_ui_thread=True):
        if plugin_id in self.plugins_instances:
            self.unloadPlugin(plugin_id)
        try:
            plugin = ElyxPlugin(str(self._plugin_dir(plugin_id)))
            metainfo = plugin.get_metainfo()
            main_file_path = plugin.structure.main_file_path
            module_name = (
                "ElyxPlugins." + plugin_id + "."
                + ((".".join(main_file_path.split("/")[:-1]) + ".") if "/" in main_file_path else "")
                + main_file_path.split("/")[-1].split(".")[0]
            )

            requirements = metainfo.get("requirements") or []
            if requirements:
                try:
                    import pip_controller

                    pip_controller.install_dependencies(requirements, plugin_id)
                except Exception:
                    logcat("[ERROR] [ElyxWheels] dependencies for %s: %s"
                           % (plugin_id, traceback.format_exc()))
            if plugin.structure.wheels_path:
                try:
                    _install_local_wheels(plugin, plugin_id)
                except Exception:
                    logcat("[ERROR] [ElyxWheels] local wheels for %s: %s"
                           % (plugin_id, traceback.format_exc()))
            else:
                _clear_local_wheels(plugin_id)

            validation = plugin.get_validation_result()
            metadata = validation.plugin
            if plugin.errors:
                error = "\n".join(str(item) for item, _ in plugin.errors)
                metadata.setError(error)
                metadata.setEnabled(False)
                _ios.plugins.put(plugin_id, metadata)
                _ios.set_enabled(plugin_id, False)
                self._run(callback, error)
                return
            metadata.setEnabled(False)
            _ios.plugins.put(plugin_id, metadata)

            importer.invalidate_caches()
            lifecycle.begin(plugin_id)
            try:
                with lifecycle.plugin_context(plugin_id):
                    main_module = importlib.import_module(module_name)
                    plugin_class = None
                    for value in vars(main_module).values():
                        if isinstance(value, type) and issubclass(value, BasePlugin) and value is not BasePlugin:
                            plugin_class = value
                            break
                    if plugin_class is None:
                        raise RuntimeError("plugin class not found in " + module_name)
                    instance = plugin_class()
            except BaseException:
                lifecycle.stop(plugin_id)
                raise

            instance.id = plugin_id
            instance.name = metainfo.get("name", plugin_id)
            instance.description = metainfo.get("description", "")
            instance.author = metainfo.get("author", "")
            instance.version = metainfo.get("version", "1.0.0")
            instance.icon = metainfo.get("icon")
            instance.min_version = metainfo.get("min_version", "")
            instance.enabled = False
            instance.initialized = False
            instance.error_message = None
            plugin_strings = plugin.get_strings()
            if plugin_strings:
                instance.strings = plugin_strings
            self.plugins_instances[plugin_id] = instance

            enabled = bool(enable_after_install) or _ios.is_enabled(plugin_id)
            if enabled:
                self.setPluginEnabled(plugin_id, True, callback,
                                      callback_on_ui_thread=callback_on_ui_thread)
            else:
                self._run(callback)
        except BaseException:
            error = traceback.format_exc()
            logcat("[ERROR] [ElyxPlugin] Failed to load %s: %s" % (plugin_id, error))
            self.unloadPlugin(plugin_id)
            metadata = _ios.plugins.get(plugin_id) or _ios.ElyxMetadata(plugin_id, plugin_id)
            metadata.setError(error)
            metadata.setEnabled(False)
            _ios.plugins.put(plugin_id, metadata)
            _ios.set_enabled(plugin_id, False)
            self._run(callback, error)

    def unloadPlugin(self, plugin_id):
        instance = self.plugins_instances.pop(plugin_id, None)
        lifecycle.stop(plugin_id)
        try:
            if instance is not None:
                instance.enabled = False
                was_initialized = instance.initialized
                instance.initialized = False
                if was_initialized:
                    try:
                        with lifecycle.plugin_context(plugin_id):
                            instance._invoke_plugin_unload()
                    except BaseException:
                        logcat("[ERROR] [ElyxPlugin] unload %s: %s"
                               % (plugin_id, traceback.format_exc()))
            try:
                BasePlugin._cleanup(plugin_id)
            except Exception:
                pass
        finally:
            try:
                importer.unload_plugin(plugin_id)
            except Exception:
                pass
            metadata = _ios.plugins.get(plugin_id)
            if metadata is not None:
                metadata.setEnabled(False)

    def unloadPlugins(self):
        for plugin_id in list(self.plugins_instances.keys()):
            self.unloadPlugin(plugin_id)

    # -- State ----------------------------------------------------------------

    def setPluginEnabled(self, plugin_id, enabled, callback=None, callback_on_ui_thread=True):
        instance = self.plugins_instances.get(plugin_id)
        if enabled and instance is None:
            self.loadPlugin(plugin_id, enable_after_install=True, callback=callback,
                            callback_on_ui_thread=callback_on_ui_thread)
            return
        metadata = _ios.plugins.get(plugin_id)
        if enabled:
            try:
                if instance is None:
                    raise RuntimeError("Plugin %s is not loaded" % plugin_id)
                with lifecycle.plugin_context(plugin_id):
                    instance.on_plugin_load()
                instance.initialized = True
                instance.enabled = True
                instance.error_message = None
                if metadata is not None:
                    metadata.setEnabled(True)
                    metadata.setError(None)
                _ios.set_enabled(plugin_id, True)
                self._run(callback)
            except BaseException:
                error = traceback.format_exc()
                instance.enabled = False
                instance.initialized = False
                instance.error_message = error
                if metadata is not None:
                    metadata.setEnabled(False)
                    metadata.setError(error)
                _ios.set_enabled(plugin_id, False)
                self._run(callback, error)
        else:
            if instance is not None:
                try:
                    with lifecycle.plugin_context(plugin_id):
                        instance._invoke_plugin_unload()
                except BaseException:
                    logcat("[ERROR] [ElyxPlugin] disable %s: %s"
                           % (plugin_id, traceback.format_exc()))
                instance.initialized = False
                instance.enabled = False
            if metadata is not None:
                metadata.setEnabled(False)
            _ios.set_enabled(plugin_id, False)
            try:
                BasePlugin._cleanup(plugin_id)
            except Exception:
                pass
            self._run(callback)

    def deletePlugin(self, plugin_id, callback=None):
        self.unloadPlugin(plugin_id)
        try:
            import pip_controller

            pip_controller.uninstall_dependencies(plugin_id)
        except Exception:
            pass
        _clear_local_wheels(plugin_id)
        directory = self._plugin_dir(plugin_id)
        if directory.exists():
            shutil.rmtree(str(directory), ignore_errors=True)
        try:
            import plugin_settings
            import extera_ios

            plugin_settings.clear_settings(plugin_id)
            extera_ios.host("settings.reload", plugin_id=plugin_id)
        except Exception:
            pass
        _ios.plugins.remove(plugin_id)
        self._run(callback)

    def loadPluginSettings(self, plugin_id):
        instance = self.plugins_instances.get(plugin_id)
        if instance is None or not instance.enabled:
            return None
        try:
            with lifecycle.plugin_context(plugin_id):
                return instance.create_settings()
        except Exception:
            logcat("[ERROR] [ElyxPlugin] settings for %s: %s"
                   % (plugin_id, traceback.format_exc()))
            return None

    # -- Install --------------------------------------------------------------

    def install_archive(self, file_path, password=None, enable=True, visiting=None):
        path = Path(file_path)
        if not path.is_file():
            raise ValidationError("Plugin archive not found")
        with zipfile.ZipFile(path, "r") as archive:
            members = _safe_members(archive)
            plugin = ElyxPlugin(plzip=archive, pwd=password, raise_errors=True)
            metadata = plugin.get_metainfo()
            plugin_id = metadata["id"]

        # Elyx plugins may require other plugins by id and download link. Install
        # the missing ones first, the way Android's install sheet resolves the
        # requirement list, and keep a visiting set so a dependency cycle does
        # not recurse forever.
        visiting = set(visiting or ())
        visiting.add(plugin_id)
        self._install_required(metadata.get("requires") or {}, visiting)

        destination = self._plugin_dir(plugin_id)
        staging = Path(tempfile.mkdtemp(prefix="elyx-install-"))
        try:
            with zipfile.ZipFile(path, "r") as archive:
                if password:
                    archive.setpassword(str(password).encode())
                archive.extractall(staging)
            # Re-validate the extracted directory before replacing the old copy.
            ElyxPlugin(str(staging), raise_errors=True)
            if destination.exists():
                shutil.rmtree(str(destination), ignore_errors=True)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging), str(destination))
        finally:
            if staging.exists():
                shutil.rmtree(str(staging), ignore_errors=True)
        _ios.set_enabled(plugin_id, bool(enable))
        instance = self.loadPlugin(plugin_id)
        return _ios.plugins.get(plugin_id), (instance if enable else None)

    def _install_required(self, requires, visiting):
        for raw_id, link in requires.items():
            plugin_id = str(raw_id)
            required_version = None
            if " " in plugin_id:
                plugin_id, version = plugin_id.split(" ", 1)
                required_version = version.strip().strip("()")
            plugin_id = plugin_id.strip()
            if not plugin_id or plugin_id in visiting:
                continue
            installed = _ios.plugins.get(plugin_id)
            if installed is not None:
                version = getattr(installed, "version", "") or ""
                if not required_version or _ios.version_at_least(version, required_version):
                    continue
            if not isinstance(link, str) or not link.startswith(("http://", "https://")):
                raise ValidationError(
                    "Required plugin %s is missing and has no https download link" % plugin_id
                )
            archive_path = self._download_required(plugin_id, link)
            try:
                visiting.add(plugin_id)
                self.install_archive(archive_path, enable=True, visiting=visiting)
            finally:
                try:
                    os.unlink(archive_path)
                except OSError:
                    pass

    def _download_required(self, plugin_id, link):
        import urllib.request

        try:
            request = urllib.request.Request(
                link, headers={"User-Agent": "ExteraPluginKit/1.0"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(MAX_ARCHIVE_TOTAL + 1)
        except Exception as error:
            raise ValidationError(
                "Required plugin %s could not be downloaded: %s" % (plugin_id, error)
            )
        if len(data) > MAX_ARCHIVE_TOTAL:
            raise ValidationError("Required plugin %s is larger than the archive limit" % plugin_id)
        handle, path = tempfile.mkstemp(prefix="elyx-required-", suffix=".elyx")
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(data)
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return path


engine = None


def setup():
    global engine
    if engine is not None:
        return engine
    engine = IOSPluginEngine()
    engine.init()
    return engine


def stop():
    global engine
    current = engine
    engine = None
    if current is not None:
        current.shutdown()
