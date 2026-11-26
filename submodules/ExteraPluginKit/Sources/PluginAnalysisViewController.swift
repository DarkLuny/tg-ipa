import Foundation
import UIKit

/// The install sheet: what a plugin claims, what it can do, and the decision.
public final class PluginAnalysisViewController: UITableViewController {
    private struct Row {
        enum Kind {
            case statement(PluginAnalysisStatement)
            case finding(PluginAnalysisFinding)
            case note(String)
            case diff(PluginAnalysisStatement, Bool)
            case diffFinding(PluginAnalysisFinding)
        }

        var kind: Kind
    }

    private let report: PluginAnalysisReport
    private let installTitle: String?
    private let onInstall: (() -> Void)?
    private let onInstallWithEnable: ((Bool) -> Void)?
    private let pluginTitle: String
    private let pluginSubtitle: String
    private let requirements: [String]
    private let trustedSource: Bool
    private var rows: [Row] = []
    private var diffRows: [Row] = []
    /// Android's install sheet starts with "enable after installation" off.
    private var enableAfterInstallation = false
    private var riskAcknowledged = false

    public init(title: String, subtitle: String, report: PluginAnalysisReport, installTitle: String?, onInstall: (() -> Void)?, requirements: [String] = [], trustedSource: Bool = false, onInstallWithEnable: ((Bool) -> Void)? = nil) {
        self.pluginTitle = title
        self.pluginSubtitle = subtitle
        self.report = report
        self.installTitle = installTitle
        self.onInstall = onInstall
        self.onInstallWithEnable = onInstallWithEnable
        self.requirements = requirements
        self.trustedSource = trustedSource
        super.init(style: .insetGrouped)
        self.title = title
        self.buildRows()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    private func buildRows() {
        self.rows = self.report.statements.map { Row(kind: .statement($0)) }
        for statement in self.report.statements {
            if let note = PluginAnalysisCatalog.note(for: statement, report: self.report) {
                self.rows.append(Row(kind: .note(note)))
            }
            for finding in self.report.findings(for: statement) {
                self.rows.append(Row(kind: .finding(finding)))
            }
        }
        self.diffRows = []
        guard let diff = self.report.diff, !diff.isEmpty else {
            return
        }
        for statement in diff.newStatements {
            self.diffRows.append(Row(kind: .diff(statement, true)))
        }
        for statement in diff.changed(in: self.report) {
            self.diffRows.append(Row(kind: .diff(statement, false)))
            for finding in diff.changedFindings(in: self.report, statement: statement) {
                self.diffRows.append(Row(kind: .diffFinding(finding)))
            }
        }
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        if self.installTitle != nil {
            self.navigationItem.rightBarButtonItem = UIBarButtonItem(
                title: self.installTitle, style: .done, target: self, action: #selector(self.installTapped)
            )
        }
        if !self.report.statements.isEmpty || !self.report.findings.isEmpty {
            self.navigationItem.leftBarButtonItem = UIBarButtonItem(
                title: "Share", style: .plain, target: self, action: #selector(self.shareReport)
            )
        }
    }

    @objc private func shareReport() {
        var lines: [String] = [
            "\(self.pluginTitle) \(self.pluginSubtitle)",
            "Risk: \(self.report.maxSeverity.title)",
            "Analyzer: \(self.report.analyzerVersion), \(self.report.elapsedMilliseconds) ms"
        ]
        for statement in self.report.statements {
            lines.append("")
            lines.append("[\(statement.severity.title)] \(PluginAnalysisCatalog.title(for: statement))")
            if let detail = PluginAnalysisCatalog.detail(for: statement), !detail.isEmpty {
                lines.append(detail)
            }
            let values = self.report.values(for: statement)
            if !values.isEmpty {
                lines.append("Values: \(values.prefix(12).joined(separator: ", "))")
            }
            for finding in self.report.findings(for: statement) {
                let title = finding.title.isEmpty ? finding.rule : finding.title
                lines.append("  - \(title): \(finding.values.prefix(6).joined(separator: ", "))")
            }
        }
        if let diff = self.report.diff, !diff.isEmpty {
            lines.append("")
            lines.append("Changes since the installed version:")
            for statement in diff.newStatements {
                lines.append("[New] \(PluginAnalysisCatalog.title(for: statement))")
            }
            for statement in diff.changed(in: self.report) {
                lines.append("[Changed] \(PluginAnalysisCatalog.title(for: statement))")
            }
        }
        if let sha256 = self.report.sha256 {
            lines.append("")
            lines.append("SHA-256: \(sha256)")
        }
        if !self.report.limits.isEmpty {
            lines.append("Limits: \(self.report.limits.joined(separator: ", "))")
        }
        let activity = UIActivityViewController(activityItems: [lines.joined(separator: "\n")], applicationActivities: nil)
        activity.popoverPresentationController?.sourceView = self.view
        activity.popoverPresentationController?.sourceRect = self.view.bounds
        self.present(activity, animated: true)
    }

    @objc private func installTapped() {
        if !self.trustedSource && !PluginPreferences.shared.allowUnknownSources {
            let alert = UIAlertController(
                title: "Unknown source",
                message: "Installing plugins from unknown sources is turned off. Enable it in Plugins engine settings, then try again.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "OK", style: .default))
            self.present(alert, animated: true)
            return
        }
        if !self.trustedSource && !self.riskAcknowledged {
            let alert = UIAlertController(
                title: "Unknown source",
                message: "This plugin is not published in a trusted catalog. Continue only if you trust its author and have read its code.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
            alert.addAction(UIAlertAction(title: "Continue", style: .destructive) { [weak self] _ in
                self?.riskAcknowledged = true
                self?.installTapped()
            })
            self.present(alert, animated: true)
            return
        }
        if self.report.maxSeverity == .critical {
            let alert = UIAlertController(
                title: "Critical risk",
                message: "This plugin can read your account or messages and send them away. Install it only if you trust its author and have read its code.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
            alert.addAction(UIAlertAction(title: "Install anyway", style: .destructive) { [weak self] _ in
                self?.finishInstall()
                self?.navigationController?.popViewController(animated: true)
            })
            self.present(alert, animated: true)
            return
        }
        if self.report.status == .unavailable {
            let alert = UIAlertController(
                title: "Analysis unavailable",
                message: self.report.message ?? "This build could not analyze the plugin. Install it only from a source you trust.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
            alert.addAction(UIAlertAction(title: "Continue", style: .default) { [weak self] _ in
                self?.finishInstall()
                self?.navigationController?.popViewController(animated: true)
            })
            self.present(alert, animated: true)
            return
        }
        self.finishInstall()
        self.navigationController?.popViewController(animated: true)
    }

    private func finishInstall() {
        if let onInstallWithEnable {
            onInstallWithEnable(self.enableAfterInstallation)
        } else {
            self.onInstall?()
        }
    }

    @objc private func enableChanged(_ sender: UISwitch) {
        self.enableAfterInstallation = sender.isOn
    }

    public override func numberOfSections(in tableView: UITableView) -> Int {
        return 4
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        switch section {
        case 0: return self.installTitle != nil ? 3 : 2
        case 1: return self.diffRows.count
        case 2: return self.report.statements.isEmpty ? 1 : self.rows.count
        default: return 2
        }
    }

    public override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        switch section {
        case 1: return self.diffRows.isEmpty ? nil : "What changed"
        case 2: return "Capabilities"
        case 3: return "Analyzer"
        default: return nil
        }
    }

    public override func tableView(_ tableView: UITableView, titleForFooterInSection section: Int) -> String? {
        if section == 0, !self.requirements.isEmpty {
            return "Requires: \(self.requirements.joined(separator: ", ")). Pure-Python packages are installed from PyPI when you tap \(self.installTitle ?? "Install")."
        }
        if section == 3 {
            if self.report.status == .unavailable {
                return self.report.message ?? "The static analyzer is not available in this build."
            }
            return "Analysis \(self.report.analyzerVersion), \(self.report.elapsedMilliseconds) ms. A clean report means the rules did not match; it is not a guarantee."
        }
        return nil
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        cell.accessoryView = nil
        cell.accessoryType = .none
        cell.selectionStyle = .none
        cell.textLabel?.numberOfLines = 3
        cell.detailTextLabel?.numberOfLines = 4

        if indexPath.section == 0 {
            if indexPath.row == 1 {
                cell.textLabel?.text = self.trustedSource ? "Trusted source" : "Unknown source"
                cell.detailTextLabel?.text = self.trustedSource
                    ? "Published in a plugin catalog."
                    : "Not published in a trusted catalog. Install it only if you trust its author."
                cell.textLabel?.numberOfLines = 1
                cell.textLabel?.textColor = UIColor(pluginColor: self.trustedSource ? 0x34C759 : 0xF2A33C)
                return cell
            }
            if indexPath.row == 2 {
                cell.textLabel?.text = "Enable after installation"
                cell.detailTextLabel?.text = "Load the plugin as soon as it is installed."
                cell.textLabel?.numberOfLines = 1
                cell.textLabel?.textColor = .label
                cell.selectionStyle = .none
                let toggle = UISwitch()
                toggle.isOn = self.enableAfterInstallation
                toggle.addTarget(self, action: #selector(self.enableChanged(_:)), for: .valueChanged)
                cell.accessoryView = toggle
                return cell
            }
            cell.textLabel?.text = self.pluginTitle
            cell.detailTextLabel?.text = self.pluginSubtitle
            cell.textLabel?.textColor = .label
            let badge = UILabel()
            badge.text = self.report.maxSeverity.title
            badge.font = .systemFont(ofSize: 13, weight: .semibold)
            badge.textColor = UIColor(pluginColor: self.report.maxSeverity.color)
            badge.sizeToFit()
            cell.accessoryView = badge
            return cell
        }

        if indexPath.section == 1 {
            let row = self.diffRows[indexPath.row]
            switch row.kind {
            case let .diff(statement, isNew):
                cell.textLabel?.text = PluginAnalysisCatalog.title(for: statement)
                cell.textLabel?.textColor = .label
                var detail = isNew
                    ? "New capability since the installed version."
                    : "Changed since the installed version."
                if let description = PluginAnalysisCatalog.detail(for: statement), !description.isEmpty {
                    detail += "\n" + description
                }
                cell.detailTextLabel?.text = detail
                let badge = UILabel()
                badge.text = isNew ? "New" : "Changed"
                badge.font = .systemFont(ofSize: 13, weight: .semibold)
                badge.textColor = UIColor(pluginColor: isNew ? 0xD7263D : 0xF2A33C)
                badge.sizeToFit()
                cell.accessoryView = badge
            case let .diffFinding(finding):
                cell.textLabel?.text = finding.title.isEmpty ? finding.rule : finding.title
                cell.textLabel?.textColor = .secondaryLabel
                var detail = finding.values.prefix(4).joined(separator: ", ")
                if let first = finding.evidence.first, first.line > 0 {
                    detail += "\nline \(first.line): \(first.excerpt ?? "")"
                }
                cell.detailTextLabel?.text = detail
            default:
                break
            }
            return cell
        }

        if indexPath.section == 2 {
            guard !self.report.statements.isEmpty else {
                cell.textLabel?.text = self.report.status == .unavailable ? "Not analyzed" : "Nothing suspicious found"
                cell.textLabel?.textColor = .secondaryLabel
                return cell
            }
            let row = self.rows[indexPath.row]
            switch row.kind {
            case let .statement(statement):
                cell.textLabel?.text = PluginAnalysisCatalog.title(for: statement)
                cell.textLabel?.textColor = .label
                var detail = PluginAnalysisCatalog.detail(for: statement) ?? ""
                let values = self.report.values(for: statement)
                if !values.isEmpty {
                    detail += "\n" + values.prefix(6).joined(separator: ", ")
                }
                cell.detailTextLabel?.text = detail
                let badge = UILabel()
                badge.text = statement.severity.title
                badge.font = .systemFont(ofSize: 13, weight: .semibold)
                badge.textColor = UIColor(pluginColor: statement.severity.color)
                badge.sizeToFit()
                cell.accessoryView = badge
            case let .finding(finding):
                cell.textLabel?.text = finding.title.isEmpty ? finding.rule : finding.title
                cell.textLabel?.textColor = .secondaryLabel
                var detail = finding.values.prefix(4).joined(separator: ", ")
                if let first = finding.evidence.first, first.line > 0 {
                    let excerpt = first.excerpt ?? ""
                    detail += "\nline \(first.line): \(excerpt)"
                }
                cell.detailTextLabel?.text = detail
            case let .note(text):
                cell.textLabel?.text = text
                cell.textLabel?.textColor = .secondaryLabel
            case .diff, .diffFinding:
                break
            }
            return cell
        }

        if indexPath.row == 0 {
            cell.textLabel?.text = "Checksum"
            cell.detailTextLabel?.text = self.report.sha256 ?? "unavailable"
        } else {
            cell.textLabel?.text = "Limits"
            cell.detailTextLabel?.text = self.report.limits.isEmpty ? "none" : self.report.limits.joined(separator: ", ")
        }
        cell.textLabel?.textColor = .secondaryLabel
        return cell
    }
}

extension UIColor {
    convenience init(pluginColor value: UInt32) {
        self.init(
            red: CGFloat((value >> 16) & 0xFF) / 255.0,
            green: CGFloat((value >> 8) & 0xFF) / 255.0,
            blue: CGFloat(value & 0xFF) / 255.0,
            alpha: 1.0
        )
    }
}
