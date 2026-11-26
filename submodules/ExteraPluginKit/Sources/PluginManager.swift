import Foundation
import UIKit

// The plugin callbacks use `Result<_, String>` to surface host errors. String
// does not conform to Error in the standard library; opt in once here so the
// existing plugin-facing API stays source-compatible.
extension String: @retroactive Error {}

public struct PluginEntity: Sendable {
    public var type: String
    public var offset: Int
    public var length: Int
    public var url: String?
    public var language: String?

    public init(type: String, offset: Int, length: Int, url: String? = nil, language: String? = nil) {
        self.type = type
        self.offset = offset
        self.length = length
        self.url = url
        self.language = language
    }

    public init?(json: [String: Any]) {
        guard let type = json["type"] as? String else {
            return nil
        }
        self.type = type
        self.offset = (json["offset"] as? NSNumber)?.intValue ?? 0
        self.length = (json["length"] as? NSNumber)?.intValue ?? 0
        self.url = json["url"] as? String
        self.language = json["language"] as? String
    }

    public var dictionary: [String: Any] {
        var value: [String: Any] = [
            "type": self.type,
            "offset": self.offset,
            "length": self.length
        ]
        if let url = self.url { value["url"] = url }
        if let language = self.language { value["language"] = language }
        return value
    }
}

public struct PluginSendRequest: Sendable {
    public var accountId: Int64
    public var peerId: Int64
    public var kind: String
    public var text: String?
    public var caption: String?
    public var entities: [PluginEntity]
    public var path: String?
    public var replyTo: Int32?
    public var silent: Bool
    public var scheduleDate: Int32
    public var replyMarkupJSON: String?

    public init(accountId: Int64, peerId: Int64, kind: String, text: String?, caption: String?, entities: [PluginEntity], path: String?, replyTo: Int32?, silent: Bool, scheduleDate: Int32, replyMarkupJSON: String? = nil) {
        self.accountId = accountId
        self.peerId = peerId
        self.kind = kind
        self.text = text
        self.caption = caption
        self.entities = entities
        self.path = path
        self.replyTo = replyTo
        self.silent = silent
        self.scheduleDate = scheduleDate
        self.replyMarkupJSON = replyMarkupJSON
    }
}

/// The app-side operations a plugin may call.
///
/// The kit is deliberately free of a TelegramCore dependency: the app installs
/// an environment at launch, and a build that has not done so reports a clear
/// error to the plugin instead of failing to link.
public struct PluginEnvironment {
    public var currentAccountId: () -> Int64
    public var accountIds: () -> [Int64]
    public var send: (PluginSendRequest) -> Result<Int32, String>
    public var request: (Int64, String, [String: Any]) -> [String: Any]
    public var peer: (Int64, Int64) -> [String: Any]?
    public var chats: (Int64, Int, Int) -> [[String: Any]]
    public var contacts: (Int64) -> [[String: Any]]
    public var me: (Int64) -> [String: Any]?
    public var deleteMessages: (Int64, Int64, [Int32], Bool) -> Bool
    public var editMessage: (Int64, Int64, Int32, String?, [[String: Any]]) -> Result<Void, String>
    public var copyToClipboard: (String) -> Void
    public var readClipboard: () -> String
    public var openURL: (String, Bool) -> Void
    public var presentController: ([String: Any]) -> Void
    public var pickFile: ([String], Bool) -> [String]
    public var httpRequest: (String, String, [String: String], String?, Double) -> [String: Any]
    public var openPluginSettings: (String, String?) -> Void

    public init(
        currentAccountId: @escaping () -> Int64 = { 0 },
        accountIds: @escaping () -> [Int64] = { [] },
        send: @escaping (PluginSendRequest) -> Result<Int32, String> = { _ in .failure("sending is not configured") },
        request: @escaping (Int64, String, [String: Any]) -> [String: Any] = { _, _, _ in ["error": "requests are not configured"] },
        peer: @escaping (Int64, Int64) -> [String: Any]? = { _, _ in nil },
        chats: @escaping (Int64, Int, Int) -> [[String: Any]] = { _, _, _ in [] },
        contacts: @escaping (Int64) -> [[String: Any]] = { _ in [] },
        me: @escaping (Int64) -> [String: Any]? = { _ in nil },
        deleteMessages: @escaping (Int64, Int64, [Int32], Bool) -> Bool = { _, _, _, _ in false },
        editMessage: @escaping (Int64, Int64, Int32, String?, [[String: Any]]) -> Result<Void, String> = { _, _, _, _, _ in .failure("editing messages is not configured") },
        copyToClipboard: @escaping (String) -> Void = { UIPasteboard.general.string = $0 },
        readClipboard: @escaping () -> String = { UIPasteboard.general.string ?? "" },
        openURL: @escaping (String, Bool) -> Void = { _, _ in },
        presentController: @escaping ([String: Any]) -> Void = { _ in },
        pickFile: @escaping ([String], Bool) -> [String] = { _, _ in [] },
        httpRequest: @escaping (String, String, [String: String], String?, Double) -> [String: Any] = { _, _, _, _, _ in ["error": "network access is not configured"] },
        openPluginSettings: @escaping (String, String?) -> Void = { _, _ in }
    ) {
        self.currentAccountId = currentAccountId
        self.accountIds = accountIds
        self.send = send
        self.request = request
        self.peer = peer
        self.chats = chats
        self.contacts = contacts
        self.me = me
        self.deleteMessages = deleteMessages
        self.editMessage = editMessage
        self.copyToClipboard = copyToClipboard
        self.readClipboard = readClipboard
        self.openURL = openURL
        self.presentController = presentController
        self.pickFile = pickFile
        self.httpRequest = httpRequest
        self.openPluginSettings = openPluginSettings
    }
}

public enum PluginManagerError: Error, CustomStringConvertible {
    case runtimeUnavailable(String)
    case pluginNotLoaded(String)
    case notConfigured(String)

    public var description: String {
        switch self {
        case let .runtimeUnavailable(message): return message
        case let .pluginNotLoaded(id): return "plugin \(id) is not loaded"
        case let .notConfigured(what): return "\(what) is not configured in this build"
        }
    }
}

public struct PluginChatContext {
    public var accountId: Int64
    public var dialogId: Int64
    public var topicId: Int64

    public init(accountId: Int64, dialogId: Int64, topicId: Int64) {
        self.accountId = accountId
        self.dialogId = dialogId
        self.topicId = topicId
    }
}

/// Owns installed plugins, their runtime instances and their hooks.
public final class PluginManager: @unchecked Sendable {
    public static let shared = PluginManager()

    public static let didChange = Notification.Name("ExteraPluginKit.PluginsDidChange")

    private let store = PluginStore.shared
    private let hooks = PluginHooks.shared
    private let queue = DispatchQueue(label: "com.exteragram.plugins.manager", qos: .userInitiated)
    private let lock = NSLock()

    public private(set) var startError: String?
    private var installed: [Plugin] = []
    private var started = false
    private var starting = false
    private var notifyingPluginsUpdated = false
    /// Android's `PluginsWatchdog`: every plugin execution gets a five-second
    /// budget, and a plugin that is still inside one is shown as not responding.
    private var executionCounts: [String: Int] = [:]
    private var executionTimers: [String: DispatchWorkItem] = [:]
    private let chatLock = NSLock()
    private var _currentChat: PluginChatContext?

    public var environment = PluginEnvironment()
    public var sdkDirectoryOverride: URL?

    private init() {
    }

    // -- Current chat --------------------------------------------------------

    /// Records the chat that is currently on screen so `get_last_fragment`
    /// and `ChatActivity.getDialogId()` can answer like Android's fragment.
    public func setCurrentChat(_ chat: PluginChatContext?) {
        self.chatLock.lock()
        self._currentChat = chat
        self.chatLock.unlock()
    }

    public func currentChat() -> PluginChatContext? {
        self.chatLock.lock()
        defer { self.chatLock.unlock() }
        return self._currentChat
    }

    // -- State ---------------------------------------------------------------

    public var plugins: [Plugin] {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.installed
    }

    public func plugin(id: String) -> Plugin? {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.installed.first { $0.id == id }
    }

    public var isRunning: Bool {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.started
    }

    public var storeURL: URL {
        return self.store.pluginsURL
    }

    public var sdkURL: URL {
        return self.store.sdkURL
    }

    // -- Lifecycle -----------------------------------------------------------

    /// Loads the installed list and starts the runtime. Safe to call once at launch.
    public func start(completion: (() -> Void)? = nil) {
        self.lock.lock()
        if self.started || self.starting {
            self.lock.unlock()
            completion?()
            return
        }
        self.starting = true
        self.lock.unlock()

        if PluginHostAPI.shared.uiHost == nil {
            PluginHostAPI.shared.uiHost = PluginOverlayHost.shared
        }

        self.queue.async {
            do {
                try self.store.prepare()
                if let sdkSource = self.sdkDirectoryOverride ?? PluginStore.bundledSDKDirectory() {
                    try self.store.installSDK(from: sdkSource)
                }

                let installed = self.store.loadInstalled()
                self.lock.lock()
                self.installed = installed
                self.lock.unlock()

                // A marker written before loading a plugin tells the next launch
                // which plugin crashed the app.
                if let crashed = self.store.crashedPluginId {
                    self.store.crashedPluginId = nil
                    if let plugin = self.plugin(id: crashed) {
                        plugin.update(error: "the app crashed while loading this plugin")
                        self.store.setEnabled(false, for: crashed)
                    }
                }

                // The engine switch and safe mode both stop plugin code from
                // running; the installed list stays available so the user can
                // turn the engine back on or delete a plugin.
                guard PluginPreferences.shared.isEngineActive else {
                    self.started = true
                    self.starting = false
                    self.startError = nil
                    self.notifyChanged()
                    DispatchQueue.main.async {
                        completion?()
                    }
                    return
                }

                _ = try PythonRuntime.shared.start(
                    sdkPath: self.store.sdkURL,
                    pluginsPath: self.store.pluginsURL,
                    filesPath: self.store.filesURL,
                    stdlibPath: PluginStore.bundledStdlibDirectory()
                )

                // Elyx plugins live in `plugins/ElyxPlugins`; the Python engine
                // owns their archives, settings and hooks. They are merged into
                // the same list so one screen manages both engines.
                self.loadElyxPlugins()

                // Settings of deleted plugins must not survive a reinstall.
                // `self.plugins` now includes the Elyx plugins, so their
                // settings are kept as well.
                _ = try? PythonRuntime.shared.call(
                    "prune_plugin_settings",
                    [PluginJSON.encodeString(self.plugins.map { $0.id })]
                )

                for plugin in self.plugins where plugin.isEnabled {
                    if !plugin.isElyx {
                        self.load(plugin)
                    }
                }
                self.started = true
                self.starting = false
                self.startError = nil
                self.executeAppEvent("app_start")
                self.notifyChanged()
                DispatchQueue.main.async {
                    completion?()
                }
            } catch {
                self.lock.lock()
                self.starting = false
                self.started = false
                self.startError = "\(error)"
                self.lock.unlock()
                PluginLog.log("plugins did not start: \(error)", level: .error)
                DispatchQueue.main.async {
                    completion?()
                }
            }
        }
    }

    public func stop() {
        self.executeAppEvent("app_stop")
        PythonRuntime.shared.stop()
        PluginHostAPI.shared.releaseNativeObjects()
        self.hooks.reset()
        self.lock.lock()
        self.started = false
        self.installed = []
        self.lock.unlock()
        self.notifyChanged()
    }

    /// Restarts the runtime and reloads every plugin, used by the Elyx
    /// development server after it applies a change on disk.
    public func reloadAll(completion: (() -> Void)? = nil) {
        self.applyPreferences(completion: completion)
    }

    /// Restores the SDK that ships in the app bundle, the iOS counterpart of
    /// Android's "Restore SDK from APK": it replaces a broken or modified
    /// `plugins-sdk` copy and restarts the engine.
    public func restoreBundledSDK(completion: @escaping (Bool, String?) -> Void) {
        self.queue.async {
            guard let source = self.sdkDirectoryOverride ?? PluginStore.bundledSDKDirectory() else {
                DispatchQueue.main.async {
                    completion(false, "the app bundle does not contain the plugins SDK")
                }
                return
            }
            do {
                try self.store.installSDK(from: source, force: true)
            } catch {
                DispatchQueue.main.async {
                    completion(false, "\(error)")
                }
                return
            }
            self.stop()
            self.start {
                DispatchQueue.main.async {
                    completion(true, nil)
                }
            }
        }
    }

    /// Applies a change to `PluginPreferences`: stops the runtime and starts it
    /// again so the engine switch and safe mode take effect immediately, the
    /// way Android restarts its engine from the plugins settings screen.
    public func applyPreferences(completion: (() -> Void)? = nil) {
        self.lock.lock()
        let wasStarted = self.started
        self.lock.unlock()
        if !wasStarted {
            self.start {
                self.postPluginNotification("pluginsPySdkInfoChanged")
                completion?()
            }
            return
        }
        self.queue.async {
            self.stop()
            self.start {
                self.postPluginNotification("pluginsPySdkInfoChanged")
                completion?()
            }
        }
    }

    private func load(_ plugin: Plugin) {
        guard plugin.isEnabled else {
            return
        }
        if plugin.isElyx {
            let value = try? PythonRuntime.shared.call("elyx_load", [plugin.id])
            let object = value as? [String: Any] ?? [:]
            if (object["ok"] as? Bool) == true {
                plugin.update(isLoaded: true, clearError: true)
                plugin.markEnabled(true)
                self.loadSettings(plugin)
            } else {
                plugin.update(isLoaded: false, error: (object["error"] as? String) ?? "the Elyx plugin did not load")
            }
            return
        }
        self.store.crashedPluginId = plugin.id
        do {
            let value = try PythonRuntime.shared.call("load_plugin", [plugin.id, plugin.path.path, ""])
            let object = value as? [String: Any] ?? [:]
            if (object["ok"] as? Bool) == true {
                plugin.update(isLoaded: true, clearError: true)
                plugin.update(isNotResponding: false)
                self.store.crashedPluginId = nil
                self.loadSettings(plugin)
            } else {
                let message = (object["error"] as? String) ?? "the plugin did not load"
                plugin.update(isLoaded: false, error: message)
                self.store.crashedPluginId = nil
                PluginLog.log(message, pluginId: plugin.id, level: .error)
            }
        } catch {
            plugin.update(isLoaded: false, error: "\(error)")
            self.store.crashedPluginId = nil
            PluginLog.log("\(error)", pluginId: plugin.id, level: .error)
        }
    }

    private func loadSettings(_ plugin: Plugin) {
        do {
            let method = plugin.isElyx ? "elyx_settings" : "load_settings"
            let value = try PythonRuntime.shared.call(method, [plugin.id])
            let screen = PluginSettingsScreen(json: value)
            plugin.update(settings: screen.controls)
            if let error = screen.error {
                PluginLog.log("settings: \(error)", pluginId: plugin.id, level: .warning)
            }
            self.postPluginNotification("pluginSettingsRegistered", arguments: [plugin.id])
        } catch {
            PluginLog.log("settings: \(error)", pluginId: plugin.id, level: .warning)
        }
    }

    /// Delivers an Android-style `NotificationCenter` event to plugin observers.
    /// Android posts `pluginSettingsRegistered`, `pluginIsNotResponding`,
    /// `pluginCatalogUpdated` and `pluginsPySdkInfoChanged` from its controllers;
    /// on iOS those controllers are Swift, so the same names enter the Python bus
    /// from here.
    private func postPluginNotification(_ name: String, arguments: [Any] = []) {
        guard PythonRuntime.shared.isStarted else {
            return
        }
        self.queue.async {
            _ = try? PythonRuntime.shared.call("notify_plugin_event", [name] + arguments)
        }
    }

    /// Loads the Elyx engine's plugin list and merges it into `installed`.
    private func loadElyxPlugins() {
        guard let value = try? PythonRuntime.shared.call("elyx_setup", []) else {
            return
        }
        let object = value as? [String: Any] ?? [:]
        let list = object["plugins"] as? [[String: Any]] ?? []
        var elyx: [Plugin] = []
        for item in list {
            guard let id = item["id"] as? String, !id.isEmpty,
                  let name = item["name"] as? String, !name.isEmpty else {
                continue
            }
            let requirements = (item["requirements"] as? [Any])?.compactMap { $0 as? String } ?? []
            let icon = (item["icon"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            let appVersion = (item["app_version"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            let sdkVersion = (item["sdk_version"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            let manifest = PluginManifest(
                id: id,
                name: name,
                description: (item["description"] as? String) ?? "",
                author: (item["author"] as? String) ?? "",
                version: (item["version"] as? String) ?? "1.0",
                icon: icon,
                appVersionRequirement: appVersion,
                sdkVersionRequirement: sdkVersion,
                requirements: requirements
            )
            let enabled = (item["enabled"] as? Bool) ?? false
            let plugin = Plugin(
                manifest: manifest,
                path: self.store.elyxPluginURL(id: id),
                index: self.plugins.count + elyx.count,
                isEnabled: enabled,
                engine: "elyx-py"
            )
            if let error = item["error"] as? String, !error.isEmpty {
                plugin.update(error: error)
            } else if enabled {
                plugin.update(isLoaded: true)
            }
            elyx.append(plugin)
        }
        self.lock.lock()
        self.installed.removeAll { $0.isElyx }
        self.installed.append(contentsOf: elyx)
        self.lock.unlock()
    }

    // -- Mutations -----------------------------------------------------------

    public func setEnabled(_ enabled: Bool, pluginId: String, completion: ((Bool) -> Void)? = nil) {
        guard let plugin = self.plugin(id: pluginId) else {
            completion?(false)
            return
        }
        self.queue.async {
            guard PluginPreferences.shared.isEngineActive else {
                DispatchQueue.main.async {
                    completion?(false)
                }
                return
            }
            if plugin.isElyx {
                let value = try? PythonRuntime.shared.call("elyx_set_enabled", [pluginId, enabled])
                let object = value as? [String: Any] ?? [:]
                let ok = (object["ok"] as? Bool) ?? false
                if ok {
                    plugin.update(isEnabled: enabled, isLoaded: enabled, clearError: true)
                    if enabled {
                        self.loadSettings(plugin)
                    }
                } else {
                    plugin.update(error: (object["error"] as? String) ?? "the Elyx plugin did not load")
                }
                self.notifyChanged()
                DispatchQueue.main.async {
                    completion?(ok)
                }
                return
            }
            var success = true
            if enabled {
                if !plugin.manifest.requirements.isEmpty {
                    let value = try? PythonRuntime.shared.call(
                        "install_requirements",
                        [pluginId, plugin.manifest.requirements]
                    )
                    let object = value as? [String: Any] ?? [:]
                    if (object["ok"] as? Bool) != true {
                        let message = (object["error"] as? String) ?? "could not install the plugin dependencies"
                        plugin.update(error: message)
                        self.store.setEnabled(false, for: pluginId)
                        self.notifyChanged()
                        DispatchQueue.main.async {
                            completion?(false)
                        }
                        return
                    }
                }
                self.store.crashedPluginId = pluginId
                do {
                    let value = try PythonRuntime.shared.call(
                        "set_enabled",
                        [pluginId, true, plugin.path.path, ""]
                    )
                    let object = value as? [String: Any] ?? [:]
                    success = (object["ok"] as? Bool) ?? false
                    if success {
                        plugin.update(isLoaded: true, clearError: true)
                        plugin.markEnabled(true)
                        self.loadSettings(plugin)
                    } else {
                        let message = (object["error"] as? String) ?? "the plugin did not load"
                        plugin.update(error: message)
                    }
                    self.store.crashedPluginId = nil
                } catch {
                    success = false
                    plugin.update(error: "\(error)")
                    self.store.crashedPluginId = nil
                }
            } else {
                _ = try? PythonRuntime.shared.call("set_enabled", [pluginId, false])
                self.hooks.removeHooks(pluginId: pluginId)
                PluginFileHandlers.shared.unregisterAll(pluginId: pluginId)
                PluginIntentHandlers.shared.unregisterAll(pluginId: pluginId)
                plugin.update(isLoaded: false, isNotResponding: false)
                plugin.markEnabled(false)
            }
            self.store.setEnabled(success && enabled, for: pluginId)
            self.notifyChanged()
            DispatchQueue.main.async {
                completion?(success)
            }
        }
    }

    public func reload(pluginId: String, completion: ((Bool) -> Void)? = nil) {
        guard let plugin = self.plugin(id: pluginId), plugin.isEnabled else {
            completion?(false)
            return
        }
        self.queue.async {
            if plugin.isElyx {
                _ = try? PythonRuntime.shared.call("elyx_unload", [pluginId])
                _ = try? PythonRuntime.shared.call("elyx_load", [pluginId])
                plugin.update(isNotResponding: false)
                self.loadSettings(plugin)
                self.notifyChanged()
                DispatchQueue.main.async {
                    completion?(plugin.error == nil)
                }
                return
            }
            _ = try? PythonRuntime.shared.call("unload_plugin", [pluginId])
            self.hooks.removeHooks(pluginId: pluginId)
            plugin.update(isNotResponding: false)
            self.load(plugin)
            self.notifyChanged()
            DispatchQueue.main.async {
                completion?(plugin.error == nil)
            }
        }
    }

    /// The installed file for `id`, used to share it or open it in another app.
    public func pluginFileURL(id: String) -> URL {
        if self.plugin(id: id)?.isElyx == true {
            return self.store.elyxPluginURL(id: id)
        }
        return self.store.pluginURL(id: id)
    }

    public func isPinned(pluginId: String) -> Bool {
        return self.store.isPinned(pluginId)
    }

    public func setPinned(_ pinned: Bool, pluginId: String) {
        self.store.setPinned(pinned, for: pluginId)
        self.notifyChanged()
    }

    /// Packs an Elyx plugin directory into a `.elyx` archive in the cache and
    /// returns it, the same `getPluginPath` flow Android uses when sharing an
    /// Elyx plugin.
    public func exportElyxArchive(pluginId: String, completion: @escaping (URL?) -> Void) {
        self.queue.async {
            let value = try? PythonRuntime.shared.call("elyx_export_archive", [pluginId])
            let object = value as? [String: Any] ?? [:]
            let path = object["path"] as? String
            let url = path.flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0) }
            DispatchQueue.main.async {
                completion(url)
            }
        }
    }

    public func delete(pluginId: String, completion: ((Bool) -> Void)? = nil) {
        guard let plugin = self.plugin(id: pluginId) else {
            completion?(false)
            return
        }
        self.queue.async {
            if plugin.isElyx {
                let value = try? PythonRuntime.shared.call("elyx_delete", [pluginId])
                let object = value as? [String: Any] ?? [:]
                let success = (object["ok"] as? Bool) ?? false
                self.lock.lock()
                self.installed.removeAll { $0.id == pluginId }
                self.lock.unlock()
                self.postPluginNotification("pluginSettingsUnregistered", arguments: [pluginId])
                self.notifyChanged()
                DispatchQueue.main.async {
                    completion?(success)
                }
                return
            }
            _ = try? PythonRuntime.shared.call("unload_plugin", [pluginId])
            _ = try? PythonRuntime.shared.call("clear_plugin_settings", [pluginId])
            _ = try? PythonRuntime.shared.call("uninstall_requirements", [pluginId])
            self.hooks.removeHooks(pluginId: pluginId)
            PluginFileHandlers.shared.unregisterAll(pluginId: pluginId)
            PluginIntentHandlers.shared.unregisterAll(pluginId: pluginId)
            var success = true
            do {
                try self.store.delete(id: pluginId)
            } catch {
                success = false
                PluginLog.log("delete failed: \(error)", pluginId: pluginId, level: .error)
            }
            self.lock.lock()
            self.installed.removeAll { $0.id == pluginId }
            self.lock.unlock()
            self.postPluginNotification("pluginSettingsUnregistered", arguments: [pluginId])
            self.notifyChanged()
            DispatchQueue.main.async {
                completion?(success)
            }
        }
    }

    public struct InstallResult {
        public var plugin: Plugin?
        public var report: PluginAnalysisReport?
        public var error: String?
        public var replaced: Bool
    }

    public struct ElyxInspection {
        public var metadata: [String: Any]?
        public var errors: [String]
        public var requiredPlugins: [String]
        public var error: String?
        public var ok: Bool

        public init(metadata: [String: Any]?, errors: [String], requiredPlugins: [String], error: String?, ok: Bool) {
            self.metadata = metadata
            self.errors = errors
            self.requiredPlugins = requiredPlugins
            self.error = error
            self.ok = ok
        }
    }

    /// Reads an `.elyx` archive's metadata without installing it.
    public func inspectElyx(url: URL, password: String? = nil, completion: @escaping (ElyxInspection) -> Void) {
        self.queue.async {
            var arguments: [Any] = [url.path]
            if let password, !password.isEmpty {
                arguments.append(password)
            }
            let value = try? PythonRuntime.shared.call("elyx_inspect_archive", arguments)
            let object = value as? [String: Any] ?? [:]
            let metadata = object["metadata"] as? [String: Any]
            let errors = (object["errors"] as? [Any])?.compactMap { $0 as? String } ?? []
            let required = (object["required_plugins"] as? [Any])?.compactMap { $0 as? String } ?? []
            let error = object["error"] as? String
            let ok = (object["ok"] as? Bool) ?? false
            DispatchQueue.main.async {
                completion(ElyxInspection(
                    metadata: metadata,
                    errors: errors,
                    requiredPlugins: required,
                    error: error,
                    ok: ok
                ))
            }
        }
    }

    /// Analyses and installs a `.plugin` file. The caller decides whether to
    /// enable it after showing the report; passing `enabled` applies that choice
    /// before the plugin is loaded.
    public func install(url: URL, enabled requestedEnabled: Bool? = nil, completion: @escaping (InstallResult) -> Void) {
        self.queue.async {
            let existingURL = (try? PluginManifestParser.parse(fileAt: url)).map { self.store.pluginURL(id: $0.id) }
            let report = PluginAnalyzer.shared.analyzeSynchronously(
                PluginAnalysisRequest(fileURL: url, name: url.lastPathComponent, previousFileURL: existingURL)
            )
            do {
                let parsed = try PluginManifestParser.parse(fileAt: url)
                if let requirement = parsed.appVersionRequirement {
                    let satisfied = try pluginVersionRequirementIsSatisfied(requirement, actual: PluginHostInfo.compatibilityVersion)
                    if !satisfied {
                        throw PluginStoreError.invalidPlugin("plugin requires app version \(requirement), this build is \(PluginHostInfo.compatibilityVersion)")
                    }
                }
                if let requirement = parsed.sdkVersionRequirement {
                    let satisfied = try pluginVersionRequirementIsSatisfied(requirement, actual: PluginHostInfo.sdkVersion)
                    if !satisfied {
                        throw PluginStoreError.invalidPlugin("plugin requires SDK \(requirement), this runtime is \(PluginHostInfo.sdkVersion)")
                    }
                }
                let result = try self.store.install(fileAt: url)
                var dependencyError: String?
                if !result.manifest.requirements.isEmpty {
                    let value = try? PythonRuntime.shared.call(
                        "install_requirements",
                        [result.manifest.id, result.manifest.requirements]
                    )
                    let object = value as? [String: Any] ?? [:]
                    if (object["ok"] as? Bool) != true {
                        dependencyError = (object["error"] as? String) ?? "could not install the plugin dependencies"
                        PluginLog.log(dependencyError ?? "dependency installation failed", pluginId: result.manifest.id, level: .error)
                    }
                }
                if let requestedEnabled {
                    self.store.setEnabled(requestedEnabled, for: result.manifest.id)
                }
                let enabled = dependencyError == nil && self.store.isEnabled(result.manifest.id)
                if dependencyError != nil {
                    self.store.setEnabled(false, for: result.manifest.id)
                }
                let plugin = Plugin(
                    manifest: result.manifest,
                    path: self.store.pluginURL(id: result.manifest.id),
                    index: self.installed.count,
                    isEnabled: enabled
                )
                self.lock.lock()
                self.installed.removeAll { $0.id == plugin.id }
                self.installed.append(plugin)
                self.lock.unlock()
                if enabled && self.started && PluginPreferences.shared.isEngineActive {
                    self.load(plugin)
                }
                self.notifyChanged()
                DispatchQueue.main.async {
                    completion(InstallResult(plugin: plugin, report: report, error: dependencyError, replaced: result.replaced))
                }
            } catch {
                DispatchQueue.main.async {
                    completion(InstallResult(plugin: nil, report: report, error: "\(error)", replaced: false))
                }
            }
        }
    }

    /// Installs a `.elyx` archive. The Elyx engine validates the archive,
    /// extracts it into `plugins/ElyxPlugins/<id>` and returns the plugin.
    public func installElyx(url: URL, completion: @escaping (InstallResult) -> Void) {
        self.installElyx(url: url, password: nil, enabled: nil, completion: completion)
    }

    public func installElyx(url: URL, password: String?, enabled: Bool? = nil, completion: @escaping (InstallResult) -> Void) {
        guard PluginPreferences.shared.isEngineActive else {
            completion(InstallResult(
                plugin: nil,
                report: nil,
                error: "Turn on the Plugins engine before installing an Elyx plugin.",
                replaced: false
            ))
            return
        }
        self.queue.async {
            var arguments: [Any] = [url.path]
            if let password, !password.isEmpty {
                arguments.append(password)
            } else if enabled != nil {
                arguments.append(NSNull())
            }
            if let enabled {
                arguments.append(enabled)
            }
            let value = try? PythonRuntime.shared.call("elyx_install_archive", arguments)
            let object = value as? [String: Any] ?? [:]
            if (object["ok"] as? Bool) != true {
                DispatchQueue.main.async {
                    completion(InstallResult(
                        plugin: nil,
                        report: nil,
                        error: (object["error"] as? String) ?? "the .elyx archive is invalid",
                        replaced: false
                    ))
                }
                return
            }
            self.loadElyxPlugins()
            let pluginId = object["plugin_id"] as? String
            let plugin = pluginId.flatMap { self.plugin(id: $0) }
            self.notifyChanged()
            DispatchQueue.main.async {
                completion(InstallResult(
                    plugin: plugin,
                    report: nil,
                    error: plugin?.error,
                    replaced: false
                ))
            }
        }
    }

    /// Downloads a plugin file from an http(s) URL into a temporary directory.
    public func downloadPlugin(urlString: String, completion: @escaping (Result<URL, String>) -> Void) {
        guard let url = URL(string: urlString),
              let scheme = url.scheme?.lowercased(),
              scheme == "https" || scheme == "http" else {
            completion(.failure("Enter a valid http(s) URL."))
            return
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 60
        request.setValue("ExteraPluginKit/1.0", forHTTPHeaderField: "User-Agent")
        URLSession.shared.downloadTask(with: request) { location, response, error in
            if let error {
                completion(.failure(error.localizedDescription))
                return
            }
            guard let location else {
                completion(.failure("The download produced no file."))
                return
            }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard (200..<300).contains(status) else {
                completion(.failure("The download returned HTTP \(status)."))
                return
            }
            let name = url.lastPathComponent.isEmpty ? "plugin.plugin" : url.lastPathComponent
            let directory = FileManager.default.temporaryDirectory
                .appendingPathComponent("plugin-download-\(UUID().uuidString)", isDirectory: true)
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let destination = directory.appendingPathComponent(name)
            try? FileManager.default.removeItem(at: destination)
            do {
                try FileManager.default.moveItem(at: location, to: destination)
                completion(.success(destination))
            } catch {
                completion(.failure(error.localizedDescription))
            }
        }.resume()
    }

    /// Downloads a `.plugin`/`.elyx` file and installs it through the matching
    /// engine. Used by the "Install from URL" action.
    public func installFromURL(urlString: String, completion: @escaping (InstallResult) -> Void) {
        self.downloadPlugin(urlString: urlString) { [weak self] result in
            guard let self else {
                return
            }
            switch result {
            case let .failure(message):
                DispatchQueue.main.async {
                    completion(InstallResult(plugin: nil, report: nil, error: message, replaced: false))
                }
            case let .success(file):
                let extensionName = file.pathExtension.lowercased()
                if extensionName == "elyx" || extensionName == "eaf" {
                    self.installElyx(url: file, completion: completion)
                } else {
                    self.install(url: file, completion: completion)
                }
            }
        }
    }

    // -- Settings ------------------------------------------------------------

    public func settingsScreen(pluginId: String) -> PluginSettingsScreen? {
        do {
            let method = self.plugin(id: pluginId)?.isElyx == true ? "elyx_settings" : "load_settings"
            let value = try PythonRuntime.shared.call(method, [pluginId])
            return PluginSettingsScreen(json: value)
        } catch {
            return PluginSettingsScreen(controls: [], error: "\(error)")
        }
    }

    public func settingValue(pluginId: String, key: String, defaultValue: Any? = nil) -> Any? {
        guard let value = try? PythonRuntime.shared.call("get_setting_value", [pluginId, key, defaultValue ?? NSNull()]) else {
            return defaultValue
        }
        return value is NSNull ? defaultValue : value
    }

    public func setSettingValue(pluginId: String, key: String, value: Any) {
        _ = try? PythonRuntime.shared.call("set_setting_value", [pluginId, key, value])
    }

    /// Clears all values for a plugin, matching Android's "Reset settings".
    public func resetSettings(pluginId: String, completion: ((Bool) -> Void)? = nil) {
        self.queue.async {
            let value = try? PythonRuntime.shared.call("clear_plugin_settings", [pluginId])
            let success = (value as? Bool) ?? false
            self.postPluginNotification("pluginSettingsUnregistered", arguments: [pluginId])
            if let plugin = self.plugin(id: pluginId) {
                self.loadSettings(plugin)
            }
            self.notifyChanged()
            DispatchQueue.main.async {
                completion?(success)
            }
        }
    }

    public func invokeCallback(_ handle: String, arguments: [Any]) {
        do {
            _ = try PythonRuntime.shared.invoke(callback: handle, arguments: arguments)
        } catch {
            PluginLog.log("callback \(handle) failed: \(error)", level: .error)
        }
    }

    // -- App events ----------------------------------------------------------

    public func executeAppEvent(_ event: String) {
        for plugin in self.plugins where plugin.isLoaded {
            if plugin.isElyx {
                _ = try? PythonRuntime.shared.call("elyx_app_event", [plugin.id, event])
            } else {
                _ = try? PythonRuntime.shared.call("call_lifecycle", [plugin.id, "on_app_event", event])
            }
        }
    }

    public func notifyChanged() {
        DispatchQueue.main.async {
            NotificationCenter.default.post(name: Self.didChange, object: nil)
        }
        guard PythonRuntime.shared.isStarted else {
            return
        }
        self.lock.lock()
        let shouldNotify = !self.notifyingPluginsUpdated
        if shouldNotify {
            self.notifyingPluginsUpdated = true
        }
        self.lock.unlock()
        guard shouldNotify else {
            return
        }
        self.queue.async {
            _ = try? PythonRuntime.shared.call("notify_plugins_updated", [])
            self.lock.lock()
            self.notifyingPluginsUpdated = false
            self.lock.unlock()
        }
    }

    /// Marks a plugin as not responding (or responsive again).  Called by the
    /// hook dispatcher's watchdog; Android exposes the same user-visible state.
    public func markNotResponding(pluginId: String, _ value: Bool) {
        self.lock.lock()
        let plugin = self.installed.first(where: { $0.id == pluginId })
        self.lock.unlock()
        guard let plugin, plugin.isNotResponding != value else {
            return
        }
        plugin.update(isNotResponding: value)
        self.postPluginNotification("pluginIsNotResponding")
        if value {
            self.notifyChanged()
        }
    }

    /// Starts one plugin execution (a hook, a queued callback, a menu item or a
    /// lifecycle method). Concurrent executions of the same plugin share one
    /// timer, so a short callback cannot clear another callback's watchdog.
    public func beginPluginExecution(pluginId: String) {
        guard !pluginId.isEmpty else {
            return
        }
        self.lock.lock()
        let count = (self.executionCounts[pluginId] ?? 0) + 1
        self.executionCounts[pluginId] = count
        if count == 1 {
            let work = DispatchWorkItem { [weak self] in
                self?.markNotResponding(pluginId: pluginId, true)
            }
            self.executionTimers[pluginId] = work
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 5.0, execute: work)
        }
        self.lock.unlock()
    }

    public func endPluginExecution(pluginId: String) {
        guard !pluginId.isEmpty else {
            return
        }
        var work: DispatchWorkItem?
        var clear = false
        self.lock.lock()
        let count = max(0, (self.executionCounts[pluginId] ?? 1) - 1)
        if count == 0 {
            self.executionCounts.removeValue(forKey: pluginId)
            work = self.executionTimers.removeValue(forKey: pluginId)
            clear = true
        } else {
            self.executionCounts[pluginId] = count
        }
        self.lock.unlock()
        work?.cancel()
        if clear {
            self.markNotResponding(pluginId: pluginId, false)
        }
    }
}


