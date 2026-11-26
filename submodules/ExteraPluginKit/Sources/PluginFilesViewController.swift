import Foundation
import UIKit

/// Browses the files of an installed plugin, the iOS counterpart of Android's
/// `PluginFileViewer` for Elyx plugins (whose plugin is a directory).
public final class PluginFilesViewController: UITableViewController {
    private let directory: URL
    private var entries: [URL] = []

    public init(directory: URL, title: String? = nil) {
        self.directory = directory
        super.init(style: .insetGrouped)
        self.title = title ?? directory.lastPathComponent
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        self.load()
    }

    private func load() {
        let values = (try? FileManager.default.contentsOfDirectory(
            at: self.directory,
            includingPropertiesForKeys: [.isDirectoryKey, .fileSizeKey],
            options: [.skipsHiddenFiles]
        )) ?? []
        self.entries = values.sorted { lhs, rhs in
            let leftDirectory = (try? lhs.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory ?? false
            let rightDirectory = (try? rhs.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory ?? false
            if leftDirectory != rightDirectory {
                return leftDirectory && !rightDirectory
            }
            return lhs.lastPathComponent.localizedStandardCompare(rhs.lastPathComponent) == .orderedAscending
        }
        self.tableView.reloadData()
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        return max(1, self.entries.count)
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: "cell")
        guard !self.entries.isEmpty else {
            cell.textLabel?.text = "Empty folder"
            cell.textLabel?.textColor = .secondaryLabel
            cell.selectionStyle = .none
            return cell
        }
        let url = self.entries[indexPath.row]
        let values = try? url.resourceValues(forKeys: [.isDirectoryKey, .fileSizeKey])
        let isDirectory = values?.isDirectory ?? false
        cell.textLabel?.text = url.lastPathComponent
        cell.imageView?.image = UIImage(systemName: isDirectory ? "folder" : "doc.text")
        cell.imageView?.tintColor = .systemBlue
        if isDirectory {
            cell.detailTextLabel?.text = "Folder"
        } else {
            let size = Int64(values?.fileSize ?? 0)
            cell.detailTextLabel?.text = ByteCountFormatter.string(fromByteCount: size, countStyle: .file)
        }
        cell.accessoryType = .disclosureIndicator
        cell.selectionStyle = .default
        return cell
    }

    public override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        guard !self.entries.isEmpty else {
            return
        }
        let url = self.entries[indexPath.row]
        let isDirectory = (try? url.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory ?? false
        if isDirectory {
            self.navigationController?.pushViewController(
                PluginFilesViewController(directory: url),
                animated: true
            )
            return
        }
        if let data = try? Data(contentsOf: url), let text = String(data: data, encoding: .utf8) {
            self.navigationController?.pushViewController(
                PluginSourceViewController(title: url.lastPathComponent, source: text),
                animated: true
            )
        } else {
            let alert = UIAlertController(
                title: "Cannot preview",
                message: "This file is not UTF-8 text.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "OK", style: .default))
            self.present(alert, animated: true)
        }
    }
}
