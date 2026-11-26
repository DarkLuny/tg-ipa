# This is the iOS counterpart of the exteraGram plugins SDK.
#
# A Python plugin written for exteraGram imports Java packages at module level:
# `from org.telegram.messenger import UserConfig`, `from java.lang import Object`,
# `from de.robv.android.xposed import XposedBridge`.  Without those imports the
# module would fail before a single line of the plugin runs.
#
# This installer answers every such import with a proxy module.  Attribute access
# returns a `ClassRef`, which is a real Python class object (so `isinstance`
# works) and whose calls are forwarded to the Swift host.  A symbol the host does
# not implement raises a PluginError at the call site, not at import time.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import importlib
import importlib.machinery
import sys
import types

from extera_utils.classes import ClassRef, ObjectProxy


_PREFIXES = (
    "java",
    "javax",
    "android",
    "androidx",
    "dalvik",
    "com",
    "org",
    "de",
    "kotlin",
)


def _is_proxyable(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _PREFIXES)


# Android classes that have a real iOS-side implementation.  They are filled in
# by `install()` from `telegram_compat.exports()`; everything else falls back to
# a `ClassRef` forwarded to the Swift host.
_NATIVE_CLASSES = {}

# Names resolved on first use, so importing their module is not required while
# `compat.install()` is still inside the runtime bootstrap.
_LAZY_NATIVE = {
    "android.content.Intent": ("intents", "Intent"),
    "android.net.Uri": ("intents", "Uri"),
    "org.telegram.ui.Components.UItem": ("ui.settings", "UItem"),
    "org.telegram.tgnet.TLObject": ("extera_utils.classes", "TLObject"),
    "org.telegram.ui.Components.Bulletin": ("ui.bulletin", "Bulletin"),
    "com.exteragram.hook.ExteraHook": ("partial_hooks", "ExteraHook"),
    "com.exteragram.hook.HookTarget": ("partial_hooks", "HookTarget"),
    "com.exteragram.hook.InstructionMatcher": ("partial_hooks", "InstructionMatcher"),
    "com.exteragram.hook.Interceptor": ("partial_hooks", "Interceptor"),
    "com.exteragram.messenger.plugins.utils.ClassProxy": ("class_proxy", "ClassProxy"),
    "com.chaquo.python.PyObject": ("telegram_compat", "PyObject"),
    "com.chaquo.python.PyException": ("telegram_compat", "PyException"),
    "com.chaquo.python.Python": ("telegram_compat", "Python"),
    "java.util.ArrayList": ("extera_utils.classes", "NativeList"),
    "java.util.LinkedList": ("extera_utils.classes", "NativeList"),
    "java.util.HashMap": ("extera_utils.classes", "NativeMap"),
    "java.util.LinkedHashMap": ("extera_utils.classes", "NativeMap"),
    "java.util.HashSet": ("extera_utils.classes", "NativeSet"),
    "java.util.LinkedHashSet": ("extera_utils.classes", "NativeSet"),
    "java.util.concurrent.ConcurrentHashMap": ("extera_utils.classes", "NativeMap"),
    "java.io.File": ("extera_utils.classes", "NativeFile"),
    "java.util.Arrays": ("extera_utils.classes", "JavaArrays"),
    "java.io.ByteArrayInputStream": ("extera_utils.classes", "ByteArrayInputStream"),
    "java.lang.Class": ("extera_utils.classes", "JavaClassFacade"),
    "java.lang.reflect.Method": ("extera_utils.classes", "MemberRef"),
    "java.lang.reflect.Member": ("extera_utils.classes", "MemberRef"),
    "com.exteragram.messenger.plugins.models.CustomSetting": ("ui.settings", "Custom"),
    "com.exteragram.messenger.plugins.models.DividerSetting": ("ui.settings", "Divider"),
    "com.exteragram.messenger.plugins.models.EditTextSetting": ("ui.settings", "EditText"),
    "com.exteragram.messenger.plugins.models.HeaderSetting": ("ui.settings", "Header"),
    "com.exteragram.messenger.plugins.models.InputSetting": ("ui.settings", "Input"),
    "com.exteragram.messenger.plugins.models.SelectorSetting": ("ui.settings", "Selector"),
    "com.exteragram.messenger.plugins.models.SwitchSetting": ("ui.settings", "Switch"),
    "com.exteragram.messenger.plugins.models.TextSetting": ("ui.settings", "Text"),
}


def _lazy_native(full_name):
    spec = _LAZY_NATIVE.get(full_name)
    if spec is None:
        return None
    module_name, attribute = spec
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None
    value = getattr(module, attribute, None)
    if value is not None:
        _NATIVE_CLASSES[full_name] = value
    return value


class _ProxyModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        full = self.__name__ + "." + name
        native = _NATIVE_CLASSES.get(full)
        if native is not None:
            return native
        native = _lazy_native(full)
        if native is not None:
            return native
        # Java sub-packages (`android.view.animation` out of `android.view`)
        # must stay modules, otherwise `from android.view import animation`
        # yields a ClassRef and its class constants disappear.
        if any(key.startswith(full + ".") for key in _NATIVE_CLASSES):
            try:
                return importlib.import_module(full)
            except Exception:
                pass
        if any(key.startswith(full + ".") for key in _LAZY_NATIVE):
            try:
                return importlib.import_module(full)
            except Exception:
                pass
        # Lower-case names in Java packages are sub-packages
        # (`org.telegram.messenger` out of `org.telegram`).  Creating a
        # `ClassRef` for one still works when a plugin references it as a class.
        return ClassRef(full)


class _ProxyLoader:
    def create_module(self, spec):
        module = _ProxyModule(spec.name)
        module.__path__ = []
        return module

    def exec_module(self, module):
        pass


class _ProxyFinder:
    def find_spec(self, fullname, path=None, target=None):
        if not _is_proxyable(fullname):
            return None
        return importlib.machinery.ModuleSpec(fullname, _ProxyLoader(), is_package=True)


def _jarray(element_type):
    def factory(values):
        return list(values or [])

    factory.element_type = element_type
    return factory


def _install_java_module():
    if "java" in sys.modules and getattr(sys.modules["java"], "__extera_proxy__", False):
        return sys.modules["java"]
    module = _ProxyModule("java")
    module.__path__ = []
    module.__extera_proxy__ = True
    module.jarray = _jarray
    module.jboolean = bool
    module.jbyte = int
    module.jchar = str
    module.jshort = int
    module.jint = int
    module.jlong = int
    module.jfloat = float
    module.jdouble = float

    def dynamic_proxy(base=None):
        try:
            from extera_utils.classes import ClassRef

            if isinstance(base, ClassRef):
                return object
        except Exception:
            pass
        return base if isinstance(base, type) else object

    def cast(_type, value):
        return value

    def jclass(name):
        full_name = str(name)
        native = _NATIVE_CLASSES.get(full_name)
        if native is None:
            native = _lazy_native(full_name)
        return native if native is not None else ClassRef(full_name)

    module.dynamic_proxy = dynamic_proxy
    module.cast = cast
    module.jclass = jclass
    sys.modules["java"] = module
    return module


class _MethodHookParam:
    def __init__(self, method=None, this_object=None, args=None):
        self.method = method
        self.thisObject = this_object
        self.args = list(args or [])
        self._result = None
        self._throwable = None
        self._extras = {}

    def getResult(self):
        return self._result

    def setResult(self, value):
        self._result = value

    def getThrowable(self):
        return self._throwable

    def setThrowable(self, value):
        self._throwable = value

    def getObjectExtra(self, key):
        return self._extras.get(key)

    def setObjectExtra(self, key, value):
        self._extras[key] = value

    def hasThrowable(self):
        return self._throwable is not None


class _Unhook:
    def __init__(self, handle=None):
        self._handle = handle

    def unhook(self):
        if self._handle:
            import extera_ios

            extera_ios.host("runtime.unswizzle", handle=self._handle)


class _XC_MethodHook:
    MethodHookParam = _MethodHookParam

    class Unhook(_Unhook):
        pass


class _XposedBridge:
    @staticmethod
    def hookMethod(method, callback):
        import extera_ios

        class_name = getattr(method, "class_name", None)
        selector = getattr(method, "name", None)
        if class_name and selector:
            callbacks = {}
            before = getattr(callback, "before_hooked_method", None)
            after = getattr(callback, "after_hooked_method", None)
            replace = getattr(callback, "replace_hooked_method", None)
            if callable(replace):
                callbacks["replace"] = extera_ios.retain(replace)
            else:
                if callable(before):
                    callbacks["before"] = extera_ios.retain(before)
                if callable(after):
                    callbacks["after"] = extera_ios.retain(after)
            handle = extera_ios.host(
                "runtime.swizzle",
                class_name=str(class_name),
                selector=str(selector),
                callbacks=callbacks,
                filters=[],
            )
            return _XC_MethodHook.Unhook(handle)
        return _XC_MethodHook.Unhook(extera_ios.host(
            "runtime.hook_method_object",
            target=method,
            callback=extera_ios.retain(callback),
        ))

    @staticmethod
    def hookAllMethods(clazz, method_name, callback):
        import extera_ios

        callbacks = {}
        before = getattr(callback, "before_hooked_method", None)
        after = getattr(callback, "after_hooked_method", None)
        replace = getattr(callback, "replace_hooked_method", None)
        if callable(replace):
            callbacks["replace"] = extera_ios.retain(replace)
        else:
            if callable(before):
                callbacks["before"] = extera_ios.retain(before)
            if callable(after):
                callbacks["after"] = extera_ios.retain(after)
        handle = extera_ios.host(
            "runtime.swizzle",
            class_name=getattr(clazz, "__name__", str(clazz)),
            selector=method_name,
            callbacks=callbacks,
            filters=[],
        )
        if not handle:
            return []
        return [_XC_MethodHook.Unhook(handle)]

    @staticmethod
    def hookAllConstructors(clazz, callback):
        return _XposedBridge.hookAllMethods(clazz, "init", callback)

    @staticmethod
    def log(text):
        import extera_ios

        extera_ios.log(text)


def _install_xposed_module():
    module = _ProxyModule("de.robv.android.xposed")
    module.__path__ = []
    module.XposedBridge = _XposedBridge
    module.XC_MethodHook = _XC_MethodHook
    module.XC_MethodReplacement = type("XC_MethodReplacement", (_XC_MethodHook,), {})
    sys.modules["de.robv.android.xposed"] = module
    sys.modules["de.robv.android"] = _ProxyModule("de.robv.android")
    sys.modules["de.robv.android"].__path__ = []
    sys.modules["de.robv"] = _ProxyModule("de.robv")
    sys.modules["de.robv"].__path__ = []
    sys.modules["de"] = _ProxyModule("de")
    sys.modules["de"].__path__ = []
    return module


_installed = False


def install():
    """Installs the Java/Android import hooks.  Safe to call twice."""
    global _installed
    if _installed:
        return
    _installed = True

    finder = _ProxyFinder()
    sys.meta_path.insert(0, finder)
    _install_java_module()
    _install_xposed_module()

    # Native shims for the app classes plugins touch most often
    # (`UserConfig`, `MessagesController`, `LocaleController`, ...).  They keep
    # Android semantics while calling into the iOS app, instead of being an
    # opaque `ClassRef`.
    try:
        import telegram_compat

        _NATIVE_CLASSES.update(telegram_compat.exports())
        try:
            from extera_utils import classes as _classes

            _classes._CLASSES.update(_NATIVE_CLASSES)
        except Exception:
            pass
    except Exception:
        pass

    # `java.lang`, `java.util` and friends are used as packages; the finder
    # would handle them, but pre-creating `java.lang` keeps `from java.lang
    # import Object` working on Python builds that cache imports aggressively.
    for name in ("java.lang", "java.util", "java.lang.reflect", "java.io",
                 "java.nio", "java.nio.charset", "java.util.concurrent",
                 "java.util.concurrent.atomic",
                 "android.view", "android.content", "android.content.res",
                 "android.content.pm", "android.graphics", "android.widget",
                 "android.os", "android.media", "android.text", "android.util",
                 "android.net", "android.text.format", "android.provider",
                 "androidx.core.content"):
        if name not in sys.modules:
            module = _ProxyModule(name)
            module.__path__ = []
            sys.modules[name] = module


def uninstall():
    global _installed
    if not _installed:
        return
    _installed = False
    sys.meta_path[:] = [item for item in sys.meta_path if not isinstance(item, _ProxyFinder)]
