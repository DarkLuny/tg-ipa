# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Android intents are the OS-level "open this URL / share this file" channel.
# On iOS the equivalents are URL opens and share-sheet items; the Swift host
# calls one dispatcher per phase, and this module performs the Android
# `IntentFilterRecord` matching itself: scheme, host, path template, action,
# MIME type, categories, flags, required query parameters and priority.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import inspect
import re
import secrets
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit

import extera_ios
from log_utils import log


_PATH_ARG_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)}")


class Uri:
    """A small `android.net.Uri` stand-in used by intent callbacks."""

    def __init__(self, url="", scheme=None, host=None, path=None, query=None,
                 fragment=None):
        self._url = "" if url is None else str(url)
        parts = urlsplit(self._url) if self._url else None
        self._scheme = scheme if scheme is not None else (parts.scheme if parts else None)
        self._host = host if host is not None else (parts.hostname if parts else None)
        if path is not None:
            self._path = path
        elif parts is not None:
            self._path = parts.path if parts.path else None
        else:
            self._path = None
        self._query = query if query is not None else (parts.query if parts else None)
        self._fragment = fragment if fragment is not None else (parts.fragment if parts else None)
        self._query_args = {}
        if self._query:
            for key, value in parse_qsl(str(self._query), keep_blank_values=True):
                if key and key not in self._query_args:
                    self._query_args[key] = value

    def getScheme(self):
        return self._scheme

    def getHost(self):
        return self._host

    def getPath(self):
        if self._path is None:
            return None
        return self._path if self._path.startswith("/") else "/" + self._path

    def getQuery(self):
        return self._query

    def getQueryParameter(self, name):
        return self._query_args.get(str(name))

    def getQueryParameterNames(self):
        return list(self._query_args.keys())

    @staticmethod
    def parse(uri):
        return Uri(uri)

    @classmethod
    def getClass(cls):
        from extera_utils.classes import ClassRef

        return ClassRef("android.net.Uri")

    def toString(self):
        return self._url

    def __str__(self):
        return self._url


class Intent:
    """The subset of `android.content.Intent` intent callbacks use."""

    ACTION_VIEW = "android.intent.action.VIEW"
    ACTION_SEND = "android.intent.action.SEND"
    ACTION_SEND_MULTIPLE = "android.intent.action.SEND_MULTIPLE"
    ACTION_CHOOSER = "android.intent.action.CHOOSER"
    ACTION_MAIN = "android.intent.action.MAIN"
    CATEGORY_LAUNCHER = "android.intent.category.LAUNCHER"
    CATEGORY_BROWSABLE = "android.intent.category.BROWSABLE"
    CATEGORY_DEFAULT = "android.intent.category.DEFAULT"
    FLAG_GRANT_READ_URI_PERMISSION = 0x00000001
    FLAG_GRANT_WRITE_URI_PERMISSION = 0x00000002
    EXTRA_STREAM = "android.intent.extra.STREAM"
    EXTRA_TEXT = "android.intent.extra.TEXT"
    EXTRA_SUBJECT = "android.intent.extra.SUBJECT"
    EXTRA_EMAIL = "android.intent.extra.EMAIL"

    @classmethod
    def getClass(cls):
        from extera_utils.classes import ClassRef

        return ClassRef("android.content.Intent")

    @classmethod
    def createChooser(cls, target, title=None):
        intent = cls(cls.ACTION_CHOOSER)
        intent.putExtra("android.intent.extra.INTENT", target)
        if title is not None:
            intent.putExtra("android.intent.extra.TITLE", title)
        return intent

    def __init__(self, action=None, data=None, type=None, flags=0,
                 categories=None, extras=None):
        self._action = action
        if data is None or isinstance(data, Uri):
            self._data = data
        else:
            self._data = Uri(data)
        self._type = type
        self._flags = int(flags or 0)
        self._categories = set(categories or [])
        self._extras = dict(extras or {})

    def getAction(self):
        return self._action

    def setAction(self, action):
        self._action = action

    def getData(self):
        return self._data

    def setData(self, data):
        self._data = data if data is None or isinstance(data, Uri) else Uri(data)

    def getType(self):
        return self._type

    def setType(self, value):
        self._type = value

    def getFlags(self):
        return self._flags

    def setFlags(self, flags):
        self._flags = int(flags or 0)

    def getCategories(self):
        return set(self._categories)

    def addCategory(self, category):
        if category:
            self._categories.add(str(category))

    def getExtras(self):
        return dict(self._extras)

    def hasExtra(self, name):
        return name in self._extras

    def getStringExtra(self, name):
        value = self._extras.get(name)
        return value if isinstance(value, str) else None

    def getIntExtra(self, name, default=0):
        try:
            return int(self._extras.get(name, default))
        except (TypeError, ValueError):
            return default

    def getBooleanExtra(self, name, default=False):
        return bool(self._extras.get(name, default))

    def putExtra(self, name, value):
        self._extras[name] = value
        return self

    def __str__(self):
        return "Intent(%s, %s)" % (self._action, self._data)


class HandlerType:
    BEFORE = 0
    AFTER = 1


@dataclass
class HandlerInfo:
    callback: Optional[Callable] = None
    scheme: Optional[str] = None
    host: Optional[str] = None
    path: Optional[str] = None
    required_path_args_names: Optional[List[str]] = None
    priority: Optional[int] = 0
    action: Optional[str] = None
    whitelist_flags: Optional[List[int]] = None
    blacklist_flags: Optional[List[int]] = None
    type: Optional[str] = None
    categories: Optional[List[str]] = None
    handler: Optional[Callable] = None
    name: Optional[str] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    @property
    def function(self):
        return self.callback or self.handler


class IntentsManager:
    HandlerInfo = HandlerInfo
    HandlerType = HandlerType
    _AS = ["tg", "https", "http"]

    @dataclass
    class _HandlerInfo:
        handler_id: str
        callback: Callable = field(compare=False, repr=False)
        hook_type: str = "before"
        priority: int = 0
        scheme: Optional[str] = None
        host: Optional[str] = None
        path: Optional[str] = None
        path_regex: Optional[str] = None
        required_path_args_names: tuple = field(default_factory=tuple)
        action: Optional[str] = None
        whitelist_flags: tuple = field(default_factory=tuple)
        blacklist_flags: tuple = field(default_factory=tuple)
        type: Optional[str] = None
        categories: tuple = field(default_factory=tuple)
        owner: str = ""

    @dataclass
    class HandlerHandle:
        handler_id: str = ""

        def unhandle(self):
            IntentsManager.unhandle(self.handler_id)

    class HandlerNotRegistered(Exception):
        def __init__(self, handler_id):
            super().__init__("Handler '%s' is not registered." % handler_id)

    _lock = threading.RLock()
    _handlers = {}
    _current_plugin = ""
    _before_handle = None
    _after_handle = None

    # -- Parsing -------------------------------------------------------------

    @staticmethod
    def parse(url):
        if "://" not in url:
            raise ValueError("Invalid uri: %s" % url)
        scheme, rest = url.split("://", 1)
        host, separator, path = rest.partition("/")
        result = {"scheme": scheme, "host": host}
        if separator:
            result["path"] = path
        if "?" in rest:
            result["query"] = rest.split("?", 1)[1]
        return result

    @classmethod
    def _normalize_path(cls, path):
        if path is None:
            return None
        path = str(path).strip()
        if not path:
            return None
        if not path.startswith("/"):
            path = "/" + path
        return path

    @classmethod
    def _build_path_regex(cls, path):
        if path is None:
            return None, ()
        result = []
        names = []
        last_index = 0
        for match in _PATH_ARG_RE.finditer(path):
            result.append(re.escape(path[last_index:match.start()]))
            result.append(r"[^/]+")
            names.append(match.group(1))
            last_index = match.end()
        result.append(re.escape(path[last_index:]))
        return "^" + "".join(result) + "$", tuple(names)

    @classmethod
    def _normalize_required_path_args_names(cls, names):
        if names is None:
            return ()
        normalized = []
        for name in names:
            current = str(name).strip()
            if current and current not in normalized:
                normalized.append(current)
        return tuple(normalized)

    @classmethod
    def _normalize_flags(cls, flags):
        if flags is None:
            return ()
        normalized = []
        for flag in flags:
            current = int(flag)
            if current not in normalized:
                normalized.append(current)
        return tuple(normalized)

    @classmethod
    def _normalize_categories(cls, categories):
        if categories is None:
            return ()
        normalized = []
        for category in categories:
            current = str(category).strip()
            if current and current not in normalized:
                normalized.append(current)
        return tuple(normalized)

    @classmethod
    def _make_handler_info(cls, callback, *, hook_type, scheme=None, host=None,
                           path=None, required_path_args_names=None,
                           action=None, priority=0, whitelist_flags=None,
                           blacklist_flags=None, type=None, categories=None):
        normalized_path = cls._normalize_path(path)
        path_regex, _ = cls._build_path_regex(normalized_path)
        return cls._HandlerInfo(
            handler_id=secrets.token_hex(16),
            callback=callback,
            hook_type=hook_type,
            priority=0 if priority is None else int(priority),
            scheme=None if scheme is None else str(scheme).strip().lower(),
            host=None if host is None else str(host).strip().lower(),
            path=normalized_path,
            path_regex=path_regex,
            required_path_args_names=cls._normalize_required_path_args_names(
                required_path_args_names
            ),
            action=None if action is None else str(action).strip(),
            whitelist_flags=cls._normalize_flags(whitelist_flags),
            blacklist_flags=cls._normalize_flags(blacklist_flags),
            type=None if type is None else str(type).strip(),
            categories=cls._normalize_categories(categories),
            owner=cls._current_plugin or "",
        )

    # -- Context -------------------------------------------------------------

    @classmethod
    def _extract_query_args(cls, data):
        if data is None:
            return {}
        query = data.getQuery()
        if not query:
            return {}
        result = {}
        for key, value in parse_qsl(str(query), keep_blank_values=True):
            if key:
                result[key] = value
        return result

    @classmethod
    def _extract_path_args(cls, path_template, actual_path):
        if not path_template or not actual_path:
            return {}
        template_parts = [part for part in path_template.split("/") if part]
        actual_parts = [part for part in str(actual_path).split("/") if part]
        if len(template_parts) != len(actual_parts):
            return {}
        result = {}
        for template_part, actual_part in zip(template_parts, actual_parts):
            match = _PATH_ARG_RE.fullmatch(template_part)
            if match:
                result[match.group(1)] = actual_part
            elif template_part != actual_part:
                return {}
        return result

    @classmethod
    def _build_callback_context(cls, info, intent):
        data = intent.getData()
        scheme = data.getScheme() if data is not None else None
        host = data.getHost() if data is not None else None
        path = data.getPath() if data is not None else None
        action = intent.getAction()
        flags = int(intent.getFlags())
        type_value = intent.getType()
        categories = {str(category) for category in intent.getCategories() if category is not None}
        query_args = cls._extract_query_args(data)
        path_args = cls._extract_path_args(info.path, path)
        named_context = {
            "intent": intent,
            "scheme": scheme,
            "host": host,
            "path": path,
            "query_args": query_args,
            "action": action,
            "flags": flags,
            "type": type_value,
            "categories": categories,
        }
        standard_args = [intent, scheme, host, path, query_args, action, flags,
                         type_value, categories]
        available = dict(named_context)
        available.update(path_args)
        available.update(query_args)
        return available, standard_args

    @classmethod
    def _invoke_handler_callback(cls, info, intent, payload=None):
        callback = info.callback
        available, standard_args = cls._build_callback_context(info, intent)
        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            return callback(intent)
        args = []
        kwargs = {}
        consumed_standard = set()
        bound_names = set()
        has_var_args = False
        has_var_kwargs = False
        standard_names = ("intent", "scheme", "host", "path", "query_args",
                          "action", "flags", "type", "categories")
        for parameter in signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
                has_var_args = True
                continue
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                has_var_kwargs = True
                continue
            if parameter.name not in available:
                continue
            value = available[parameter.name]
            bound_names.add(parameter.name)
            if parameter.name in standard_names:
                consumed_standard.add(parameter.name)
            if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                  inspect.Parameter.POSITIONAL_OR_KEYWORD):
                args.append(value)
            elif parameter.kind == inspect.Parameter.KEYWORD_ONLY:
                kwargs[parameter.name] = value
        if has_var_args:
            for name, value in zip(standard_names, standard_args):
                if name not in consumed_standard:
                    args.append(value)
        if has_var_kwargs:
            for key, value in available.items():
                if key not in kwargs and key not in bound_names:
                    kwargs[key] = value
        return callback(*args, **kwargs)

    # -- Matching ------------------------------------------------------------

    @classmethod
    def _matches(cls, info, intent):
        data = intent.getData()
        if info.action is not None:
            if intent.getAction() is None or intent.getAction() != info.action:
                return False
        if info.scheme is not None:
            if data is None or data.getScheme() is None:
                return False
            if data.getScheme().lower() != info.scheme:
                return False
        if info.host is not None:
            if data is None or data.getHost() is None:
                return False
            if data.getHost().lower() != info.host:
                return False
        if info.type is not None:
            if intent.getType() is None or intent.getType() != info.type:
                return False
        if info.path_regex is not None:
            if data is None or data.getPath() is None:
                return False
            if re.match(info.path_regex, data.getPath()) is None:
                return False
        if info.required_path_args_names:
            if data is None:
                return False
            for name in info.required_path_args_names:
                if data.getQueryParameter(name) is None:
                    return False
        if info.categories:
            categories = intent.getCategories()
            if not categories:
                return False
            for category in info.categories:
                if category not in categories:
                    return False
        flags = int(intent.getFlags())
        for flag in info.whitelist_flags:
            if flags & flag != flag:
                return False
        for flag in info.blacklist_flags:
            if flags & flag != 0:
                return False
        return True

    @classmethod
    def _dispatch_matched(cls, matched, hook_type, intent, payload=None):
        try:
            ordered = sorted(matched, key=lambda info: info.priority)
            for info in ordered:
                result = cls._invoke_handler_callback(info, intent, payload)
                if hook_type == "before" and result is True:
                    return True
        except Exception:
            log("Failed to dispatch intent handlers: %s" % traceback.format_exc())
        return False

    # -- Host bridge ---------------------------------------------------------

    @classmethod
    def _ensure_host_handlers(cls):
        if cls._before_handle is None:
            cls._before_handle = extera_ios.retain(cls._host_dispatch_before)
            extera_ios.register_intent_handler(
                "", {"type": "url", "priority": 0}, cls._before_handle, before=True
            )
        if cls._after_handle is None:
            cls._after_handle = extera_ios.retain(cls._host_dispatch_after)
            extera_ios.register_intent_handler(
                "", {"type": "url", "priority": 0}, cls._after_handle, before=False
            )

    @classmethod
    def _dispose_host_handlers(cls):
        if cls._before_handle is not None:
            extera_ios.unregister_intent_handler("", cls._before_handle)
            extera_ios.release(cls._before_handle)
            cls._before_handle = None
        if cls._after_handle is not None:
            extera_ios.unregister_intent_handler("", cls._after_handle)
            extera_ios.release(cls._after_handle)
            cls._after_handle = None

    @classmethod
    def _intent_from_payload(cls, payload):
        if isinstance(payload, Intent):
            return payload
        if not isinstance(payload, dict):
            return Intent(action=Intent.ACTION_VIEW, data=Uri(str(payload)))
        url = payload.get("url") or payload.get("data") or ""
        uri = Uri(
            url,
            scheme=payload.get("scheme") or None,
            host=payload.get("host") or None,
            path=payload.get("path") or None,
            query=payload.get("query") or None,
        )
        categories = payload.get("categories")
        return Intent(
            action=payload.get("action") or Intent.ACTION_VIEW,
            data=uri,
            type=payload.get("mime_type") or payload.get("intent_type"),
            flags=payload.get("flags") or 0,
            categories=categories if isinstance(categories, (list, tuple, set)) else None,
            extras=payload.get("extras") or {},
        )

    @classmethod
    def _host_dispatch(cls, payload, hook_type):
        try:
            intent = cls._intent_from_payload(payload)
            with cls._lock:
                candidates = list(cls._handlers.values())
            matched = [info for info in candidates
                       if info.hook_type == hook_type and cls._matches(info, intent)]
            return cls._dispatch_matched(matched, hook_type, intent, payload)
        except Exception:
            log("Failed to dispatch intent handlers: %s" % traceback.format_exc())
            return False

    @classmethod
    def _host_dispatch_before(cls, payload):
        return cls._host_dispatch(payload, "before")

    @classmethod
    def _host_dispatch_after(cls, payload):
        return cls._host_dispatch(payload, "after")

    # -- Public API ----------------------------------------------------------

    @classmethod
    def _install_handler(cls, info):
        with cls._lock:
            cls._handlers[info.handler_id] = info
        cls._ensure_host_handlers()
        return cls.HandlerHandle(info.handler_id)

    @classmethod
    def _coerce_handler_info(cls, info=None, options=None):
        options = dict(options or {})
        if isinstance(info, HandlerInfo):
            return info
        if callable(info):
            options.pop("callback", None)
            options.pop("handler", None)
            options.pop("function", None)
            return HandlerInfo(callback=info, **options)
        if info is None:
            callback = options.pop("callback", None)
            if callback is None:
                callback = options.pop("handler", None)
            if callback is None:
                callback = options.pop("function", None)
            return HandlerInfo(callback=callback, **options)
        raise TypeError("Expected HandlerInfo or a callable callback")

    @classmethod
    def new_global_before_handler(cls, info=None, **options):
        info = cls._coerce_handler_info(info, options)
        return cls._install_handler(cls._make_handler_info(
            info.function,
            hook_type="before",
            scheme=info.scheme,
            host=info.host,
            path=info.path,
            required_path_args_names=info.required_path_args_names,
            priority=info.priority,
            action=info.action,
            whitelist_flags=info.whitelist_flags,
            blacklist_flags=info.blacklist_flags,
            type=info.type,
            categories=info.categories,
        ))

    @classmethod
    def new_global_after_handler(cls, info=None, **options):
        info = cls._coerce_handler_info(info, options)
        return cls._install_handler(cls._make_handler_info(
            info.function,
            hook_type="after",
            scheme=info.scheme,
            host=info.host,
            path=info.path,
            required_path_args_names=info.required_path_args_names,
            priority=info.priority,
            action=info.action,
            whitelist_flags=info.whitelist_flags,
            blacklist_flags=info.blacklist_flags,
            type=info.type,
            categories=info.categories,
        ))

    @classmethod
    def unhandle(cls, handler_id):
        with cls._lock:
            if handler_id not in cls._handlers:
                raise cls.HandlerNotRegistered(handler_id)
            cls._handlers.pop(handler_id, None)
            remaining = bool(cls._handlers)
        if not remaining:
            cls._dispose_host_handlers()

    @classmethod
    def remove_handlers_for_plugin(cls, plugin_id):
        with cls._lock:
            ids = [key for key, info in cls._handlers.items()
                   if info.owner == plugin_id]
            for key in ids:
                cls._handlers.pop(key, None)
            remaining = bool(cls._handlers)
        if not remaining:
            cls._dispose_host_handlers()

    @classmethod
    def _stop(cls):
        with cls._lock:
            cls._handlers.clear()
        cls._dispose_host_handlers()

    # -- iOS compatibility helpers ------------------------------------------

    @classmethod
    def _dispatch(cls, handler_id, payload):
        """Invokes one handler directly, for hosts that route per handler."""
        with cls._lock:
            info = cls._handlers.get(handler_id)
        if info is None:
            return None
        if isinstance(payload, dict) and not any(
            key in payload for key in ("url", "data", "scheme", "host", "path", "action")
        ):
            return info.callback(payload)
        return cls._invoke_handler_callback(info, cls._intent_from_payload(payload))


@dataclass
class HandlerHandle:
    handler_id: str = ""
    _manager: Any = None

    def unhandle(self):
        IntentsManager.unhandle(self.handler_id)

    def __repr__(self):
        return "<HandlerHandle %s>" % self.handler_id


@dataclass
class IntentInfo:
    action: str
    data: Optional[str] = None
    package: Optional[str] = None
    component: Optional[str] = None
    extras: Dict[str, Any] = field(default_factory=dict)


def send_intent(intent):
    return extera_ios.host(
        "intent.send",
        action=getattr(intent, "action", None),
        data=getattr(intent, "data", None),
        extras=getattr(intent, "extras", {}) or {},
    )
