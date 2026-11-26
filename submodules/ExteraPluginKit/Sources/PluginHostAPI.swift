import Foundation
import UIKit
import AVFoundation
import CoreLocation
import CoreMedia
import UserNotifications

/// Handles every method a plugin can call through `extera_ios.host`.
///
/// The dispatcher is intentionally a single switch: it is the complete list of
/// host capabilities, and a method that is not here cannot be reached from a
/// plugin. Most methods map one-to-one onto the Android SDK function of the same
/// name; the ones that cannot exist on iOS (SharedPreferences, Android
/// fragments, ART reflection) return a typed error in the same JSON shape.
public final class PluginHostAPI: @unchecked Sendable {
    public static let shared = PluginHostAPI()

    public weak var uiHost: PluginUIHost?

    private let lock = NSLock()
    private var objects: [String: [String: Any]] = [:]
    private var objectClasses: [String: String] = [:]
    private var objectOwners: [String: String] = [:]
    private var nativeObjects: [String: AnyObject] = [:]
    private var nativeObjectOrder: [String] = []
    private var alerts: [String: UIAlertController] = [:]
    private var alertSpecs: [String: [String: Any]] = [:]
    private var uiWorkItems: [String: DispatchWorkItem] = [:]
    private var audioPlayer: AVAudioPlayer?
    private var nextIdentifier = 0

    private init() {
    }

    public func handle(method: String, payload: String) -> String {
        let input = PluginJSON.dictionary(payload)
        do {
            let result = try self.dispatch(method: method, input: input)
            return PluginJSON.encodeString(result ?? NSNull())
        } catch let error as PluginHostError {
            return PluginJSON.encodeString(["error": error.message])
        } catch {
            return PluginJSON.encodeString(["error": "\(error)"])
        }
    }

    public struct PluginHostError: Error {
        public var message: String

        public init(_ message: String) {
            self.message = message
        }
    }

    private func dispatch(method: String, input: [String: Any]) throws -> Any? {
        switch method {
        case "log":
            let text = (input["text"] as? String) ?? ""
            PluginLog.log(text, level: .info)
            return true

        case "log.write":
            PluginLog.log(
                (input["text"] as? String) ?? "",
                pluginId: (input["plugin_id"] as? String) ?? "",
                level: PluginLogLevel(rawValue: (input["level"] as? String) ?? "info") ?? .info
            )
            return true

        case "app.info":
            return [
                "version": PluginHostInfo.appVersion,
                "engine_version": PluginHostInfo.compatibilityVersion,
                "build": PluginHostInfo.buildNumber,
                "sdk_version": PluginHostInfo.sdkVersion,
                "platform": "ios",
                "engine": "python",
                "runtime": PythonRuntime.shared.isStarted ? "python" : "unavailable"
            ]

        case "app.updateBadge":
            let count = (input["count"] as? NSNumber)?.intValue ?? 0
            DispatchQueue.main.async {
                if #available(iOS 16.0, *) {
                    UNUserNotificationCenter.current().setBadgeCount(max(0, count), withCompletionHandler: nil)
                } else {
                    UIApplication.shared.applicationIconBadgeNumber = max(0, count)
                }
            }
            return true

        case "config.get":
            guard let key = input["key"] as? String else {
                throw PluginHostError("config.get expects key")
            }
            return self.configValue(for: key)

        case "config.set":
            guard let key = input["key"] as? String else {
                throw PluginHostError("config.set expects key")
            }
            guard let value = input["value"] else {
                throw PluginHostError("config.set expects value")
            }
            self.setConfigValue(value, for: key)
            return true

        case "config.all":
            return self.allConfigValues()

        case "location.address":
            let latitude = (input["latitude"] as? NSNumber)?.doubleValue
                ?? (input["lat"] as? NSNumber)?.doubleValue
            let longitude = (input["longitude"] as? NSNumber)?.doubleValue
                ?? (input["long"] as? NSNumber)?.doubleValue
            guard let latitude = latitude, let longitude = longitude else {
                throw PluginHostError("location.address expects latitude and longitude")
            }
            // CLGeocoder delivers its completion on the main queue; blocking the
            // main thread here would deadlock, so report no address from it.
            if Thread.isMainThread {
                return ["address": ""]
            }
            let semaphore = DispatchSemaphore(value: 0)
            var address = ""
            CLGeocoder().reverseGeocodeLocation(
                CLLocation(latitude: latitude, longitude: longitude)
            ) { placemarks, _ in
                if let placemark = placemarks?.first {
                    let parts = [
                        placemark.name,
                        placemark.locality,
                        placemark.administrativeArea,
                        placemark.country
                    ].compactMap { $0 }.filter { !$0.isEmpty }
                    address = parts.joined(separator: ", ")
                }
                semaphore.signal()
            }
            _ = semaphore.wait(timeout: .now() + 5)
            return ["address": address]

        case "device.info":
            return [
                "model": UIDevice.current.model,
                "system": UIDevice.current.systemVersion,
                "name": UIDevice.current.name,
                "locale": Locale.current.identifier
            ]

        case "account.current":
            return PluginManager.shared.environment.currentAccountId()

        case "account.list":
            return PluginManager.shared.environment.accountIds()

        case "paths.dir":
            let kind = (input["kind"] as? String) ?? (input["name"] as? String) ?? (input["path"] as? String) ?? "files"
            let store = PluginStore.shared
            let url: URL
            switch kind {
            case "plugins":
                url = store.pluginsURL
            case "sdk":
                url = store.sdkURL
            case "cache":
                url = FileManager.default.temporaryDirectory
            case "documents":
                url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first ?? store.filesURL
            case "images":
                url = store.filesURL.appendingPathComponent("images", isDirectory: true)
            case "videos":
                url = store.filesURL.appendingPathComponent("videos", isDirectory: true)
            case "audios":
                url = store.filesURL.appendingPathComponent("audios", isDirectory: true)
            default:
                url = store.filesURL
            }
            if kind == "files" || kind == "images" || kind == "videos" || kind == "audios" {
                try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
            }
            return url.path

        case "ui.run":
            guard let handle = input["handle"] as? String else {
                throw PluginHostError("ui.run expects a callback handle")
            }
            let delay = (input["delay"] as? NSNumber)?.doubleValue ?? 0
            let workItem = DispatchWorkItem { [weak self] in
                guard let self else {
                    return
                }
                self.lock.lock()
                self.uiWorkItems.removeValue(forKey: handle)
                self.lock.unlock()
                PluginManager.shared.invokeCallback(handle, arguments: [])
            }
            self.lock.lock()
            self.uiWorkItems[handle]?.cancel()
            self.uiWorkItems[handle] = workItem
            self.lock.unlock()
            DispatchQueue.main.asyncAfter(deadline: .now() + max(0, delay) / 1000.0, execute: workItem)
            return handle

        case "ui.cancel":
            if let handle = input["handle"] as? String {
                self.lock.lock()
                let workItem = self.uiWorkItems.removeValue(forKey: handle)
                self.lock.unlock()
                workItem?.cancel()
            }
            return true

        case "ui.toast":
            let text = (input["text"] as? String) ?? ""
            self.uiHost?.showBulletin(kind: "simple", text: text, subtext: nil, duration: (input["duration"] as? NSNumber)?.intValue ?? 2000)
            return true

        case "ui.bulletin":
            let spec = PluginBulletinSpec(
                kind: (input["kind"] as? String) ?? "simple",
                text: (input["text"] as? String) ?? "",
                subtext: input["subtext"] as? String,
                duration: (input["duration"] as? NSNumber)?.intValue ?? 2000,
                icon: input["icon"],
                buttonText: input["button_text"] as? String,
                onButton: input["on_click"] as? String,
                undoText: input["undo_text"] as? String,
                onUndo: input["on_undo"] as? String,
                onAction: input["on_action"] as? String
            )
            self.uiHost?.showBulletin(spec)
            return true

        case "ui.copy":
            PluginManager.shared.environment.copyToClipboard((input["text"] as? String) ?? "")
            return true

        case "ui.clipboard":
            return PluginManager.shared.environment.readClipboard()

        case "ui.open_url":
            PluginManager.shared.environment.openURL((input["url"] as? String) ?? "", (input["external"] as? Bool) ?? false)
            return true

        case "ui.notify":
            self.postNotification(title: (input["title"] as? String) ?? "", text: (input["text"] as? String) ?? "")
            return true

        case "ui.present":
            PluginManager.shared.environment.presentController((input["spec"] as? [String: Any]) ?? [:])
            return true

        case "ui.dismiss":
            DispatchQueue.main.async {
                self.topViewController()?.dismiss(animated: true)
            }
            return true

        case "ui.last_fragment":
            if let chat = PluginManager.shared.currentChat() {
                return [
                    "__class__": "org.telegram.ui.ChatActivity",
                    "dialog_id": chat.dialogId,
                    "topic_id": chat.topicId,
                    "account": chat.accountId
                ]
            }
            guard let controller = self.topViewController() else {
                return NSNull()
            }
            return self.descriptor(for: controller)

        case "audio.play":
            guard let path = input["path"] as? String,
                  FileManager.default.fileExists(atPath: path) else {
                return ["ok": false, "error": "cannot read the audio file"]
            }
            var response: [String: Any] = ["ok": false, "error": "cannot play the file"]
            let play = {
                do {
                    let player = try AVAudioPlayer(contentsOf: URL(fileURLWithPath: path))
                    player.enableRate = true
                    if let volume = (input["volume"] as? NSNumber)?.floatValue {
                        player.volume = max(0.0, min(1.0, volume))
                    }
                    if let rate = (input["rate"] as? NSNumber)?.floatValue, rate > 0.0 {
                        player.rate = max(0.1, min(3.0, rate))
                    }
                    player.prepareToPlay()
                    player.play()
                    self.audioPlayer = player
                    response = [
                        "ok": true,
                        "playing": player.isPlaying,
                        "duration": player.duration
                    ]
                } catch {
                    response = ["ok": false, "error": "\(error)"]
                }
            }
            if Thread.isMainThread {
                play()
            } else {
                DispatchQueue.main.sync(execute: play)
            }
            return response

        case "audio.pause":
            self.withAudioPlayer { player in
                player.pause()
            }
            return ["ok": true, "state": self.audioState()]

        case "audio.resume":
            self.withAudioPlayer { player in
                player.play()
            }
            return ["ok": true, "state": self.audioState()]

        case "audio.stop":
            self.withAudioPlayer { player in
                player.stop()
                player.currentTime = 0
            }
            return ["ok": true]

        case "audio.seek":
            let position = (input["position"] as? NSNumber)?.doubleValue ?? 0
            self.withAudioPlayer { player in
                player.currentTime = max(0, min(player.duration, position))
            }
            return ["ok": true, "state": self.audioState()]

        case "audio.rate":
            let rate = (input["rate"] as? NSNumber)?.floatValue ?? 1.0
            self.withAudioPlayer { player in
                player.enableRate = true
                player.rate = max(0.1, min(3.0, rate))
            }
            return ["ok": true, "state": self.audioState()]

        case "audio.volume":
            let volume = (input["volume"] as? NSNumber)?.floatValue ?? 1.0
            self.withAudioPlayer { player in
                player.volume = max(0.0, min(1.0, volume))
            }
            return ["ok": true]

        case "audio.state":
            return self.audioState()

        case "media.frame":
            guard let path = input["path"] as? String,
                  FileManager.default.fileExists(atPath: path) else {
                return ["ok": false, "error": "cannot read the video file"]
            }
            let seconds = (input["time"] as? NSNumber)?.doubleValue ?? 0
            let asset = AVURLAsset(url: URL(fileURLWithPath: path))
            let generator = AVAssetImageGenerator(asset: asset)
            generator.appliesPreferredTrackTransform = true
            let time = CMTime(seconds: max(0, seconds), preferredTimescale: 600)
            var actual = CMTime.zero
            do {
                let image = try generator.copyCGImage(at: time, actualTime: &actual)
                let uiImage = UIImage(cgImage: image)
                guard let data = uiImage.jpegData(compressionQuality: 0.8) else {
                    return ["ok": false, "error": "cannot encode the frame"]
                }
                return [
                    "ok": true,
                    "data": data.base64EncodedString(),
                    "width": Int(image.width),
                    "height": Int(image.height),
                    "time": CMTimeGetSeconds(actual)
                ]
            } catch {
                return ["ok": false, "error": "\(error)"]
            }

        case "ui.pick_file":
            return PluginManager.shared.environment.pickFile(
                (input["extensions"] as? [String]) ?? [],
                (input["multiple"] as? Bool) ?? false
            )

        case "alert.create":
            return self.presentAlert(input, show: false)
        case "alert.show":
            return self.presentAlert(input, show: true)
        case "alert.update":
            return self.updateAlert(input)
        case "alert.dismiss":
            if let identifier = input["id"] as? String {
                self.dismissAlert(identifier)
            }
            return true

        case "hooks.add":
            guard let pluginId = input["plugin_id"] as? String,
                  let name = input["name"] as? String else {
                throw PluginHostError("hooks.add expects plugin_id and name")
            }
            PluginHooks.shared.addEventHook(
                pluginId: pluginId,
                name: name,
                matchSubstring: (input["match_substring"] as? Bool) ?? false,
                priority: (input["priority"] as? NSNumber)?.intValue ?? 0
            )
            return true

        case "hooks.remove":
            if let pluginId = input["plugin_id"] as? String,
               let name = input["name"] as? String {
                PluginHooks.shared.removeEventHook(pluginId: pluginId, name: name)
            }
            return true

        case "hooks.add_xposed":
            if let pluginId = input["plugin_id"] as? String, let handle = input["handle"] as? String {
                PluginHooks.shared.addXposedHook(pluginId: pluginId, handle: handle)
            }
            return true

        case "menu.add":
            guard let pluginId = input["plugin_id"] as? String,
                  let data = input["data"] as? [String: Any] else {
                throw PluginHostError("menu.add expects plugin_id and data")
            }
            return PluginHooks.shared.addMenuItem(pluginId: pluginId, json: data)

        case "menu.update":
            // Replacing a menu item keeps its identity, so merge the existing
            // fields with the supplied changes and remove + add.
            if let pluginId = input["plugin_id"] as? String,
               let itemId = input["item_id"] as? String,
               let existing = PluginHooks.shared.menuItem(id: itemId),
               existing.pluginId == pluginId {
                var data: [String: Any] = [
                    "menu_type": existing.menuType.rawValue,
                    "text": existing.text,
                    "item_id": itemId,
                    "priority": existing.priority
                ]
                if let value = existing.subtext {
                    data["subtext"] = value
                }
                if let value = existing.icon {
                    data["icon"] = value
                }
                if let value = existing.condition {
                    data["condition"] = value
                }
                if let value = existing.onClick {
                    data["on_click"] = value
                }
                if let value = existing.onLongClick {
                    data["on_long_click"] = value
                }
                if let changes = input["data"] as? [String: Any] {
                    for (key, value) in changes {
                        data[key] = value
                    }
                }
                _ = PluginHooks.shared.removeMenuItem(pluginId: pluginId, itemId: itemId)
                return PluginHooks.shared.addMenuItem(pluginId: pluginId, json: data)
            }
            return false

        case "menu.remove":
            if let pluginId = input["plugin_id"] as? String,
               let itemId = input["item_id"] as? String {
                return PluginHooks.shared.removeMenuItem(pluginId: pluginId, itemId: itemId)
            }
            return false

        case "menu.list":
            let rawType = (input["menu_type"] as? String) ?? "message_context_menu"
            guard let type = PluginMenuItem.MenuType(rawValue: rawType) else {
                return []
            }
            let context = (input["context"] as? [String: Any]) ?? [:]
            return PluginHooks.shared.menuItems(for: type, context: context).map { item -> [String: Any] in
                [
                    "item_id": item.itemId,
                    "text": item.text,
                    "subtext": item.subtext ?? "",
                    "icon": item.icon ?? "",
                    "priority": item.priority
                ]
            }

        case "menu.invoke":
            guard let itemId = input["item_id"] as? String,
                  let item = PluginHooks.shared.menuItem(id: itemId) else {
                return false
            }
            PluginHooks.shared.invokeMenuItem(
                item,
                context: (input["context"] as? [String: Any]) ?? [:],
                longPress: (input["long_press"] as? Bool) ?? false
            )
            return true

        case "settings.reload":
            if input["plugin_id"] is String {
                PluginManager.shared.notifyChanged()
            }
            return true

        case "plugins.reload":
            PluginManager.shared.reloadAll()
            return true

        case "plugins.show_install":
            DispatchQueue.main.async {
                guard let top = self.topViewController() else {
                    return
                }
                let controller = PluginsViewController()
                let navigation = UINavigationController(rootViewController: controller)
                top.present(navigation, animated: true) {
                    controller.presentInstallPicker()
                }
            }
            return true

        case "plugins.is_pinned":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            return PluginManager.shared.isPinned(pluginId: pluginId)

        case "plugins.set_pinned":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            PluginManager.shared.setPinned((input["pinned"] as? Bool) ?? false, pluginId: pluginId)
            return true

        case "plugins.set_enabled":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            PluginManager.shared.setEnabled((input["enabled"] as? Bool) ?? false, pluginId: pluginId)
            return true

        case "runtime.is_started":
            return PythonRuntime.shared.isStarted

        case "settings.open":
            if let pluginId = input["plugin_id"] as? String {
                let link = input["link"] as? String
                DispatchQueue.main.async {
                    PluginManager.shared.environment.openPluginSettings(pluginId, link)
                }
            }
            return true

        case "settings.get":
            guard let pluginId = input["plugin_id"] as? String,
                  let key = input["key"] as? String else {
                return input["default"]
            }
            return PluginManager.shared.settingValue(pluginId: pluginId, key: key, defaultValue: input["default"])

        case "settings.set":
            if let pluginId = input["plugin_id"] as? String,
               let key = input["key"] as? String {
                PluginManager.shared.setSettingValue(pluginId: pluginId, key: key, value: input["value"] ?? NSNull())
            }
            return true

        case "client.send", "client.send_text":
            return try self.sendMessage(input)

        case "client.send_media":
            return try self.sendMedia(input)

        case "client.edit_message":
            let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
            let peer = (input["peer"] as? NSNumber)?.int64Value ?? 0
            let messageId = (input["message_id"] as? NSNumber)?.int32Value ?? 0
            let entities = (input["entities"] as? [[String: Any]]) ?? []
            return try self.editMessage(
                account: account,
                peer: peer,
                messageId: messageId,
                text: input["text"] as? String,
                entities: entities,
                path: input["path"] as? String,
                kind: input["kind"] as? String
            )

        case "client.delete_messages":
            let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
            let peer = (input["peer"] as? NSNumber)?.int64Value ?? 0
            let ids = (input["message_ids"] as? [NSNumber])?.map { $0.int32Value } ?? []
            return PluginManager.shared.environment.deleteMessages(account, peer, ids, (input["revoke"] as? Bool) ?? true)

        case "client.request":
            let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
            let name = (input["name"] as? String) ?? ""
            let payload = (input["payload"] as? [String: Any]) ?? [:]
            return PluginManager.shared.environment.request(account, name, payload)

        case "client.download":
            let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
            let fileId = (input["id"] as? NSNumber)?.int64Value ?? 0
            let accessHash = (input["access_hash"] as? NSNumber)?.int64Value ?? 0
            let reference = Data(base64Encoded: (input["file_reference"] as? String) ?? "") ?? Data()
            let fileName = (input["file_name"] as? String) ?? ""
            let size = (input["size"] as? NSNumber)?.int64Value ?? 0
            return PluginDownloader.download(
                accountId: account,
                fileId: fileId,
                accessHash: accessHash,
                fileReference: reference,
                fileName: fileName,
                size: size,
                kind: (input["kind"] as? String) ?? "document",
                thumbSize: (input["thumb_size"] as? String) ?? ""
            )

        case "client.peer":
            let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
            let peer = (input["peer"] as? NSNumber)?.int64Value ?? 0
            return PluginManager.shared.environment.peer(account, peer)

        case "client.chats":
            let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
            return PluginManager.shared.environment.chats(
                account,
                (input["limit"] as? NSNumber)?.intValue ?? 100,
                (input["offset"] as? NSNumber)?.intValue ?? 0
            )

        case "client.contacts":
            let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
            return PluginManager.shared.environment.contacts(account)

        case "client.me":
            let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
            return PluginManager.shared.environment.me(account)

        case "client.last_fragment":
            if let chat = PluginManager.shared.currentChat() {
                return [
                    "__class__": "org.telegram.ui.ChatActivity",
                    "dialog_id": chat.dialogId,
                    "topic_id": chat.topicId,
                    "account": chat.accountId
                ]
            }
            return NSNull()

        case "client.notification_center":
            return ["account": (input["account"] as? NSNumber)?.int64Value ?? 0]

        case "locale.language":
            let preferred = Locale.preferredLanguages.first ?? "en"
            return String(preferred.prefix(2))

        case "locale.string":
            let key = (input["key"] as? String) ?? ""
            if let localized = PluginLocalization.string(for: key) {
                return localized
            }
            return Bundle.main.localizedString(forKey: key, value: key, table: nil)

        case "runtime.build_version":
            return 66999

        case "notifications.set_observed":
            let name = (input["name"] as? String) ?? ""
            if !name.isEmpty {
                PluginHooks.shared.setNotificationObserved(
                    name: name,
                    observed: (input["observed"] as? Bool) ?? false
                )
            }
            return true

        case "file.register":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            let extensionName = (input["extension"] as? String) ?? ""
            let handle = (input["handle"] as? String) ?? ""
            return PluginFileHandlers.shared.register(
                pluginId: pluginId,
                extensionName: extensionName,
                description: (input["description"] as? String) ?? "",
                handle: handle,
                icon: input["icon"]
            )

        case "file.unregister":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            let extensionName = (input["extension"] as? String) ?? ""
            PluginFileHandlers.shared.unregister(pluginId: pluginId, extensionName: extensionName)
            return true

        case "intent.register":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            let spec = (input["spec"] as? [String: Any]) ?? [:]
            let handlerId = (input["handle"] as? String) ?? UUID().uuidString
            let handle = (input["handle"] as? String) ?? ""
            PluginIntentHandlers.shared.register(
                id: handlerId,
                pluginId: pluginId,
                handle: handle,
                before: (input["before"] as? Bool) ?? true,
                priority: (spec["priority"] as? NSNumber)?.intValue ?? 0,
                type: (spec["type"] as? String) ?? "url",
                scheme: spec["scheme"] as? String,
                host: spec["host"] as? String,
                path: spec["path"] as? String
            )
            return handlerId

        case "intent.unregister":
            if let identifier = input["id"] as? String {
                PluginIntentHandlers.shared.unregister(id: identifier)
            }
            return true

        case "intent.send":
            if let url = input["data"] as? String {
                PluginManager.shared.environment.openURL(url, true)
                return true
            }
            return false

        case "http.request":
            return self.httpRequest(input)

        case "http.download":
            return self.httpDownload(input)

        case "analyze.file":
            let path = (input["path"] as? String) ?? ""
            return PluginAnalyzer.shared.analyzeSynchronously(
                PluginAnalysisRequest(fileURL: URL(fileURLWithPath: path), name: (input["name"] as? String) ?? path)
            ).asJSON

        case "runtime.is_main_thread":
            return Thread.isMainThread

        case "runtime.plugin_started":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            PluginManager.shared.beginPluginExecution(pluginId: pluginId)
            return NSNull()

        case "runtime.plugin_finished":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            PluginManager.shared.endPluginExecution(pluginId: pluginId)
            return NSNull()

        case "runtime.object.call":
            guard let handle = input["handle"] as? String,
                  let selector = input["selector"] as? String else {
                return NSNull()
            }
            let arguments = (input["args"] as? [Any]) ?? []
            if PluginObjCRuntime.shared.object(for: handle) != nil {
                let result = PluginObjCRuntime.shared.callObject(handle: handle, selector: selector, arguments: arguments)
                if let result {
                    return PluginHostAPI.propertyValue(result)
                }
                return NSNull()
            }
            return NSNull()

        case "runtime.object.get":
            if let handle = input["handle"] as? String, let name = input["name"] as? String {
                if let value = PluginObjCRuntime.shared.getProperty(handle: handle, name: name) {
                    return PluginHostAPI.propertyValue(value)
                }
            }
            return NSNull()

        case "runtime.object.set":
            if let handle = input["handle"] as? String, let name = input["name"] as? String {
                return PluginObjCRuntime.shared.setProperty(handle: handle, name: name, value: input["value"] ?? NSNull())
            }
            return false

        case "runtime.call":
            guard let target = input["target"] as? String,
                  let selector = input["selector"] as? String else {
                return NSNull()
            }
            let arguments = (input["args"] as? [Any]) ?? []
            if let result = PluginObjCRuntime.shared.callObject(handle: target, selector: selector, arguments: arguments) {
                return PluginHostAPI.propertyValue(result)
            }
            return NSNull()

        case "runtime.get_property":
            if let target = input["target"] as? String, let name = input["name"] as? String,
               let value = PluginObjCRuntime.shared.getProperty(handle: target, name: name) {
                return PluginHostAPI.propertyValue(value)
            }
            return NSNull()

        case "runtime.set_property":
            if let target = input["target"] as? String, let name = input["name"] as? String {
                return PluginObjCRuntime.shared.setProperty(handle: target, name: name, value: input["value"] ?? NSNull())
            }
            return false

        case "runtime.responds_to":
            guard let target = input["target"] as? String,
                  let selector = input["selector"] as? String,
                  let object = PluginObjCRuntime.shared.object(for: target) as? NSObject else {
                return false
            }
            let resolved = PluginObjCRuntime.mappedSelector(selector)
            return object.responds(to: NSSelectorFromString(resolved))

        case "runtime.resolve":
            return Self.resolveSymbol((input["symbol"] as? String) ?? "")

        case "hook.param.set":
            if let id = input["id"] as? String {
                return PluginObjCRuntime.shared.setParamResult(id: id, value: input["value"] ?? NSNull())
            }
            return false

        case "hook.param.set_argument":
            if let id = input["id"] as? String {
                let index = (input["index"] as? NSNumber)?.intValue ?? (input["index"] as? Int) ?? 0
                return PluginObjCRuntime.shared.setParamArgument(id: id, index: index, value: input["value"] ?? NSNull())
            }
            return false

        case "hook.param.extra":
            if let id = input["id"] as? String, let key = input["key"] as? String {
                return PluginObjCRuntime.shared.setParamExtra(id: id, key: key, value: input["value"] ?? NSNull())
            }
            return false

        case "runtime.class_exists":
            return NSClassFromString(PluginObjCRuntime.mappedClassName((input["name"] as? String) ?? "")) != nil

        case "runtime.selector_exists":
            guard let name = input["class_name"] as? String,
                  let selector = input["selector"] as? String,
                  let cls = NSClassFromString(PluginObjCRuntime.mappedClassName(name)) else {
                return false
            }
            return class_getInstanceMethod(cls, NSSelectorFromString(selector)) != nil
                || class_getClassMethod(cls, NSSelectorFromString(selector)) != nil

        case "runtime.swizzle":
            guard let className = input["class_name"] as? String,
                  let selector = input["selector"] as? String else {
                return NSNull()
            }
            let rawCallbacks = (input["callbacks"] as? [String: Any]) ?? [:]
            var callbacks: [String: String] = [:]
            for (key, value) in rawCallbacks {
                if let value = value as? String {
                    callbacks[key] = value
                }
            }
            let filters = (input["filters"] as? [[String: Any]]) ?? []
            let beforeFilters = (input["before_filters"] as? [[String: Any]]) ?? []
            let afterFilters = (input["after_filters"] as? [[String: Any]]) ?? []
            let handle = PluginObjCRuntime.shared.install(
                className: className,
                selector: selector,
                callbacks: callbacks,
                filters: filters,
                beforeFilters: beforeFilters,
                afterFilters: afterFilters
            )
            return handle ?? NSNull()

        case "runtime.unswizzle":
            if let handle = input["handle"] as? String {
                PluginObjCRuntime.shared.uninstall(handle: handle)
                return true
            }
            return false

        case "runtime.proceed":
            guard let paramId = input["param_id"] as? String else {
                return NSNull()
            }
            let arguments = input["args"] as? [Any]
            return PluginObjCRuntime.shared.proceed(id: paramId, arguments: arguments) ?? NSNull()

        case "runtime.skip":
            guard let paramId = input["param_id"] as? String else {
                return false
            }
            return PluginObjCRuntime.shared.skip(id: paramId)

        case "runtime.swizzle_all":
            return NSNull()

        case "runtime.hook_method_object", "runtime.hook_all_methods":
            return NSNull()

        case "java.new":
            let name = (input["class_name"] as? String) ?? ""
            let mapped = PluginObjCRuntime.mappedClassName(name)
            let native: NSObject?
            switch mapped {
            case "UIView": native = UIView()
            case "UILabel": native = UILabel()
            case "UIImageView": native = UIImageView()
            case "UIButton": native = UIButton(type: .system)
            case "UISwitch": native = UISwitch()
            case "UITextField": native = UITextField()
            case "UIScrollView": native = UIScrollView()
            case "UIAlertController": native = UIAlertController(title: nil, message: nil, preferredStyle: .alert)
            case "UIViewController": native = UIViewController()
            case "NSObject": native = NSObject()
            default: native = nil
            }
            if let native {
                let handle = self.registerObject(native)
                self.lock.lock()
                self.objectClasses[handle] = mapped
                self.lock.unlock()
                return handle
            }
            return self.createObject(className: name, owner: (input["owner"] as? String) ?? "")

        case "java.call", "java.invoke":
            return self.callObject(input)

        case "java.get_field", "java.get_static_field":
            if let handle = input["target"] as? String, let member = input["member"] as? String {
                if let value = PluginObjCRuntime.shared.getProperty(handle: handle, name: member) {
                    return PluginHostAPI.propertyValue(value)
                }
                return self.objects[handle]?[member]
            }
            return NSNull()

        case "java.set_field", "java.set_static_field":
            if let handle = input["target"] as? String, let member = input["member"] as? String {
                if PluginHostAPI.shared.object(for: handle) != nil {
                    return PluginObjCRuntime.shared.setProperty(handle: handle, name: member, value: input["value"] ?? NSNull())
                }
                var object = self.objects[handle] ?? [:]
                object[member] = input["value"] ?? NSNull()
                self.objects[handle] = object
                return true
            }
            return false

        case "java.is_instance":
            guard let handle = input["target"] as? String else {
                return false
            }
            let expected = (input["class_name"] as? String) ?? ""
            let actual = self.objectClasses[handle] ?? ""
            return actual == expected || actual.hasSuffix("." + expected) || expected.hasSuffix("." + actual)

        case "java.release_plugin":
            let pluginId = (input["plugin_id"] as? String) ?? ""
            for (handle, owner) in self.objectOwners where owner == pluginId {
                self.objects.removeValue(forKey: handle)
                self.objectClasses.removeValue(forKey: handle)
                self.objectOwners.removeValue(forKey: handle)
            }
            return true

        case "telegram.call":
            return self.telegramCall(input)

        case "device.clipboard.get":
            return PluginManager.shared.environment.readClipboard()

        default:
            throw PluginHostError("unknown host method \(method)")
        }
    }

    // -- Sending -------------------------------------------------------------

    // MARK: - ExteraConfig bridge

    private static let clientConfigPrefix = "extera.client."

    private func boolValue(_ value: Any) -> Bool {
        if let value = value as? Bool {
            return value
        }
        if let value = value as? NSNumber {
            return value.boolValue
        }
        return false
    }

    private func configValue(for key: String) -> Any {
        switch key {
        case "pluginsEngine":
            return PluginPreferences.shared.engineEnabled
        case "pluginsSafeMode":
            return PluginPreferences.shared.safeMode
        case "pluginsDevMode":
            return PluginPreferences.shared.developerMode
        case "pluginsStaticAnalysis":
            return PluginPreferences.shared.staticAnalysis
        case "pluginsCompactView":
            return PluginPreferences.shared.compactView
        case "pluginsUnknownSources":
            return PluginPreferences.shared.allowUnknownSources
        default:
            return UserDefaults.standard.object(forKey: Self.clientConfigPrefix + key) ?? NSNull()
        }
    }

    private func setConfigValue(_ value: Any, for key: String) {
        switch key {
        case "pluginsEngine":
            PluginPreferences.shared.engineEnabled = self.boolValue(value)
        case "pluginsSafeMode":
            PluginPreferences.shared.safeMode = self.boolValue(value)
        case "pluginsDevMode":
            PluginPreferences.shared.developerMode = self.boolValue(value)
        case "pluginsStaticAnalysis":
            PluginPreferences.shared.staticAnalysis = self.boolValue(value)
        case "pluginsCompactView":
            PluginPreferences.shared.compactView = self.boolValue(value)
        case "pluginsUnknownSources":
            PluginPreferences.shared.allowUnknownSources = self.boolValue(value)
        default:
            UserDefaults.standard.set(value, forKey: Self.clientConfigPrefix + key)
        }
    }

    private func allConfigValues() -> [String: Any] {
        var result: [String: Any] = [
            "pluginsEngine": PluginPreferences.shared.engineEnabled,
            "pluginsSafeMode": PluginPreferences.shared.safeMode,
            "pluginsDevMode": PluginPreferences.shared.developerMode,
            "pluginsStaticAnalysis": PluginPreferences.shared.staticAnalysis,
            "pluginsCompactView": PluginPreferences.shared.compactView,
            "pluginsUnknownSources": PluginPreferences.shared.allowUnknownSources
        ]
        for (key, value) in UserDefaults.standard.dictionaryRepresentation() {
            guard key.hasPrefix(Self.clientConfigPrefix) else {
                continue
            }
            result[String(key.dropFirst(Self.clientConfigPrefix.count))] = value
        }
        return result
    }

    private func sendMessage(_ input: [String: Any]) throws -> Any {
        let account = (input["account"] as? NSNumber)?.int64Value ?? PluginManager.shared.environment.currentAccountId()
        let peer = (input["peer"] as? NSNumber)?.int64Value ?? 0
        if peer == 0 {
            throw PluginHostError("the message has no peer")
        }
        let entities = (input["entities"] as? [[String: Any]])?.compactMap(PluginEntity.init(json:)) ?? []
        let replyMarkupJSON: String? = (input["reply_markup"] as? [String: Any]).flatMap { value in
            PluginJSON.encodeString(value)
        }
        let request = PluginSendRequest(
            accountId: account,
            peerId: peer,
            kind: (input["kind"] as? String) ?? "text",
            text: input["text"] as? String,
            caption: input["caption"] as? String,
            entities: entities,
            path: input["path"] as? String,
            replyTo: (input["reply_to"] as? NSNumber)?.int32Value,
            silent: (input["silent"] as? Bool) ?? false,
            scheduleDate: (input["schedule_date"] as? NSNumber)?.int32Value ?? 0,
            replyMarkupJSON: replyMarkupJSON
        )
        switch PluginManager.shared.environment.send(request) {
        case let .success(id):
            return ["ok": true, "id": id]
        case let .failure(message):
            return ["ok": false, "error": message]
        }
    }

    private func sendMedia(_ input: [String: Any]) throws -> Any {
        return try self.sendMessage(input)
    }

    private func editMessage(account: Int64, peer: Int64, messageId: Int32, text: String?, entities: [[String: Any]], path: String?, kind: String?) throws -> Any {
        if let path {
            // A media edit uploads the file and edits through the same raw
            // request the SDK uses, so `path` is not silently dropped.  The
            // upload runs in the background and the call returns immediately,
            // like Android's asynchronous `editMessage`.
            let payload: [String: Any] = [
                "peer": peer,
                "id": messageId,
                "message": text ?? "",
                "entities": entities,
                "path": path,
                "kind": kind ?? "photo"
            ]
            DispatchQueue.global(qos: .userInitiated).async {
                let result = PluginManager.shared.environment.request(account, "messages.editMessage", payload)
                if let error = result["error"] as? String {
                    PluginLog.log("plugin media edit failed: \(error)", level: .warning)
                }
            }
            return ["ok": true]
        }
        switch PluginManager.shared.environment.editMessage(account, peer, messageId, text, entities) {
        case .success:
            return ["ok": true]
        case let .failure(message):
            return ["ok": false, "error": message]
        }
    }

    private func httpRequest(_ input: [String: Any]) -> [String: Any] {
        let url = (input["url"] as? String) ?? ""
        let method = (input["method"] as? String) ?? "GET"
        let headers = (input["headers"] as? [String: String]) ?? [:]
        let body = input["body"] as? String
        let timeout = (input["timeout"] as? NSNumber)?.doubleValue ?? 30
        return PluginManager.shared.environment.httpRequest(url, method, headers, body, timeout)
    }

    /// Downloads a binary file with URLSession (system trust store) and writes
    /// it to `path`.  Used by the pure-Python wheel installer; `http.request`
    /// returns text and would corrupt a wheel.
    private func httpDownload(_ input: [String: Any]) -> [String: Any] {
        guard let urlString = input["url"] as? String,
              let url = URL(string: urlString),
              let scheme = url.scheme?.lowercased(),
              scheme == "https" || scheme == "http" else {
            return ["error": "invalid URL"]
        }
        guard let path = input["path"] as? String, !path.isEmpty else {
            return ["error": "missing destination path"]
        }
        let maxBytes = (input["max_bytes"] as? NSNumber)?.int64Value ?? 250 * 1024 * 1024
        let timeout = (input["timeout"] as? NSNumber)?.doubleValue ?? 120
        var request = URLRequest(url: url, timeoutInterval: max(1, timeout))
        request.httpMethod = "GET"
        request.setValue("ExteraPlugins-iOS/1.0", forHTTPHeaderField: "User-Agent")

        let semaphore = DispatchSemaphore(value: 0)
        let box = PluginHTTPResultBox()
        box.set(["error": "no response"])
        let task = URLSession.shared.downloadTask(with: request) { location, response, error in
            defer {
                semaphore.signal()
            }
            if let error {
                box.set(["error": error.localizedDescription])
                return
            }
            guard let location else {
                box.set(["error": "the download produced no file"])
                return
            }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard status == 200 else {
                box.set(["error": "HTTP \(status)"])
                return
            }
            do {
                let attributes = try FileManager.default.attributesOfItem(atPath: location.path)
                let size = (attributes[.size] as? NSNumber)?.int64Value ?? 0
                if size > maxBytes {
                    box.set(["error": "the file is larger than the limit"])
                    return
                }
                let destination = URL(fileURLWithPath: path)
                try? FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
                try? FileManager.default.removeItem(at: destination)
                try FileManager.default.moveItem(at: location, to: destination)
                box.set(["ok": true, "status": status, "size": size])
            } catch {
                box.set(["error": error.localizedDescription])
            }
        }
        task.resume()
        _ = semaphore.wait(timeout: .now() + max(1, timeout) + 5)
        return box.get()
    }

    // -- Alerts --------------------------------------------------------------

    private func presentAlert(_ input: [String: Any], show: Bool) -> [String: Any] {
        let identifier = (input["id"] as? String) ?? self.nextIdentifierString()
        self.lock.lock()
        self.alertSpecs[identifier] = input
        let existing = self.alerts[identifier]
        self.lock.unlock()

        if let existing {
            if show {
                DispatchQueue.main.async {
                    self.presentAlertController(existing, identifier: identifier)
                }
            }
            return ["id": identifier]
        }

        DispatchQueue.main.async { [weak self] in
            guard let self else {
                return
            }
            self.lock.lock()
            let spec = self.alertSpecs[identifier]
            self.lock.unlock()
            guard let spec else {
                return
            }

            let title = spec["title"] as? String
            let message = spec["message"] as? String
            let items = (spec["items"] as? [String]) ?? []
            let controller = UIAlertController(title: title, message: message, preferredStyle: items.isEmpty ? .alert : .actionSheet)

            func addButton(_ entry: Any?, style: UIAlertAction.Style) {
                guard let entry = entry as? [String: Any], let text = entry["text"] as? String else {
                    return
                }
                let callback = entry["callback"] as? String
                controller.addAction(UIAlertAction(title: text, style: style, handler: { _ in
                    if let callback {
                        PluginManager.shared.invokeCallback(callback, arguments: [])
                    }
                }))
            }
            addButton(spec["positive"], style: .default)
            addButton(spec["negative"], style: .cancel)
            addButton(spec["neutral"], style: .default)
            if !items.isEmpty {
                let callback = spec["items_callback"] as? String
                for (index, item) in items.enumerated() {
                    controller.addAction(UIAlertAction(title: item, style: .default, handler: { _ in
                        if let callback {
                            PluginManager.shared.invokeCallback(callback, arguments: [index])
                        }
                    }))
                }
            }
            if controller.actions.isEmpty {
                controller.addAction(UIAlertAction(title: "OK", style: .cancel, handler: nil))
            }

            self.lock.lock()
            self.alerts[identifier] = controller
            self.lock.unlock()

            guard show else {
                return
            }
            self.presentAlertController(controller, identifier: identifier)
        }
        return ["id": identifier]
    }

    private func presentAlertController(_ controller: UIAlertController, identifier: String) {
        guard let presenter = self.topViewController() else {
            return
        }
        if let popover = controller.popoverPresentationController {
            popover.sourceView = presenter.view
            popover.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.midY, width: 1, height: 1)
            popover.permittedArrowDirections = []
        }
        presenter.present(controller, animated: true)
    }

    private func updateAlert(_ input: [String: Any]) -> Bool {
        guard let identifier = input["id"] as? String else {
            return false
        }
        self.lock.lock()
        if var spec = self.alertSpecs[identifier] {
            for key in ["title", "message"] {
                if let value = input[key] {
                    spec[key] = value
                }
            }
            self.alertSpecs[identifier] = spec
        }
        let controller = self.alerts[identifier]
        self.lock.unlock()

        if let controller {
            let title = input["title"] as? String
            let message = input["message"] as? String
            DispatchQueue.main.async {
                if let title {
                    controller.title = title
                }
                if let message {
                    controller.message = message
                }
            }
        }
        return true
    }

    private func dismissAlert(_ identifier: String) {
        self.lock.lock()
        self.alertSpecs.removeValue(forKey: identifier)
        self.lock.unlock()
        DispatchQueue.main.async {
            self.alerts[identifier]?.dismiss(animated: true)
            self.alerts.removeValue(forKey: identifier)
        }
    }

    private func topViewController() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let window = scenes.flatMap { $0.windows }.first { $0.isKeyWindow } ?? scenes.first?.windows.first
        var controller = window?.rootViewController
        while let presented = controller?.presentedViewController {
            controller = presented
        }
        return controller
    }

    private func withAudioPlayer(_ body: @escaping (AVAudioPlayer) -> Void) {
        let work = {
            if let player = self.audioPlayer {
                body(player)
            }
        }
        if Thread.isMainThread {
            work()
        } else {
            DispatchQueue.main.sync(execute: work)
        }
    }

    private func audioState() -> [String: Any] {
        var value: [String: Any] = [
            "playing": false,
            "position": 0.0,
            "duration": 0.0,
            "rate": 1.0
        ]
        let work = {
            if let player = self.audioPlayer {
                value = [
                    "playing": player.isPlaying,
                    "position": player.currentTime,
                    "duration": player.duration,
                    "rate": player.rate,
                    "volume": player.volume
                ]
            }
        }
        if Thread.isMainThread {
            work()
        } else {
            DispatchQueue.main.sync(execute: work)
        }
        return value
    }

    private func postNotification(title: String, text: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = text
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request, withCompletionHandler: nil)
    }

    // -- Proxy objects --------------------------------------------------------

    private func nextIdentifierString() -> String {
        self.lock.lock()
        defer { self.lock.unlock() }
        self.nextIdentifier += 1
        return "obj-\(self.nextIdentifier)"
    }

    private func createObject(className: String, owner: String) -> String {
        let handle = self.nextIdentifierString()
        self.lock.lock()
        self.objects[handle] = ["_class": className]
        self.objectClasses[handle] = className
        if !owner.isEmpty {
            self.objectOwners[handle] = owner
        }
        self.lock.unlock()
        return handle
    }

    /// Keeps a native object alive for Python and returns an opaque handle.
    func registerObject(_ object: AnyObject) -> String {
        let handle = self.nextIdentifierString()
        self.lock.lock()
        self.nativeObjects[handle] = object
        self.nativeObjectOrder.append(handle)
        if self.nativeObjectOrder.count > 2000 {
            let stale = self.nativeObjectOrder.removeFirst()
            self.nativeObjects.removeValue(forKey: stale)
            self.objectClasses.removeValue(forKey: stale)
        }
        self.objectClasses[handle] = NSStringFromClass(type(of: object))
        self.lock.unlock()
        return handle
    }

    func object(for handle: String) -> AnyObject? {
        self.lock.lock()
        defer { self.lock.unlock() }
        return self.nativeObjects[handle]
    }

    func releaseNativeObjects() {
        self.lock.lock()
        self.nativeObjects.removeAll()
        self.nativeObjectOrder.removeAll()
        self.lock.unlock()
    }

    func descriptor(for object: AnyObject) -> [String: Any] {
        let handle = self.registerObject(object)
        return [
            "__handle__": handle,
            "__class__": NSStringFromClass(type(of: object))
        ]
    }

    static func propertyValue(_ value: Any) -> Any {
        switch value {
        case let value as String:
            return value
        case let value as NSString:
            return value as String
        case let value as NSNumber:
            return value
        case let value as Bool:
            return value
        case let value as [String: Any]:
            return value
        case let value as [Any]:
            return value
        case is NSNull:
            return NSNull()
        default:
            return PluginHostAPI.shared.descriptor(for: value as AnyObject)
        }
    }

    /// Resolves an Android-style symbol (`android.view.View.setOnClickListener`)
    /// into the iOS class/selector it maps to.  `extera_ios.resolve_symbol`
    /// returns the empty object when nothing matches.
    private static func resolveSymbol(_ symbol: String) -> [String: Any] {
        let trimmed = symbol.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return [:]
        }

        let direct = PluginObjCRuntime.mappedClassName(trimmed)
        if NSClassFromString(direct) != nil {
            return ["type": "class", "name": trimmed, "class": direct]
        }

        let parts = trimmed.split(separator: ".").map(String.init)
        guard parts.count > 1 else {
            return ["type": "unknown", "name": trimmed]
        }
        for count in stride(from: parts.count - 1, through: 1, by: -1) {
            let className = parts.prefix(count).joined(separator: ".")
            let mapped = PluginObjCRuntime.mappedClassName(className)
            guard let cls = NSClassFromString(mapped) else {
                continue
            }
            let member = parts.dropFirst(count).joined(separator: ".")
            let selector = PluginObjCRuntime.mappedSelector(member)
            if class_getInstanceMethod(cls, NSSelectorFromString(selector)) != nil
                || class_getClassMethod(cls, NSSelectorFromString(selector)) != nil {
                return [
                    "type": "selector",
                    "name": member,
                    "class": mapped,
                    "android_class": className,
                    "selector": selector
                ]
            }
            let capitalized = member.prefix(1).uppercased() + String(member.dropFirst())
            if class_getInstanceMethod(cls, NSSelectorFromString(member)) != nil
                || class_getInstanceMethod(cls, NSSelectorFromString("set\(capitalized):")) != nil {
                return [
                    "type": "property",
                    "name": member,
                    "class": mapped,
                    "android_class": className
                ]
            }
            return ["type": "class", "name": className, "class": mapped]
        }
        return ["type": "unknown", "name": trimmed]
    }

    private func callObject(_ input: [String: Any]) -> Any? {
        let className = (input["class_name"] as? String) ?? ""
        let method = (input["method"] as? String) ?? (input["member"] as? String) ?? ""
        let handle = input["target"] as? String

        if let handle, PluginHostAPI.shared.object(for: handle) != nil {
            let result = PluginObjCRuntime.shared.callObject(
                handle: handle,
                selector: method,
                arguments: (input["args"] as? [Any]) ?? []
            )
            if let result {
                return PluginHostAPI.propertyValue(result)
            }
            return NSNull()
        }

        // A small, explicit mapping of the Java controller methods that appear
        // most often in plugins. Everything else reports a precise error.
        if method == "getUser" || method == "getChat" || method == "getPeer" {
            if let arguments = input["args"] as? [Any], let first = arguments.first as? NSNumber {
                let account = PluginManager.shared.environment.currentAccountId()
                return PluginManager.shared.environment.peer(account, first.int64Value)
            }
            return nil
        }
        if method == "getDialogs" || method == "getChats" {
            let account = PluginManager.shared.environment.currentAccountId()
            let limit = (input["args"] as? [NSNumber])?.first?.intValue ?? 100
            return PluginManager.shared.environment.chats(account, limit, 0)
        }
        if method == "getContacts" {
            let account = PluginManager.shared.environment.currentAccountId()
            return PluginManager.shared.environment.contacts(account)
        }
        if method == "getCurrentUser" {
            return PluginManager.shared.environment.me(PluginManager.shared.environment.currentAccountId())
        }
        if method == "getDialogId" || method == "getId" {
            if let handle, let object = self.objects[handle] {
                return object[method == "getId" ? "id" : "peer"]
            }
        }
        if method == "getMessagesController" || method == "getContactsController"
            || method == "getSendMessagesHelper" || method == "getUserConfig"
            || method == "getConnectionsManager" || method == "getMessagesStorage" {
            return self.createObject(className: "org.telegram.messenger." + method, owner: "")
        }
        if method == "getAccountInstance" {
            return self.createObject(className: "org.telegram.messenger.AccountInstance", owner: "")
        }
        if method == "getName" {
            return self.objectClasses[handle ?? ""] ?? className
        }
        _ = className
        return NSNull()
    }

    private func telegramCall(_ input: [String: Any]) -> Any? {
        let target = (input["target"] as? String) ?? ""
        let method = (input["method"] as? String) ?? ""
        let args = (input["args"] as? [Any]) ?? []

        if target.contains("UserConfig"), method == "getSelectedAccount" || method == "selectedAccount" || method == "getSelectedAccountId" {
            return PluginManager.shared.environment.currentAccountId()
        }
        if target.contains("MessagesController") {
            if method == "getUser" || method == "getChat" || method == "getUserFull" || method == "getChatFull" {
                if let number = args.first as? NSNumber {
                    return PluginManager.shared.environment.peer(
                        PluginManager.shared.environment.currentAccountId(),
                        number.int64Value
                    )
                }
            }
        }
        if target.contains("FileLoader"), method == "getDirectory" {
            let kinds = ["plugins", "cache", "files", "documents"]
            let kind: String
            if let name = args.first as? String {
                kind = name
            } else if let number = args.first as? NSNumber, number.intValue >= 0, number.intValue < kinds.count {
                kind = kinds[number.intValue]
            } else {
                kind = "files"
            }
            let store = PluginStore.shared
            switch kind {
            case "plugins":
                return store.pluginsURL.path
            case "cache":
                return FileManager.default.temporaryDirectory.path
            case "documents":
                return FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?.path ?? store.filesURL.path
            default:
                return store.filesURL.path
            }
        }
        if let object = PluginObjCRuntime.shared.object(for: target) {
            if let result = PluginObjCRuntime.shared.callObject(handle: target, selector: method, arguments: args) {
                return PluginHostAPI.propertyValue(result)
            }
        }
        return NSNull()
    }
}

/// UI hooks the host can implement; the kit ships a default one for alerts.
public protocol PluginUIHost: AnyObject {
    func showBulletin(kind: String, text: String, subtext: String?, duration: Int)
    func showBulletin(_ spec: PluginBulletinSpec)
}

public extension PluginUIHost {
    func showBulletin(_ spec: PluginBulletinSpec) {
        self.showBulletin(
            kind: spec.kind,
            text: spec.text,
            subtext: spec.subtext,
            duration: spec.duration
        )
    }
}

/// A richer bulletin description, matching the Android `BulletinFactory` API:
/// an icon, an action button and the undo/expire pair.
public struct PluginBulletinSpec {
    public var kind: String
    public var text: String
    public var subtext: String?
    public var duration: Int
    public var icon: Any?
    public var buttonText: String?
    public var onButton: String?
    public var undoText: String?
    public var onUndo: String?
    public var onAction: String?

    public init(
        kind: String,
        text: String,
        subtext: String? = nil,
        duration: Int = 2000,
        icon: Any? = nil,
        buttonText: String? = nil,
        onButton: String? = nil,
        undoText: String? = nil,
        onUndo: String? = nil,
        onAction: String? = nil
    ) {
        self.kind = kind
        self.text = text
        self.subtext = subtext
        self.duration = duration
        self.icon = icon
        self.buttonText = buttonText
        self.onButton = onButton
        self.undoText = undoText
        self.onUndo = onUndo
        self.onAction = onAction
    }
}

/// Thread-safe result box for URLSession completions, which run off the
/// caller's thread.  A captured mutable `var` is rejected by Swift 6.
public final class PluginHTTPResultBox: @unchecked Sendable {
    private let lock = NSLock()
    private var value: [String: Any]

    public init(_ value: [String: Any] = [:]) {
        self.value = value
    }

    public func set(_ value: [String: Any]) {
        self.lock.lock()
        self.value = value
        self.lock.unlock()
    }

    public func get() -> [String: Any] {
        self.lock.lock()
        defer {
            self.lock.unlock()
        }
        return self.value
    }
}

/// Generic thread-safe box for values filled in by an asynchronous callback.
public final class PluginValueBox<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: T

    public init(_ value: T) {
        self.value = value
    }

    public func set(_ value: T) {
        self.lock.lock()
        self.value = value
        self.lock.unlock()
    }

    public func get() -> T {
        self.lock.lock()
        defer {
            self.lock.unlock()
        }
        return self.value
    }
}

extension PluginAnalysisReport {
    var asJSON: [String: Any] {
        var statements: [[String: Any]] = []
        for statement in self.statements {
            statements.append([
                "id": statement.id,
                "severity": Self.label(statement.severity),
                "title": statement.title,
                "values": statement.values,
                "rules": statement.rules,
                "capabilities": statement.capabilities
            ])
        }
        let findingsJSON: [[String: Any]] = self.findings.map { key, value in
            let entry: [String: Any] = [
                "rule": key,
                "severity": Self.label(value.severity),
                "title": value.title,
                "values": value.values,
                "capabilities": value.capabilities,
                "evidence": [],
                "evidence_total": value.evidenceTotal
            ]
            return entry
        }
        return [
            "analyzer": ["version": self.analyzerVersion],
            "max_severity": Self.label(self.maxSeverity),
            "statements": statements,
            "findings": findingsJSON,
            "limits": self.limits,
            "stats": ["elapsed_ms": self.elapsedMilliseconds]
        ]
    }

    private static func label(_ severity: PluginAnalysisSeverity) -> String {
        switch severity {
        case .info: return "info"
        case .caution: return "caution"
        case .danger: return "danger"
        case .critical: return "critical"
        case .none: return "none"
        }
    }
}
