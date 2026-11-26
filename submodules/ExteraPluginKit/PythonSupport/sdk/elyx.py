# This is the iOS counterpart of the exteraGram plugins SDK.
#
# `elyx` is the public facade for structured `.elyx` plugins, matching the
# module name plugin code imports on Android.  The implementation lives in
# `elyxcore`; this module only re-exports the supported symbols and the two
# runtime helpers.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

from elyxcore.assets import (
    Asset,
    AssetNotFoundException,
    Assets,
    AssetsDirNotFoundException,
)
from elyxcore.localization import Strings
from elyxcore.settings import SettingsController
from elyxcore.utils import LazyDict, gen, gen2, mvel_execute
from elyxcore import get_environment, import_module

__all__ = (
    "Asset",
    "AssetNotFoundException",
    "Assets",
    "AssetsDirNotFoundException",
    "LazyDict",
    "SettingsController",
    "Strings",
    "gen",
    "gen2",
    "get_environment",
    "import_module",
    "mvel_execute",
)
