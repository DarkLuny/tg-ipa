# This is the iOS counterpart of the exteraGram plugins SDK.
#
# The reflection helpers keep their Android names and return handles the host
# can act on.  `get_method` names an Objective-C selector; `get_field` names a
# property/key path.  A member that does not exist still returns a handle so a
# plugin's `if method is None` branches stay meaningful, but calling it reports
# the missing selector precisely.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import traceback
from typing import Any, Optional

import extera_ios
from extera_utils.classes import ClassRef, MemberRef, ObjectProxy, java_class as _java_class
from log_utils import log


JavaClass = ClassRef
JavaObject = ObjectProxy


def jarray(element_class):
    """Chaquopy's `jarray(type)(values)`; iOS backs the array with a native list."""
    def build(values=()):
        from extera_utils.classes import NativeList

        if isinstance(values, int):
            return NativeList()
        return NativeList(values or ())

    build.element_class = element_class
    return build


def cast(type_or_class, value):
    """Chaquopy's `cast`; the facade already presents the target object."""
    return value


def find_class(class_name):
    if not isinstance(class_name, str):
        return None
    try:
        return _java_class(class_name)
    except Exception:
        log("Error finding class '%s': %s" % (class_name, traceback.format_exc()))
        return None


def _owner(clazz):
    if isinstance(clazz, ClassRef):
        return clazz
    if isinstance(clazz, str):
        return ClassRef(clazz)
    if isinstance(clazz, ObjectProxy):
        target = clazz.get_class()
        if isinstance(target, ClassRef):
            return target
        name = getattr(target, "__name__", None)
        return ClassRef(str(name)) if name else None
    name = getattr(clazz, "__name__", None)
    return ClassRef(str(name)) if name else None


def get_method(clazz, method_name, *param_types):
    owner = _owner(clazz)
    if owner is None:
        return None
    return MemberRef(owner.get_name(), method_name, param_types, "method")


def get_constructor(clazz, *param_types):
    owner = _owner(clazz)
    if owner is None:
        return None
    return MemberRef(owner.get_name(), "init", param_types, "constructor")


def get_field(clazz, field_name):
    owner = _owner(clazz)
    if owner is None:
        return None
    return MemberRef(owner.get_name(), field_name, (), "field")


def get_private_field(obj, field_name):
    if not isinstance(obj, ObjectProxy) or not isinstance(field_name, str):
        return None
    return obj.__getattr__(field_name)


def set_private_field(obj, field_name, new_value):
    if not isinstance(obj, ObjectProxy) or not isinstance(field_name, str):
        return False
    setattr(obj, field_name, new_value)
    return True


def get_static_private_field(clazz, field_name):
    owner = _owner(clazz)
    if owner is None or not isinstance(field_name, str):
        return None
    return extera_ios.host(
        "java.get_static_field", class_name=owner.get_name(), member=field_name
    )


def set_static_private_field(clazz, field_name, new_value):
    owner = _owner(clazz)
    if owner is None or not isinstance(field_name, str):
        return False
    return bool(extera_ios.host(
        "java.set_static_field",
        class_name=owner.get_name(),
        member=field_name,
        value=new_value,
    ))


def java_class(clazz):
    if isinstance(clazz, str):
        return _java_class(clazz)
    if isinstance(clazz, ClassRef):
        return clazz
    return _owner(clazz)


def _java_lang_class(clazz):
    if isinstance(clazz, ClassRef):
        return clazz
    if isinstance(clazz, str):
        return _java_class(clazz)
    if isinstance(clazz, ObjectProxy):
        return clazz.get_class()
    name = getattr(clazz, "__name__", None)
    return _java_class(name) if name else None


_PRIMITIVE_BOXES = {
    "boolean": "java.lang.Boolean", "byte": "java.lang.Byte", "char": "java.lang.Character",
    "short": "java.lang.Short", "int": "java.lang.Integer", "long": "java.lang.Long",
    "float": "java.lang.Float", "double": "java.lang.Double", "void": "java.lang.Void",
}

_ARRAY_PRIMITIVES = {
    "Z": "boolean", "B": "byte", "C": "char", "S": "short",
    "I": "int", "J": "long", "F": "float", "D": "double",
}


def _class_for_name(name):
    """Resolves a class name, including `int`, `boolean[]` and `[Z` forms."""
    if not isinstance(name, str):
        return None
    base = name.strip()
    dimensions = 0
    while base.endswith("[]"):
        base = base[:-2].rstrip()
        dimensions += 1
    if base.startswith("[") and base[1:2] in _ARRAY_PRIMITIVES:
        dimensions += 1
        base = _ARRAY_PRIMITIVES[base[1:2]]
    elif base.startswith("["):
        dimensions += 1
        base = base[1:].lstrip("L").rstrip(";")
    if base in _PRIMITIVE_BOXES:
        base = _PRIMITIVE_BOXES[base]
    resolved = _java_class(base)
    if resolved is None:
        return None
    return ClassRef(resolved.get_name() + "[]" * dimensions) if dimensions else resolved


def _parameter_classes(param_types):
    classes = []
    for param_type in param_types or ():
        resolved = _class_for_name(param_type) if isinstance(param_type, str) else _java_lang_class(param_type)
        if resolved is None:
            return None
        classes.append(resolved)
    return classes


def _find_declared_field(java_class, field_name):
    owner = _java_lang_class(java_class)
    if owner is None or not isinstance(field_name, str):
        return None
    return MemberRef(owner.get_name(), field_name, (), "field")
