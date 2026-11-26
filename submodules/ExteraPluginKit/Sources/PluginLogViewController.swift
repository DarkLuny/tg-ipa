import Foundation
import UIKit

/// Plain log viewer for every plugin, kept separate from the plugin screens so
/// a plugin that fails to load can still be diagnosed.
public final class PluginLogViewController: UITableViewController {
    private var entries: [PluginLogEntry] = []
    private var observer: NSObjectProtocol?
    private var shareItem: UIBarButtonItem?

    public init() {
        super.init(style: .plain)
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
        self.title = "Plugin log"
        let share = UIBarButtonItem(title: "Share", style: .plain, target: self, action: #selector(self.shareLog))
        self.shareItem = share
        self.navigationItem.rightBarButtonItems = [
            UIBarButtonItem(title: "Clear", style: .plain, target: self, action: #selector(self.clear)),
            share,
        ]
        self.observer = NotificationCenter.default.addObserver(forName: PluginLog.didChange, object: nil, queue: .main) { [weak self] _ in
            self?.reload()
        }
        self.reload()
    }

    @objc private func shareLog() {
        guard !self.entries.isEmpty else {
            return
        }
        let text = self.entries.map { entry in
            "[\(Self.formatter.string(from: entry.date))] \(entry.pluginId.isEmpty ? "host" : entry.pluginId) \(entry.level.rawValue): \(entry.text)"
        }.joined(separator: "\n")
        let activity = UIActivityViewController(activityItems: [text], applicationActivities: nil)
        activity.popoverPresentationController?.sourceView = self.view
        activity.popoverPresentationController?.sourceRect = self.view.bounds
        self.present(activity, animated: true)
    }

    private func reload() {
        self.entries = PluginLog.all()
        self.shareItem?.isEnabled = !self.entries.isEmpty
        self.tableView.reloadData()
        if !self.entries.isEmpty {
            self.tableView.scrollToRow(at: IndexPath(row: self.entries.count - 1, section: 0), at: .bottom, animated: false)
        }
    }

    @objc private func clear() {
        PluginLog.clear()
    }

    public override func numberOfSections(in tableView: UITableView) -> Int {
        return 1
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        return self.entries.count
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        let entry = self.entries[indexPath.row]
        cell.textLabel?.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        cell.textLabel?.numberOfLines = 0
        cell.textLabel?.text = entry.text
        cell.textLabel?.textColor = entry.level == .error ? .systemRed : (entry.level == .warning ? .systemOrange : .label)
        cell.detailTextLabel?.text = "\(entry.pluginId.isEmpty ? "host" : entry.pluginId) · \(entry.level.rawValue) · \(Self.formatter.string(from: entry.date))"
        cell.detailTextLabel?.font = .systemFont(ofSize: 10)
        return cell
    }

    private static let formatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()
}
