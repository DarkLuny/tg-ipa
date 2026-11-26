# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Android plugins build Java subclasses and reach app classes through Chaquopy's
# `java` module.  iOS has neither JVM nor ART, so this module provides the same
# names backed by two things that do exist:
#
#   * the Objective-C runtime, for classes and selectors that the app exposes
#     (`extera_utils.iosruntime`), and
#   * typed proxies for Telegram data (`client_utils`), which carry plain
#     dictionaries instead of `TLRPC` objects.
#
# A class that cannot be resolved still produces a proxy object: setting a field
# or calling a method then reports a precise error instead of failing the import
# of the whole plugin.  This is what keeps most scripts loadable.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import copy
import inspect
import os
import re
import threading
import weakref

import extera_ios


_LOCK = threading.RLock()
_CLASSES = {}


class _ClassMeta(type):
    def __instancecheck__(cls, instance):
        if isinstance(instance, ObjectProxy):
            return instance.is_instance_of(cls.__name__)
        return False

    def __repr__(cls):
        return "<iOS class %s>" % cls.__name__


class Constant:
    __slots__ = ("name", "value")

    def __init__(self, name, value=None):
        self.name = name
        self.value = self.name if value is None else value

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return "Constant(%r)" % (self.value,)

    def __eq__(self, other):
        if isinstance(other, Constant):
            return self.value == other.value
        return self.value == other

    def __hash__(self):
        return hash(self.value)

    def __int__(self):
        return int(self.value)


class NativeList(list):
    """Stand-in for `java.util.ArrayList`."""

    def __init__(self, values=()):
        if isinstance(values, int):
            super().__init__()
        elif values is None:
            super().__init__()
        else:
            super().__init__(values)

    def add(self, value):
        self.append(value)
        return True

    def get(self, index):
        return self[int(index)]

    def set(self, index, value):
        self[int(index)] = value
        return value

    def size(self):
        return len(self)

    def isEmpty(self):
        return not self

    def is_empty(self):
        return not self

    def clear(self):
        del self[:]

    def iterator(self):
        return iter(self)

    def toArray(self):
        return list(self)

    def contains(self, value):
        return value in self

    @classmethod
    def getClass(cls):
        return ClassRef("java.util.ArrayList")


class NativeMap(dict):
    """Stand-in for `java.util.HashMap` / `ConcurrentHashMap`."""

    def __init__(self, values=None, *args, **kwargs):
        if isinstance(values, int):
            super().__init__()
        elif values is None:
            super().__init__(*args, **kwargs)
        else:
            super().__init__(values, *args, **kwargs)

    def put(self, key, value):
        self[key] = value
        return value

    def get(self, key, default=None):
        return dict.get(self, key, default)

    def getOrDefault(self, key, default=None):
        return dict.get(self, key, default)

    def containsKey(self, key):
        return key in self

    def size(self):
        return len(self)

    def isEmpty(self):
        return not self

    def remove(self, key):
        return self.pop(key, None)

    def keySet(self):
        return set(self.keys())

    def entrySet(self):
        return [{"key": key, "value": value} for key, value in self.items()]

    @classmethod
    def getClass(cls):
        return ClassRef("java.util.HashMap")


class NativeSet(set):
    """Stand-in for `java.util.HashSet` / `LinkedHashSet`."""

    def __init__(self, values=()):
        super().__init__()
        if values is not None and not isinstance(values, int):
            for value in values:
                self.add(value)

    def add(self, value):
        super().add(value)
        return True

    def addAll(self, values):
        changed = False
        for value in values or ():
            if value not in self:
                super().add(value)
                changed = True
        return changed

    def remove(self, value):
        try:
            super().remove(value)
            return True
        except KeyError:
            return False

    def contains(self, value):
        return value in self

    def containsAll(self, values):
        return all(value in self for value in (values or ()))

    def removeAll(self, values):
        for value in list(values or ()):
            self.discard(value)
        return True

    def size(self):
        return len(self)

    def isEmpty(self):
        return not self

    def iterator(self):
        return iter(self)

    def toArray(self):
        return list(self)

    @classmethod
    def getClass(cls):
        return ClassRef("java.util.HashSet")


class NativeFile:
    """Stand-in for `java.io.File`, backed by a real path in the sandbox."""

    def __init__(self, *parts):
        self._path = os.path.join(*[str(part) for part in parts if part is not None])

    @classmethod
    def getClass(cls):
        return ClassRef("java.io.File")

    def getAbsolutePath(self):
        return os.path.abspath(self._path)

    def getPath(self):
        return self._path

    def getName(self):
        return os.path.basename(self._path)

    def exists(self):
        return os.path.exists(self._path)

    def isFile(self):
        return os.path.isfile(self._path)

    def isDirectory(self):
        return os.path.isdir(self._path)

    def length(self):
        try:
            return os.path.getsize(self._path)
        except OSError:
            return 0

    def lastModified(self):
        try:
            return int(os.path.getmtime(self._path) * 1000)
        except OSError:
            return 0

    def delete(self):
        try:
            os.remove(self._path)
            return True
        except OSError:
            return False

    def deleteOnExit(self):
        import atexit

        atexit.register(self.delete)

    def mkdirs(self):
        os.makedirs(self._path, exist_ok=True)
        return True

    def listFiles(self):
        try:
            return [NativeFile(os.path.join(self._path, name)) for name in os.listdir(self._path)]
        except OSError:
            return []

    def __str__(self):
        return self._path

    def __fspath__(self):
        return self._path


class JavaArrays:
    """`java.util.Arrays` static helpers."""

    @staticmethod
    def asList(*values):
        """Java's `Arrays.asList(T... a)`: accepts varargs or one collection."""
        if not values:
            return NativeList()
        if len(values) == 1:
            value = values[0]
            if value is None:
                return NativeList()
            if isinstance(value, (list, tuple, set)):
                return NativeList(value)
            try:
                return NativeList(list(value))
            except TypeError:
                return NativeList([value])
        return NativeList(values)

    @staticmethod
    def stream(values=None):
        return iter(values or ())

    @staticmethod
    def sort(values=None):
        try:
            return sorted(values or ())
        except Exception:
            return list(values or ())

    @staticmethod
    def toString(values=None):
        return "[" + ", ".join(str(value) for value in (values or ())) + "]"

    @staticmethod
    def copyOf(values, length):
        result = list(values or ())[: int(length)]
        while len(result) < int(length):
            result.append(None)
        return result

    @staticmethod
    def copyOfRange(values, start, end):
        return list(values or ())[int(start):int(end)]

    @staticmethod
    def equals(left, right):
        return list(left or ()) == list(right or ())

    @staticmethod
    def fill(values, value=None):
        if isinstance(values, list):
            for index in range(len(values)):
                values[index] = value
        return values

    @staticmethod
    def hashCode(values):
        return hash(tuple(values or ()))


class ByteArrayInputStream:
    """`java.io.ByteArrayInputStream` backed by bytes."""

    def __init__(self, data=b"", offset=0, length=None):
        raw = bytes(data or b"")
        offset = int(offset or 0)
        if length is None:
            self._data = raw[offset:]
        else:
            self._data = raw[offset:offset + int(length)]
        self._position = 0
        self._mark = 0
        self._closed = False

    def read(self, target=None, offset=0, length=None):
        if self._closed:
            return -1
        if target is not None and not isinstance(target, int):
            start = int(offset or 0)
            amount = int(length or (len(target) - start))
            chunk = self._data[self._position:self._position + amount]
            target[start:start + len(chunk)] = chunk
            self._position += len(chunk)
            return len(chunk)
        amount = 1 if target is None else int(target)
        chunk = self._data[self._position:self._position + amount]
        self._position += len(chunk)
        if not chunk:
            return -1
        if amount == 1:
            return chunk[0]
        return list(chunk)

    def available(self):
        return max(0, len(self._data) - self._position)

    def skip(self, count):
        step = max(0, int(count or 0))
        step = min(step, self.available())
        self._position += step
        return step

    def mark(self, *args):
        self._mark = self._position

    def reset(self):
        self._position = self._mark

    def markSupported(self):
        return True

    def close(self):
        self._closed = True


class JavaClassFacade:
    """`java.lang.Class` static facade (`Class.forName` and companions)."""

    @staticmethod
    def forName(name, *args, **kwargs):
        return ClassRef(str(name))

    @classmethod
    def getClass(cls):
        return ClassRef("java.lang.Class")

    @classmethod
    def getName(cls):
        return "java.lang.Class"

    @classmethod
    def getSimpleName(cls):
        return "Class"

    @staticmethod
    def isInstance(value, class_value):
        if hasattr(class_value, "isInstance"):
            return bool(class_value.isInstance(value))
        return False


_NATIVE_CONSTRUCTORS = {
    "java.util.ArrayList": NativeList,
    "java.util.LinkedList": NativeList,
    "java.util.HashMap": NativeMap,
    "java.util.LinkedHashMap": NativeMap,
    "java.util.concurrent.ConcurrentHashMap": NativeMap,
    "java.util.HashSet": set,
    "java.io.File": NativeFile,
    "java.lang.String": str,
    "java.lang.Integer": int,
    "java.lang.Long": int,
    "java.lang.Boolean": bool,
    "java.lang.Float": float,
    "java.lang.Double": float,
}



class MemberRef:
    __slots__ = ("class_name", "name", "params", "kind")

    def __init__(self, class_name, name, params=(), kind="method"):
        self.class_name = class_name
        self.name = name
        self.params = tuple(params or ())
        self.kind = kind

    @classmethod
    def getClass(cls):
        return ClassRef("java.lang.reflect.Method")

    def get_name(self):
        return self.name

    def getName(self):
        return self.name

    def get_declaring_class(self):
        return ClassRef(self.class_name)

    def getDeclaringClass(self):
        return self.get_declaring_class()

    def get_parameter_types(self):
        return list(self.params)

    def getParameterTypes(self):
        return self.get_parameter_types()

    def get_return_type(self):
        return ClassRef("java.lang.Object")

    def getReturnType(self):
        return self.get_return_type()

    def get_type(self):
        return ClassRef("java.lang.Object")

    def getType(self):
        return self.get_type()

    def invoke(self, instance=None, *args):
        if self.class_name == "java.util.Arrays":
            if self.name == "asList":
                return NativeList(args[0] if args and isinstance(args[0], (list, tuple)) else args)
            if self.name == "stream":
                return iter(args[0] if args else [])
        target = instance.handle if isinstance(instance, ObjectProxy) else None
        return extera_ios.host(
            "java.invoke",
            class_name=self.class_name,
            member=self.name,
            target=target,
            args=list(args),
            params=list(self.params),
        )

    def get(self, instance=None):
        target = instance.handle if isinstance(instance, ObjectProxy) else None
        return extera_ios.host(
            "java.get_field",
            class_name=self.class_name,
            member=self.name,
            target=target,
        )

    def set(self, instance=None, value=None):
        target = instance.handle if isinstance(instance, ObjectProxy) else None
        return extera_ios.host(
            "java.set_field",
            class_name=self.class_name,
            member=self.name,
            target=target,
            value=value,
        )

    def __call__(self, *args):
        return self.invoke(None, *args)

    def __repr__(self):
        return "<member %s.%s>" % (self.class_name, self.name)


class ObjectProxy:
    """A remote app object, identified by an opaque host handle."""

    _KNOWN = {}

    def __init__(self, class_name, handle=None, data=None):
        object.__setattr__(self, "_class_name", class_name)
        object.__setattr__(self, "_handle", handle)
        object.__setattr__(self, "_data", data or {})

    @property
    def handle(self):
        return self._handle

    def is_instance_of(self, class_name):
        if self._class_name == class_name:
            return True
        return bool(extera_ios.host(
            "java.is_instance",
            class_name=class_name,
            target=self._handle,
        ))

    def get_class(self):
        return ClassRef(self._class_name)

    def getClass(self):
        return self.get_class()

    def to_dict(self):
        return dict(self._data)

    def to_json(self):
        return {
            "__handle__": self._handle,
            "__class__": self._class_name,
        }

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in self._data:
            return self._data[name]

        def method(*args, **kwargs):
            return extera_ios.host(
                "java.call",
                class_name=self._class_name,
                target=self._handle,
                method=name,
                args=list(args),
                kwargs=kwargs,
            )

        method.__name__ = name
        return method

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        self._data[name] = value
        if self._handle:
            extera_ios.host(
                "java.set_field",
                class_name=self._class_name,
                target=self._handle,
                member=name,
                value=value,
            )

    def __repr__(self):
        return "<%s%s>" % (self._class_name, " #%s" % self._handle if self._handle else "")


class ClassRef(metaclass=_ClassMeta):
    __slots__ = ("_name",)

    def __init__(self, name):
        object.__setattr__(self, "_name", str(name))

    @property
    def __name__(self):
        return self._name

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        full = self._name + "." + name
        if full in _CLASSES:
            return _CLASSES[full]
        # A nested class (`TLRPC.TL_photo`), a static member, or a constant.
        if (
            (name[:1].isupper() and "_" in name)
            or name[:2] == "TL"
            or (
                self._name == "org.telegram.tgnet.TLRPC"
                and name[:1].isupper()
                and not name.isupper()
            )
        ):
            return self._nested(name)
        if name.isupper():
            return Constant(full)
        return MemberRef(self._name, name)

    def _nested(self, name):
        full = self._name + "." + name
        with _LOCK:
            value = _CLASSES.get(full)
            if value is None:
                value = ClassRef(full)
                _CLASSES[full] = value
            return value

    # -- Reflection surface --------------------------------------------------
    #
    # Android's `X.class` and `X.getClass()` both produce a `java.lang.Class`.
    # The iOS kit has no JVM, so a `ClassRef` *is* that object: these methods
    # build member handles the way `hook_utils.get_method`/`get_field` do, and
    # `partial_hooks` can then hook them.

    def getClass(self):
        return self

    def get_class(self):
        return self

    def getDeclaredMethod(self, name, *param_types):
        return MemberRef(self._name, str(name), param_types, "method")

    def getMethod(self, name, *param_types):
        return self.getDeclaredMethod(name, *param_types)

    def getDeclaredField(self, name):
        return MemberRef(self._name, str(name), (), "field")

    def getField(self, name):
        return self.getDeclaredField(name)

    def getDeclaredMethods(self):
        return []

    def getDeclaredFields(self):
        return []

    def getDeclaredConstructors(self):
        return [MemberRef(self._name, "init", (), "constructor")]

    def isInstance(self, value):
        if isinstance(value, ObjectProxy):
            return value.is_instance_of(self._name)
        return False

    def cast(self, value):
        return value

    def __call__(self, *args, **kwargs):
        if self._name.startswith("org.telegram.tgnet.TLRPC."):
            return _make_tl_object(self._name.rsplit(".", 1)[-1], args, kwargs)
        native = _NATIVE_CONSTRUCTORS.get(self._name)
        if native is not None:
            if native is NativeList:
                values = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else args
                return NativeList(values)
            if native is NativeMap:
                value = NativeMap()
                if args and isinstance(args[0], dict):
                    value.update(args[0])
                return value
            if native is set:
                return set(args[0] if args and isinstance(args[0], (list, tuple, set)) else args)
            if native is NativeFile:
                return NativeFile(*args)
            if not args:
                return native()
            return native(args[0])

        data = {}
        if args and isinstance(args[0], dict):
            data.update(args[0])
        data.update(kwargs)
        handle = extera_ios.host(
            "java.new",
            class_name=self._name,
            args=list(args),
            kwargs=kwargs,
        )
        return ObjectProxy(self._name, handle=handle, data=data)

    def get_name(self):
        return self._name

    def getName(self):
        return self._name

    def is_primitive(self):
        return self._name in _PRIMITIVES

    def isPrimitive(self):
        return self.is_primitive()

    def __repr__(self):
        return "<class %s>" % self._name


_PRIMITIVES = {
    "boolean", "byte", "char", "short", "int", "long", "float", "double", "void",
}


_TL_NAMESPACES = {
    "account", "auth", "bots", "channels", "contacts", "help", "langpack",
    "messages", "payments", "phone", "photos", "stats", "stickers", "storage",
    "updates", "upload", "users",
}


def _tl_constructor_name(class_name):
    name = class_name
    if name.startswith("TL_"):
        name = name[3:]
    parts = [part for part in name.split("_") if part]
    if not parts:
        return name
    if len(parts) > 1 and parts[0] in _TL_NAMESPACES:
        head = parts[0]
        tail = parts[1:]
        first = tail[0][:1].lower() + tail[0][1:]
        rest = "".join(part[:1].upper() + part[1:] for part in tail[1:])
        return head + "." + first + rest
    return parts[0][:1].lower() + parts[0][1:] + "".join(
        part[:1].upper() + part[1:] for part in parts[1:]
    )


def _serialize_tl_value(value):
    """Converts a TL object graph into the plain JSON the host can read."""
    if isinstance(value, TLObject):
        return {
            key: _serialize_tl_value(item)
            for key, item in value.items()
        }
    if isinstance(value, dict):
        return {
            key: _serialize_tl_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_serialize_tl_value(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        import base64

        return base64.b64encode(bytes(value)).decode("ascii")
    return value


class TLObject(dict):
    """A Telegram TL constructor backed by a dictionary.

    `TLRPC.TL_inputMediaPhoto()` produces
    `{"_": "inputMediaPhoto", ...}`; fields are readable and writable as
    attributes, which is what plugin code expects from a Java TL object.
    """

    def __init__(self, constructor, fields=None, **kwargs):
        super().__init__()
        self["_"] = constructor
        for key, value in (fields or {}).items():
            self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def get_name(self):
        return self.get("_", "")

    def getName(self):
        return self.get_name()

    def get_constructor(self):
        return self.get_name()

    def to_native(self):
        return self.get_name(), _serialize_tl_value(dict(self))

    def to_json(self):
        return _serialize_tl_value(dict(self))

    def __repr__(self):
        return "<TLObject %s>" % (self.get_name(),)


def _make_tl_object(class_name, args, kwargs):
    fields = {}
    if args and isinstance(args[0], dict):
        fields.update(args[0])
    fields.update(kwargs)
    return TLObject(_tl_constructor_name(class_name), fields)


def java_class(name):
    with _LOCK:
        value = _CLASSES.get(name)
        if value is None:
            value = ClassRef(name)
            _CLASSES[name] = value
        return value


jclass = java_class
JavaClass = ClassRef


def find_class(name):
    return java_class(name)


class _UnsetType:
    def __repr__(self):
        return "<unset>"


_UNSET = _UnsetType()


def _java_of(instance):
    if isinstance(instance, ObjectProxy):
        return instance
    return getattr(instance, "_jthis", None)


class _Modifier:
    PUBLIC = 0x0001
    PRIVATE = 0x0002
    PROTECTED = 0x0004
    STATIC = 0x0008
    FINAL = 0x0010
    SYNCHRONIZED = 0x0020
    VOLATILE = 0x0040
    TRANSIENT = 0x0080
    NATIVE = 0x0100
    INTERFACE = 0x0200
    ABSTRACT = 0x0400
    STRICT = 0x0800
    SYNTHETIC = 0x1000


_MODIFIER_FLAGS = {
    "public": _Modifier.PUBLIC,
    "private": _Modifier.PRIVATE,
    "protected": _Modifier.PROTECTED,
    "static": _Modifier.STATIC,
    "final": _Modifier.FINAL,
    "synchronized": _Modifier.SYNCHRONIZED,
    "volatile": _Modifier.VOLATILE,
    "transient": _Modifier.TRANSIENT,
    "native": _Modifier.NATIVE,
    "interface": _Modifier.INTERFACE,
    "abstract": _Modifier.ABSTRACT,
    "strictfp": _Modifier.STRICT,
    "synthetic": _Modifier.SYNTHETIC,
}

_PRIMITIVE_TYPE_NAMES = {
    "boolean", "byte", "char", "short", "int", "long", "float", "double", "void",
}


def jvoid_type():
    return "void"


def _copy_default(value):
    if value is _UNSET:
        return _UNSET
    if callable(value):
        return value()
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _normalize_java_type(type_ref):
    if type_ref is None:
        return None
    if isinstance(type_ref, ClassRef):
        return type_ref.get_name()
    if isinstance(type_ref, str):
        normalized = type_ref.strip()
        if normalized.lower() in _PRIMITIVE_TYPE_NAMES:
            return normalized.lower()
        return normalized
    mapping = {
        bool: "boolean",
        int: "int",
        float: "double",
        str: "java.lang.String",
        bytes: "[B",
        list: "java.util.ArrayList",
        dict: "java.util.HashMap",
    }
    return mapping.get(type_ref, getattr(type_ref, "__name__", str(type_ref)))


def _normalize_arg_types(arg_types, *, allow_none=False):
    if arg_types is None:
        return None if allow_none else []
    if not isinstance(arg_types, (list, tuple)):
        arg_types = [arg_types]
    return [_normalize_java_type(arg_type) for arg_type in arg_types]


def _parse_modifiers(modifiers):
    if modifiers is None:
        return _Modifier.PUBLIC
    if isinstance(modifiers, int):
        return modifiers

    result = 0
    normalized = str(modifiers).replace("|", " ").replace(",", " ").split()
    for token in normalized:
        flag = _MODIFIER_FLAGS.get(token.lower())
        if flag is None:
            raise ValueError("Unknown modifier: %s" % token)
        result |= flag
    return result or _Modifier.PUBLIC


def _parse_argument_specs(arguments=None, *, arg_types=None, allow_none=False):
    if arguments is not None and arg_types is not None:
        raise ValueError("Use either arguments or arg_types, not both")

    if arguments is None:
        return None, _normalize_arg_types(arg_types, allow_none=allow_none)

    if not isinstance(arguments, (list, tuple)):
        arguments = [arguments]

    names = []
    types = []
    for index, argument in enumerate(arguments):
        if isinstance(argument, (list, tuple)):
            if len(argument) != 2:
                raise ValueError("Argument tuples must be in the form (name, type)")
            name, value_type = argument
        else:
            name, value_type = None, argument
        names.append("arg%d" % index if name is None else str(name))
        types.append(_normalize_java_type(value_type))
    return names, types


def _get_java_field_value(java_instance, field_name):
    if java_instance is None:
        return _UNSET
    handle = getattr(java_instance, "handle", None)
    if not handle:
        return _UNSET
    try:
        value = extera_ios.host(
            "java.get_field",
            class_name=getattr(java_instance, "_class_name", "java.lang.Object"),
            target=handle,
            member=field_name,
        )
    except Exception:
        return _UNSET
    return _UNSET if value is None else value


def _set_java_field_value(java_instance, field_name, value):
    if java_instance is None:
        return False
    handle = getattr(java_instance, "handle", None)
    if not handle:
        return False
    try:
        extera_ios.host(
            "java.set_field",
            class_name=getattr(java_instance, "_class_name", "java.lang.Object"),
            target=handle,
            member=field_name,
            value=value,
        )
        return True
    except Exception:
        return False


def _find_class_attr(cls, name):
    for current in cls.__mro__:
        if name in current.__dict__:
            return current.__dict__[name]
    return None


def _unwrap_callable_attr(attr):
    return attr.__func__ if isinstance(attr, (classmethod, staticmethod)) else attr


def _bind_attr(instance, attr):
    if not hasattr(attr, "__get__"):
        return attr
    if isinstance(instance, type):
        if isinstance(attr, classmethod):
            return attr.__get__(None, instance)
        return attr.__get__(instance, instance)
    return attr.__get__(instance, type(instance))


def _callable_parameters(fn):
    signature = inspect.signature(_unwrap_callable_attr(fn))
    parameters = list(signature.parameters.values())
    if parameters and parameters[0].name in ("self", "cls"):
        parameters = parameters[1:]
    return signature, parameters


def _call_with_supported_args(fn, *args):
    signature = inspect.signature(_unwrap_callable_attr(fn))
    parameters = list(signature.parameters.values())
    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return fn(*args)
    positional = [
        parameter for parameter in parameters
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return fn(*args[:len(positional)])


def _infer_arg_types(fn):
    _, parameters = _callable_parameters(fn)
    result = []
    for parameter in parameters:
        if parameter.annotation is inspect.Signature.empty:
            raise ValueError(
                "Method '%s' requires arg_types or annotations"
                % getattr(_unwrap_callable_attr(fn), "__name__", "?")
            )
        result.append(_normalize_java_type(parameter.annotation))
    return result


def _infer_method_signature(fn):
    signature, _ = _callable_parameters(fn)
    arg_types = _infer_arg_types(fn)
    return_annotation = signature.return_annotation
    return_type = "void" if return_annotation is inspect.Signature.empty else _normalize_java_type(return_annotation)
    return return_type, arg_types


def _type_name(type_ref):
    normalized = _normalize_java_type(type_ref)
    if normalized is None:
        return None
    return getattr(normalized, "getName", lambda: str(normalized))()


def _build_signature(name, arg_types):
    if arg_types is None:
        return name
    return ":".join([name] + [_type_name(arg_type) for arg_type in arg_types])


def _split_signature(raw_name):
    parts = (raw_name or "").split(":")
    return parts[0], tuple(parts[1:])


def _call_super(instance, simple_name, args):
    try:
        return getattr(instance, "SUPER_%s" % simple_name)(*args)
    except Exception:
        return None


def _normalize_constructor_result(updated_args):
    if updated_args is None:
        return None
    if isinstance(updated_args, (list, tuple)):
        return list(updated_args)
    return [updated_args]


def _normalize_proxy_custom_name(name):
    if name is None:
        return None
    normalized = str(name).strip()
    if not normalized:
        return None
    return "".join(char if char.isalnum() or char == "_" else "_" for char in normalized)


class _MethodMetadata:
    def __init__(self, kind, return_type, arg_types, modifiers, throws=None,
                 java_name=None, implementation="python", code=None, arg_names=None):
        self.kind = kind
        self.return_type = return_type
        self.arg_types = arg_types
        self.modifiers = modifiers
        self.throws = throws
        self.java_name = java_name
        self.implementation = implementation
        self.code = code
        self.arg_names = arg_names

    def resolve(self, fn, python_name):
        return_type = self.return_type
        arg_types = self.arg_types
        arg_names = list(self.arg_names) if self.arg_names is not None else None

        if self.kind == "method" and self.implementation == "python" and (return_type is None or arg_types is None):
            inferred_return_type, inferred_arg_types = _infer_method_signature(fn)
            if return_type is None:
                return_type = inferred_return_type
            if arg_types is None:
                arg_types = inferred_arg_types
        elif self.implementation == "mvel":
            if self.kind == "method":
                if return_type is None:
                    return_type = "void"
                if arg_types is None:
                    arg_types = []
                    if arg_names:
                        raise ValueError(
                            "MVEL method '%s' defines argument names without argument types" % python_name
                        )
            elif arg_names is not None and arg_types is not None and len(arg_names) != len(arg_types):
                raise ValueError(
                    "MVEL method '%s' must have the same number of argument names and argument types" % python_name
                )

        return _ResolvedMethodMetadata(
            kind=self.kind,
            python_name=python_name,
            java_name=self.java_name or python_name,
            return_type=_normalize_java_type(return_type) if return_type is not None else None,
            arg_types=_normalize_arg_types(arg_types, allow_none=self.kind == "override"),
            modifiers=_parse_modifiers(self.modifiers),
            throws=self.throws,
            implementation=self.implementation,
            code=self.code,
            arg_names=arg_names,
        )


class _ResolvedMethodMetadata:
    def __init__(self, *, kind, python_name, java_name, return_type, arg_types,
                 modifiers, throws=None, implementation="python", code=None, arg_names=None):
        self.kind = kind
        self.python_name = python_name
        self.java_name = java_name
        self.return_type = return_type
        self.arg_types = arg_types
        self.modifiers = modifiers
        self.throws = throws
        self.implementation = implementation
        self.code = code
        self.arg_names = arg_names
        self.signature = _build_signature(java_name, arg_types) if arg_types is not None else None


class _ConstructorMetadata:
    def __init__(self, arg_types=None, *, phase="post"):
        self.arg_types = arg_types
        self.phase = phase

    def resolve(self, fn, python_name):
        arg_types = self.arg_types
        if arg_types is None:
            try:
                arg_types = _infer_arg_types(fn)
            except ValueError:
                arg_types = None
        return _ResolvedConstructorMetadata(
            python_name=python_name,
            arg_types=_normalize_arg_types(arg_types, allow_none=True),
            phase=self.phase,
        )


class _ResolvedConstructorMetadata:
    def __init__(self, *, python_name, arg_types, phase):
        self.python_name = python_name
        self.arg_types = arg_types
        self.phase = phase
        self.signature = _build_signature("<constructor>", arg_types) if arg_types is not None else None


class _ClassBuildMetadata:
    def resolve(self, python_name):
        return _ResolvedClassBuildMetadata(python_name=python_name)


class _ResolvedClassBuildMetadata:
    def __init__(self, *, python_name):
        self.python_name = python_name


class _FieldMetadata:
    def __init__(self, field_type, default=_UNSET, modifiers="public", methods=None):
        self.field_type = field_type
        self.default = default
        self.modifiers = modifiers
        self.methods = methods

    def resolve(self, python_name):
        return _ResolvedFieldMetadata(
            python_name=python_name,
            field_type=_normalize_java_type(self.field_type),
            default=self.default,
            modifiers=_parse_modifiers(self.modifiers),
            methods=_resolve_field_accessor_methods(self.methods, python_name, self.field_type),
        )


class _ResolvedFieldMetadata:
    def __init__(self, *, python_name, field_type, default, modifiers, methods):
        self.python_name = python_name
        self.field_type = field_type
        self.default = default
        self.modifiers = modifiers
        self.methods = methods


class _FieldAccessorMetadata:
    def __init__(self, kind, name=None, modifiers="public"):
        self.kind = kind
        self.name = name
        self.modifiers = modifiers

    def resolve(self, field_name, field_type):
        return _ResolvedFieldAccessorMetadata(
            kind=self.kind,
            name=self.name or _default_field_accessor_name(field_name, self.kind, field_type),
            modifiers=_parse_modifiers(self.modifiers),
        )


class _ResolvedFieldAccessorMetadata:
    def __init__(self, *, kind, name, modifiers):
        self.kind = kind
        self.name = name
        self.modifiers = modifiers


def _field_accessor_title(name):
    return "".join(part[:1].upper() + part[1:] for part in str(name).split("_") if part)


def _default_field_accessor_name(field_name, kind, field_type):
    title = _field_accessor_title(field_name)
    if kind == "get":
        return "is%s" % title if str(field_type).lower() == "boolean" else "get%s" % title
    return "set%s" % title


def _resolve_field_accessor_methods(methods, field_name, field_type):
    if methods is None:
        return []
    if isinstance(methods, (list, tuple)):
        items = methods
    else:
        items = [methods]
    return [item.resolve(field_name, field_type) for item in items if isinstance(item, _FieldAccessorMetadata)]


class JField:
    def __init__(self, field_type, *, default=_UNSET, modifiers="public", methods=None):
        self.__jfield__ = _FieldMetadata(field_type, default=default, modifiers=modifiers, methods=methods)
        self.name = None
        self.storage_name = None

    def __set_name__(self, owner, name):
        self.name = name
        self.storage_name = "__jfield_value_%s" % name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self

        java_value = _get_java_field_value(_java_of(instance), self.name)
        if java_value is not _UNSET:
            instance.__dict__[self.storage_name] = java_value
            return java_value

        if self.storage_name in instance.__dict__:
            return instance.__dict__[self.storage_name]

        value = _copy_default(self.__jfield__.default)
        if value is _UNSET:
            return None
        instance.__dict__[self.storage_name] = value
        return value

    def __set__(self, instance, value):
        instance.__dict__[self.storage_name] = value
        _set_java_field_value(_java_of(instance), self.name, value)


class JMvelMethod:
    def __init__(self, metadata):
        self.__jproxy_method__ = metadata
        self.python_name = None

    def __set_name__(self, owner, name):
        self.python_name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self

        def call(*args):
            return self._invoke(instance, args)

        call.__name__ = self.python_name or "mvel"
        return call

    def _invoke(self, instance, args):
        metadata = self.__jproxy_method__
        names = metadata.arg_names
        if names is None:
            names = ["arg%d" % index for index in range(len(args))]

        environment = {
            "self": instance,
            "this": _java_of(instance),
            "args": list(args),
        }
        environment.update(zip(names, args))

        code = str(metadata.code or "").strip()
        code = re.sub(r"\bnull\b", "None", code)
        code = re.sub(r"\btrue\b", "True", code)
        code = re.sub(r"\bfalse\b", "False", code)
        code = code.rstrip(";").strip()
        if code.startswith("return "):
            code = code[len("return "):]

        try:
            return eval(code, {"__builtins__": __builtins__}, environment)
        except Exception as error:
            raise RuntimeError(
                "MVEL implementation of '%s' cannot run on iOS: %s" % (self.python_name, error)
            ) from error


class ClassInterceptor:
    """Receives every intercepted method call; Android's DexMaker callback analogue."""

    def __init__(self, fn=None, pyclass=None, **kwargs):
        self.fn = fn
        self.pyclass = pyclass
        self.kwargs = kwargs

    def run(self, instance, method_name, args):
        if self.pyclass is not None:
            handler = self.pyclass._resolve_method_handler(method_name, method_name)
            if handler is not None:
                attr = _find_class_attr(self.pyclass, handler)
                return _bind_attr(instance, attr)(*args)
        if self.fn is not None:
            return self.fn(instance, method_name, args)
        return None


def _collect_method_metadata(pyclass):
    methods = {}
    for current in reversed(pyclass.__mro__):
        for name, attr in current.__dict__.items():
            metadata = getattr(attr, "__jproxy_method__", None)
            if metadata is None:
                continue
            target = attr if not isinstance(attr, (classmethod, staticmethod)) else attr.__func__
            methods[name] = metadata.resolve(target, name)
    for name in getattr(pyclass, "__jlegacy_methods__", ()):
        pass
    return methods


def _collect_constructor_metadata(pyclass):
    constructors = {}
    for current in reversed(pyclass.__mro__):
        for name, attr in current.__dict__.items():
            metadata = getattr(attr, "__jproxy_constructor__", None)
            if metadata is None:
                continue
            target = attr if not isinstance(attr, (classmethod, staticmethod)) else attr.__func__
            constructors[name] = metadata.resolve(target, name)
    return constructors


def _collect_class_build_metadata(pyclass):
    hooks = []
    for current in reversed(pyclass.__mro__):
        for name, attr in current.__dict__.items():
            metadata = getattr(attr, "__jclass_build_hook__", None)
            if metadata is not None:
                hooks.append(metadata.resolve(name))
    return hooks


def _collect_field_metadata(pyclass):
    fields = {}
    for current in reversed(pyclass.__mro__):
        for name, attr in current.__dict__.items():
            if isinstance(attr, JField):
                fields[name] = attr.__jfield__.resolve(name)
    return fields


def _select_method_overload(candidates, args):
    if not candidates:
        return None
    exact = [
        candidate for candidate in candidates
        if candidate.arg_types is not None and len(candidate.arg_types) == len(args)
    ]
    if exact:
        return exact[0]
    wildcard = [candidate for candidate in candidates if candidate.arg_types is None]
    return wildcard[0] if wildcard else candidates[0]


def _build_method_specs(pyclass):
    specs = []
    for method in pyclass._resolved_jmethods().values():
        specs.append({
            "name": method.java_name,
            "signature": method.signature,
            "return_type": method.return_type,
            "arg_types": method.arg_types,
            "modifiers": method.modifiers,
            "kind": method.kind,
        })
    return specs


def _build_field_specs(pyclass):
    specs = []
    for field in pyclass._resolved_jfields().values():
        specs.append({
            "name": field.python_name,
            "type": field.field_type,
            "modifiers": field.modifiers,
        })
    return specs


def _build_method_dispatch(pyclass):
    exact = {}
    wildcard = {}
    for name, method in pyclass._resolved_jmethods().items():
        if method.kind != "method":
            continue
        if method.arg_types is None:
            wildcard[method.java_name] = name
        else:
            exact[method.signature] = name
    return {"exact": exact, "wildcard": wildcard}


def _build_constructor_dispatch(pyclass):
    post = {"exact": {}, "wildcard": None}
    pre = {"exact": {}, "wildcard": None}
    for name, constructor in pyclass._resolved_jconstructors().items():
        target = post if constructor.phase == "post" else pre
        if constructor.arg_types is None:
            target["wildcard"] = name
        else:
            target["exact"][constructor.signature] = name
    return {"post": post, "pre": pre}


def _parse_override_spec(signature, *, name=None, arg_types=None):
    if signature:
        if len(signature) > 1:
            raise ValueError("Override expects at most one signature")
        raw = signature[0]
        if isinstance(raw, str):
            parsed_name, parsed_types = _split_signature(raw)
            return name or parsed_name, list(parsed_types)
        if arg_types is None:
            arg_types = [raw]
    return name, _normalize_arg_types(arg_types, allow_none=True)


def _parse_method_spec(signature, *, return_type=None, arg_types=None, name=None):
    resolved_name = name
    if signature:
        raw = signature[0]
        if isinstance(raw, str):
            parsed_name, parsed_types = _split_signature(raw)
            resolved_name = resolved_name or parsed_name
            if arg_types is None and parsed_types:
                arg_types = list(parsed_types)
        elif len(signature) > 1:
            resolved_name = resolved_name or str(raw)
            if arg_types is None:
                arg_types = list(signature[1:])
        elif arg_types is None:
            arg_types = [raw]
    return resolved_name, return_type, _normalize_arg_types(arg_types, allow_none=True)


def _parse_constructor_spec(signature, *, arg_types=None):
    if arg_types is None and signature:
        if len(signature) == 1 and isinstance(signature[0], (list, tuple)):
            arg_types = list(signature[0])
        else:
            arg_types = list(signature)
    return _normalize_arg_types(arg_types, allow_none=True)


def _to_java_list(items):
    return NativeList(items or [])


class JHelper:
    @staticmethod
    def Override(*signature, arg_types=None, modifiers="public", throws=None, name=None):
        resolved_name, resolved_types = _parse_override_spec(signature, name=name, arg_types=arg_types)

        def decorator(fn):
            _unwrap_callable_attr(fn).__jproxy_method__ = _MethodMetadata(
                "override", None, resolved_types, modifiers, throws=throws, java_name=resolved_name
            )
            return fn

        return decorator

    @staticmethod
    def Overload(name, arg_types, *, modifiers="public", throws=None):
        return JHelper.Override(name, arg_types, modifiers=modifiers, throws=throws)

    @staticmethod
    def Method(*signature, return_type=None, arg_types=None, modifiers="public", throws=None, name=None):
        resolved_name, resolved_return, resolved_types = _parse_method_spec(
            signature, return_type=return_type, arg_types=arg_types, name=name
        )

        def decorator(fn):
            _unwrap_callable_attr(fn).__jproxy_method__ = _MethodMetadata(
                "method", resolved_return, resolved_types, modifiers, throws=throws, java_name=resolved_name
            )
            return fn

        return decorator

    @staticmethod
    def MVELMethod(*, code, return_type=None, arguments=None, arg_types=None,
                   modifiers="public", throws=None, name=None, override=False):
        names, types = _parse_argument_specs(arguments, arg_types=arg_types, allow_none=override)
        return JMvelMethod(_MethodMetadata(
            "override" if override else "method",
            return_type,
            types,
            modifiers,
            throws=throws,
            java_name=name,
            implementation="mvel",
            code=code,
            arg_names=names,
        ))

    @staticmethod
    def MVELOverride(*signature, code, arguments=None, arg_types=None,
                     modifiers="public", throws=None, name=None):
        resolved_name, signature_types = _parse_override_spec(signature, name=name, arg_types=arg_types)
        if arguments is not None and signature_types is not None:
            raise ValueError("Use either arguments or arg_types for MVEL overrides, not both")
        resolved_arguments = arguments if arguments is not None else signature_types
        return JHelper.MVELMethod(
            code=code,
            return_type=None,
            arguments=resolved_arguments,
            modifiers=modifiers,
            throws=throws,
            name=name,
            override=True,
        )

    @staticmethod
    def Constructor(*signature, arg_types=None):
        resolved_types = _parse_constructor_spec(signature, arg_types=arg_types)

        def decorator(fn):
            _unwrap_callable_attr(fn).__jproxy_constructor__ = _ConstructorMetadata(resolved_types, phase="post")
            return fn

        return decorator

    @staticmethod
    def PreConstructor(*signature, arg_types=None):
        resolved_types = _parse_constructor_spec(signature, arg_types=arg_types)

        def decorator(fn):
            _unwrap_callable_attr(fn).__jproxy_constructor__ = _ConstructorMetadata(resolved_types, phase="pre")
            return fn

        return decorator

    @staticmethod
    def Field(field_type, *, default=_UNSET, modifiers="public", methods=None):
        return JField(field_type, default=default, modifiers=modifiers, methods=methods)

    @staticmethod
    def GetMethod(name=None, *, modifiers="public"):
        return _FieldAccessorMetadata("get", name=name, modifiers=modifiers)

    @staticmethod
    def SetMethod(name=None, *, modifiers="public"):
        return _FieldAccessorMetadata("set", name=name, modifiers=modifiers)

    @staticmethod
    def ClassBuilder():
        def decorator(fn):
            _unwrap_callable_attr(fn).__jclass_build_hook__ = _ClassBuildMetadata()
            return fn

        return decorator


class Base:
    """iOS counterpart of the Android managed proxy base.

    Without ART there is no generated Java subclass, so a `Base` subclass owns a
    Python peer and, when the app has the corresponding object, a host handle in
    `_jthis`.  Method and field metadata keep the Android declaration syntax and
    are exposed to plugins that introspect it.
    """

    __jbaseclass__ = None
    __jinterfaces__ = ()
    __jproxy_class__ = None
    __jproxy_interceptor__ = None
    __jproxy_custom_name__ = None
    __jlegacy_methods__ = ()
    __jlegacy_constructors__ = ()
    __jresolved_methods__ = None
    __jresolved_constructors__ = None
    __jresolved_fields__ = None
    __jmethod_dispatch__ = None
    __jconstructor_dispatch__ = None
    __jclass_build_hooks_cache__ = None
    __jowner__ = None

    _peers = weakref.WeakSet()

    def __init__(self, *args, **kwargs):
        Base._peers.add(self)
        self.__dict__.setdefault("_jthis", None)

    @classmethod
    def on_pre_init(cls, *args):
        return None

    def on_post_init(self, *args):
        pass

    @property
    def java(self):
        return _java_of(self)

    @property
    def this(self):
        return self.java

    def __getattr__(self, item):
        if item == "_jthis":
            return None
        managed = self._managed_method(item)
        if managed is not None:
            return managed
        java_instance = _java_of(self)
        if java_instance is None:
            raise AttributeError(item)
        return getattr(java_instance, item)

    def jrelease(self):
        data = self.__dict__
        if data.get("_jthis") is None:
            return False
        try:
            self.on_release()
        except Exception:
            import traceback

            from log_utils import log

            log("Error in %s.on_release: %s" % (type(self).__name__, traceback.format_exc()))
        data.pop("_jthis", None)
        Base._peers.discard(self)
        return True

    def on_release(self):
        pass

    def _managed_method(self, name):
        candidates = [
            method
            for method in type(self)._resolved_jmethods().values()
            if method.java_name == name and method.implementation == "python"
        ]
        if not candidates:
            return None

        def dispatcher(*args):
            selected = _select_method_overload(candidates, args)
            if selected is None:
                java_instance = _java_of(self)
                if java_instance is None:
                    raise AttributeError(name)
                return getattr(java_instance, name)(*args)
            attr = _find_class_attr(type(self), selected.python_name)
            return _bind_attr(self, attr)(*args)

        return dispatcher

    @classmethod
    def _resolved_jmethods(cls):
        if cls.__jresolved_methods__ is None:
            cls.__jresolved_methods__ = _collect_method_metadata(cls)
        return cls.__jresolved_methods__

    @classmethod
    def _resolved_jconstructors(cls):
        if cls.__jresolved_constructors__ is None:
            cls.__jresolved_constructors__ = _collect_constructor_metadata(cls)
        return cls.__jresolved_constructors__

    @classmethod
    def _resolved_jfields(cls):
        if cls.__jresolved_fields__ is None:
            cls.__jresolved_fields__ = _collect_field_metadata(cls)
        return cls.__jresolved_fields__

    @classmethod
    def _method_dispatch(cls):
        if cls.__jmethod_dispatch__ is None:
            cls.__jmethod_dispatch__ = _build_method_dispatch(cls)
        return cls.__jmethod_dispatch__

    @classmethod
    def _constructor_dispatch(cls):
        if cls.__jconstructor_dispatch__ is None:
            cls.__jconstructor_dispatch__ = _build_constructor_dispatch(cls)
        return cls.__jconstructor_dispatch__

    @classmethod
    def _class_build_hooks(cls):
        if cls.__jclass_build_hooks_cache__ is None:
            cls.__jclass_build_hooks_cache__ = [hook.python_name for hook in _collect_class_build_metadata(cls)]
        return cls.__jclass_build_hooks_cache__

    @classmethod
    def _resolve_method_handler(cls, raw_name, simple_name):
        dispatch = cls._method_dispatch()
        return (
            dispatch["exact"].get(raw_name)
            or dispatch["wildcard"].get(simple_name)
            or (simple_name if _find_class_attr(cls, simple_name) is not None else None)
        )

    @classmethod
    def _resolve_constructor_handler(cls, phase, raw_name):
        dispatch = cls._constructor_dispatch()[phase]
        return dispatch["exact"].get(raw_name) or dispatch["wildcard"]

    @classmethod
    def extends(cls, java_class, *interfaces, methods=None, constructors=None, custom_name=None):
        def decorator(pyclass):
            for interface in interfaces:
                if not isinstance(interface, (ClassRef, type)):
                    raise ValueError("interfaces must be JavaClass types")
            if not issubclass(pyclass, Base):
                raise TypeError("Managed proxies must inherit from Base")
            pyclass.__jbaseclass__ = java_class
            pyclass.__jinterfaces__ = tuple(interfaces or ())
            pyclass.__jlegacy_methods__ = tuple(methods or ())
            pyclass.__jlegacy_constructors__ = tuple(constructors or ())
            pyclass.__jproxy_custom_name__ = _normalize_proxy_custom_name(custom_name) or pyclass.__name__
            pyclass.__jproxy_class__ = None
            pyclass.__jproxy_interceptor__ = None
            pyclass.__jresolved_methods__ = None
            pyclass.__jresolved_constructors__ = None
            pyclass.__jresolved_fields__ = None
            pyclass.__jmethod_dispatch__ = None
            pyclass.__jconstructor_dispatch__ = None
            pyclass.__jclass_build_hooks_cache__ = None
            return pyclass

        return decorator

    @classmethod
    def bind(cls, java_class, *interfaces, methods=None, constructors=None, custom_name=None):
        return cls.extends(
            java_class, *interfaces, methods=methods, constructors=constructors, custom_name=custom_name
        )(cls)

    @classmethod
    def java_class(cls):
        if cls.__jbaseclass__ is None:
            raise ValueError("%s is not bound to a Java class" % cls.__name__)
        if cls.__jproxy_class__ is None:
            cls.__jproxy_class__ = ClassRef(
                cls.__jbaseclass__.get_name()
                if isinstance(cls.__jbaseclass__, ClassRef)
                else str(cls.__jbaseclass__)
            )
        return cls.__jproxy_class__

    @classmethod
    def from_java(cls, instance, *, init_args=None):
        if instance is None:
            return None
        peer = cls.__new__(cls)
        Base.__init__(peer)
        peer._jthis = instance
        return peer

    @classmethod
    def _instantiate_java(cls, *args):
        base = cls.java_class()
        java_instance = base(*args)
        return java_instance, _build_signature("<constructor>", list(args))

    @classmethod
    def new_java_instance(cls, *args):
        java_instance, _ = cls._instantiate_java(*args)
        return java_instance

    @classmethod
    def new_instance(cls, *args, init_args=None):
        cls.on_pre_init(*args)
        java_instance, _ = cls._instantiate_java(*args)
        peer = cls.__new__(cls)
        Base.__init__(peer)
        peer._jthis = java_instance
        peer.on_post_init(*args)
        return peer

    @classmethod
    def newInstance(cls, *args, **kwargs):
        return cls.new_instance(*args, **kwargs)


def class_proxy(clazz, *, fn=None, interceptor=None, methods=None, constructors=None,
                custom_name=None, **kwargs):
    """Creates a proxy class for `clazz`.

    `interceptor` may be a `Base` subclass (the managed form); otherwise the
    callable is stored and receives `(instance, method_name, args)`, matching the
    Android `ClassInterceptor` contract.
    """
    if fn is None and interceptor is None:
        raise ValueError("fn or interceptor must be provided")

    if isinstance(interceptor, type) and issubclass(interceptor, Base):
        return interceptor.bind(clazz, methods=methods, constructors=constructors, custom_name=custom_name)

    base_name = clazz.get_name() if isinstance(clazz, ClassRef) else str(clazz)

    class _GeneratedProxy(Base):
        __jbaseclass__ = clazz
        __jproxy_custom_name__ = _normalize_proxy_custom_name(custom_name)
        __jproxy_fn__ = staticmethod(fn) if fn is not None else None
        __jproxy_interceptor__ = interceptor

        def _intercept(self, method_name, args):
            if self.__jproxy_fn__ is not None:
                return self.__jproxy_fn__(self, method_name, args)
            return self.__jproxy_interceptor__.run(self, method_name, args)

        def __getattr__(self, item):
            if item.startswith("_"):
                return Base.__getattr__(self, item)

            def dispatch(*args):
                return self._intercept(item, args)

            dispatch.__name__ = item
            return dispatch

    _GeneratedProxy.__name__ = _normalize_proxy_custom_name(custom_name) or ("Proxy_" + base_name.rsplit(".", 1)[-1])
    _GeneratedProxy.__qualname__ = _GeneratedProxy.__name__
    return _GeneratedProxy


def collect_peers():
    """Returns the live managed peers (iOS analogue of Android's Java peer scan)."""
    return list(Base._peers)


def release_plugin(plugin_id=None):
    """Releases peers and host objects owned by a plugin."""
    for peer in list(Base._peers):
        owner = getattr(type(peer), "__jowner__", None)
        if plugin_id is None or owner in (None, plugin_id):
            try:
                peer.jrelease()
            except Exception:
                pass
    try:
        return extera_ios.host("java.release_plugin", plugin_id=plugin_id)
    except Exception:
        return None


@Base.extends(ClassRef("java.lang.Object"))
class PyObj(Base):
    obj = JField("com.chaquo.python.PyObject")

    @classmethod
    def create(cls, obj):
        instance = cls.new_instance()
        instance.obj = obj
        return instance


joverride = JHelper.Override
joverload = JHelper.Overload
jmethod = JHelper.Method
jfield = JHelper.Field
jconstructor = JHelper.Constructor
jpreconstructor = JHelper.PreConstructor
jgetmethod = JHelper.GetMethod
jsetmethod = JHelper.SetMethod
jmvelmethod = JHelper.MVELMethod
jmveloverride = JHelper.MVELOverride
jMVELmethod = JHelper.MVELMethod
jMVELoverride = JHelper.MVELOverride
jclassbuilder = JHelper.ClassBuilder
java_subclass = Base.extends
jvoid = "void"
