load("@build_bazel_rules_apple//apple:apple.bzl", "apple_dynamic_xcframework_import")
load("@build_bazel_rules_apple//apple:resources.bzl", "apple_resource_group")

# CPython 3.11.18 (Python-Apple-support 3.11-b13). The release tarball is
# vendored next to this file; see README.md for the checksum and the reason the
# `lib` symlinks are materialised as copies on Windows.
apple_dynamic_xcframework_import(
    name = "Python",
    xcframework_imports = glob(["Python.xcframework/**"]),
    visibility = ["//visibility:public"],
)

# The headers of the device slice are architecture-independent. They are a
# separate target so `PluginPython` can list them as inputs and `__has_include`
# sees them in a sandboxed build.
filegroup(
    name = "PythonHeaders",
    srcs = glob(["Python.xcframework/ios-arm64/Python.framework/Headers/**"]),
    visibility = ["//visibility:public"],
)

config_setting(
    name = "simulator_arm64",
    values = {"cpu": "ios_sim_arm64"},
    visibility = ["//visibility:public"],
)

config_setting(
    name = "simulator_x86_64",
    values = {"cpu": "ios_x86_64"},
    visibility = ["//visibility:public"],
)

# The standard library has to be in the app bundle; `structured_resources`
# keeps `encodings/`, `importlib/` and `lib-dynload/` as directories, which is
# required for imports. The device and simulator copies differ in
# `lib-dynload` and `_sysconfigdata*.py`.
apple_resource_group(
    name = "PythonStdlib",
    structured_resources = glob(["stdlib/**"]),
    visibility = ["//visibility:public"],
)

apple_resource_group(
    name = "PythonStdlibSimulator",
    structured_resources = glob(["stdlib-simulator/**"]),
    visibility = ["//visibility:public"],
)

apple_resource_group(
    name = "PythonStdlibSimulatorX86_64",
    structured_resources = glob(["stdlib-simulator-x86_64/**"]),
    visibility = ["//visibility:public"],
)
