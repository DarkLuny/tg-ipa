# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Helpers for the Objective-C runtime and for the app's own iOS API.  A plugin
# written for Android uses `hook_utils.get_method(...)`; on iOS the same call
# returns a `MemberRef` that names an Objective-C selector, and `hook_method`
# installs it through the host.  Swift methods that are not exposed to
# Objective-C cannot be swizzled, and the host reports that instead of claiming
# a hook was installed.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import extera_ios


def class_exists(name):
    return bool(extera_ios.host("runtime.class_exists", name=str(name)))


def selector_exists(class_name, selector):
    return bool(extera_ios.host(
        "runtime.selector_exists", class_name=str(class_name), selector=str(selector)
    ))


def responds_to(object_handle, selector):
    return bool(extera_ios.host(
        "runtime.responds_to", target=object_handle, selector=str(selector)
    ))


def call(object_handle, selector, *args):
    return extera_ios.host(
        "runtime.call",
        target=object_handle,
        selector=str(selector),
        args=list(args),
    )


def get_property(object_handle, name):
    return extera_ios.host("runtime.get_property", target=object_handle, name=str(name))


def set_property(object_handle, name, value):
    return extera_ios.host(
        "runtime.set_property", target=object_handle, name=str(name), value=value
    )


def swizzle(class_name, selector, before_handle=None, after_handle=None, replace_handle=None):
    """Installs a method hook on an Objective-C method.

    Returns a hook handle, or None when the class/selector is not reachable from
    Objective-C (the usual reason is a Swift method without `@objc`).
    """
    return extera_ios.host(
        "runtime.swizzle",
        class_name=str(class_name),
        selector=str(selector),
        before=before_handle,
        after=after_handle,
        replace=replace_handle,
    )


def unswizzle(handle):
    return extera_ios.host("runtime.unswizzle", handle=handle)


def is_main_thread():
    return bool(extera_ios.host("runtime.is_main_thread"))


def os_version():
    return str(extera_ios.host("device.info").get("system", ""))
