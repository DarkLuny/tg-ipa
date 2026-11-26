import Foundation

public struct PluginAnalysisRequest: Sendable {
    public var fileURL: URL
    public var name: String
    public var previousFileURL: URL?

    public init(fileURL: URL, name: String, previousFileURL: URL? = nil) {
        self.fileURL = fileURL
        self.name = name
        self.previousFileURL = previousFileURL
    }
}

/// Static analysis of a plugin before it is installed.
///
/// The real work happens in `extera_analyzer.py`, which is part of the SDK and
/// runs in the same embedded interpreter that will run the plugin. This class
/// adds the file-level checks the Python module cannot do (size limit, SHA-256,
/// unreadable file) and turns the JSON into the model the UI renders.
public final class PluginAnalyzer: @unchecked Sendable {
    public static let shared = PluginAnalyzer()

    public static let maximumFileSize = 64 * 1024 * 1024

    private let queue = DispatchQueue(label: "com.exteragram.plugins.analyzer", qos: .userInitiated)
    private let cacheLock = NSLock()
    private var cache: [String: PluginAnalysisReport] = [:]
    private let cacheLimit = 64

    private init() {
    }

    public func cachedReport(sha256: String) -> PluginAnalysisReport? {
        self.cacheLock.lock()
        defer { self.cacheLock.unlock() }
        return self.cache[sha256]
    }

    public func analyze(_ request: PluginAnalysisRequest, completion: @escaping (PluginAnalysisReport) -> Void) {
        self.queue.async {
            let report = self.performAnalysis(request)
            if let sha256 = report.sha256, report.status == .done {
                self.cacheLock.lock()
                self.cache[sha256] = report
                if self.cache.count > self.cacheLimit {
                    self.cache.removeValue(forKey: self.cache.keys.first ?? "")
                }
                self.cacheLock.unlock()
            }
            DispatchQueue.main.async {
                completion(report)
            }
        }
    }

    public func analyzeSynchronously(_ request: PluginAnalysisRequest) -> PluginAnalysisReport {
        return self.performAnalysis(request)
    }

    private func performAnalysis(_ request: PluginAnalysisRequest) -> PluginAnalysisReport {
        let url = request.fileURL
        let attributes = try? FileManager.default.attributesOfItem(atPath: url.path)
        let size = (attributes?[.size] as? NSNumber)?.int64Value ?? 0
        if size > Int64(Self.maximumFileSize) {
            return PluginAnalysisReport(status: .tooLarge, message: "the file is larger than 64 MB")
        }
        guard let data = try? Data(contentsOf: url) else {
            return PluginAnalysisReport(status: .failed, message: "could not read the plugin file")
        }
        let sha256 = PluginHashing.sha256(data)
        let extensionName = url.pathExtension.lowercased()
        let isArchive = extensionName == "elyx" || extensionName == "eaf"
            || data.starts(with: [0x50, 0x4B, 0x03, 0x04])

        if !PluginPreferences.shared.staticAnalysis {
            return PluginAnalysisReport(
                status: .done,
                analyzerVersion: "disabled",
                maxSeverity: .none,
                statements: [],
                findings: [:],
                limits: [],
                message: "Static analysis is disabled in Plugins engine settings.",
                sha256: sha256
            )
        }

        guard PythonRuntime.shared.isStarted else {
            if isArchive {
                return PluginAnalysisReport(
                    status: .unavailable,
                    analyzerVersion: "swift-lexical",
                    maxSeverity: .none,
                    statements: [],
                    findings: [:],
                    limits: ["unanalyzed"],
                    message: "Static analysis of Elyx archives needs the embedded interpreter.",
                    sha256: sha256
                )
            }
            return PluginAnalyzer.lexicalReport(data: data, name: request.name, sha256: sha256)
        }
        do {
            // An update is analyzed together with the installed version, so the
            // sheet can show what appeared since the user last trusted it.
            if let previousURL = request.previousFileURL,
               let comparison = try? PythonRuntime.shared.call(
                   "analyze_compare",
                   [previousURL.path, url.path, request.name]
               ),
               let root = comparison as? [String: Any],
               let reportValue = root["report"] {
                var report = PluginAnalysisReport(json: reportValue, sha256: sha256)
                if let diffValue = root["diff"] {
                    report.diff = PluginAnalysisDiff(json: diffValue)
                }
                return report
            }
            let value = try PythonRuntime.shared.call(
                isArchive ? "analyze_archive" : "analyze",
                [url.path, request.name]
            )
            return PluginAnalysisReport(json: value, sha256: sha256)
        } catch {
            return PluginAnalyzer.lexicalReport(data: data, name: request.name, sha256: sha256, error: "\(error)")
        }
    }

    /// A conservative scan used when Python is not linked into the build.
    /// It never claims a plugin is safe: the report is `unavailable`, and the
    /// install sheet then asks the user to confirm.
    private static func lexicalReport(data: Data, name: String, sha256: String?, error: String? = nil) -> PluginAnalysisReport {
        let source = String(data: data, encoding: .utf8) ?? ""
        var findings: [String: PluginAnalysisFinding] = [:]
        var statements: [PluginAnalysisStatement] = []

        func add(rule: String, severity: PluginAnalysisSeverity, title: String, capabilities: [String], value: String) {
            if var existing = findings[rule] {
                if !existing.values.contains(value) {
                    existing.values.append(value)
                }
                findings[rule] = existing
            } else {
                findings[rule] = PluginAnalysisFinding(json: [
                    "rule": rule,
                    "severity": severity == .danger ? "danger" : severity == .caution ? "caution" : "info",
                    "title": title,
                    "values": [value],
                    "capabilities": capabilities,
                    "evidence": [],
                    "evidence_total": 0
                ])
            }
        }

        let patterns: [(String, PluginAnalysisSeverity, [String], String, String)] = [
            ("py.dynamic_exec", .danger, ["dynamic_code"], "Dynamic code execution", "exec("),
            ("net.endpoints", .info, ["network"], "Network endpoint", "http"),
            ("py.native", .danger, ["native_code"], "Native code", "subprocess"),
            ("hooks.java", .danger, ["java_hooks"], "Hooks app code", "hook_method"),
            ("py.session_data", .critical, ["files", "session_data"], "Session data", "session")
        ]
        for (rule, severity, capabilities, title, needle) in patterns where source.contains(needle) {
            add(rule: rule, severity: severity, title: title, capabilities: capabilities, value: needle)
        }
        if !findings.isEmpty {
            statements.append(PluginAnalysisStatement(json: [
                "id": "unverified",
                "severity": "caution",
                "title": "Static analysis is unavailable",
                "values": [],
                "rules": Array(findings.keys),
                "capabilities": ["unverified"]
            ]))
        }

        var report = PluginAnalysisReport(
            status: .unavailable,
            analyzerVersion: "swift-lexical",
            maxSeverity: findings.values.map { $0.severity }.max() ?? .caution,
            statements: statements,
            findings: findings,
            limits: ["unanalyzed"],
            message: error ?? "the embedded analyzer is not available in this build",
            sha256: sha256
        )
        report.status = .unavailable
        return report
    }
}
