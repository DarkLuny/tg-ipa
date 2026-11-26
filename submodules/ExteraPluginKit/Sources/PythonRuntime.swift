import Foundation
#if canImport(Darwin)
import Darwin
#endif

public struct PluginRuntimeError: Error, CustomStringConvertible, Sendable {
    public var message: String

    public init(_ message: String) {
        self.message = message
    }

    public var description: String {
        return self.message
    }
}

public struct PluginRuntimeInfo: Sendable {
    public var sdkVersion: String
    public var appVersion: String
    public var sdkPath: String
    public var pluginsPath: String
}

/// Swift face of the CPython bridge.
///
/// Every call is JSON on the C boundary, so this class never touches `PyObject`.
/// The interpreter runs on its own serial queue; `call` is synchronous and safe
/// to use from the main thread as long as the runtime is started.
public final class PythonRuntime: @unchecked Sendable {
    public static let shared = PythonRuntime()

    private let queue = DispatchQueue(label: "com.exteragram.plugins.python", qos: .userInitiated)
    private let queueKey = DispatchSpecificKey<UInt8>()
    private let lock = NSLock()
    private let startLock = NSRecursiveLock()
    private var started = false
    private var startError: String?
    public private(set) var info: PluginRuntimeInfo?

    private init() {
        self.queue.setSpecific(key: self.queueKey, value: 1)
    }

    public var isAvailable: Bool {
        return extera_pl_python_available() != 0
    }

    public var isStarted: Bool {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.started
    }

    /// Starts the interpreter and imports `_extera_runtime`.
    @discardableResult
    public func start(sdkPath: URL, pluginsPath: URL, filesPath: URL, stdlibPath: URL? = nil) throws -> PluginRuntimeInfo {
        self.startLock.lock()
        defer { self.startLock.unlock() }

        self.lock.lock()
        if let info = self.info {
            self.lock.unlock()
            return info
        }
        self.lock.unlock()

        guard self.isAvailable else {
            throw PluginRuntimeError("this build was compiled without the CPython runtime")
        }

        var startFailure: String?
        var startedInfo: PluginRuntimeInfo?
        self.performOnQueue {
            var errorPointer: UnsafeMutablePointer<CChar>?
            let status: Int32
            if let stdlibPath {
                status = stdlibPath.path.withCString { stdlibPointer in
                    extera_pl_python_start(sdkPath.path, pluginsPath.path, filesPath.path, stdlibPointer, &errorPointer)
                }
            } else {
                status = extera_pl_python_start(sdkPath.path, pluginsPath.path, filesPath.path, nil, &errorPointer)
            }
            if status != 0 {
                startFailure = errorPointer.map { String(cString: $0) } ?? "the Python interpreter did not start"
                if let errorPointer {
                    extera_pl_python_free(errorPointer)
                }
                return
            }

            self.lock.lock()
            self.started = true
            self.lock.unlock()

            let raw = (try? self.call("runtime_version", [])) ?? [String: Any]()
            let object = raw as? [String: Any] ?? [:]
            startedInfo = PluginRuntimeInfo(
                sdkVersion: (object["sdk"] as? String) ?? "0",
                appVersion: PluginHostInfo.appVersion,
                sdkPath: sdkPath.path,
                pluginsPath: pluginsPath.path
            )
        }

        if let startFailure {
            self.lock.lock()
            self.startError = startFailure
            self.lock.unlock()
            throw PluginRuntimeError(startFailure)
        }
        guard let startedInfo else {
            throw PluginRuntimeError("the Python interpreter did not produce runtime information")
        }
        self.lock.lock()
        self.info = startedInfo
        self.lock.unlock()
        return startedInfo
    }

    public func stop() {
        guard self.isStarted else {
            return
        }
        self.performOnQueue {
            extera_pl_python_stop()
        }
        self.lock.lock()
        self.started = false
        self.info = nil
        self.lock.unlock()
    }

    /// Calls `_extera_runtime.<function>(*args)`. Returns the decoded JSON value.
    public func call(_ function: String, _ args: [Any]) throws -> Any {
        guard self.isStarted else {
            throw PluginRuntimeError("the plugin runtime is not started")
        }
        let payload: String
        do {
            let data = try JSONSerialization.data(withJSONObject: args, options: [])
            payload = String(data: data, encoding: .utf8) ?? "[]"
        } catch {
            throw PluginRuntimeError("could not encode the arguments for \(function): \(error)")
        }

        var errorPointer: UnsafeMutablePointer<CChar>?
        let result: UnsafeMutablePointer<CChar>? = self.performOnQueue {
            extera_pl_python_call_json(function, payload, &errorPointer)
        }
        if let errorPointer {
            let message = String(cString: errorPointer)
            extera_pl_python_free(errorPointer)
            throw PluginRuntimeError(message)
        }
        guard let result else {
            throw PluginRuntimeError("\(function) returned no result")
        }
        let text = String(cString: result)
        extera_pl_python_free(result)
        if text.isEmpty || text == "null" {
            return NSNull()
        }
        return (try? JSONSerialization.jsonObject(with: Data(text.utf8))) ?? text
    }

    /// Runs a retained Python callback. Called from the host when a control is used.
    public func invoke(callback handle: String, arguments: [Any] = []) throws -> Any {
        guard self.isStarted else {
            throw PluginRuntimeError("the plugin runtime is not started")
        }
        let data = try JSONSerialization.data(withJSONObject: arguments, options: [])
        let payload = String(data: data, encoding: .utf8) ?? "[]"
        var errorPointer: UnsafeMutablePointer<CChar>?
        let result: UnsafeMutablePointer<CChar>? = self.performOnQueue {
            extera_pl_python_invoke(handle, payload, &errorPointer)
        }
        if let errorPointer {
            let message = String(cString: errorPointer)
            extera_pl_python_free(errorPointer)
            throw PluginRuntimeError(message)
        }
        guard let result else {
            return NSNull()
        }
        let text = String(cString: result)
        extera_pl_python_free(result)
        return (try? JSONSerialization.jsonObject(with: Data(text.utf8))) ?? text
    }

    private func performOnQueue<T>(_ body: () -> T) -> T {
        if DispatchQueue.getSpecific(key: self.queueKey) != nil {
            return body()
        }
        return self.queue.sync(execute: body)
    }
}

public enum PluginHostInfo {
    public static var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
        return version ?? "13.2"
    }

    /// Version used for `__app_version__` requirements.
    ///
    /// The iOS app and exteraGram do not share version numbers. The engine
    /// advertises the exteraGram line it implements, so a plugin written for
    /// `>=13.2.1` is not rejected by a Telegram-iOS build whose marketing
    /// version happens to be lower.
    public static var compatibilityVersion: String {
        return "13.2.1"
    }

    public static var buildNumber: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
        return version ?? "0"
    }

    public static var sdkVersion: String {
        return PythonRuntime.shared.info?.sdkVersion ?? "1.4.6.5"
    }
}

/// The single C callback the runtime uses to reach Swift.
///
/// `PluginPython.c` declares it weak, so a build without the app (the host test
/// harness) links without this symbol.
@_cdecl("pl_host_call")
public func exteraPluginHostCall(_ method: UnsafePointer<CChar>?, _ payload: UnsafePointer<CChar>?) -> UnsafeMutablePointer<CChar>? {
    let methodName = method.map { String(cString: $0) } ?? ""
    let payloadText = payload.map { String(cString: $0) } ?? "{}"
    let result = PluginHostAPI.shared.handle(method: methodName, payload: payloadText)
    return strdup(result)
}

