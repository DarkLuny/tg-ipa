import Foundation
import UIKit
import Display
import SwiftSignalKit
import TelegramCore
import AccountContext

public extension QrStudioScreen {
    static func preloadTheme(context: AccountContext, peerId: EnginePeer.Id) -> Disposable {
        return context.engine.peers.preloadShareTheme(peerId: peerId).startStrict()
    }
}
