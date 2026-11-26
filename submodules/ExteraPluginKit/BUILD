load("@rules_cc//cc:objc_library.bzl", "objc_library")
load("@build_bazel_rules_swift//swift:swift.bzl", "swift_library")
load("@build_bazel_rules_apple//apple:resources.bzl", "apple_resource_bundle", "apple_resource_group")
load("//build-system/bazel-utils:plist_fragment.bzl", "plist_fragment")

# The Python SDK is copied into the app bundle as `ExteraPlugins.bundle` and
# unpacked into Application Support on first launch, so a plugin sees a writable
# directory and an SDK update can replace it without touching user data.
plist_fragment(
    name = "ExteraPluginsInfo",
    extension = "plist",
    template = "<key>CFBundleIdentifier</key><string>org.telegram.ExteraPlugins</string><key>CFBundleName</key><string>ExteraPlugins</string>",
)

apple_resource_group(
    name = "ExteraPluginsSDKResources",
    structured_resources = glob([
        "PythonSupport/sdk/**",
    ]),
)

apple_resource_bundle(
    name = "ExteraPluginsBundle",
    bundle_name = "ExteraPlugins",
    infoplists = [":ExteraPluginsInfo"],
    resources = [":ExteraPluginsSDKResources"],
    visibility = ["//visibility:public"],
)

# CPython bridge. The C file compiles to a stub when no Python headers are on
# the include path, so the app links without the runtime and reports
# `isAvailable == false`; see README.md for adding Python-Apple-support.
objc_library(
    name = "PluginPython",
    srcs = ["PythonSupport/src/PluginPython.c"],
    hdrs = [
        "PythonSupport/include/PluginPython.h",
        "//third-party/python-ios:PythonHeaders",
    ],
    includes = [
        "PythonSupport/include",
        "../../third-party/python-ios/Python.xcframework/ios-arm64/Python.framework/Headers",
    ],
    copts = ["-fno-objc-arc"],
    sdk_frameworks = ["Foundation"],
    deps = [
        "//third-party/python-ios:Python",
    ],
    visibility = ["//visibility:public"],
)

swift_library(
    name = "ExteraPluginKit",
    module_name = "ExteraPluginKit",
    srcs = glob([
        "Sources/**/*.swift",
    ]),
    copts = [
        "-warnings-as-errors",
    ],
    linkopts = [
        "-framework",
        "NaturalLanguage",
    ],
    deps = [
        ":PluginPython",
    ],
    visibility = [
        "//visibility:public",
    ],
)
