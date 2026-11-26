import Foundation
import UIKit
import UniformTypeIdentifiers

/// The Plugins screen.
///
/// It uses UIKit directly rather than Telegram's component system: the kit is
/// usable from a Settings row, a debug menu or a standalone test app, and it
/// must not depend on TelegramUI (TelegramUI depends on the kit for the settings
/// row, so importing it back would be a cycle).
public final class PluginsViewController: UITableViewController {
    private enum Section {
        case engine
        case installed
        case menu
        case actions
    }

    private var plugins: [Plugin] = []
    private var visiblePlugins: [Plugin] = []
    private var menuItems: [PluginMenuItem] = []
    private var observer: NSObjectProtocol?
    private let activity = UIActivityIndicatorView(style: .medium)
    private let searchController = UISearchController(searchResultsController: nil)
    private var presentedCrashAlert = false
    private var alertedNotResponding = Set<String>()

    public init() {
        super.init(style: .insetGrouped)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    deinit {
        if let observer {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.title = "Plugins"
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        self.searchController.searchResultsUpdater = self
        self.searchController.obscuresBackgroundDuringPresentation = false
        self.searchController.searchBar.placeholder = "Search"
        self.navigationItem.searchController = self.searchController
        self.navigationItem.hidesSearchBarWhenScrolling = false
        self.definesPresentationContext = true
        self.navigationItem.rightBarButtonItem = UIBarButtonItem(
            barButtonSystemItem: .add, target: self, action: #selector(self.installTapped)
        )
        self.navigationItem.leftBarButtonItem = UIBarButtonItem(
            title: "Reload", style: .plain, target: self, action: #selector(self.reloadAll)
        )
        self.activity.hidesWhenStopped = true
        self.tableView.tableFooterView = self.activity
        self.activity.startAnimating()

        self.observer = NotificationCenter.default.addObserver(
            forName: PluginManager.didChange, object: nil, queue: .main
        ) { [weak self] _ in
            self?.reload()
        }
        PluginManager.shared.start { [weak self] in
            self?.activity.stopAnimating()
            self?.reload()
        }
        self.reload()
    }

    private func reload() {
        let all = PluginManager.shared.plugins.sorted { lhs, rhs in
            let leftPinned = PluginManager.shared.isPinned(pluginId: lhs.id)
            let rightPinned = PluginManager.shared.isPinned(pluginId: rhs.id)
            if leftPinned != rightPinned {
                return leftPinned && !rightPinned
            }
            return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
        }
        self.plugins = all
        let query = self.searchController.searchBar.text?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if query.isEmpty {
            self.visiblePlugins = all
        } else {
            self.visiblePlugins = all.filter { $0.name.localizedCaseInsensitiveContains(query) }
        }
        let context: [String: Any] = ["_host": "plugins_screen"]
        self.menuItems = PluginHooks.shared.menuItems(for: .mainMenu, context: context)
            + PluginHooks.shared.menuItems(for: .drawerMenu, context: context)
        self.tableView.reloadData()
        self.presentNotRespondingAlertIfNeeded()
    }

    private func presentNotRespondingAlertIfNeeded() {
        guard self.viewIfLoaded?.window != nil, self.presentedViewController == nil else {
            return
        }
        guard let plugin = self.plugins.first(where: {
            $0.isNotResponding && !self.alertedNotResponding.contains($0.id)
        }) else {
            return
        }
        self.alertedNotResponding.insert(plugin.id)
        let alert = UIAlertController(
            title: "Plugin not responding",
            message: "\(plugin.name) is taking too long to handle an event. You can wait, or disable it and enable it again later.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Wait", style: .default) { [weak self] _ in
            self?.alertedNotResponding.remove(plugin.id)
        })
        alert.addAction(UIAlertAction(title: "Disable plugin", style: .destructive) { _ in
            PluginManager.shared.setEnabled(false, pluginId: plugin.id) { _ in }
        })
        self.present(alert, animated: true)
    }

    public override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        self.presentCrashAlertIfNeeded()
    }

    private func presentCrashAlertIfNeeded() {
        guard !self.presentedCrashAlert else {
            return
        }
        guard let plugin = self.plugins.first(where: { $0.error == "the app crashed while loading this plugin" }) else {
            return
        }
        self.presentedCrashAlert = true
        let alert = UIAlertController(
            title: "Safe mode",
            message: "\(plugin.name) was disabled because the app crashed while loading it. The other plugins were loaded as usual.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Plugin details", style: .default) { [weak self] _ in
            self?.navigationController?.pushViewController(PluginInfoViewController(plugin: plugin), animated: true)
        })
        alert.addAction(UIAlertAction(title: "OK", style: .cancel))
        self.present(alert, animated: true)
    }

    @objc private func reloadAll() {
        PluginManager.shared.start { [weak self] in
            self?.reload()
        }
        self.reload()
    }

    @objc private func installTapped() {
        if #available(iOS 14.0, *) {
            let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.data, .item], asCopy: true)
            picker.delegate = self
            picker.allowsMultipleSelection = false
            self.present(picker, animated: true)
        } else {
            let picker = UIDocumentPickerViewController(documentTypes: ["public.data", "public.item"], in: .import)
            picker.delegate = self
            self.present(picker, animated: true)
        }
    }

    /// Opens the document picker used by the “install plugin” action.
    /// The host exposes it to plugins as `plugins.show_install`.
    public func presentInstallPicker() {
        self.loadViewIfNeeded()
        self.installTapped()
    }

    @objc private func installURLTapped() {
        let alert = UIAlertController(
            title: "Install from URL",
            message: "Enter an http(s) link to a .plugin, .elyx or .eaf file.",
            preferredStyle: .alert
        )
        alert.addTextField { field in
            field.placeholder = "https://example.com/plugin.plugin"
            field.autocapitalizationType = .none
            field.autocorrectionType = .no
            field.keyboardType = .URL
        }
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Install", style: .default) { [weak self, weak alert] _ in
            guard let text = alert?.textFields?.first?.text, !text.isEmpty else {
                return
            }
            self?.activity.startAnimating()
            PluginManager.shared.downloadPlugin(urlString: text) { [weak self] result in
                DispatchQueue.main.async {
                    self?.activity.stopAnimating()
                    switch result {
                    case let .success(url):
                        self?.presentInstall(for: url, displayName: url.lastPathComponent)
                    case let .failure(error):
                        let failure = UIAlertController(title: "Download failed", message: error, preferredStyle: .alert)
                        failure.addAction(UIAlertAction(title: "OK", style: .default))
                        self?.present(failure, animated: true)
                    }
                }
            }
        })
        self.present(alert, animated: true)
    }

    /// Runs the analyzer and opens the install sheet for a downloaded or picked
    /// file, the same two-step flow the catalog and the chat attachment use.
    private func presentInstall(for fileURL: URL, displayName: String) {
        let extensionName = fileURL.pathExtension.lowercased()
        if extensionName == "elyx" || extensionName == "eaf" {
            PluginManager.shared.inspectElyx(url: fileURL) { [weak self] inspection in
                let controller = PluginElyxInstallViewController(url: fileURL, inspection: inspection) {
                    self?.reload()
                }
                self?.navigationController?.pushViewController(controller, animated: true)
            }
            return
        }
        let report = PluginAnalyzer.shared.analyzeSynchronously(
            PluginAnalysisRequest(fileURL: fileURL, name: displayName)
        )
        let install = PluginAnalysisViewController(
            title: "Install plugin",
            subtitle: displayName,
            report: report,
            installTitle: "Install",
            onInstall: nil,
            requirements: (try? PluginManifestParser.parse(fileAt: fileURL))?.requirements ?? [],
            onInstallWithEnable: { [weak self] enabled in
                PluginManager.shared.install(url: fileURL, enabled: enabled) { result in
                    if let error = result.error {
                        let alert = UIAlertController(title: "Install failed", message: error, preferredStyle: .alert)
                        alert.addAction(UIAlertAction(title: "OK", style: .default))
                        self?.present(alert, animated: true)
                    }
                    self?.reload()
                }
            }
        )
        self.navigationController?.pushViewController(install, animated: true)
    }

    private func open(_ plugin: Plugin) {
        let controller = PluginSettingsViewController(pluginId: plugin.id)
        self.navigationController?.pushViewController(controller, animated: true)
    }

    private func showAnalysis(_ plugin: Plugin) {
        if plugin.isElyx {
            var message = plugin.manifest.description
            if let error = plugin.error, !error.isEmpty {
                message = message.isEmpty ? error : "\(message)\n\n\(error)"
            }
            let alert = UIAlertController(
                title: "\(plugin.name) \(plugin.manifest.version)",
                message: message,
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "OK", style: .default))
            self.present(alert, animated: true)
            return
        }
        guard let data = try? Data(contentsOf: plugin.path) else {
            return
        }
        let report = PluginAnalyzer.shared.analyzeSynchronously(
            PluginAnalysisRequest(fileURL: plugin.path, name: plugin.path.lastPathComponent)
        )
        let controller = PluginAnalysisViewController(
            title: plugin.name,
            subtitle: "\(plugin.manifest.version) by \(plugin.manifest.author)",
            report: report,
            installTitle: nil,
            onInstall: nil,
            requirements: plugin.manifest.requirements
        )
        self.navigationController?.pushViewController(controller, animated: true)
        _ = data
    }

    private func icon(for plugin: Plugin) -> UIImage? {
        guard let name = plugin.manifest.icon, !name.isEmpty else {
            return nil
        }
        let path: String?
        if plugin.isElyx {
            path = plugin.path.appendingPathComponent(name).path
        } else {
            path = plugin.path.deletingLastPathComponent().appendingPathComponent(name).path
        }
        if let path, let image = UIImage(contentsOfFile: path) {
            return image
        }
        return nil
    }

    private func openInfo(_ plugin: Plugin) {
        self.navigationController?.pushViewController(PluginInfoViewController(plugin: plugin), animated: true)
    }

    // -- Table view ----------------------------------------------------------

    private var sections: [Section] {
        var sections: [Section] = [.engine]
        if PluginPreferences.shared.isEngineActive {
            sections.append(.installed)
            if !self.menuItems.isEmpty {
                sections.append(.menu)
            }
        }
        sections.append(.actions)
        return sections
    }

    public override func numberOfSections(in tableView: UITableView) -> Int {
        return self.sections.count
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        switch self.sections[section] {
        case .engine:
            return 1
        case .installed:
            return max(1, self.visiblePlugins.count)
        case .menu:
            return self.menuItems.count
        case .actions:
            return 6
        }
    }

    public override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        switch self.sections[section] {
        case .engine:
            return nil
        case .installed:
            return "Installed"
        case .menu:
            return "Plugin actions"
        case .actions:
            return "Actions"
        }
    }

    public override func tableView(_ tableView: UITableView, titleForFooterInSection section: Int) -> String? {
        if self.sections[section] == .engine {
            if PluginPreferences.shared.safeMode {
                return "Safe mode is on: no plugin code is loaded until you turn it off in Plugins engine."
            }
            return "Turning the engine off unloads every plugin without deleting it or its settings."
        }
        guard self.sections[section] == .installed else {
            return nil
        }
        if !PythonRuntime.shared.isAvailable {
            return "This build does not embed CPython, so plugins cannot run. The list and the analyzer still work."
        }
        if let startError = PluginManager.shared.startError {
            return "The plugin runtime did not start: \(startError)"
        }
        return "Plugins run Python code with the app's permissions. Install only code you trust."
    }

    public override func tableView(_ tableView: UITableView, heightForRowAt indexPath: IndexPath) -> CGFloat {
        guard indexPath.section < self.sections.count else {
            return UITableView.automaticDimension
        }
        if self.sections[indexPath.section] == .installed, PluginPreferences.shared.compactView {
            return 44
        }
        return UITableView.automaticDimension
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        cell.accessoryView = nil
        cell.accessoryType = .none
        cell.textLabel?.numberOfLines = 2

        switch self.sections[indexPath.section] {
        case .engine:
            let preferences = PluginPreferences.shared
            cell.textLabel?.text = "Plugins engine"
            if preferences.safeMode {
                cell.detailTextLabel?.text = "Safe mode is on — plugins are not loaded."
            } else if preferences.engineEnabled {
                cell.detailTextLabel?.text = "On"
            } else {
                cell.detailTextLabel?.text = "Off"
            }
            cell.textLabel?.numberOfLines = 1
            cell.selectionStyle = .none
            let toggle = UISwitch()
            toggle.isOn = preferences.engineEnabled
            toggle.addTarget(self, action: #selector(self.engineChanged(_:)), for: .valueChanged)
            cell.accessoryView = toggle
            return cell
        case .installed:
            guard !self.visiblePlugins.isEmpty else {
                cell.textLabel?.text = self.plugins.isEmpty ? "No plugins installed" : "No results"
                cell.textLabel?.textColor = .secondaryLabel
                cell.selectionStyle = .none
                return cell
            }
            let plugin = self.visiblePlugins[indexPath.row]
            if let icon = self.icon(for: plugin) {
                cell.imageView?.image = icon
            } else {
                cell.imageView?.image = UIImage(systemName: PluginIcon.systemName(for: plugin.manifest.icon ?? ""))
            }
            let status: String
            if let error = plugin.error {
                let lastLine = error.split(separator: "\n").last.map(String.init) ?? error
                status = " — " + lastLine
            } else if plugin.isNotResponding {
                status = " — not responding"
            } else {
                status = ""
            }
            cell.textLabel?.text = plugin.name + status
            cell.textLabel?.textColor = plugin.error == nil ? .label : .systemRed
            let pinned = PluginManager.shared.isPinned(pluginId: plugin.id)
            if PluginPreferences.shared.compactView {
                cell.textLabel?.numberOfLines = 1
                cell.detailTextLabel?.text = pinned ? "Pinned" : nil
            } else {
                let prefix = pinned ? "Pinned · " : ""
                cell.detailTextLabel?.text = "\(prefix)\(plugin.manifest.version) · \(plugin.manifest.author)"
            }

            let toggle = UISwitch()
            toggle.isOn = plugin.isEnabled
            toggle.tag = indexPath.row
            toggle.addTarget(self, action: #selector(self.toggleChanged(_:)), for: .valueChanged)
            cell.accessoryView = toggle
            cell.selectionStyle = .default
            return cell
        case .menu:
            let item = self.menuItems[indexPath.row]
            cell.imageView?.image = UIImage(systemName: PluginIcon.systemName(for: item.icon ?? ""))
            cell.textLabel?.text = item.text
            cell.textLabel?.textColor = .label
            cell.detailTextLabel?.text = item.subtext ?? item.pluginId
            cell.accessoryType = .none
            cell.selectionStyle = .default
            return cell
        case .actions:
            cell.accessoryView = nil
            cell.accessoryType = .disclosureIndicator
            cell.textLabel?.textColor = .label
            if indexPath.row == 0 {
                cell.textLabel?.text = "Install from file…"
            } else if indexPath.row == 1 {
                cell.textLabel?.text = "Install from URL…"
            } else if indexPath.row == 2 {
                cell.textLabel?.text = "Plugin catalog"
            } else if indexPath.row == 3 {
                cell.textLabel?.text = "Plugins engine"
            } else if indexPath.row == 4 {
                cell.textLabel?.text = "View log"
            } else {
                cell.textLabel?.text = "Clear log"
            }
            cell.selectionStyle = .default
            return cell
        }
    }

    public override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        switch self.sections[indexPath.section] {
        case .engine:
            let toggle = PluginPreferences.shared.engineEnabled
            PluginPreferences.shared.engineEnabled = !toggle
            PluginManager.shared.applyPreferences { [weak self] in
                self?.reload()
            }
        case .installed:
            guard !self.visiblePlugins.isEmpty else {
                self.navigationController?.pushViewController(PluginCatalogViewController(), animated: true)
                return
            }
            self.open(self.visiblePlugins[indexPath.row])
        case .menu:
            let item = self.menuItems[indexPath.row]
            PluginHooks.shared.invokeMenuItem(item, context: ["_host": "plugins_screen"])
        case .actions:
            if indexPath.row == 0 {
                self.installTapped()
            } else if indexPath.row == 1 {
                self.installURLTapped()
            } else if indexPath.row == 2 {
                self.navigationController?.pushViewController(PluginCatalogViewController(), animated: true)
            } else if indexPath.row == 3 {
                self.navigationController?.pushViewController(PluginSDKInfoViewController(), animated: true)
            } else if indexPath.row == 4 {
                self.navigationController?.pushViewController(PluginLogViewController(), animated: true)
            } else {
                PluginLog.clear()
            }
        }
    }

    public override func tableView(_ tableView: UITableView, trailingSwipeActionsConfigurationForRowAt indexPath: IndexPath) -> UISwipeActionsConfiguration? {
        guard indexPath.section < self.sections.count,
              self.sections[indexPath.section] == .installed,
              !self.visiblePlugins.isEmpty else {
            return nil
        }
        let plugin = self.visiblePlugins[indexPath.row]
        let delete = UIContextualAction(style: .destructive, title: "Delete") { [weak self] _, _, completion in
            self?.confirmDelete(plugin, completion: completion)
        }
        let reload = UIContextualAction(style: .normal, title: "Reload") { [weak self] _, _, completion in
            PluginManager.shared.reload(pluginId: plugin.id) { _ in
                self?.reload()
                completion(true)
            }
        }
        reload.backgroundColor = .systemBlue
        let info = UIContextualAction(style: .normal, title: "Info") { [weak self] _, _, completion in
            self?.openInfo(plugin)
            completion(true)
        }
        info.backgroundColor = .systemOrange
        let pinTitle = PluginManager.shared.isPinned(pluginId: plugin.id) ? "Unpin" : "Pin"
        let pin = UIContextualAction(style: .normal, title: pinTitle) { [weak self] _, _, completion in
            let pinned = PluginManager.shared.isPinned(pluginId: plugin.id)
            PluginManager.shared.setPinned(!pinned, pluginId: plugin.id)
            self?.reload()
            completion(true)
        }
        pin.backgroundColor = .systemPurple
        let share = UIContextualAction(style: .normal, title: "Share") { [weak self, weak tableView] _, _, completion in
            guard let self else {
                completion(false)
                return
            }
            if plugin.isElyx {
                PluginManager.shared.exportElyxArchive(pluginId: plugin.id) { [weak self] url in
                    guard let self, let url else {
                        completion(false)
                        return
                    }
                    self.presentShareSheet(url: url, indexPath: indexPath, tableView: tableView)
                    completion(true)
                }
            } else {
                let url = PluginManager.shared.pluginFileURL(id: plugin.id)
                self.presentShareSheet(url: url, indexPath: indexPath, tableView: tableView)
                completion(true)
            }
        }
        share.backgroundColor = .systemGreen
        return UISwipeActionsConfiguration(actions: [delete, reload, pin, share, info])
    }

    public override func tableView(_ tableView: UITableView, contextMenuConfigurationForRowAt indexPath: IndexPath, point: CGPoint) -> UIContextMenuConfiguration? {
        guard indexPath.section < self.sections.count,
              self.sections[indexPath.section] == .installed,
              indexPath.row < self.visiblePlugins.count else {
            return nil
        }
        let plugin = self.visiblePlugins[indexPath.row]
        let pinned = PluginManager.shared.isPinned(pluginId: plugin.id)
        var actions: [UIAction] = [
            UIAction(title: "Settings", image: UIImage(systemName: "gearshape")) { [weak self] _ in
                self?.open(plugin)
            },
            UIAction(
                title: plugin.isEnabled ? "Disable" : "Enable",
                image: UIImage(systemName: plugin.isEnabled ? "pause.circle" : "play.circle")
            ) { [weak self] _ in
                PluginManager.shared.setEnabled(!plugin.isEnabled, pluginId: plugin.id) { _ in
                    self?.reload()
                }
            },
            UIAction(
                title: pinned ? "Unpin" : "Pin",
                image: UIImage(systemName: pinned ? "pin.slash" : "pin")
            ) { [weak self] _ in
                PluginManager.shared.setPinned(!pinned, pluginId: plugin.id)
                self?.reload()
            },
            UIAction(title: "Info", image: UIImage(systemName: "info.circle")) { [weak self] _ in
                self?.openInfo(plugin)
            },
        ]
        actions.append(UIAction(
            title: "Delete",
            image: UIImage(systemName: "trash"),
            attributes: .destructive
        ) { [weak self] _ in
            self?.confirmDelete(plugin, completion: nil)
        })
        return UIContextMenuConfiguration(identifier: nil, previewProvider: nil) { _ in
            UIMenu(children: actions)
        }
    }

    private func confirmDelete(_ plugin: Plugin, completion: ((Bool) -> Void)?) {
        let alert = UIAlertController(
            title: "Delete \(plugin.name)?",
            message: "The plugin and its settings will be removed.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completion?(false) })
        alert.addAction(UIAlertAction(title: "Delete", style: .destructive) { [weak self] _ in
            PluginManager.shared.delete(pluginId: plugin.id) { _ in
                self?.reload()
                completion?(true)
            }
        })
        self.present(alert, animated: true)
    }

    private func presentShareSheet(url: URL, indexPath: IndexPath, tableView: UITableView?) {
        let activity = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        if let tableView {
            activity.popoverPresentationController?.sourceView = tableView
            activity.popoverPresentationController?.sourceRect = tableView.rectForRow(at: indexPath)
        }
        self.present(activity, animated: true)
    }

    @objc private func engineChanged(_ sender: UISwitch) {
        PluginPreferences.shared.engineEnabled = sender.isOn
        sender.isEnabled = false
        PluginManager.shared.applyPreferences { [weak self] in
            self?.reload()
        }
    }

    @objc private func toggleChanged(_ sender: UISwitch) {
        guard sender.tag < self.visiblePlugins.count else {
            return
        }
        let plugin = self.visiblePlugins[sender.tag]
        sender.isEnabled = false
        PluginManager.shared.setEnabled(sender.isOn, pluginId: plugin.id) { [weak self] _ in
            sender.isEnabled = true
            self?.reload()
        }
    }
}

extension PluginsViewController: UISearchResultsUpdating {
    public func updateSearchResults(for searchController: UISearchController) {
        self.reload()
    }
}

extension PluginsViewController: UIDocumentPickerDelegate {
    public func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        guard let url = urls.first else {
            return
        }
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(url.lastPathComponent)
        try? FileManager.default.removeItem(at: temporary)
        do {
            try FileManager.default.copyItem(at: url, to: temporary)
        } catch {
            PluginLog.log("could not read the selected file: \(error)", level: .error)
            return
        }
        self.presentInstall(for: temporary, displayName: url.lastPathComponent)
    }
}
