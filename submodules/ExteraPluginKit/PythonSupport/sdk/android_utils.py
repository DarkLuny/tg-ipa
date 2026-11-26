# This is the iOS counterpart of the exteraGram plugins SDK.
#
# The Android SDK calls these helpers `android_utils`; the module keeps the name
# so a plugin that does `from android_utils import log, run_on_ui_thread` runs
# unchanged.  Every operation maps to an iOS host call.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import traceback

import extera_ios


def log(data):
    """Android's legacy logger: dumps objects and splits long text."""
    if isinstance(data, (str, int, float, bool)) or data is None:
        text = str(data)
    else:
        try:
            from log_utils import dump

            text = dump(data)
        except Exception:
            text = str(data)
    try:
        from log_utils import _split_for_logcat

        chunks = _split_for_logcat(text)
    except Exception:
        chunks = [text]
    for chunk in chunks:
        extera_ios.log(chunk)


def copy_to_clipboard(text):
    extera_ios.copy_to_clipboard(text)
    try:
        from ui.bulletin import BulletinHelper

        BulletinHelper.show_copied_to_clipboard()
    except Exception:
        pass


def run_on_ui_thread(func, delay=0):
    """Posts `func` to the main queue and returns its managed callback.

    Android returns a `ManagedCallback` whose `cancel()` removes the runnable
    from the UI queue.  iOS keeps that contract on top of the host's work item
    handle, so plugin code written against the Android SDK can cancel a queued
    task the same way.
    """
    if not callable(func):
        raise TypeError("func must be callable")
    from extera_utils.lifecycle import bind_task

    callback = bind_task(func, once=True)
    try:
        handle = extera_ios.run_on_ui_thread(callback, delay)
    except BaseException:
        callback.cancel()
        raise
    if handle:
        callback.set_cancel(lambda: extera_ios.cancel_ui_task(handle))
    return callback


class _Runnable:
    """The Android `Runnable` shim: a callable wrapper with `run()`."""

    def __init__(self, function):
        if not callable(function):
            raise TypeError("fn must be callable")
        self.function = function

    def run(self):
        return self.function()


def R(fn):
    return _Runnable(fn)


# Android SDK internal name used by `android_utils._void_callback`.
_R = R


def _void_callback(fn):
    """Wraps a Python callable as a void callback; errors are logged."""
    def callback(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception:
            log("Error in void callback: %s" % traceback.format_exc())

    return callback


class OnClickListener:
    def __init__(self, function):
        self._fn = function

    def onClick(self, _view):
        try:
            self._fn(_view)
        except Exception:
            log("Error in onClick listener: %s" % traceback.format_exc())


class OnLongClickListener:
    def __init__(self, function):
        self._fn = function

    def onLongClick(self, _view):
        try:
            result = self._fn(_view)
            return True if result is None else bool(result)
        except Exception:
            log("Error in onLongClick listener: %s" % traceback.format_exc())
            return False
