import Foundation

/// How `updateMessageWidgetData` changes one of a message widget's two states: a field it leaves out is
/// unchanged, an empty one clears it, any other replaces it.
enum MessageWidgetDataChange: Equatable {
    case unchanged
    case set(Data?)
}

func messageWidgetDataChange(_ text: String?) -> MessageWidgetDataChange {
    guard let text else {
        return .unchanged
    }
    return .set(text.isEmpty ? nil : Data(text.utf8))
}
