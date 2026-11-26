import Foundation

/// The strategy a hook returns; the names match `PluginsConstants.Strategy`.
public enum PluginHookStrategy: String, Sendable {
    case `default` = "DEFAULT"
    case modify = "MODIFY"
    case cancel = "CANCEL"
    case modifyFinal = "MODIFY_FINAL"
}

public struct PluginHookResult {
    public var strategy: PluginHookStrategy = .default
    public var request: [String: Any]? = nil
    public var response: [String: Any]? = nil
    public var update: [String: Any]? = nil
    public var updates: [String: Any]? = nil
    public var error: String? = nil
    public var params: [String: Any]? = nil
    public var failure: String? = nil

    public init(json: Any?) {
        guard let object = json as? [String: Any] else {
            return
        }
        self.strategy = PluginHookStrategy(rawValue: (object["strategy"] as? String) ?? "DEFAULT") ?? .default
        self.request = object["request"] as? [String: Any]
        self.response = object["response"] as? [String: Any]
        self.update = object["update"] as? [String: Any]
        self.updates = object["updates"] as? [String: Any]
        self.error = object["error"] as? String
        self.params = object["params"] as? [String: Any]
        self.failure = object["failure"] as? String
    }
}

public struct PluginEventHook: Sendable, Equatable {
    public var pluginId: String
    public var name: String
    public var matchSubstring: Bool
    public var priority: Int

    public init(pluginId: String, name: String, matchSubstring: Bool, priority: Int) {
        self.pluginId = pluginId
        self.name = name
        self.matchSubstring = matchSubstring
        self.priority = priority
    }

    public func matches(_ eventName: String) -> Bool {
        if self.matchSubstring {
            return eventName.contains(self.name)
        }
        return eventName == self.name
    }
}

public struct PluginMenuItem: Sendable, Equatable {
    public enum MenuType: String, Sendable {
        case messageContextMenu = "message_context_menu"
        case drawerMenu = "drawer_menu"
        case mainMenu = "main_menu"
        case chatActionMenu = "chat_action_menu"
        case profileActionMenu = "profile_action_menu"
    }

    public var pluginId: String
    public var itemId: String
    public var menuType: MenuType
    public var text: String
    public var subtext: String?
    public var icon: String?
    public var condition: String?
    public var priority: Int
    public var onClick: String?
    public var onLongClick: String?

    public init?(pluginId: String, json: [String: Any]) {
        guard let rawType = json["menu_type"] as? String,
              let menuType = MenuType(rawValue: rawType),
              let text = json["text"] as? String,
              !text.isEmpty,
              let onClick = json["on_click"] as? String,
              !onClick.isEmpty else {
            return nil
        }
        self.pluginId = pluginId
        self.itemId = (json["item_id"] as? String) ?? "\(pluginId).\(UUID().uuidString)"
        self.menuType = menuType
        self.text = text
        self.subtext = json["subtext"] as? String
        self.icon = json["icon"] as? String
        self.condition = json["condition"] as? String
        self.priority = (json["priority"] as? NSNumber)?.intValue ?? 0
        self.onClick = onClick
        self.onLongClick = json["on_long_click"] as? String
    }
}

/// Hook registry and dispatcher.
///
/// The registry is deliberately dumb: it maps a name to plugins and calls them
/// in priority order. The actual hook payloads are dictionaries flattened by
/// `PluginHookPoints` in TelegramCore, so the plugin sees the same constructor
/// names as on Android (`messages.sendMessage`, `updateNewMessage`).
public final class PluginHooks: @unchecked Sendable {
    public static let shared = PluginHooks()

    private let lock = NSLock()
    private var hooks: [String: [PluginEventHook]] = [:]
    private var menuItems: [String: PluginMenuItem] = [:] // by item id
    private var menuOrder: [String: [String]] = [:] // menu type raw value -> item ids
    private var xposedHooks: [String: [String]] = [:] // plugin id -> hook handles
    private var observedNotifications: Set<String> = []

    private init() {
    }

    public func reset() {
        self.lock.lock()
        let xposed = self.xposedHooks.values.flatMap { $0 }
        self.hooks.removeAll()
        self.menuItems.removeAll()
        self.menuOrder.removeAll()
        self.xposedHooks.removeAll()
        self.observedNotifications.removeAll()
        self.lock.unlock()
        for handle in xposed {
            PluginObjCRuntime.shared.uninstall(handle: handle)
        }
    }

    public func addXposedHook(pluginId: String, handle: String) {
        self.lock.lock()
        self.xposedHooks[pluginId, default: []].append(handle)
        self.lock.unlock()
    }

    // -- Event hooks ---------------------------------------------------------

    public func addEventHook(pluginId: String, name: String, matchSubstring: Bool, priority: Int) {
        self.lock.lock()
        var list = self.hooks[name] ?? []
        list.removeAll { $0.pluginId == pluginId }
        list.append(PluginEventHook(pluginId: pluginId, name: name, matchSubstring: matchSubstring, priority: priority))
        list.sort { $0.priority > $1.priority }
        self.hooks[name] = list
        self.lock.unlock()
    }

    public func removeEventHook(pluginId: String, name: String) {
        self.lock.lock()
        if var list = self.hooks[name] {
            list.removeAll { $0.pluginId == pluginId }
            if list.isEmpty {
                self.hooks.removeValue(forKey: name)
            } else {
                self.hooks[name] = list
            }
        }
        self.lock.unlock()
    }

    public func removeHooks(pluginId: String) {
        self.lock.lock()
        let xposed = self.xposedHooks.removeValue(forKey: pluginId) ?? []
        for (name, list) in self.hooks {
            let filtered = list.filter { $0.pluginId != pluginId }
            if filtered.isEmpty {
                self.hooks.removeValue(forKey: name)
            } else {
                self.hooks[name] = filtered
            }
        }
        for (itemId, item) in self.menuItems where item.pluginId == pluginId {
            self.menuItems.removeValue(forKey: itemId)
            self.menuOrder[item.menuType.rawValue]?.removeAll { $0 == itemId }
        }
        self.lock.unlock()
        for handle in xposed {
            PluginObjCRuntime.shared.uninstall(handle: handle)
        }
    }

    /// Plugin ids interested in `eventName`, in priority order.
    public func interestedPlugins(for eventName: String) -> [String] {
        self.lock.lock()
        var candidates: [PluginEventHook] = []
        if let exact = self.hooks[eventName] {
            candidates.append(contentsOf: exact)
        }
        for (name, list) in self.hooks where name != eventName {
            for hook in list where hook.matchSubstring && eventName.contains(name) {
                candidates.append(hook)
            }
        }
        self.lock.unlock()

        var best: [String: Int] = [:]
        for hook in candidates {
            best[hook.pluginId] = max(best[hook.pluginId] ?? Int.min, hook.priority)
        }
        return best.keys.sorted { left, right in
            if best[left] != best[right] {
                return (best[left] ?? 0) > (best[right] ?? 0)
            }
            return left < right
        }
    }

    public func wants(eventName: String) -> Bool {
        return !self.interestedPlugins(for: eventName).isEmpty
    }

    /// Remembers that a `NotificationCenter` observer waits for `name`.
    ///
    /// Android plugins subscribe through `get_notification_center(account)`
    /// rather than `on_update_hook`; the host must still ask for those updates.
    public func setNotificationObserved(name: String, observed: Bool) {
        self.lock.lock()
        if observed {
            self.observedNotifications.insert(name)
        } else {
            self.observedNotifications.remove(name)
        }
        self.lock.unlock()
    }

    public func wantsNotificationUpdate(_ name: String) -> Bool {
        self.lock.lock()
        let value = self.observedNotifications.contains(name)
        self.lock.unlock()
        return value
    }

    public func call(pluginId: String, hook: String, arguments: [Any]) -> PluginHookResult {
        PluginManager.shared.beginPluginExecution(pluginId: pluginId)
        defer {
            PluginManager.shared.endPluginExecution(pluginId: pluginId)
        }
        do {
            let value = try PythonRuntime.shared.call("call_hook", [pluginId, hook, PluginJSON.encodeString(arguments)])
            return PluginHookResult(json: value)
        } catch {
            PluginLog.log("hook \(hook) of \(pluginId) failed: \(error)", pluginId: pluginId, level: .error)
            return PluginHookResult(json: ["failure": "\(error)"])
        }
    }

    // -- Dispatch ------------------------------------------------------------

    public func executePreRequest(name: String, account: Int64, params: [String: Any]) -> PluginHookResult {
        var result = PluginHookResult(json: nil)
        for pluginId in self.interestedPlugins(for: name) {
            let current = self.call(pluginId: pluginId, hook: "pre_request_hook", arguments: [name, account, params])
            if current.strategy == .cancel {
                return current
            }
            if current.strategy == .modifyFinal {
                return current
            }
            if current.strategy == .modify, let request = current.request {
                result.strategy = .modify
                result.request = request
            }
            if current.failure != nil {
                result.failure = current.failure
            }
        }
        return result
    }

    public func executePostRequest(name: String, account: Int64, response: [String: Any]?, error: String?) -> PluginHookResult {
        var result = PluginHookResult(json: nil)
        for pluginId in self.interestedPlugins(for: name) {
            let current = self.call(pluginId: pluginId, hook: "post_request_hook", arguments: [name, account, response ?? [:], error ?? NSNull()])
            if current.strategy == .modifyFinal {
                return current
            }
            if let response = current.response {
                result.strategy = .modify
                result.response = response
            }
        }
        return result
    }

    public func executeUpdate(name: String, account: Int64, update: [String: Any]) -> PluginHookResult {
        // `NotificationCenter` observers see every update they subscribed to,
        // including the ones no `on_update_hook` asked for.
        _ = try? PythonRuntime.shared.call(
            "notify_update",
            [name, account, PluginJSON.encodeString(update)]
        )
        var result = PluginHookResult(json: nil)
        for pluginId in self.interestedPlugins(for: name) {
            let current = self.call(pluginId: pluginId, hook: "on_update_hook", arguments: [name, account, update])
            if current.strategy == .modify, let value = current.update {
                result.strategy = .modify
                result.update = value
            }
            if current.strategy == .modifyFinal {
                return current
            }
        }
        return result
    }

    public func executeUpdates(container: String, account: Int64, updates: [String: Any]) -> PluginHookResult {
        var result = PluginHookResult(json: nil)
        for pluginId in self.interestedPlugins(for: "*") + self.interestedPlugins(for: container) {
            let current = self.call(pluginId: pluginId, hook: "on_updates_hook", arguments: [container, account, updates])
            if current.strategy == .modify, let value = current.updates {
                result.strategy = .modify
                result.updates = value
            }
        }
        return result
    }

    public func executeSendMessage(account: Int64, params: [String: Any]) -> PluginHookResult {
        var result = PluginHookResult(json: nil)
        for pluginId in self.interestedPlugins(for: "send_message_hook") {
            let current = self.call(pluginId: pluginId, hook: "on_send_message_hook", arguments: [account, params])
            if current.strategy == .cancel {
                return current
            }
            if let value = current.params {
                result.strategy = current.strategy
                result.params = value
                if current.strategy == .modifyFinal {
                    return result
                }
            }
        }
        return result
    }

    public func executeAppEvent(_ event: String) {
        for pluginId in self.interestedPlugins(for: "on_app_event") {
            _ = try? PythonRuntime.shared.call("call_lifecycle", [pluginId, "on_app_event", event])
        }
    }

    // -- Menu items ----------------------------------------------------------

    @discardableResult
    public func addMenuItem(pluginId: String, json: [String: Any]) -> String? {
        guard let item = PluginMenuItem(pluginId: pluginId, json: json) else {
            return nil
        }
        self.lock.lock()
        self.menuItems[item.itemId] = item
        var order = self.menuOrder[item.menuType.rawValue] ?? []
        order.removeAll { $0 == item.itemId }
        order.append(item.itemId)
        order.sort { left, right in
            let l = self.menuItems[left]?.priority ?? 0
            let r = self.menuItems[right]?.priority ?? 0
            return l > r
        }
        self.menuOrder[item.menuType.rawValue] = order
        self.lock.unlock()
        return item.itemId
    }

    public func removeMenuItem(pluginId: String, itemId: String) -> Bool {
        self.lock.lock()
        defer { self.lock.unlock() }
        guard let item = self.menuItems[itemId], item.pluginId == pluginId else {
            return false
        }
        self.menuItems.removeValue(forKey: itemId)
        self.menuOrder[item.menuType.rawValue]?.removeAll { $0 == itemId }
        return true
    }

    public func menuItems(for type: PluginMenuItem.MenuType, context: [String: Any] = [:]) -> [PluginMenuItem] {
        self.lock.lock()
        let ids = self.menuOrder[type.rawValue] ?? []
        let items = ids.compactMap { self.menuItems[$0] }
        self.lock.unlock()

        return items.filter { item in
            guard let condition = item.condition, !condition.isEmpty else {
                return true
            }
            let value = try? PythonRuntime.shared.call("evaluate_condition", [condition, PluginJSON.encodeString(context)])
            return (value as? Bool) ?? false
        }
    }

    public func menuItem(id: String) -> PluginMenuItem? {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.menuItems[id]
    }

    public func invokeMenuItem(_ item: PluginMenuItem, context: [String: Any], longPress: Bool = false) {
        guard let handle = longPress ? item.onLongClick : item.onClick else {
            return
        }
        do {
            _ = try PythonRuntime.shared.invoke(callback: handle, arguments: [context])
        } catch {
            PluginLog.log("menu item \(item.itemId) failed: \(error)", pluginId: item.pluginId, level: .error)
        }
    }
}
