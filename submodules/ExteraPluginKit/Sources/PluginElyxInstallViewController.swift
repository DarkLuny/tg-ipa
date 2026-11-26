import Foundation
import UIKit

/// Install sheet for an `.elyx` archive: metadata, pip requirements, required
/// plugins, validation errors, and the password retry for encrypted archives.
public final class PluginElyxInstallViewController: UITableViewController {
    private enum Row {
        case value(title: String, value: String)
        case error(String)
        case toggle(title: String, detail: String?, value: Bool)
        case action(title: String, detail: String?)
    }

    private let url: URL
    private let inspection: PluginManager.ElyxInspection
    private let onInstalled: (() -> Void)?
    private var sections: [(title: String?, rows: [Row])] = []
    private var installing = false
    private var enableAfterInstallation = false
    private var analysis: PluginAnalysisReport?
    private let activity = UIActivityIndicatorView(style: .medium)

    public init(url: URL, inspection: PluginManager.ElyxInspection, onInstalled: (() -> Void)? = nil) {
        self.url = url
        self.inspection = inspection
        self.onInstalled = onInstalled
        super.init(style: .insetGrouped)
        self.title = "Install Elyx plugin"
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        self.activity.hidesWhenStopped = true
        self.tableView.tableFooterView = self.activity
        self.navigationItem.rightBarButtonItem = UIBarButtonItem(
            title: "Install", style: .done, target: self, action: #selector(self.installTapped)
        )
        self.buildSections()
        PluginAnalyzer.shared.analyze(
            PluginAnalysisRequest(fileURL: self.url, name: self.url.lastPathComponent)
        ) { [weak self] report in
            guard let self else {
                return
            }
            self.analysis = report
            self.buildSections()
            self.tableView.reloadData()
        }
    }

    private func buildSections() {
        let metadata = self.inspection.metadata ?? [:]
        var plugin: [Row] = []
        if let name = metadata["name"] as? String, !name.isEmpty {
            plugin.append(.value(title: "Name", value: name))
        }
        if let id = metadata["id"] as? String, !id.isEmpty {
            plugin.append(.value(title: "Identifier", value: id))
        }
        if let version = metadata["version"] as? String, !version.isEmpty {
            plugin.append(.value(title: "Version", value: version))
        }
        if let author = metadata["author"] as? String, !author.isEmpty {
            plugin.append(.value(title: "Author", value: author))
        }
        if let description = metadata["description"] as? String, !description.isEmpty {
            plugin.append(.value(title: "Description", value: description))
        }
        if let icon = metadata["icon"] as? String, !icon.isEmpty {
            plugin.append(.value(title: "Icon", value: icon))
        }

        var requirements: [Row] = []
        if let values = metadata["requirements"] as? [Any] {
            requirements = values.compactMap { $0 as? String }.map {
                .value(title: "Package", value: $0)
            }
        }

        let required = self.inspection.requiredPlugins.map {
            Row.value(title: "Required plugin", value: $0)
        }

        var issues: [Row] = self.inspection.errors.map { .error($0) }
        if let error = self.inspection.error, !error.isEmpty, !self.inspection.errors.contains(error) {
            issues.append(.error(error))
        }

        let options: [Row] = [
            .toggle(
                title: "Enable after installation",
                detail: "Load the plugin as soon as it is installed.",
                value: self.enableAfterInstallation
            )
        ]

        var analysisRows: [Row] = []
        if let analysis {
            analysisRows.append(.value(title: "Risk", value: analysis.maxSeverity.title))
            if let message = analysis.message, !message.isEmpty {
                analysisRows.append(.value(title: "Notes", value: message))
            }
            analysisRows.append(.action(
                title: "View analysis",
                detail: "Open the full static analysis report before installing."
            ))
        } else {
            analysisRows.append(.value(title: "Analysis", value: "Analyzing…"))
        }

        self.sections = [
            ("Plugin", plugin),
            ("Options", options),
            ("Requirements", requirements),
            ("Required plugins", required),
            ("Issues", issues),
            ("Analysis", analysisRows),
        ].filter { !$0.1.isEmpty }
    }

    @objc private func installTapped() {
        let combined = ([self.inspection.error ?? ""] + self.inspection.errors).joined(separator: "\n")
        if !self.inspection.ok, PluginInstallUI.isPasswordError(combined) {
            PluginInstallUI.presentPasswordPrompt(from: self) { [weak self] password in
                self?.install(password: password)
            }
            return
        }
        self.install(password: nil)
    }

    private func install(password: String?) {
        guard !self.installing else {
            return
        }
        self.installing = true
        self.activity.startAnimating()
        PluginManager.shared.installElyx(url: self.url, password: password, enabled: self.enableAfterInstallation) { [weak self] result in
            guard let self else {
                return
            }
            self.activity.stopAnimating()
            self.installing = false
            if let error = result.error {
                if password == nil, PluginInstallUI.isPasswordError(error) {
                    PluginInstallUI.presentPasswordPrompt(from: self) { [weak self] entered in
                        self?.install(password: entered)
                    }
                    return
                }
                let alert = UIAlertController(title: "Install failed", message: error, preferredStyle: .alert)
                alert.addAction(UIAlertAction(title: "OK", style: .default))
                self.present(alert, animated: true)
                return
            }
            self.onInstalled?()
            let message = result.plugin.map { "\($0.name) \($0.manifest.version)" }
            let alert = UIAlertController(title: "Installed", message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "OK", style: .default) { [weak self] _ in
                guard let self else {
                    return
                }
                if let navigationController = self.navigationController, navigationController.viewControllers.count > 1 {
                    navigationController.popViewController(animated: true)
                } else {
                    self.dismiss(animated: true)
                }
            })
            self.present(alert, animated: true)
        }
    }

    // -- Table ---------------------------------------------------------------

    public override func numberOfSections(in tableView: UITableView) -> Int {
        return self.sections.count
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        return self.sections[section].rows.count
    }

    public override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        return self.sections[section].title
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let row = self.sections[indexPath.section].rows[indexPath.row]
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        cell.textLabel?.numberOfLines = 3
        cell.detailTextLabel?.numberOfLines = 4
        switch row {
        case let .value(title, value):
            cell.textLabel?.text = title
            cell.detailTextLabel?.text = value
            cell.selectionStyle = .none
        case let .error(message):
            cell.textLabel?.text = message
            cell.textLabel?.textColor = .systemRed
            cell.textLabel?.numberOfLines = 0
            cell.selectionStyle = .none
        case let .toggle(title, detail, value):
            cell.textLabel?.text = title
            cell.textLabel?.numberOfLines = 1
            cell.detailTextLabel?.text = detail
            cell.selectionStyle = .none
            let toggle = UISwitch()
            toggle.isOn = value
            toggle.addTarget(self, action: #selector(self.enableChanged(_:)), for: .valueChanged)
            cell.accessoryView = toggle
        case let .action(title, detail):
            cell.textLabel?.text = title
            cell.detailTextLabel?.text = detail
            cell.selectionStyle = .default
            cell.accessoryType = .disclosureIndicator
        }
        return cell
    }

    public override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        guard indexPath.section < self.sections.count else {
            return
        }
        guard case .action = self.sections[indexPath.section].rows[indexPath.row],
              let analysis = self.analysis else {
            return
        }
        let metadata = self.inspection.metadata ?? [:]
        let name = (metadata["name"] as? String) ?? "Elyx plugin"
        let version = (metadata["version"] as? String) ?? ""
        let author = (metadata["author"] as? String) ?? ""
        let subtitle = version.isEmpty ? author : (author.isEmpty ? version : "\(version) by \(author)")
        let controller = PluginAnalysisViewController(
            title: name,
            subtitle: subtitle,
            report: analysis,
            installTitle: nil,
            onInstall: nil,
            requirements: []
        )
        self.navigationController?.pushViewController(controller, animated: true)
    }

    @objc private func enableChanged(_ sender: UISwitch) {
        self.enableAfterInstallation = sender.isOn
    }
}
