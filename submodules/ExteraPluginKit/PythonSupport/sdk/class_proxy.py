# This is the iOS counterpart of the exteraGram plugins SDK.
#
# `com.exteragram.messenger.plugins.utils.ClassProxy` generates a Dex class on
# Android. iOS has no Dex; this facade creates a Python class with the same
# contract:
#
#   * an overridden method calls the handler with
#     `(instance, "name:java.lang.Type:...", args)`;
#   * a constructor uses the same shape with `"<constructor>"`;
#   * a field spec becomes the getter/setter methods named in the spec, backed
#     by a per-instance dictionary;
#   * `ProxyMethodSpec(implementation="mvel")` evaluates its MVEL expression.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import traceback


def _type_name(value):
    if isinstance(value, str):
        return value
    getter = getattr(value, "getName", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            pass
    name = getattr(value, "__name__", None)
    if name:
        return str(name)
    return "java.lang.Object"


def _signature(name, parameter_types=None):
    parts = [str(name)]
    for value in parameter_types or ():
        parts.append(":" + _type_name(value))
    return "".join(parts)


def _member_name(member):
    name = getattr(member, "name", None)
    if isinstance(name, str) and name:
        return name
    getter = getattr(member, "getName", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            pass
    return None


def _member_parameter_types(member):
    getter = getattr(member, "getParameterTypes", None)
    if callable(getter):
        try:
            return list(getter() or [])
        except Exception:
            pass
    return list(getattr(member, "params", ()) or ())


def _invoke_handler(handler, instance, signature, arguments):
    try:
        runner = getattr(handler, "run", None)
        if callable(runner):
            return runner(instance, signature, list(arguments))
        return handler(instance, signature, list(arguments))
    except Exception:
        _log("ClassProxy handler error (%s): %s" % (signature, traceback.format_exc()))
        return None


def _log(text):
    try:
        import extera_ios

        extera_ios.log(str(text))
    except Exception:
        print(text)


def _eval_mvel(code, argument_names, arguments):
    try:
        from telegram_compat import MVEL

        context = dict(zip(argument_names or (), arguments))
        context.setdefault("args", list(arguments))
        context.setdefault("this", arguments[0] if arguments else None)
        return MVEL.eval(code, context)
    except Exception:
        _log("ClassProxy MVEL error: %s" % traceback.format_exc())
        return None


class ProxyMethodSpec:
    """`ClassProxy.ProxyMethodSpec` record."""

    __slots__ = (
        "name",
        "returnType",
        "parameterTypes",
        "modifiers",
        "overrideExisting",
        "implementation",
        "mvelCode",
        "argumentNames",
    )

    def __init__(self, name, returnType=None, parameterTypes=None, modifiers=0,
                 overrideExisting=True, implementation="python", mvelCode=None,
                 argumentNames=None):
        self.name = str(name)
        self.returnType = returnType
        self.parameterTypes = list(parameterTypes or [])
        self.modifiers = int(modifiers or 0)
        self.overrideExisting = bool(overrideExisting)
        self.implementation = str(implementation or "python")
        self.mvelCode = mvelCode
        self.argumentNames = list(argumentNames or [])

    def isMvel(self):
        return self.implementation == "mvel" and self.mvelCode is not None

    def __repr__(self):
        return "<ProxyMethodSpec %s(%s)>" % (
            self.name,
            ", ".join(_type_name(value) for value in self.parameterTypes),
        )


class FieldMethodSpec:
    """`ClassProxy.FieldMethodSpec` record."""

    __slots__ = ("name", "modifiers", "getter")

    def __init__(self, name, modifiers=0, getter=True):
        self.name = str(name)
        self.modifiers = int(modifiers or 0)
        self.getter = bool(getter)

    def __repr__(self):
        return "<FieldMethodSpec %s %s>" % (
            self.name,
            "getter" if self.getter else "setter",
        )


class FieldSpec:
    """`ClassProxy.FieldSpec` record."""

    __slots__ = ("name", "type", "modifiers", "methods")

    def __init__(self, name, type=None, modifiers=0, methods=None):
        self.name = str(name)
        self.type = type
        self.modifiers = int(modifiers or 0)
        self.methods = list(methods or [])

    def __repr__(self):
        return "<FieldSpec %s>" % self.name


class DexMakerHook:
    """`ClassProxy.DexMakerHook`; the hook runs before the class is built."""

    def apply(self, dexMaker, proxyType, superType, interfaces):
        return None


class TypeHelper:
    @staticmethod
    def box(value):
        return value

    @staticmethod
    def unboxInt(value):
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def unboxBool(value):
        return bool(value)

    @staticmethod
    def unboxLong(value):
        return TypeHelper.unboxInt(value)

    @staticmethod
    def unboxDouble(value):
        try:
            return float(value)
        except Exception:
            return 0.0

    @staticmethod
    def unboxFloat(value):
        return TypeHelper.unboxDouble(value)

    @staticmethod
    def unboxShort(value):
        return TypeHelper.unboxInt(value)

    @staticmethod
    def unboxByte(value):
        return TypeHelper.unboxInt(value)

    @staticmethod
    def unboxChar(value):
        if isinstance(value, str):
            return value[:1] if value else 0
        try:
            return chr(int(value))
        except Exception:
            return 0


class ClassProxy:
    DexMakerHook = DexMakerHook
    ProxyMethodSpec = ProxyMethodSpec
    FieldMethodSpec = FieldMethodSpec
    FieldSpec = FieldSpec
    TypeHelper = TypeHelper

    @staticmethod
    def runPythonRunnable(callback):
        if callback is None:
            return None
        try:
            return callback()
        except Exception:
            _log("ClassProxy runnable error: %s" % traceback.format_exc())
            return None

    @staticmethod
    def createProxyClass(baseClass, handler, *args):
        values = list(args)
        dex_hook = None
        interfaces = []
        if values and isinstance(values[0], DexMakerHook):
            dex_hook = values.pop(0)
            interfaces = list(values.pop(0) or []) if values else []
        methods = list(values.pop(0) or []) if values else []
        constructors = list(values.pop(0) or []) if values else []
        method_specs = list(values.pop(0) or []) if values else []
        field_specs = list(values.pop(0) or []) if values else []
        custom_name = values.pop(0) if values else None

        if dex_hook is not None:
            try:
                dex_hook.apply(None, None, baseClass, interfaces)
            except Exception:
                _log("ClassProxy DexMakerHook error: %s" % traceback.format_exc())

        base = baseClass if isinstance(baseClass, type) else object
        class_name = str(custom_name) if custom_name else (
            "Proxy_" + _type_name(baseClass).rsplit(".", 1)[-1]
        )

        namespace = {
            "__extera_proxy_class__": True,
            "__extera_proxy_handler__": staticmethod(handler),
            "__extera_proxy_methods__": tuple(
                [(_member_name(method), _signature(_member_name(method),
                                                   _member_parameter_types(method)))
                 for method in methods]
                + [(spec.name, _signature(spec.name, spec.parameterTypes))
                   for spec in method_specs]
            ),
        }

        def proxy_init(self, *init_args, **init_kwargs):
            self.__dict__["__extera_proxy_fields_values__"] = {}
            base_init = getattr(self, "__extera_proxy_base_init__", None)
            if callable(base_init):
                try:
                    base_init(*init_args, **init_kwargs)
                except Exception:
                    pass
            if constructors:
                parameter_types = _member_parameter_types(constructors[0])
                signature = _signature("<constructor>", parameter_types)
                _invoke_handler(handler, self, signature, init_args)

        namespace["__init__"] = proxy_init

        def make_handler_method(name, signature):
            def method(self, *method_args):
                return _invoke_handler(handler, self, signature, method_args)
            method.__name__ = name
            return method

        for method in methods:
            name = _member_name(method) or "method"
            signature = _signature(name, _member_parameter_types(method))
            namespace[name] = make_handler_method(name, signature)

        for spec in method_specs:
            name = spec.name
            if spec.isMvel():
                def make_mvel_method(name, code, argument_names):
                    def method(self, *method_args):
                        return _eval_mvel(code, argument_names, method_args)
                    method.__name__ = name
                    return method

                namespace[name] = make_mvel_method(
                    name, spec.mvelCode, spec.argumentNames
                )
            else:
                signature = _signature(name, spec.parameterTypes)
                namespace[name] = make_handler_method(name, signature)

        if field_specs:
            namespace["__extera_proxy_field_names__"] = tuple(
                spec.name for spec in field_specs
            )

            for spec in field_specs:
                for accessor in spec.methods:
                    name = accessor.name
                    if accessor.getter:
                        def make_field_getter(field_name):
                            def getter(self):
                                return self.__dict__.get(
                                    "__extera_proxy_fields_values__", {}
                                ).get(field_name)
                            return getter

                        namespace[name] = make_field_getter(spec.name)
                    else:
                        def make_field_setter(field_name):
                            def setter(self, value):
                                self.__dict__.setdefault(
                                    "__extera_proxy_fields_values__", {}
                                )[field_name] = value
                                return None
                            return setter

                        namespace[name] = make_field_setter(spec.name)

            def proxy_getattr(self, name):
                values = self.__dict__.get("__extera_proxy_fields_values__", {})
                if name in values:
                    return values[name]
                for cls in type(self).__mro__[1:]:
                    base_getattr = cls.__dict__.get("__getattr__")
                    if base_getattr is not None:
                        return base_getattr(self, name)
                raise AttributeError(name)

            def proxy_setattr(self, name, value):
                if name.startswith("_"):
                    object.__setattr__(self, name, value)
                    return
                self.__dict__.setdefault("__extera_proxy_fields_values__", {})[
                    name
                ] = value

            namespace["__getattr__"] = proxy_getattr
            namespace["__setattr__"] = proxy_setattr

        # Keep `super()` working when the base is a Python class.
        if base is not object:
            previous_init = getattr(base, "__init__", None)
            if callable(previous_init):
                namespace["__extera_proxy_base_init__"] = previous_init

        proxy_class = type(class_name, (base,), namespace)
        proxy_class.__jproxy_class__ = proxy_class
        proxy_class.__extera_proxy_base__ = baseClass
        proxy_class.__extera_proxy_interfaces__ = tuple(interfaces)
        return proxy_class
