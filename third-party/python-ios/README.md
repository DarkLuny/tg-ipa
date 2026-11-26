# CPython for iOS (vendored)

Vendored release:
[Python-Apple-support 3.11-b13](https://github.com/beeware/Python-Apple-support/releases/tag/3.11-b13)

```
Python-3.11-iOS-support.b13.tar.gz
sha256 e1f55eef2b8c4812f63ee02f8284c8db067ef1a26e75b9a470934376ac197ea0
Python 3.11.18, minimum iOS 13.0
```

Contents:

- `Python.xcframework/` — device and simulator slices of `Python.framework`;
- `stdlib/python3.11/` — the device standard library;
- `stdlib-simulator/python3.11/` — the arm64 simulator standard library;
- `stdlib-simulator-x86_64/python3.11/` — the x86_64 simulator standard library
  (`lib-x86_64/python3.11` plus the pure-Python files).

The release archive stores `ios-arm64/lib/libpython3.11.dylib` as a symlink to
`../Python.framework/Python`. Windows `tar` cannot create that symlink, so this
tree materialises it as a copy and copies `lib-arm64/python3.11` into `lib/`.
The archive itself is unmodified (`sha256` above).

`BUILD` exposes:

- `Python` — `apple_dynamic_xcframework_import` used by the app and by
  `//submodules/ExteraPluginKit:PluginPython`;
- `PythonHeaders` — the framework headers, listed as an input of `PluginPython`
  so a sandboxed compile sees `Python.h`;
- `PythonStdlib`, `PythonStdlibSimulator`, `PythonStdlibSimulatorX86_64` —
  `apple_resource_group` targets with `structured_resources`, so
  `encodings/`, `importlib/` and `lib-dynload/` stay directories.

`Telegram/BUILD` selects the stdlib for the target CPU:

| CPU | Resource |
|---|---|
| `ios_arm64` (device) | `PythonStdlib` |
| `ios_sim_arm64` | `PythonStdlibSimulator` |
| `ios_x86_64` | `PythonStdlibSimulatorX86_64` |

`PluginStore.bundledStdlibDirectory()` also searches the app resources
recursively for a `python3.11` directory containing `encodings/__init__.py`, so
a different resource layout still resolves.

On a device the `.so` files in `lib-dynload` are executable code and must be
signed with the app identity; the simulator does not require it.
