import Foundation

/// Client-side settings that exteraGram exposes in addition to the plugin SDK.
///
/// The keys intentionally use the Android preference names with an `extera.client.`
/// prefix.  This keeps one source of truth for the settings screen, the network
/// layer and the Python `ExteraConfig` facade: a plugin that writes
/// `ExteraConfig.downloadSpeedBoost` changes the same value the UI reads.
public final class ExteraSettings {
    public static let shared = ExteraSettings()

    public static let didChange = Notification.Name("ExteraSettingsDidChange")

    private let defaults = UserDefaults.standard

    private enum Key {
        static let prefix = "extera.client."

        static let disableNumberRounding = prefix + "disableNumberRounding"
        static let formatTimeWithSeconds = prefix + "formatTimeWithSeconds"
        static let relativeLastSeen = prefix + "relativeLastSeen"
        static let filterZalgo = prefix + "filterZalgo"
        static let hidePhoneNumber = prefix + "hidePhoneNumber"
        static let showIdAndDc = prefix + "showIdAndDc"
        static let defaultProfileTab = prefix + "defaultProfileTab"
        static let hideArchiveFolder = prefix + "hideArchiveFolder"
        static let disableUnarchiveSwipe = prefix + "disableUnarchiveSwipe"
        static let hideStories = prefix + "hideStories"
        static let tabIcons = prefix + "tabIcons"
        static let hideNavigationBarLabels = prefix + "hideNavigationBarLabels"
        static let replyBackground = prefix + "replyBackground"
        static let replyColors = prefix + "replyColors"
        static let replyEmoji = prefix + "replyEmoji"
        static let tabCounterMode = prefix + "tabCounterMode"
        static let hideShareButton = prefix + "hideShareButton"
        static let showSaveMessageButton = prefix + "showSaveMessageButton"
        static let showCopyPhotoButton = prefix + "showCopyPhotoButton"
        static let showReportButton = prefix + "showReportButton"
        static let showClearButton = prefix + "showClearButton"
        static let replaceEditedWithIcon = prefix + "replaceEditedWithIcon"
        static let disableGreetingSticker = prefix + "disableGreetingSticker"
        static let hideSendAsPeer = prefix + "hideSendAsPeer"
        static let addCommaAfterMention = prefix + "addCommaAfterMention"
        static let hideKeyboardOnScroll = prefix + "hideKeyboardOnScroll"
        static let stickerTimeMode = prefix + "stickerTimeMode"
        static let stickerSize = prefix + "stickerSize"
        static let stickerShape = prefix + "stickerShape"
        static let doubleTapSeekDuration = prefix + "doubleTapSeekDuration"
        static let hideReactionsInPrivateChats = prefix + "hideReactionsInPrivateChats"
        static let hideReactionsInChannels = prefix + "hideReactionsInChannels"
        static let hideReactionsInGroups = prefix + "hideReactionsInGroups"
        static let showOnlineStatus = prefix + "showOnlineStatus"
        static let hideFloatingButton = prefix + "hideFloatingButton"
        static let hideDialogsSearchBar = prefix + "hideDialogsSearchBar"
        static let centerTitle = prefix + "centerTitle"
        static let hideActionBarStatus = prefix + "hideActionBarStatus"
        static let downloadSpeedBoost = prefix + "downloadSpeedBoost"
        static let uploadSpeedBoost = prefix + "uploadSpeedBoost"
        static let enableAdBlock = prefix + "enableAdBlock"
        static let avatarCorners = prefix + "avatarCorners"
        static let newLoadingStyle = prefix + "newLoadingStyle"
        static let newSliderStyle = prefix + "newSliderStyle"
        static let newSwitchStyle = prefix + "newSwitchStyle"
        static let alwaysSendInHD = prefix + "alwaysSendInHD"
        static let cameraStabilization = prefix + "cameraStabilization"
        static let cameraMirrorMode = prefix + "cameraMirrorMode"
        static let extendedFramesPerSecond = prefix + "extendedFramesPerSecond"
        static let hideCameraTile = prefix + "hideCameraTile"
        static let disableNotificationDelay = prefix + "disableNotificationDelay"
        static let inAppVibration = prefix + "inAppVibration"
    }

    private init() {
    }

    private func bool(_ key: String, default defaultValue: Bool) -> Bool {
        if let value = self.defaults.object(forKey: key) as? Bool {
            return value
        }
        if let value = self.defaults.object(forKey: key) as? NSNumber {
            return value.boolValue
        }
        return defaultValue
    }

    private func integer(_ key: String, default defaultValue: Int) -> Int {
        if let value = self.defaults.object(forKey: key) as? Int {
            return value
        }
        if let value = self.defaults.object(forKey: key) as? NSNumber {
            return value.intValue
        }
        return defaultValue
    }

    private func double(_ key: String, default defaultValue: Double) -> Double {
        if let value = self.defaults.object(forKey: key) as? Double {
            return value
        }
        if let value = self.defaults.object(forKey: key) as? NSNumber {
            return value.doubleValue
        }
        return defaultValue
    }

    private func setBool(_ value: Bool, for key: String) {
        self.defaults.set(value, forKey: key)
        self.notifyChanged()
    }

    private func setInteger(_ value: Int, for key: String) {
        self.defaults.set(value, forKey: key)
        self.notifyChanged()
    }

    private func setDouble(_ value: Double, for key: String) {
        self.defaults.set(value, forKey: key)
        self.notifyChanged()
    }

    private func notifyChanged() {
        if Thread.isMainThread {
            NotificationCenter.default.post(name: Self.didChange, object: nil)
        } else {
            DispatchQueue.main.async {
                NotificationCenter.default.post(name: Self.didChange, object: nil)
            }
        }
    }

    // MARK: - General

    public var disableNumberRounding: Bool {
        get { return self.bool(Key.disableNumberRounding, default: false) }
        set { self.setBool(newValue, for: Key.disableNumberRounding) }
    }

    public var formatTimeWithSeconds: Bool {
        get { return self.bool(Key.formatTimeWithSeconds, default: false) }
        set { self.setBool(newValue, for: Key.formatTimeWithSeconds) }
    }

    public var relativeLastSeen: Bool {
        get { return self.bool(Key.relativeLastSeen, default: false) }
        set { self.setBool(newValue, for: Key.relativeLastSeen) }
    }

    public var filterZalgo: Bool {
        get { return self.bool(Key.filterZalgo, default: true) }
        set { self.setBool(newValue, for: Key.filterZalgo) }
    }

    public var hidePhoneNumber: Bool {
        get { return self.bool(Key.hidePhoneNumber, default: false) }
        set { self.setBool(newValue, for: Key.hidePhoneNumber) }
    }

    /// 0 = hidden, 1 = show id, 2 = show id and dc.
    public var showIdAndDc: Int {
        get { return self.integer(Key.showIdAndDc, default: 1) }
        set { self.setInteger(newValue, for: Key.showIdAndDc) }
    }

    /// 0 = default, 1 = media, 2 = common groups.
    public var defaultProfileTab: Int {
        get { return min(2, max(0, self.integer(Key.defaultProfileTab, default: 0))) }
        set { self.setInteger(min(2, max(0, newValue)), for: Key.defaultProfileTab) }
    }

    public var hideArchiveFolder: Bool {
        get { return self.bool(Key.hideArchiveFolder, default: false) }
        set { self.setBool(newValue, for: Key.hideArchiveFolder) }
    }

    public var disableUnarchiveSwipe: Bool {
        get { return self.bool(Key.disableUnarchiveSwipe, default: true) }
        set { self.setBool(newValue, for: Key.disableUnarchiveSwipe) }
    }

    // MARK: - Appearance

    public var hideStories: Bool {
        get { return self.bool(Key.hideStories, default: false) }
        set { self.setBool(newValue, for: Key.hideStories) }
    }

    /// 0 = icons and titles, 1 = titles only, 2 = icons only.
    public var tabIcons: Int {
        get { return min(2, max(0, self.integer(Key.tabIcons, default: 1))) }
        set { self.setInteger(min(2, max(0, newValue)), for: Key.tabIcons) }
    }

    public var hideNavigationBarLabels: Bool {
        get { return self.bool(Key.hideNavigationBarLabels, default: false) }
        set { self.setBool(newValue, for: Key.hideNavigationBarLabels) }
    }

    public var replyBackground: Bool {
        get { return self.bool(Key.replyBackground, default: true) }
        set { self.setBool(newValue, for: Key.replyBackground) }
    }

    public var replyColors: Bool {
        get { return self.bool(Key.replyColors, default: true) }
        set { self.setBool(newValue, for: Key.replyColors) }
    }

    public var replyEmoji: Bool {
        get { return self.bool(Key.replyEmoji, default: true) }
        set { self.setBool(newValue, for: Key.replyEmoji) }
    }

    /// 0 = all, 1 = unmuted, 2 = hidden.  iOS currently implements all/hidden.
    public var tabCounterMode: Int {
        get { return min(2, max(0, self.integer(Key.tabCounterMode, default: 0))) }
        set { self.setInteger(min(2, max(0, newValue)), for: Key.tabCounterMode) }
    }

    public var hideShareButton: Bool {
        get { return self.bool(Key.hideShareButton, default: true) }
        set { self.setBool(newValue, for: Key.hideShareButton) }
    }

    public var showSaveMessageButton: Bool {
        get { return self.bool(Key.showSaveMessageButton, default: false) }
        set { self.setBool(newValue, for: Key.showSaveMessageButton) }
    }

    public var showCopyPhotoButton: Bool {
        get { return self.bool(Key.showCopyPhotoButton, default: true) }
        set { self.setBool(newValue, for: Key.showCopyPhotoButton) }
    }

    public var showReportButton: Bool {
        get { return self.bool(Key.showReportButton, default: true) }
        set { self.setBool(newValue, for: Key.showReportButton) }
    }

    public var showClearButton: Bool {
        get { return self.bool(Key.showClearButton, default: true) }
        set { self.setBool(newValue, for: Key.showClearButton) }
    }

    public var replaceEditedWithIcon: Bool {
        get { return self.bool(Key.replaceEditedWithIcon, default: true) }
        set { self.setBool(newValue, for: Key.replaceEditedWithIcon) }
    }

    public var disableGreetingSticker: Bool {
        get { return self.bool(Key.disableGreetingSticker, default: false) }
        set { self.setBool(newValue, for: Key.disableGreetingSticker) }
    }

    public var hideSendAsPeer: Bool {
        get { return self.bool(Key.hideSendAsPeer, default: false) }
        set { self.setBool(newValue, for: Key.hideSendAsPeer) }
    }

    public var addCommaAfterMention: Bool {
        get { return self.bool(Key.addCommaAfterMention, default: true) }
        set { self.setBool(newValue, for: Key.addCommaAfterMention) }
    }

    public var hideKeyboardOnScroll: Bool {
        get { return self.bool(Key.hideKeyboardOnScroll, default: true) }
        set { self.setBool(newValue, for: Key.hideKeyboardOnScroll) }
    }

    public var stickerTimeMode: Int {
        get { return self.integer(Key.stickerTimeMode, default: 0) }
        set { self.setInteger(newValue, for: Key.stickerTimeMode) }
    }

    public var stickerSize: Double {
        get { return min(20.0, max(4.0, self.double(Key.stickerSize, default: 12.0))) }
        set { self.setDouble(min(20.0, max(4.0, newValue)), for: Key.stickerSize) }
    }

    public var stickerShape: Int {
        get { return min(2, max(0, self.integer(Key.stickerShape, default: 1))) }
        set { self.setInteger(min(2, max(0, newValue)), for: Key.stickerShape) }
    }

    public var doubleTapSeekDuration: Int {
        get { return min(3, max(0, self.integer(Key.doubleTapSeekDuration, default: 1))) }
        set { self.setInteger(min(3, max(0, newValue)), for: Key.doubleTapSeekDuration) }
    }

    public func doubleTapSeekDurationSeconds() -> Double {
        switch self.doubleTapSeekDuration {
        case 0: return 5.0
        case 1: return 10.0
        case 2: return 15.0
        default: return 30.0
        }
    }

    public func stickerSizeScale() -> Double {
        let denominator = 0.5 + (12.0 - 14.0) / 30.0
        return max(0.25, (0.5 + (self.stickerSize - 14.0) / 30.0) / denominator)
    }

    public var hideReactionsInPrivateChats: Bool {
        get { return self.bool(Key.hideReactionsInPrivateChats, default: false) }
        set { self.setBool(newValue, for: Key.hideReactionsInPrivateChats) }
    }

    public var hideReactionsInChannels: Bool {
        get { return self.bool(Key.hideReactionsInChannels, default: false) }
        set { self.setBool(newValue, for: Key.hideReactionsInChannels) }
    }

    public var hideReactionsInGroups: Bool {
        get { return self.bool(Key.hideReactionsInGroups, default: false) }
        set { self.setBool(newValue, for: Key.hideReactionsInGroups) }
    }

    public var showOnlineStatus: Bool {
        get { return self.bool(Key.showOnlineStatus, default: false) }
        set { self.setBool(newValue, for: Key.showOnlineStatus) }
    }

    public var hideFloatingButton: Bool {
        get { return self.bool(Key.hideFloatingButton, default: false) }
        set { self.setBool(newValue, for: Key.hideFloatingButton) }
    }

    public var hideDialogsSearchBar: Bool {
        get { return self.bool(Key.hideDialogsSearchBar, default: false) }
        set { self.setBool(newValue, for: Key.hideDialogsSearchBar) }
    }

    public var centerTitle: Bool {
        get { return self.bool(Key.centerTitle, default: false) }
        set { self.setBool(newValue, for: Key.centerTitle) }
    }

    public var hideActionBarStatus: Bool {
        get { return self.bool(Key.hideActionBarStatus, default: false) }
        set { self.setBool(newValue, for: Key.hideActionBarStatus) }
    }

    public var avatarCorners: Double {
        get { return self.double(Key.avatarCorners, default: 28.0) }
        set { self.setDouble(newValue, for: Key.avatarCorners) }
    }

    public var newLoadingStyle: Bool {
        get { return self.bool(Key.newLoadingStyle, default: true) }
        set { self.setBool(newValue, for: Key.newLoadingStyle) }
    }

    public var newSliderStyle: Bool {
        get { return self.bool(Key.newSliderStyle, default: true) }
        set { self.setBool(newValue, for: Key.newSliderStyle) }
    }

    public var newSwitchStyle: Bool {
        get { return self.bool(Key.newSwitchStyle, default: true) }
        set { self.setBool(newValue, for: Key.newSwitchStyle) }
    }

    // MARK: - Network and media

    /// 0 = off, 1 = fast (512 KiB / 8 parts), 2 = ultra (1 MiB / 12 parts).
    public var downloadSpeedBoost: Int {
        get { return min(2, max(0, self.integer(Key.downloadSpeedBoost, default: 0))) }
        set { self.setInteger(min(2, max(0, newValue)), for: Key.downloadSpeedBoost) }
    }

    public var uploadSpeedBoost: Bool {
        get { return self.bool(Key.uploadSpeedBoost, default: false) }
        set { self.setBool(newValue, for: Key.uploadSpeedBoost) }
    }

    public var enableAdBlock: Bool {
        get { return self.bool(Key.enableAdBlock, default: true) }
        set { self.setBool(newValue, for: Key.enableAdBlock) }
    }

    public var alwaysSendInHD: Bool {
        get { return self.bool(Key.alwaysSendInHD, default: true) }
        set { self.setBool(newValue, for: Key.alwaysSendInHD) }
    }

    public var cameraStabilization: Bool {
        get { return self.bool(Key.cameraStabilization, default: false) }
        set { self.setBool(newValue, for: Key.cameraStabilization) }
    }

    public var cameraMirrorMode: Bool {
        get { return self.bool(Key.cameraMirrorMode, default: true) }
        set { self.setBool(newValue, for: Key.cameraMirrorMode) }
    }

    public var extendedFramesPerSecond: Bool {
        get { return self.bool(Key.extendedFramesPerSecond, default: false) }
        set { self.setBool(newValue, for: Key.extendedFramesPerSecond) }
    }

    public var hideCameraTile: Bool {
        get { return self.bool(Key.hideCameraTile, default: false) }
        set { self.setBool(newValue, for: Key.hideCameraTile) }
    }

    public var disableNotificationDelay: Bool {
        get { return self.bool(Key.disableNotificationDelay, default: false) }
        set { self.setBool(newValue, for: Key.disableNotificationDelay) }
    }

    public var inAppVibration: Bool {
        get { return self.bool(Key.inAppVibration, default: true) }
        set { self.setBool(newValue, for: Key.inAppVibration) }
    }

    /// Removes long runs of combining marks (zalgo) while keeping normal
    /// accents.  Runs of up to two marks are preserved.
    public static func filterZalgoText(_ text: String) -> String {
        var result = String.UnicodeScalarView()
        var combiningRun = 0
        for scalar in text.unicodeScalars {
            switch scalar.properties.generalCategory {
            case .nonspacingMark, .enclosingMark:
                combiningRun += 1
                if combiningRun > 2 {
                    continue
                }
            default:
                combiningRun = 0
            }
            result.append(scalar)
        }
        return String(result)
    }

    // MARK: - Plugin-facing helpers

    /// Reads a value by its Android `ExteraConfig` name.  Returns `nil` when the
    /// setting has never been written, so the Python facade can apply the
    /// Android default.
    public func value(forAndroidKey key: String) -> Any? {
        switch key {
        case "disableNumberRounding": return self.disableNumberRounding
        case "formatTimeWithSeconds": return self.formatTimeWithSeconds
        case "relativeLastSeen": return self.relativeLastSeen
        case "filterZalgo": return self.filterZalgo
        case "hidePhoneNumber": return self.hidePhoneNumber
        case "showIdAndDc": return self.showIdAndDc
        case "defaultProfileTab": return self.defaultProfileTab
        case "hideArchiveFolder": return self.hideArchiveFolder
        case "disableUnarchiveSwipe": return self.disableUnarchiveSwipe
        case "hideStories": return self.hideStories
        case "tabIcons": return self.tabIcons
        case "hideNavigationBarLabels": return self.hideNavigationBarLabels
        case "replyBackground": return self.replyBackground
        case "replyColors": return self.replyColors
        case "replyEmoji": return self.replyEmoji
        case "tabCounterMode": return self.tabCounterMode
        case "hideShareButton": return self.hideShareButton
        case "showSaveMessageButton": return self.showSaveMessageButton
        case "showCopyPhotoButton": return self.showCopyPhotoButton
        case "showReportButton": return self.showReportButton
        case "showClearButton": return self.showClearButton
        case "replaceEditedWithIcon": return self.replaceEditedWithIcon
        case "disableGreetingSticker": return self.disableGreetingSticker
        case "hideSendAsPeer": return self.hideSendAsPeer
        case "addCommaAfterMention": return self.addCommaAfterMention
        case "hideKeyboardOnScroll": return self.hideKeyboardOnScroll
        case "stickerTimeMode": return self.stickerTimeMode
        case "stickerSize": return self.stickerSize
        case "stickerShape": return self.stickerShape
        case "doubleTapSeekDuration": return self.doubleTapSeekDuration
        case "hideReactionsInPrivateChats": return self.hideReactionsInPrivateChats
        case "hideReactionsInChannels": return self.hideReactionsInChannels
        case "hideReactionsInGroups": return self.hideReactionsInGroups
        case "showOnlineStatus": return self.showOnlineStatus
        case "hideFloatingButton": return self.hideFloatingButton
        case "hideDialogsSearchBar": return self.hideDialogsSearchBar
        case "centerTitle": return self.centerTitle
        case "hideActionBarStatus": return self.hideActionBarStatus
        case "downloadSpeedBoost": return self.downloadSpeedBoost
        case "uploadSpeedBoost": return self.uploadSpeedBoost
        case "enableAdBlock": return self.enableAdBlock
        case "avatarCorners": return self.avatarCorners
        case "newLoadingStyle": return self.newLoadingStyle
        case "newSliderStyle": return self.newSliderStyle
        case "newSwitchStyle": return self.newSwitchStyle
        case "alwaysSendInHD": return self.alwaysSendInHD
        case "cameraStabilization": return self.cameraStabilization
        case "cameraMirrorMode": return self.cameraMirrorMode
        case "extendedFramesPerSecond": return self.extendedFramesPerSecond
        case "hideCameraTile": return self.hideCameraTile
        case "disableNotificationDelay": return self.disableNotificationDelay
        case "inAppVibration": return self.inAppVibration
        default: return nil
        }
    }

    /// Writes a value by its Android `ExteraConfig` name.
    private func configBool(_ value: Any, default defaultValue: Bool) -> Bool {
        if let value = value as? Bool {
            return value
        }
        if let value = value as? NSNumber {
            return value.boolValue
        }
        return defaultValue
    }

    @discardableResult
    public func setValue(_ value: Any, forAndroidKey key: String) -> Bool {
        switch key {
        case "disableNumberRounding": self.disableNumberRounding = self.configBool(value, default: false)
        case "formatTimeWithSeconds": self.formatTimeWithSeconds = self.configBool(value, default: false)
        case "relativeLastSeen": self.relativeLastSeen = self.configBool(value, default: false)
        case "filterZalgo": self.filterZalgo = self.configBool(value, default: true)
        case "hidePhoneNumber": self.hidePhoneNumber = self.configBool(value, default: false)
        case "showIdAndDc": self.showIdAndDc = (value as? NSNumber)?.intValue ?? 1
        case "defaultProfileTab": self.defaultProfileTab = (value as? NSNumber)?.intValue ?? 0
        case "hideArchiveFolder": self.hideArchiveFolder = self.configBool(value, default: false)
        case "disableUnarchiveSwipe": self.disableUnarchiveSwipe = self.configBool(value, default: true)
        case "hideStories": self.hideStories = self.configBool(value, default: false)
        case "tabIcons": self.tabIcons = (value as? NSNumber)?.intValue ?? 1
        case "hideNavigationBarLabels": self.hideNavigationBarLabels = self.configBool(value, default: false)
        case "replyBackground": self.replyBackground = self.configBool(value, default: true)
        case "replyColors": self.replyColors = self.configBool(value, default: true)
        case "replyEmoji": self.replyEmoji = self.configBool(value, default: true)
        case "tabCounterMode": self.tabCounterMode = (value as? NSNumber)?.intValue ?? 0
        case "hideShareButton": self.hideShareButton = self.configBool(value, default: true)
        case "showSaveMessageButton": self.showSaveMessageButton = self.configBool(value, default: false)
        case "showCopyPhotoButton": self.showCopyPhotoButton = self.configBool(value, default: true)
        case "showReportButton": self.showReportButton = self.configBool(value, default: true)
        case "showClearButton": self.showClearButton = self.configBool(value, default: true)
        case "replaceEditedWithIcon": self.replaceEditedWithIcon = self.configBool(value, default: true)
        case "disableGreetingSticker": self.disableGreetingSticker = self.configBool(value, default: false)
        case "hideSendAsPeer": self.hideSendAsPeer = self.configBool(value, default: false)
        case "addCommaAfterMention": self.addCommaAfterMention = self.configBool(value, default: true)
        case "hideKeyboardOnScroll": self.hideKeyboardOnScroll = self.configBool(value, default: true)
        case "stickerTimeMode": self.stickerTimeMode = (value as? NSNumber)?.intValue ?? 0
        case "stickerSize": self.stickerSize = (value as? NSNumber)?.doubleValue ?? 12.0
        case "stickerShape": self.stickerShape = (value as? NSNumber)?.intValue ?? 1
        case "doubleTapSeekDuration": self.doubleTapSeekDuration = (value as? NSNumber)?.intValue ?? 1
        case "hideReactionsInPrivateChats": self.hideReactionsInPrivateChats = self.configBool(value, default: false)
        case "hideReactionsInChannels": self.hideReactionsInChannels = self.configBool(value, default: false)
        case "hideReactionsInGroups": self.hideReactionsInGroups = self.configBool(value, default: false)
        case "showOnlineStatus": self.showOnlineStatus = self.configBool(value, default: false)
        case "hideFloatingButton": self.hideFloatingButton = self.configBool(value, default: false)
        case "hideDialogsSearchBar": self.hideDialogsSearchBar = self.configBool(value, default: false)
        case "centerTitle": self.centerTitle = self.configBool(value, default: false)
        case "hideActionBarStatus": self.hideActionBarStatus = self.configBool(value, default: false)
        case "downloadSpeedBoost": self.downloadSpeedBoost = (value as? NSNumber)?.intValue ?? 0
        case "uploadSpeedBoost": self.uploadSpeedBoost = self.configBool(value, default: false)
        case "enableAdBlock": self.enableAdBlock = self.configBool(value, default: true)
        case "avatarCorners": self.avatarCorners = (value as? NSNumber)?.doubleValue ?? 28.0
        case "newLoadingStyle": self.newLoadingStyle = self.configBool(value, default: true)
        case "newSliderStyle": self.newSliderStyle = self.configBool(value, default: true)
        case "newSwitchStyle": self.newSwitchStyle = self.configBool(value, default: true)
        case "alwaysSendInHD": self.alwaysSendInHD = self.configBool(value, default: true)
        case "cameraStabilization": self.cameraStabilization = self.configBool(value, default: false)
        case "cameraMirrorMode": self.cameraMirrorMode = self.configBool(value, default: true)
        case "extendedFramesPerSecond": self.extendedFramesPerSecond = self.configBool(value, default: false)
        case "hideCameraTile": self.hideCameraTile = self.configBool(value, default: false)
        case "disableNotificationDelay": self.disableNotificationDelay = self.configBool(value, default: false)
        case "inAppVibration": self.inAppVibration = self.configBool(value, default: true)
        default:
            return false
        }
        return true
    }

    /// The Android `ExteraConfig` names this build understands.
    public static let androidKeys: [String] = [
        "disableNumberRounding", "formatTimeWithSeconds", "relativeLastSeen",
        "filterZalgo", "hidePhoneNumber", "showIdAndDc", "defaultProfileTab", "hideArchiveFolder",
        "disableUnarchiveSwipe", "hideStories", "tabIcons", "hideNavigationBarLabels", "replyBackground", "replyColors", "replyEmoji", "tabCounterMode",
        "hideShareButton", "showSaveMessageButton", "showCopyPhotoButton", "showReportButton", "showClearButton", "replaceEditedWithIcon", "disableGreetingSticker", "hideSendAsPeer", "addCommaAfterMention", "hideKeyboardOnScroll", "stickerTimeMode", "stickerSize", "stickerShape", "doubleTapSeekDuration",
        "hideReactionsInPrivateChats", "hideReactionsInChannels", "hideReactionsInGroups",
        "showOnlineStatus", "hideFloatingButton", "hideDialogsSearchBar",
        "centerTitle", "hideActionBarStatus", "downloadSpeedBoost",
        "uploadSpeedBoost", "enableAdBlock", "avatarCorners",
        "newLoadingStyle", "newSliderStyle", "newSwitchStyle",
        "alwaysSendInHD", "cameraStabilization", "cameraMirrorMode", "extendedFramesPerSecond", "hideCameraTile",
        "disableNotificationDelay", "inAppVibration"
    ]
}
