import Foundation

/// English strings for the Android resource keys plugins pass to
/// `LocaleController.getString`.
///
/// Telegram iOS does not use Android's keyed resources, so without this the
/// key itself would be shown. The dictionary covers the labels plugins use for
/// their own dialogs, buttons and toasts; unknown keys fall back to the bundle.
enum PluginLocalization {
    private static let strings: [String: String] = [
        "OK": "OK",
        "Cancel": "Cancel",
        "Delete": "Delete",
        "Save": "Save",
        "Done": "Done",
        "Settings": "Settings",
        "Copy": "Copy",
        "Share": "Share",
        "Edit": "Edit",
        "Close": "Close",
        "Yes": "Yes",
        "No": "No",
        "Error": "Error",
        "Warning": "Warning",
        "Loading": "Loading",
        "Search": "Search",
        "Send": "Send",
        "Reply": "Reply",
        "Forward": "Forward",
        "Pin": "Pin",
        "Unpin": "Unpin",
        "Mute": "Mute",
        "Unmute": "Unmute",
        "Leave": "Leave",
        "Join": "Join",
        "Add": "Add",
        "Remove": "Remove",
        "Reset": "Reset",
        "Enable": "Enable",
        "Disable": "Disable",
        "Plugins": "Plugins",
        "Plugin settings": "Plugin settings",
        "Restart": "Restart",
        "Apply": "Apply",
        "Retry": "Retry",
        "Update": "Update",
        "Install": "Install",
        "Uninstall": "Uninstall",
        "Select": "Select",
        "Select all": "Select all",
        "Open": "Open",
        "Read more": "Read more",
        "Show more": "Show more",
        "All": "All",
        "None": "None",
        "Today": "Today",
        "Yesterday": "Yesterday",
        "Online": "Online",
        "Offline": "Offline",
        "Typing...": "typing…",
        "Sending": "Sending",
        "Sent": "Sent",
        "Failed": "Failed",
        "Success": "Success",
        "Copied": "Copied",
        "Link copied": "Link copied",
        "Message copied": "Message copied",
        "No results": "No results"
    ]

    static func string(for key: String) -> String? {
        if let value = self.strings[key] {
            return value
        }
        let normalized = key.replacingOccurrences(of: "_", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        for (candidate, value) in self.strings {
            if candidate.caseInsensitiveCompare(normalized) == .orderedSame {
                return value
            }
        }
        return nil
    }
}
