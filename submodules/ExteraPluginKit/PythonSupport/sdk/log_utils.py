# This is the iOS counterpart of the exteraGram plugins SDK.
#
# `get_logger()` and the `Logger` interface mirror the Android module.  Entries
# are routed to the host log that the Plugins screen shows; the level filtering,
# formatting, handlers, timers and `dump()` behave the same as on Android.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import itertools
import os
import sys
import threading
import time
import traceback
import types
from collections import deque
from collections.abc import Mapping
from enum import Enum, IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


__all__ = ["LogLevel", "LogRecord", "Logger", "get_logger", "dump", "log"]


_INTERNAL_TAG = "pysdk"
_FALLBACK_TAG = "python"
_MAX_ENTRY_BYTES = 4000
_INLINE_WIDTH = 100
_LEAF_REPR_LIMIT = 300

_PLUGIN_MODULE_PREFIX = "extera_plugin_"

_LEAF_TYPES = (
    type,
    BaseException,
    types.ModuleType,
    types.FunctionType,
    types.BuiltinFunctionType,
    types.MethodType,
)

_dev_mode = False
_plugin_loggers: Dict[str, "Logger"] = {}
_plugin_loggers_lock = threading.Lock()
_handler_state = threading.local()


class LogLevel(IntEnum):
    VERBOSE = 2
    DEBUG = 3
    INFO = 4
    WARNING = 5
    ERROR = 6
    OFF = 100


def _set_dev_mode(enabled: bool) -> None:
    global _dev_mode
    _dev_mode = bool(enabled)


def _default_level() -> LogLevel:
    return LogLevel.DEBUG if _dev_mode else LogLevel.INFO


def _coerce_level(value: Union[LogLevel, int, str]) -> LogLevel:
    if isinstance(value, LogLevel):
        return value
    try:
        if isinstance(value, str):
            return LogLevel[value.strip().upper()]
        return LogLevel(int(value))
    except (KeyError, ValueError, TypeError):
        raise ValueError("Unknown log level: %r" % (value,)) from None


def _split_for_logcat(text: str, limit: int = 3800) -> List[str]:
    """Splits a line into host-sized chunks without breaking a code point."""
    text = str(text)
    if len(text) * 4 <= limit:
        return [text]
    data = text.encode("utf-8", "replace")
    if len(data) <= limit:
        return [text]

    chunks = []
    lines: List[bytes] = []
    size = 0
    for line in data.split(b"\n"):
        while len(line) > limit:
            if lines:
                chunks.append(b"\n".join(lines))
                lines, size = [], 0
            cut = limit
            while cut > 0 and (line[cut] & 0xC0) == 0x80:
                cut -= 1
            if cut == 0:
                cut = limit
            chunks.append(line[:cut])
            line = line[cut:]
        added = len(line) + (1 if lines else 0)
        if lines and size + added > limit:
            chunks.append(b"\n".join(lines))
            lines, size, added = [], 0, len(line)
        lines.append(line)
        size += added
    if lines:
        chunks.append(b"\n".join(lines))
    return [chunk.decode("utf-8", "replace") for chunk in chunks]


def _host_level(level: LogLevel) -> str:
    if level >= LogLevel.ERROR:
        return "error"
    if level == LogLevel.WARNING:
        return "warning"
    if level == LogLevel.INFO:
        return "info"
    return "debug"


def _write_host(level: LogLevel, tag: str, text: str, plugin_id: Optional[str] = None) -> None:
    import extera_ios

    limit = _MAX_ENTRY_BYTES - len(tag.encode("utf-8", "replace"))
    for chunk in _split_for_logcat(text, limit):
        try:
            extera_ios.host_json("log.write", {
                "text": chunk,
                "level": _host_level(level),
                "plugin_id": plugin_id or "",
                "tag": tag,
                "time": time.time(),
            })
        except Exception:
            try:
                sys.stderr.write("[%s] %s\n" % (tag, chunk))
            except Exception:
                pass


def _report_internal_error(message: str) -> None:
    try:
        _write_host(LogLevel.ERROR, _INTERNAL_TAG, "%s\n%s" % (message, traceback.format_exc()))
    except Exception:
        pass


def _caller_frame(stacklevel: int = 1):
    try:
        frame = sys._getframe(0)
    except ValueError:
        return None
    while frame is not None and frame.f_globals.get("__name__") == __name__:
        frame = frame.f_back
    for _ in range(stacklevel - 1):
        if frame is None:
            break
        frame = frame.f_back
    return frame


def _format_location(frame) -> str:
    code = frame.f_code
    return "%s:%s:%s" % (os.path.basename(code.co_filename), code.co_name, frame.f_lineno)


def _plugin_id_from_frame(frame) -> Optional[str]:
    if frame is None:
        return None
    module_name = str(frame.f_globals.get("__name__", ""))
    if module_name.startswith(_PLUGIN_MODULE_PREFIX):
        return module_name[len(_PLUGIN_MODULE_PREFIX):].split(".")[0]

    path = str(frame.f_code.co_filename).replace("\\", "/")
    if path.endswith(".plugin"):
        return os.path.splitext(os.path.basename(path))[0]
    parts = path.split("/")
    if "plugins" in parts:
        index = parts.index("plugins")
        if index + 1 < len(parts):
            name = parts[index + 1]
            if name.endswith(".plugin"):
                return os.path.splitext(name)[0]
            return name
    return None


def _strip_plugin_prefix(name: str, plugin_id: str) -> str:
    for prefix in (_PLUGIN_MODULE_PREFIX + plugin_id, plugin_id):
        if name == prefix:
            return ""
        if name.startswith(prefix + "."):
            return name[len(prefix) + 1:]
    return name


def _format_message(msg: Any, args: tuple) -> str:
    text = str(msg)
    if not args:
        return text
    values = args[0] if len(args) == 1 and isinstance(args[0], Mapping) and args[0] else args
    try:
        return text % values
    except Exception as error:
        return "%s %r (formatting failed: %s: %s)" % (text, values, type(error).__name__, error)


def _format_exc_info(exc_info: Any) -> Optional[str]:
    if isinstance(exc_info, BaseException):
        exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
    elif not isinstance(exc_info, tuple):
        exc_info = sys.exc_info()
    if len(exc_info) != 3 or exc_info[0] is None:
        return None
    return "".join(traceback.format_exception(*exc_info)).rstrip()


def _compose(message: str, location: Optional[str], tb: Optional[str]) -> str:
    text = message if location is None else "[%s] %s" % (location, message)
    return text if tb is None else "%s\n%s" % (text, tb)


class LogRecord:
    __slots__ = ("level", "tag", "message", "location", "traceback", "created", "plugin_id")

    def __init__(self, level: LogLevel, tag: str, message: str, location: Optional[str],
                 tb: Optional[str], created: float, plugin_id: Optional[str] = None):
        self.level = level
        self.tag = tag
        self.message = message
        self.location = location
        self.traceback = tb
        self.created = created
        self.plugin_id = plugin_id

    @property
    def text(self) -> str:
        return _compose(self.message, self.location, self.traceback)

    def __repr__(self):
        return "<LogRecord %s %s: %r>" % (self.level.name, self.tag, self.message)


class _Timer:
    __slots__ = ("_logger", "_label", "_level", "_start")

    def __init__(self, logger: "Logger", label: str, level: LogLevel):
        self._logger = logger
        self._label = label
        self._level = level
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = (time.perf_counter() - self._start) * 1000
        status = " (failed)" if exc_type is not None else ""
        self._logger.log(self._level, "%s took %.1f ms%s", self._label, elapsed, status)
        return False


class Logger:
    __slots__ = ("_tag", "_parent", "_level", "_children", "_handlers", "_show_location", "_plugin_id")

    def __init__(self, tag: str, *, show_location: bool = True, plugin_id: Optional[str] = None):
        if not isinstance(tag, str) or not tag:
            raise ValueError("tag must be a non-empty string")
        self._tag = tag
        self._parent = None
        self._level = None
        self._children: Dict[str, "Logger"] = {}
        self._handlers: Tuple[Callable[[LogRecord], Any], ...] = ()
        self._show_location = show_location
        self._plugin_id = plugin_id

    @property
    def tag(self) -> str:
        return self._tag

    @property
    def name(self) -> str:
        return self._tag

    @property
    def level(self) -> Optional[LogLevel]:
        return self._level

    @level.setter
    def level(self, value: Union[LogLevel, int, str, None]):
        self._level = None if value is None else _coerce_level(value)

    @property
    def effective_level(self) -> LogLevel:
        logger: Optional[Logger] = self
        while logger is not None:
            if logger._level is not None:
                return logger._level
            logger = logger._parent
        return _default_level()

    def is_enabled_for(self, level: Union[LogLevel, int, str]) -> bool:
        level = _coerce_level(level)
        return level < LogLevel.OFF and level >= self.effective_level

    def child(self, name: str) -> "Logger":
        logger = self
        for part in str(name).split("."):
            if part:
                logger = logger._child(part)
        return logger

    def verbose(self, msg: Any, *args, exc_info: Any = None, stacklevel: int = 1) -> None:
        if LogLevel.VERBOSE >= self.effective_level:
            self._emit(LogLevel.VERBOSE, msg, args, exc_info, stacklevel)

    def debug(self, msg: Any, *args, exc_info: Any = None, stacklevel: int = 1) -> None:
        if LogLevel.DEBUG >= self.effective_level:
            self._emit(LogLevel.DEBUG, msg, args, exc_info, stacklevel)

    def info(self, msg: Any, *args, exc_info: Any = None, stacklevel: int = 1) -> None:
        if LogLevel.INFO >= self.effective_level:
            self._emit(LogLevel.INFO, msg, args, exc_info, stacklevel)

    def warning(self, msg: Any, *args, exc_info: Any = None, stacklevel: int = 1) -> None:
        if LogLevel.WARNING >= self.effective_level:
            self._emit(LogLevel.WARNING, msg, args, exc_info, stacklevel)

    warn = warning

    def error(self, msg: Any, *args, exc_info: Any = None, stacklevel: int = 1) -> None:
        if LogLevel.ERROR >= self.effective_level:
            self._emit(LogLevel.ERROR, msg, args, exc_info, stacklevel)

    def exception(self, msg: Any, *args, stacklevel: int = 1) -> None:
        if LogLevel.ERROR >= self.effective_level:
            self._emit(LogLevel.ERROR, msg, args, True, stacklevel)

    def log(self, level: Union[LogLevel, int, str], msg: Any, *args, exc_info: Any = None,
            stacklevel: int = 1) -> None:
        level = _coerce_level(level)
        if LogLevel.OFF > level >= self.effective_level:
            self._emit(level, msg, args, exc_info, stacklevel)

    def dump(self, obj: Any, label: Optional[str] = None, *,
             level: Union[LogLevel, int, str] = LogLevel.DEBUG,
             depth: int = 2, max_items: int = 20, stacklevel: int = 1) -> None:
        level = _coerce_level(level)
        if LogLevel.OFF > level >= self.effective_level:
            text = dump(obj, depth=depth, max_items=max_items)
            self._emit(level, text if label is None else "%s: %s" % (label, text), (), None, stacklevel)

    def timed(self, label: str, level: Union[LogLevel, int, str] = LogLevel.DEBUG) -> _Timer:
        return _Timer(self, label, _coerce_level(level))

    def add_handler(self, handler: Callable[[LogRecord], Any]) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        if handler not in self._handlers:
            self._handlers = self._handlers + (handler,)

    def remove_handler(self, handler: Callable[[LogRecord], Any]) -> bool:
        if handler not in self._handlers:
            return False
        self._handlers = tuple(item for item in self._handlers if item != handler)
        return True

    def _child(self, part: str) -> "Logger":
        child = self._children.get(part)
        if child is None:
            child = Logger("%s.%s" % (self._tag, part), show_location=self._show_location,
                           plugin_id=self._plugin_id)
            child._parent = self
            child = self._children.setdefault(part, child)
        return child

    def _reset(self) -> None:
        self._level = None
        self._handlers = ()
        for child in list(self._children.values()):
            child._reset()

    def _emit(self, level: LogLevel, msg: Any, args: tuple, exc_info: Any, stacklevel: int) -> None:
        try:
            message = _format_message(msg, args)
            tb = _format_exc_info(exc_info) if exc_info else None
            location = None
            if self._show_location:
                frame = _caller_frame(stacklevel)
                if frame is not None:
                    location = _format_location(frame)
                del frame
            _write_host(level, self._tag, _compose(message, location, tb), self._plugin_id)
            self._dispatch(level, message, location, tb)
        except Exception:
            _report_internal_error("Failed to write a log entry for %s" % self._tag)

    def _dispatch(self, level: LogLevel, message: str, location: Optional[str], tb: Optional[str]) -> None:
        handlers: Tuple[Callable[[LogRecord], Any], ...] = ()
        logger: Optional[Logger] = self
        while logger is not None:
            handlers += logger._handlers
            logger = logger._parent
        if not handlers or getattr(_handler_state, "active", False):
            return

        record = LogRecord(level, self._tag, message, location, tb, time.time(), self._plugin_id)
        _handler_state.active = True
        try:
            for handler in handlers:
                try:
                    handler(record)
                except Exception:
                    _report_internal_error("Log handler %r failed" % (handler,))
        finally:
            _handler_state.active = False

    def __repr__(self):
        return "<Logger %s level=%s>" % (self._tag, self.effective_level.name)


def _plugin_logger(plugin_id: str) -> Logger:
    logger = _plugin_loggers.get(plugin_id)
    if logger is None:
        with _plugin_loggers_lock:
            logger = _plugin_loggers.get(plugin_id)
            if logger is None:
                logger = Logger("plugin.%s" % plugin_id, plugin_id=plugin_id)
                _plugin_loggers[plugin_id] = logger
    return logger


def _reset_plugin_logger(plugin_id: str) -> None:
    logger = _plugin_loggers.get(plugin_id)
    if logger is not None:
        logger._reset()


def get_logger(name: Optional[str] = None) -> Logger:
    frame = _caller_frame()
    plugin_id = _plugin_id_from_frame(frame)
    del frame

    if plugin_id is None:
        return Logger(name or _FALLBACK_TAG)

    logger = _plugin_logger(plugin_id)
    name = _strip_plugin_prefix(name, plugin_id) if name else ""
    return logger.child(name) if name else logger


def log(text, level: Union[LogLevel, int, str] = LogLevel.INFO, plugin_id=None) -> None:
    """Writes one line through the same host log `get_logger()` uses."""
    resolved = _coerce_level(level)
    frame = _caller_frame()
    resolved_plugin = plugin_id or _plugin_id_from_frame(frame)
    del frame
    _write_host(resolved, resolved_plugin or _FALLBACK_TAG, str(text), resolved_plugin)


class _Unreadable:
    __slots__ = ("error",)

    def __init__(self, error: BaseException):
        self.error = error

    def __repr__(self):
        return "<%s: %s>" % (type(self.error).__name__, self.error)


def _truncate(text: str, limit: int = _LEAF_REPR_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _scalar_repr(obj: Any) -> Optional[str]:
    if obj is None or isinstance(obj, (bool, int, float, complex, str)):
        return repr(obj)
    if isinstance(obj, (bytes, bytearray)):
        return repr(bytes(obj)) if len(obj) <= 32 else "%s[%d]" % (type(obj).__name__, len(obj))
    if isinstance(obj, Enum):
        return "%s.%s" % (type(obj).__name__, obj.name)
    if isinstance(obj, _Unreadable):
        return repr(obj)
    return None


def _python_fields(obj: Any) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    try:
        attrs = object.__getattribute__(obj, "__dict__")
    except Exception:
        attrs = None
    if isinstance(attrs, dict):
        for name, value in attrs.items():
            if not name.startswith("_chaquopy") and not name.startswith("__"):
                fields[name] = value

    for cls in type(obj).__mro__:
        slots = cls.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for name in slots:
            if name in fields or name in ("__dict__", "__weakref__"):
                continue
            try:
                fields[name] = object.__getattribute__(obj, name)
            except Exception:
                pass
    return fields


class _Dumper:
    def __init__(self, depth: int, max_items: int):
        self._depth = max(0, int(depth))
        self._max_items = max(0, int(max_items))
        self._lines: List[str] = []
        self._path: set = set()

    def render(self, obj: Any) -> str:
        self._node("", obj, 0)
        return "\n".join(self._lines)

    def _node(self, label: str, obj: Any, level: int) -> None:
        pad = "  " * level
        try:
            header, key, kind, entries = self._inspect(obj)
        except Exception as error:
            self._lines.append("%s%s%r" % (pad, label, _Unreadable(error)))
            return

        if entries is None:
            self._lines.append("%s%s%s" % (pad, label, header))
            return
        if key is not None and key in self._path:
            self._lines.append("%s%s%s <cycle>" % (pad, label, header))
            return
        opening, closing = ("[", "]") if kind == "seq" else ("{", "}")
        if level >= self._depth:
            self._lines.append("%s%s%s %s…%s" % (pad, label, header, opening, closing))
            return

        try:
            items, hidden = entries()
        except Exception as error:
            self._lines.append("%s%s%s %r" % (pad, label, header, _Unreadable(error)))
            return

        if not items and not hidden:
            self._lines.append("%s%s%s %s%s" % (pad, label, header, opening, closing))
            return
        if kind != "obj" and not hidden:
            inline = self._inline(items, kind)
            if inline is not None:
                self._lines.append("%s%s%s %s" % (pad, label, header, inline))
                return

        self._lines.append("%s%s%s" % (pad, label, header))
        if key is not None:
            self._path.add(key)
        try:
            for item_label, value in items:
                self._node(item_label, value, level + 1)
        finally:
            if key is not None:
                self._path.discard(key)
        if hidden:
            self._lines.append("%s  … %d more" % (pad, hidden))

    @staticmethod
    def _inline(items: List[Tuple[str, Any]], kind: str) -> Optional[str]:
        parts = []
        for item_label, value in items:
            text = _scalar_repr(value)
            if text is None:
                return None
            parts.append(text if kind == "seq" else "%s%s" % (item_label, text))
        text = ", ".join(parts)
        if len(text) > _INLINE_WIDTH:
            return None
        return "[%s]" % text if kind == "seq" else "{%s}" % text

    def _take(self, items, total: int):
        taken = list(itertools.islice(items, self._max_items))
        return taken, max(0, total - len(taken))

    @staticmethod
    def _key(key: Any) -> str:
        text = _scalar_repr(key)
        return text if text is not None else _truncate(str(key), 60)

    def _inspect(self, obj: Any):
        scalar = _scalar_repr(obj)
        if scalar is not None:
            return scalar, None, None, None

        if _is_host_object(obj):
            fields = _python_fields(obj)
            if fields:
                return type(obj).__name__, id(obj), "obj", lambda: (
                    [("%s = " % name, value) for name, value in fields.items()], 0
                )
            description = _describe_host_object(obj)
            return _truncate(description), None, None, None

        if isinstance(obj, _LEAF_TYPES):
            return _truncate(repr(obj)), None, None, None
        if isinstance(obj, Mapping):
            return (
                "%s(%d)" % (type(obj).__name__, len(obj)), id(obj), "map",
                lambda: self._take(((("%s: " % self._key(key), value) for key, value in obj.items()), len(obj))),
            )
        if isinstance(obj, tuple) and hasattr(type(obj), "_fields"):
            return type(obj).__name__, id(obj), "obj", lambda: (
                [("%s = " % name, value) for name, value in zip(obj._fields, obj)], 0
            )
        if isinstance(obj, (list, tuple, set, frozenset, deque)):
            return (
                "%s(%d)" % (type(obj).__name__, len(obj)), id(obj), "seq",
                lambda: self._take(((("[%d] = " % index, value) for index, value in enumerate(obj)), len(obj))),
            )

        fields = _python_fields(obj)
        if fields:
            return type(obj).__name__, id(obj), "obj", lambda: (
                [("%s = " % name, value) for name, value in fields.items()], 0
            )
        return _truncate(repr(obj)), None, None, None


def _is_host_object(obj: Any) -> bool:
    name = type(obj).__name__
    return name in ("ObjectProxy", "JavaObject") or hasattr(obj, "__handle__")


def _describe_host_object(obj: Any) -> str:
    for attribute in ("description", "toString"):
        try:
            value = getattr(obj, attribute)
            return str(value() if callable(value) else value)
        except Exception:
            continue
    return repr(obj)


def dump(obj: Any, depth: int = 2, max_items: int = 20) -> str:
    try:
        return _Dumper(depth, max_items).render(obj)
    except Exception as error:
        return "<dump failed: %s: %s>" % (type(error).__name__, error)
