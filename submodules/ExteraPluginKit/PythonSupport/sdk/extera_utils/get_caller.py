# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Caller and plugin-id detection.  The function names and return shapes match
# the Android module; the iOS plugin runtime loads `<id>.plugin` files under the
# `extera_plugin_<id>` module name, so both conventions are understood.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import inspect
import os


ELYX_PLUGIN_NAMESPACE = "ElyxPlugins"
PLUGIN_MODULE_PREFIX = "extera_plugin_"

# Kept for older iOS SDK callers.
IOS_PLUGIN_NAMESPACE = PLUGIN_MODULE_PREFIX


def _get_callable_location(fn):
    """Returns `(filename, function, firstlineno, module)` for a callable."""
    target = fn
    seen = set()

    for _ in range(5):
        if target is None or id(target) in seen:
            break
        seen.add(id(target))

        code = getattr(target, "__code__", None)
        if code is not None:
            return (
                code.co_filename,
                code.co_name,
                code.co_firstlineno,
                getattr(target, "__module__", ""),
            )

        next_target = getattr(target, "__wrapped__", None)
        if next_target is None:
            next_target = getattr(target, "__func__", None)
        if next_target is None:
            next_target = getattr(target, "func", None)
        if next_target is None:
            next_target = getattr(type(target), "__call__", None)
        target = next_target

    return None


def _plugin_id_from_location(filename, module_name=""):
    module_parts = str(module_name or "").split(".")
    if len(module_parts) > 1 and module_parts[0] == ELYX_PLUGIN_NAMESPACE:
        return module_parts[1]
    if len(module_parts) >= 1 and module_parts[0].startswith(PLUGIN_MODULE_PREFIX):
        remainder = module_parts[0][len(PLUGIN_MODULE_PREFIX):]
        if remainder:
            return remainder

    path = str(filename or "").replace("\\", "/")
    path_parts = path.split("/")

    if ELYX_PLUGIN_NAMESPACE in path_parts:
        index = path_parts.index(ELYX_PLUGIN_NAMESPACE)
        if index + 1 < len(path_parts):
            return path_parts[index + 1]

    if "plugins" in path_parts:
        index = path_parts.index("plugins")
        if index + 1 < len(path_parts):
            name = path_parts[index + 1]
            return os.path.splitext(name)[0]

    if path.endswith(".plugin"):
        return os.path.splitext(os.path.basename(path))[0]

    return os.path.splitext(os.path.basename(path))[0]


def _format_location(filename, function, lineno, module_name=""):
    plugin_id = _plugin_id_from_location(filename, module_name)
    return "[%s:%s:%s] " % (os.path.basename(str(filename)), function, lineno), plugin_id


def get_plugin_id(fn=None):
    """Returns `(location_prefix, plugin_id)`, like the Android SDK."""
    try:
        location = _get_callable_location(fn)
    except Exception:
        location = None
    if location is not None:
        return _format_location(*location)

    frame = None
    caller_frame = None
    try:
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_frame = frame.f_back.f_back
        if caller_frame:
            code = caller_frame.f_code
            return _format_location(
                code.co_filename,
                code.co_name,
                caller_frame.f_lineno,
                caller_frame.f_globals.get("__name__", ""),
            )
    except Exception:
        pass
    finally:
        del frame
        del caller_frame

    return "", ""
