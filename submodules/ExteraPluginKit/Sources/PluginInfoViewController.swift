import Foundation
import UIKit

/// Details for one installed plugin plus the runtime's SDK information, the
/// iOS counterpart of the Android plugin info sheet.
public final class PluginInfoViewController: UITableViewController {
    private enum Row {
        case value(title: String, value: String)
        case action(title: String, action: () -> Void)
    }

    private let plugin: Plugin
    private var sections: [(title: String?, rows: [Row])] = []

    public init(plugin: Plugin) {
        self.plugin = plugin
        super.init(style: .insetGrouped)
        self.title = "Plugin info"
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        self.buildSections()
    }

    private func buildSections() {
        var pluginRows: [Row] = [
            .value(title: "Name", value: self.plugin.name),
            .value(title: "Identifier", value: self.plugin.id),
            .value(title: "Version", value: self.plugin.manifest.version),
            .value(title: "Author", value: self.plugin.manifest.author.isEmpty ? "Unknown" : self.plugin.manifest.author),
            .value(title: "Engine", value: self.plugin.isElyx ? "Elyx (.elyx)" : "Python (.plugin)"),
            .value(title: "Enabled", value: self.plugin.isEnabled ? "Yes" : "No"),
            .value(title: "Loaded", value: self.plugin.isLoaded ? "Yes" : "No")
        ]
        if let error = self.plugin.error {
            pluginRows.append(.value(title: "Error", value: error))
        }
        if let description = self.plugin.manifest.description as String?, !description.isEmpty {
            pluginRows.insert(.value(title: "Description", value: description), at: 1)
        }

        var fileRows: [Row] = [
            .value(title: "Path", value: self.plugin.path.path),
            .value(title: "Size", value: self.formattedSize())
        ]
        if !self.plugin.manifest.requirements.isEmpty {
            fileRows.append(.value(title: "Requirements", value: self.plugin.manifest.requirements.joined(separator: ", ")))
        }

        let runtimeRows: [Row] = [
            .value(title: "SDK", value: PluginHostInfo.sdkVersion),
            .value(title: "App compatibility", value: PluginHostInfo.compatibilityVersion),
            .value(title: "Build", value: PluginHostInfo.buildNumber),
            .value(title: "CPython", value: PythonRuntime.shared.isAvailable ? "Embedded" : "Not embedded"),
        ]

        var actionRows: [Row] = []
        actionRows.append(.action(title: "Plugin settings") { [weak self] in
            self?.openSettings()
        })
        actionRows.append(.action(title: self.plugin.isEnabled ? "Disable plugin" : "Enable plugin") { [weak self] in
            self?.toggleEnabled()
        })
        let pinned = PluginManager.shared.isPinned(pluginId: self.plugin.id)
        actionRows.append(.action(title: pinned ? "Unpin plugin" : "Pin plugin") { [weak self] in
            self?.togglePinned()
        })
        if !self.plugin.isElyx && self.plugin.path.pathExtension.lowercased() == "plugin" {
            actionRows.append(.action(title: "View source") { [weak self] in
                self?.openSource()
            })
            actionRows.append(.action(title: "Analyzer") { [weak self] in
                self?.openAnalyzer()
            })
        }
        if self.plugin.isElyx {
            actionRows.append(.action(title: "View files") { [weak self] in
                self?.openFiles()
            })
            actionRows.append(.action(title: "Analyzer") { [weak self] in
                self?.openElyxAnalyzer()
            })
        }
        if !self.plugin.manifest.requirements.isEmpty {
            actionRows.append(.action(title: "Reinstall dependencies") { [weak self] in
                self?.reinstallDependencies()
            })
        }
        actionRows.append(.action(title: "Share plugin") { [weak self] in
            self?.share()
        })
        actionRows.append(.action(title: "Delete plugin") { [weak self] in
            self?.confirmDelete()
        })

        self.sections = [
            ("Plugin", pluginRows),
            ("Files", fileRows),
            ("Runtime", runtimeRows),
            ("Actions", actionRows),
        ]
    }

    private func formattedSize() -> String {
        let total = self.directorySize(self.plugin.path)
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useKB, .useMB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: total)
    }

    private func directorySize(_ url: URL) -> Int64 {
        let values = try? url.resourceValues(forKeys: [.isDirectoryKey])
        if values?.isDirectory == true {
            var total: Int64 = 0
            let enumerator = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.fileSizeKey])
            while let item = enumerator?.nextObject() as? URL {
                if let size = (try? item.resourceValues(forKeys: [.fileSizeKey]))?.fileSize {
                    total += Int64(size)
                }
            }
            return total
        }
        return Int64((try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0)
    }

    private func openSettings() {
        self.navigationController?.pushViewController(
            PluginSettingsViewController(pluginId: self.plugin.id),
            animated: true
        )
    }

    private func toggleEnabled() {
        let target = !self.plugin.isEnabled
        PluginManager.shared.setEnabled(target, pluginId: self.plugin.id) { [weak self] _ in
            guard let self else {
                return
            }
            self.buildSections()
            self.tableView.reloadData()
        }
    }

    private func togglePinned() {
        let pinned = PluginManager.shared.isPinned(pluginId: self.plugin.id)
        PluginManager.shared.setPinned(!pinned, pluginId: self.plugin.id)
        self.buildSections()
        self.tableView.reloadData()
    }

    private func confirmDelete() {
        let alert = UIAlertController(
            title: "Delete \(self.plugin.name)?",
            message: "The plugin and its settings will be removed.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Delete", style: .destructive) { [weak self] _ in
            guard let self else {
                return
            }
            PluginManager.shared.delete(pluginId: self.plugin.id) { [weak self] _ in
                DispatchQueue.main.async {
                    self?.navigationController?.popViewController(animated: true)
                }
            }
        })
        self.present(alert, animated: true)
    }

    private func openSource() {
        guard let source = try? String(contentsOf: self.plugin.path, encoding: .utf8) else {
            return
        }
        self.navigationController?.pushViewController(
            PluginSourceViewController(title: self.plugin.name, source: source),
            animated: true
        )
    }

    private func openFiles() {
        guard self.plugin.isElyx else {
            return
        }
        self.navigationController?.pushViewController(
            PluginFilesViewController(directory: self.plugin.path, title: self.plugin.name),
            animated: true
        )
    }

    private func openElyxAnalyzer() {
        guard self.plugin.isElyx else {
            return
        }
        PluginManager.shared.exportElyxArchive(pluginId: self.plugin.id) { [weak self] url in
            guard let self else {
                return
            }
            guard let url else {
                let alert = UIAlertController(
                    title: "Could not analyze",
                    message: "The .elyx archive could not be created.",
                    preferredStyle: .alert
                )
                alert.addAction(UIAlertAction(title: "OK", style: .default))
                self.present(alert, animated: true)
                return
            }
            PluginAnalyzer.shared.analyze(
                PluginAnalysisRequest(fileURL: url, name: url.lastPathComponent)
            ) { [weak self] report in
                guard let self else {
                    return
                }
                let controller = PluginAnalysisViewController(
                    title: self.plugin.name,
                    subtitle: "\(self.plugin.manifest.version) by \(self.plugin.manifest.author)",
                    report: report,
                    installTitle: nil,
                    onInstall: nil,
                    requirements: self.plugin.manifest.requirements
                )
                self.navigationController?.pushViewController(controller, animated: true)
            }
        }
    }

    private func openAnalyzer() {
        let report = PluginAnalyzer.shared.analyzeSynchronously(
            PluginAnalysisRequest(fileURL: self.plugin.path, name: self.plugin.path.lastPathComponent)
        )
        let controller = PluginAnalysisViewController(
            title: self.plugin.name,
            subtitle: "\(self.plugin.manifest.version) by \(self.plugin.manifest.author)",
            report: report,
            installTitle: nil,
            onInstall: nil,
            requirements: self.plugin.manifest.requirements
        )
        self.navigationController?.pushViewController(controller, animated: true)
    }

    private func reinstallDependencies() {
        guard !self.plugin.manifest.requirements.isEmpty else {
            return
        }
        PluginManager.shared.setEnabled(true, pluginId: self.plugin.id) { [weak self] success in
            let alert = UIAlertController(
                title: success ? "Dependencies installed" : "Dependency install failed",
                message: success ? nil : "See the plugin log for details.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "OK", style: .default))
            self?.present(alert, animated: true)
        }
    }

    private func share() {
        if self.plugin.isElyx {
            PluginManager.shared.exportElyxArchive(pluginId: self.plugin.id) { [weak self] url in
                guard let self else {
                    return
                }
                guard let url else {
                    let alert = UIAlertController(
                        title: "Could not share",
                        message: "The .elyx archive could not be created.",
                        preferredStyle: .alert
                    )
                    alert.addAction(UIAlertAction(title: "OK", style: .default))
                    self.present(alert, animated: true)
                    return
                }
                self.presentShare(url: url)
            }
            return
        }
        self.presentShare(url: PluginManager.shared.pluginFileURL(id: self.plugin.id))
    }

    private func presentShare(url: URL) {
        let activity = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        activity.popoverPresentationController?.sourceView = self.view
        activity.popoverPresentationController?.sourceRect = self.view.bounds
        self.present(activity, animated: true)
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
        cell.detailTextLabel?.numberOfLines = 3
        switch row {
        case let .value(title, value):
            cell.textLabel?.text = title
            cell.detailTextLabel?.text = value
            cell.selectionStyle = .none
            cell.accessoryType = .none
        case let .action(title, _):
            cell.textLabel?.text = title
            cell.detailTextLabel?.text = nil
            cell.selectionStyle = .default
            cell.accessoryType = .disclosureIndicator
        }
        return cell
    }

    public override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        if case let .action(_, action) = self.sections[indexPath.section].rows[indexPath.row] {
            action()
        }
    }
}

/// A read-only source viewer.
public final class PluginSourceViewController: UIViewController {
    private let source: String
    private let textView = UITextView()

    public init(title: String, source: String) {
        self.source = source
        super.init(nibName: nil, bundle: nil)
        self.title = title
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.view.backgroundColor = .systemBackground
        self.textView.translatesAutoresizingMaskIntoConstraints = false
        self.textView.isEditable = false
        self.textView.font = UIFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        self.textView.text = self.source
        self.view.addSubview(self.textView)
        NSLayoutConstraint.activate([
            self.textView.leadingAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.leadingAnchor),
            self.textView.trailingAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.trailingAnchor),
            self.textView.topAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.topAnchor),
            self.textView.bottomAnchor.constraint(equalTo: self.view.safeAreaLayoutGuide.bottomAnchor)
        ])
    }
}
