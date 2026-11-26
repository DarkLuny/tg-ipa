import Foundation
import Postbox
import SwiftSignalKit
internal import TelegramApi
import MtProtoKit

/// Builds an `Api.InputStickerSet` from the fields a plugin sends: either
/// `short_name` or an `id`/`access_hash` pair.
private func pluginInputStickerSet(_ payload: [String: Any]) -> Api.InputStickerSet {
    let rawSet = (payload["stickerset"] as? [String: Any]) ?? [:]
    let shortName = (rawSet["short_name"] as? String) ?? (payload["short_name"] as? String) ?? ""
    if !shortName.isEmpty {
        return .inputStickerSetShortName(.init(shortName: shortName))
    }
    let setId = (rawSet["id"] as? NSNumber)?.int64Value ?? (payload["id"] as? NSNumber)?.int64Value ?? 0
    let accessHash = (rawSet["access_hash"] as? NSNumber)?.int64Value ?? (payload["access_hash"] as? NSNumber)?.int64Value ?? 0
    return .inputStickerSetID(.init(id: setId, accessHash: accessHash))
}

/// Builds `Api.ReplyMarkup` from the plugin's inline-keyboard JSON.
///
/// The accepted shape is `{"rows": [[{"text": ..., "url": ... | "data": ...}]]}`,
/// matching Android's `TLRPC.TL_replyInlineMarkup`.
private func pluginReplyMarkup(_ value: Any?) -> Api.ReplyMarkup? {
    guard let data = value as? [String: Any] else {
        return nil
    }
    let rows = (data["rows"] as? [[[String: Any]]])
        ?? (data["buttons"] as? [[[String: Any]]])
        ?? []
    var apiRows: [Api.KeyboardButtonRow] = []
    for row in rows {
        var buttons: [Api.KeyboardButton] = []
        for button in row {
            let text = (button["text"] as? String) ?? ""
            if let url = button["url"] as? String, !url.isEmpty {
                buttons.append(.keyboardButtonUrl(.init(text: text, url: url)))
            } else if let callback = button["data"] as? String {
                buttons.append(.keyboardButtonCallback(.init(
                    flags: 0,
                    text: text,
                    data: Buffer(data: Data(callback.utf8))
                )))
            } else if let callback = button["callback_data"] as? String {
                buttons.append(.keyboardButtonCallback(.init(
                    flags: 0,
                    text: text,
                    data: Buffer(data: Data(callback.utf8))
                )))
            } else {
                buttons.append(.keyboardButton(.init(text: text)))
            }
        }
        if !buttons.isEmpty {
            apiRows.append(.keyboardButtonRow(.init(buttons: buttons)))
        }
    }
    if apiRows.isEmpty {
        return nil
    }
    return .replyInlineMarkup(.init(rows: apiRows))
}

/// Builds `inputMediaPoll` from a plugin's poll JSON (`poll` or `inputMediaPoll`).
private func pluginPollInputMedia(_ mediaValues: [String: Any]) -> Api.InputMedia? {
    let pollValues = (mediaValues["poll"] as? [String: Any]) ?? mediaValues
    let questionText = (pollValues["question"] as? String)
        ?? (pollValues["text"] as? String)
        ?? (pollValues["message"] as? String)
        ?? ""
    let questionEntities = pluginMessageTextEntities(
        (pollValues["question_entities"] as? [[String: Any]])
            ?? (pollValues["entities"] as? [[String: Any]])
            ?? []
    )
    var pollFlags: Int32 = (pollValues["flags"] as? NSNumber)?.int32Value ?? 0
    let pollBoolFlags: [(String, Int)] = [
        ("closed", 0),
        ("public_voters", 1),
        ("multiple_choice", 2),
        ("quiz", 3),
        ("open_answers", 6),
        ("revoting_disabled", 7),
        ("shuffle_answers", 8),
        ("hide_results_until_close", 9),
    ]
    for (key, bit) in pollBoolFlags where (pollValues[key] as? Bool) == true {
        pollFlags |= 1 << Int32(bit)
    }
    let closePeriod = (pollValues["close_period"] as? NSNumber)?.int32Value
    let closeDate = (pollValues["close_date"] as? NSNumber)?.int32Value
    if closePeriod != nil {
        pollFlags |= 1 << 4
    }
    if closeDate != nil {
        pollFlags |= 1 << 5
    }
    let countries = (pollValues["countries_iso2"] as? [String])
        ?? (pollValues["countries"] as? [String])
        ?? []
    let answerValues = (pollValues["answers"] as? [[String: Any]])
        ?? (pollValues["options"] as? [[String: Any]])
        ?? []
    var apiAnswers: [Api.PollAnswer] = []
    var correctAnswers: [Int32] = []
    for (index, answer) in answerValues.enumerated() {
        let answerText = (answer["text"] as? String) ?? ""
        let answerEntities = pluginMessageTextEntities(
            (answer["entities"] as? [[String: Any]]) ?? []
        )
        let textWithEntities = Api.TextWithEntities.textWithEntities(.init(
            text: answerText,
            entities: apiEntitiesFromMessageTextEntities(
                answerEntities,
                associatedPeers: SimpleDictionary<PeerId, Peer>()
            )
        ))
        if (answer["correct"] as? Bool) == true {
            correctAnswers.append(Int32(index))
        }
        let optionData = (answer["option"] as? String).flatMap { Data(base64Encoded: $0) }
            ?? Data(answerText.utf8)
        apiAnswers.append(.pollAnswer(.init(
            flags: 0,
            text: textWithEntities,
            option: Buffer(data: optionData),
            media: nil,
            addedBy: nil,
            date: nil
        )))
    }
    var pollMediaFlags: Int32 = 0
    if !correctAnswers.isEmpty {
        pollMediaFlags |= 1 << 0
    }
    let solution = pollValues["solution"] as? String
    var solutionEntities: [Api.MessageEntity]?
    if solution != nil {
        pollMediaFlags |= 1 << 1
        solutionEntities = apiEntitiesFromMessageTextEntities(
            pluginMessageTextEntities(
                (pollValues["solution_entities"] as? [[String: Any]]) ?? []
            ),
            associatedPeers: SimpleDictionary<PeerId, Peer>()
        )
    }
    return .inputMediaPoll(.init(
        flags: pollMediaFlags,
        poll: .poll(.init(
            id: 0,
            flags: pollFlags,
            question: .textWithEntities(.init(
                text: questionText,
                entities: apiEntitiesFromMessageTextEntities(
                    questionEntities,
                    associatedPeers: SimpleDictionary<PeerId, Peer>()
                )
            )),
            answers: apiAnswers,
            closePeriod: closePeriod,
            closeDate: closeDate,
            countriesIso2: countries,
            hash: 0
        )),
        correctAnswers: correctAnswers.isEmpty ? nil : correctAnswers,
        attachedMedia: nil,
        solution: solution,
        solutionEntities: solutionEntities,
        solutionMedia: nil
    ))
}

/// Performs the subset of Telegram requests the plugin SDK exposes.
///
/// A plugin on Android builds `TLObject` instances and calls
/// `ConnectionsManager.sendRequest`; iOS has no name-to-constructor reflection
/// for the generated API, so the names that scripts use most often are mapped
/// here explicitly instead of failing every raw request.
public func pluginPerformRequest(account: Account, name: String, payload: [String: Any]) -> Signal<[String: Any]?, NoError> {
    switch name {
    case "users.getUsers":
        let rawIds = (payload["ids"] as? [Any]) ?? (payload["id"] as? [Any]) ?? []
        let ids = rawIds.compactMap { value -> Int64? in
            if let number = value as? NSNumber { return number.int64Value }
            if let text = value as? String { return Int64(text) }
            return nil
        }
        return account.postbox.transaction { transaction -> [Api.InputUser] in
            return ids.compactMap { id in
                let peerId = pluginPeerId(fromDialogId: id)
                guard let peer = transaction.getPeer(peerId) else { return nil }
                return apiInputUser(peer)
            }
        }
        |> mapToSignal { users in
            return account.network.request(Api.functions.users.getUsers(id: users))
            |> map { result -> [String: Any]? in
                switch result {
                case let .users(data):
                    return ["users": data.users.map { pluginValueObject($0) }, "count": data.users.count]
                case let .usersSlice(data):
                    return ["users": data.users.map { pluginValueObject($0) }, "count": Int(data.count)]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getHistory":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let offsetId = (payload["offset_id"] as? NSNumber)?.int32Value ?? 0
        let limit = (payload["limit"] as? NSNumber)?.int32Value ?? 50
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.getHistory(
                peer: inputPeer,
                offsetId: offsetId,
                offsetDate: 0,
                addOffset: 0,
                limit: limit,
                maxId: 0,
                minId: 0,
                hash: 0
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .messages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) }
                    ]
                case let .messagesSlice(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case let .channelMessages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case .messagesNotModified:
                    return ["messages": [], "users": [], "chats": []]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "contacts.resolveUsername":
        let username = (payload["username"] as? String) ?? ""
        let referer = payload["referer"] as? String
        var flags: Int32 = 0
        if referer != nil {
            flags |= 1 << 0
        }
        return account.network.request(Api.functions.contacts.resolveUsername(flags: flags, username: username, referer: referer))
        |> map { result -> [String: Any]? in
            switch result {
            case let .resolvedPeer(data):
                return [
                    "peer": pluginValueObject(data.peer),
                    "users": data.users.map { pluginValueObject($0) },
                    "chats": data.chats.map { pluginValueObject($0) }
                ]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "chatlists.checkChatlistInvite":
        let slug = (payload["slug"] as? String) ?? (payload["invite"] as? String) ?? ""
        guard !slug.isEmpty else {
            return .single(["error": "slug is required"])
        }
        return account.network.request(Api.functions.chatlists.checkChatlistInvite(slug: slug))
        |> map { result -> [String: Any]? in
            return pluginValueObject(result)
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.setTyping":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let actionName = (payload["action"] as? String) ?? "typing"
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            let action: Api.SendMessageAction
            switch actionName {
            case "record", "recording":
                action = .sendMessageRecordAudioAction
            case "upload":
                action = .sendMessageUploadDocumentAction(.init(progress: 0))
            case "cancel":
                action = .sendMessageCancelAction
            default:
                action = .sendMessageTypingAction
            }
            return account.network.request(Api.functions.messages.setTyping(
                flags: 0,
                peer: inputPeer,
                topMsgId: nil,
                action: action
            ))
            |> map { _ -> [String: Any]? in
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "users.getFullUser":
        let rawPeer = (payload["id"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputUser? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputUser(peer)
        }
        |> mapToSignal { inputUser -> Signal<[String: Any]?, NoError> in
            guard let inputUser else {
                return .single(["error": "unknown user"])
            }
            return account.network.request(Api.functions.users.getFullUser(id: inputUser))
            |> map { result -> [String: Any]? in
                switch result {
                case let .userFull(data):
                    return [
                        "user": pluginValueObject(data.fullUser),
                        "users": data.users.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) }
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.readHistory":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let maxId = (payload["max_id"] as? NSNumber)?.int32Value ?? Int32.max - 1
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.readHistory(peer: inputPeer, maxId: maxId))
            |> map { _ -> [String: Any]? in
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "channels.joinChannel":
        let rawPeer = (payload["channel"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputChannel? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputChannel(peer)
        }
        |> mapToSignal { inputChannel -> Signal<[String: Any]?, NoError> in
            guard let inputChannel else {
                return .single(["error": "unknown channel"])
            }
            return account.network.request(Api.functions.channels.joinChannel(channel: inputChannel))
            |> map { _ -> [String: Any]? in
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getMessages":
        let rawIds = (payload["id"] as? [Any]) ?? (payload["ids"] as? [Any]) ?? []
        let ids = rawIds.compactMap { value -> Int32? in
            if let number = value as? NSNumber { return number.int32Value }
            if let text = value as? String { return Int32(text) }
            return nil
        }
        return account.network.request(Api.functions.messages.getMessages(
            id: ids.map { Api.InputMessage.inputMessageID(.init(id: $0)) }
        ))
        |> map { result -> [String: Any]? in
            switch result {
            case let .messages(data):
                return [
                    "messages": data.messages.map { pluginValueObject($0) },
                    "users": data.users.map { pluginValueObject($0) },
                    "chats": data.chats.map { pluginValueObject($0) }
                ]
            case let .messagesSlice(data):
                return [
                    "messages": data.messages.map { pluginValueObject($0) },
                    "users": data.users.map { pluginValueObject($0) },
                    "chats": data.chats.map { pluginValueObject($0) },
                    "count": Int(data.count)
                ]
            case let .channelMessages(data):
                return [
                    "messages": data.messages.map { pluginValueObject($0) },
                    "users": data.users.map { pluginValueObject($0) },
                    "chats": data.chats.map { pluginValueObject($0) },
                    "count": Int(data.count)
                ]
            case .messagesNotModified:
                return ["messages": [], "users": [], "chats": []]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.search":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let query = (payload["q"] as? String) ?? (payload["query"] as? String) ?? ""
        let limit = (payload["limit"] as? NSNumber)?.int32Value ?? 50
        let offsetId = (payload["offset_id"] as? NSNumber)?.int32Value ?? 0
        let maxId = (payload["max_id"] as? NSNumber)?.int32Value ?? 0
        let minId = (payload["min_id"] as? NSNumber)?.int32Value ?? 0
        let minDate = (payload["min_date"] as? NSNumber)?.int32Value ?? 0
        let maxDate = (payload["max_date"] as? NSNumber)?.int32Value ?? 0

        let filter: Api.MessagesFilter
        switch ((payload["filter"] as? String) ?? "").lowercased() {
        case "photos":
            filter = .inputMessagesFilterPhotos
        case "video":
            filter = .inputMessagesFilterVideo
        case "photo_video", "photovideo":
            filter = .inputMessagesFilterPhotoVideo
        case "document", "documents":
            filter = .inputMessagesFilterDocument
        case "url", "urls":
            filter = .inputMessagesFilterUrl
        case "music":
            filter = .inputMessagesFilterMusic
        case "voice":
            filter = .inputMessagesFilterVoice
        case "round_voice":
            filter = .inputMessagesFilterRoundVoice
        case "round_video":
            filter = .inputMessagesFilterRoundVideo
        case "gif":
            filter = .inputMessagesFilterGif
        case "pinned":
            filter = .inputMessagesFilterPinned
        case "poll", "polls":
            filter = .inputMessagesFilterPoll
        case "chat_photos", "chatphotos":
            filter = .inputMessagesFilterChatPhotos
        case "mentions":
            filter = .inputMessagesFilterMyMentions
        default:
            filter = .inputMessagesFilterEmpty
        }

        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.search(
                flags: 0,
                peer: inputPeer,
                q: query,
                fromId: nil,
                savedPeerId: nil,
                savedReaction: nil,
                topMsgId: nil,
                filter: filter,
                minDate: minDate,
                maxDate: maxDate,
                offsetId: offsetId,
                addOffset: 0,
                limit: limit,
                maxId: maxId,
                minId: minId,
                hash: 0
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .messages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) }
                    ]
                case let .messagesSlice(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case let .channelMessages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case .messagesNotModified:
                    return ["messages": [], "users": [], "chats": []]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getFullChat":
        let rawPeer = (payload["chat_id"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        return account.postbox.transaction { transaction -> Int64? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId), peerId.namespace == Namespaces.Peer.CloudGroup else {
                return nil
            }
            return peerId.id._internalGetInt64Value()
        }
        |> mapToSignal { chatId -> Signal<[String: Any]?, NoError> in
            guard let chatId else {
                return .single(["error": "unknown chat"])
            }
            return account.network.request(Api.functions.messages.getFullChat(chatId: chatId))
            |> map { result -> [String: Any]? in
                switch result {
                case let .chatFull(data):
                    return [
                        "fullChat": pluginValueObject(data.fullChat),
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "channels.getFullChannel":
        let rawPeer = (payload["channel"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputChannel? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputChannel(peer)
        }
        |> mapToSignal { inputChannel -> Signal<[String: Any]?, NoError> in
            guard let inputChannel else {
                return .single(["error": "unknown channel"])
            }
            return account.network.request(Api.functions.channels.getFullChannel(channel: inputChannel))
            |> map { result -> [String: Any]? in
                switch result {
                case let .chatFull(data):
                    return [
                        "fullChat": pluginValueObject(data.fullChat),
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.deleteMessages":
        let rawIds = (payload["id"] as? [Any]) ?? (payload["ids"] as? [Any]) ?? []
        let ids = rawIds.compactMap { value -> Int32? in
            if let number = value as? NSNumber { return number.int32Value }
            if let text = value as? String { return Int32(text) }
            return nil
        }
        let revoke = (payload["revoke"] as? Bool) ?? false
        return account.network.request(Api.functions.messages.deleteMessages(
            flags: revoke ? (1 << 0) : 0,
            id: ids
        ))
        |> map { result -> [String: Any]? in
            return ["ok": true, "pts": Int(result.pts), "pts_count": Int(result.ptsCount)]
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.sendReaction":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let messageId = (payload["msg_id"] as? NSNumber)?.int32Value ?? (payload["id"] as? NSNumber)?.int32Value ?? 0
        var flags: Int32 = 0
        var reactions: [Api.Reaction]? = nil
        let rawReaction = payload["reaction"]
        var reactionValues: [String] = []
        if let text = rawReaction as? String, !text.isEmpty {
            reactionValues = [text]
        } else if let list = rawReaction as? [Any] {
            reactionValues = list.compactMap { $0 as? String }.filter { !$0.isEmpty }
        }
        if !reactionValues.isEmpty {
            flags |= 1 << 0
            reactions = reactionValues.map { Api.Reaction.reactionEmoji(.init(emoticon: $0)) }
            if (payload["big"] as? Bool) == true {
                flags |= 1 << 1
            }
            if (payload["recent"] as? Bool) == true {
                flags |= 1 << 2
            }
        }
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.sendReaction(
                flags: flags,
                peer: inputPeer,
                msgId: messageId,
                reaction: reactions
            ))
            |> map { _ -> [String: Any]? in
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getPeerDialogs":
        let rawPeers = (payload["peers"] as? [Any]) ?? []
        return account.postbox.transaction { transaction -> [Api.InputDialogPeer] in
            return rawPeers.compactMap { value -> Api.InputDialogPeer? in
                let raw = (value as? NSNumber)?.int64Value ?? 0
                let peerId = pluginPeerId(fromDialogId: raw)
                guard let peer = transaction.getPeer(peerId), let inputPeer = apiInputPeer(peer) else {
                    return nil
                }
                return .inputDialogPeer(.init(peer: inputPeer))
            }
        }
        |> mapToSignal { inputPeers -> Signal<[String: Any]?, NoError> in
            guard !inputPeers.isEmpty else {
                return .single(["error": "unknown peers"])
            }
            return account.network.request(Api.functions.messages.getPeerDialogs(peers: inputPeers))
            |> map { result -> [String: Any]? in
                switch result {
                case let .peerDialogs(data):
                    return [
                        "dialogs": data.dialogs.map { pluginValueObject($0) },
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "state": pluginValueObject(data.state)
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getDialogs":
        let limit = (payload["limit"] as? NSNumber)?.int32Value ?? 50
        let offsetId = (payload["offset_id"] as? NSNumber)?.int32Value ?? 0
        let offsetDate = (payload["offset_date"] as? NSNumber)?.int32Value ?? 0
        let rawFolder = (payload["folder_id"] as? NSNumber)?.int32Value
        let folderId: Int32? = (rawFolder == nil || rawFolder == 0) ? nil : rawFolder
        var flags: Int32 = 0
        if folderId != nil {
            flags |= 1 << 1
        }
        return account.network.request(Api.functions.messages.getDialogs(
            flags: flags,
            folderId: folderId,
            offsetDate: offsetDate,
            offsetId: offsetId,
            offsetPeer: .inputPeerEmpty,
            limit: limit,
            hash: 0
        ))
        |> map { result -> [String: Any]? in
            switch result {
            case let .dialogs(data):
                return [
                    "dialogs": data.dialogs.map { pluginValueObject($0) },
                    "messages": data.messages.map { pluginValueObject($0) },
                    "chats": data.chats.map { pluginValueObject($0) },
                    "users": data.users.map { pluginValueObject($0) }
                ]
            case let .dialogsSlice(data):
                return [
                    "dialogs": data.dialogs.map { pluginValueObject($0) },
                    "messages": data.messages.map { pluginValueObject($0) },
                    "chats": data.chats.map { pluginValueObject($0) },
                    "users": data.users.map { pluginValueObject($0) },
                    "count": Int(data.count)
                ]
            case let .dialogsNotModified(count):
                return ["dialogs": [], "messages": [], "chats": [], "users": [], "count": Int(count)]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "channels.leaveChannel":
        let rawPeer = (payload["channel"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputChannel? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputChannel(peer)
        }
        |> mapToSignal { inputChannel -> Signal<[String: Any]?, NoError> in
            guard let inputChannel else {
                return .single(["error": "unknown channel"])
            }
            return account.network.request(Api.functions.channels.leaveChannel(channel: inputChannel))
            |> map { _ -> [String: Any]? in
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.forwardMessages":
        let rawFrom = (payload["from_peer"] as? NSNumber)?.int64Value ?? 0
        let rawTo = (payload["to_peer"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let rawIds = (payload["id"] as? [Any]) ?? (payload["ids"] as? [Any]) ?? []
        let ids = rawIds.compactMap { value -> Int32? in
            if let number = value as? NSNumber { return number.int32Value }
            if let text = value as? String { return Int32(text) }
            return nil
        }
        return account.postbox.transaction { transaction -> (Api.InputPeer, Api.InputPeer)? in
            let fromId = pluginPeerId(fromDialogId: rawFrom)
            let toId = pluginPeerId(fromDialogId: rawTo)
            guard let fromPeer = transaction.getPeer(fromId),
                  let toPeer = transaction.getPeer(toId),
                  let fromInput = apiInputPeer(fromPeer),
                  let toInput = apiInputPeer(toPeer) else {
                return nil
            }
            return (fromInput, toInput)
        }
        |> mapToSignal { pair -> Signal<[String: Any]?, NoError> in
            guard let pair else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.forwardMessages(
                flags: 0,
                fromPeer: pair.0,
                id: ids,
                randomId: ids.map { _ in Int64.random(in: Int64.min ... Int64.max) },
                toPeer: pair.1,
                topMsgId: nil,
                replyTo: nil,
                scheduleDate: nil,
                scheduleRepeatPeriod: nil,
                sendAs: nil,
                quickReplyShortcut: nil,
                effect: nil,
                videoTimestamp: nil,
                allowPaidStars: nil,
                suggestedPost: nil
            ))
            |> map { _ -> [String: Any]? in
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.sendMessage":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let text = (payload["message"] as? String) ?? (payload["text"] as? String) ?? ""
        let replyToId = ((payload["reply_to_msg_id"] as? NSNumber)
            ?? (payload["reply_to"] as? NSNumber)
            ?? (payload["replyToMsgId"] as? NSNumber))?.int32Value ?? 0
        let entityValues = (payload["entities"] as? [[String: Any]]) ?? []
        var flags: Int32 = (payload["flags"] as? NSNumber)?.int32Value ?? 0
        if (payload["no_webpage"] as? Bool) == true {
            flags |= 1 << 1
        }
        if (payload["silent"] as? Bool) == true {
            flags |= 1 << 5
        }
        if (payload["background"] as? Bool) == true {
            flags |= 1 << 6
        }
        if (payload["clear_draft"] as? Bool) == true {
            flags |= 1 << 7
        }
        let scheduleDate = (payload["schedule_date"] as? NSNumber)?.int32Value
        let randomId = (payload["random_id"] as? NSNumber)?.int64Value ?? Int64.random(in: Int64.min ... Int64.max)
        let replyTo: Api.InputReplyTo? = replyToId > 0 ? .inputReplyToMessage(.init(
            flags: 0,
            replyToMsgId: replyToId,
            topMsgId: nil,
            replyToPeerId: nil,
            quoteText: nil,
            quoteEntities: nil,
            quoteOffset: nil,
            monoforumPeerId: nil,
            todoItemId: nil,
            pollOption: nil,
            quoteRich: nil
        )) : nil
        return account.postbox.transaction { transaction -> (Api.InputPeer, [Api.MessageEntity])? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId), let inputPeer = apiInputPeer(peer) else {
                return nil
            }
            let entities = pluginMessageTextEntities(entityValues)
            return (inputPeer, apiEntitiesFromMessageTextEntities(entities, associatedPeers: SimpleDictionary<PeerId, Peer>()))
        }
        |> mapToSignal { pair -> Signal<[String: Any]?, NoError> in
            guard let pair else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.sendMessage(
                flags: flags,
                peer: pair.0,
                replyTo: replyTo,
                message: text,
                randomId: randomId,
                replyMarkup: pluginReplyMarkup(payload["reply_markup"]),
                entities: pair.1,
                scheduleDate: scheduleDate,
                scheduleRepeatPeriod: nil,
                sendAs: nil,
                quickReplyShortcut: nil,
                effect: nil,
                allowPaidStars: nil,
                suggestedPost: nil,
                richMessage: nil
            ))
            |> map { result -> [String: Any]? in
                return pluginValueObject(result)
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.sendMedia":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let text = (payload["message"] as? String) ?? (payload["text"] as? String) ?? ""
        let entityValues = (payload["entities"] as? [[String: Any]]) ?? []
        var flags: Int32 = (payload["flags"] as? NSNumber)?.int32Value ?? 0
        if (payload["silent"] as? Bool) == true {
            flags |= 1 << 5
        }
        if (payload["background"] as? Bool) == true {
            flags |= 1 << 6
        }
        let scheduleDate = (payload["schedule_date"] as? NSNumber)?.int32Value
        let randomId = (payload["random_id"] as? NSNumber)?.int64Value ?? Int64.random(in: Int64.min ... Int64.max)
        let mediaValues = (payload["media"] as? [String: Any]) ?? [:]
        let mediaName = ((mediaValues["_"] as? String) ?? (payload["media_type"] as? String) ?? "").lowercased()
        let inputMedia: Api.InputMedia?
        switch mediaName {
        case "inputmediageopoint", "input_media_geo_point", "geo", "location":
            let point = (mediaValues["geo_point"] as? [String: Any]) ?? mediaValues
            let latitude = (point["lat"] as? NSNumber)?.doubleValue ?? 0.0
            let longitude = (point["long"] as? NSNumber)?.doubleValue ?? (point["lon"] as? NSNumber)?.doubleValue ?? 0.0
            var geoFlags: Int32 = 0
            var accuracyRadius: Int32?
            if let value = (point["accuracy_radius"] as? NSNumber)?.intValue {
                geoFlags |= 1 << 0
                accuracyRadius = Int32(value)
            }
            inputMedia = .inputMediaGeoPoint(.init(geoPoint: Api.InputGeoPoint.inputGeoPoint(.init(flags: geoFlags, lat: latitude, long: longitude, accuracyRadius: accuracyRadius))))
        case "inputmediacontact", "input_media_contact", "contact":
            inputMedia = .inputMediaContact(.init(
                phoneNumber: (mediaValues["phone_number"] as? String) ?? (mediaValues["phone"] as? String) ?? "",
                firstName: (mediaValues["first_name"] as? String) ?? "",
                lastName: (mediaValues["last_name"] as? String) ?? "",
                vcard: (mediaValues["vcard"] as? String) ?? ""
            ))
        case "inputmediavenue", "input_media_venue", "venue":
            let point = (mediaValues["geo_point"] as? [String: Any]) ?? mediaValues
            let latitude = (point["lat"] as? NSNumber)?.doubleValue ?? 0.0
            let longitude = (point["long"] as? NSNumber)?.doubleValue ?? (point["lon"] as? NSNumber)?.doubleValue ?? 0.0
            inputMedia = .inputMediaVenue(.init(
                geoPoint: Api.InputGeoPoint.inputGeoPoint(.init(flags: 0, lat: latitude, long: longitude, accuracyRadius: nil)),
                title: (mediaValues["title"] as? String) ?? "",
                address: (mediaValues["address"] as? String) ?? "",
                provider: (mediaValues["provider"] as? String) ?? "",
                venueId: (mediaValues["venue_id"] as? String) ?? (mediaValues["venueId"] as? String) ?? "",
                venueType: (mediaValues["venue_type"] as? String) ?? (mediaValues["venueType"] as? String) ?? ""
            ))
        case "inputmediadice", "input_media_dice", "dice":
            inputMedia = .inputMediaDice(.init(emoticon: (mediaValues["emoticon"] as? String) ?? "🎲"))
        case "inputmediadocument", "input_media_document", "document", "sticker":
            let nestedId = mediaValues["id"] as? [String: Any]
            let documentId = (mediaValues["id"] as? NSNumber)?.int64Value
                ?? (nestedId?["id"] as? NSNumber)?.int64Value
                ?? 0
            let accessHash = (mediaValues["access_hash"] as? NSNumber)?.int64Value
                ?? (nestedId?["access_hash"] as? NSNumber)?.int64Value
                ?? 0
            let fileReference = ((mediaValues["file_reference"] as? String)
                ?? (nestedId?["file_reference"] as? String))
                .flatMap { Data(base64Encoded: $0) } ?? Data()
            inputMedia = .inputMediaDocument(.init(
                flags: 0,
                id: .inputDocument(.init(
                    id: documentId,
                    accessHash: accessHash,
                    fileReference: Buffer(data: fileReference)
                )),
                videoCover: nil,
                videoTimestamp: nil,
                ttlSeconds: nil,
                query: mediaValues["query"] as? String
            ))
        case "inputmediaphoto", "input_media_photo", "photo":
            let nestedId = mediaValues["id"] as? [String: Any]
            let photoId = (mediaValues["id"] as? NSNumber)?.int64Value
                ?? (nestedId?["id"] as? NSNumber)?.int64Value
                ?? 0
            let accessHash = (mediaValues["access_hash"] as? NSNumber)?.int64Value
                ?? (nestedId?["access_hash"] as? NSNumber)?.int64Value
                ?? 0
            let fileReference = ((mediaValues["file_reference"] as? String)
                ?? (nestedId?["file_reference"] as? String))
                .flatMap { Data(base64Encoded: $0) } ?? Data()
            inputMedia = .inputMediaPhoto(.init(
                flags: 0,
                id: .inputPhoto(.init(
                    id: photoId,
                    accessHash: accessHash,
                    fileReference: Buffer(data: fileReference)
                )),
                ttlSeconds: nil,
                video: nil
            ))
        case "inputmediapoll", "input_media_poll", "poll":
            inputMedia = pluginPollInputMedia(mediaValues)
        default:
            inputMedia = nil
        }
        guard let inputMedia else {
            return .single(["error": "unsupported media"])
        }
        return account.postbox.transaction { transaction -> (Api.InputPeer, [Api.MessageEntity])? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId), let inputPeer = apiInputPeer(peer) else {
                return nil
            }
            let entities = pluginMessageTextEntities(entityValues)
            return (inputPeer, apiEntitiesFromMessageTextEntities(entities, associatedPeers: SimpleDictionary<PeerId, Peer>()))
        }
        |> mapToSignal { pair -> Signal<[String: Any]?, NoError> in
            guard let pair else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.sendMedia(
                flags: flags,
                peer: pair.0,
                replyTo: nil,
                media: inputMedia,
                message: text,
                randomId: randomId,
                replyMarkup: nil,
                entities: pair.1,
                scheduleDate: scheduleDate,
                scheduleRepeatPeriod: nil,
                sendAs: nil,
                quickReplyShortcut: nil,
                effect: nil,
                allowPaidStars: nil,
                suggestedPost: nil
            ))
            |> map { result -> [String: Any]? in
                return pluginValueObject(result)
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.editMessage":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let messageId = ((payload["id"] as? NSNumber)
            ?? (payload["message_id"] as? NSNumber)
            ?? (payload["msg_id"] as? NSNumber))?.int32Value ?? 0
        guard messageId > 0 else {
            return .single(["error": "message id is required"])
        }
        let text = (payload["message"] as? String) ?? (payload["text"] as? String)
        let entityValues = (payload["entities"] as? [[String: Any]]) ?? []
        var flags: Int32 = (payload["flags"] as? NSNumber)?.int32Value ?? 0
        if (payload["no_webpage"] as? Bool) == true {
            flags |= 1 << 1
        }
        if (payload["invert_media"] as? Bool) == true {
            flags |= 1 << 16
        }
        let scheduleDate = (payload["schedule_date"] as? NSNumber)?.int32Value
        let mediaPath = payload["path"] as? String
        let mediaKind = ((payload["kind"] as? String) ?? "photo").lowercased()
        let editMediaValues = (payload["media"] as? [String: Any]) ?? [:]
        let editMediaName = ((editMediaValues["_"] as? String) ?? "").lowercased()
        let pollMedia: Api.InputMedia? = (
            editMediaName == "inputmediapoll"
                || editMediaName == "input_media_poll"
                || editMediaName == "poll"
        ) ? pluginPollInputMedia(editMediaValues) : nil
        var mediaSignal: Signal<Api.InputMedia?, String> = .single(pollMedia)
        if let mediaPath {
            guard let data = try? Data(contentsOf: URL(fileURLWithPath: mediaPath)) else {
                return .single(["error": "cannot read the media file"])
            }
            if mediaKind == "photo" || mediaKind == "image" {
                mediaSignal = uploadedImage(account: account, data: data)
                |> map { event -> Api.InputMedia? in
                    if case let .result(media) = event {
                        return media
                    }
                    return nil
                }
                |> mapError { _ -> String in
                    return "media upload failed"
                }
            } else {
                let fileName = URL(fileURLWithPath: mediaPath).lastPathComponent
                mediaSignal = uploadedFile(
                    account: account,
                    data: data,
                    mimeType: pluginMediaMimeType(for: mediaPath),
                    attributes: [.FileName(fileName: fileName)]
                )
                |> map { event -> Api.InputMedia? in
                    if case let .result(media) = event {
                        return media
                    }
                    return nil
                }
                |> mapError { _ -> String in
                    return "media upload failed"
                }
            }
        }
        return account.postbox.transaction { transaction -> (Api.InputPeer, [Api.MessageEntity])? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId), let inputPeer = apiInputPeer(peer) else {
                return nil
            }
            let entities = pluginMessageTextEntities(entityValues)
            return (inputPeer, apiEntitiesFromMessageTextEntities(entities, associatedPeers: SimpleDictionary<PeerId, Peer>()))
        }
        |> mapToSignal { pair -> Signal<[String: Any]?, NoError> in
            guard let pair else {
                return .single(["error": "unknown peer"])
            }
            return mediaSignal
            |> mapToSignal { media -> Signal<[String: Any]?, NoError> in
                if mediaPath != nil && media == nil {
                    return .single(["error": "media upload failed"])
                }
                var requestFlags = flags
                if media != nil {
                    requestFlags |= Int32(1 << 14)
                }
                return account.network.request(Api.functions.messages.editMessage(
                    flags: requestFlags,
                    peer: pair.0,
                    id: messageId,
                    message: text,
                    media: media,
                    replyMarkup: nil,
                    entities: pair.1,
                    scheduleDate: scheduleDate,
                    scheduleRepeatPeriod: nil,
                    quickReplyShortcutId: nil,
                    richMessage: nil
                ))
                |> map { result -> [String: Any]? in
                    return pluginValueObject(result)
                }
                |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                    return .single(["error": "request failed"])
                }
            }
            |> `catch` { message -> Signal<[String: Any]?, NoError> in
                return .single(["error": message])
            }
        }

    case "messages.sendVote":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let messageId = (payload["msg_id"] as? NSNumber)?.int32Value ?? (payload["id"] as? NSNumber)?.int32Value ?? 0
        let rawOptions = (payload["options"] as? [Any]) ?? []
        let options = rawOptions.compactMap { value -> Buffer? in
            if let text = value as? String, let data = Data(base64Encoded: text) {
                return Buffer(data: data)
            }
            if let text = value as? String {
                return Buffer(data: Data(text.utf8))
            }
            if let number = value as? NSNumber {
                return Buffer(data: Data([UInt8(truncatingIfNeeded: number.intValue)]))
            }
            return nil
        }
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.sendVote(
                peer: inputPeer,
                msgId: messageId,
                options: options
            ))
            |> map { result -> [String: Any]? in
                return pluginValueObject(result)
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getBotCallbackAnswer":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let messageId = (payload["msg_id"] as? NSNumber)?.int32Value ?? (payload["id"] as? NSNumber)?.int32Value ?? 0
        let dataText = (payload["data"] as? String) ?? ""
        let callbackData = Data(base64Encoded: dataText) ?? Data(dataText.utf8)
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.getBotCallbackAnswer(
                flags: callbackData.isEmpty ? 0 : (1 << 0),
                peer: inputPeer,
                msgId: messageId,
                data: callbackData.isEmpty ? nil : Buffer(data: callbackData),
                password: .inputCheckPasswordEmpty
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .botCallbackAnswer(answer):
                    return [
                        "message": answer.message ?? "",
                        "url": answer.url ?? "",
                        "alert": (answer.flags & (1 << 1)) != 0
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.deleteHistory":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let maxId = (payload["max_id"] as? NSNumber)?.int32Value ?? Int32.max - 1
        let justClear = (payload["just_clear"] as? Bool) == true
        let revoke = (payload["revoke"] as? Bool) ?? false
        let minDate = (payload["min_date"] as? NSNumber)?.int32Value
        let maxDate = (payload["max_date"] as? NSNumber)?.int32Value
        var flags: Int32 = 0
        if justClear {
            flags |= 1 << 0
        }
        if revoke {
            flags |= 1 << 1
        }
        if minDate != nil {
            flags |= 1 << 2
        }
        if maxDate != nil {
            flags |= 1 << 3
        }
        let effectiveMaxId: Int32 = (minDate != nil || maxDate != nil) ? 0 : maxId
        return account.postbox.transaction { transaction -> [String: Any]? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else {
                return ["error": "unknown peer"]
            }
            if peerId.namespace == Namespaces.Peer.CloudChannel, let inputChannel = apiInputChannel(peer) {
                return ["channel": inputChannel]
            }
            guard let inputPeer = apiInputPeer(peer) else {
                return ["error": "unknown peer"]
            }
            return ["peer": inputPeer]
        }
        |> mapToSignal { value -> Signal<[String: Any]?, NoError> in
            guard let value else {
                return .single(["error": "request failed"])
            }
            if let error = value["error"] as? String {
                return .single(["error": error])
            }
            if let channel = value["channel"] as? Api.InputChannel {
                return account.network.request(Api.functions.channels.deleteHistory(
                    flags: flags,
                    channel: channel,
                    maxId: effectiveMaxId
                ))
                |> map { _ -> [String: Any]? in
                    return ["ok": true]
                }
                |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                    return .single(["error": "request failed"])
                }
            }
            guard let inputPeer = value["peer"] as? Api.InputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.deleteHistory(
                flags: flags,
                peer: inputPeer,
                maxId: effectiveMaxId,
                minDate: minDate,
                maxDate: maxDate
            ))
            |> map { result -> [String: Any]? in
                if let result {
                    return [
                        "ok": true,
                        "pts": Int(result.pts),
                        "pts_count": Int(result.ptsCount)
                    ]
                }
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.markDialogUnread":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let unread = (payload["unread"] as? Bool) ?? true
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.markDialogUnread(
                flags: unread ? (1 << 0) : 0,
                parentPeer: nil,
                peer: .inputDialogPeer(.init(peer: inputPeer))
            ))
            |> map { _ -> [String: Any]? in
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "account.updateNotifySettings":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let muteUntil = (payload["mute_until"] as? NSNumber)?.int32Value ?? 0
        let showPreviews = (payload["show_previews"] as? Bool) ?? true
        let storiesMuted = (payload["stories_muted"] as? Bool)
        var flags: Int32 = (1 << 0) | (1 << 2)
        if storiesMuted != nil {
            flags |= 1 << 6
        }
        let settings = Api.InputPeerNotifySettings.inputPeerNotifySettings(.init(
            flags: flags,
            showPreviews: showPreviews ? .boolTrue : .boolFalse,
            silent: nil,
            muteUntil: muteUntil,
            sound: nil,
            storiesMuted: storiesMuted.map { $0 ? .boolTrue : .boolFalse },
            storiesHideSender: nil,
            storiesSound: nil
        ))
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.account.updateNotifySettings(
                peer: .inputNotifyPeer(.init(peer: inputPeer)),
                settings: settings
            ))
            |> map { _ -> [String: Any]? in
                return ["ok": true]
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.updatePinnedMessage":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let messageId = ((payload["id"] as? NSNumber)
            ?? (payload["message_id"] as? NSNumber))?.int32Value ?? 0
        var flags: Int32 = 0
        if (payload["silent"] as? Bool) == true {
            flags |= 1 << 0
        }
        if (payload["unpin"] as? Bool) == true || messageId == 0 {
            flags |= 1 << 1
        }
        if (payload["for_this_peer_only"] as? Bool) == true {
            flags |= 1 << 2
        }
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.updatePinnedMessage(
                flags: flags,
                peer: inputPeer,
                id: messageId
            ))
            |> map { result -> [String: Any]? in
                return pluginValueObject(result)
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "contacts.block", "contacts.unblock":
        let rawPeer = (payload["id"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let blocking = name == "contacts.block"
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            let signal: Signal<[String: Any]?, NoError>
            if blocking {
                signal = account.network.request(Api.functions.contacts.block(flags: 0, id: inputPeer))
                |> map { _ -> [String: Any]? in
                    return ["ok": true]
                }
                |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                    return .single(["error": "request failed"])
                }
            } else {
                signal = account.network.request(Api.functions.contacts.unblock(flags: 0, id: inputPeer))
                |> map { _ -> [String: Any]? in
                    return ["ok": true]
                }
                |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                    return .single(["error": "request failed"])
                }
            }
            return signal
        }

    case "contacts.addContact":
        let rawPeer = (payload["id"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let firstName = (payload["first_name"] as? String) ?? ""
        let lastName = (payload["last_name"] as? String) ?? ""
        let phone = (payload["phone"] as? String) ?? ""
        let noteText = (payload["note"] as? String) ?? ""
        var flags: Int32 = 0
        var note: Api.TextWithEntities?
        if !noteText.isEmpty {
            flags |= 1 << 1
            note = .textWithEntities(.init(text: noteText, entities: []))
        }
        return account.postbox.transaction { transaction -> Api.InputUser? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputUser(peer)
        }
        |> mapToSignal { inputUser -> Signal<[String: Any]?, NoError> in
            guard let inputUser else {
                return .single(["error": "unknown user"])
            }
            return account.network.request(Api.functions.contacts.addContact(
                flags: flags,
                id: inputUser,
                firstName: firstName,
                lastName: lastName,
                phone: phone,
                note: note
            ))
            |> map { result -> [String: Any]? in
                return pluginValueObject(result)
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "contacts.deleteContacts":
        let rawIds = (payload["id"] as? [Any]) ?? (payload["ids"] as? [Any]) ?? []
        let ids = rawIds.compactMap { value -> Int64? in
            if let number = value as? NSNumber { return number.int64Value }
            if let text = value as? String { return Int64(text) }
            return nil
        }
        return account.postbox.transaction { transaction -> [Api.InputUser]? in
            var users: [Api.InputUser] = []
            for rawId in ids {
                let peerId = pluginPeerId(fromDialogId: rawId)
                if let peer = transaction.getPeer(peerId), let inputUser = apiInputUser(peer) {
                    users.append(inputUser)
                }
            }
            return users.isEmpty ? nil : users
        }
        |> mapToSignal { inputUsers -> Signal<[String: Any]?, NoError> in
            guard let inputUsers else {
                return .single(["error": "unknown users"])
            }
            return account.network.request(Api.functions.contacts.deleteContacts(id: inputUsers))
            |> map { result -> [String: Any]? in
                return pluginValueObject(result)
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "contacts.importContacts":
        let contactValues = (payload["contacts"] as? [[String: Any]]) ?? []
        let inputs = contactValues.map { item -> Api.InputContact in
            .inputPhoneContact(.init(
                flags: 0,
                clientId: (item["client_id"] as? NSNumber)?.int64Value ?? Int64.random(in: Int64.min ... Int64.max),
                phone: (item["phone"] as? String) ?? "",
                firstName: (item["first_name"] as? String) ?? "",
                lastName: (item["last_name"] as? String) ?? "",
                note: nil
            ))
        }
        guard !inputs.isEmpty else {
            return .single(["error": "no contacts"])
        }
        return account.network.request(Api.functions.contacts.importContacts(contacts: inputs))
        |> map { result -> [String: Any]? in
            return pluginValueObject(result)
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "photos.getUserPhotos":
        let rawPeer = (payload["id"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let offset = (payload["offset"] as? NSNumber)?.int32Value ?? 0
        let maxId = (payload["max_id"] as? NSNumber)?.int32Value ?? 0
        let limit = (payload["limit"] as? NSNumber)?.int32Value ?? 100
        return account.postbox.transaction { transaction -> Api.InputUser? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputUser(peer)
        }
        |> mapToSignal { inputUser -> Signal<[String: Any]?, NoError> in
            guard let inputUser else {
                return .single(["error": "unknown user"])
            }
            return account.network.request(Api.functions.photos.getUserPhotos(
                userId: inputUser,
                offset: offset,
                maxId: maxId,
                limit: limit
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .photos(data):
                    return [
                        "photos": data.photos.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                case let .photosSlice(data):
                    return [
                        "count": Int(data.count),
                        "photos": data.photos.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getPeerSettings":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.getPeerSettings(peer: inputPeer))
            |> map { result -> [String: Any]? in
                switch result {
                case let .peerSettings(data):
                    return [
                        "settings": pluginValueObject(data.settings),
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getDialogFilters":
        return account.network.request(Api.functions.messages.getDialogFilters())
        |> map { result -> [String: Any]? in
            switch result {
            case let .dialogFilters(data):
                return [
                    "flags": data.flags,
                    "filters": data.filters.map { pluginValueObject($0) }
                ]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getMessagesViews":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let rawIds = (payload["id"] as? [Any]) ?? (payload["ids"] as? [Any]) ?? []
        let ids = rawIds.compactMap { value -> Int32? in
            if let number = value as? NSNumber { return number.int32Value }
            if let text = value as? String { return Int32(text) }
            return nil
        }
        guard !ids.isEmpty else {
            return .single(["views": [Any]()])
        }
        let increment = (payload["increment"] as? Bool) ?? false
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.getMessagesViews(
                peer: inputPeer,
                id: ids,
                increment: increment ? .boolTrue : .boolFalse
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .messageViews(data):
                    return [
                        "views": data.views.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getPinnedDialogs":
        let folderId = (payload["folder_id"] as? NSNumber)?.int32Value ?? 0
        return account.network.request(Api.functions.messages.getPinnedDialogs(folderId: folderId))
        |> map { result -> [String: Any]? in
            switch result {
            case let .peerDialogs(data):
                return [
                    "dialogs": data.dialogs.map { pluginValueObject($0) },
                    "messages": data.messages.map { pluginValueObject($0) },
                    "chats": data.chats.map { pluginValueObject($0) },
                    "users": data.users.map { pluginValueObject($0) },
                    "state": pluginValueObject(data.state)
                ]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getCommonChats":
        let rawPeer = (payload["user_id"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let maxId = (payload["max_id"] as? NSNumber)?.int64Value ?? 0
        let limit = min(max((payload["limit"] as? NSNumber)?.int32Value ?? 100, 1), 100)
        return account.postbox.transaction { transaction -> Api.InputUser? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputUser(peer)
        }
        |> mapToSignal { inputUser -> Signal<[String: Any]?, NoError> in
            guard let inputUser else {
                return .single(["error": "unknown user"])
            }
            return account.network.request(Api.functions.messages.getCommonChats(
                userId: inputUser,
                maxId: maxId,
                limit: limit
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .chats(data):
                    return [
                        "chats": data.chats.map { pluginValueObject($0) },
                        "count": data.chats.count
                    ]
                case let .chatsSlice(data):
                    return [
                        "chats": data.chats.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getFeaturedStickers":
        let hash = (payload["hash"] as? NSNumber)?.int64Value ?? 0
        return account.network.request(Api.functions.messages.getFeaturedStickers(hash: hash))
        |> map { result -> [String: Any]? in
            switch result {
            case let .featuredStickers(data):
                return [
                    "sets": data.sets.map { pluginValueObject($0) },
                    "unread": data.unread.map { Int($0) },
                    "notModified": false
                ]
            case .featuredStickersNotModified:
                return ["sets": [Any](), "notModified": true]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getRecentStickers":
        let hash = (payload["hash"] as? NSNumber)?.int64Value ?? 0
        return account.network.request(Api.functions.messages.getRecentStickers(flags: 0, hash: hash))
        |> map { result -> [String: Any]? in
            switch result {
            case let .recentStickers(data):
                return [
                    "stickers": data.stickers.map { pluginValueObject($0) },
                    "notModified": false
                ]
            case .recentStickersNotModified:
                return ["stickers": [Any](), "notModified": true]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.saveRecentSticker", "messages.faveSticker":
        let documentId = (payload["id"] as? NSNumber)?.int64Value ?? 0
        let accessHash = (payload["access_hash"] as? NSNumber)?.int64Value ?? 0
        let fileReference = (payload["file_reference"] as? String).flatMap { Data(base64Encoded: $0) } ?? Data()
        let input = Api.InputDocument.inputDocument(.init(
            id: documentId,
            accessHash: accessHash,
            fileReference: Buffer(data: fileReference)
        ))
        let negative = (payload["unsave"] as? Bool) == true || (payload["unfave"] as? Bool) == true
        let signal: Signal<Api.Bool, MTRpcError>
        if name == "messages.faveSticker" {
            signal = account.network.request(Api.functions.messages.faveSticker(
                id: input,
                unfave: negative ? .boolTrue : .boolFalse
            ))
        } else {
            signal = account.network.request(Api.functions.messages.saveRecentSticker(
                flags: 0,
                id: input,
                unsave: negative ? .boolTrue : .boolFalse
            ))
        }
        return signal
        |> map { _ -> [String: Any]? in
            return ["ok": true]
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getAllStickers":
        let hash = (payload["hash"] as? NSNumber)?.int64Value ?? 0
        return account.network.request(Api.functions.messages.getAllStickers(hash: hash))
        |> map { result -> [String: Any]? in
            switch result {
            case let .allStickers(data):
                return [
                    "sets": data.sets.map { pluginValueObject($0) },
                    "hash": data.hash
                ]
            case .allStickersNotModified:
                return ["sets": [Any](), "notModified": true]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getStickers":
        let emoticon = (payload["emoticon"] as? String) ?? ""
        let hash = (payload["hash"] as? NSNumber)?.int64Value ?? 0
        return account.network.request(Api.functions.messages.getStickers(emoticon: emoticon, hash: hash))
        |> map { result -> [String: Any]? in
            switch result {
            case let .stickers(data):
                return [
                    "stickers": data.stickers.map { pluginValueObject($0) },
                    "hash": data.hash
                ]
            case .stickersNotModified:
                return ["stickers": [Any](), "notModified": true]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getSavedGifs":
        let hash = (payload["hash"] as? NSNumber)?.int64Value ?? 0
        return account.network.request(Api.functions.messages.getSavedGifs(hash: hash))
        |> map { result -> [String: Any]? in
            switch result {
            case let .savedGifs(data):
                return [
                    "gifs": data.gifs.map { pluginValueObject($0) },
                    "hash": data.hash
                ]
            case .savedGifsNotModified:
                return ["gifs": [Any](), "notModified": true]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getFavedStickers":
        let hash = (payload["hash"] as? NSNumber)?.int64Value ?? 0
        return account.network.request(Api.functions.messages.getFavedStickers(hash: hash))
        |> map { result -> [String: Any]? in
            switch result {
            case let .favedStickers(data):
                return [
                    "packs": data.packs.map { pluginValueObject($0) },
                    "stickers": data.stickers.map { pluginValueObject($0) },
                    "hash": data.hash
                ]
            case .favedStickersNotModified:
                return ["notModified": true]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getStickerSet":
        let rawSet = (payload["stickerset"] as? [String: Any]) ?? [:]
        let shortName = (rawSet["short_name"] as? String) ?? (payload["short_name"] as? String) ?? ""
        let input: Api.InputStickerSet
        if !shortName.isEmpty {
            input = .inputStickerSetShortName(.init(shortName: shortName))
        } else {
            let setId = (rawSet["id"] as? NSNumber)?.int64Value ?? (payload["id"] as? NSNumber)?.int64Value ?? 0
            let accessHash = (rawSet["access_hash"] as? NSNumber)?.int64Value ?? (payload["access_hash"] as? NSNumber)?.int64Value ?? 0
            input = .inputStickerSetID(.init(id: setId, accessHash: accessHash))
        }
        let hash = (payload["hash"] as? NSNumber)?.int32Value ?? 0
        return account.network.request(Api.functions.messages.getStickerSet(stickerset: input, hash: hash))
        |> map { result -> [String: Any]? in
            switch result {
            case let .stickerSet(data):
                return [
                    "set": pluginValueObject(data.set),
                    "packs": data.packs.map { pluginValueObject($0) },
                    "keywords": data.keywords.map { pluginValueObject($0) },
                    "documents": data.documents.map { pluginValueObject($0) }
                ]
            case .stickerSetNotModified:
                return ["notModified": true]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "channels.getMessages":
        let rawChannel = (payload["channel"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let rawIds = (payload["id"] as? [Any]) ?? (payload["ids"] as? [Any]) ?? []
        let ids = rawIds.compactMap { value -> Int32? in
            if let number = value as? NSNumber { return number.int32Value }
            if let text = value as? String { return Int32(text) }
            return nil
        }
        return account.postbox.transaction { transaction -> Api.InputChannel? in
            let peerId = pluginPeerId(fromDialogId: rawChannel)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputChannel(peer)
        }
        |> mapToSignal { inputChannel -> Signal<[String: Any]?, NoError> in
            guard let inputChannel else {
                return .single(["error": "unknown channel"])
            }
            return account.network.request(Api.functions.channels.getMessages(
                channel: inputChannel,
                id: ids.map { Api.InputMessage.inputMessageID(.init(id: $0)) }
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .channelMessages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                case let .messages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                case let .messagesSlice(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case .messagesNotModified:
                    return ["messages": [Any](), "chats": [Any](), "users": [Any]()]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.searchStickers":
        let query = (payload["q"] as? String) ?? (payload["query"] as? String) ?? ""
        let emoticon = (payload["emoticon"] as? String) ?? ""
        let langCode = (payload["lang_code"] as? [Any])?.compactMap { $0 as? String } ?? []
        let offset = (payload["offset"] as? NSNumber)?.int32Value ?? 0
        let requestedLimit = (payload["limit"] as? NSNumber)?.int32Value ?? 128
        let limit = max(1, min(requestedLimit, 200))
        let hash = (payload["hash"] as? NSNumber)?.int64Value ?? 0
        return account.network.request(Api.functions.messages.searchStickers(
            flags: 0,
            q: query,
            emoticon: emoticon,
            langCode: langCode,
            offset: offset,
            limit: limit,
            hash: hash
        ))
        |> map { result -> [String: Any]? in
            switch result {
            case let .foundStickers(data):
                return [
                    "stickers": data.stickers.map { pluginValueObject($0) },
                    "hash": data.hash,
                    "next_offset": data.nextOffset.map { $0 as Any } ?? NSNull()
                ]
            case let .foundStickersNotModified(data):
                return [
                    "stickers": [Any](),
                    "notModified": true,
                    "next_offset": data.nextOffset.map { $0 as Any } ?? NSNull()
                ]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "channels.getParticipants":
        let rawChannel = (payload["channel"] as? NSNumber)?.int64Value ?? (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let offset = (payload["offset"] as? NSNumber)?.int32Value ?? 0
        let requestedLimit = (payload["limit"] as? NSNumber)?.int32Value ?? 100
        let limit = max(1, min(requestedLimit, 200))
        let hash = (payload["hash"] as? NSNumber)?.int64Value ?? 0
        let filterName = ((payload["filter"] as? String) ?? "recent").lowercased()
        let query = (payload["q"] as? String) ?? ""
        let filter: Api.ChannelParticipantsFilter
        switch filterName {
        case "admins":
            filter = .channelParticipantsAdmins
        case "bots":
            filter = .channelParticipantsBots
        case "search", "recent_search":
            filter = .channelParticipantsSearch(Api.ChannelParticipantsFilter.Cons_channelParticipantsSearch(q: query))
        case "contacts":
            filter = .channelParticipantsContacts(Api.ChannelParticipantsFilter.Cons_channelParticipantsContacts(q: query))
        case "banned", "restricted":
            filter = .channelParticipantsBanned(Api.ChannelParticipantsFilter.Cons_channelParticipantsBanned(q: query))
        case "kicked":
            filter = .channelParticipantsKicked(Api.ChannelParticipantsFilter.Cons_channelParticipantsKicked(q: query))
        case "mentions":
            filter = .channelParticipantsMentions(Api.ChannelParticipantsFilter.Cons_channelParticipantsMentions(
                flags: query.isEmpty ? 0 : (1 << 0),
                q: query.isEmpty ? nil : query,
                topMsgId: nil
            ))
        default:
            filter = .channelParticipantsRecent
        }
        return account.postbox.transaction { transaction -> Api.InputChannel? in
            let peerId = pluginPeerId(fromDialogId: rawChannel)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputChannel(peer)
        }
        |> mapToSignal { inputChannel -> Signal<[String: Any]?, NoError> in
            guard let inputChannel else {
                return .single(["error": "unknown channel"])
            }
            return account.network.request(Api.functions.channels.getParticipants(
                channel: inputChannel,
                filter: filter,
                offset: offset,
                limit: limit,
                hash: hash
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .channelParticipants(data):
                    return [
                        "count": Int(data.count),
                        "participants": data.participants.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                case .channelParticipantsNotModified:
                    return ["notModified": true, "participants": [Any]()]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.installStickerSet":
        let input = pluginInputStickerSet(payload)
        let archived = (payload["archived"] as? Bool) ?? false
        return account.network.request(Api.functions.messages.installStickerSet(
            stickerset: input,
            archived: archived ? .boolTrue : .boolFalse
        ))
        |> map { result -> [String: Any]? in
            switch result {
            case .stickerSetInstallResultSuccess:
                return ["success": true]
            case let .stickerSetInstallResultArchive(data):
                return [
                    "success": true,
                    "archived": data.sets.map { pluginValueObject($0) }
                ]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.uninstallStickerSet":
        let input = pluginInputStickerSet(payload)
        return account.network.request(Api.functions.messages.uninstallStickerSet(stickerset: input))
        |> map { _ -> [String: Any]? in
            return ["ok": true]
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getArchivedStickers":
        let flags = (payload["flags"] as? NSNumber)?.int32Value ?? 0
        let offsetId = (payload["offset_id"] as? NSNumber)?.int64Value ?? 0
        let requestedLimit = (payload["limit"] as? NSNumber)?.int32Value ?? 200
        let limit = max(1, min(requestedLimit, 200))
        return account.network.request(Api.functions.messages.getArchivedStickers(
            flags: flags,
            offsetId: offsetId,
            limit: limit
        ))
        |> map { result -> [String: Any]? in
            switch result {
            case let .archivedStickers(data):
                return [
                    "sets": data.sets.map { pluginValueObject($0) },
                    "count": Int(data.count)
                ]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.getEmojiKeywordsDifference":
        let langCode = (payload["lang_code"] as? String) ?? (payload["langCode"] as? String) ?? "en"
        let fromVersion = (payload["from_version"] as? NSNumber)?.int32Value ?? 0
        return account.network.request(Api.functions.messages.getEmojiKeywordsDifference(
            langCode: langCode,
            fromVersion: fromVersion
        ))
        |> map { result -> [String: Any]? in
            switch result {
            case let .emojiKeywordsDifference(data):
                return [
                    "lang_code": data.langCode,
                    "from_version": data.fromVersion,
                    "version": data.version,
                    "keywords": data.keywords.map { pluginValueObject($0) }
                ]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "account.updateStatus":
        let offline = (payload["offline"] as? Bool) ?? false
        return account.network.request(Api.functions.account.updateStatus(
            offline: offline ? .boolTrue : .boolFalse
        ))
        |> map { _ -> [String: Any]? in
            return ["ok": true]
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.readMentions":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.readMentions(peer: inputPeer))
            |> map { result -> [String: Any]? in
                switch result {
                case let .affectedMessages(data):
                    return ["pts": data.pts, "pts_count": data.ptsCount]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.readReactions":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.readReactions(
                flags: 0,
                peer: inputPeer,
                topMsgId: nil,
                savedPeerId: nil
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .affectedHistory(data):
                    return [
                        "pts": data.pts,
                        "pts_count": data.ptsCount,
                        "offset": data.offset
                    ]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getUnreadMentions":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let offsetId = (payload["offset_id"] as? NSNumber)?.int32Value ?? 0
        let addOffset = (payload["add_offset"] as? NSNumber)?.int32Value ?? 0
        let limit = (payload["limit"] as? NSNumber)?.int32Value ?? 100
        let maxId = (payload["max_id"] as? NSNumber)?.int32Value ?? 0
        let minId = (payload["min_id"] as? NSNumber)?.int32Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.getUnreadMentions(
                flags: 0,
                peer: inputPeer,
                topMsgId: nil,
                offsetId: offsetId,
                addOffset: addOffset,
                limit: limit,
                maxId: maxId,
                minId: minId
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .messages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                case let .messagesSlice(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case let .channelMessages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case .messagesNotModified:
                    return ["messages": [Any](), "chats": [Any](), "users": [Any]()]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "messages.getUnreadReactions":
        let rawPeer = (payload["peer"] as? NSNumber)?.int64Value ?? 0
        let offsetId = (payload["offset_id"] as? NSNumber)?.int32Value ?? 0
        let addOffset = (payload["add_offset"] as? NSNumber)?.int32Value ?? 0
        let limit = (payload["limit"] as? NSNumber)?.int32Value ?? 100
        let maxId = (payload["max_id"] as? NSNumber)?.int32Value ?? 0
        let minId = (payload["min_id"] as? NSNumber)?.int32Value ?? 0
        return account.postbox.transaction { transaction -> Api.InputPeer? in
            let peerId = pluginPeerId(fromDialogId: rawPeer)
            guard let peer = transaction.getPeer(peerId) else { return nil }
            return apiInputPeer(peer)
        }
        |> mapToSignal { inputPeer -> Signal<[String: Any]?, NoError> in
            guard let inputPeer else {
                return .single(["error": "unknown peer"])
            }
            return account.network.request(Api.functions.messages.getUnreadReactions(
                flags: 0,
                peer: inputPeer,
                topMsgId: nil,
                savedPeerId: nil,
                offsetId: offsetId,
                addOffset: addOffset,
                limit: limit,
                maxId: maxId,
                minId: minId
            ))
            |> map { result -> [String: Any]? in
                switch result {
                case let .messages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) }
                    ]
                case let .messagesSlice(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case let .channelMessages(data):
                    return [
                        "messages": data.messages.map { pluginValueObject($0) },
                        "chats": data.chats.map { pluginValueObject($0) },
                        "users": data.users.map { pluginValueObject($0) },
                        "count": Int(data.count)
                    ]
                case .messagesNotModified:
                    return ["messages": [Any](), "chats": [Any](), "users": [Any]()]
                }
            }
            |> `catch` { _ -> Signal<[String: Any]?, NoError> in
                return .single(["error": "request failed"])
            }
        }

    case "upload.getFile":
        let documentId = (payload["id"] as? NSNumber)?.int64Value ?? 0
        let accessHash = (payload["access_hash"] as? NSNumber)?.int64Value ?? 0
        let offset = (payload["offset"] as? NSNumber)?.int64Value ?? 0
        let requestedLimit = (payload["limit"] as? NSNumber)?.int32Value ?? (128 * 1024)
        let limit = max(1, min(requestedLimit, 512 * 1024))
        let referenceText = (payload["file_reference"] as? String) ?? ""
        let reference = Data(base64Encoded: referenceText) ?? Data()
        let kind = (payload["kind"] as? String) ?? "document"
        let thumbSize = (payload["thumb_size"] as? String) ?? ""
        let location: Api.InputFileLocation
        if kind == "photo" {
            location = .inputPhotoFileLocation(.init(
                id: documentId,
                accessHash: accessHash,
                fileReference: Buffer(data: reference),
                thumbSize: thumbSize
            ))
        } else {
            location = .inputDocumentFileLocation(.init(
                id: documentId,
                accessHash: accessHash,
                fileReference: Buffer(data: reference),
                thumbSize: ""
            ))
        }
        return account.network.request(Api.functions.upload.getFile(
            flags: 0,
            location: location,
            offset: offset,
            limit: limit
        ))
        |> map { result -> [String: Any]? in
            switch result {
            case let .file(data):
                return [
                    "bytes": data.bytes.makeData().base64EncodedString(),
                    "type": "file"
                ]
            case .fileCdnRedirect(_):
                return ["error": "CDN redirect is not supported"]
            }
        }
        |> `catch` { _ -> Signal<[String: Any]?, NoError> in
            return .single(["error": "request failed"])
        }

    case "messages.translateText":
        var texts: [String] = []
        if let raw = payload["text"] as? [Any] {
            for item in raw {
                if let value = item as? String {
                    texts.append(value)
                } else if let object = item as? [String: Any], let value = object["text"] as? String {
                    texts.append(value)
                }
            }
        } else if let value = payload["text"] as? String {
            texts.append(value)
        }
        let toLang = (payload["to_lang"] as? String) ?? (payload["toLang"] as? String) ?? "en"
        guard !texts.isEmpty else {
            return .single(["results": [Any]()])
        }
        let apiTexts: [Api.TextWithEntities] = texts.map { value in
            return .textWithEntities(.init(text: value, entities: []))
        }
        return account.network.request(Api.functions.messages.translateText(
            flags: 2,
            peer: nil,
            id: nil,
            text: apiTexts,
            toLang: toLang,
            tone: nil
        ))
        |> map { result -> [String: Any]? in
            switch result {
            case let .translateResult(data):
                var values: [Any] = []
                for item in data.result {
                    switch item {
                    case let .textWithEntities(text):
                        values.append(text.text)
                    }
                }
                return ["results": values]
            }
        }
        |> `catch` { error -> Signal<[String: Any]?, NoError> in
            return .single(["error": String(describing: error)])
        }

    default:
        return .single(["error": "unsupported request on iOS: \(name)"])
    }
}

/// Converts the entity dictionaries a plugin sends into TelegramCore's entity
/// model. The shapes are the same ones `ui.alert` and the send hooks use.
private func pluginMessageTextEntities(_ values: [[String: Any]]) -> [MessageTextEntity] {
    var entities: [MessageTextEntity] = []
    for value in values {
        guard let type = value["type"] as? String,
              let offset = (value["offset"] as? NSNumber)?.intValue,
              let length = (value["length"] as? NSNumber)?.intValue,
              offset >= 0, length > 0 else {
            continue
        }
        let range = offset ..< (offset + length)
        switch type {
        case "bold":
            entities.append(MessageTextEntity(range: range, type: .Bold))
        case "italic":
            entities.append(MessageTextEntity(range: range, type: .Italic))
        case "underline":
            entities.append(MessageTextEntity(range: range, type: .Underline))
        case "strikethrough":
            entities.append(MessageTextEntity(range: range, type: .Strikethrough))
        case "spoiler":
            entities.append(MessageTextEntity(range: range, type: .Spoiler))
        case "code":
            entities.append(MessageTextEntity(range: range, type: .Code))
        case "pre":
            entities.append(MessageTextEntity(range: range, type: .Pre(language: value["language"] as? String)))
        case "text_link":
            entities.append(MessageTextEntity(range: range, type: .TextUrl(url: (value["url"] as? String) ?? "")))
        case "blockquote":
            entities.append(MessageTextEntity(range: range, type: .BlockQuote(isCollapsed: (value["collapsed"] as? Bool) ?? false)))
        default:
            break
        }
    }
    return entities
}

/// Android dialog id → Postbox peer id, the same conversion the plugin host uses.
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

