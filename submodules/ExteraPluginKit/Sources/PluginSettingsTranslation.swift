import Foundation
import NaturalLanguage
import UIKit

/// Translates the strings of a plugin's settings screen, the iOS counterpart of
/// Android's `PluginSettingsTranslation`.
///
/// The strings are sent to Telegram's translation endpoint
/// (`messages.translateText`) in batches. A screen shows a translate button
/// only when the detected language differs from the app language, and the
/// translated strings replace the originals until translation is switched off
/// again. The cache lives per plugin for the lifetime of the process, exactly
/// like Android's map of instances.
final class PluginSettingsTranslation {
    private static let queue = DispatchQueue(label: "org.telegram.extera.plugin-translation", qos: .userInitiated)
    private static var instances: [String: PluginSettingsTranslation] = [:]

    static func of(_ pluginId: String) -> PluginSettingsTranslation {
        if let existing = instances[pluginId] {
            return existing
        }
        let instance = PluginSettingsTranslation(pluginId: pluginId)
        instances[pluginId] = instance
        return instance
    }

    private let pluginId: String
    private var translations: [String: String] = [:]
    private var pending = Set<String>()
    private var failed = Set<String>()
    private var targetLanguage = PluginSettingsTranslation.targetLanguageCode()
    private var detectedLanguage: String?
    private var detecting = false

    /// Called on the main thread after the state changes; the argument is true
    /// when every request failed and translation was switched off.
    var onChange: ((Bool) -> Void)?

    private(set) var enabled = false
    private(set) var isLoading = false
    private(set) var failureMessage: String?

    private init(pluginId: String) {
        self.pluginId = pluginId
    }

    private static func targetLanguageCode() -> String {
        let raw = Bundle.main.preferredLocalizations.first ?? Locale.current.identifier
        let primary = raw.split(separator: "-").first.map(String.init) ?? raw
        return primary.lowercased()
    }

    private static func primaryLanguage(_ code: String) -> String {
        return code.split(separator: "-").first.map { String($0).lowercased() } ?? code.lowercased()
    }

    var isTranslatable: Bool {
        guard let detectedLanguage, !detectedLanguage.isEmpty else {
            return false
        }
        return PluginSettingsTranslation.primaryLanguage(detectedLanguage)
            != PluginSettingsTranslation.primaryLanguage(self.targetLanguage)
    }

    func resetFailed() {
        self.failed.removeAll()
        self.failureMessage = nil
    }

    func setEnabled(_ enabled: Bool) {
        guard self.enabled != enabled else {
            return
        }
        self.enabled = enabled
        if enabled {
            self.failed.removeAll()
            self.failureMessage = nil
        }
        self.onChange?(false)
    }

    func text(_ original: String?) -> String? {
        guard self.enabled, let original else {
            return original
        }
        return self.translations[original] ?? original
    }

    func check(_ texts: [String]) {
        let language = PluginSettingsTranslation.targetLanguageCode()
        if language != self.targetLanguage {
            self.targetLanguage = language
            self.translations.removeAll()
            self.failed.removeAll()
        }

        var seen = Set<String>()
        var unique: [String] = []
        for text in texts {
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                continue
            }
            if seen.insert(text).inserted {
                unique.append(text)
            }
        }

        if self.detectedLanguage == nil, !self.detecting, !unique.isEmpty {
            self.detect(String(unique.joined(separator: "\n").prefix(2000)))
        }

        guard self.enabled else {
            return
        }
        let missing = unique.filter {
            self.translations[$0] == nil && !self.pending.contains($0) && !self.failed.contains($0)
        }
        if !missing.isEmpty {
            self.request(missing)
        }
    }

    private func detect(_ sample: String) {
        self.detecting = true
        let recognizer = NLLanguageRecognizer()
        recognizer.processString(sample)
        let language = recognizer.dominantLanguage?.rawValue
        DispatchQueue.main.async { [weak self] in
            guard let self else {
                return
            }
            self.detecting = false
            guard let language, !language.isEmpty else {
                return
            }
            self.detectedLanguage = language
            self.onChange?(false)
        }
    }

    private func request(_ texts: [String]) {
        let language = self.targetLanguage
        let chunks: [[String]] = stride(from: 0, to: texts.count, by: 20).map {
            Array(texts[$0 ..< min($0 + 20, texts.count)])
        }
        self.pending.formUnion(texts)
        self.isLoading = true
        assert(Thread.isMainThread)

        PluginSettingsTranslation.queue.async { [weak self] in
            guard let self else {
                return
            }
            var translated: [String: String] = [:]
            var failedTexts = Set<String>()
            var lastError: String?
            for chunk in chunks {
                let account = PluginManager.shared.environment.currentAccountId()
                let response = PluginManager.shared.environment.request(
                    account,
                    "messages.translateText",
                    ["text": chunk, "to_lang": language]
                )
                if let error = response["error"] as? String, !error.isEmpty {
                    lastError = error
                    failedTexts.formUnion(chunk)
                    continue
                }
                let results = response["results"] as? [Any] ?? []
                for (index, text) in chunk.enumerated() {
                    if index < results.count,
                       let value = results[index] as? String,
                       !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        translated[text] = value
                    } else {
                        failedTexts.insert(text)
                    }
                }
            }

            DispatchQueue.main.async {
                self.pending.subtract(texts)
                self.isLoading = !self.pending.isEmpty
                guard language == self.targetLanguage else {
                    self.onChange?(false)
                    return
                }
                for (text, value) in translated {
                    self.translations[text] = value
                }
                self.failed.formUnion(failedTexts)
                let failedAll = !failedTexts.isEmpty && self.translations.isEmpty
                if failedAll {
                    self.enabled = false
                    self.failureMessage = lastError
                }
                self.onChange?(failedAll)
            }
        }
    }
}
