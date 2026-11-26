# This is the iOS counterpart of the exteraGram plugins SDK.
#
# The Android SDK exposes a development server over an abstract Unix socket so
# the IDE plugin can list, enable, reload, write and remove plugins, and start a
# remote Python debugger.  iOS has no abstract sockets or `adb forward`, so the
# same JSON protocol is served over TCP on the loopback interface.  Every
# command name, request field and response shape is unchanged.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import enum
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import traceback
from typing import Any, Callable, Dict, Optional

import _extera_runtime
import extera_ios
from android_utils import log
from base_plugin import AppEvent, BasePlugin
from log_utils import _set_dev_mode


class DebuggerPlatform(enum.Enum):
    PyCharm = "pycharm"
    VSCode = "vscode"


class Callback:
    """iOS analogue of Android's `Utilities.Callback` proxy."""

    def __init__(self, fn: Callable[[Any], None]):
        self._fn = fn

    def run(self, arg):
        try:
            self._fn(arg)
        except Exception:
            log("Error running callback: %s" % traceback.format_exc())

    def __call__(self, arg):
        self.run(arg)


class DebuggerEventListener(BasePlugin):
    def __init__(self, host: str, port: int, platform: DebuggerPlatform):
        super().__init__()

        self.id = "debugger_event_listener"
        self.name = "Debugger Event Listener"
        self.enabled = True
        self.initialized = True

        self.host = host
        self.port = port
        self.platform = platform

    def on_app_event(self, event_type):
        if self.platform != DebuggerPlatform.PyCharm:
            return
        if event_type == AppEvent.PAUSE or event_type == AppEvent.PAUSE.value:
            DevServer.stop_remote_debugging(self.platform)
        elif event_type == AppEvent.RESUME or event_type == AppEvent.RESUME.value:
            DevServer.setup_remote_debugging(self.host, self.port, self.platform)


def _plugins_directory() -> str:
    try:
        directory = extera_ios.host("paths.dir", name="plugins")
        if directory:
            return str(directory)
    except Exception:
        pass
    for entry in sys.path:
        if os.path.basename(str(entry).replace("\\", "/").rstrip("/")) == "plugins":
            return str(entry)
    return os.path.join(os.getcwd(), "plugins")


def _plugin_path(plugin_id: str) -> str:
    return os.path.join(_plugins_directory(), plugin_id + ".plugin")


def _installed_plugin_ids():
    directory = _plugins_directory()
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return sorted(
        os.path.splitext(name)[0]
        for name in names
        if name.endswith(".plugin") and os.path.isfile(os.path.join(directory, name))
    )


class DevServer:
    # Kept for source compatibility with the Android SDK; iOS does not use it.
    SOCKET_NAME = "exteragram_devserver"
    ADB_UIDS = (0, 2000)
    SOCKET_TIMEOUT = 600
    BUFFER_SIZE = 4096

    HOST = "127.0.0.1"
    PORT = 8765

    PYCHARM_DEBUGGER_DIR = os.path.join(_plugins_directory(), "debugger", "pydevd-pycharm.egg")

    _server_thread: Optional[threading.Thread] = None
    _server_socket: Optional[socket.socket] = None
    _is_running = False
    _active_debugging = False
    _active_platform = None
    _host = HOST
    _port = PORT

    # -- Server lifecycle ----------------------------------------------------

    @staticmethod
    def _get_plugins_map():
        ids = set(_installed_plugin_ids())
        try:
            for item in json.loads(_extera_runtime.loaded_plugins()):
                if item.get("id"):
                    ids.add(item["id"])
        except Exception:
            pass
        return sorted(ids)

    @classmethod
    def start_server(cls, host: Optional[str] = None, port: Optional[int] = None) -> threading.Thread:
        if cls._is_running and cls._server_thread and cls._server_thread.is_alive():
            log("Server already running on %s:%s" % (cls._host, cls._port))
            return cls._server_thread

        cls._host = host or cls.HOST
        cls._port = int(port if port is not None else cls.PORT)
        cls._is_running = True

        cls._server_thread = threading.Thread(target=cls._server_thread_function, daemon=True)
        cls._server_thread.start()
        _set_dev_mode(True)
        log("Server started in background thread on %s:%s" % (cls._host, cls._port))
        return cls._server_thread

    @classmethod
    def stop_server(cls) -> bool:
        if not cls._is_running:
            log("Server not running")
            return False

        log("Stopping development server...")

        if cls._active_debugging and cls._active_platform:
            cls.stop_remote_debugging(cls._active_platform)

        if cls._server_socket:
            try:
                cls._server_socket.close()
                cls._server_socket = None
                log("Server socket closed")
            except Exception as error:
                log("Error closing server socket: %s\n%s" % (error, traceback.format_exc()))

        cls._is_running = False
        _set_dev_mode(False)
        log("Development server stopped")
        return True

    @classmethod
    def is_server_running(cls) -> bool:
        return cls._is_running

    @classmethod
    def address(cls):
        return (cls._host, cls._port)

    @classmethod
    def _address(cls):
        """Android's abstract-socket name.

        iOS serves the same protocol over loopback TCP (`address()`); this
        helper exists so plugins and tools written against the Android SDK can
        still read the socket name.
        """
        return "\0" + cls.SOCKET_NAME

    @staticmethod
    def _peer_uid(client_socket) -> Optional[int]:
        """Android's `SO_PEERCRED` peer check, when the platform has it."""
        try:
            import struct

            option = getattr(socket, "SO_PEERCRED", 17)
            _, uid, _ = struct.unpack(
                "3i",
                client_socket.getsockopt(
                    socket.SOL_SOCKET, option, struct.calcsize("3i")
                ),
            )
            return uid
        except Exception:
            return None

    @classmethod
    def _is_trusted_peer(cls, peer) -> bool:
        """Accepts Android's UID or iOS's loopback peer tuple.

        Android trusts adb (uid 0/2000) and the app itself; iOS has no peer
        credentials, so the TCP server only accepts connections from loopback.
        """
        if isinstance(peer, int):
            getuid = getattr(os, "getuid", None)
            app_uid = getuid() if getuid is not None else None
            return peer in cls.ADB_UIDS or (app_uid is not None and peer == app_uid)
        if peer is None:
            return False
        try:
            address = peer[0] if isinstance(peer, tuple) else str(peer)
        except Exception:
            return False
        return address in ("127.0.0.1", "::1", "localhost")

    @classmethod
    def _server_thread_function(cls):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls._server_socket = server

        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((cls._host, cls._port))
            server.listen(1)
            cls._port = server.getsockname()[1]
            cls._is_running = True
            log("Server listening on %s:%s" % (cls._host, cls._port))

            while cls._is_running:
                try:
                    if cls._server_socket is None:
                        break
                    cls._server_socket.settimeout(0.5)
                    client_socket, peer = cls._server_socket.accept()
                    if not cls._is_trusted_peer(peer):
                        log("Rejected connection from %s" % (peer,))
                        client_socket.close()
                        continue
                    log("Accepted connection from %s" % (peer,))
                    cls._handle_client(client_socket)
                except socket.timeout:
                    continue
                except Exception as error:
                    if cls._is_running:
                        log("Accept error: %s\n%s" % (error, traceback.format_exc()))
        except Exception as error:
            log("Server error: %s\n%s" % (error, traceback.format_exc()))
        finally:
            if cls._server_socket:
                try:
                    cls._server_socket.close()
                except Exception:
                    pass
                cls._server_socket = None

            cls._is_running = False
            log("Server thread terminated")

    @classmethod
    def _handle_client(cls, client_socket: socket.socket):
        buffer = b""

        try:
            client_socket.settimeout(cls.SOCKET_TIMEOUT)

            while cls._is_running:
                data = client_socket.recv(cls.BUFFER_SIZE)
                if not data:
                    break

                buffer += data
                buffer = cls._process_buffer(buffer, client_socket)

        except socket.timeout:
            log("Connection timed out")
        except Exception as error:
            log("Error handling client: %s\n%s" % (error, traceback.format_exc()))
        finally:
            try:
                client_socket.close()
            except Exception:
                pass
            log("Client connection closed")

    @classmethod
    def _process_buffer(cls, buffer: bytes, client_socket: socket.socket) -> bytes:
        buffer_str = buffer.decode("utf-8", errors="replace")
        position = 0

        while position < len(buffer_str):
            while position < len(buffer_str) and buffer_str[position].isspace():
                position += 1

            if position >= len(buffer_str):
                break

            try:
                command, end_position = json.JSONDecoder().raw_decode(buffer_str[position:])
                cls._process_command(command, client_socket)
                position += end_position
            except json.JSONDecodeError:
                break

        return buffer[len(buffer_str[:position].encode("utf-8")):]

    @classmethod
    def _process_command(cls, command: Dict[str, Any], client_socket: socket.socket):
        log("Received command: %s" % (command,))
        action = command.get("@")
        request_id = command.get("#")

        handlers = {
            "get_plugins": cls._handle_get_plugins,
            "enable_plugin": cls._handle_enable_plugin,
            "disable_plugin": cls._handle_disable_plugin,
            "reload_plugin": cls._handle_reload_plugin,
            "write_plugin": cls._handle_write_plugin,
            "remove_plugin": cls._handle_remove_plugin,
            "start_debugger": cls._handle_start_debugger,
            "stop_debugger": cls._handle_stop_debugger,
            "ping": cls._handle_ping,
        }

        handler = handlers.get(action)
        if handler:
            result = handler(command) or {}
        else:
            log("Unknown action: %s" % (action,))
            result = {}

        data = {"#": request_id, **result}

        try:
            client_socket.sendall(json.dumps(data).encode("utf-8"))
            log("Sent response for request %s" % (request_id,))
        except Exception as error:
            log("Error sending response: %s\n%s" % (error, traceback.format_exc()))

    # -- Plugin commands -----------------------------------------------------

    @classmethod
    def _plugin_metadata(cls, plugin_id: str) -> Dict[str, Any]:
        path = _plugin_path(plugin_id)
        metadata: Dict[str, Any] = {}
        if os.path.exists(path):
            try:
                from extera_utils.metadata_parser import get_metadata

                metadata = get_metadata(path)
            except Exception:
                metadata = {}
        return metadata

    @classmethod
    def _plugin_info(cls, plugin_id: str) -> Dict[str, Any]:
        metadata = cls._plugin_metadata(plugin_id)
        loaded = _extera_runtime.is_loaded(plugin_id)
        error = None
        try:
            info = json.loads(_extera_runtime.plugin_info(plugin_id))
            if info:
                metadata = info.get("metadata") or metadata
                error = info.get("error")
        except Exception:
            pass
        return {
            "name": metadata.get("name") or plugin_id,
            "description": metadata.get("description"),
            "author": metadata.get("author"),
            "version": metadata.get("version"),
            "error": error,
            "enabled": bool(loaded),
        }

    @classmethod
    def _handle_get_plugins(cls, command: Dict[str, Any]):
        result = {}
        for plugin_id in cls._get_plugins_map():
            result[plugin_id] = cls._plugin_info(plugin_id)
        return result

    @classmethod
    def _plugin_exists(cls, plugin_id: str) -> bool:
        return os.path.exists(_plugin_path(plugin_id)) or _extera_runtime.is_loaded(plugin_id)

    @classmethod
    def _handle_enable_plugin(cls, command: Dict[str, Any]):
        plugin_id = command.get("plugin_id")
        if not plugin_id:
            log("Missing plugin_id in enable_plugin command")
            return {"error": "Missing plugin_id"}
        if not cls._plugin_exists(plugin_id):
            log("Plugin %s not found" % plugin_id)
            return {"error": "Plugin not found"}

        log("Enabling plugin %s" % plugin_id)
        path = _plugin_path(plugin_id) if os.path.exists(_plugin_path(plugin_id)) else None
        result = json.loads(_extera_runtime.set_enabled(plugin_id, True, path))
        return None if result.get("ok", True) else {"error": result.get("error") or "Could not enable plugin"}

    @classmethod
    def _handle_disable_plugin(cls, command: Dict[str, Any]):
        plugin_id = command.get("plugin_id")
        if not plugin_id:
            log("Missing plugin_id in disable_plugin command")
            return {"error": "Missing plugin_id"}
        if not cls._plugin_exists(plugin_id):
            log("Plugin %s not found" % plugin_id)
            return {"error": "Plugin not found"}

        log("Disabling plugin %s" % plugin_id)
        result = json.loads(_extera_runtime.set_enabled(plugin_id, False))
        return None if result.get("ok", True) else {"error": result.get("error") or "Could not disable plugin"}

    @classmethod
    def _handle_reload_plugin(cls, command: Dict[str, Any]):
        plugin_id = command.get("plugin_id")
        if not plugin_id:
            log("Missing plugin_id in reload_plugin command")
            return {"error": "Missing plugin_id"}
        if not cls._plugin_exists(plugin_id):
            log("Plugin %s not found" % plugin_id)
            return {"error": "Plugin not found"}

        log("Reloading plugin %s" % plugin_id)
        cls._reload_plugin(plugin_id)
        return None

    @classmethod
    def _handle_write_plugin(cls, command: Dict[str, Any]):
        plugin_id = command.get("plugin_id")
        content = command.get("content")

        if not plugin_id or not content:
            log("Missing plugin_id or content in write_plugin command")
            return {"error": "Missing plugin_id or content"}

        log("Writing plugin %s" % plugin_id)

        try:
            directory = _plugins_directory()
            os.makedirs(directory, exist_ok=True)
            path = _plugin_path(plugin_id)
            previous = None
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    previous = handle.read()

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".plugin", delete=False, encoding="utf-8", dir=directory
            ) as temp_file:
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = temp_file.name

            os.replace(temp_path, path)
            _extera_runtime.unload_plugin(plugin_id)
            result = json.loads(_extera_runtime.load_plugin(plugin_id, path))
            if not result.get("ok"):
                if previous is not None:
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(previous)
                return {"error": result.get("error") or "Could not load the plugin"}

            log("Plugin %s written successfully" % plugin_id)
            return None
        except Exception as error:
            log("Error writing plugin %s: %s\n%s" % (plugin_id, error, traceback.format_exc()))
            return {"error": str(error)}

    @classmethod
    def _handle_remove_plugin(cls, command: Dict[str, Any]):
        plugin_id = command.get("plugin_id")
        if not plugin_id:
            log("Missing plugin_id in remove_plugin command")
            return {"error": "Missing plugin_id"}
        if not cls._plugin_exists(plugin_id):
            log("Plugin %s not found" % plugin_id)
            return {"error": "Plugin not found"}

        log("Removing plugin %s" % plugin_id)
        _extera_runtime.unload_plugin(plugin_id)
        try:
            _extera_runtime.clear_plugin_settings(plugin_id)
        except Exception:
            pass
        path = _plugin_path(plugin_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as error:
            return {"error": str(error)}
        return None

    # -- Debugger ------------------------------------------------------------

    @classmethod
    def _handle_start_debugger(cls, command: Dict[str, Any]):
        if cls._active_debugging:
            log("Debugger is already active.")
            return {"status": "already_running"}

        host = command.get("host")
        port = command.get("port")
        platform_str = command.get("platform")

        if not host or not port or not platform_str:
            log("Missing host, port, or platform in start_debugger command")
            return {"error": "Missing required parameters"}

        try:
            platform = DebuggerPlatform(platform_str)
        except ValueError:
            log("Invalid platform: %s" % platform_str)
            return {"error": "Invalid platform: %s" % platform_str}

        log("Starting remote debugger on %s:%s, platform: %s" % (host, port, platform))
        success = cls.setup_remote_debugging(host, port, platform)

        if success:
            cls._active_debugging = True
            cls._active_platform = platform
            return {"status": "started"}
        return {"error": "Failed to start debugger"}

    @classmethod
    def _handle_stop_debugger(cls, command: Dict[str, Any]):
        log("Stopping remote debugger")

        if not cls._active_debugging:
            log("Debugger is not active.")
            return {"status": "not_running"}

        platform_str = command.get("platform")
        if not platform_str:
            log("Missing platform in stop_debugger command")
            return {"error": "Missing platform"}

        try:
            platform = DebuggerPlatform(platform_str)
        except ValueError:
            log("Invalid platform: %s" % platform_str)
            return {"error": "Invalid platform: %s" % platform_str}

        cls.stop_remote_debugging(platform)
        cls._active_debugging = False
        cls._active_platform = None
        return {"status": "stopped"}

    @classmethod
    def _handle_ping(cls, command: Dict[str, Any]):
        log("Received ping command")
        return {"pong": True}

    @classmethod
    def _reload_plugin(cls, plugin_id: str):
        try:
            path = _plugin_path(plugin_id)
            if not os.path.exists(path):
                log("Cannot reload plugin '%s': file not found." % plugin_id)
                return

            _extera_runtime.unload_plugin(plugin_id)
            result = json.loads(_extera_runtime.load_plugin(plugin_id, path))
            if result.get("ok"):
                log("Plugin '%s' reloaded successfully." % plugin_id)
            else:
                log("Error reloading plugin %s: %s" % (plugin_id, result.get("error")))
        except Exception as error:
            log("Error during _reload_plugin for '%s': %s\n%s" % (plugin_id, error, traceback.format_exc()))

    @classmethod
    def setup_remote_debugging(cls, host: str, port: int, platform: DebuggerPlatform) -> bool:
        if platform == DebuggerPlatform.PyCharm:
            success = cls._setup_pycharm_remote_debugger(host, port)
        elif platform == DebuggerPlatform.VSCode:
            success = cls._setup_vscode_remote_debugger(host, port)
        else:
            log("Unsupported debugger platform: %s" % platform)
            success = False

        if success:
            cls._active_debugging = True
            cls._active_platform = platform
        return success

    @classmethod
    def stop_remote_debugging(cls, platform: DebuggerPlatform) -> bool:
        if platform == DebuggerPlatform.PyCharm:
            success = cls._stop_pycharm_remote_debugging()
        elif platform == DebuggerPlatform.VSCode:
            success = cls._stop_vscode_remote_debugger()
        else:
            log("Unsupported debugger platform: %s" % platform)
            success = False

        if success:
            cls._active_debugging = False
            cls._active_platform = None
        return success

    @classmethod
    def _setup_pycharm_remote_debugger(cls, host: str, port: int) -> bool:
        try:
            sys.path.append(cls.PYCHARM_DEBUGGER_DIR)
            import pydevd_pycharm

            log("Setting up PyCharm remote debugger on %s:%s" % (host, port))
            pydevd_pycharm.settrace(
                host,
                port=port,
                stdoutToServer=True,
                stderrToServer=True,
                suspend=False,
            )
            log("PyCharm remote debugger setup complete")
            return True
        except ImportError:
            log("PyCharm debugger module not found")
            return False
        except Exception as error:
            log("Error setting up PyCharm remote debugger: %s" % error)
            return False

    @classmethod
    def _setup_vscode_remote_debugger(cls, host: str, port: int) -> bool:
        try:
            import debugpy

            log("Connecting VS Code remote debugger to %s:%s" % (host, port))
            debugpy.listen((host, port), in_process_debug_adapter=True)
            log("VS Code remote debugger connected successfully")
            return True
        except ImportError:
            log("VS Code debugger module not found")
            return False
        except Exception as error:
            log("Error setting up VS Code remote debugger: %s" % error)
            return False

    @classmethod
    def _stop_pycharm_remote_debugging(cls) -> bool:
        try:
            import pydevd_pycharm

            log("Stopping PyCharm remote debugger")
            pydevd_pycharm.stoptrace()
            log("PyCharm remote debugger stopped successfully")
            return True
        except ImportError:
            log("PyCharm debugger module not found")
            return False
        except Exception as error:
            log("Error stopping PyCharm remote debugger: %s" % error)
            return False

    @classmethod
    def _stop_vscode_remote_debugger(cls) -> bool:
        try:
            import debugpy._vendored.pydevd.pydevd

            log("Stopping VS Code remote debugger")
            debugpy._vendored.pydevd.pydevd.stoptrace()
            log("VS Code remote debugger stopped successfully")
            return True
        except ImportError:
            log("VS Code debugger module not found")
            return False
        except Exception as error:
            log("Error stopping VS Code remote debugger: %s" % error)
            return False

    # -- Instance form (kept for the earlier iOS SDK) ------------------------

    def __init__(self, *args, **kwargs):
        self.host = kwargs.get("host", self.HOST)
        self.port = int(kwargs.get("port", self.PORT))

    def start(self):
        DevServer.start_server(self.host, self.port)
        return DevServer._is_running

    def stop(self):
        return DevServer.stop_server()

    def is_running(self):
        return DevServer._is_running


def start_server(*args, **kwargs):
    return DevServer.start_server(*args, **kwargs)


def stop_server(*args, **kwargs):
    return DevServer.stop_server()
