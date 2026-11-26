import Foundation

/// Declarations for `PluginPython.c`.
///
/// They are declared here instead of importing a Clang module so the kit has no
/// bridging header of its own and can be linked into an app, an extension or a
/// test bundle without build-system changes. The C side is the only place that
/// includes `Python.h`.
@_silgen_name("pl_python_available")
func extera_pl_python_available() -> Int32

@_silgen_name("pl_python_start")
func extera_pl_python_start(
    _ sdkPath: UnsafePointer<CChar>?,
    _ pluginsPath: UnsafePointer<CChar>?,
    _ filesPath: UnsafePointer<CChar>?,
    _ stdlibPath: UnsafePointer<CChar>?,
    _ error: UnsafeMutablePointer<UnsafeMutablePointer<CChar>?>?
) -> Int32

@_silgen_name("pl_python_call_json")
func extera_pl_python_call_json(
    _ function: UnsafePointer<CChar>?,
    _ arguments: UnsafePointer<CChar>?,
    _ error: UnsafeMutablePointer<UnsafeMutablePointer<CChar>?>?
) -> UnsafeMutablePointer<CChar>?

@_silgen_name("pl_python_invoke")
func extera_pl_python_invoke(
    _ handle: UnsafePointer<CChar>?,
    _ payload: UnsafePointer<CChar>?,
    _ error: UnsafeMutablePointer<UnsafeMutablePointer<CChar>?>?
) -> UnsafeMutablePointer<CChar>?

@_silgen_name("pl_python_stop")
func extera_pl_python_stop()

@_silgen_name("pl_python_free")
func extera_pl_python_free(_ value: UnsafeMutablePointer<CChar>?)
