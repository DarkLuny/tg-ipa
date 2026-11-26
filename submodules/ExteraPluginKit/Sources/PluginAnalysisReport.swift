import Foundation

/// Severity levels used by the analyzer, matching `AnalyzerReport` on Android.
public enum PluginAnalysisSeverity: Int, Comparable, Sendable {
    case none = -1
    case info = 0
    case caution = 1
    case danger = 2
    case critical = 3

    public init(label: String?) {
        switch label {
        case "info": self = .info
        case "caution": self = .caution
        case "danger": self = .danger
        case "critical": self = .critical
        default: self = .none
        }
    }

    public static func < (lhs: PluginAnalysisSeverity, rhs: PluginAnalysisSeverity) -> Bool {
        return lhs.rawValue < rhs.rawValue
    }

    public var title: String {
        switch self {
        case .info: return "Info"
        case .caution: return "Attention"
        case .danger: return "Dangerous"
        case .critical: return "Critical"
        case .none: return "Checked"
        }
    }

    /// `0xRRGGBB` as used by the theme, so the UI can tint the row.
    public var color: UInt32 {
        switch self {
        case .info: return 0x3D8BFF
        case .caution: return 0xF2A33C
        case .danger: return 0xF25C4A
        case .critical: return 0xD7263D
        case .none: return 0x34C759
        }
    }
}

public enum PluginAnalysisCategory: String, Sendable {
    case code
    case stealth
    case account
    case messages
    case network
    case files
    case device
    case app
    case packages
    case other

    public var title: String {
        switch self {
        case .code: return "Code"
        case .stealth: return "Stealth"
        case .account: return "Account"
        case .messages: return "Messages"
        case .network: return "Network"
        case .files: return "Files"
        case .device: return "Device"
        case .app: return "App"
        case .packages: return "Packages"
        case .other: return "Other"
        }
    }

    public var systemImage: String {
        switch self {
        case .code: return "chevron.left.forwardslash.chevron.right"
        case .stealth: return "eye.slash"
        case .account: return "person.crop.circle"
        case .messages: return "bubble.left.and.bubble.right"
        case .network: return "network"
        case .files: return "folder"
        case .device: return "iphone"
        case .app: return "app.badge"
        case .packages: return "shippingbox"
        case .other: return "info.circle"
        }
    }
}

public struct PluginAnalysisEvidence: Sendable {
    public var line: Int
    public var excerpt: String?
    public var symbol: String
    public var scope: String?
}

public struct PluginAnalysisFinding: Sendable {
    public var rule: String
    public var severity: PluginAnalysisSeverity
    public var title: String
    public var values: [String]
    public var capabilities: [String]
    public var evidence: [PluginAnalysisEvidence]
    public var evidenceTotal: Int

    public init(json: [String: Any]) {
        self.rule = (json["rule"] as? String) ?? ""
        self.severity = PluginAnalysisSeverity(label: json["severity"] as? String)
        self.title = (json["title"] as? String) ?? ""
        self.values = (json["values"] as? [Any])?.compactMap { $0 as? String } ?? []
        self.capabilities = (json["capabilities"] as? [Any])?.compactMap { $0 as? String } ?? []
        let entries = (json["evidence"] as? [[String: Any]]) ?? []
        self.evidence = entries.map { entry in
            let location = entry["location"] as? [String: Any]
            return PluginAnalysisEvidence(
                line: (location?["line"] as? NSNumber)?.intValue ?? 0,
                excerpt: entry["excerpt"] as? String,
                symbol: (entry["symbol"] as? String) ?? "",
                scope: location?["scope"] as? String
            )
        }
        self.evidenceTotal = (json["evidence_total"] as? NSNumber)?.intValue ?? self.evidence.count
    }
}

public struct PluginAnalysisStatement: Sendable {
    public var id: String
    public var severity: PluginAnalysisSeverity
    public var title: String
    public var values: [String]
    public var rules: [String]
    public var capabilities: [String]

    public init(json: [String: Any]) {
        self.id = (json["id"] as? String) ?? ""
        self.severity = PluginAnalysisSeverity(label: json["severity"] as? String)
        self.title = (json["title"] as? String) ?? ""
        self.values = (json["values"] as? [Any])?.compactMap { $0 as? String } ?? []
        self.rules = (json["rules"] as? [Any])?.compactMap { $0 as? String } ?? []
        self.capabilities = (json["capabilities"] as? [Any])?.compactMap { $0 as? String } ?? []
    }
}

/// The complete report produced before a plugin is installed.
public struct PluginAnalysisReport: Sendable {
    public enum Status: String, Sendable {
        case done
        case unavailable
        case failed
        case timeout
        case crashed
        case tooLarge
        case memory
    }

    public var status: Status
    public var analyzerVersion: String
    public var maxSeverity: PluginAnalysisSeverity
    public var statements: [PluginAnalysisStatement]
    public var findings: [String: PluginAnalysisFinding]
    public var limits: [String]
    public var elapsedMilliseconds: Int
    public var message: String?
    public var sha256: String?
    /// Changes compared with the installed version, when the sheet analyzes an
    /// update. `nil` for a first install, matching Android's `AnalyzerDiff`.
    public var diff: PluginAnalysisDiff?

    public init(
        status: Status,
        analyzerVersion: String = "",
        maxSeverity: PluginAnalysisSeverity = .none,
        statements: [PluginAnalysisStatement] = [],
        findings: [String: PluginAnalysisFinding] = [:],
        limits: [String] = [],
        elapsedMilliseconds: Int = 0,
        message: String? = nil,
        sha256: String? = nil,
        diff: PluginAnalysisDiff? = nil
    ) {
        self.status = status
        self.analyzerVersion = analyzerVersion
        self.maxSeverity = maxSeverity
        self.statements = statements
        self.findings = findings
        self.limits = limits
        self.elapsedMilliseconds = elapsedMilliseconds
        self.message = message
        self.sha256 = sha256
        self.diff = diff
    }

    public init(json: Any, sha256: String? = nil) {
        guard let root = json as? [String: Any] else {
            self.init(status: .failed, message: "the analyzer returned no report", sha256: sha256)
            return
        }
        let analyzer = root["analyzer"] as? [String: Any]
        let findingList = (root["findings"] as? [[String: Any]] ?? []).map(PluginAnalysisFinding.init(json:))
        var findings: [String: PluginAnalysisFinding] = [:]
        for finding in findingList {
            findings[finding.rule] = finding
        }
        let statements = (root["statements"] as? [[String: Any]] ?? [])
            .map(PluginAnalysisStatement.init(json:))
            .sorted { $0.severity > $1.severity }
        self.init(
            status: .done,
            analyzerVersion: (analyzer?["version"] as? String) ?? "",
            maxSeverity: PluginAnalysisSeverity(label: root["max_severity"] as? String),
            statements: statements,
            findings: findings,
            limits: (root["limits"] as? [Any])?.compactMap { $0 as? String } ?? [],
            elapsedMilliseconds: ((root["stats"] as? [String: Any])?["elapsed_ms"] as? NSNumber)?.intValue ?? 0,
            message: nil,
            sha256: sha256
        )
    }

    public func findings(for statement: PluginAnalysisStatement) -> [PluginAnalysisFinding] {
        return statement.rules.compactMap { findings[$0] }.sorted { $0.severity > $1.severity }
    }

    public func values(for statement: PluginAnalysisStatement) -> [String] {
        var result: [String] = []
        for finding in findings(for: statement) {
            let capabilities = finding.capabilities.filter { statement.capabilities.contains($0) }
            if capabilities.contains("network") {
                if finding.rule.contains("endpoints") || finding.rule == "net.raw_ip" {
                    result.append(contentsOf: finding.values.map(PluginAnalysisCatalog.host))
                }
            } else if capabilities.contains(where: { PluginAnalysisCatalog.symbolCapabilities.contains($0) }) {
                result.append(contentsOf: finding.values.compactMap(PluginAnalysisCatalog.symbolName))
            } else if capabilities.contains("third_party_code")
                        || capabilities.contains("verified_packages")
                        || capabilities.contains("mvel_code")
                        || capabilities.contains("unused_files") {
                result.append(contentsOf: finding.values)
            }
        }
        var seen = Set<String>()
        return result.filter { $0.isEmpty ? false : seen.insert($0).inserted }
    }

    public var isEmpty: Bool {
        return statements.isEmpty && maxSeverity == .none
    }
}

/// Difference between the installed version and an update, matching
/// Android's `AnalyzerDiff` (`new_statements` / `new_findings`).
public struct PluginAnalysisDiff: Sendable {
    public struct Change: Sendable {
        public var newValues: [String]
        public var evidence: [PluginAnalysisEvidence]
    }

    public var newStatements: [PluginAnalysisStatement]
    public var changes: [String: Change]
    public var findings: [String: PluginAnalysisFinding]

    public init(json: Any) {
        guard let root = json as? [String: Any] else {
            self.newStatements = []
            self.changes = [:]
            self.findings = [:]
            return
        }
        self.newStatements = (root["new_statements"] as? [[String: Any]] ?? [])
            .map(PluginAnalysisStatement.init(json:))
            .sorted { $0.severity > $1.severity }
        var changes: [String: Change] = [:]
        var findings: [String: PluginAnalysisFinding] = [:]
        for item in (root["new_findings"] as? [[String: Any]] ?? []) {
            let finding = PluginAnalysisFinding(json: item)
            findings[finding.rule] = finding
            changes[finding.rule] = Change(
                newValues: (item["new_values"] as? [Any])?.compactMap { $0 as? String } ?? [],
                evidence: finding.evidence
            )
        }
        self.changes = changes
        self.findings = findings
    }

    public var isEmpty: Bool {
        return self.newStatements.isEmpty && self.changes.isEmpty
    }

    /// Statements that existed before but whose rules now have new evidence.
    public func changed(in report: PluginAnalysisReport) -> [PluginAnalysisStatement] {
        let newIDs = Set(self.newStatements.map { $0.id })
        return report.statements.filter { statement in
            !newIDs.contains(statement.id)
                && statement.rules.contains { self.changes[$0] != nil }
        }
    }

    public func changedFindings(
        in report: PluginAnalysisReport,
        statement: PluginAnalysisStatement
    ) -> [PluginAnalysisFinding] {
        return report.findings(for: statement).compactMap { finding in
            guard let change = self.changes[finding.rule] else {
                return nil
            }
            var updated = finding
            updated.values = change.newValues
            updated.evidence = change.evidence
            updated.evidenceTotal = change.evidence.count
            return updated
        }
    }
}

/// Names, categories and one-line explanations for the statement ids.
public enum PluginAnalysisCatalog {
    static let symbolCapabilities: Set<String> = [
        "telegram_api", "sensitive_requests", "intercepts_requests", "session_data",
        "java_hooks", "ui_hooks", "host_tampering", "traffic_interception"
    ]

    private struct Entry {
        let category: PluginAnalysisCategory
        let title: String
        let detail: String
    }

    private static let entries: [String: Entry] = [
        "remote_code": Entry(category: .stealth, title: "Runs code received from outside",
                             detail: "The plugin can decode and execute code that is not in the .plugin file."),
        "remote_control": Entry(category: .stealth, title: "Can be controlled remotely",
                                detail: "The plugin combines network access with dynamic code execution."),
        "exfiltrate_messages": Entry(category: .messages, title: "Can send messages or contacts away",
                                     detail: "The plugin reads personal chats and has network access."),
        "account_takeover": Entry(category: .account, title: "Can reach account credentials",
                                  detail: "The plugin reads session or account data and can send it out."),
        "wallet_access": Entry(category: .account, title: "Touches wallet data",
                               detail: "The plugin refers to TON, Stars or wallet recovery material."),
        "dynamic_code": Entry(category: .code, title: "Executes code built at runtime",
                              detail: "`exec`, `eval` or `compile` is used."),
        "java_hooks": Entry(category: .code, title: "Hooks app code",
                            detail: "The plugin intercepts methods or network requests."),
        "ui_hooks": Entry(category: .app, title: "Changes the interface",
                          detail: "The plugin adds settings, menu items or overlays."),
        "event_hooks": Entry(category: .app, title: "Subscribes to app events",
                             detail: "The plugin receives updates, lifecycle events or sent messages."),
        "network_access": Entry(category: .network, title: "Uses the network",
                                detail: "The plugin can connect to remote servers."),
        "file_access": Entry(category: .files, title: "Reads or writes files",
                             detail: "The plugin touches the file system."),
        "telegram_api": Entry(category: .app, title: "Uses the Telegram API",
                              detail: "The plugin calls Telegram methods through the client."),
        "session_data": Entry(category: .account, title: "Can reach session data",
                              detail: "The plugin can access the account's session or key material."),
        "sensitive_requests": Entry(category: .account, title: "Calls sensitive requests",
                                    detail: "The plugin sends account, message or payment requests."),
        "intercepts_requests": Entry(category: .stealth, title: "Intercepts network requests",
                                     detail: "The plugin observes or cancels outgoing requests."),
        "host_tampering": Entry(category: .device, title: "Can change the host application",
                                detail: "The plugin uses reflection or native code to alter the app."),
        "native_code": Entry(category: .device, title: "Runs native code",
                             detail: "The plugin starts processes or loads native libraries."),
        "obfuscation": Entry(category: .stealth, title: "Contains encoded data",
                             detail: "The plugin carries opaque or compressed payloads."),
        "packages": Entry(category: .packages, title: "Needs third-party packages",
                          detail: "The plugin declares Python packages that are not part of the SDK.")
    ]

    public static func category(for statement: PluginAnalysisStatement) -> PluginAnalysisCategory {
        if let entry = entries[statement.id] {
            return entry.category
        }
        if statement.capabilities.contains("network") { return .network }
        if statement.capabilities.contains("files") { return .files }
        if statement.capabilities.contains("messages") { return .messages }
        if statement.capabilities.contains("account") || statement.capabilities.contains("session_data") {
            return .account
        }
        return .other
    }

    public static func title(for statement: PluginAnalysisStatement) -> String {
        if let entry = entries[statement.id] {
            return entry.title
        }
        return statement.title.isEmpty ? statement.id : statement.title
    }

    public static func detail(for statement: PluginAnalysisStatement) -> String? {
        return entries[statement.id]?.detail
    }

    public static func host(_ value: String) -> String {
        var text = value
        if let scheme = text.range(of: "://") {
            text = String(text[scheme.upperBound...])
        }
        for separator in ["/", "?", ":"] {
            if let range = text.range(of: separator) {
                text = String(text[..<range.lowerBound])
            }
        }
        return text.trimmingCharacters(in: .whitespaces)
    }

    public static func symbolName(_ value: String) -> String? {
        var symbol = value
        if let range = symbol.range(of: " (") {
            symbol = String(symbol[..<range.lowerBound])
        }
        if let colon = symbol.lastIndex(of: ":") {
            symbol = String(symbol[symbol.index(after: colon)...])
        }
        symbol = symbol.trimmingCharacters(in: .whitespaces)
        if symbol.isEmpty || symbol.hasPrefix("<") || symbol == "?" {
            return nil
        }
        let className = symbol.split(separator: "#").first.map(String.init) ?? symbol
        let member = symbol.split(separator: "#").dropFirst().joined(separator: "#")
        let simple = className.split(separator: ".").last.map(String.init) ?? className
        return member.isEmpty ? simple : simple + "." + member
    }

    public static func note(for statement: PluginAnalysisStatement, report: PluginAnalysisReport) -> String? {
        if statement.rules.contains("tl.unresolved_request") {
            return "Some Telegram requests could not be resolved and are listed by name only."
        }
        if statement.id == "java_hooks" && (report.findings["hooks.unresolved"] != nil || report.findings["hooks.external"] != nil) {
            return "Some hooks target methods that the iOS runtime cannot reach."
        }
        return nil
    }
}
