import Foundation
import SwiftSignalKit
import MtProtoKit
internal import TelegramApi

/// Hook points the plugin runtime attaches to, declared inside TelegramCore so
/// the core does not depend on the plugin module.
///
/// `ExteraPluginKit` depends on `AccountContext`, and `AccountContext` depends
/// on `TelegramCore`, so a direct reference from the core to the kit would be a
/// cycle. The core exposes closures instead and the app wires them at launch;
/// when nothing is wired every hook is `nil` and the cost is one optional check.
///
/// Values cross the closures as JSON text, never as object graphs: a TL request
/// contains Swift enums and `TLObject`s that `JSONSerialization` refuses, so
/// they are flattened first. This is also what keeps a plugin from receiving an
/// app object it could call methods on.
public final class PluginHookPoints: @unchecked Sendable {
    public static let shared = PluginHookPoints()

    /// The account whose network is calling a hook. Set by the app at launch.
    public var currentAccountId: () -> Int64 = { 0 }

    /// Whether any plugin listens for this request name (`messages.setTyping`).
    /// Checked before parameters are flattened, so a build with no plugins pays
    /// only one optional closure call per request.
    public var wantsRequest: ((_ name: String) -> Bool)?

    /// Called before a TL request leaves the device.
    ///
    /// `parametersJSON` is the flattened request. Returning `false` cancels the
    /// request. A plugin may rewrite the JSON, but the serialized MTProto buffer
    /// has already been built, so field changes cannot be applied on iOS; only
    /// cancellation is honoured. This is reported by the plugin runtime.
    public var preRequest: ((_ name: String, _ accountId: Int64, _ parametersJSON: String) -> Bool)?

    /// Called after a TL request finished, whether it succeeded or failed.
    public var postRequest: ((_ name: String, _ accountId: Int64, _ responseJSON: String, _ error: String?) -> Void)?

    /// Called for every update the account state receives.
    ///
    /// The update has already been accepted, so a plugin can only observe it.
    public var receivedUpdate: ((_ accountId: Int64, _ name: String, _ updateJSON: String) -> Void)?

    /// Whether any plugin cares about an update constructor.
    public var wantsUpdate: ((_ name: String) -> Bool)?

    /// Rewrites or cancels an outgoing text message.
    ///
    /// The Android hook receives the whole `SendMessageParams`; the iOS app
    /// enqueues a typed `EnqueueMessage`, so the portable part is the text and
    /// the peer. Returning `false` drops the message.
    public var wantsSendMessage: (() -> Bool)?
    public var sendMessage: ((_ accountId: Int64, _ peerId: Int64, _ text: inout String) -> Bool)?

    /// Called when a plugin menu needs rebuilding.
    public var menuItemsChanged: (() -> Void)?

    private init() {
    }
}

/// Flattens a TL value into a JSON-compatible value.
func pluginJSONValue(_ value: Any?) -> Any {
    switch value {
    case nil, is NSNull:
        return NSNull()
    case let value as String:
        return value
    case let value as Bool:
        return value
    case let value as Int:
        return value
    case let value as Int32:
        return Int(value)
    case let value as Int64:
        return value
    case let value as Double:
        return value
    case let value as Data:
        return value.base64EncodedString()
    case let value as Buffer:
        // TL bytes fields (document file references, photo strips) arrive as a
        // Buffer; base64 is the shape `upload.getFile` and plugins expect.
        return value.makeData().base64EncodedString()
    case let value as [Any?]:
        return value.map { pluginJSONValue($0) }
    case let value as [Any]:
        return value.map { pluginJSONValue($0) }
    default:
        if let value = value {
            // `CustomStringConvertible` on a generated API value prints the
            // constructor name only, which is small and stable.
            return String(describing: value)
        }
        return NSNull()
    }
}

/// Any TL value as a JSON object of its fields.
func pluginValueObject(_ value: Any?) -> [String: Any] {
    var result: [String: Any] = [:]
    if let description = value as? TypeConstructorDescription {
        let (name, parameters) = description.descriptionFields()
        result["_"] = name
        for (fieldName, fieldValue) in parameters {
            result[fieldName] = pluginJSONValue(fieldValue.value)
        }
    } else {
        result["_"] = pluginJSONValue(value)
    }
    return result
}

/// Any TL value as a JSON object of its fields.
func pluginValueJSON(_ value: Any?) -> String {
    return pluginJSONString(pluginValueObject(value))
}

/// One update as a plugin's `on_update_hook` sees it.
func pluginUpdateFields(_ update: Api.Update) -> (name: String, fields: [String: Any]) {
    let (name, parameters) = update.descriptionFields()
    var fields: [String: Any] = ["_": name]
    for (fieldName, value) in parameters {
        fields[fieldName] = pluginJSONValue(value.value)
    }
    return (name, fields)
}

/// Flattens request parameters into a JSON object.
func pluginRequestParametersJSON(_ parameters: [(String, ConstructorParameterDescription)]) -> String {
    var result: [String: Any] = [:]
    for (name, description) in parameters {
        result[name] = pluginJSONValue(description.value)
    }
    return pluginJSONString(result)
}

func pluginJSONString(_ object: [String: Any]) -> String {
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
          let text = String(data: data, encoding: .utf8) else {
        return "{}"
    }
    return text
}

/// Reported to the caller when a plugin cancels a request.
public let pluginCancelledRequestError: MTRpcError = MTRpcError(
    errorCode: 406,
    errorDescription: "PLUGIN_CANCELLED"
)
