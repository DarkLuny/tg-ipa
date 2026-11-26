import Foundation
import TelegramCore
import Postbox
import SwiftSignalKit

public enum RenderedTotalUnreadCountType {
    case raw
    case filtered
}

public func renderedTotalUnreadCount(inAppSettings: InAppNotificationSettings, totalUnreadState: EngineChatListTotalUnreadState) -> (Int32, RenderedTotalUnreadCountType) {
    let type: RenderedTotalUnreadCountType
    switch inAppSettings.totalUnreadCountDisplayStyle {
        case .filtered:
            type = .filtered
    }
    return (totalUnreadState.count(for: inAppSettings.totalUnreadCountDisplayStyle.category, in: inAppSettings.totalUnreadCountDisplayCategory.statsType, with: inAppSettings.totalUnreadCountIncludeTags), type)
}

/// Total unread chats excluding muted chats.  exteraGram's `unmuted` tab
/// counter uses this value; the normal counter follows the user's
/// "include muted" display setting.
public func renderedUnmutedUnreadCount(accountManager: AccountManager<TelegramAccountManagerTypes>, engine: TelegramEngine) -> Signal<Int32, NoError> {
    return combineLatest(
        accountManager.sharedData(keys: [ApplicationSpecificSharedDataKeys.inAppNotificationSettings]),
        engine.data.subscribe(
            TelegramEngine.EngineData.Item.Messages.TotalReadCounters()
        )
    )
    |> map { sharedData, totalReadCounters -> Int32 in
        let inAppSettings: InAppNotificationSettings
        if let value = sharedData.entries[ApplicationSpecificSharedDataKeys.inAppNotificationSettings]?.get(InAppNotificationSettings.self) {
            inAppSettings = value
        } else {
            inAppSettings = .defaultSettings
        }
        return totalReadCounters.count(for: .filtered, in: inAppSettings.totalUnreadCountDisplayCategory.statsType, with: inAppSettings.totalUnreadCountIncludeTags)
    }
    |> distinctUntilChanged
}

public func renderedTotalUnreadCount(accountManager: AccountManager<TelegramAccountManagerTypes>, engine: TelegramEngine) -> Signal<(Int32, RenderedTotalUnreadCountType), NoError> {
    return combineLatest(
        accountManager.sharedData(keys: [ApplicationSpecificSharedDataKeys.inAppNotificationSettings]),
        engine.data.subscribe(
            TelegramEngine.EngineData.Item.Messages.TotalReadCounters()
        )
    )
    |> map { sharedData, totalReadCounters -> (Int32, RenderedTotalUnreadCountType) in
        let inAppSettings: InAppNotificationSettings
        if let value = sharedData.entries[ApplicationSpecificSharedDataKeys.inAppNotificationSettings]?.get(InAppNotificationSettings.self) {
            inAppSettings = value
        } else {
            inAppSettings = .defaultSettings
        }
        let type: RenderedTotalUnreadCountType
        switch inAppSettings.totalUnreadCountDisplayStyle {
            case .filtered:
                type = .filtered
        }
        return (totalReadCounters.count(for: inAppSettings.totalUnreadCountDisplayStyle.category, in: inAppSettings.totalUnreadCountDisplayCategory.statsType, with: inAppSettings.totalUnreadCountIncludeTags), type)
    }
    |> distinctUntilChanged(isEqual: { lhs, rhs in
        return lhs == rhs
    })
}
