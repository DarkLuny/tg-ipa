import Foundation

public enum PluginJSON {
    public static func encodeString(_ value: Any) -> String {
        guard JSONSerialization.isValidJSONObject(value) else {
            return "null"
        }
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: []),
              let text = String(data: data, encoding: .utf8) else {
            return "null"
        }
        return text
    }

    public static func encode(_ value: Any) -> String {
        return self.encodeString(value)
    }

    public static func decode(_ text: String) -> Any? {
        guard let data = text.data(using: .utf8) else {
            return nil
        }
        return try? JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
    }

    public static func dictionary(_ text: String) -> [String: Any] {
        return (self.decode(text) as? [String: Any]) ?? [:]
    }
}

public enum PluginLogLevel: String, Sendable {
    case debug
    case info
    case warning
    case error
}

public struct PluginLogEntry: Sendable {
    public var date: Date
    public var pluginId: String
    public var level: PluginLogLevel
    public var text: String

    public init(date: Date = Date(), pluginId: String, level: PluginLogLevel, text: String) {
        self.date = date
        self.pluginId = pluginId
        self.level = level
        self.text = text
    }
}

/// Per-plugin log ring buffer, shown by the Plugins screen.
public enum PluginLog {
    public static let didChange = Notification.Name("ExteraPluginKit.PluginLogDidChange")

    private static let lock = NSLock()
    private static var entries: [PluginLogEntry] = []
    private static let limit = 2000

    public static func log(_ text: String, pluginId: String = "", level: PluginLogLevel = .info) {
        let trimmed = text.count > 8000 ? String(text.prefix(8000)) + "..." : text
        let entry = PluginLogEntry(pluginId: pluginId, level: level, text: trimmed)
        lock.lock()
        entries.append(entry)
        if entries.count > limit {
            entries.removeFirst(entries.count - limit)
        }
        lock.unlock()

        #if DEBUG
        NSLog("[extera-plugins][%@][%@] %@", pluginId, level.rawValue, trimmed)
        #endif
        DispatchQueue.main.async {
            NotificationCenter.default.post(name: didChange, object: nil)
        }
    }

    public static func all() -> [PluginLogEntry] {
        lock.lock()
        defer { lock.unlock() }
        return entries
    }

    public static func forPlugin(_ pluginId: String) -> [PluginLogEntry] {
        return self.all().filter { $0.pluginId == pluginId }
    }

    public static func text(forPlugin pluginId: String) -> String {
        return self.forPlugin(pluginId).map { entry in
            "[\(Self.formatter.string(from: entry.date))] [\(entry.level.rawValue)] \(entry.text)"
        }.joined(separator: "\n")
    }

    public static func clear() {
        lock.lock()
        entries.removeAll()
        lock.unlock()
        DispatchQueue.main.async {
            NotificationCenter.default.post(name: didChange, object: nil)
        }
    }

    private static let formatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()
}
