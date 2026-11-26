import Foundation

/// One row of a plugin's settings screen, as returned by `create_settings()`.
///
/// The Android SDK passes dataclasses (`ui.settings.Switch`, `Selector`, ...);
/// the Python runtime serialises them into this shape. Callbacks are opaque
/// handles retained by `extera_ios.retain` and invoked through the bridge.
public struct PluginSettingControl: Equatable, Sendable {
    public enum Kind: String, Sendable {
        case toggle = "switch"
        case picker = "selector"
        case input
        case header
        case divider
        case text
        case editText = "edit_text"
        case custom
    }

    public var kind: Kind
    public var key: String?
    public var text: String
    public var subtext: String?
    public var icon: String?
    public var accent: Bool
    public var red: Bool
    public var hint: String?
    public var multiline: Bool
    public var maxLength: Int
    public var mask: String?
    public var linkAlias: String?
    public var isDefaultOn: Bool
    public var defaultText: String
    public var defaultIndex: Int
    public var items: [String]
    public var callbacks: [String: String]
    public var customTitle: String?
    public var viewSpec: String?
    public var factoryType: String?
    public var factoryHandlers: [String]

    public init(
        kind: Kind,
        key: String? = nil,
        text: String = "",
        subtext: String? = nil,
        icon: String? = nil,
        accent: Bool = false,
        red: Bool = false,
        hint: String? = nil,
        multiline: Bool = false,
        maxLength: Int = 256,
        mask: String? = nil,
        linkAlias: String? = nil,
        isDefaultOn: Bool = false,
        defaultText: String = "",
        defaultIndex: Int = 0,
        items: [String] = [],
        callbacks: [String: String] = [:],
        customTitle: String? = nil,
        viewSpec: String? = nil,
        factoryType: String? = nil,
        factoryHandlers: [String] = []
    ) {
        self.kind = kind
        self.key = key
        self.text = text
        self.subtext = subtext
        self.icon = icon
        self.accent = accent
        self.red = red
        self.hint = hint
        self.multiline = multiline
        self.maxLength = maxLength
        self.mask = mask
        self.linkAlias = linkAlias
        self.isDefaultOn = isDefaultOn
        self.defaultText = defaultText
        self.defaultIndex = defaultIndex
        self.items = items
        self.callbacks = callbacks
        self.customTitle = customTitle
        self.viewSpec = viewSpec
        self.factoryType = factoryType
        self.factoryHandlers = factoryHandlers
    }

    public init?(json: Any) {
        guard let object = json as? [String: Any] else {
            return nil
        }
        let rawType = (object["type"] as? String) ?? "custom"
        let kind = Kind(rawValue: rawType) ?? .custom
        var callbacks: [String: String] = [:]
        for name in ["on_click", "on_change", "on_long_click", "create_sub_fragment"] {
            if let handle = object[name] as? String {
                callbacks[name] = handle
            }
        }
        var viewSpec: String?
        if let view = object["view"],
           let data = try? JSONSerialization.data(withJSONObject: view),
           let text = String(data: data, encoding: .utf8) {
            viewSpec = text
        }
        var factoryType: String?
        var factoryHandlers: [String] = []
        if let factory = object["factory"] as? [String: Any] {
            factoryType = factory["viewType"] as? String
            factoryHandlers = (factory["handlers"] as? [Any])?.compactMap { $0 as? String } ?? []
        }
        self.init(
            kind: kind,
            key: object["key"] as? String,
            text: (object["text"] as? String) ?? (object["hint"] as? String) ?? "",
            subtext: object["subtext"] as? String,
            icon: object["icon"] as? String,
            accent: (object["accent"] as? Bool) ?? false,
            red: (object["red"] as? Bool) ?? false,
            hint: object["hint"] as? String,
            multiline: (object["multiline"] as? Bool) ?? false,
            maxLength: (object["max_length"] as? NSNumber)?.intValue ?? 256,
            mask: object["mask"] as? String,
            linkAlias: object["link_alias"] as? String,
            isDefaultOn: (object["default"] as? Bool) ?? false,
            defaultText: (object["default"] as? String) ?? "",
            defaultIndex: (object["default"] as? NSNumber)?.intValue ?? 0,
            items: (object["items"] as? [Any])?.compactMap { $0 as? String } ?? [],
            callbacks: callbacks,
            customTitle: (object["title"] as? String),
            viewSpec: viewSpec,
            factoryType: factoryType,
            factoryHandlers: factoryHandlers
        )
    }
}

/// Current value of a setting, read from the Python settings store.
public enum PluginSettingValue: Equatable, Sendable {
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case json(String)

    public init?(json: Any?) {
        guard let json else {
            return nil
        }
        switch json {
        case let value as Bool:
            self = .bool(value)
        case let value as NSNumber:
            let double = value.doubleValue
            if double.rounded() == double, abs(double) < Double(Int.max) {
                self = .int(value.intValue)
            } else {
                self = .double(double)
            }
        case let value as String:
            self = .string(value)
        default:
            if let data = try? JSONSerialization.data(withJSONObject: json),
               let text = String(data: data, encoding: .utf8) {
                self = .json(text)
            } else {
                return nil
            }
        }
    }

    public var boolValue: Bool {
        switch self {
        case let .bool(value): return value
        case let .int(value): return value != 0
        case let .double(value): return value != 0
        case let .string(value): return !value.isEmpty
        case let .json(value): return value != "null" && value != "false" && value != "0"
        }
    }

    public var stringValue: String {
        switch self {
        case let .bool(value): return value ? "true" : "false"
        case let .int(value): return String(value)
        case let .double(value): return String(value)
        case let .string(value): return value
        case let .json(value): return value
        }
    }

    public var intValue: Int {
        switch self {
        case let .bool(value): return value ? 1 : 0
        case let .int(value): return value
        case let .double(value): return Int(value)
        case let .string(value): return Int(value) ?? 0
        case let .json(value): return Int(value) ?? 0
        }
    }

    public var jsonObject: Any {
        switch self {
        case let .bool(value): return value
        case let .int(value): return value
        case let .double(value): return value
        case let .string(value): return value
        case let .json(value):
            return (try? JSONSerialization.jsonObject(with: Data(value.utf8))) ?? NSNull()
        }
    }
}

/// A settings screen: the controls of one plugin plus a link alias target.
public struct PluginSettingsScreen: Sendable {
    public var title: String?
    public var controls: [PluginSettingControl]
    public var error: String?

    public init(title: String? = nil, controls: [PluginSettingControl], error: String? = nil) {
        self.title = title
        self.controls = controls
        self.error = error
    }

    public init(json: Any?) {
        guard let object = json as? [String: Any] else {
            self.init(controls: [], error: "the plugin did not return settings")
            return
        }
        self.init(
            title: object["title"] as? String,
            controls: (object["settings"] as? [Any] ?? []).compactMap { PluginSettingControl(json: $0) },
            error: object["error"] as? String
        )
    }
}

