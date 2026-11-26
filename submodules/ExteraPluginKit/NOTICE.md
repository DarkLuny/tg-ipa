# Notice

This directory contains an independent iOS implementation of the exteraGram
plugins interface.

The plugin format, the public SDK module names (`base_plugin`, `client_utils`,
`hook_utils`, `intents`, `file_utils`, `ui.alert`, `ui.settings`, ...), the
`BasePlugin` hook names and the metadata names (`__id__`, `__name__`, ...) come
from exteraGram:

    exteraGram for Android
    Copyright @exteraGram, 2022-2026
    https://github.com/exteraSquad/exteraGram
    GPL v3 or later, with ADDITIONAL_TERMS.md

The Swift, C and Python sources under `submodules/ExteraPluginKit` were written
for Telegram-iOS. They are licensed under the GNU GPL v2 or later, like
Telegram-iOS. A distributed fork must keep the exteraGram attribution required
by its licence and must not present itself as exteraGram or as endorsed by its
authors.

## Third-party code

`PythonSupport/sdk/_vendor/yaml` is PyYAML, MIT licence,
https://pyyaml.org/. Its licence text is kept at `_vendor/yaml/LICENSE`.

`PythonSupport/sdk/_vendor/packaging` is `packaging`, Apache-2.0 or
BSD-2-Clause, https://github.com/pypa/packaging. Its licence text is in
`_vendor/packaging-*.dist-info/`.

`PythonSupport/sdk/_vendor/requests.py` is a small compatibility shim written
for this port; it is not the `requests` project.
