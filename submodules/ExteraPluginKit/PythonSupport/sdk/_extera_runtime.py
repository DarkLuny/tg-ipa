# This is the iOS counterpart of the exteraGram plugins SDK.
#
# `_extera_runtime` is the object the C bridge talks to.  It owns the mapping
# between a plugin id and its Python instance, turns the JSON arguments the
# Swift host sends into Python objects, calls the plugin's hooks and serialises
# what comes back.  Keeping this layer in Python means the Swift side never
# manipulates PyObject and the whole plugin protocol can be tested on a Mac or
# on Windows with the SDK stub.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import dataclasses
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import threading
import traceback

import _sdk_version
import compat
import extera_ios
import message_fields
import pip_controller
import plugin_settings


_LOCK = threading.RLock()
_PLUGINS = {}
_LOAD_ORDER = []
_PLUGINS_PATH = None
_SETTINGS_HANDLES = {}

_RUNTIME_VERSION = "1.0"


class AttrDict(dict):
    """A dict whose keys are also readable as attributes.

    Telegram request/update objects arrive as JSON; plugin code written for
    Android reads `request.peer` and writes `result.request = request`.  This
    keeps both styles working without pretending to be a real TL object.
    """

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            pass
        # Android's `MessageObject.messageOwner` is the underlying TLRPC.Message;
        # a hook payload is that dictionary itself.
        if name == "messageOwner":
            return self
        method = _PAYLOAD_METHODS.get(name)
        if method is not None:
            return lambda *args, **kwargs: method(self, *args, **kwargs)
        # A method the plugin expects on a TL object but this payload does not
        # carry (a media-only field, another API layer) answers the Java default
        # instead of aborting the whole hook with AttributeError.
        if name[:2] == "is" and name[2:3].isupper():
            return lambda *args, **kwargs: False
        if name[:3] == "can" and name[3:4].isupper():
            return lambda *args, **kwargs: False
        if name[:3] == "get" and name[3:4].isupper():
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


def _payload_first(value, *names):
    for name in names:
        item = value.get(name)
        if item is not None:
            return item
    return None


def _payload_dialog_id(value):
    direct = _payload_first(value, "dialog_id", "peer_id")
    if direct is not None:
        return direct
    peer = value.get("peer")
    if isinstance(peer, dict):
        for key, negative in (("user_id", False), ("chat_id", True), ("channel_id", True)):
            identifier = peer.get(key)
            if identifier:
                identifier = int(identifier)
                return -identifier if negative else identifier
    owner = value.get("messageOwner")
    if isinstance(owner, dict):
        return _payload_dialog_id(owner)
    return 0


def _payload_id(value):
    result = _payload_first(value, "id", "message_id")
    if result is None:
        owner = value.get("messageOwner")
        if isinstance(owner, dict):
            result = _payload_first(owner, "id")
    return result or 0


def _payload_from_id(value):
    result = _payload_first(value, "from_id", "sender_id", "from")
    if result is None:
        owner = value.get("messageOwner")
        if isinstance(owner, dict):
            result = _payload_first(owner, "from_id", "from")
    return result or 0


def _payload_is_out(value):
    return bool(_payload_first(value, "out", "is_out"))


def _payload_text(value):
    return _payload_first(value, "message", "text", "caption")


def _payload_document_name(value):
    document = value.get("document")
    if isinstance(document, dict):
        name = document.get("file_name") or document.get("name")
        if name:
            return name
    return value.get("file_name")


def _payload_reply_id(value):
    reply = value.get("reply_to")
    if isinstance(reply, dict):
        return reply.get("reply_to_msg_id") or reply.get("reply_to_id") or 0
    return value.get("reply_to_msg_id") or value.get("reply_to") or 0


_PAYLOAD_METHODS = {
    "getDialogId": _payload_dialog_id,
    "getPeerId": _payload_dialog_id,
    "getId": _payload_id,
    "getFromId": _payload_from_id,
    "getSenderId": _payload_from_id,
    "isOut": _payload_is_out,
    "isOutOwner": _payload_is_out,
    "getMessageText": _payload_text,
    "getDocument": lambda value: value.get("document"),
    "getDocumentName": _payload_document_name,
    "getPhoto": lambda value: value.get("photo"),
    "getMedia": lambda value: value.get("media"),
    "isMediaEmpty": lambda value: value.get("media") is None,
    "isUnread": lambda value: bool(_payload_first(value, "unread", "is_unread")),
    "getDate": lambda value: _payload_first(value, "date") or 0,
    "getRealDate": lambda value: _payload_first(value, "date") or 0,
    "isForwarded": lambda value: value.get("fwd_from") is not None,
    "isReply": lambda value: value.get("reply_to") is not None or value.get("reply_to_msg_id") is not None,
    "getReplyMsgId": _payload_reply_id,
    "isSending": lambda value: bool(_payload_first(value, "sending", "is_sending")),
    "isEditingMessage": lambda value: bool(_payload_first(value, "editing", "is_editing")),
    "isDeleted": lambda value: bool(_payload_first(value, "deleted", "is_deleted")),
    "getMessageOwner": lambda value: value,
    "isVoice": message_fields.is_voice,
    "isMusic": message_fields.is_music,
    "isVideo": message_fields.is_video,
    "isRoundVideo": message_fields.is_round_video,
    "isGif": message_fields.is_gif,
    "isSticker": message_fields.is_sticker,
    "isPhoto": message_fields.is_photo,
    "isDocument": message_fields.is_document,
    "hasPhoto": message_fields.has_photo,
    "hasDocument": message_fields.has_document,
    "getMediaDuration": message_fields.media_duration,
    "getFileName": message_fields.file_name,
    "getFileSize": message_fields.file_size,
    "canForwardMessage": lambda value: not bool(_payload_first(value, "noforwards", "no_forwards")),
    "canEditMessage": lambda value: not bool(_payload_first(value, "edit_hide", "edit_hidden")),
    "canDeleteMessage": lambda value: not bool(_payload_first(value, "noforwards", "no_forwards")),
    "isScheduled": lambda value: bool(_payload_first(value, "scheduled", "is_scheduled")),
    "isSponsored": lambda value: bool(_payload_first(value, "sponsored", "is_sponsored")),
    "isSecret": lambda value: bool(_payload_first(value, "secret", "is_secret")),
    "getApproximateHeight": lambda value: 0,
}


def _decode(payload, default=None):
    if payload is None or payload == "":
        return default
    if isinstance(payload, (dict, list)):
        return _wrap(payload)
    try:
        return _wrap(json.loads(payload, object_hook=AttrDict))
    except Exception:
        return default


def _wrap(value):
    if isinstance(value, dict) and not isinstance(value, AttrDict):
        return AttrDict({key: _wrap(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def _encode(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=_default)
    except Exception:
        return "null"


def _default(value):
    if hasattr(value, "to_native"):
        return value.to_native()
    if dataclasses.is_dataclass(value):
        return _dataclass_to_dict(value)
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return {key: item for key, item in value.__dict__.items() if not key.startswith("_")}
    return str(value)


def _dataclass_to_dict(value):
    result = {}
    for field in dataclasses.fields(value):
        item = getattr(value, field.name)
        if field.name in ("before_filters", "after_filters"):
            continue
        if callable(item):
            result[field.name] = extera_ios.retain(item)
        elif dataclasses.is_dataclass(item):
            result[field.name] = _dataclass_to_dict(item)
        elif hasattr(item, "value") and type(item).__name__ == "Enum":
            result[field.name] = item.value
        else:
            result[field.name] = item
    return result


# ---------------------------------------------------------------------------
# Startup


def initialize(sdk_path, plugins_path, files_path=None):
    """Called once by `PluginPython.c` after the interpreter starts."""
    global _PLUGINS_PATH
    _PLUGINS_PATH = plugins_path
    # Pure-Python packages the SDK itself needs (PyYAML, packaging, a requests
    # shim).  They are not plugin dependencies and must not be installed into
    # every plugin.
    vendor_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor")
    if os.path.isdir(vendor_path) and vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)
    compat.install()
    paths = [sdk_path, plugins_path]
    if files_path:
        paths.append(files_path)
    for path in reversed([item for item in paths if item]):
        if path not in sys.path:
            sys.path.insert(0, path)
    plugin_settings.init(plugins_path)
    try:
        pip_controller.initialize(plugins_path)
    except Exception:
        extera_ios.log("could not initialize the dependency registry: %s" % traceback.format_exc())
    return _encode({
        "version": _sdk_version.__version__,
        "app_version": extera_ios.app_version(),
        "sdk_path": sdk_path,
        "plugins_path": plugins_path,
    })


def parse_metadata(path):
    from extera_utils.metadata_parser import get_metadata

    try:
        return _encode({"ok": True, "metadata": get_metadata(path)})
    except Exception as error:
        return _encode({"ok": False, "error": str(error)})


# ---------------------------------------------------------------------------
# Plugin instances


class PluginEntry:
    __slots__ = ("plugin_id", "path", "module", "instance", "metadata", "error",
                 "enabled", "index")

    def __init__(self, plugin_id, path):
        self.plugin_id = plugin_id
        self.path = path
        self.module = None
        self.instance = None
        self.metadata = {}
        self.error = None
        self.enabled = False
        self.index = 0


def _module_name(plugin_id):
    return "extera_plugin_" + "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in plugin_id
    )


def _find_plugin_instance(entry):
    import base_plugin

    module = entry.module
    plugin_class = base_plugin.BasePlugin._findPluginClass(module)
    if plugin_class is None:
        raise RuntimeError("plugin does not define a class extending BasePlugin")
    instance = plugin_class()
    instance.id = entry.plugin_id
    instance.name = entry.metadata.get("name") or entry.plugin_id
    instance.description = entry.metadata.get("description") or ""
    instance.author = entry.metadata.get("author") or ""
    instance.version = str(entry.metadata.get("version") or "1.0")
    instance.icon = entry.metadata.get("icon") or None
    instance.min_version = entry.metadata.get("min_version") or ""
    requirements = entry.metadata.get("requirements") or ""
    instance.requirements = [item for item in str(requirements).split(",") if item]
    instance.enabled = True

    from extera_utils import lifecycle

    instance._lifecycle = lifecycle.scope_for(entry.plugin_id)
    return instance


def load_plugin(plugin_id, path, metadata_json=None):
    """Imports the file, instantiates the plugin and calls on_plugin_load."""
    with _LOCK:
        entry = _PLUGINS.get(plugin_id)
        if entry is not None and entry.instance is not None and entry.error is None:
            return _encode({"ok": True, "alreadyLoaded": True, "metadata": entry.metadata})

        entry = PluginEntry(plugin_id, path)
        if metadata_json:
            entry.metadata = _decode(metadata_json, {}) or {}
        if not entry.metadata:
            try:
                from extera_utils.metadata_parser import get_metadata

                entry.metadata = get_metadata(path)
            except Exception as error:
                entry.error = "could not read the plugin metadata: %s" % error
                _PLUGINS[plugin_id] = entry
                return _encode({"ok": False, "error": entry.error})

        requirements = entry.metadata.get("requirements")
        if requirements:
            deps_dir = os.path.join(_PLUGINS_PATH, ".deps", plugin_id) if _PLUGINS_PATH else ""
            if not deps_dir or not os.path.isdir(deps_dir):
                try:
                    extera_ios.log(
                        "[%s] __requirements__ are not installed (%s); "
                        "put pure-Python packages in %s"
                        % (plugin_id, requirements, deps_dir or "plugins/.deps/<id>")
                    )
                except Exception:
                    pass

        try:
            module_name = _module_name(plugin_id)
            plugin_dir = os.path.dirname(os.path.abspath(path))
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            if _PLUGINS_PATH:
                deps_dir = os.path.join(_PLUGINS_PATH, ".deps", plugin_id)
                if os.path.isdir(deps_dir) and deps_dir not in sys.path:
                    sys.path.insert(0, deps_dir)
            pip_controller.refresh_sys_path()
            importlib.invalidate_caches()
            loader = importlib.machinery.SourceFileLoader(module_name, path)
            spec = importlib.util.spec_from_loader(module_name, loader)
            if spec is None:
                raise RuntimeError("could not create an import spec for %s" % path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            loader.exec_module(module)
            entry.module = module
            entry.instance = _find_plugin_instance(entry)
            entry.index = len(_PLUGINS)
            entry.enabled = True
            _PLUGINS[plugin_id] = entry
            if plugin_id not in _LOAD_ORDER:
                _LOAD_ORDER.append(plugin_id)

            entry.instance.on_plugin_load()
            entry.instance.initialized = True
            return _encode({
                "ok": True,
                "metadata": entry.metadata,
                "index": entry.index,
            })
        except Exception:
            entry.error = traceback.format_exc()
            _PLUGINS[plugin_id] = entry
            return _encode({"ok": False, "error": entry.error})


def unload_plugin(plugin_id):
    with _LOCK:
        entry = _PLUGINS.pop(plugin_id, None)
        if plugin_id in _LOAD_ORDER:
            _LOAD_ORDER.remove(plugin_id)
    if entry is None:
        return _encode({"ok": True})
    error = None
    if entry.instance is not None:
        try:
            entry.instance._invoke_plugin_unload()
        except Exception:
            error = traceback.format_exc()
        try:
            import base_plugin

            base_plugin.BasePlugin._cleanup(plugin_id)
        except Exception:
            pass
        try:
            for item in getattr(entry.instance, "_menu_items", {}).values():
                data = item.get("data", {})
                for key in ("on_click", "on_long_click"):
                    handle = data.get(key)
                    if handle:
                        extera_ios.release(handle)
        except Exception:
            pass
        try:
            for handle in _SETTINGS_HANDLES.pop(plugin_id, set()):
                extera_ios.release(handle)
        except Exception:
            pass
        try:
            from extera_utils import lifecycle

            lifecycle.stop(plugin_id)
        except Exception:
            pass
        try:
            from extera_utils import classes

            classes.release_plugin(plugin_id)
        except Exception:
            pass
        try:
            import telegram_compat

            telegram_compat.remove_observers_for_plugin(plugin_id)
        except Exception:
            pass
        try:
            import intents

            intents.IntentsManager.remove_handlers_for_plugin(plugin_id)
        except Exception:
            pass
    if entry.module is not None:
        sys.modules.pop(getattr(entry.module, "__name__", ""), None)
    try:
        if _PLUGINS_PATH:
            deps_dir = os.path.join(_PLUGINS_PATH, ".deps", plugin_id)
            if deps_dir in sys.path:
                sys.path.remove(deps_dir)
        pip_controller.refresh_sys_path()
        importlib.invalidate_caches()
    except Exception:
        pass
    return _encode({"ok": error is None, "error": error})


def set_enabled(plugin_id, enabled, path=None, metadata_json=None):
    if enabled:
        result = _decode(load_plugin(plugin_id, path, metadata_json), {})
        return _encode(result)
    result = _decode(unload_plugin(plugin_id), {})
    result["ok"] = result.get("ok", True)
    return _encode(result)


def _resolve_plugin_instance(plugin_id):
    """Returns `(instance, regular_entry)` for Python and Elyx plugins.

    Elyx plugins live in the Elyx engine rather than `_PLUGINS`, but their
    `BasePlugin` instances register the same hooks, menus and settings, so the
    hook dispatcher must find them here too.
    """
    with _LOCK:
        entry = _PLUGINS.get(plugin_id)
    if entry is not None and entry.instance is not None:
        return entry.instance, entry
    try:
        from elyxcore import _ios_engine

        engine = _ios_engine.engine
        if engine is not None:
            instance = engine.plugins_instances.get(plugin_id)
            if instance is not None:
                return instance, entry
    except Exception:
        pass
    return None, entry


def is_loaded(plugin_id):
    instance, entry = _resolve_plugin_instance(plugin_id)
    if entry is not None and entry.error is not None:
        return False
    return instance is not None


def prune_plugin_settings(plugin_ids_json):
    try:
        values = _decode(plugin_ids_json, [])
        if not isinstance(values, list):
            values = []
        removed = plugin_settings.prune(values)
        return _encode({"ok": True, "removed": removed})
    except Exception:
        return _encode({"ok": False, "removed": [], "error": traceback.format_exc()})


# ---------------------------------------------------------------------------
# Elyx plugins


def _elyx_metadata_dict(metadata):
    if metadata is None:
        return None
    return {
        "id": metadata.getId(),
        "name": metadata.getName(),
        "description": metadata.getDescription(),
        "author": metadata.getAuthor(),
        "version": metadata.getVersion(),
        "icon": metadata.getIcon(),
        "app_version": metadata.getAppVersion(),
        "sdk_version": metadata.getSdkVersion(),
        "requirements": metadata.getRequirements(),
        "required_plugins": metadata.getRequiredPlugins(),
        "enabled": metadata.isEnabled(),
        "error": metadata.getError(),
        "engine": metadata.getEngine(),
    }


def _elyx_engine():
    from elyxcore import _ios_engine

    return _ios_engine.setup()


def elyx_setup():
    try:
        engine = _elyx_engine()
        plugins = [_elyx_metadata_dict(item) for item in engine.scan()]
        return _encode({"ok": True, "plugins": plugins})
    except Exception:
        return _encode({"ok": False, "plugins": [], "error": traceback.format_exc()})


def elyx_scan():
    try:
        engine = _elyx_engine()
        plugins = [_elyx_metadata_dict(item) for item in engine.scan()]
        return _encode({"ok": True, "plugins": plugins})
    except Exception:
        return _encode({"ok": False, "plugins": [], "error": traceback.format_exc()})


def elyx_load(plugin_id):
    try:
        engine = _elyx_engine()
        engine.loadPlugin(plugin_id)
        metadata = _elyx_metadata(plugin_id)
        return _encode({
            "ok": metadata is not None and metadata.getError() is None,
            "plugin": _elyx_metadata_dict(metadata),
            "error": metadata.getError() if metadata is not None else None,
        })
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def elyx_unload(plugin_id):
    try:
        engine = _elyx_engine()
        engine.unloadPlugin(plugin_id)
        return _encode({"ok": True})
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def elyx_set_enabled(plugin_id, enabled):
    try:
        engine = _elyx_engine()
        engine.setPluginEnabled(plugin_id, bool(enabled))
        metadata = _elyx_metadata(plugin_id)
        ok = True if not enabled else (
            metadata is not None and metadata.getError() is None
        )
        return _encode({
            "ok": ok,
            "plugin": _elyx_metadata_dict(metadata),
            "error": metadata.getError() if metadata is not None else None,
        })
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def elyx_delete(plugin_id):
    try:
        engine = _elyx_engine()
        engine.deletePlugin(plugin_id)
        return _encode({"ok": True})
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def elyx_export_archive(plugin_id):
    try:
        import shutil
        import time
        from pathlib import Path

        engine = _elyx_engine()
        source = Path(engine.plugin_dir(plugin_id))
        if not source.is_dir():
            return _encode({"ok": False, "error": "unknown Elyx plugin"})
        cache_root = extera_ios.host("paths.dir", kind="cache") or ""
        if not cache_root:
            import tempfile

            cache_root = tempfile.gettempdir()
        target = Path(cache_root) / "elyx_share"
        target.mkdir(parents=True, exist_ok=True)
        base = target / ("%s-%d" % (plugin_id, int(time.time())))
        built = shutil.make_archive(str(base), "zip", str(source))
        archive = base.with_suffix(".elyx")
        Path(built).replace(archive)
        return _encode({"ok": True, "path": str(archive)})
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def elyx_inspect_archive(path, password=None):
    try:
        import zipfile

        from elyxcore._plugin import ElyxPlugin

        with zipfile.ZipFile(path, "r") as archive:
            plugin = ElyxPlugin(plzip=archive, pwd=password, raise_errors=False)
            validation = plugin.get_validation_result()
            metadata = validation.plugin if validation is not None else None
            errors = [str(error) for error, _ in plugin.errors]
            structure = plugin.structure
            return _encode({
                "ok": metadata is not None and not errors,
                "metadata": _elyx_metadata_dict(metadata),
                "errors": errors,
                "required_plugins": metadata.getRequiredPlugins() if metadata is not None else [],
                "main": structure.main_file_path if structure is not None else None,
                "assets": structure.assets if structure is not None else None,
                "wheels": structure.wheels_path if structure is not None else None,
            })
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def elyx_install_archive(path, password=None, enable=True):
    try:
        engine = _elyx_engine()
        metadata, _instance = engine.install_archive(path, password, enable)
        plugin_id = metadata.getId() if metadata is not None else None
        return _encode({
            "ok": metadata is not None and metadata.getError() is None,
            "plugin_id": plugin_id,
            "plugin": _elyx_metadata_dict(metadata),
        })
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def _elyx_metadata(plugin_id):
    try:
        from elyxcore import _ios

        return _ios.plugins.get(plugin_id)
    except Exception:
        return None


def elyx_settings(plugin_id):
    try:
        from elyxcore import _ios_engine

        engine = _ios_engine.engine or _ios_engine.setup()
        instance = engine.plugins_instances.get(plugin_id)
        if instance is None or not instance.enabled:
            return _encode({"ok": False, "error": "plugin is not loaded", "settings": []})
        from extera_utils import lifecycle

        with lifecycle.plugin_context(plugin_id):
            controls = instance.create_settings() or []
        result = [_serialize_control(control) for control in controls]
        handles = set()
        _collect_callback_handles(result, handles)
        key = "elyx:" + plugin_id
        previous = _SETTINGS_HANDLES.get(key)
        _SETTINGS_HANDLES[key] = handles
        if previous:
            for handle in previous - handles:
                extera_ios.release(handle)
        return _encode({"ok": True, "settings": _wrap(result)})
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc(), "settings": []})


def elyx_app_event(plugin_id, event):
    try:
        from elyxcore import _ios_engine

        engine = _ios_engine.engine or _ios_engine.setup()
        instance = engine.plugins_instances.get(plugin_id)
        if instance is None or not instance.enabled:
            return _encode(False)
        import base_plugin
        from extera_utils import lifecycle

        with lifecycle.plugin_context(plugin_id):
            instance.on_app_event(base_plugin.AppEvent(str(event)))
        return _encode(True)
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def plugin_info(plugin_id):
    instance, entry = _resolve_plugin_instance(plugin_id)
    if entry is not None:
        return _encode({
            "id": plugin_id,
            "metadata": entry.metadata,
            "enabled": entry.enabled,
            "error": entry.error,
            "loaded": entry.instance is not None,
        })
    try:
        from elyxcore import _ios

        metadata = _ios.plugins.get(plugin_id)
        if metadata is not None:
            return _encode({
                "id": plugin_id,
                "metadata": {
                    "id": metadata.getId(),
                    "name": metadata.getName(),
                    "description": metadata.getDescription(),
                    "author": metadata.getAuthor(),
                    "version": metadata.getVersion(),
                    "icon": metadata.getIcon(),
                    "app_version": metadata.getAppVersion(),
                    "sdk_version": metadata.getSdkVersion(),
                    "requirements": metadata.getRequirements(),
                    "engine": metadata.getEngine(),
                },
                "enabled": metadata.isEnabled(),
                "error": metadata.getError(),
                "loaded": instance is not None,
            })
    except Exception:
        pass
    return _encode(None)


def loaded_plugins():
    with _LOCK:
        return _encode([{
            "id": plugin_id,
            "loaded": _PLUGINS[plugin_id].instance is not None,
            "error": _PLUGINS[plugin_id].error,
        } for plugin_id in _LOAD_ORDER])


# ---------------------------------------------------------------------------
# Hooks


def _hook_result(value, hook_name):
    import base_plugin

    if value is None:
        return {"strategy": "DEFAULT"}
    if not isinstance(value, base_plugin.HookResult):
        if isinstance(value, dict):
            return value
        return {"strategy": "DEFAULT"}

    result = {"strategy": value.strategy.value if hasattr(value.strategy, "value") else str(value.strategy)}
    mapping = {
        "request": value.request,
        "response": value.response,
        "update": value.update,
        "updates": value.updates,
        "error": value.error,
        "params": value.params,
    }
    for key, item in mapping.items():
        if item is not None:
            result[key] = item
    return result


def call_hook(plugin_id, hook_name, args_json):
    instance, _entry = _resolve_plugin_instance(plugin_id)
    if instance is None:
        return _encode({"strategy": "DEFAULT", "error": "plugin is not loaded"})
    method = getattr(instance, hook_name, None)
    if not callable(method):
        return _encode({"strategy": "DEFAULT"})
    args = _decode(args_json, [])
    if not isinstance(args, list):
        args = [args]
    try:
        from extera_utils import lifecycle

        with lifecycle.plugin_context(plugin_id):
            value = method(*args)
        return _encode(_hook_result(value, hook_name))
    except Exception:
        return _encode({
            "strategy": "DEFAULT",
            "failure": traceback.format_exc(),
        })


def notify_update(update_name, account, update_json):
    """Posts a host update into the Android-style `NotificationCenter` bus."""
    try:
        import telegram_compat

        update = _decode(update_json, {})
        telegram_compat.notify_update(str(update_name), int(account or 0), update)
        return _encode({"ok": True})
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})


def call_lifecycle(plugin_id, event_name, args_json=None):
    instance, _entry = _resolve_plugin_instance(plugin_id)
    if instance is None:
        return _encode(None)
    try:
        extera_ios.host("runtime.plugin_started", plugin_id=plugin_id)
    except Exception:
        pass
    try:
        from extera_utils import lifecycle

        with lifecycle.plugin_context(plugin_id):
            if event_name == "on_app_event":
                import base_plugin

                raw = _decode(args_json, "app_resume") if args_json else "app_resume"
                try:
                    event = base_plugin.AppEvent(raw)
                except Exception:
                    event = base_plugin.AppEvent.RESUME
                return _encode(instance.on_app_event(event))
            method = getattr(instance, event_name, None)
            if callable(method):
                return _encode(method())
    except Exception:
        return _encode({"error": traceback.format_exc()})
    finally:
        try:
            extera_ios.host("runtime.plugin_finished", plugin_id=plugin_id)
        except Exception:
            pass
    return _encode(None)


def call_menu_item(plugin_id, item_id, context_json):
    instance, _entry = _resolve_plugin_instance(plugin_id)
    if instance is None:
        return _encode(False)
    item = getattr(instance, "_menu_items", {}).get(item_id)
    if item is None:
        return _encode(False)
    context = _decode(context_json, {}) or {}
    try:
        extera_ios.host("runtime.plugin_started", plugin_id=plugin_id)
    except Exception:
        pass
    try:
        callback = item.get("on_click")
        if callback is not None:
            callback(context)
        return _encode(True)
    except Exception:
        return _encode({"ok": False, "error": traceback.format_exc()})
    finally:
        try:
            extera_ios.host("runtime.plugin_finished", plugin_id=plugin_id)
        except Exception:
            pass


_CONDITION_BUILTINS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "isinstance": isinstance,
    "any": any,
    "all": all,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
}


def _translate_mvel(text):
    """Rewrites the Java/MVEL operators used by menu and hook conditions."""
    result = []
    index = 0
    length = len(text)
    quote = None
    while index < length:
        character = text[index]
        if quote is not None:
            result.append(character)
            if character == "\\" and index + 1 < length:
                result.append(text[index + 1])
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
            result.append(character)
            index += 1
            continue
        if text.startswith("&&", index):
            result.append(" and ")
            index += 2
            continue
        if text.startswith("||", index):
            result.append(" or ")
            index += 2
            continue
        if character == "!" and not text.startswith("!=", index):
            result.append(" not ")
            index += 1
            continue
        result.append(character)
        index += 1
    translated = "".join(result)
    translated = re.sub(r"\btrue\b", "True", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bfalse\b", "False", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bnull\b", "None", translated, flags=re.IGNORECASE)
    # MVEL exposes the hook parameter as a Java object.
    translated = re.sub(r"\.getResult\(\)", ".result", translated)
    translated = re.sub(r"\.getThrowable\(\)", ".throwable", translated)
    return translated


def _evaluate_mvel(text, context):
    translated = _translate_mvel(text)
    namespace = {
        "__builtins__": _CONDITION_BUILTINS,
        "context": context,
    }
    for key, value in context.items():
        if isinstance(key, str) and key.isidentifier() and key not in namespace:
            namespace[key] = value
    return eval(translated, namespace)


def evaluate_condition(expression, context_json=None):
    """Evaluates a menu item or hook `condition`.

    Android compiles these with MVEL.  The same expressions (comparisons,
    boolean operators, field paths, `context.get(...)`) are evaluated here;
    the context is an `AttrDict`, so `message.out` and `context["out"]` both
    read the same value.
    """
    if expression is None or expression == "":
        return _encode(True)
    text = str(expression).strip()
    if not text:
        return _encode(True)
    context = _decode(context_json, {}) or {}
    if not isinstance(context, dict):
        context = {"value": context}
    lower = text.lower()
    if lower in ("true", "false"):
        return _encode(lower == "true")
    if lower == "null":
        return _encode(False)
    try:
        return _encode(bool(_evaluate_mvel(text, context)))
    except Exception:
        pass
    # Conservative fallback for expressions the Python evaluator cannot parse.
    if text.startswith("!"):
        return _encode(not _value_of(context, text[1:]))
    return _encode(bool(_value_of(context, text)))


def _value_of(context, path):
    current = context
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def execute_plugin_callback(plugin_id, callback):
    from extera_utils import lifecycle

    scope = lifecycle.scope_for(plugin_id) if plugin_id else None
    if plugin_id:
        try:
            extera_ios.host("runtime.plugin_started", plugin_id=plugin_id)
        except Exception:
            pass
    try:
        with lifecycle.active_scope(scope):
            return callback()
    finally:
        if plugin_id:
            try:
                extera_ios.host("runtime.plugin_finished", plugin_id=plugin_id)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Settings


_SETTING_FIELDS = {
    "type", "key", "text", "subtext", "icon", "accent", "red", "default",
    "items", "hint", "multiline", "max_length", "mask", "link_alias",
}


def _settings_payload(plugin_id):
    with _LOCK:
        entry = _PLUGINS.get(plugin_id)
    if entry is None or entry.instance is None:
        return {"ok": False, "error": "plugin is not loaded", "settings": []}
    try:
        controls = entry.instance.create_settings() or []
        result = []
        for control in controls:
            result.append(_serialize_control(control))
        handles = set()
        _collect_callback_handles(result, handles)
        previous = _SETTINGS_HANDLES.get(plugin_id)
        _SETTINGS_HANDLES[plugin_id] = handles
        if previous:
            for handle in previous - handles:
                extera_ios.release(handle)
        return {"ok": True, "settings": result}
    except Exception:
        return {"ok": False, "error": traceback.format_exc(), "settings": []}


def _collect_callback_handles(value, result):
    if isinstance(value, str):
        if value.startswith("cb-"):
            result.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_callback_handles(item, result)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_callback_handles(item, result)


def _serialize_control(control):
    if control is None:
        return {"type": "divider"}
    if isinstance(control, dict):
        return control
    if not dataclasses.is_dataclass(control):
        # A plugin may return a bare string as a section header.
        if isinstance(control, str):
            return {"type": "header", "text": control}
        return {"type": "custom", "title": str(control)}

    result = {}
    for field in dataclasses.fields(control):
        name = field.name
        value = getattr(control, name)
        if name not in _SETTING_FIELDS and name not in (
            "on_click", "on_change", "on_long_click", "create_sub_fragment",
            "view", "item", "factory", "factory_args",
        ):
            continue
        if callable(value):
            result[name] = extera_ios.retain(value)
        elif name == "items":
            result[name] = list(value or [])
        elif name in ("view", "item", "factory", "factory_args"):
            result[name] = _describe_custom(value)
        elif hasattr(value, "value") and type(value).__name__ == "Enum":
            result[name] = value.value
        else:
            result[name] = value
    result.setdefault("type", "custom")
    return result


def _describe_custom(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_json"):
        try:
            return value.to_json()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {
            key: item for key, item in value.__dict__.items()
            if isinstance(item, (str, int, float, bool, list, dict, type(None)))
        }
    return str(value)


def load_settings(plugin_id):
    result = _settings_payload(plugin_id)
    return _encode({"ok": result["ok"], "error": result.get("error"),
                    "settings": _wrap(result["settings"])})


def get_setting_value(plugin_id, key, default=None):
    return _encode(plugin_settings.get_setting(plugin_id, key, default))


def set_setting_value(plugin_id, key, value):
    plugin_settings.set_setting(plugin_id, key, value)
    return _encode(True)


def get_all_settings(plugin_id):
    return _encode(plugin_settings.get_all_settings(plugin_id))


def clear_plugin_settings(plugin_id):
    plugin_settings.clear_settings(plugin_id)
    return _encode(True)


def _requirement_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value)
    parts = re.split(r",(?=\s*[A-Za-z0-9_.\-]+\s*(?:[<>=!~]|$))", text)
    return [part.strip() for part in parts if part.strip()]


def install_requirements(plugin_id, requirements=None):
    try:
        if requirements is None:
            with _LOCK:
                entry = _PLUGINS.get(plugin_id)
            value = entry.metadata.get("requirements") if entry is not None else []
        else:
            value = requirements

        def progress(text):
            try:
                extera_ios.log("[pip:%s] %s" % (plugin_id, text))
            except Exception:
                pass

        paths = pip_controller.install_dependencies(
            _requirement_list(value), plugin_id, progress=progress
        )
        return _encode({"ok": True, "paths": paths, "error": None})
    except Exception as error:
        try:
            extera_ios.log("[pip:%s] %s" % (plugin_id, traceback.format_exc()))
        except Exception:
            pass
        return _encode({"ok": False, "paths": [], "error": str(error)})


def uninstall_requirements(plugin_id):
    try:
        pip_controller.uninstall_dependencies(plugin_id)
        return _encode({"ok": True})
    except Exception as error:
        return _encode({"ok": False, "error": str(error)})


def refresh_settings(plugin_id):
    return load_settings(plugin_id)


# ---------------------------------------------------------------------------
# Development server


def dev_server_start(host=None, port=None):
    try:
        import dev_server

        dev_server.DevServer.start_server(host, port)
        return dev_server_state()
    except Exception:
        return _encode({"ok": False, "running": False, "error": traceback.format_exc()})


def dev_server_stop():
    try:
        import dev_server

        dev_server.DevServer.stop_server()
        return dev_server_state()
    except Exception:
        return _encode({"ok": False, "running": False, "error": traceback.format_exc()})


def dev_server_state():
    try:
        import dev_server

        host, port = dev_server.DevServer.address()
        return _encode({
            "ok": True,
            "running": dev_server.DevServer.is_server_running(),
            "host": host,
            "port": port,
        })
    except Exception:
        return _encode({"ok": False, "running": False, "error": traceback.format_exc()})


def notify_plugins_updated():
    try:
        import telegram_compat

        # Android's update runnable posts both names whenever the plugin list
        # or its menu items can have changed.
        telegram_compat.notify_all("pluginsUpdated")
        telegram_compat.notify_all("pluginMenuItemsUpdated")
    except Exception:
        pass
    return _encode(True)


def notify_plugin_event(name, *args):
    """Posts one Android plugin notification to every observer.

    Swift calls this for `pluginIsNotResponding`,
    `pluginSettingsRegistered`/`pluginSettingsUnregistered`,
    `pluginCatalogUpdated` and `pluginsPySdkInfoChanged`.
    """
    try:
        import telegram_compat

        telegram_compat.notify_all(str(name), *args)
    except Exception:
        pass
    return _encode(True)


# ---------------------------------------------------------------------------
# Analyzer


def analyze(path, name=None):
    import extera_analyzer

    return extera_analyzer.analyze_json(path, name)


def analyze_archive(path, name=None):
    import extera_analyzer

    return extera_analyzer.analyze_archive_json(path, name)


def analyze_text(source, name="plugin"):
    import extera_analyzer

    return _encode(extera_analyzer.analyze_source(source, name))


def analyze_diff(previous_path, path, name=None):
    """Compares an installed version with an update, like Android's diff call."""
    import extera_analyzer

    return extera_analyzer.analyze_diff_json(previous_path, path, name)


def analyze_compare(previous_path, path, name=None):
    """Returns `{"report": ..., "diff": ...}` in one analysis pass."""
    import extera_analyzer

    return _encode(extera_analyzer.analyze_compare(previous_path, path, name))


# ---------------------------------------------------------------------------
# Callback bridge


def invoke_callback(handle, args_json):
    return extera_ios._invoke(handle, args_json)


def release_callback(handle):
    extera_ios.release(handle)
    return _encode(True)


def runtime_version():
    return _encode({"runtime": _RUNTIME_VERSION, "sdk": _sdk_version.__version__})


def shutdown():
    for plugin_id in list(_LOAD_ORDER):
        unload_plugin(plugin_id)
    return _encode({"ok": True})
