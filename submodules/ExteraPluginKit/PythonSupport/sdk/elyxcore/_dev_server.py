# This is the iOS counterpart of ElyxCore's dev-server patch.
#
# The Android class wraps `dev_server.DevServer._process_command` and adds the
# `elyx_*` commands used by the IDE plugin.  The transport is different on iOS
# (TCP loopback instead of an abstract Unix socket), but the patch point and the
# compressed `data` response shape are the same.
#
# Licensed under the GPL v2 or later, like the rest of this repository.

import base64
import hashlib
import json
import os
import shutil
import socket
import traceback
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import dev_server
from android_utils import log as logcat
from elyxcore._ios_engine import IOSPluginEngine
from elyxcore._plugin import ElyxPlugin


def _get_plugin_types():
    return IOSPluginEngine, ElyxPlugin


class ElyxDevServer:
    original_method = None
    hash_cache = {}
    _patched = False

    @classmethod
    def get_file_hash(cls, filepath):
        mtime = os.path.getmtime(filepath)
        if filepath in cls.hash_cache:
            cached_hash, cached_mtime = cls.hash_cache[filepath]
            if cached_mtime == mtime:
                return cached_hash

        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                hash_md5.update(chunk)
        file_hash = hash_md5.hexdigest()
        cls.hash_cache[filepath] = (file_hash, mtime)
        return file_hash

    @classmethod
    def setup(cls):
        if cls._patched:
            return
        cls.original_method = getattr(dev_server.DevServer, "_process_command")
        dev_server.DevServer._process_command = staticmethod(cls._process_command)
        cls._patched = True

    @classmethod
    def teardown(cls):
        if not cls._patched:
            return
        if cls.original_method is not None:
            dev_server.DevServer._process_command = cls.original_method
        cls.original_method = None
        cls._patched = False

    @staticmethod
    def _process_command(command: Dict[str, Any], client_socket: socket.socket) -> None:
        action = command.get("@")
        request_id = command.get("#")

        def on_complete(result):
            data = {"#": request_id}
            if result:
                data["data"] = base64.b64encode(
                    zlib.compress(json.dumps(result).encode(), level=7)
                ).decode()
            try:
                client_socket.sendall(json.dumps(data).encode("utf-8"))
            except Exception:
                logcat("[ElyxDevServer] Error sending response: " + traceback.format_exc())

        try:
            handlers = {
                "elyx_ping": ElyxDevServer._handle_elyx_ping,
                "elyx_changes": ElyxDevServer._handle_elyx_changes,
                "get_elyx_plugins": ElyxDevServer._handle_get_elyx_plugins,
                "elyx_compare_folder": ElyxDevServer._handle_elyx_compare_folder,
            }
            handler = handlers.get(action)
            if handler:
                payload = None
                if command.get("data"):
                    payload = json.loads(
                        zlib.decompress(base64.b64decode(command["data"]))
                    )
                handler(payload, on_complete)
            elif ElyxDevServer.original_method is not None:
                ElyxDevServer.original_method(command, client_socket)
        except Exception:
            on_complete({"error": "Error processing command: " + traceback.format_exc()})

    @staticmethod
    def cmpss(rs):
        return base64.b64encode(
            zlib.compress(json.dumps(rs).encode(), level=7)
        ).decode()

    @staticmethod
    def _handle_elyx_changes(command: Dict[str, Any], on_complete,
                             custom_on_complete=None):
        try:
            engine, _ = _get_plugin_types()
            plugin_id = command.get("plugin_id")
            if plugin_id not in ElyxPlugin.instances_by_id:
                error = {"error": "Plugin with id %s not found!" % plugin_id}
                if custom_on_complete is None:
                    return on_complete(error)
                return custom_on_complete.run(ElyxDevServer.cmpss(error))

            instance = ElyxPlugin.instances_by_id[plugin_id]
            plugin_dir = instance.dir_path
            errors = []
            for change in command.get("changes", []):
                event_type = change.get("#")
                try:
                    if event_type == "deleted":
                        path = Path(plugin_dir) / change["path"]
                        if not path.exists():
                            continue
                        if change.get("is_directory"):
                            shutil.rmtree(str(path))
                        else:
                            os.remove(str(path))
                    elif event_type == "created":
                        path = Path(plugin_dir) / change["path"]
                        os.makedirs(str(path.parent), exist_ok=True)
                        with open(str(path), "wb") as handle:
                            handle.write(base64.b64decode(change["content"]))
                    elif event_type == "moved":
                        path = Path(plugin_dir) / change["dest_path"]
                        os.makedirs(str(path.parent), exist_ok=True)
                        shutil.move(str(Path(plugin_dir) / change["path"]), str(path))
                    elif event_type == "modified":
                        path = Path(plugin_dir) / change["path"]
                        os.makedirs(str(path.parent), exist_ok=True)
                        with open(str(path), "wb") as handle:
                            handle.write(base64.b64decode(change["content"]))
                except Exception as error:
                    errors.append(
                        "Failed to apply change <%s>: %s\n%s"
                        % (event_type, error, traceback.format_exc())
                    )

            engine_instance = engine.instance
            if engine_instance is not None:
                engine_instance.unloadPlugin(plugin_id)

            def callback(error):
                if error:
                    errors.append(error)
                result = {"errors": errors, "success": not errors}
                if custom_on_complete is None:
                    on_complete(result)
                else:
                    custom_on_complete.run(ElyxDevServer.cmpss(result))
                try:
                    import extera_ios

                    extera_ios.host("plugins.reload")
                except Exception:
                    pass

            new_plugin = ElyxPlugin(plugin_dir)
            new_plugin.init()
            if engine_instance is not None:
                engine_instance.loadPlugin(plugin_id, plugin_dir, callback=callback)
            else:
                on_complete({"errors": ["Elyx engine is not running"], "success": False})
        except Exception:
            error = {"error": "Error applying changes:\n" + traceback.format_exc()}
            if custom_on_complete is None:
                on_complete(error)
            else:
                custom_on_complete.run(ElyxDevServer.cmpss(error))

    @staticmethod
    def _handle_get_elyx_plugins(_, on_complete, custom_on_complete=None):
        try:
            _, plugin_class = _get_plugin_types()
            plugins = {
                plugin_id: plugin.get_metainfo()
                for plugin_id, plugin in plugin_class.instances_by_id.items()
            }
            if custom_on_complete is not None:
                custom_on_complete.run(ElyxDevServer.cmpss(plugins))
            else:
                on_complete(plugins)
        except Exception:
            error = {"error": "Error getting plugins: " + traceback.format_exc()}
            if custom_on_complete is not None:
                custom_on_complete.run(ElyxDevServer.cmpss(error))
            else:
                on_complete(error)

    @staticmethod
    def _handle_elyx_ping(_, on_complete):
        on_complete({"pong": True})

    @staticmethod
    def _handle_elyx_compare_folder(command, on_complete, custom_on_complete=None):
        try:
            _, plugin_class = _get_plugin_types()
            plugin_id = command.get("plugin_id")
            if plugin_id not in plugin_class.instances_by_id:
                error = {"error": "Plugin with id %s not found!" % plugin_id}
                if custom_on_complete is None:
                    return on_complete(error)
                return custom_on_complete.run(ElyxDevServer.cmpss(error))

            instance = plugin_class.instances_by_id[plugin_id]
            plugin_dir = instance.dir_path
            response = {}
            remote = command.get("data", {})
            for relpath, file_hash in remote.items():
                path = Path(plugin_dir).joinpath(relpath)
                if not path.exists():
                    response.setdefault("created", []).append(relpath)
                elif file_hash != ElyxDevServer.get_file_hash(path):
                    response.setdefault("modified", []).append(relpath)

            for root, dirs, files in os.walk(plugin_dir):
                if "__pycache__" in root:
                    continue
                dirs[:] = [name for name in dirs if name != "__pycache__"]
                for name in files:
                    path = os.path.join(root, name)
                    relpath = os.path.relpath(path, plugin_dir).replace("\\", "/")
                    if relpath not in remote:
                        response.setdefault("deleted", []).append(relpath)

            if custom_on_complete is None:
                on_complete(response)
            else:
                custom_on_complete.run(ElyxDevServer.cmpss(response))
        except Exception:
            error = {"error": "Error comparing folder: " + traceback.format_exc()}
            if custom_on_complete is None:
                on_complete(error)
            else:
                custom_on_complete.run(ElyxDevServer.cmpss(error))
