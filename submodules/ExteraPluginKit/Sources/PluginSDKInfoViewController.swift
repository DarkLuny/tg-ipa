import Foundation
import UIKit

/// The "Plugins engine" screen, the iOS counterpart of Android's
/// `PluginsInfoActivity`: the engine switches (engine, safe mode, developer
/// mode, static analysis, compact view), the development server state, and the
/// runtime/paths/counts that Android shows below them.
public final class PluginSDKInfoViewController: UITableViewController {
    private enum Row {
        case toggle(title: String, detail: String?, value: Bool, tag: Int, enabled: Bool)
        case value(title: String, value: String)
        case action(title: String, detail: String?)
    }

    private var sections: [(String, [Row])] = []
    private var devServerRunning = false
    private var devServerAddress = "127.0.0.1"
    private var devServerPort = 0
    private var devServerError: String?
    private var busy = false

    public init() {
        super.init(style: .insetGrouped)
        self.title = "Plugins engine"
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        self.buildSections()
        self.refreshDevServerState { [weak self] in
            guard let self else {
                return
            }
            self.buildSections()
            self.tableView.reloadData()
        }
    }

    public override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        self.buildSections()
        self.tableView.reloadData()
        self.refreshDevServerState { [weak self] in
            guard let self else {
                return
            }
            self.buildSections()
            self.tableView.reloadData()
            self.syncDeveloperMode()
        }
    }

    private func refreshDevServerState(completion: (() -> Void)? = nil) {
        guard PythonRuntime.shared.isStarted else {
            self.devServerRunning = false
            completion?()
            return
        }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let value = try? PythonRuntime.shared.call("dev_server_state", [])
            DispatchQueue.main.async {
                guard let self else {
                    completion?()
                    return
                }
                let object = value as? [String: Any] ?? [:]
                self.devServerRunning = (object["running"] as? Bool) ?? false
                if let host = object["host"] as? String, !host.isEmpty {
                    self.devServerAddress = host
                }
                self.devServerPort = (object["port"] as? NSNumber)?.intValue ?? 0
                self.devServerError = object["error"] as? String
                completion?()
            }
        }
    }

    private func buildSections() {
        let preferences = PluginPreferences.shared
        let python = PythonRuntime.shared
        let active = preferences.isEngineActive

        var developerDetail: String?
        if preferences.developerMode {
            if let error = self.devServerError, !error.isEmpty {
                developerDetail = error
            } else if self.devServerRunning {
                let port = self.devServerPort > 0 ? ":\(self.devServerPort)" : ""
                developerDetail = "Listening on \(self.devServerAddress)\(port)"
            } else {
                developerDetail = "The development server is not running."
            }
        } else {
            developerDetail = "Starts a loopback server for remote plugin debugging and sets the log level to debug."
        }

        let engine: [Row] = [
            .toggle(
                title: "Plugins engine",
                detail: "Runs Python plugins. Turning it off unloads every plugin until it is turned back on.",
                value: preferences.engineEnabled,
                tag: 0,
                enabled: true
            ),
            .toggle(
                title: "Safe mode",
                detail: "Loads no plugins while it is on. Use it after a plugin crash.",
                value: preferences.safeMode,
                tag: 1,
                enabled: preferences.engineEnabled
            ),
            .toggle(
                title: "Developer mode",
                detail: developerDetail,
                value: preferences.developerMode,
                tag: 2,
                enabled: active && python.isStarted
            ),
            .toggle(
                title: "Static analysis",
                detail: "Analyzes a plugin before installation. Turning it off installs without the report.",
                value: preferences.staticAnalysis,
                tag: 3,
                enabled: active
            ),
            .toggle(
                title: "Compact view",
                detail: "Shows one-line plugin rows without descriptions.",
                value: preferences.compactView,
                tag: 4,
                enabled: true
            ),
            .toggle(
                title: "Unknown sources",
                detail: "Allows installing plugins that are not published in a trusted plugin catalog.",
                value: preferences.allowUnknownSources,
                tag: 5,
                enabled: true
            ),
        ]

        let manager = PluginManager.shared
        let plugins = manager.plugins

        var runtime: [Row] = [
            .value(title: "SDK", value: PluginHostInfo.sdkVersion),
            .value(title: "App compatibility", value: PluginHostInfo.compatibilityVersion),
            .value(title: "Build", value: PluginHostInfo.buildNumber),
            .value(title: "CPython", value: python.isAvailable ? (python.isStarted ? "Running" : "Embedded") : "Not embedded"),
            .value(title: "Analyzer", value: "swift-lexical (bundled)"),
        ]
        if let error = manager.startError {
            runtime.append(.value(title: "Start error", value: error))
        }

        let paths: [Row] = [
            .value(title: "SDK", value: manager.sdkURL.path),
            .value(title: "Plugins", value: manager.storeURL.path),
            .value(title: "SDK size", value: self.formattedSize(of: manager.sdkURL)),
        ]

        let counts: [Row] = [
            .value(title: "Installed", value: "\(plugins.count)"),
            .value(title: "Python (.plugin)", value: "\(plugins.filter { !$0.isElyx }.count)"),
            .value(title: "Elyx (.elyx)", value: "\(plugins.filter { $0.isElyx }.count)"),
            .value(title: "Enabled", value: "\(plugins.filter { $0.isEnabled }.count)"),
            .value(title: "Loaded", value: "\(plugins.filter { $0.isLoaded }.count)"),
        ]

        let actions: [Row] = [
            .action(
                title: "Restore SDK from app bundle",
                detail: "Replaces the installed SDK with the one inside this app and restarts the engine."
            ),
            .action(
                title: "Reload all plugins",
                detail: "Stops the runtime and loads every enabled plugin again."
            ),
        ]

        self.sections = [
            ("Engine", engine),
            ("Runtime", runtime),
            ("Paths", paths),
            ("Plugins", counts),
            ("Actions", actions),
        ]
    }

    private func formattedSize(of url: URL) -> String {
        let values = try? url.resourceValues(forKeys: [.isDirectoryKey])
        var total: Int64 = 0
        if values?.isDirectory == true {
            let enumerator = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.fileSizeKey])
            while let item = enumerator?.nextObject() as? URL {
                if let size = (try? item.resourceValues(forKeys: [.fileSizeKey]))?.fileSize {
                    total += Int64(size)
                }
            }
        } else {
            total = Int64((try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0)
        }
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useKB, .useMB, .useGB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: total)
    }

    // -- Actions -------------------------------------------------------------

    @objc private func switchChanged(_ sender: UISwitch) {
        let preferences = PluginPreferences.shared
        switch sender.tag {
        case 0:
            preferences.engineEnabled = sender.isOn
            self.applyPreferences()
        case 1:
            preferences.safeMode = sender.isOn
            self.applyPreferences()
        case 2:
            preferences.developerMode = sender.isOn
            self.setDeveloperMode(sender.isOn)
        case 3:
            preferences.staticAnalysis = sender.isOn
            self.buildSections()
            self.tableView.reloadData()
        case 4:
            preferences.compactView = sender.isOn
            self.buildSections()
            self.tableView.reloadData()
        case 5:
            preferences.allowUnknownSources = sender.isOn
            self.buildSections()
            self.tableView.reloadData()
        default:
            break
        }
    }

    private func applyPreferences() {
        guard !self.busy else {
            return
        }
        self.busy = true
        self.activityStart()
        PluginManager.shared.applyPreferences { [weak self] in
            guard let self else {
                return
            }
            self.busy = false
            self.activityStop()
            self.refreshDevServerState { [weak self] in
                guard let self else {
                    return
                }
                self.buildSections()
                self.tableView.reloadData()
                self.syncDeveloperMode()
            }
        }
    }

    private func setDeveloperMode(_ enabled: Bool) {
        let preferences = PluginPreferences.shared
        guard PythonRuntime.shared.isStarted else {
            preferences.developerMode = false
            self.buildSections()
            self.tableView.reloadData()
            return
        }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let value = try? PythonRuntime.shared.call(
                enabled ? "dev_server_start" : "dev_server_stop", []
            )
            let object = value as? [String: Any] ?? [:]
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.devServerRunning = (object["running"] as? Bool) ?? false
                if let host = object["host"] as? String, !host.isEmpty {
                    self.devServerAddress = host
                }
                self.devServerPort = (object["port"] as? NSNumber)?.intValue ?? 0
                self.devServerError = object["error"] as? String
                if enabled && !self.devServerRunning {
                    preferences.developerMode = false
                }
                self.buildSections()
                self.tableView.reloadData()
            }
        }
    }

    private func syncDeveloperMode() {
        let preferences = PluginPreferences.shared
        guard preferences.developerMode,
              preferences.isEngineActive,
              PythonRuntime.shared.isStarted,
              !self.devServerRunning else {
            return
        }
        self.setDeveloperMode(true)
    }

    private func activityStart() {
        let activity = UIActivityIndicatorView(style: .medium)
        activity.startAnimating()
        self.tableView.tableFooterView = activity
    }

    private func activityStop() {
        self.tableView.tableFooterView = nil
    }

    // -- Table ---------------------------------------------------------------

    public override func numberOfSections(in tableView: UITableView) -> Int {
        return self.sections.count
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        return self.sections[section].1.count
    }

    public override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        return self.sections[section].0
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let row = self.sections[indexPath.section].1[indexPath.row]
        switch row {
        case let .toggle(title, detail, value, tag, enabled):
            let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
            cell.textLabel?.text = title
            cell.textLabel?.numberOfLines = 1
            cell.detailTextLabel?.text = detail
            cell.detailTextLabel?.numberOfLines = 4
            cell.selectionStyle = .none
            let toggle = UISwitch()
            toggle.isOn = value
            toggle.tag = tag
            toggle.isEnabled = enabled
            toggle.addTarget(self, action: #selector(self.switchChanged(_:)), for: .valueChanged)
            cell.accessoryView = toggle
            return cell
        case let .value(title, value):
            let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
            cell.textLabel?.text = title
            cell.detailTextLabel?.text = value
            cell.detailTextLabel?.numberOfLines = 3
            cell.selectionStyle = .none
            return cell
        case let .action(title, detail):
            let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
            cell.textLabel?.text = title
            cell.detailTextLabel?.text = detail
            cell.detailTextLabel?.numberOfLines = 4
            cell.selectionStyle = .default
            cell.accessoryType = .disclosureIndicator
            return cell
        }
    }

    public override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        guard indexPath.section < self.sections.count else {
            return
        }
        let row = self.sections[indexPath.section].1[indexPath.row]
        guard case let .action(title, _) = row else {
            return
        }
        if title == "Restore SDK from app bundle" {
            self.confirmRestoreSDK()
        } else if title == "Reload all plugins" {
            self.busy = true
            self.activityStart()
            PluginManager.shared.reloadAll { [weak self] in
                guard let self else {
                    return
                }
                self.busy = false
                self.activityStop()
                self.refreshDevServerState { [weak self] in
                    guard let self else {
                        return
                    }
                    self.buildSections()
                    self.tableView.reloadData()
                }
            }
        }
    }

    private func confirmRestoreSDK() {
        let alert = UIAlertController(
            title: "Restore SDK from app bundle?",
            message: "The installed plugins SDK will be replaced with the copy inside this app. Plugins and settings are kept.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Restore", style: .destructive) { [weak self] _ in
            guard let self else {
                return
            }
            self.busy = true
            self.activityStart()
            PluginManager.shared.restoreBundledSDK { [weak self] success, error in
                guard let self else {
                    return
                }
                self.busy = false
                self.activityStop()
                self.refreshDevServerState { [weak self] in
                    guard let self else {
                        return
                    }
                    self.buildSections()
                    self.tableView.reloadData()
                }
                if !success {
                    let failure = UIAlertController(
                        title: "Restore failed",
                        message: error ?? "The SDK could not be restored.",
                        preferredStyle: .alert
                    )
                    failure.addAction(UIAlertAction(title: "OK", style: .default))
                    self.present(failure, animated: true)
                }
            }
        })
        self.present(alert, animated: true)
    }
}
