import Foundation

/// One installed plugin.
public final class Plugin: @unchecked Sendable {
    public let manifest: PluginManifest
    public let path: URL
    public let index: Int
    public let engine: String

    public private(set) var isEnabled: Bool
    public private(set) var isLoaded: Bool = false
    public private(set) var error: String?
    public private(set) var isNotResponding: Bool = false
    public private(set) var settings: [PluginSettingControl] = []

    public var id: String { self.manifest.id }
    public var name: String { self.manifest.name }
    public var isElyx: Bool { self.engine == "elyx-py" }

    public init(manifest: PluginManifest, path: URL, index: Int, isEnabled: Bool, engine: String = "python") {
        self.manifest = manifest
        self.path = path
        self.index = index
        self.isEnabled = isEnabled
        self.engine = engine
    }

    public func update(isEnabled: Bool? = nil, isLoaded: Bool? = nil, error: String? = nil, isNotResponding: Bool? = nil, clearError: Bool = false) {
        if clearError {
            self.error = nil
        }
        if let isEnabled {
            self.isEnabled = isEnabled && self.error == nil
        }
        if let isLoaded {
            self.isLoaded = isLoaded
        }
        if let error {
            self.error = error
            self.isEnabled = false
        }
        if let isNotResponding {
            self.isNotResponding = isNotResponding
        }
    }

    public func update(settings: [PluginSettingControl]) {
        self.settings = settings
    }

    public func markEnabled(_ enabled: Bool) {
        self.isEnabled = enabled && self.error == nil
    }
}

public struct PluginLoadState: Sendable {
    public var enabled: [String: Bool]
    public var crashed: String?

    public init(enabled: [String: Bool], crashed: String?) {
        self.enabled = enabled
        self.crashed = crashed
    }
}

public enum PluginStoreError: Error, CustomStringConvertible {
    case cannotCreateDirectory(String)
    case missingSDK
    case invalidPlugin(String)

    public var description: String {
        switch self {
        case let .cannotCreateDirectory(path):
            return "could not create \(path)"
        case .missingSDK:
            return "the plugins SDK is missing from the app bundle"
        case let .invalidPlugin(message):
            return message
        }
    }
}

/// Files, enable states and the SDK copy.
///
/// Layout under Application Support/ExteraPlugins:
///
///     plugins/<id>.plugin           installed plugins
///     plugins-sdk/                  the Python SDK (copied from the bundle)
///     plugins/plugin_settings.json  values written by plugin_settings.py
///     plugins/.deps/<id>/           packages installed for a plugin
///
public final class PluginStore: @unchecked Sendable {
    public static let shared = PluginStore()

    private let fileManager = FileManager.default
    private let lock = NSLock()
    private let defaults = UserDefaults.standard

    public private(set) var rootURL: URL!
    public private(set) var pluginsURL: URL!
    public private(set) var sdkURL: URL!
    public private(set) var filesURL: URL!

    private let enabledPrefix = "extera.plugins.enabled."
    private let crashKey = "extera.plugins.crashed"
    private let pinnedKey = "extera.plugins.pinned"

    private init() {
        let base = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? fileManager.temporaryDirectory
        self.configure(root: base.appendingPathComponent("ExteraPlugins", isDirectory: true))
    }

    private func configure(root: URL) {
        self.rootURL = root
        self.pluginsURL = root.appendingPathComponent("plugins", isDirectory: true)
        self.sdkURL = root.appendingPathComponent("plugins-sdk", isDirectory: true)
        self.filesURL = root.appendingPathComponent("files", isDirectory: true)
    }

    /// Points the store at another directory. Used by tests and the simulator.
    public func use(root: URL) {
        self.lock.lock()
        defer { self.lock.unlock() }
        self.configure(root: root)
    }

    public func prepare() throws {
        let depsURL = self.pluginsURL.appendingPathComponent(".deps", isDirectory: true)
        for url in [self.rootURL, self.pluginsURL, self.filesURL, depsURL] {
            do {
                try self.fileManager.createDirectory(at: url!, withIntermediateDirectories: true, attributes: nil)
            } catch {
                throw PluginStoreError.cannotCreateDirectory(url?.path ?? "")
            }
        }
    }

    /// Installs the Python SDK from a directory shipped in the app bundle.
    ///
    /// The copy is keyed by the SDK version: an app update replaces the SDK,
    /// and a runtime installed by an OTA update (the Android behaviour) is left
    /// alone unless the bundled one is newer.
    public func installSDK(from source: URL, force: Bool = false) throws {
        guard self.fileManager.fileExists(atPath: source.path) else {
            throw PluginStoreError.missingSDK
        }
        guard let resolvedSource = Self.isSDKDirectory(source) ? source : Self.findSDKRoot(under: source) else {
            throw PluginStoreError.missingSDK
        }
        let marker = self.sdkURL.appendingPathComponent("v.txt")
        let bundledVersion = (try? String(contentsOf: resolvedSource.appendingPathComponent("v.txt"), encoding: .utf8)) ?? "0"
        let installedVersion = (try? String(contentsOf: marker, encoding: .utf8)) ?? ""
        if !force, installedVersion == bundledVersion, self.fileManager.fileExists(atPath: self.sdkURL.path) {
            return
        }
        let staging = self.rootURL.appendingPathComponent("plugins-sdk.tmp", isDirectory: true)
        try? self.fileManager.removeItem(at: staging)
        try self.fileManager.copyItem(at: resolvedSource, to: staging)
        try? self.fileManager.removeItem(at: self.sdkURL)
        try self.fileManager.moveItem(at: staging, to: self.sdkURL)
        try bundledVersion.write(to: marker, atomically: true, encoding: .utf8)
    }

    private static func isSDKDirectory(_ url: URL) -> Bool {
        return FileManager.default.fileExists(atPath: url.appendingPathComponent("_extera_runtime.py").path)
    }

    /// Finds the SDK root when the resources were packaged with an extra path
    /// prefix (for example `third-party/python-ios/PythonSupport/sdk`).
    private static func findSDKRoot(under root: URL, depth: Int = 5) -> URL? {
        if Self.isSDKDirectory(root) {
            return root
        }
        guard depth > 0 else {
            return nil
        }
        let children = (try? FileManager.default.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )) ?? []
        for child in children {
            guard (try? child.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true else {
                continue
            }
            if let found = Self.findSDKRoot(under: child, depth: depth - 1) {
                return found
            }
        }
        return nil
    }

    private static func isStdlibDirectory(_ url: URL) -> Bool {
        return FileManager.default.fileExists(atPath: url.appendingPathComponent("encodings/__init__.py").path)
    }

    private static func findStdlibRoot(under root: URL, depth: Int = 6) -> URL? {
        if root.lastPathComponent == "python3.11", Self.isStdlibDirectory(root) {
            return root
        }
        guard depth > 0 else {
            return nil
        }
        let children = (try? FileManager.default.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )) ?? []
        for child in children {
            guard (try? child.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true else {
                continue
            }
            if child.lastPathComponent == "python3.11", Self.isStdlibDirectory(child) {
                return child
            }
            if let found = Self.findStdlibRoot(under: child, depth: depth - 1) {
                return found
            }
        }
        return nil
    }

    /// The SDK directory inside the app bundle, if the build ships one.
    public static func bundledSDKDirectory() -> URL? {
        let bundleCandidates: [URL?] = [
            Bundle.main.bundleURL.appendingPathComponent("ExteraPlugins.bundle", isDirectory: true),
            Bundle.main.resourceURL?.appendingPathComponent("ExteraPlugins.bundle", isDirectory: true),
            Bundle.main.bundleURL.appendingPathComponent("Frameworks/ExteraPlugins.bundle", isDirectory: true)
        ]
        var candidates: [URL?] = []
        for bundleURL in bundleCandidates {
            guard let bundleURL, let bundle = Bundle(url: bundleURL) else { continue }
            candidates.append(bundleURL)
            candidates.append(bundleURL.appendingPathComponent("PythonSupport/sdk", isDirectory: true))
            candidates.append(bundleURL.appendingPathComponent("sdk", isDirectory: true))
            if let resourcePath = bundle.resourcePath {
                candidates.append(URL(fileURLWithPath: resourcePath).appendingPathComponent("PythonSupport/sdk", isDirectory: true))
                candidates.append(URL(fileURLWithPath: resourcePath).appendingPathComponent("sdk", isDirectory: true))
            }
        }
        candidates.append(Bundle.main.resourceURL?.appendingPathComponent("ExteraPlugins/sdk", isDirectory: true))
        candidates.append(Bundle.main.bundleURL.appendingPathComponent("ExteraPlugins/sdk", isDirectory: true))
        candidates.append(Bundle.main.resourceURL?.appendingPathComponent("plugins-sdk", isDirectory: true))
        if let bundle = Bundle(identifier: "org.telegram.ExteraPlugins") {
            candidates.append(bundle.bundleURL)
            candidates.append(bundle.bundleURL.appendingPathComponent("PythonSupport/sdk", isDirectory: true))
            candidates.append(bundle.bundleURL.appendingPathComponent("sdk", isDirectory: true))
        }
        for candidate in candidates {
            guard let candidate else { continue }
            var isDirectory: ObjCBool = false
            if FileManager.default.fileExists(atPath: candidate.path, isDirectory: &isDirectory), isDirectory.boolValue, Self.isSDKDirectory(candidate) {
                return candidate
            }
        }
        for root in [Bundle.main.resourceURL, Bundle.main.bundleURL] {
            guard let root else { continue }
            if let found = Self.findSDKRoot(under: root) {
                return found
            }
        }
        return nil
    }
    /// The Python standard library shipped by `//third-party/python-ios`.
    public static func bundledStdlibDirectory() -> URL? {
        #if targetEnvironment(simulator)
        let candidates: [URL?] = [
            Bundle.main.resourceURL?.appendingPathComponent("stdlib-simulator/python3.11", isDirectory: true),
            Bundle.main.resourceURL?.appendingPathComponent("PythonStdlibSimulator/python3.11", isDirectory: true),
            Bundle.main.resourceURL?.appendingPathComponent("stdlib/python3.11", isDirectory: true)
        ]
        #else
        let candidates: [URL?] = [
            Bundle.main.resourceURL?.appendingPathComponent("stdlib/python3.11", isDirectory: true),
            Bundle.main.resourceURL?.appendingPathComponent("PythonStdlib/python3.11", isDirectory: true),
            Bundle.main.resourceURL?.appendingPathComponent("python3.11", isDirectory: true),
            Bundle.main.bundleURL.appendingPathComponent("PythonStdlib/python3.11", isDirectory: true)
        ]
        #endif
        for candidate in candidates {
            guard let candidate else { continue }
            var isDirectory: ObjCBool = false
            if FileManager.default.fileExists(atPath: candidate.path, isDirectory: &isDirectory), isDirectory.boolValue, Self.isStdlibDirectory(candidate) {
                return candidate
            }
        }
        for root in [Bundle.main.resourceURL, Bundle.main.bundleURL] {
            guard let root else { continue }
            if let found = Self.findStdlibRoot(under: root) {
                return found
            }
        }
        return nil
    }

    // -- Listing -------------------------------------------------------------

    public func installedPluginURLs() -> [URL] {
        let contents = (try? self.fileManager.contentsOfDirectory(
            at: self.pluginsURL,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        )) ?? []
        return contents
            .filter { $0.pathExtension.lowercased() == "plugin" }
            .sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    }

    public func loadInstalled() -> [Plugin] {
        var result: [Plugin] = []
        for (index, url) in self.installedPluginURLs().enumerated() {
            do {
                let manifest = try PluginManifestParser.parse(fileAt: url)
                let enabled = self.defaults.object(forKey: self.enabledPrefix + manifest.id) as? Bool ?? true
                result.append(Plugin(manifest: manifest, path: url, index: index, isEnabled: enabled))
            } catch {
                // Android keeps a broken plugin in the list, disabled and with
                // the parse error, so the user can read the reason and delete it.
                let fallbackId = url.deletingPathExtension().lastPathComponent
                let manifest = PluginManifest(id: fallbackId, name: fallbackId)
                let plugin = Plugin(manifest: manifest, path: url, index: index, isEnabled: false)
                plugin.update(error: "\(error)")
                plugin.markEnabled(false)
                PluginLog.log("Invalid plugin \(url.lastPathComponent): \(error)", level: .warning)
                result.append(plugin)
            }
        }
        return result
    }

    public func isEnabled(_ id: String) -> Bool {
        return self.defaults.object(forKey: self.enabledPrefix + id) as? Bool ?? true
    }

    public func setEnabled(_ enabled: Bool, for id: String) {
        self.defaults.set(enabled, forKey: self.enabledPrefix + id)
    }

    public func clearEnabled(for id: String) {
        self.defaults.removeObject(forKey: self.enabledPrefix + id)
    }

    public var pinnedPluginIds: [String] {
        return self.defaults.stringArray(forKey: self.pinnedKey) ?? []
    }

    public func isPinned(_ id: String) -> Bool {
        return self.pinnedPluginIds.contains(id)
    }

    public func setPinned(_ pinned: Bool, for id: String) {
        var ids = self.pinnedPluginIds
        if pinned {
            if !ids.contains(id) {
                ids.append(id)
            }
        } else {
            ids.removeAll { $0 == id }
        }
        self.defaults.set(ids, forKey: self.pinnedKey)
    }

    public var crashedPluginId: String? {
        get { return self.defaults.string(forKey: self.crashKey) }
        set {
            if let newValue {
                self.defaults.set(newValue, forKey: self.crashKey)
            } else {
                self.defaults.removeObject(forKey: self.crashKey)
            }
        }
    }

    // -- Mutations -----------------------------------------------------------

    /// Copies a `.plugin` file into the store, replacing a previous version.
    /// Returns the plugin id and whether an older copy was replaced.
    @discardableResult
    public func install(fileAt url: URL) throws -> (manifest: PluginManifest, replaced: Bool) {
        let manifest = try PluginManifestParser.parse(fileAt: url)
        // A plugin id is also a Python module name (`extera_plugin_<id>` and
        // the source is importable as `<id>`); an SDK module of the same name
        // must not be shadowed.
        if self.topLevelModuleNames(in: self.sdkURL).contains(manifest.id) {
            throw PluginStoreError.invalidPlugin(
                "plugin __id__ \"\(manifest.id)\" is already used as a Python module name by the plugins SDK"
            )
        }
        let destination = self.pluginsURL.appendingPathComponent(manifest.id + ".plugin")
        let replaced = self.fileManager.fileExists(atPath: destination.path)
        if replaced {
            let backup = self.rootURL.appendingPathComponent("backup-" + manifest.id + ".plugin")
            try? self.fileManager.removeItem(at: backup)
            try? self.fileManager.copyItem(at: destination, to: backup)
        }
        try? self.fileManager.removeItem(at: destination)
        try self.fileManager.copyItem(at: url, to: destination)
        if !replaced {
            self.defaults.set(true, forKey: self.enabledPrefix + manifest.id)
        }
        return (manifest, replaced)
    }

    public func delete(id: String) throws {
        let url = self.pluginsURL.appendingPathComponent(id + ".plugin")
        try? self.fileManager.removeItem(at: url)
        self.defaults.removeObject(forKey: self.enabledPrefix + id)
        let dependencies = self.pluginsURL.appendingPathComponent(".deps/" + id, isDirectory: true)
        try? self.fileManager.removeItem(at: dependencies)
    }

    public func pluginURL(id: String) -> URL {
        return self.pluginsURL.appendingPathComponent(id + ".plugin")
    }

    public func elyxPluginURL(id: String) -> URL {
        return self.pluginsURL
            .appendingPathComponent("ElyxPlugins", isDirectory: true)
            .appendingPathComponent(id, isDirectory: true)
    }

    /// Top-level importable names in a directory: the same rule the Android
    /// engine uses to decide whether a plugin id shadows a module.
    public func topLevelModuleNames(in directory: URL) -> Set<String> {
        guard let contents = try? self.fileManager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }
        var names = Set<String>()
        for url in contents {
            let name = url.lastPathComponent
            let isDirectory = (try? url.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory ?? false
            if isDirectory {
                if name == "__pycache__" || name.hasSuffix(".dist-info") || name.hasSuffix(".data") {
                    continue
                }
                names.insert(name)
            } else if name.hasSuffix(".py") || name.hasSuffix(".pyc") || name.hasSuffix(".so") {
                if let stem = name.split(separator: ".").first {
                    names.insert(String(stem))
                }
            }
        }
        return names
    }

    public func settingsFileURL() -> URL {
        return self.pluginsURL.appendingPathComponent("plugin_settings.json")
    }

    // -- Hashing -------------------------------------------------------------

    public func sha256(of url: URL) -> String? {
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }
        return PluginHashing.sha256(data)
    }
}
