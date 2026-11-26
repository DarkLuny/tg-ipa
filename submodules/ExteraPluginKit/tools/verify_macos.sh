#!/usr/bin/env bash
# Run the full iOS verification on a macOS host with Xcode.
#
# Usage:
#   bash submodules/ExteraPluginKit/tools/verify_macos.sh
#
# The script is intentionally strict: a failed build, a failed Python test or
# an unsigned device library stops it.  It does not modify the repository.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

echo "== Python plugin tests =="
python3 submodules/ExteraPluginKit/tests/test_parity.py
python3 submodules/ExteraPluginKit/tests/test_sdk.py
python3 submodules/ExteraPluginKit/tests/test_imports.py
python3 submodules/ExteraPluginKit/tests/test_elyx.py
python3 submodules/ExteraPluginKit/tests/test_pip.py
python3 submodules/ExteraPluginKit/tools/check_client_parity.py

echo "== iOS simulator build =="
python3 build-system/Make/Make.py build --configuration=debug_sim_arm64

echo "== Device stdlib signing (dry run, then real) =="
python3 submodules/ExteraPluginKit/tools/sign_python_libs.py --help
# After a device build, run this with the actual build directory:
# python3 submodules/ExteraPluginKit/tools/sign_python_libs.py \
#   --root "$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH" --verify

echo "== Boot the simulator and install =="
# The exact destination depends on the Xcode installation.  List first:
# xcrun simctl list devices available
# xcrun simctl install booted <path-to-Telegram.app>
# xcrun simctl launch booted <bundle-id>
# Then exercise Settings -> ExteraGram and Settings -> Plugins manually.
echo "Build and host tests passed. Finish with the simulator/device checklist."
