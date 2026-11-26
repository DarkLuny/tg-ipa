import Foundation
import UIKit
import SwiftSignalKit
import TelegramCore
import AccountContext
import Postbox
import Display
import ExteraPluginKit

/// Wires the plugin kit to the running app.
///
/// Called once from `AppDelegate` after `SharedAccountContextImpl` exists. It is
/// the only bridge between TelegramCore/AccountContext and the kit: the kit
/// itself stays free of both, and a build that never calls this has no plugins
/// and no hook cost.
enum PluginBootstrap {
    private static let registry = PluginContextRegistry()
    private static var started = false

    static func start(sharedContext: SharedAccountContext) {
        if self.started {
            return
        }
        self.started = true

        self.registry.attach(sharedContext: sharedContext)
        self.installHookPoints()
        self.installEnvironment()
        PluginManager.shared.start()

        HapticFeedback.isEnabled = ExteraSettings.shared.inAppVibration
        _ = NotificationCenter.default.addObserver(forName: ExteraSettings.didChange, object: nil, queue: .main) { _ in
            HapticFeedback.isEnabled = ExteraSettings.shared.inAppVibration
        }

        _ = NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { _ in
            PluginManager.shared.executeAppEvent("app_pause")
        }
        _ = NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { _ in
            PluginManager.shared.executeAppEvent("app_resume")
        }
        _ = NotificationCenter.default.addObserver(forName: Notification.Name("ExteraPluginKit.ChatOpened"), object: nil, queue: .main) { notification in
            guard let info = notification.userInfo,
                  let accountId = (info["accountId"] as? NSNumber)?.int64Value,
                  let peerId = (info["peerId"] as? NSNumber)?.int64Value else {
                return
            }
            let topicId = (info["threadId"] as? NSNumber)?.int64Value ?? 0
            PluginManager.shared.setCurrentChat(PluginChatContext(
                accountId: accountId,
                dialogId: PluginBootstrap.dialogId(from: PeerId(peerId)),
                topicId: topicId
            ))
        }
        _ = NotificationCenter.default.addObserver(forName: Notification.Name("ExteraPluginKit.ChatClosed"), object: nil, queue: .main) { _ in
            PluginManager.shared.setCurrentChat(nil)
        }
    }

    // -- Hooks ---------------------------------------------------------------

    private static func installHookPoints() {
        let hooks = PluginHooks.shared
        let hookPoints = PluginHookPoints.shared

        hookPoints.currentAccountId = {
            return registry.primary?.account.peerId.toInt64() ?? 0
        }

        hookPoints.wantsRequest = { name in
            return hooks.wants(eventName: name)
        }
        hookPoints.preRequest = { name, accountId, parametersJSON in
            let result = hooks.executePreRequest(
                name: name,
                account: accountId,
                params: PluginJSON.dictionary(parametersJSON)
            )
            if result.strategy == .cancel {
                return false
            }
            if result.strategy == .modify {
                PluginLog.log(
                    "a plugin rewrote \(name), but iOS cannot reserialize a TL request; the change was not applied",
                    pluginId: "",
                    level: .warning
                )
            }
            return true
        }
        hookPoints.postRequest = { name, accountId, responseJSON, error in
            _ = hooks.executePostRequest(
                name: name,
                account: accountId,
                response: PluginJSON.dictionary(responseJSON),
                error: error
            )
        }
        hookPoints.wantsUpdate = { name in
            return hooks.wants(eventName: name) || hooks.wantsNotificationUpdate(name)
        }
        hookPoints.receivedUpdate = { accountId, name, updateJSON in
            _ = hooks.executeUpdate(
                name: name,
                account: accountId,
                update: PluginJSON.dictionary(updateJSON)
            )
        }
        hookPoints.wantsSendMessage = {
            return hooks.wants(eventName: "send_message_hook")
        }
        hookPoints.sendMessage = { accountId, peerId, text in
            let original = text
            let result = hooks.executeSendMessage(
                account: accountId,
                params: ["peer": PluginBootstrap.dialogId(from: PeerId(peerId)), "message": original]
            )
            if result.strategy == .cancel {
                return false
            }
            if let updated = result.params?["message"] as? String {
                text = updated
            }
            return true
        }
    }

    // -- Environment ---------------------------------------------------------

    private static func installEnvironment() {
        PluginManager.shared.environment = PluginEnvironment(
            currentAccountId: {
                return registry.primary?.account.peerId.toInt64() ?? 0
            },
            accountIds: {
                return registry.contexts.keys.sorted()
            },
            send: { request in
                return registry.send(request)
            },
            request: { accountId, name, payload in
                if Thread.isMainThread {
                    return ["error": "raw requests cannot run on the main thread"]
                }
                guard let context = registry.context(id: accountId) else {
                    return ["error": "unknown account \(accountId)"]
                }
                let semaphore = DispatchSemaphore(value: 0)
                var result: [String: Any]?
                let disposable = pluginPerformRequest(account: context.account, name: name, payload: payload).start(next: { value in
                    result = value
                    semaphore.signal()
                })
                _ = semaphore.wait(timeout: .now() + 15.0)
                disposable.dispose()
                return result ?? ["error": "request did not finish"]
            },
            peer: { accountId, peerId in
                if Thread.isMainThread {
                    return nil
                }
                guard let context = registry.context(id: accountId) else {
                    return nil
                }
                return PluginBootstrap.fetchPeer(context: context, peerId: peerId)
            },
            chats: { accountId, limit, _ in
                if Thread.isMainThread {
                    return []
                }
                guard let context = registry.context(id: accountId) else {
                    return []
                }
                return PluginBootstrap.fetchChats(context: context, limit: limit)
            },
            contacts: { accountId in
                guard let context = registry.context(id: accountId) else {
                    return []
                }
                return context.account.postbox.getContactPeerIds().prefix(200).map { peerId -> [String: Any] in
                    let id = PluginBootstrap.dialogId(from: peerId)
                    // Android's `TL_contact` carries `user_id`; plugins read it.
                    return ["id": id, "peer_id": id, "user_id": id]
                }
            },
            me: { accountId in
                if Thread.isMainThread {
                    return nil
                }
                guard let context = registry.context(id: accountId) else {
                    return nil
                }
                return PluginBootstrap.fetchPeer(context: context, peerId: PluginBootstrap.dialogId(from: context.account.peerId))
            },
            deleteMessages: { accountId, peer, ids, revoke in
                guard let context = registry.context(id: accountId) else {
                    return false
                }
                let resolvedPeer = PluginBootstrap.peerId(fromDialogId: peer)
                let messageIds = ids.map { MessageId(peerId: resolvedPeer, namespace: Namespaces.Message.Cloud, id: $0) }
                let _ = context.engine.messages.deleteMessagesInteractively(
                    messageIds: messageIds,
                    type: revoke ? .forEveryone : .forLocalPeer
                ).start()
                return true
            },
            editMessage: { accountId, peer, messageId, text, entities in
                guard let context = registry.context(id: accountId) else {
                    return .failure("unknown account \(accountId)")
                }
                return PluginBootstrap.editMessage(
                    context: context,
                    peerId: peer,
                    messageId: messageId,
                    text: text,
                    entities: entities
                )
            },
            copyToClipboard: { text in
                UIPasteboard.general.string = text
            },
            readClipboard: {
                return UIPasteboard.general.string ?? ""
            },
            openURL: { url, _ in
                guard let value = URL(string: url) else { return }
                UIApplication.shared.open(value, options: [:], completionHandler: nil)
            },
            presentController: { spec in
                PluginBootstrap.present(spec: spec)
            },
            pickFile: { _, _ in
                return []
            },
            httpRequest: { url, method, headers, body, timeout in
                return PluginBootstrap.http(url: url, method: method, headers: headers, body: body, timeout: timeout)
            },
            openPluginSettings: { pluginId, link in
                let controller = PluginSettingsViewController(pluginId: pluginId, alias: link)
                PluginBootstrap.push(controller)
            }
        )
    }

    // -- Repository links ----------------------------------------------------

    /// Handles Android's `t.me/exteraPluginRepo?c=…` (channel) and
    /// `?git=…` (Git index) links, opening the repository the same way
    /// `PluginRepositoryLinks.open` does.
    @discardableResult
    static func handleOpenURL(_ url: URL) -> Bool {
        guard let link = PluginCatalog.parseRepositoryLink(url) else {
            return false
        }
        let accountId = PluginManager.shared.environment.currentAccountId()
        DispatchQueue.main.async {
            switch link {
            case let .channel(username):
                PluginCatalog.resolveChannel(accountId: accountId, username: username) { result in
                    DispatchQueue.main.async {
                        switch result {
                        case let .success((peerId, resolvedUsername, title)):
                            if let repository = PluginCatalogStore.shared.addChannel(
                                peerId: peerId,
                                username: resolvedUsername,
                                name: title
                            ) {
                                PluginBootstrap.push(PluginCatalogRepositoryViewController(repository: repository))
                            }
                        case let .failure(error):
                            PluginBootstrap.showCatalogError(error)
                        }
                    }
                }
            case let .git(value):
                guard let normalized = PluginCatalog.normalizeURL(value) else {
                    PluginBootstrap.showCatalogError(PluginCatalogError.invalidURL)
                    return
                }
                PluginCatalog.loadIndex(repositoryURL: normalized, etag: nil) { result in
                    DispatchQueue.main.async {
                        switch result {
                        case let .success(.loaded(index, _, etag)):
                            if let repository = PluginCatalogStore.shared.add(
                                url: normalized,
                                name: index.name,
                                homepage: index.homepage
                            ) {
                                PluginCatalogStore.shared.recordSync(id: repository.id, index: index, etag: etag)
                                PluginBootstrap.push(PluginCatalogRepositoryViewController(repository: repository))
                            }
                        case .success(.notModified):
                            break
                        case let .failure(error):
                            PluginBootstrap.showCatalogError(error)
                        }
                    }
                }
            }
        }
        return true
    }

    private static func showCatalogError(_ error: Error) {
        let alert = UIAlertController(
            title: "Catalog error",
            message: (error as? PluginCatalogError)?.description ?? "\(error)",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "OK", style: .default))
        PluginBootstrap.topViewController()?.present(alert, animated: true)
    }

    // -- Helpers -------------------------------------------------------------

    private static func present(spec: [String: Any]) {
        let type = (spec["type"] as? String) ?? ""
        switch type {
        case "plugins":
            PluginBootstrap.push(PluginsViewController())
        case "plugin_settings":
            if let pluginId = spec["plugin_id"] as? String {
                PluginBootstrap.push(PluginSettingsViewController(pluginId: pluginId))
            }
        default:
            break
        }
    }

    private static func push(_ controller: UIViewController) {
        DispatchQueue.main.async {
            guard let top = PluginBootstrap.topViewController() else {
                return
            }
            if let navigation = top as? UINavigationController {
                navigation.pushViewController(controller, animated: true)
            } else if let navigation = top.navigationController {
                navigation.pushViewController(controller, animated: true)
            } else {
                top.present(controller, animated: true)
            }
        }
    }

    private static func topViewController() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let window = scenes.flatMap { $0.windows }.first { $0.isKeyWindow } ?? scenes.first?.windows.first
        var controller = window?.rootViewController
        while let presented = controller?.presentedViewController {
            controller = presented
        }
        if let navigation = controller as? UINavigationController {
            return navigation.visibleViewController ?? navigation
        }
        if let tab = controller as? UITabBarController {
            return tab.selectedViewController ?? tab
        }
        return controller
    }

    fileprivate static func editMessage(context: AccountContext, peerId: Int64, messageId: Int32, text: String?, entities: [[String: Any]]) -> Result<Void, String> {
        let resolvedPeer = PluginBootstrap.peerId(fromDialogId: peerId)
        let id = MessageId(peerId: resolvedPeer, namespace: Namespaces.Message.Cloud, id: messageId)
        let parsedEntities: [MessageTextEntity] = PluginBootstrap.entities(entities)
        let attribute = parsedEntities.isEmpty ? nil : TextEntitiesMessageAttribute(entities: parsedEntities)
        let _ = context.engine.messages.requestEditMessage(
            messageId: id,
            text: text ?? "",
            media: .keep,
            entities: attribute,
            richText: nil,
            inlineStickers: [:],
            webpagePreviewAttribute: nil,
            invertMediaAttribute: nil,
            disableUrlPreview: false,
            scheduleInfoAttribute: nil
        ).start(next: { _ in
        }, error: { error in
            PluginLog.log("edit failed: \(error)", level: .error)
        })
        return .success(Void())
    }

    fileprivate static func entities(_ values: [[String: Any]]) -> [MessageTextEntity] {
        return values.compactMap { entity in
            guard let type = entity["type"] as? String else { return nil }
            let offset = (entity["offset"] as? NSNumber)?.intValue ?? 0
            let length = (entity["length"] as? NSNumber)?.intValue ?? 0
            let range = offset ..< (offset + length)
            switch type {
            case "bold": return MessageTextEntity(range: range, type: .Bold)
            case "italic": return MessageTextEntity(range: range, type: .Italic)
            case "underline": return MessageTextEntity(range: range, type: .Underline)
            case "strikethrough": return MessageTextEntity(range: range, type: .Strikethrough)
            case "spoiler": return MessageTextEntity(range: range, type: .Spoiler)
            case "code": return MessageTextEntity(range: range, type: .Code)
            case "pre": return MessageTextEntity(range: range, type: .Pre(language: entity["language"] as? String))
            case "text_link": return MessageTextEntity(range: range, type: .TextUrl(url: (entity["url"] as? String) ?? ""))
            case "blockquote": return MessageTextEntity(range: range, type: .BlockQuote(isCollapsed: false))
            default: return nil
            }
        }
    }

    fileprivate static func fetchChats(context: AccountContext, limit: Int) -> [[String: Any]] {
        let semaphore = DispatchSemaphore(value: 0)
        let box = PluginValueBox<[[String: Any]]>([])
        let signal = context.account.viewTracker.tailChatListView(
            groupId: PeerGroupId(rawValue: 0),
            count: min(max(limit, 1), 500)
        )
        let disposable = signal.start(next: { view, _ in
            box.set(view.items.compactMap { item -> [String: Any]? in
                guard case let .MessageEntry(data) = item else {
                    return nil
                }
                let id = PluginBootstrap.dialogId(from: data.index.messageIndex.id.peerId)
                return ["id": id, "peer_id": id]
            })
            semaphore.signal()
        })
        _ = semaphore.wait(timeout: .now() + 1.0)
        disposable.dispose()
        return box.get()
    }

    fileprivate static func fetchPeer(context: AccountContext, peerId: Int64) -> [String: Any]? {
        let resolved = PluginBootstrap.peerId(fromDialogId: peerId)
        let semaphore = DispatchSemaphore(value: 0)
        let box = PluginValueBox<[String: Any]?>(nil)
        let signal = context.engine.data.get(TelegramEngine.EngineData.Item.Peer.Peer(id: resolved))
        |> map { value -> [String: Any]? in
            guard let value else {
                return nil
            }
            let kind: String
            switch value {
            case .user(_):
                kind = "user"
            case .legacyGroup(_):
                kind = "group"
            case .channel(_):
                kind = "channel"
            case .community(_):
                kind = "community"
            case .secretChat(_):
                kind = "secretChat"
            }
            var fields: [String: Any] = [
                "id": PluginBootstrap.dialogId(from: value.id),
                "title": value.debugDisplayTitle,
                "username": value.addressName ?? "",
                "usernames": value.usernames.map { $0.username },
                "kind": kind,
                "isUser": kind == "user",
                "isGroup": kind == "group" || kind == "community",
                "isChannel": kind == "channel",
                "premium": value.isPremium,
                "verified": value.isVerified,
                "scam": value.isScam,
                "fake": value.isFake,
                "deleted": value.isDeleted,
                "support": value.isService,
                "bot": false
            ]
            // Android's TLRPC.User exposes first_name/last_name/phone; plugin
            // code reads them directly, so provide the same keys here.
            switch value.indexName {
            case let .personName(first, last, _, phone):
                fields["first_name"] = first
                fields["last_name"] = last
                fields["phone"] = phone ?? ""
            case let .title(title, _):
                fields["first_name"] = ""
                fields["last_name"] = ""
                fields["phone"] = ""
                if (fields["title"] as? String ?? "").isEmpty {
                    fields["title"] = title
                }
            }
            if case let .user(user) = value {
                fields["bot"] = user.botInfo != nil
            }
            return fields
        }
        let disposable = signal.start(next: { value in
            box.set(value)
            semaphore.signal()
        })
        _ = semaphore.wait(timeout: .now() + 1.0)
        disposable.dispose()
        return box.get()
    }

    fileprivate static func peerId(fromDialogId value: Int64) -> PeerId {
        if value <= -1000000000000 {
            return PeerId(namespace: Namespaces.Peer.CloudChannel, id: PeerId.Id._internalFromInt64Value(-(value + 1000000000000)))
        }
        if value < 0 {
            return PeerId(namespace: Namespaces.Peer.CloudGroup, id: PeerId.Id._internalFromInt64Value(-value))
        }
        return PeerId(namespace: Namespaces.Peer.CloudUser, id: PeerId.Id._internalFromInt64Value(value))
    }

    static func dialogId(from peerId: PeerId) -> Int64 {
        if peerId.namespace == Namespaces.Peer.CloudChannel {
            return -(peerId.id._internalGetInt64Value() + 1000000000000)
        }
        if peerId.namespace == Namespaces.Peer.CloudGroup {
            return -peerId.id._internalGetInt64Value()
        }
        return peerId.id._internalGetInt64Value()
    }

    fileprivate static func mimeType(for path: String) -> String {
        switch URL(fileURLWithPath: path).pathExtension.lowercased() {
        case "jpg", "jpeg": return "image/jpeg"
        case "png": return "image/png"
        case "webp": return "image/webp"
        case "heic": return "image/heic"
        case "gif": return "image/gif"
        case "mp4": return "video/mp4"
        case "mov": return "video/quicktime"
        case "mkv": return "video/x-matroska"
        case "mp3": return "audio/mpeg"
        case "m4a": return "audio/mp4"
        case "ogg", "opus": return "audio/ogg"
        case "flac": return "audio/flac"
        case "pdf": return "application/pdf"
        case "zip": return "application/zip"
        default: return "application/octet-stream"
        }
    }

    private static func http(url: String, method: String, headers: [String: String], body: String?, timeout: Double) -> [String: Any] {
        guard let value = URL(string: url) else {
            return ["error": "invalid URL"]
        }
        var request = URLRequest(url: value, timeoutInterval: max(1, timeout))
        request.httpMethod = method
        request.httpBody = body?.data(using: .utf8)
        for (key, item) in headers {
            request.setValue(item, forHTTPHeaderField: key)
        }
        let semaphore = DispatchSemaphore(value: 0)
        let box = PluginHTTPResultBox(["error": "no response"])
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error {
                box.set(["error": error.localizedDescription])
            } else {
                let http = response as? HTTPURLResponse
                box.set([
                    "status": http?.statusCode ?? 0,
                    "body": data.flatMap { String(data: $0, encoding: .utf8) } ?? "",
                    "headers": (http?.allHeaderFields as? [String: String]) ?? [:]
                ])
            }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + max(1, timeout) + 1)
        return box.get()
    }
}

private final class PluginContextRegistry: @unchecked Sendable {
    private let lock = NSLock()
    private(set) var primary: AccountContext?
    private var byId: [Int64: AccountContext] = [:]

    var contexts: [Int64: AccountContext] {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.byId
    }

    func context(id: Int64) -> AccountContext? {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.byId[id]
    }

    func attach(sharedContext: SharedAccountContext) {
        let _ = (sharedContext.activeAccountContexts
        |> deliverOnMainQueue).start(next: { [weak self] value in
            guard let self else { return }
            let (primary, accounts) = value
            self.lock.lock()
            self.primary = primary
            self.byId = Dictionary(uniqueKeysWithValues: accounts.map { pair in
                (pair.1.account.peerId.toInt64(), pair.1)
            })
            self.lock.unlock()
        })
    }

    func send(_ request: PluginSendRequest) -> Result<Int32, String> {
        guard let context = self.context(id: request.accountId) else {
            return .failure("unknown account \(request.accountId)")
        }
        if request.kind == "poll" {
            return .failure("polls from plugins are not implemented on iOS")
        }
        if let replyMarkupJSON = request.replyMarkupJSON,
           let data = replyMarkupJSON.data(using: .utf8),
           let replyMarkup = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            var payload: [String: Any] = [
                "peer": request.peerId,
                "message": request.text ?? request.caption ?? "",
                "reply_markup": replyMarkup
            ]
            if !request.entities.isEmpty {
                payload["entities"] = request.entities.map { entity -> [String: Any] in
                    var value: [String: Any] = [
                        "type": entity.type,
                        "offset": entity.offset,
                        "length": entity.length
                    ]
                    if let url = entity.url {
                        value["url"] = url
                    }
                    if let language = entity.language {
                        value["language"] = language
                    }
                    return value
                }
            }
            if let replyTo = request.replyTo {
                payload["reply_to_msg_id"] = replyTo
            }
            if request.silent {
                payload["silent"] = true
            }
            if request.scheduleDate > 0 {
                payload["schedule_date"] = request.scheduleDate
            }
            let _ = pluginPerformRequest(
                account: context.account,
                name: "messages.sendMessage",
                payload: payload
            ).start(next: { _ in })
            return .success(0)
        }
        if request.kind == "photo" || request.kind == "video" || request.kind == "audio" || request.kind == "document" {
            guard let path = request.path, let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else {
                return .failure("cannot read the media file")
            }
            var attributes: [MessageAttribute] = []
            if !request.entities.isEmpty {
                attributes.append(TextEntitiesMessageAttribute(entities: request.entities.map { entity in
                    let range = entity.offset ..< (entity.offset + entity.length)
                    switch entity.type {
                    case "bold": return MessageTextEntity(range: range, type: .Bold)
                    case "italic": return MessageTextEntity(range: range, type: .Italic)
                    case "underline": return MessageTextEntity(range: range, type: .Underline)
                    case "strikethrough": return MessageTextEntity(range: range, type: .Strikethrough)
                    case "spoiler": return MessageTextEntity(range: range, type: .Spoiler)
                    case "code": return MessageTextEntity(range: range, type: .Code)
                    case "pre": return MessageTextEntity(range: range, type: .Pre(language: entity.language))
                    case "text_link": return MessageTextEntity(range: range, type: .TextUrl(url: entity.url ?? ""))
                    case "blockquote": return MessageTextEntity(range: range, type: .BlockQuote(isCollapsed: false))
                    default: return MessageTextEntity(range: range, type: .Unknown)
                    }
                }))
            }
            if let replyTo = request.replyTo {
                attributes.append(ReplyMessageAttribute(
                    messageId: MessageId(peerId: PluginBootstrap.peerId(fromDialogId: request.peerId), namespace: Namespaces.Message.Cloud, id: replyTo),
                    threadMessageId: nil,
                    quote: nil,
                    isQuote: false,
                    innerSubject: nil
                ))
            }
            let fileName = URL(fileURLWithPath: path).lastPathComponent
            let media: StandaloneMedia
            if request.kind == "photo" {
                media = .image(data)
            } else {
                media = .file(
                    data: data,
                    mimeType: PluginBootstrap.mimeType(for: path),
                    attributes: [
                        .FileName(fileName: fileName)
                    ]
                )
            }
            let caption = request.text ?? request.caption ?? ""
            let disposable = standaloneSendMessage(
                account: context.account,
                peerId: PluginBootstrap.peerId(fromDialogId: request.peerId),
                text: caption,
                attributes: attributes,
                media: media,
                replyToMessageId: request.replyTo.map { MessageId(peerId: PluginBootstrap.peerId(fromDialogId: request.peerId), namespace: Namespaces.Message.Cloud, id: $0) }
            ).start(next: { _ in
            }, error: { error in
                PluginLog.log("media send failed: \(error)", level: .error)
            })
            _ = disposable
            return .success(0)
        }
        let text = request.text ?? request.caption ?? ""
        let entities: [MessageTextEntity] = request.entities.compactMap { entity in
            let range = entity.offset ..< (entity.offset + entity.length)
            switch entity.type {
            case "bold": return MessageTextEntity(range: range, type: .Bold)
            case "italic": return MessageTextEntity(range: range, type: .Italic)
            case "underline": return MessageTextEntity(range: range, type: .Underline)
            case "strikethrough": return MessageTextEntity(range: range, type: .Strikethrough)
            case "spoiler": return MessageTextEntity(range: range, type: .Spoiler)
            case "code": return MessageTextEntity(range: range, type: .Code)
            case "pre": return MessageTextEntity(range: range, type: .Pre(language: entity.language))
            case "text_link": return MessageTextEntity(range: range, type: .TextUrl(url: entity.url ?? ""))
            case "blockquote": return MessageTextEntity(range: range, type: .BlockQuote(isCollapsed: false))
            default: return nil
            }
        }
        var attributes: [MessageAttribute] = []
        if !entities.isEmpty {
            attributes.append(TextEntitiesMessageAttribute(entities: entities))
        }
        if let replyTo = request.replyTo {
            attributes.append(ReplyMessageAttribute(
                messageId: MessageId(peerId: PluginBootstrap.peerId(fromDialogId: request.peerId), namespace: Namespaces.Message.Cloud, id: replyTo),
                threadMessageId: nil,
                quote: nil,
                isQuote: false,
                innerSubject: nil
            ))
        }
        let peerId = PluginBootstrap.peerId(fromDialogId: request.peerId)
        let message = EnqueueMessage.message(
            text: text,
            attributes: attributes,
            inlineStickers: [:],
            mediaReference: nil,
            threadId: nil,
            replyToMessageId: nil,
            replyToStoryId: nil,
            localGroupingKey: nil,
            correlationId: nil,
            bubbleUpEmojiOrStickersets: [:]
        )
        let _ = enqueueMessages(account: context.account, peerId: peerId, messages: [message]).start()
        return .success(0)
    }
}


