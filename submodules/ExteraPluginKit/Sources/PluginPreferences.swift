import Foundation

/// The switches of the "Plugins engine" screen, the iOS counterpart of
/// Android's `pluginsEngine`, `pluginsSafeMode`, `pluginsDevMode`,
/// `pluginsStaticAnalysis` and `pluginsCompactView` preferences.
///
/// Values live in `UserDefaults` so they survive a relaunch exactly like the
/// Android flags do. The engine is considered active only when it is turned on
/// and safe mode is off.
public final class PluginPreferences {
    public static let shared = PluginPreferences()

    private enum Key {
        static let engine = "extera.plugins.engine.enabled"
        static let safeMode = "extera.plugins.safe_mode"
        static let developerMode = "extera.plugins.developer_mode"
        static let staticAnalysis = "extera.plugins.static_analysis"
        static let compactView = "extera.plugins.compact_view"
        static let unknownSources = "extera.plugins.unknown_sources"
    }

    private let defaults = UserDefaults.standard

    private init() {
    }

    private func bool(_ key: String, default defaultValue: Bool) -> Bool {
        return self.defaults.object(forKey: key) as? Bool ?? defaultValue
    }

    private func setBool(_ value: Bool, forKey key: String) {
        self.defaults.set(value, forKey: key)
    }

    /// The master switch. When it is off no plugin code runs; the installed
    /// list and its settings are left untouched.
    public var engineEnabled: Bool {
        get { return self.bool(Key.engine, default: true) }
        set { self.setBool(newValue, forKey: Key.engine) }
    }

    /// Safe mode skips plugin loading for the whole app session even while the
    /// engine switch is on, which is what Android does after a crash.
    public var safeMode: Bool {
        get { return self.bool(Key.safeMode, default: false) }
        set { self.setBool(newValue, forKey: Key.safeMode) }
    }

    /// Runs the Python development server and lowers the log level to debug.
    public var developerMode: Bool {
        get { return self.bool(Key.developerMode, default: false) }
        set { self.setBool(newValue, forKey: Key.developerMode) }
    }

    /// Runs the local static analyzer before a plugin is installed.
    public var staticAnalysis: Bool {
        get { return self.bool(Key.staticAnalysis, default: true) }
        set { self.setBool(newValue, forKey: Key.staticAnalysis) }
    }

    /// Single-line plugin rows without descriptions or error text.
    public var compactView: Bool {
        get { return self.bool(Key.compactView, default: false) }
        set { self.setBool(newValue, forKey: Key.compactView) }
    }

    /// Android's `pluginsUnknownSources`: when off, a plugin that does not come
    /// from a trusted catalog is refused before it is installed.
    public var allowUnknownSources: Bool {
        get { return self.bool(Key.unknownSources, default: false) }
        set { self.setBool(newValue, forKey: Key.unknownSources) }
    }

    /// True when plugin code may be loaded.
    public var isEngineActive: Bool {
        return self.engineEnabled && !self.safeMode
    }
}
