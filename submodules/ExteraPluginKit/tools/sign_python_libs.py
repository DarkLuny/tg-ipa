#!/usr/bin/env python3
"""Sign the CPython ``lib-dynload`` shared objects inside an iOS app bundle.

The device build must re-sign every ``*.so`` under the bundled standard
library with the app's identity; the simulator does not require this.  Run
this on macOS after the app has been built and before installing it on a
device::

    python3 submodules/ExteraPluginKit/tools/sign_python_libs.py \
        --root "$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH"

The script searches recursively for directories named ``lib-dynload`` and
signs every ``*.so`` below them.  ``--dry-run`` prints the matches without
calling ``codesign`` and works on any OS.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def find_dynload_roots(root: str) -> list[str]:
    roots = []
    for base, dirs, _files in os.walk(root):
        if os.path.basename(base) == "lib-dynload":
            roots.append(base)
            dirs[:] = []
    return roots


def find_libraries(root: str) -> list[str]:
    libraries = []
    for dynload in find_dynload_roots(root):
        for name in sorted(os.listdir(dynload)):
            if name.endswith(".so"):
                libraries.append(os.path.join(dynload, name))
    return libraries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="app bundle or stdlib directory")
    parser.add_argument(
        "--identity",
        default=os.environ.get("EXPANDED_CODE_SIGN_IDENTITY")
        or os.environ.get("CODE_SIGN_IDENTITY")
        or "",
        help="codesign identity (default: Xcode's EXPANDED_CODE_SIGN_IDENTITY)",
    )
    parser.add_argument("--dry-run", action="store_true", help="only list the files")
    parser.add_argument("--verify", action="store_true", help="verify each signature")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    libraries = find_libraries(root)
    print("lib-dynload roots:", len(find_dynload_roots(root)))
    print("shared objects:", len(libraries))
    for library in libraries:
        print(" ", library)

    if args.dry_run:
        return 0
    if not args.identity:
        print(
            "error: no signing identity; pass --identity or set "
            "EXPANDED_CODE_SIGN_IDENTITY",
            file=sys.stderr,
        )
        return 2
    if not libraries:
        print("error: no lib-dynload/*.so files found", file=sys.stderr)
        return 1

    for library in libraries:
        subprocess.run(
            [
                "/usr/bin/codesign",
                "--force",
                "--sign",
                args.identity,
                "--timestamp=none",
                library,
            ],
            check=True,
        )
        if args.verify:
            subprocess.run(
                ["/usr/bin/codesign", "--verify", "--verbose=2", library],
                check=True,
            )
    print("signed", len(libraries), "shared objects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
