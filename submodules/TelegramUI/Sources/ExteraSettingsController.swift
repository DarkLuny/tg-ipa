import Foundation
import UIKit
import AsyncDisplayKit
import Display
import AccountContext
import TelegramCore
import TelegramPresentationData

/// The client-side exteraGram settings that are implemented in this port.
///
/// This screen is intentionally separate from the plugin SDK screen: it changes
/// Telegram-iOS behaviour, while `PluginsViewController` manages Python plugins.
/// Every switch writes `ExteraSettings`, which is also the storage behind the
/// Python `ExteraConfig` facade.
public final class ExteraSettingsController: ViewController, UITableViewDataSource, UITableViewDelegate {
    private enum Section: Int, CaseIterable {
        case general
        case appearance
        case messages
        case network

        var title: String {
            switch self {
            case .general: return "General"
            case .appearance: return "Appearance"
            case .messages: return "Messages"
            case .network: return "Network"
            }
        }
    }

    private enum Row {
        case numberRounding
        case timeWithSeconds
        case hidePhone
        case showIdAndDc
        case inAppVibration
        case hideSearchBar
        case relativeLastSeen
        case filterZalgo
        case defaultProfileTab
        case appIcon
        case avatarCorners
        case hideStories
        case hideArchive
        case hideActionBarStatus
        case hideFloatingButton
        case disableUnarchiveSwipe
        case tabIcons
        case hideNavigationBarLabels
        case tabCounterMode
        case adBlock
        case hideShareButton
        case showCopyPhotoButton
        case showReportButton
        case showClearButton
        case replaceEditedWithIcon
        case disableGreetingSticker
        case hideSendAsPeer
        case addCommaAfterMention
        case hideKeyboardOnScroll
        case stickerTimeMode
        case stickerSize
        case stickerShape
        case doubleTapSeekDuration
        case replyBackground
        case replyColors
        case replyEmoji
        case hideReactionsInPrivateChats
        case hideReactionsInChannels
        case hideReactionsInGroups
        case alwaysSendInHD
        case cameraStabilization
        case cameraMirrorMode
        case extendedFramesPerSecond
        case hideCameraTile
        case downloadBoost
        case uploadBoost
    }

    private enum SwitchTag: Int {
        case numberRounding = 1
        case timeWithSeconds = 2
        case adBlock = 3
        case uploadBoost = 4
        case hideStories = 5
        case hideArchive = 6
        case hidePhone = 7
        case inAppVibration = 8
        case disableUnarchiveSwipe = 9
        case hideActionBarStatus = 10
        case hideSearchBar = 11
        case relativeLastSeen = 12
        case filterZalgo = 13
        case hideShareButton = 14
        case alwaysSendInHD = 17
        case hideFloatingButton = 18
        case showCopyPhotoButton = 19
        case showReportButton = 20
        case showClearButton = 21
        case cameraStabilization = 22
        case cameraMirrorMode = 23
        case extendedFramesPerSecond = 33
        case hideReactionsInPrivateChats = 24
        case hideReactionsInChannels = 25
        case hideReactionsInGroups = 26
        case replaceEditedWithIcon = 27
        case disableGreetingSticker = 28
        case hideSendAsPeer = 29
        case addCommaAfterMention = 30
        case hideKeyboardOnScroll = 31
        case stickerTimeMode = 32
        case hideNavigationBarLabels = 34
        case replyBackground = 35
        case replyColors = 36
        case replyEmoji = 37
        case hideCameraTile = 38
    }

    private let context: AccountContext
    private let tableView = UITableView(frame: .zero, style: .insetGrouped)

    public init(context: AccountContext) {
        self.context = context
        super.init(navigationBarPresentationData: NavigationBarPresentationData(presentationData: context.sharedContext.currentPresentationData.with { $0 }))
        self.title = "ExteraGram"
    }

    required init(coder aDecoder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    private var presentationData: PresentationData {
        return self.context.sharedContext.currentPresentationData.with { $0 }
    }

    private func rows(for section: Section) -> [Row] {
        switch section {
        case .general:
            return [.numberRounding, .timeWithSeconds, .hidePhone, .showIdAndDc, .defaultProfileTab, .inAppVibration, .hideSearchBar, .relativeLastSeen, .filterZalgo]
        case .appearance:
            return [.appIcon, .avatarCorners, .tabIcons, .hideNavigationBarLabels, .tabCounterMode, .hideStories, .hideArchive, .hideActionBarStatus, .hideFloatingButton, .disableUnarchiveSwipe]
        case .messages:
            return [.adBlock, .hideShareButton, .showCopyPhotoButton, .showReportButton, .showClearButton, .replaceEditedWithIcon, .disableGreetingSticker, .hideSendAsPeer, .addCommaAfterMention, .hideKeyboardOnScroll, .stickerTimeMode, .stickerSize, .stickerShape, .doubleTapSeekDuration, .replyBackground, .replyColors, .replyEmoji, .hideReactionsInPrivateChats, .hideReactionsInChannels, .hideReactionsInGroups, .alwaysSendInHD, .cameraStabilization, .cameraMirrorMode, .extendedFramesPerSecond, .hideCameraTile]
        case .network:
            return [.downloadBoost, .uploadBoost]
        }
    }

    public override func loadDisplayNode() {
        self.displayNode = ASDisplayNode()
        self.displayNode.backgroundColor = self.presentationData.theme.list.blocksBackgroundColor
        self.displayNodeDidLoad()

        self.tableView.dataSource = self
        self.tableView.delegate = self
        self.tableView.rowHeight = 44.0
        self.tableView.backgroundColor = self.presentationData.theme.list.blocksBackgroundColor
        self.tableView.separatorColor = self.presentationData.theme.list.itemPlainSeparatorColor
        self.displayNode.view.addSubview(self.tableView)

        self.applyTheme()
    }

    public override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        self.applyTheme()
        self.tableView.reloadData()
    }

    public override func containerLayoutUpdated(_ layout: ContainerViewLayout, transition: ContainedViewLayoutTransition) {
        super.containerLayoutUpdated(layout, transition: transition)

        let navigationHeight = self.navigationLayout(layout: layout).navigationFrame.maxY
        self.tableView.frame = CGRect(
            x: 0.0,
            y: navigationHeight,
            width: layout.size.width,
            height: max(0.0, layout.size.height - navigationHeight)
        )
    }

    private func applyTheme() {
        let theme = self.presentationData.theme
        self.displayNode.backgroundColor = theme.list.blocksBackgroundColor
        self.displayNode.view.backgroundColor = theme.list.blocksBackgroundColor
        self.tableView.backgroundColor = theme.list.blocksBackgroundColor
        self.tableView.separatorColor = theme.list.itemPlainSeparatorColor
        self.displayNode.view.tintColor = theme.list.itemAccentColor
    }

    public func numberOfSections(in tableView: UITableView) -> Int {
        return Section.allCases.count
    }

    public func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        guard let section = Section(rawValue: section) else {
            return 0
        }
        return self.rows(for: section).count
    }

    public func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        return Section(rawValue: section)?.title
    }

    public func tableView(_ tableView: UITableView, titleForFooterInSection section: Int) -> String? {
        if Section(rawValue: section) == .network {
            return "Fast uses 512 KiB parts with 8 parallel requests. Ultra uses 1 MiB parts with 12 parallel requests. Changing this affects new downloads and uploads."
        }
        return nil
    }

    public func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let theme = self.presentationData.theme
        let cell = tableView.dequeueReusableCell(withIdentifier: "cell") ?? UITableViewCell(style: .subtitle, reuseIdentifier: "cell")
        cell.backgroundColor = theme.list.itemBlocksBackgroundColor
        cell.textLabel?.textColor = theme.list.itemPrimaryTextColor
        cell.detailTextLabel?.textColor = theme.list.itemSecondaryTextColor
        cell.accessoryView = nil
        cell.accessoryType = .none
        cell.selectionStyle = .default

        guard let section = Section(rawValue: indexPath.section) else {
            return cell
        }
        let row = self.rows(for: section)[indexPath.row]

        switch row {
        case .numberRounding:
            cell.textLabel?.text = "Disable number rounding"
            cell.detailTextLabel?.text = "1.23K → 1,234"
            cell.accessoryView = self.makeSwitch(tag: .numberRounding, isOn: ExteraSettings.shared.disableNumberRounding)
        case .timeWithSeconds:
            cell.textLabel?.text = "Time with seconds"
            cell.detailTextLabel?.text = "12:34 → 12:34:56"
            cell.accessoryView = self.makeSwitch(tag: .timeWithSeconds, isOn: ExteraSettings.shared.formatTimeWithSeconds)
        case .hidePhone:
            cell.textLabel?.text = "Hide phone number"
            cell.detailTextLabel?.text = "Mask the number in your profile"
            cell.accessoryView = self.makeSwitch(tag: .hidePhone, isOn: ExteraSettings.shared.hidePhoneNumber)
        case .showIdAndDc:
            cell.textLabel?.text = "Show ID and DC"
            cell.detailTextLabel?.text = self.showIdAndDcTitle(ExteraSettings.shared.showIdAndDc)
            cell.accessoryType = .disclosureIndicator
        case .inAppVibration:
            cell.textLabel?.text = "In-app vibration"
            cell.detailTextLabel?.text = "Haptic feedback inside the app"
            cell.accessoryView = self.makeSwitch(tag: .inAppVibration, isOn: ExteraSettings.shared.inAppVibration)
        case .hideSearchBar:
            cell.textLabel?.text = "Hide search bar"
            cell.detailTextLabel?.text = "Remove the search field from the chat list"
            cell.accessoryView = self.makeSwitch(tag: .hideSearchBar, isOn: ExteraSettings.shared.hideDialogsSearchBar)
        case .relativeLastSeen:
            cell.textLabel?.text = "Relative last seen"
            cell.detailTextLabel?.text = "Use minutes/hours instead of absolute times"
            cell.accessoryView = self.makeSwitch(tag: .relativeLastSeen, isOn: ExteraSettings.shared.relativeLastSeen)
        case .filterZalgo:
            cell.textLabel?.text = "Filter zalgo"
            cell.detailTextLabel?.text = "Remove excessive combining marks from plain text"
            cell.accessoryView = self.makeSwitch(tag: .filterZalgo, isOn: ExteraSettings.shared.filterZalgo)
        case .defaultProfileTab:
            cell.textLabel?.text = "Default profile tab"
            cell.detailTextLabel?.text = self.defaultProfileTabTitle(ExteraSettings.shared.defaultProfileTab)
            cell.accessoryType = .disclosureIndicator
        case .appIcon:
            cell.textLabel?.text = "App icon"
            cell.detailTextLabel?.text = self.currentAppIconTitle()
            cell.accessoryType = .disclosureIndicator
        case .avatarCorners:
            cell.textLabel?.text = "Avatar corners"
            cell.detailTextLabel?.text = self.avatarCornersTitle(ExteraSettings.shared.avatarCorners)
            cell.accessoryType = .disclosureIndicator
        case .hideStories:
            cell.textLabel?.text = "Hide stories"
            cell.detailTextLabel?.text = "Remove the stories row from the chat list"
            cell.accessoryView = self.makeSwitch(tag: .hideStories, isOn: ExteraSettings.shared.hideStories)
        case .hideArchive:
            cell.textLabel?.text = "Hide archive folder"
            cell.detailTextLabel?.text = "Keep archived chats out of the chat list"
            cell.accessoryView = self.makeSwitch(tag: .hideArchive, isOn: ExteraSettings.shared.hideArchiveFolder)
        case .hideActionBarStatus:
            cell.textLabel?.text = "Hide action bar status"
            cell.detailTextLabel?.text = "Remove the presence/member line from the chat title"
            cell.accessoryView = self.makeSwitch(tag: .hideActionBarStatus, isOn: ExteraSettings.shared.hideActionBarStatus)
        case .hideFloatingButton:
            cell.textLabel?.text = "Hide floating button"
            cell.detailTextLabel?.text = "Hide the chat-list compose button"
            cell.accessoryView = self.makeSwitch(tag: .hideFloatingButton, isOn: ExteraSettings.shared.hideFloatingButton)
        case .disableUnarchiveSwipe:
            cell.textLabel?.text = "Disable unarchive swipe"
            cell.detailTextLabel?.text = "Keep archived chats in the archive when swiped"
            cell.accessoryView = self.makeSwitch(tag: .disableUnarchiveSwipe, isOn: ExteraSettings.shared.disableUnarchiveSwipe)
        case .tabIcons:
            cell.textLabel?.text = "Tab bar"
            cell.detailTextLabel?.text = self.tabIconsTitle(ExteraSettings.shared.tabIcons)
            cell.accessoryType = .disclosureIndicator
        case .hideNavigationBarLabels:
            cell.textLabel?.text = "Hide tab bar labels"
            cell.detailTextLabel?.text = "Show icons without titles"
            cell.accessoryView = self.makeSwitch(tag: .hideNavigationBarLabels, isOn: ExteraSettings.shared.hideNavigationBarLabels)
        case .tabCounterMode:
            cell.textLabel?.text = "Tab counter"
            cell.detailTextLabel?.text = self.tabCounterModeTitle(ExteraSettings.shared.tabCounterMode)
            cell.accessoryType = .disclosureIndicator
        case .adBlock:
            cell.textLabel?.text = "Ad block"
            cell.detailTextLabel?.text = "Hide sponsored messages"
            cell.accessoryView = self.makeSwitch(tag: .adBlock, isOn: ExteraSettings.shared.enableAdBlock)
        case .hideShareButton:
            cell.textLabel?.text = "Hide share button"
            cell.detailTextLabel?.text = "Remove Share from the message menu"
            cell.accessoryView = self.makeSwitch(tag: .hideShareButton, isOn: ExteraSettings.shared.hideShareButton)
        case .showCopyPhotoButton:
            cell.textLabel?.text = "Show copy photo button"
            cell.detailTextLabel?.text = "Copy an image from the message menu"
            cell.accessoryView = self.makeSwitch(tag: .showCopyPhotoButton, isOn: ExteraSettings.shared.showCopyPhotoButton)
        case .showReportButton:
            cell.textLabel?.text = "Show report button"
            cell.detailTextLabel?.text = "Report a message or profile"
            cell.accessoryView = self.makeSwitch(tag: .showReportButton, isOn: ExteraSettings.shared.showReportButton)
        case .showClearButton:
            cell.textLabel?.text = "Show clear button"
            cell.detailTextLabel?.text = "Show Clear History in the chat menu"
            cell.accessoryView = self.makeSwitch(tag: .showClearButton, isOn: ExteraSettings.shared.showClearButton)
        case .replaceEditedWithIcon:
            cell.textLabel?.text = "Replace Edited with icon"
            cell.detailTextLabel?.text = "Show a pencil instead of the Edited label"
            cell.accessoryView = self.makeSwitch(tag: .replaceEditedWithIcon, isOn: ExteraSettings.shared.replaceEditedWithIcon)
        case .disableGreetingSticker:
            cell.textLabel?.text = "Disable greeting sticker"
            cell.detailTextLabel?.text = "Hide the sticker in an empty chat"
            cell.accessoryView = self.makeSwitch(tag: .disableGreetingSticker, isOn: ExteraSettings.shared.disableGreetingSticker)
        case .hideSendAsPeer:
            cell.textLabel?.text = "Hide send-as button"
            cell.detailTextLabel?.text = "Hide the send-as avatar in the input field"
            cell.accessoryView = self.makeSwitch(tag: .hideSendAsPeer, isOn: ExteraSettings.shared.hideSendAsPeer)
        case .addCommaAfterMention:
            cell.textLabel?.text = "Add comma after mention"
            cell.detailTextLabel?.text = "Insert \", \" after a selected mention"
            cell.accessoryView = self.makeSwitch(tag: .addCommaAfterMention, isOn: ExteraSettings.shared.addCommaAfterMention)
        case .hideKeyboardOnScroll:
            cell.textLabel?.text = "Hide keyboard on scroll"
            cell.detailTextLabel?.text = "Dismiss the input when the history is dragged"
            cell.accessoryView = self.makeSwitch(tag: .hideKeyboardOnScroll, isOn: ExteraSettings.shared.hideKeyboardOnScroll)
        case .stickerTimeMode:
            cell.textLabel?.text = "Hide sticker time"
            cell.detailTextLabel?.text = "Hide timestamps on sticker messages"
            cell.accessoryView = self.makeSwitch(tag: .stickerTimeMode, isOn: ExteraSettings.shared.stickerTimeMode == 2)
        case .stickerSize:
            cell.textLabel?.text = "Sticker size"
            cell.detailTextLabel?.text = String(format: "%.0f", ExteraSettings.shared.stickerSize)
            cell.accessoryType = .disclosureIndicator
        case .stickerShape:
            cell.textLabel?.text = "Sticker shape"
            cell.detailTextLabel?.text = ExteraSettings.shared.stickerShape == 0 ? "None" : "Rounded"
            cell.accessoryType = .disclosureIndicator
        case .doubleTapSeekDuration:
            cell.textLabel?.text = "Double-tap seek"
            cell.detailTextLabel?.text = String(format: "%.0f seconds", ExteraSettings.shared.doubleTapSeekDurationSeconds())
            cell.accessoryType = .disclosureIndicator
        case .replyBackground:
            cell.textLabel?.text = "Reply background"
            cell.detailTextLabel?.text = "Draw the background behind a quoted reply"
            cell.accessoryView = self.makeSwitch(tag: .replyBackground, isOn: ExteraSettings.shared.replyBackground)
        case .replyColors:
            cell.textLabel?.text = "Reply colors"
            cell.detailTextLabel?.text = "Use the author's name colors in replies"
            cell.accessoryView = self.makeSwitch(tag: .replyColors, isOn: ExteraSettings.shared.replyColors)
        case .replyEmoji:
            cell.textLabel?.text = "Reply emoji"
            cell.detailTextLabel?.text = "Use the author's background emoji in replies"
            cell.accessoryView = self.makeSwitch(tag: .replyEmoji, isOn: ExteraSettings.shared.replyEmoji)
        case .hideReactionsInPrivateChats:
            cell.textLabel?.text = "Hide reactions in private chats"
            cell.detailTextLabel?.text = "Hide the reaction footer in DMs"
            cell.accessoryView = self.makeSwitch(tag: .hideReactionsInPrivateChats, isOn: ExteraSettings.shared.hideReactionsInPrivateChats)
        case .hideReactionsInChannels:
            cell.textLabel?.text = "Hide reactions in channels"
            cell.detailTextLabel?.text = "Hide the reaction footer in channels"
            cell.accessoryView = self.makeSwitch(tag: .hideReactionsInChannels, isOn: ExteraSettings.shared.hideReactionsInChannels)
        case .hideReactionsInGroups:
            cell.textLabel?.text = "Hide reactions in groups"
            cell.detailTextLabel?.text = "Hide the reaction footer in groups"
            cell.accessoryView = self.makeSwitch(tag: .hideReactionsInGroups, isOn: ExteraSettings.shared.hideReactionsInGroups)
        case .alwaysSendInHD:
            cell.textLabel?.text = "Always send in HD"
            cell.detailTextLabel?.text = "Force the high-quality photo flag"
            cell.accessoryView = self.makeSwitch(tag: .alwaysSendInHD, isOn: ExteraSettings.shared.alwaysSendInHD)
        case .cameraStabilization:
            cell.textLabel?.text = "Camera stabilization"
            cell.detailTextLabel?.text = "Enable standard video stabilization"
            cell.accessoryView = self.makeSwitch(tag: .cameraStabilization, isOn: ExteraSettings.shared.cameraStabilization)
        case .cameraMirrorMode:
            cell.textLabel?.text = "Mirror front camera"
            cell.detailTextLabel?.text = "Mirror photos from the front camera"
            cell.accessoryView = self.makeSwitch(tag: .cameraMirrorMode, isOn: ExteraSettings.shared.cameraMirrorMode)
        case .extendedFramesPerSecond:
            cell.textLabel?.text = "Extended frame rate"
            cell.detailTextLabel?.text = "Prefer 60 fps video capture when supported"
            cell.accessoryView = self.makeSwitch(tag: .extendedFramesPerSecond, isOn: ExteraSettings.shared.extendedFramesPerSecond)
        case .hideCameraTile:
            cell.textLabel?.text = "Hide camera tile"
            cell.detailTextLabel?.text = "Remove the camera cell from the media picker"
            cell.accessoryView = self.makeSwitch(tag: .hideCameraTile, isOn: ExteraSettings.shared.hideCameraTile)
        case .downloadBoost:
            cell.textLabel?.text = "Download speed boost"
            cell.detailTextLabel?.text = self.downloadBoostTitle(ExteraSettings.shared.downloadSpeedBoost)
            cell.accessoryType = .disclosureIndicator
        case .uploadBoost:
            cell.textLabel?.text = "Upload speed boost"
            cell.detailTextLabel?.text = "More parallel upload parts"
            cell.accessoryView = self.makeSwitch(tag: .uploadBoost, isOn: ExteraSettings.shared.uploadSpeedBoost)
        }
        return cell
    }

    private func makeSwitch(tag: SwitchTag, isOn: Bool) -> UISwitch {
        let control = UISwitch()
        control.tag = tag.rawValue
        control.isOn = isOn
        control.onTintColor = self.presentationData.theme.list.itemAccentColor
        control.addTarget(self, action: #selector(self.switchChanged(_:)), for: .valueChanged)
        return control
    }

    @objc private func switchChanged(_ sender: UISwitch) {
        guard let tag = SwitchTag(rawValue: sender.tag) else {
            return
        }
        switch tag {
        case .numberRounding:
            ExteraSettings.shared.disableNumberRounding = sender.isOn
        case .timeWithSeconds:
            ExteraSettings.shared.formatTimeWithSeconds = sender.isOn
        case .hidePhone:
            ExteraSettings.shared.hidePhoneNumber = sender.isOn
        case .inAppVibration:
            ExteraSettings.shared.inAppVibration = sender.isOn
        case .hideSearchBar:
            ExteraSettings.shared.hideDialogsSearchBar = sender.isOn
        case .relativeLastSeen:
            ExteraSettings.shared.relativeLastSeen = sender.isOn
        case .filterZalgo:
            ExteraSettings.shared.filterZalgo = sender.isOn
        case .hideStories:
            ExteraSettings.shared.hideStories = sender.isOn
        case .hideArchive:
            ExteraSettings.shared.hideArchiveFolder = sender.isOn
        case .hideActionBarStatus:
            ExteraSettings.shared.hideActionBarStatus = sender.isOn
        case .hideFloatingButton:
            ExteraSettings.shared.hideFloatingButton = sender.isOn
        case .disableUnarchiveSwipe:
            ExteraSettings.shared.disableUnarchiveSwipe = sender.isOn
        case .adBlock:
            ExteraSettings.shared.enableAdBlock = sender.isOn
        case .hideShareButton:
            ExteraSettings.shared.hideShareButton = sender.isOn
        case .showCopyPhotoButton:
            ExteraSettings.shared.showCopyPhotoButton = sender.isOn
        case .showReportButton:
            ExteraSettings.shared.showReportButton = sender.isOn
        case .showClearButton:
            ExteraSettings.shared.showClearButton = sender.isOn
        case .replaceEditedWithIcon:
            ExteraSettings.shared.replaceEditedWithIcon = sender.isOn
        case .disableGreetingSticker:
            ExteraSettings.shared.disableGreetingSticker = sender.isOn
        case .hideSendAsPeer:
            ExteraSettings.shared.hideSendAsPeer = sender.isOn
        case .addCommaAfterMention:
            ExteraSettings.shared.addCommaAfterMention = sender.isOn
        case .hideKeyboardOnScroll:
            ExteraSettings.shared.hideKeyboardOnScroll = sender.isOn
        case .stickerTimeMode:
            ExteraSettings.shared.stickerTimeMode = sender.isOn ? 2 : 0
        case .replyBackground:
            ExteraSettings.shared.replyBackground = sender.isOn
        case .replyColors:
            ExteraSettings.shared.replyColors = sender.isOn
        case .replyEmoji:
            ExteraSettings.shared.replyEmoji = sender.isOn
        case .hideNavigationBarLabels:
            ExteraSettings.shared.hideNavigationBarLabels = sender.isOn
        case .hideReactionsInPrivateChats:
            ExteraSettings.shared.hideReactionsInPrivateChats = sender.isOn
        case .hideReactionsInChannels:
            ExteraSettings.shared.hideReactionsInChannels = sender.isOn
        case .hideReactionsInGroups:
            ExteraSettings.shared.hideReactionsInGroups = sender.isOn
        case .alwaysSendInHD:
            ExteraSettings.shared.alwaysSendInHD = sender.isOn
        case .cameraStabilization:
            ExteraSettings.shared.cameraStabilization = sender.isOn
        case .cameraMirrorMode:
            ExteraSettings.shared.cameraMirrorMode = sender.isOn
        case .extendedFramesPerSecond:
            ExteraSettings.shared.extendedFramesPerSecond = sender.isOn
        case .hideCameraTile:
            ExteraSettings.shared.hideCameraTile = sender.isOn
        case .uploadBoost:
            ExteraSettings.shared.uploadSpeedBoost = sender.isOn
        }
    }

    public func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)

        guard let section = Section(rawValue: indexPath.section) else {
            return
        }
        let row = self.rows(for: section)[indexPath.row]
        switch row {
        case .showIdAndDc:
            self.presentShowIdAndDcPicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .appIcon:
            self.presentAppIconPicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .avatarCorners:
            self.presentAvatarCornersPicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .tabIcons:
            self.presentTabIconsPicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .tabCounterMode:
            self.presentTabCounterModePicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .stickerSize:
            self.presentStickerSizePicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .stickerShape:
            self.presentStickerShapePicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .doubleTapSeekDuration:
            self.presentDoubleTapSeekPicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .hideNavigationBarLabels:
            break
        case .defaultProfileTab:
            self.presentDefaultProfileTabPicker(sourceCell: tableView.cellForRow(at: indexPath))
        case .downloadBoost:
            self.presentDownloadBoostPicker(sourceCell: tableView.cellForRow(at: indexPath))
        default:
            break
        }
    }

    private func showIdAndDcTitle(_ value: Int) -> String {
        switch value {
        case 1: return "ID"
        case 2: return "ID + DC"
        default: return "Hidden"
        }
    }

    private func presentShowIdAndDcPicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Show ID and DC", message: nil, preferredStyle: .actionSheet)
        for (value, title) in [(0, "Hidden"), (1, "ID"), (2, "ID + DC")] {
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                ExteraSettings.shared.showIdAndDc = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func avatarCornersTitle(_ value: Double) -> String {
        switch value {
        case ..<3.5: return "Square"
        case ..<10.5: return "Small"
        case ..<17.5: return "Medium"
        case ..<24.5: return "Large"
        default: return "Circle"
        }
    }

    private func presentAvatarCornersPicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Avatar corners", message: nil, preferredStyle: .actionSheet)
        for (value, title) in [(0.0, "Square"), (7.0, "Small"), (14.0, "Medium"), (21.0, "Large"), (28.0, "Circle")] {
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                ExteraSettings.shared.avatarCorners = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func tabCounterModeTitle(_ value: Int) -> String {
        switch value {
        case 2: return "Hidden"
        case 1: return "Unmuted"
        default: return "All"
        }
    }

    private func presentStickerSizePicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Sticker size", message: nil, preferredStyle: .actionSheet)
        for value in [8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0] {
            sheet.addAction(UIAlertAction(title: String(format: "%.0f", value), style: .default, handler: { _ in
                ExteraSettings.shared.stickerSize = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func presentDoubleTapSeekPicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Double-tap seek", message: nil, preferredStyle: .actionSheet)
        for (value, title) in [(0, "5 seconds"), (1, "10 seconds"), (2, "15 seconds"), (3, "30 seconds")] {
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                ExteraSettings.shared.doubleTapSeekDuration = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func presentStickerShapePicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Sticker shape", message: nil, preferredStyle: .actionSheet)
        for (value, title) in [(0, "None"), (1, "Rounded")] {
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                ExteraSettings.shared.stickerShape = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func presentTabCounterModePicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Tab counter", message: nil, preferredStyle: .actionSheet)
        for (value, title) in [(0, "All"), (1, "Unmuted"), (2, "Hidden")] {
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                ExteraSettings.shared.tabCounterMode = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func defaultProfileTabTitle(_ value: Int) -> String {
        switch value {
        case 1: return "Media"
        case 2: return "Common groups"
        default: return "Default"
        }
    }

    private func presentDefaultProfileTabPicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Default profile tab", message: nil, preferredStyle: .actionSheet)
        for (value, title) in [(0, "Default"), (1, "Media"), (2, "Common groups")] {
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                ExteraSettings.shared.defaultProfileTab = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func tabIconsTitle(_ value: Int) -> String {
        switch value {
        case 0: return "Icons and titles"
        case 2: return "Icons only"
        default: return "Titles only"
        }
    }

    private func presentTabIconsPicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Tab bar", message: nil, preferredStyle: .actionSheet)
        for (value, title) in [(0, "Icons and titles"), (1, "Titles only"), (2, "Icons only")] {
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                ExteraSettings.shared.tabIcons = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func currentAppIconTitle() -> String {
        let bindings = self.context.sharedContext.applicationBindings
        guard let current = bindings.getAlternateIconName() else {
            return "Default"
        }
        if let icon = bindings.getAvailableAlternateIcons().first(where: { $0.name == current }) {
            return icon.isDefault ? "Default" : icon.name
        }
        return current
    }

    private func presentAppIconPicker(sourceCell: UITableViewCell?) {
        let bindings = self.context.sharedContext.applicationBindings
        let icons = bindings.getAvailableAlternateIcons().filter { !$0.isPremium || self.context.isPremium }

        let sheet = UIAlertController(title: "App icon", message: nil, preferredStyle: .actionSheet)
        for icon in icons {
            let title = icon.isDefault ? "Default" : icon.name
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                bindings.requestSetAlternateIconName(icon.isDefault ? nil : icon.name, { _ in
                    DispatchQueue.main.async {
                        self.tableView.reloadData()
                    }
                })
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }

    private func configurePopover(_ sheet: UIAlertController, sourceCell: UITableViewCell?) {
        guard let popover = sheet.popoverPresentationController else {
            return
        }
        if let cell = sourceCell {
            popover.sourceView = cell
            popover.sourceRect = cell.bounds
        } else {
            popover.sourceView = self.view
            popover.sourceRect = CGRect(x: self.view.bounds.midX, y: self.view.bounds.midY, width: 1.0, height: 1.0)
        }
    }

    private func downloadBoostTitle(_ value: Int) -> String {
        switch value {
        case 1: return "Fast"
        case 2: return "Ultra"
        default: return "Off"
        }
    }

    private func presentDownloadBoostPicker(sourceCell: UITableViewCell?) {
        let sheet = UIAlertController(title: "Download speed boost", message: nil, preferredStyle: .actionSheet)
        for (value, title) in [(0, "Off"), (1, "Fast"), (2, "Ultra")] {
            sheet.addAction(UIAlertAction(title: title, style: .default, handler: { _ in
                ExteraSettings.shared.downloadSpeedBoost = value
                self.tableView.reloadData()
            }))
        }
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel, handler: nil))
        self.configurePopover(sheet, sourceCell: sourceCell)
        self.present(sheet, animated: true, completion: nil)
    }
}
