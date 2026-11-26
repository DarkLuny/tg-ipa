# This is the iOS counterpart of ElyxCore's engine bootstrap.
#
# Android registers `ElyxEngine` in `PluginsController.getEngines()` and waits
# for the controller to initialize.  iOS owns one Python engine; the Swift
# `PluginManager` calls `elyx_setup` and merges the scanned plugins into its
# list, so this module only starts and stops the engine object.
#
# Licensed under the GPL v2 or later, like the rest of this repository.

from elyxcore._dev_server import ElyxDevServer
from elyxcore._ios_engine import setup as setup_engine, stop as stop_engine

engine = None


def _setup():
    global engine
    if engine is not None:
        return engine
    engine = setup_engine()
    try:
        ElyxDevServer.setup()
    except Exception:
        pass
    return engine


def _stop():
    global engine
    try:
        ElyxDevServer.teardown()
    except Exception:
        pass
    engine = None
    stop_engine()
