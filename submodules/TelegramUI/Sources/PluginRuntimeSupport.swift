import Foundation
import UIKit
import TelegramCore
import AccountContext
import ExteraPluginKit

/// Crash bookkeeping for the plugin runtime. A session that ends in a crash makes the
/// next launch start in Safe Mode with plugins off, as exteraGram does.
final class PluginCrashGuard {
    static let shared = PluginCrashGuard()

    private let sessionKey = "ExteraPlugin.CrashGuard.SessionActive"
    private let cleanExitKey = "ExteraPlugin.CrashGuard.CleanExit"
    private(set) var isSafeModeEnabled: Bool = false

    private init() {
        let defaults = UserDefaults.standard
        let previousSessionActive = defaults.bool(forKey: self.sessionKey)
        let previousCleanExit = defaults.bool(forKey: self.cleanExitKey)
        self.isSafeModeEnabled = previousSessionActive && !previousCleanExit
        defaults.set(self.isSafeModeEnabled, forKey: "ExteraPlugin.CrashGuard.SafeMode")
    }

    func beginSession() {
        let defaults = UserDefaults.standard
        defaults.set(true, forKey: self.sessionKey)
        defaults.set(false, forKey: self.cleanExitKey)
    }

    func markCleanExit() {
        UserDefaults.standard.set(true, forKey: self.cleanExitKey)
    }
}

/// Owns the lifetime of the plugin engine: the Python runtime is started once the app has
/// a way to present plugin UI, and stopped when the app goes away.
final class PluginRuntime {
    static let shared = PluginRuntime()

    private weak var sharedContext: SharedAccountContext?
    private var isActive = false

    private init() {
    }

    func activate(sharedContext: SharedAccountContext) {
        guard !self.isActive else {
            return
        }
        self.isActive = true
        self.sharedContext = sharedContext
        PluginManager.shared.start()
    }

    func shutdown() {
        guard self.isActive else {
            return
        }
        self.isActive = false
        PluginCrashGuard.shared.markCleanExit()
        PluginManager.shared.stop()
    }
}

/// Handles plugin files shared into the app (`.plugin`, `.eaf`, `.elyx`) and chat documents
/// whose name or MIME type marks them as one: the file is installed into the plugin store
/// instead of being opened by the document viewer.
enum PluginFileInstaller {
    private static let pluginExtensions: Set<String> = ["plugin", "eaf", "elyx", "zip"]

    static func canInstall(url: URL) -> Bool {
        return self.pluginExtensions.contains(url.pathExtension.lowercased())
    }

    static func canInstall(fileName: String?, mimeType: String?) -> Bool {
        if let fileName, self.pluginExtensions.contains((fileName as NSString).pathExtension.lowercased()) {
            return true
        }
        if let mimeType, mimeType == "application/x-tgplugin" || mimeType == "application/zip" {
            return true
        }
        return false
    }

    static func present(url: URL, sharedContext: SharedAccountContext) {
        PluginManager.shared.install(url: url, completion: { _ in
        })
    }

    static func present(file: TelegramMediaFile, context: AccountContext, existingURL: URL?) {
        if let existingURL {
            self.present(url: existingURL, sharedContext: context.sharedContext)
        }
    }
}

extension PluginManager {
    /// URL intents targeted at plugins, before the app handles them. No plugin has
    /// registered an intent handler in this build, so the URL falls through.
    func dispatchUrlIntent(url: String) -> Bool {
        return false
    }

    func dispatchUrlIntentAfter(url: String) {
    }
}
