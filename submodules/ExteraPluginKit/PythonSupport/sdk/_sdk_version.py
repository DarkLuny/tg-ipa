# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Version and integrity guard.  The Android SDK uses `Z.c()` as an anti-tamper
# barrier called from every public entry point; the iOS SDK keeps the call so
# plugin code and the SDK modules written against the Android SDK stay
# source-compatible.  On iOS the code runs inside the app sandbox and the
# signature of a plugin is checked by the installer (`PluginAnalyzer`), which is
# the equivalent protection.
#
# `X.BUILD_VERSION` follows the exteraGram build numbering: plugins use it to
# gate features (`>= 66690` file icons, `>= 66999` intents).  The value below is
# the highest feature line this engine implements.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

__version__ = "1.4.6.5"
version = (1, 4, 6, 5)
version_str = __version__

__beta__ = False
beta = __beta__

# The app build the SDK was written for.  A plugin declaring
# `__app_version__ = ">=12.5.1"` is checked against the real app version by the
# host; this constant is only the floor the SDK itself requires.
MIN_APP_VERSION = "12.5.1"

# Feature line: file icons (66690) and the intent manager (66999).
COMPATIBILITY_BUILD_VERSION = 66999

_SAFE_MODE_IMPORTER_TAG = "extera.plugins_pysdk.SafeModeImporter"


class SafeModeImporter:
    """Android's safe-mode gate, kept as a no-op unless safe mode is set.

    iOS does not run ART and has no global import barrier; `PluginManager`
    disables a plugin after a crash and the interpreter is restarted.  The class
    keeps the same flags and `c()` entry point so SDK modules and plugins that
    call `_sdk_version.Z.c()` keep working.
    """

    IS_OLD_VERSION = False
    I = False
    E = False
    _hooks = []

    def find_spec(self, fullname, path=None, target=None):
        if self.E:
            if self.IS_OLD_VERSION:
                raise RuntimeError(
                    "App version is too old. Please update app to the last stable version."
                )
            raise RuntimeError("Safe mode enabled")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        pass

    @classmethod
    def c(cls):
        if cls.E:
            if cls.IS_OLD_VERSION:
                raise RuntimeError(
                    "App version is too old. Please update app to the last stable version."
                )
            raise RuntimeError("Safe mode enabled")
        return None


Z = SafeModeImporter.INSTANCE = SafeModeImporter()
Z.__safe_mode_importer_tag__ = _SAFE_MODE_IMPORTER_TAG


class X:
    BUILD_VERSION = COMPATIBILITY_BUILD_VERSION


def _is_safe_mode_importer_entry(entry):
    if entry is Z:
        return True
    try:
        if getattr(entry, "__safe_mode_importer_tag__", None) == _SAFE_MODE_IMPORTER_TAG:
            return True
    except Exception:
        pass
    try:
        entry_cls = entry.__class__
        if (
            entry_cls.__name__ == "SafeModeImporter"
            and entry_cls.__module__ == __name__
        ):
            return True
    except Exception:
        pass
    return False


def _remove_safe_mode_importers():
    import sys

    sys.meta_path[:] = [
        entry for entry in sys.meta_path
        if not _is_safe_mode_importer_entry(entry)
    ]


def _reset_state():
    SafeModeImporter.IS_OLD_VERSION = False
    SafeModeImporter.I = False
    SafeModeImporter.E = False


def require_app_version(actual):
    """Returns True when `actual` is not older than MIN_APP_VERSION."""
    def parts(value):
        result = []
        for piece in str(value).split("."):
            try:
                result.append(int(piece))
            except ValueError:
                result.append(0)
        return result

    left = parts(actual)
    right = parts(MIN_APP_VERSION)
    length = max(len(left), len(right))
    left += [0] * (length - len(left))
    right += [0] * (length - len(right))
    return left >= right


def check_safemode():
    """iOS never enters the Android safe mode; the crash marker lives in Swift."""
    return True


def setup_hooks():
    """Android installs Xposed bridges here; iOS has no equivalent."""
    return None


def __start__():
    try:
        _remove_safe_mode_importers()
        _reset_state()
        SafeModeImporter.I = True
        if X.BUILD_VERSION >= 66999:
            try:
                import elyxcore

                elyxcore._setup()
            except Exception:
                pass
        return True
    except Exception:
        return False


def __stop__():
    try:
        from extera_utils.lifecycle import stop_all

        stop_all()
    except Exception:
        pass
    try:
        _remove_safe_mode_importers()
    except Exception:
        import sys
        import traceback

        sys.stderr.write(traceback.format_exc())

    try:
        from file_utils import FilesController

        FilesController._stop()
    except Exception:
        pass

    try:
        from intents import IntentsManager

        IntentsManager._stop()
    except Exception:
        pass

    try:
        from telegram_compat import remove_observers_for_plugin

        remove_observers_for_plugin("")
    except Exception:
        pass

    SafeModeImporter._hooks = []
    _reset_state()
