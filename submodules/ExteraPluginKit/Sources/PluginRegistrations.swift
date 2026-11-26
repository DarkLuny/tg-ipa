import Foundation

/// File extensions claimed by plugins.
///
/// A plugin registers an extension through `FilesController`, receives a
/// callback when a user opens a file with it, and unregisters on unload. The app
/// calls `open(url:)` from its document-open path; the kit does not depend on a
/// particular Telegram screen, so the same registry serves the document picker,
/// a chat attachment and an external "Open in…" request.
public final class PluginFileHandlers: @unchecked Sendable {
    public static let shared = PluginFileHandlers()

    private struct Handler {
        var pluginId: String
        var extensionName: String
        var handle: String
        var description: String
        var icon: Any?
    }

    private let lock = NSLock()
    private var handlers: [String: Handler] = [:]

    private init() {
    }

    @discardableResult
    public func register(pluginId: String, extensionName: String, description: String, handle: String, icon: Any? = nil) -> Bool {
        let key = extensionName.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
        guard !key.isEmpty else {
            return false
        }
        self.lock.lock()
        let existing = self.handlers[key]
        self.lock.unlock()
        if let existing, existing.pluginId != pluginId {
            PluginLog.log("file extension .\(key) is already handled by \(existing.pluginId)", pluginId: pluginId, level: .warning)
            return false
        }
        self.lock.lock()
        self.handlers[key] = Handler(pluginId: pluginId, extensionName: key, handle: handle, description: description, icon: icon)
        self.lock.unlock()
        return true
    }

    public func unregister(pluginId: String, extensionName: String) {
        let key = extensionName.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
        self.lock.lock()
        if let existing = self.handlers[key], existing.pluginId == pluginId {
            self.handlers.removeValue(forKey: key)
        }
        self.lock.unlock()
    }

    public func unregisterAll(pluginId: String) {
        self.lock.lock()
        self.handlers = self.handlers.filter { $0.value.pluginId != pluginId }
        self.lock.unlock()
    }

    public var registeredExtensions: [String] {
        self.lock.lock()
        defer { self.lock.unlock() }
        return Array(self.handlers.keys)
    }

    /// Invokes the plugin that handles `url`; returns true when one did.
    @discardableResult
    public func open(url: URL) -> Bool {
        let key = url.pathExtension.lowercased()
        self.lock.lock()
        let handler = self.handlers[key]
        self.lock.unlock()
        guard let handler else {
            return false
        }
        do {
            _ = try PythonRuntime.shared.invoke(callback: handler.handle, arguments: [[
                "place": 2,
                "file": url.path,
                "file_name": url.lastPathComponent,
                "extension": key,
                "message": NSNull(),
                "activity": NSNull(),
                "parent_fragment": NSNull()
            ]])
            return true
        } catch {
            PluginLog.log("file handler for .\(key) failed: \(error)", pluginId: handler.pluginId, level: .error)
            return false
        }
    }
}

/// Before/after handlers for opened URLs and shared files.
///
/// `before` handlers can cancel the built-in handling; `after` handlers only
/// observe it. This is the iOS counterpart of Android's intent filters: the app
/// offers a URL to the registry before opening it, and again after it has been
/// handled.
public final class PluginIntentHandlers: @unchecked Sendable {
    public static let shared = PluginIntentHandlers()

    public struct Handler {
        public var id: String
        public var pluginId: String
        public var handle: String
        public var before: Bool
        public var priority: Int
        public var type: String
        public var scheme: String?
        public var host: String?
        public var path: String?
    }

    private let lock = NSLock()
    private var handlers: [String: Handler] = [:]
    private var order: [String] = []

    private init() {
    }

    public func register(id: String, pluginId: String, handle: String, before: Bool, priority: Int, type: String, scheme: String? = nil, host: String? = nil, path: String? = nil) {
        self.lock.lock()
        self.handlers[id] = Handler(id: id, pluginId: pluginId, handle: handle, before: before, priority: priority, type: type, scheme: scheme, host: host, path: path)
        self.order.removeAll { $0 == id }
        self.order.append(id)
        self.order.sort { left, right in
            let l = self.handlers[left]?.priority ?? 0
            let r = self.handlers[right]?.priority ?? 0
            return l < r
        }
        self.lock.unlock()
    }

    public func unregister(id: String) {
        self.lock.lock()
        self.handlers.removeValue(forKey: id)
        self.order.removeAll { $0 == id }
        self.lock.unlock()
    }

    public func unregisterAll(pluginId: String) {
        self.lock.lock()
        let ids = self.handlers.filter { $0.value.pluginId == pluginId }.map { $0.key }
        for id in ids {
            self.handlers.removeValue(forKey: id)
            self.order.removeAll { $0 == id }
        }
        self.lock.unlock()
    }

    /// Returns `true` when a `before` handler cancelled the built-in handling.
    public func runBefore(url: URL, extras: [String: Any] = [:]) -> Bool {
        return self.run(before: true, url: url, extras: extras)
    }

    public func runAfter(url: URL, extras: [String: Any] = [:]) {
        _ = self.run(before: false, url: url, extras: extras)
    }

    private func run(before: Bool, url: URL, extras: [String: Any]) -> Bool {
        self.lock.lock()
        let ordered = self.order.compactMap { self.handlers[$0] }.filter { $0.before == before }
        self.lock.unlock()

        let scheme = url.scheme?.lowercased()
        let host = url.host?.lowercased()
        let path = url.path

        for handler in ordered {
            if let required = handler.scheme?.lowercased(), required != scheme {
                continue
            }
            if let required = handler.host?.lowercased(), required != host {
                continue
            }
            if let required = handler.path, !required.isEmpty {
                let template = required.hasPrefix("/") ? required : "/" + required
                let candidate = path.hasPrefix("/") ? path : "/" + path
                let regex = template
                    .replacingOccurrences(of: "{", with: "([^/]+)")
                    .replacingOccurrences(of: "}", with: "")
                if (try? NSRegularExpression(pattern: "^" + regex + "$"))?.firstMatch(in: candidate, range: NSRange(location: 0, length: candidate.utf16.count)) == nil {
                    continue
                }
            }
            do {
                let value = try PythonRuntime.shared.invoke(callback: handler.handle, arguments: [[
                    "type": handler.type,
                    "url": url.absoluteString,
                    "scheme": scheme ?? "",
                    "host": host ?? "",
                    "path": path,
                    "query": url.query ?? "",
                    "action": (extras["action"] as? String) ?? "android.intent.action.VIEW",
                    "flags": (extras["flags"] as? NSNumber)?.intValue ?? 0,
                    "mime_type": (extras["type"] as? String) ?? NSNull(),
                    "categories": (extras["categories"] as? [String]) ?? [],
                    "extras": extras
                ]])
                if before, let cancelled = value as? Bool, cancelled {
                    return true
                }
            } catch {
                PluginLog.log("intent handler \(handler.id) failed: \(error)", pluginId: handler.pluginId, level: .error)
            }
        }
        return false
    }
}
