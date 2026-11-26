# This is the iOS counterpart of the exteraGram plugins SDK.
#
# `base_plugin` keeps the public API of exteraGram: the same class names, the
# same hook names, the same `HookResult` shape and the same settings helpers.
# What changes is the layer underneath:
#
#   * `add_hook` registers a name with the Swift hook registry instead of a Java
#     notification centre;
#   * `hook_method` swizzles an Objective-C selector instead of an ART method;
#   * `hook_call_site`/`hook_field_*`/`hook_return_value` map Android's bytecode
#     targets onto the closest member-level hooks (`hook_string_constant` has no
#     iOS equivalent and reports "not installed"; the plugin still loads).
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import contextlib
import contextvars
import functools
import inspect
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import _sdk_version
import extera_ios
import plugin_settings
from log_utils import Logger, _plugin_logger, _reset_plugin_logger
from extera_utils import lifecycle


@dataclass
class PluginMetadata:
    id: str
    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0"
    icon: str = ""
    min_version: str = ""
    requirements: List[str] = field(default_factory=list)


class HookStrategy(Enum):
    CANCEL = "CANCEL"
    MODIFY = "MODIFY"
    DEFAULT = "DEFAULT"
    MODIFY_FINAL = "MODIFY_FINAL"
    # Compatibility aliases used by published plugins.  They resolve to the
    # Android strategy with the same effect: NONE/PASS leave the value alone,
    # BLOCK stops the call like CANCEL.
    NONE = "DEFAULT"
    PASS = "DEFAULT"
    BLOCK = "CANCEL"


class IntentHookType(Enum):
    BEFORE = 0
    AFTER = 1


@dataclass
class HookResult:
    strategy: HookStrategy = HookStrategy.DEFAULT
    request: Any = None
    response: Any = None
    update: Any = None
    updates: Any = None
    error: Any = None
    params: Any = None


class PluginError(Exception):
    plugin_id: Optional[str]

    def __init__(self, message, plugin_id=None):
        super().__init__(message)
        self.plugin_id = plugin_id


_PARTIAL_PRIMITIVES = None
_PARTIAL_API = None


def _partial_primitives():
    """Primitive casters used by partial-hook argument marshalling.

    Android returns Chaquopy's `jint`, `jboolean`, ... types.  The iOS runtime
    has no JVM, so the same names map to Python casters with the same accepted
    input and output values.
    """
    global _PARTIAL_PRIMITIVES
    if _PARTIAL_PRIMITIVES is None:
        _PARTIAL_PRIMITIVES = {
            "boolean": bool,
            "byte": lambda value: int(value),
            "char": lambda value: value if isinstance(value, str) else chr(int(value)),
            "short": int,
            "int": int,
            "long": int,
            "float": float,
            "double": float,
        }
    return _PARTIAL_PRIMITIVES


def _to_java_value(value, java_type):
    if value is None or java_type is None:
        return value
    name = java_type.get_name() if hasattr(java_type, "get_name") else str(java_type)
    primitive = bool(java_type.is_primitive()) if hasattr(java_type, "is_primitive") else False
    boxed = {
        "java.lang.Boolean": "boolean", "java.lang.Byte": "byte",
        "java.lang.Character": "char", "java.lang.Short": "short",
        "java.lang.Integer": "int", "java.lang.Long": "long",
        "java.lang.Float": "float", "java.lang.Double": "double",
    }.get(name)
    if not primitive and boxed is None:
        return value
    wrapper = _partial_primitives().get(name if primitive else boxed)
    if wrapper is None or not isinstance(value, (bool, int, float, str)):
        return value
    try:
        return wrapper(value)
    except (TypeError, ValueError, OverflowError):
        return value


def _partial_api():
    """Android's partial-hook factory, mapped onto method-level iOS hooks.

    `com.exteragram.hook` keeps the Android surface (`ExteraHook`, `HookTarget`,
    `InstructionMatcher`, `Interceptor`).  The iOS implementation installs the
    closest equivalent - an Objective-C hook on the member the target names -
    and reports targets it cannot express (string literals) as "not installed".
    """
    global _PARTIAL_API
    if _PARTIAL_API is not None:
        return _PARTIAL_API
    try:
        from com.exteragram.hook import (
            ExteraHook,
            HookTarget,
            InstructionMatcher,
            Interceptor,
        )
        from java import dynamic_proxy, jarray
        from java.lang import Object as JavaObject
    except ImportError as error:
        raise PluginError("Partial hooks need a newer exteraGram: %s" % error)
    try:
        from com.exteragram.messenger.plugins import PluginsController
    except ImportError as error:
        raise PluginError("Partial hooks need a newer exteraGram: %s" % error)

    if not hasattr(PluginsController.getInstance(), "addPartialHook"):
        raise PluginError(
            "Partial hooks need a newer exteraGram: "
            "PluginsController.addPartialHook is missing"
        )

    class _Interceptor(dynamic_proxy(Interceptor)):
        def __init__(self, plugin, callback, param_types, result_type):
            super().__init__()
            self._plugin = plugin
            self._callback = callback
            self._param_types = param_types
            self._result_type = result_type

        def intercept(self, chain):
            scope = getattr(self._plugin, "_lifecycle", None)
            if scope is not None and scope.stop_event.is_set():
                return chain.proceed()
            wrapped = PartialChain(chain, self._param_types)
            try:
                result = self._callback(wrapped)
            except Exception:
                if not wrapped.threw:
                    Logger(
                        "%s: Partial hook error" % getattr(self._plugin, "id", "plugin")
                    ).error(traceback.format_exc())
                raise
            return _to_java_value(result, self._result_type)

    _PARTIAL_API = {
        "ExteraHook": ExteraHook,
        "HookTarget": HookTarget,
        "InstructionMatcher": InstructionMatcher,
        "Interceptor": _Interceptor,
        "jarray": jarray,
        "Object": JavaObject,
    }
    return _PARTIAL_API


def _while_plugin_active(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        scope = getattr(self, "_lifecycle", None)
        if scope is None:
            return method(self, *args, **kwargs)
        with scope._lock:
            if scope.stop_event.is_set():
                return None
            return method(self, *args, **kwargs)

    return wrapped


def _is_method_hook_phase_enabled(hook, method_name):
    callback = getattr(hook, method_name, None)
    if not callable(callback):
        return False
    implementation = getattr(callback, "__func__", callback)
    return implementation is not getattr(MethodHook, method_name)


class AppEvent(Enum):
    START = "app_start"
    STOP = "app_stop"
    PAUSE = "app_pause"
    RESUME = "app_resume"


class MenuItemType(Enum):
    MESSAGE_CONTEXT_MENU = "message_context_menu"
    DRAWER_MENU = "drawer_menu"
    MAIN_MENU = "main_menu"
    CHAT_ACTION_MENU = "chat_action_menu"
    PROFILE_ACTION_MENU = "profile_action_menu"


@dataclass
class MenuItemData:
    menu_type: MenuItemType
    text: str
    on_click: Callable[[Dict[str, Any]], None]
    item_id: Optional[str] = None
    icon: Optional[str] = None
    subtext: Optional[str] = None
    condition: Optional[str] = None
    priority: int = 0
    on_long_click: Optional[Callable[[Dict[str, Any]], None]] = None


@dataclass
class HookFilterData:
    filter_type: str
    arg_index: Optional[int] = None
    or_filters: Optional[Any] = None
    mvel_expression: Optional[str] = None
    instance_of: Optional[Any] = None
    object: Any = None

    def to_native(self):
        value = {"type": self.filter_type}
        if self.arg_index is not None:
            value["arg_index"] = int(self.arg_index)
        if self.mvel_expression is not None:
            value["expression"] = str(self.mvel_expression)
        if self.instance_of is not None:
            value["instance_of"] = str(getattr(self.instance_of, "__name__", self.instance_of))
        if self.object is not None:
            value["object"] = self.object
        if self.or_filters is not None:
            value["or"] = [item.to_native() if hasattr(item, "to_native") else item
                           for item in self.or_filters]
        return value

    def to_java_filter(self):
        return self.to_native()


class HookFilter(Enum):
    RESULT_IS_NULL = "result_is_null"
    RESULT_IS_TRUE = "result_is_true"
    RESULT_IS_FALSE = "result_is_false"
    RESULT_NOT_NULL = "result_not_null"

    @property
    def filter_data(self):
        return HookFilterData(filter_type=self.value)

    @staticmethod
    def ResultIsInstanceOf(clazz):
        return HookFilterData("result_is_instance_of", instance_of=clazz)

    @staticmethod
    def ResultEqual(value):
        return HookFilterData("result_equal", object=value)

    @staticmethod
    def ResultNotEqual(value):
        return HookFilterData("result_not_equal", object=value)

    @staticmethod
    def ArgumentIsNull(index):
        return HookFilterData("argument_is_null", arg_index=index)

    @staticmethod
    def ArgumentIsTrue(index):
        return HookFilterData("argument_is_true", arg_index=index)

    @staticmethod
    def ArgumentIsFalse(index):
        return HookFilterData("argument_is_false", arg_index=index)

    @staticmethod
    def ArgumentNotNull(index):
        return HookFilterData("argument_not_null", arg_index=index)

    @staticmethod
    def ArgumentIsInstanceOf(index, clazz):
        return HookFilterData("argument_is_instance_of", arg_index=index, instance_of=clazz)

    @staticmethod
    def ArgumentEqual(index, value):
        return HookFilterData("argument_equal", arg_index=index, object=value)

    @staticmethod
    def ArgumentNotEqual(index, value):
        return HookFilterData("argument_not_equal", arg_index=index, object=value)

    @staticmethod
    def Condition(condition, object=None):
        return HookFilterData("condition", mvel_expression=condition, object=object)

    @staticmethod
    def Or(*filters):
        values = [item for item in filters if item is not None]
        if not values:
            return None
        return HookFilterData("or", or_filters=values)


def hook_filters(*filters):
    flat = filters[0] if len(filters) == 1 and isinstance(filters[0], list) else filters

    def decorator(function):
        function.__hook_filters__ = [item.to_native() if hasattr(item, "to_native") else item
                                     for item in flat]
        return function

    return decorator


def fn_hook_filters(field_name):
    def decorator(function):
        function.__hook_filters__ = lambda self: [
            item.to_native() if hasattr(item, "to_native") else item
            for item in (getattr(self, field_name, None) or [])
        ]
        return function

    return decorator


class XposedHook(ABC):
    pass


class MethodReplacement(XposedHook):
    @abstractmethod
    def replace_hooked_method(self, param):
        pass


class MethodHook(XposedHook):
    def before_hooked_method(self, param):
        pass

    def after_hooked_method(self, param):
        pass


class BaseHook(MethodHook):
    def __init__(self, plugin=None, *, before=None, after=None,
                 before_filters=None, after_filters=None):
        self.plugin = plugin
        self.before = before
        self.after = after
        self.before_filters = before_filters
        self.after_filters = after_filters

    @fn_hook_filters("before_filters")
    def before_hooked_method(self, param):
        if self.before:
            try:
                self.before(param)
            except Exception:
                prefix = "%s: " % self.plugin.id if self.plugin else ""
                Logger(prefix or "hook").error(traceback.format_exc())

    @fn_hook_filters("after_filters")
    def after_hooked_method(self, param):
        if self.after:
            try:
                self.after(param)
            except Exception:
                prefix = "%s: " % self.plugin.id if self.plugin else ""
                Logger(prefix or "hook").error(traceback.format_exc())


class PartialChain:
    """One interception of a partial hook.

    `this_object` is the receiver of the hooked call or the object that owns the
    field, `caller` is the `this` of the method that contains the hooked place
    (always `None` on iOS: a method-level hook cannot see its caller), `args`
    are the call arguments, `[value]` for field writes and instruction hooks.
    `proceed()` runs the original implementation; `proceed(*args)` runs it with
    new arguments.
    """

    __slots__ = ("java", "threw", "_param_types")

    def __init__(self, chain=None, param_types=None):
        self.java = chain
        self.threw = False
        self._param_types = param_types or []

    @property
    def this_object(self):
        getter = getattr(self.java, "getThisObject", None)
        if callable(getter):
            return getter()
        return getattr(self.java, "this_object", None)

    @property
    def caller(self):
        getter = getattr(self.java, "getCaller", None)
        if callable(getter):
            return getter()
        return getattr(self.java, "caller", None)

    @property
    def args(self):
        getter = getattr(self.java, "getArgs", None)
        if callable(getter):
            return list(getter())
        return list(getattr(self.java, "args", []))

    def arg(self, index):
        getter = getattr(self.java, "arg", None)
        if callable(getter):
            return getter(index)
        args = self.args
        return args[index] if 0 <= index < len(args) else None

    def proceed(self, *args):
        if self.java is None:
            return None
        if not args:
            return self.java.proceed()
        if len(args) != len(self._param_types):
            raise TypeError(
                "proceed() takes %d arguments, got %d"
                % (len(self._param_types), len(args))
            )
        api = _partial_api()
        values = [
            _to_java_value(value, java_type)
            for value, java_type in zip(args, self._param_types)
        ]
        return self.java.proceed(api["jarray"](api["Object"])(values))

    def throw_to_caller(self, throwable):
        self.threw = True
        method = getattr(self.java, "throwToCaller", None)
        if callable(method):
            method(throwable)
        elif self.java is not None and hasattr(self.java, "throw_to_caller"):
            self.java.throw_to_caller(throwable)


_HOOK_ACCOUNT_ARG = {
    "pre_request_hook": 1,
    "post_request_hook": 1,
    "on_update_hook": 1,
    "on_updates_hook": 1,
    "on_send_message_hook": 0,
}

_hook_account = contextvars.ContextVar("extera_ios_hook_account", default=None)


@contextlib.contextmanager
def account_scope(account):
    token = _hook_account.set(account)
    try:
        yield
    finally:
        _hook_account.reset(token)


def get_hook_account():
    return _hook_account.get()


def _account_scoped_hook(fn, account_index):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        account = args[account_index] if len(args) > account_index else kwargs.get("account")
        with account_scope(account):
            return fn(self, *args, **kwargs)

    wrapper.__extera_account_scoped__ = True
    return wrapper


class BasePlugin:
    def __new__(cls):
        _sdk_version.Z.c()
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name, account_index in _HOOK_ACCOUNT_ARG.items():
            function = cls.__dict__.get(name)
            if function is None or getattr(function, "__extera_account_scoped__", False):
                continue
            try:
                setattr(cls, name, _account_scoped_hook(function, account_index))
            except Exception as error:
                Logger(cls.__name__).warning("Could not account-scope %s: %s" % (name, error))

    _fh = {}
    _ih = {}

    @classmethod
    def _findPluginClass(cls, module):
        for _, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, cls) and obj is not cls:
                return obj
        return None

    @classmethod
    def _cleanup(cls, plugin_id):
        for extension, secret in list(cls._fh.pop(plugin_id, [])):
            try:
                from file_utils import FilesController

                FilesController.unregister(extension, secret)
            except Exception:
                Logger(plugin_id).error(traceback.format_exc())
        for handler in cls._ih.pop(plugin_id, []):
            try:
                handler.unhandle()
            except Exception:
                pass
        _reset_plugin_logger(plugin_id)

    _begin_lifecycle = staticmethod(lifecycle.begin)
    _stop_lifecycle = staticmethod(lifecycle.stop)
    _stop_all_lifecycles = staticmethod(lifecycle.stop_all)

    def __init__(self):
        _sdk_version.Z.c()
        self._lifecycle = lifecycle.capture_scope(type(self))
        self.id = ""
        self.name = ""
        self.description = ""
        self.author = ""
        self.min_version = ""
        self.version = ""
        self.requirements = []
        self.icon = None
        self.error_message = None
        self.enabled = False
        self.initialized = False
        self._menu_items = {}
        self._menu_counter = 0

    @property
    def stop_event(self):
        return self._lifecycle.stop_event if self._lifecycle is not None else None

    def register_cleanup(self, cleanup):
        if self._lifecycle is None:
            raise RuntimeError("Plugin lifecycle is not initialized")
        return self._lifecycle.register_cleanup(cleanup)

    def on_plugin_load(self):
        _sdk_version.Z.c()

    def _invoke_plugin_unload(self):
        with lifecycle.cleanup_context(self._lifecycle):
            self.on_plugin_unload()

    def on_plugin_unload(self):
        pass

    def create_settings(self):
        _sdk_version.Z.c()
        return []

    def on_app_event(self, event_type):
        _sdk_version.Z.c()

    def pre_request_hook(self, request_name, account, request):
        return HookResult()

    def post_request_hook(self, request_name, account, response, error):
        return HookResult()

    def on_update_hook(self, update_name, account, update):
        return HookResult()

    def on_updates_hook(self, container_name, account, updates):
        return HookResult()

    def on_send_message_hook(self, account, params):
        return HookResult()

    def _while_active(self):
        if self._lifecycle is not None and self._lifecycle.stop_event.is_set():
            return False
        return True

    def add_hook(self, name, match_substring=False, priority=0):
        if not self.id or not name or self.error_message or not self._while_active():
            return None
        return extera_ios.register_event_hook(self.id, name, match_substring, priority)

    def add_on_send_message_hook(self, priority=0):
        return self.add_hook("send_message_hook", False, priority)

    def remove_hook(self, name):
        if not self.id or not name:
            return None
        return extera_ios.remove_event_hook(self.id, name)

    def add_file_hook(self, file_info):
        if file_info is None:
            raise ValueError("You must provide a file info (instance of FilesController.FileInfo)")
        from file_utils import FilesController

        FilesController._current_plugin = self.id
        secret = FilesController.register(file_info)
        BasePlugin._fh[self.id] = BasePlugin._fh.get(self.id, []) + [
            (getattr(file_info, "ext", None), secret)
        ]
        return secret

    def remove_file_hook(self, ext, secret):
        if not ext or not secret:
            raise ValueError("You must provide a file extension and secret for unregister")
        from file_utils import FilesController

        FilesController.unregister(ext, secret)
        self._fh[self.id] = [item for item in self._fh.get(self.id, []) if item[0] != ext]

    def add_intent_hook(self, info, type):
        from intents import IntentsManager

        if info is None:
            raise ValueError("You must provide a handler info (instance of IntentsManager.HandlerInfo)")
        if type is None:
            raise ValueError("You must provide a handler type (instance of IntentHookType)")
        IntentsManager._current_plugin = self.id
        if type == IntentHookType.BEFORE:
            handler = IntentsManager.new_global_before_handler(info)
        else:
            handler = IntentsManager.new_global_after_handler(info)
        BasePlugin._ih[self.id] = BasePlugin._ih.get(self.id, []) + [handler]
        return handler

    def remove_intent_hook(self, handler_id):
        from intents import IntentsManager

        if hasattr(handler_id, "unhandle"):
            handler_id.unhandle()
        else:
            IntentsManager.unhandle(handler_id)

    def get_setting(self, key, default=None):
        if not self.id or not key or self.error_message:
            return default
        return plugin_settings.get_setting(self.id, key, default)

    def set_setting(self, key, value, reload_settings=False):
        if not self.id or not key or self.error_message:
            return
        plugin_settings.set_setting(self.id, key, value)
        if reload_settings:
            extera_ios.reload_plugin_settings(self.id)

    def export_settings(self):
        if not self.id or self.error_message:
            return {}
        return plugin_settings.get_all_settings(self.id)

    def import_settings(self, settings, reload_settings=True):
        if not self.id or self.error_message:
            return
        plugin_settings.set_all_settings(self.id, settings)
        if reload_settings:
            extera_ios.reload_plugin_settings(self.id)

    # -- method hooks -------------------------------------------------------

    def _callback_handles(self, hook_instance):
        """Returns {'before'|'after'|'replace': handle} for a hook object."""
        if isinstance(hook_instance, BaseHook):
            handles = {}
            if hook_instance.before is not None:
                handles["before"] = extera_ios.retain(hook_instance.before)
            if hook_instance.after is not None:
                handles["after"] = extera_ios.retain(hook_instance.after)
            return handles

        if isinstance(hook_instance, MethodReplacement) or hasattr(hook_instance, "replace_hooked_method"):
            return {"replace": extera_ios.retain(hook_instance.replace_hooked_method)}

        if isinstance(hook_instance, MethodHook):
            before = hook_instance.before_hooked_method
            after = hook_instance.after_hooked_method
            has_before = getattr(before, "__func__", before) is not MethodHook.before_hooked_method
            has_after = getattr(after, "__func__", after) is not MethodHook.after_hooked_method
            handles = {}
            if has_before:
                handles["before"] = extera_ios.retain(before)
            if has_after:
                handles["after"] = extera_ios.retain(after)
            return handles

        before = getattr(hook_instance, "before_hooked_method", None)
        after = getattr(hook_instance, "after_hooked_method", None)
        handles = {}
        if callable(before):
            handles["before"] = extera_ios.retain(before)
        if callable(after):
            handles["after"] = extera_ios.retain(after)
        return handles

    @staticmethod
    def _native_filters(filters):
        return [item.to_native() if hasattr(item, "to_native") else item
                for item in (filters or [])]

    def _hook_filters_for(self, hook_instance, before_filters=None, after_filters=None):
        """Collects explicit and decorator-declared filters per phase."""
        before = list(before_filters or [])
        after = list(after_filters or [])

        if isinstance(hook_instance, BaseHook):
            before = list(hook_instance.before_filters or []) + before
            after = list(hook_instance.after_filters or []) + after
        else:
            for name, target in (("before_hooked_method", before), ("after_hooked_method", after)):
                callback = getattr(hook_instance, name, None)
                if not callable(callback):
                    continue
                declared = getattr(getattr(callback, "__func__", callback), "__hook_filters__", None)
                if declared is None:
                    continue
                if callable(declared):
                    try:
                        declared = declared(hook_instance)
                    except TypeError:
                        try:
                            declared = declared()
                        except TypeError:
                            declared = None
                if declared:
                    target.extend(declared)

        return self._native_filters(before), self._native_filters(after)

    def _install_hook(self, target, hook_instance, priority=None, filters=None, *,
                      before_filters=None, after_filters=None):
        if target is None:
            self.log("hook target is None")
            return None
        handles = self._callback_handles(hook_instance)
        if not handles:
            return None
        before_native, after_native = self._hook_filters_for(
            hook_instance, before_filters, after_filters
        )
        combined = self._native_filters(filters) if filters else before_native + after_native
        class_name = getattr(target, "class_name", None) or getattr(target, "_name", None) or target
        member = getattr(target, "name", target)
        result = extera_ios.host(
            "runtime.swizzle",
            class_name=str(class_name),
            selector=str(member),
            callbacks=handles,
            priority=int(priority or 0),
            filters=combined,
            before_filters=before_native,
            after_filters=after_native,
        )
        return result

    def hook_method(self, method_or_constructor, xposed_hook=None, priority=None, *,
                    before=None, after=None, before_filters=None, after_filters=None):
        _sdk_version.Z.c()
        if not self._while_active():
            return None
        if xposed_hook is None and before is None and after is None:
            raise TypeError("xposed_hook or before or after cannot be None")
        if xposed_hook is None:
            xposed_hook = BaseHook(self, before=before, after=after,
                                   before_filters=before_filters,
                                   after_filters=after_filters)
        try:
            result = self._install_hook(
                method_or_constructor, xposed_hook, priority,
                before_filters=before_filters, after_filters=after_filters,
            )
            if result:
                extera_ios.host("hooks.add_xposed", plugin_id=self.id, handle=result)
            return result
        except Exception as error:
            self.log("Error while hooking method: %s" % error)
            return None

    def hook_all_methods(self, hook_class, method_name, xposed_hook=None, priority=None, *,
                         before=None, after=None, before_filters=None, after_filters=None):
        _sdk_version.Z.c()
        if not self._while_active():
            return None
        class_name = getattr(hook_class, "__name__", hook_class)
        result = self.hook_method(
            type("Target", (), {"class_name": class_name, "name": method_name})(),
            xposed_hook, priority, before=before, after=after,
            before_filters=before_filters, after_filters=after_filters,
        )
        return [result] if result else None

    def hook_all_constructors(self, hook_class, xposed_hook=None, priority=None, *,
                              before=None, after=None, before_filters=None, after_filters=None):
        # Objective-C initialisers are selectors beginning with `init`; hooking
        # every one of them is the closest equivalent of `hookAllConstructors`.
        return self.hook_all_methods(hook_class, "init", xposed_hook, priority,
                                     before=before, after=after,
                                     before_filters=before_filters,
                                     after_filters=after_filters)

    def unhook_method(self, unhook):
        if unhook:
            extera_ios.host("runtime.unswizzle", handle=unhook)

    # -- instruction-level hooks -------------------------------------------
    #
    # Android intercepts one bytecode instruction.  iOS has no bytecode, so the
    # targets map onto the closest member-level hooks: a call site hooks the
    # callee selector, field reads/writes hook the getter/setter, and return
    # filters hook the containing method's return.  A string-literal target has
    # no iOS equivalent and reports "not installed".

    def _partial_targets_missing(self, kind, **targets):
        missing = [name for name, value in targets.items() if value is None]
        if missing:
            self.log(
                "Cannot install a partial %s hook: %s is None"
                % (kind, ", ".join(missing))
            )
        return bool(missing)

    def _install_partial(self, target, callback, priority, param_types,
                         result_type, description):
        _sdk_version.Z.c()
        if callback is None:
            raise TypeError("callback cannot be None")
        api = _partial_api()
        try:
            builder = api["ExteraHook"].hook(target)
            if priority is not None:
                builder = builder.priority(priority)
            handle = builder.intercept(
                api["Interceptor"](self, callback, param_types, result_type)
            )
        except Exception as error:
            self.log(
                "Error while installing a partial hook on %s: %s"
                % (description, error)
            )
            return None
        try:
            from com.exteragram.messenger.plugins import PluginsController

            PluginsController.getInstance().addPartialHook(self.id, handle)
        except Exception:
            pass
        return handle

    def hook_call_site(self, in_method, callee, callback, occurrence=-1, priority=None):
        """Intercepts calls to `callee` made from inside `in_method` only.

        iOS maps this to a hook on `callee`; `occurrence` is accepted and
        ignored because one selector is one hook point.
        """
        if self._partial_targets_missing("call site", in_method=in_method, callee=callee):
            return None
        target = _partial_api()["HookTarget"].callSite(in_method, callee, occurrence)
        return self._install_partial(
            target, callback, priority,
            list(callee.getParameterTypes()), callee.getReturnType(),
            "%s in %s" % (callee.getName(), in_method.getName()),
        )

    def hook_field_read(self, in_method, field, callback, occurrence=-1, priority=None):
        """Intercepts reads of `field` inside `in_method`; `proceed()` returns
        the stored value."""
        if self._partial_targets_missing("field read", in_method=in_method, field=field):
            return None
        target = _partial_api()["HookTarget"].fieldRead(in_method, field, occurrence)
        return self._install_partial(
            target, callback, priority, [], field.getType(),
            "reads of %s in %s" % (field.getName(), in_method.getName()),
        )

    def hook_field_write(self, in_method, field, callback, occurrence=-1, priority=None):
        """Intercepts writes of `field` inside `in_method`; `proceed(value)`
        stores a different value, not calling `proceed` skips the write."""
        if self._partial_targets_missing("field write", in_method=in_method, field=field):
            return None
        target = _partial_api()["HookTarget"].fieldWrite(in_method, field, occurrence)
        return self._install_partial(
            target, callback, priority, [field.getType()], None,
            "writes of %s in %s" % (field.getName(), in_method.getName()),
        )

    def hook_string_constant(self, in_method, text, callback, occurrence=-1,
                             priority=None):
        """Replaces the string literal `text` inside `in_method` with what the
        callback returns.  String literals are bytecode; iOS reports the hook as
        not installed and `hook_return_value` can filter the method result."""
        if self._partial_targets_missing("string constant", in_method=in_method):
            return None
        api = _partial_api()
        target = api["HookTarget"].instruction(
            in_method, api["InstructionMatcher"].constString(text, occurrence)
        )
        from extera_utils.classes import ClassRef

        string_class = ClassRef("java.lang.String")
        return self._install_partial(
            target, callback, priority, [string_class], string_class,
            '"%s" in %s' % (text, in_method.getName()),
        )

    def hook_return_value(self, in_method, callback, occurrence=-1, priority=None):
        """Filters the values returned by the return instructions of `in_method`."""
        if self._partial_targets_missing("return value", in_method=in_method):
            return None
        api = _partial_api()
        target = api["HookTarget"].instruction(
            in_method, api["InstructionMatcher"].returnValue(occurrence)
        )
        return_type = in_method.getReturnType()
        return self._install_partial(
            target, callback, priority, [return_type], return_type,
            "returns of %s" % in_method.getName(),
        )

    def unhook_partial(self, handle):
        try:
            from com.exteragram.messenger.plugins import PluginsController

            PluginsController.getInstance().removePartialHook(self.id, handle)
        except Exception:
            if handle:
                extera_ios.host("runtime.unswizzle", handle=handle)

    # -- logging and menus --------------------------------------------------

    @property
    def logger(self):
        custom = self.__dict__.get("_custom_logger")
        if custom is not None:
            return custom
        if getattr(self, "id", ""):
            return _plugin_logger(self.id)
        return Logger("plugin.%s" % type(self).__name__)

    @logger.setter
    def logger(self, value):
        self.__dict__["_custom_logger"] = value

    def log(self, message):
        extera_ios.log("[%s] %s" % (self.id, message))

    def client(self, account=None):
        from client_utils import get_client

        return get_client(account)

    def add_menu_item(self, menu_item_data):
        if not self.id or self.error_message or menu_item_data is None:
            return None
        if not menu_item_data.item_id:
            self._menu_counter += 1
            menu_item_data.item_id = "%s.%d" % (self.id, self._menu_counter)
        data = {
            "menu_type": menu_item_data.menu_type.value,
            "text": menu_item_data.text,
            "item_id": menu_item_data.item_id,
            "icon": menu_item_data.icon,
            "subtext": menu_item_data.subtext,
            "condition": menu_item_data.condition,
            "priority": int(menu_item_data.priority),
            "on_click": extera_ios.retain(menu_item_data.on_click),
            "on_long_click": extera_ios.retain(menu_item_data.on_long_click or menu_item_data.on_click),
        }
        self._menu_items[menu_item_data.item_id] = {
            "data": data,
            "on_click": menu_item_data.on_click,
            "on_long_click": menu_item_data.on_long_click or menu_item_data.on_click,
        }
        try:
            registered = extera_ios.add_menu_item(self.id, data)
            if isinstance(registered, str) and registered and registered != menu_item_data.item_id:
                self._menu_items[registered] = self._menu_items.pop(menu_item_data.item_id)
                menu_item_data.item_id = registered
            return menu_item_data.item_id
        except Exception as error:
            self._menu_items.pop(menu_item_data.item_id, None)
            self.log("Error adding menu item: %s" % error)
            return None

    def remove_menu_item(self, item_id):
        if not self.id or not item_id:
            return False
        self._menu_items.pop(item_id, None)
        return bool(extera_ios.remove_menu_item(self.id, item_id))

    def update_menu_item(self, item_id, **changes):
        if not self.id or not item_id:
            return False
        stored = self._menu_items.get(item_id)
        payload = {}
        if stored is not None:
            data = stored["data"]
            for key, value in changes.items():
                if value is None:
                    continue
                if key in ("on_click", "on_long_click"):
                    stored[key] = value
                    handle = extera_ios.retain(value)
                    data[key] = handle
                    payload[key] = handle
                elif key == "menu_type":
                    text = value.value if hasattr(value, "value") else str(value)
                    data[key] = text
                    payload[key] = text
                elif isinstance(value, (str, int, float, bool)):
                    data[key] = value
                    payload[key] = value
                else:
                    text = value.value if hasattr(value, "value") else str(value)
                    data[key] = text
                    payload[key] = text
        return bool(extera_ios.update_menu_item(self.id, item_id, payload))
