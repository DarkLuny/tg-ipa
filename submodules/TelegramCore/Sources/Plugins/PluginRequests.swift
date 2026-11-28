import Foundation
import Postbox
import SwiftSignalKit
import MtProtoKit

/// A TL request a plugin asked the client to perform (`perform_request` / `perform_request_raw`).
///
/// This build's `TelegramApi` was generated from an older layer than the plugin layer expects
/// (keyboard button constructors, `messages.AffectedMessages.pts`, forum topic parameters), so the
/// generic request bridge cannot be compiled against it. The plugin runtime, its hooks and UI still
/// work; a plugin that performs a raw request gets no result instead of a wrong one.
public func pluginPerformRequest(account: Account, name: String, payload: [String: Any]) -> Signal<[String: Any]?, NoError> {
    return .single(nil)
}

/// Android dialog id -> Postbox peer id, the same conversion the plugin host uses.
func pluginPeerId(fromDialogId value: Int64) -> PeerId {
    if value <= -1000000000000 {
        return PeerId(namespace: Namespaces.Peer.CloudChannel, id: PeerId.Id._internalFromInt64Value(-(value + 1000000000000)))
    }
    if value < 0 {
        return PeerId(namespace: Namespaces.Peer.CloudGroup, id: PeerId.Id._internalFromInt64Value(-value))
    }
    return PeerId(namespace: Namespaces.Peer.CloudUser, id: PeerId.Id._internalFromInt64Value(value))
}

/// The MIME type used when a plugin edits a message's media from a local path.
func pluginMediaMimeType(for path: String) -> String {
    switch (path as NSString).pathExtension.lowercased() {
    case "jpg", "jpeg":
        return "image/jpeg"
    case "png":
        return "image/png"
    case "gif":
        return "image/gif"
    case "webp":
        return "image/webp"
    case "heic", "heif":
        return "image/heic"
    case "bmp":
        return "image/bmp"
    case "mp4", "m4v":
        return "video/mp4"
    case "mov":
        return "video/quicktime"
    case "mp3":
        return "audio/mpeg"
    case "m4a":
        return "audio/mp4"
    case "ogg", "opus":
        return "audio/ogg"
    case "pdf":
        return "application/pdf"
    case "zip":
        return "application/zip"
    case "txt":
        return "text/plain"
    default:
        return "application/octet-stream"
    }
}
