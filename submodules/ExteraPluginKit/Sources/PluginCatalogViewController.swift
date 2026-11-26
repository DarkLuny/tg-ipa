import Foundation
import UIKit

/// Repositories the user added, the iOS counterpart of Android's catalog
/// screen. A repository is a GitHub link or a direct `extera-plugins.json` URL.
public final class PluginCatalogViewController: UITableViewController {
    private let activity = UIActivityIndicatorView(style: .medium)
    private var repositories: [PluginCatalogRepository] = []
    private var sections: [(title: String?, repositories: [PluginCatalogRepository])] = []
    private var verifiedRefreshInFlight = false

    public init() {
        super.init(style: .insetGrouped)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.title = "Plugin catalog"
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        self.navigationItem.rightBarButtonItem = UIBarButtonItem(
            barButtonSystemItem: .add, target: self, action: #selector(self.addTapped)
        )
        self.activity.hidesWhenStopped = true
        self.tableView.tableFooterView = self.activity
        let refresh = UIRefreshControl()
        refresh.addTarget(self, action: #selector(self.refreshPulled(_:)), for: .valueChanged)
        self.refreshControl = refresh
        self.reload()
    }

    @objc private func refreshPulled(_ sender: UIRefreshControl) {
        self.reload()
        sender.endRefreshing()
    }

    private func reload() {
        self.repositories = PluginCatalogStore.shared.repositories
        self.rebuildSections()
        self.tableView.reloadData()
        self.refreshVerifiedIfNeeded()
    }

    private func rebuildSections() {
        let verified = self.repositories.filter { $0.isVerified }
        let folders = self.repositories.filter { $0.isFolder }
        let user = self.repositories.filter { !$0.isVerified && !$0.isFolder }
        var sections: [(title: String?, repositories: [PluginCatalogRepository])] = []
        if !verified.isEmpty {
            sections.append(("Verified", verified))
        }
        if !folders.isEmpty {
            sections.append(("Folders", folders))
        }
        sections.append(("Your repositories", user))
        self.sections = sections
    }

    /// Pulls Android's trusted folder (`pPhOtEq00KhjYTc6`) at most once every
    /// five minutes, replacing the verified rows like `refreshFolderRepositories`.
    private func refreshVerifiedIfNeeded() {
        guard !self.verifiedRefreshInFlight,
              PluginCatalogStore.shared.verifiedRefreshNeeded() else {
            return
        }
        self.verifiedRefreshInFlight = true
        let accountId = PluginManager.shared.environment.currentAccountId()
        PluginCatalog.loadVerifiedChannels(accountId: accountId) { [weak self] result in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.verifiedRefreshInFlight = false
                if case let .success(channels) = result {
                    PluginCatalogStore.shared.replaceVerified(channels)
                    PluginCatalogStore.shared.markVerifiedRefreshed()
                }
                self.repositories = PluginCatalogStore.shared.repositories
                self.rebuildSections()
                self.tableView.reloadData()
            }
        }
    }

    @objc private func addTapped() {
        let sheet = UIAlertController(
            title: "Add repository",
            message: "Add a Git repository that publishes an extera-plugins.json index.",
            preferredStyle: .actionSheet
        )
        sheet.addAction(UIAlertAction(title: "Git repository", style: .default) { [weak self] _ in
            self?.promptForRepository()
        })
        sheet.addAction(UIAlertAction(title: "Choose channel", style: .default) { [weak self] _ in
            self?.promptForChannelPicker()
        })
        sheet.addAction(UIAlertAction(title: "Telegram channel", style: .default) { [weak self] _ in
            self?.promptForChannel()
        })
        sheet.addAction(UIAlertAction(title: "Telegram folder", style: .default) { [weak self] _ in
            self?.promptForFolder()
        })
        sheet.addAction(UIAlertAction(title: "Paste from clipboard", style: .default) { [weak self] _ in
            guard let text = UIPasteboard.general.string, !text.isEmpty else {
                return
            }
            self?.addRepository(text)
        })
        sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        if let popover = sheet.popoverPresentationController {
            popover.sourceView = self.view
            popover.sourceRect = self.view.bounds
        }
        self.present(sheet, animated: true)
    }

    private func promptForRepository() {
        let alert = UIAlertController(
            title: "Add Git repository",
            message: "Paste a GitHub repository link or an https://…/extera-plugins.json address.",
            preferredStyle: .alert
        )
        alert.addTextField { field in
            field.placeholder = "https://github.com/owner/repository"
            field.autocapitalizationType = .none
            field.autocorrectionType = .no
            field.keyboardType = .URL
            field.clearButtonMode = .whileEditing
        }
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Add", style: .default) { [weak self, weak alert] _ in
            guard let self, let text = alert?.textFields?.first?.text else {
                return
            }
            self.addRepository(text)
        })
        self.present(alert, animated: true)
    }

    private func promptForChannel() {
        let alert = UIAlertController(
            title: "Add Telegram channel",
            message: "Enter an @username or a t.me link to a channel that publishes plugin documents.",
            preferredStyle: .alert
        )
        alert.addTextField { field in
            field.placeholder = "@plugin_channel"
            field.autocapitalizationType = .none
            field.autocorrectionType = .no
            field.clearButtonMode = .whileEditing
        }
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Add", style: .default) { [weak self, weak alert] _ in
            guard let self, let text = alert?.textFields?.first?.text else {
                return
            }
            self.addChannel(text)
        })
        self.present(alert, animated: true)
    }

    private func promptForChannelPicker() {
        self.activity.startAnimating()
        PluginCatalog.loadDialogChannels(
            accountId: PluginManager.shared.environment.currentAccountId()
        ) { [weak self] result in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.activity.stopAnimating()
                switch result {
                case let .failure(error):
                    self.showError(error)
                case let .success(channels):
                    guard !channels.isEmpty else {
                        let empty = UIAlertController(
                            title: "No channels",
                            message: "The dialog list contains no channels.",
                            preferredStyle: .alert
                        )
                        empty.addAction(UIAlertAction(title: "OK", style: .default))
                        self.present(empty, animated: true)
                        return
                    }
                    let sheet = UIAlertController(
                        title: "Choose channel",
                        message: nil,
                        preferredStyle: .actionSheet
                    )
                    for channel in channels {
                        sheet.addAction(UIAlertAction(title: channel.title, style: .default) { [weak self] _ in
                            _ = PluginCatalogStore.shared.addChannel(
                                peerId: channel.peerId,
                                username: channel.username,
                                name: channel.title
                            )
                            self?.reload()
                        })
                    }
                    sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel))
                    if let popover = sheet.popoverPresentationController {
                        popover.sourceView = self.view
                        popover.sourceRect = self.view.bounds
                    }
                    self.present(sheet, animated: true)
                }
            }
        }
    }

    private func addChannel(_ text: String) {
        self.activity.startAnimating()
        PluginCatalog.resolveChannel(
            accountId: PluginManager.shared.environment.currentAccountId(),
            username: text
        ) { [weak self] result in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.activity.stopAnimating()
                switch result {
                case let .success(value):
                    _ = PluginCatalogStore.shared.addChannel(
                        peerId: value.peerId,
                        username: value.username,
                        name: value.title
                    )
                    self.reload()
                case let .failure(error):
                    self.showError(error)
                }
            }
        }
    }

    private func promptForFolder() {
        self.activity.startAnimating()
        PluginCatalog.loadDialogFilters(
            accountId: PluginManager.shared.environment.currentAccountId()
        ) { [weak self] result in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.activity.stopAnimating()
                switch result {
                case let .failure(error):
                    self.showError(error)
                case let .success(filters):
                    let sheet = UIAlertController(
                        title: "Add Telegram folder",
                        message: "Choose a folder; its channels are used as one catalog.",
                        preferredStyle: .actionSheet
                    )
                    var added = 0
                    for filter in filters {
                        guard let name = PluginCatalog.folderTitle(from: filter), !name.isEmpty else {
                            continue
                        }
                        let peers = PluginCatalog.folderPeerIds(from: filter)
                        guard !peers.isEmpty else {
                            continue
                        }
                        added += 1
                        sheet.addAction(UIAlertAction(title: name, style: .default) { [weak self] _ in
                            _ = PluginCatalogStore.shared.addFolder(name: name, peerIds: peers)
                            self?.reload()
                        })
                    }
                    guard added > 0 else {
                        let empty = UIAlertController(
                            title: "No folders",
                            message: "No folder contains a channel with plugins.",
                            preferredStyle: .alert
                        )
                        empty.addAction(UIAlertAction(title: "OK", style: .default))
                        self.present(empty, animated: true)
                        return
                    }
                    sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel))
                    if let popover = sheet.popoverPresentationController {
                        popover.sourceView = self.view
                        popover.sourceRect = self.view.bounds
                    }
                    self.present(sheet, animated: true)
                }
            }
        }
    }

    private func addRepository(_ text: String) {
        guard let normalized = PluginCatalog.normalizeURL(text) else {
            self.showError(PluginCatalogError.invalidURL)
            return
        }
        self.activity.startAnimating()
        PluginCatalog.loadIndex(repositoryURL: normalized, etag: nil) { [weak self] result in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.activity.stopAnimating()
                switch result {
                case let .success(.loaded(index, _, etag)):
                    if let repository = PluginCatalogStore.shared.add(
                        url: normalized,
                        name: index.name,
                        homepage: index.homepage
                    ) {
                        PluginCatalogStore.shared.recordSync(
                            id: repository.id,
                            index: index,
                            etag: etag
                        )
                    }
                    self.reload()
                case .success(.notModified):
                    self.reload()
                case let .failure(error):
                    self.showError(error)
                }
            }
        }
    }

    private func showError(_ error: Error) {
        let alert = UIAlertController(
            title: "Catalog error",
            message: error.localizedDescription,
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "OK", style: .default))
        self.present(alert, animated: true)
    }

    public override func numberOfSections(in tableView: UITableView) -> Int {
        return max(1, self.sections.count)
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        guard section < self.sections.count else {
            return 1
        }
        return max(1, self.sections[section].repositories.count)
    }

    public override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        guard section < self.sections.count else {
            return "Repositories"
        }
        return self.sections[section].title
    }

    public override func tableView(_ tableView: UITableView, titleForFooterInSection section: Int) -> String? {
        return "A repository publishes an extera-plugins.json index. Plugins are verified by size and SHA-256 before the install sheet opens."
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: "cell", for: indexPath)
        cell.accessoryView = nil
        cell.accessoryType = .disclosureIndicator
        cell.textLabel?.textColor = .label
        let repositories = indexPath.section < self.sections.count
            ? self.sections[indexPath.section].repositories
            : []
        if repositories.isEmpty {
            cell.textLabel?.text = "No repositories"
            cell.detailTextLabel?.text = nil
            cell.accessoryType = .none
        } else {
            let repository = repositories[indexPath.row]
            cell.textLabel?.text = repository.name
            if let syncedAt = repository.syncedAt, syncedAt > 0 {
                let count = repository.pluginsCount ?? 0
                cell.detailTextLabel?.text = count == 1 ? "1 plugin" : "\(count) plugins"
            } else if repository.isFolder {
                let count = repository.peerIds?.count ?? 0
                cell.detailTextLabel?.text = "Telegram folder · \(count) channel\(count == 1 ? "" : "s")"
            } else if repository.isChannel || repository.isVerified {
                cell.detailTextLabel?.text = repository.username.map { "@\($0)" } ?? repository.url
            } else {
                cell.detailTextLabel?.text = repository.url
            }
        }
        cell.selectionStyle = .default
        return cell
    }

    public override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        let repositories = indexPath.section < self.sections.count
            ? self.sections[indexPath.section].repositories
            : []
        guard !repositories.isEmpty else {
            self.addTapped()
            return
        }
        let repository = repositories[indexPath.row]
        self.navigationController?.pushViewController(
            PluginCatalogRepositoryViewController(repository: repository),
            animated: true
        )
    }

    public override func tableView(_ tableView: UITableView, trailingSwipeActionsConfigurationForRowAt indexPath: IndexPath) -> UISwipeActionsConfiguration? {
        let repositories = indexPath.section < self.sections.count
            ? self.sections[indexPath.section].repositories
            : []
        guard !repositories.isEmpty else {
            return nil
        }
        let repository = repositories[indexPath.row]
        let delete = UIContextualAction(style: .destructive, title: "Remove") { [weak self] _, _, completion in
            let alert = UIAlertController(
                title: "Remove \(repository.name)?",
                message: "The repository is removed from this device. Installed plugins are not affected.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completion(false) })
            alert.addAction(UIAlertAction(title: "Remove", style: .destructive) { _ in
                PluginCatalogStore.shared.remove(id: repository.id)
                self?.reload()
                completion(true)
            })
            self?.present(alert, animated: true)
        }
        let link = PluginCatalog.repositoryLink(for: repository)
        let copy = UIContextualAction(style: .normal, title: "Copy link") { _, _, completion in
            UIPasteboard.general.string = link ?? (repository.url.isEmpty ? repository.name : repository.url)
            completion(true)
        }
        copy.backgroundColor = .systemBlue
        let share = UIContextualAction(style: .normal, title: "Share") { [weak self] _, _, completion in
            let text = link ?? (repository.url.isEmpty ? repository.name : repository.url)
            let activity = UIActivityViewController(activityItems: [text], applicationActivities: nil)
            if let self {
                activity.popoverPresentationController?.sourceView = self.view
                activity.popoverPresentationController?.sourceRect = self.view.bounds
                self.present(activity, animated: true)
            }
            completion(true)
        }
        share.backgroundColor = .systemGreen
        return UISwipeActionsConfiguration(actions: [delete, copy, share])
    }
}

/// One repository: its published plugins, with the install flow.
public final class PluginCatalogRepositoryViewController: UITableViewController {
    private let repository: PluginCatalogRepository
    private enum CatalogState: Hashable {
        case update
        case installed
        case available
    }

    private var index: PluginCatalogIndex?
    private var visiblePlugins: [PluginCatalogPlugin] = []
    private var groupedPlugins: [(title: String, plugins: [PluginCatalogPlugin])] = []
    private var error: Error?
    private let activity = UIActivityIndicatorView(style: .medium)
    private let searchController = UISearchController(searchResultsController: nil)
    private var installing = false
    private var selectedCategory: String?
    private var sortByName = false

    private func state(for plugin: PluginCatalogPlugin) -> CatalogState {
        guard let installed = PluginManager.shared.plugin(id: plugin.id) else {
            return .available
        }
        if Self.isNewer(plugin.version, than: installed.manifest.version) {
            return .update
        }
        return .installed
    }

    private static func versionComponents(_ value: String) -> [Int] {
        return value.split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
    }

    /// Compares versions the way Android's catalog does: each numeric run is
    /// compared in order, so `2.10` is newer than `2.9`.
    private static func isNewer(_ candidate: String, than installed: String) -> Bool {
        let left = self.versionComponents(candidate)
        let right = self.versionComponents(installed)
        if left.isEmpty || right.isEmpty {
            return candidate.compare(installed, options: .numeric) == .orderedDescending
        }
        for index in 0 ..< max(left.count, right.count) {
            let lhs = index < left.count ? left[index] : 0
            let rhs = index < right.count ? right[index] : 0
            if lhs != rhs {
                return lhs > rhs
            }
        }
        return false
    }

    public init(repository: PluginCatalogRepository) {
        self.repository = repository
        super.init(style: .insetGrouped)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        self.title = self.repository.name
        self.tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        self.searchController.searchResultsUpdater = self
        self.searchController.obscuresBackgroundDuringPresentation = false
        self.searchController.searchBar.placeholder = "Search"
        self.navigationItem.searchController = self.searchController
        self.navigationItem.hidesSearchBarWhenScrolling = false
        self.definesPresentationContext = true
        self.activity.hidesWhenStopped = true
        self.tableView.tableFooterView = self.activity
        self.navigationItem.rightBarButtonItem = UIBarButtonItem(
            title: "Web", style: .plain, target: self, action: #selector(self.openWeb)
        )
        self.navigationItem.rightBarButtonItem?.isEnabled = !self.repository.isFolder
        self.navigationItem.leftBarButtonItem = UIBarButtonItem(
            title: "Filter", style: .plain, target: self, action: #selector(self.showFilter)
        )
        let refresh = UIRefreshControl()
        refresh.addTarget(self, action: #selector(self.refreshPulled(_:)), for: .valueChanged)
        self.refreshControl = refresh
        self.load()
    }

    @objc private func refreshPulled(_ sender: UIRefreshControl) {
        sender.endRefreshing()
        self.load()
    }

    private func load() {
        let repository = self.repository
        if self.index == nil {
            self.index = PluginCatalogStore.shared.cachedIndex(id: repository.id)
            if let index = self.index {
                self.title = index.name
                self.error = nil
                self.filterPlugins()
                self.tableView.reloadData()
            }
        }
        self.activity.startAnimating()
        let completion: (Result<PluginCatalogIndex, PluginCatalogError>) -> Void = { [weak self] result in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.activity.stopAnimating()
                switch result {
                case let .success(index):
                    self.index = index
                    self.error = nil
                    self.title = index.name
                case let .failure(error):
                    if self.index == nil {
                        self.visiblePlugins = []
                        self.error = error
                    }
                }
                self.filterPlugins()
                self.tableView.reloadData()
            }
        }
        let accountId = PluginManager.shared.environment.currentAccountId()
        if repository.isFolder {
            PluginCatalog.loadFolderIndex(
                accountId: accountId,
                peerIds: repository.peerIds ?? [],
                fallbackName: repository.name
            ) { result in
                switch result {
                case let .success((index, _)):
                    PluginCatalogStore.shared.recordSync(id: repository.id, index: index, etag: nil)
                    completion(.success(index))
                case let .failure(error):
                    completion(.failure(error))
                }
            }
        } else if (repository.isChannel || repository.isVerified), let peerId = repository.peerId {
            PluginCatalog.loadChannelIndex(
                accountId: accountId,
                peerId: peerId,
                fallbackName: repository.name
            ) { result in
                switch result {
                case let .success((index, _)):
                    PluginCatalogStore.shared.recordSync(id: repository.id, index: index, etag: nil)
                    completion(.success(index))
                case let .failure(error):
                    completion(.failure(error))
                }
            }
        } else {
            let storedEtag = PluginCatalogStore.shared.repositories
                .first(where: { $0.id == repository.id })?.etag
            PluginCatalog.loadIndex(repositoryURL: repository.url, etag: storedEtag) { result in
                switch result {
                case let .success(.loaded(index, _, etag)):
                    PluginCatalogStore.shared.recordSync(id: repository.id, index: index, etag: etag)
                    completion(.success(index))
                case .success(.notModified):
                    if let index = PluginCatalogStore.shared.cachedIndex(id: repository.id) ?? self.index {
                        completion(.success(index))
                    } else {
                        completion(.failure(.network("The repository answered 304 Not Modified without a cached index.")))
                    }
                case let .failure(error):
                    completion(.failure(error))
                }
            }
        }
    }

    private var categories: [String] {
        guard let index else {
            return []
        }
        var seen = Set<String>()
        var values: [String] = []
        for plugin in index.plugins {
            guard let raw = plugin.categories else {
                continue
            }
            for part in raw.split(separator: ",") {
                let value = part.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !value.isEmpty, seen.insert(value.lowercased()).inserted else {
                    continue
                }
                values.append(value)
            }
        }
        return values.sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
    }

    private func filterPlugins() {
        guard let index else {
            self.visiblePlugins = []
            return
        }
        let query = self.searchController.searchBar.text?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        var filtered = index.plugins
        if !query.isEmpty {
            filtered = filtered.filter { plugin in
                plugin.name.localizedCaseInsensitiveContains(query)
                    || (plugin.description?.localizedCaseInsensitiveContains(query) ?? false)
                    || (plugin.author?.localizedCaseInsensitiveContains(query) ?? false)
                    || (plugin.categories?.localizedCaseInsensitiveContains(query) ?? false)
            }
        }
        if let category = self.selectedCategory {
            filtered = filtered.filter { plugin in
                guard let raw = plugin.categories else {
                    return false
                }
                return raw.split(separator: ",").contains {
                    $0.trimmingCharacters(in: .whitespacesAndNewlines)
                        .caseInsensitiveCompare(category) == .orderedSame
                }
            }
        }
        // Updates and installed plugins first, as in Android's catalog sections.
        let ranks: [CatalogState: Int] = [.update: 0, .installed: 1, .available: 2]
        self.visiblePlugins = filtered.sorted { lhs, rhs in
            let leftRank = ranks[self.state(for: lhs)] ?? 2
            let rightRank = ranks[self.state(for: rhs)] ?? 2
            if leftRank != rightRank {
                return leftRank < rightRank
            }
            if self.sortByName {
                return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
            }
            let leftDate = lhs.updatedAt ?? 0
            let rightDate = rhs.updatedAt ?? 0
            if leftDate != rightDate {
                return leftDate > rightDate
            }
            return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
        }
        self.buildGroups()
    }

    private func buildGroups() {
        guard self.index != nil else {
            self.groupedPlugins = []
            return
        }
        let query = self.searchController.searchBar.text?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !query.isEmpty {
            self.groupedPlugins = self.visiblePlugins.isEmpty
                ? []
                : [("Results", self.visiblePlugins)]
            return
        }
        let updates = self.visiblePlugins.filter { self.state(for: $0) == .update }
        let installed = self.visiblePlugins.filter { self.state(for: $0) == .installed }
        let others = self.visiblePlugins.filter { self.state(for: $0) == .available }
        var groups: [(title: String, plugins: [PluginCatalogPlugin])] = []
        if !updates.isEmpty {
            groups.append(("Updates", updates))
        }
        if !installed.isEmpty {
            groups.append(("Installed", installed))
        }
        if !others.isEmpty {
            groups.append((self.selectedCategory ?? "All plugins", others))
        }
        self.groupedPlugins = groups
    }

    @objc private func showFilter() {
        let alert = UIAlertController(title: "Filter and sort", message: nil, preferredStyle: .actionSheet)
        let allCategories = self.selectedCategory == nil ? "✓ All categories" : "All categories"
        alert.addAction(UIAlertAction(title: allCategories, style: .default) { [weak self] _ in
            self?.selectedCategory = nil
            self?.applyFilter()
        })
        for category in self.categories {
            let selected = self.selectedCategory?.caseInsensitiveCompare(category) == .orderedSame
            let title = selected ? "✓ \(category)" : category
            alert.addAction(UIAlertAction(title: title, style: .default) { [weak self] _ in
                self?.selectedCategory = category
                self?.applyFilter()
            })
        }
        let lastUpdated = self.sortByName ? "Sort by last updated" : "✓ Sort by last updated"
        alert.addAction(UIAlertAction(title: lastUpdated, style: .default) { [weak self] _ in
            self?.sortByName = false
            self?.applyFilter()
        })
        let byName = self.sortByName ? "✓ Sort by name" : "Sort by name"
        alert.addAction(UIAlertAction(title: byName, style: .default) { [weak self] _ in
            self?.sortByName = true
            self?.applyFilter()
        })
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        if let popover = alert.popoverPresentationController {
            popover.sourceView = self.view
            popover.sourceRect = self.view.bounds
        }
        self.present(alert, animated: true)
    }

    private func applyFilter() {
        self.filterPlugins()
        self.tableView.reloadData()
    }

    @objc private func openWeb() {
        if self.repository.isFolder {
            return
        }
        if self.repository.isChannel {
            if let username = self.repository.username, !username.isEmpty,
               let url = URL(string: "https://t.me/\(username)") {
                UIApplication.shared.open(url)
            }
            return
        }
        let value = PluginCatalog.webURL(for: self.repository, index: self.index)
        guard let value, let url = URL(string: value) else {
            return
        }
        UIApplication.shared.open(url)
    }

    public override func numberOfSections(in tableView: UITableView) -> Int {
        return max(1, self.groupedPlugins.count)
    }

    public override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        guard !self.groupedPlugins.isEmpty, section < self.groupedPlugins.count else {
            return 1
        }
        return self.groupedPlugins[section].plugins.count
    }

    public override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        guard !self.groupedPlugins.isEmpty, section < self.groupedPlugins.count else {
            return nil
        }
        return self.groupedPlugins[section].title
    }

    public override func tableView(_ tableView: UITableView, titleForFooterInSection section: Int) -> String? {
        if let error {
            return (error as? PluginCatalogError)?.description ?? "\(error)"
        }
        return "Plugins are downloaded from the repository and installed through the same analysis sheet as a local file."
    }

    public override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: "cell", for: indexPath)
        cell.accessoryView = nil
        if !self.groupedPlugins.isEmpty, indexPath.section < self.groupedPlugins.count,
           indexPath.row < self.groupedPlugins[indexPath.section].plugins.count {
            let plugin = self.groupedPlugins[indexPath.section].plugins[indexPath.row]
            cell.textLabel?.text = "\(plugin.name) \(plugin.version)"
            var details: [String] = []
            switch self.state(for: plugin) {
            case .update:
                if let installed = PluginManager.shared.plugin(id: plugin.id) {
                    details.append("Update \(installed.manifest.version) → \(plugin.version)")
                } else {
                    details.append("Update")
                }
            case .installed:
                details.append("Installed")
            case .available:
                if let updatedAt = plugin.updatedAt {
                    let age = Date().timeIntervalSince1970 - Double(updatedAt)
                    if age >= 0, age < 7 * 24 * 60 * 60 {
                        details.append("New")
                    }
                }
            }
            if let author = plugin.author, !author.isEmpty {
                details.append(author)
            }
            if let description = plugin.description, !description.isEmpty {
                details.append(description)
            }
            if let categories = plugin.categories, !categories.isEmpty {
                details.append(categories)
            }
            cell.detailTextLabel?.text = details.joined(separator: " · ")
            cell.accessoryType = .disclosureIndicator
            cell.selectionStyle = .default
        } else {
            let query = self.searchController.searchBar.text?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            cell.textLabel?.text = self.error != nil
                ? "Could not load the index"
                : (query.isEmpty ? "No plugins" : "No results")
            cell.detailTextLabel?.text = nil
            cell.accessoryType = .none
            cell.selectionStyle = .none
        }
        return cell
    }

    public override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        guard !self.groupedPlugins.isEmpty,
              indexPath.section < self.groupedPlugins.count,
              indexPath.row < self.groupedPlugins[indexPath.section].plugins.count else {
            return
        }
        self.showPlugin(self.groupedPlugins[indexPath.section].plugins[indexPath.row])
    }

    private func showPlugin(_ plugin: PluginCatalogPlugin) {
        let state = self.state(for: plugin)
        var message = plugin.description ?? ""
        if let author = plugin.author, !author.isEmpty {
            message = message.isEmpty ? "by \(author)" : "\(message)\n\nby \(author)"
        }
        if let installed = PluginManager.shared.plugin(id: plugin.id) {
            switch state {
            case .update:
                message = "\(message)\n\nInstalled: \(installed.manifest.version)\nAvailable: \(plugin.version)"
            case .installed:
                message = "\(message)\n\nInstalled version: \(installed.manifest.version)"
            case .available:
                break
            }
        }
        if let updates = plugin.updatedAt {
            let date = Date(timeIntervalSince1970: TimeInterval(updates))
            let formatter = DateFormatter()
            formatter.dateStyle = .medium
            formatter.timeStyle = .none
            let text = formatter.string(from: date)
            message = message.isEmpty ? "Updated \(text)" : "\(message)\n\nUpdated \(text)"
        }
        if let requirements = plugin.requirements, !requirements.isEmpty {
            message = "\(message)\n\nRequires: \(requirements)"
        }
        let alert = UIAlertController(title: plugin.name, message: message, preferredStyle: .actionSheet)
        let installTitle: String
        switch state {
        case .update:
            installTitle = "Update"
        case .installed:
            installTitle = "Reinstall"
        case .available:
            installTitle = "Install"
        }
        alert.addAction(UIAlertAction(title: installTitle, style: .default) { [weak self] _ in
            self?.install(plugin)
        })
        if state != .available {
            alert.addAction(UIAlertAction(title: "Delete plugin", style: .destructive) { [weak self] _ in
                self?.confirmDelete(plugin)
            })
        }
        if plugin.documentId == nil, let url = URL(string: plugin.fileURL) {
            alert.addAction(UIAlertAction(title: "Open file URL", style: .default) { _ in
                UIApplication.shared.open(url)
            })
        }
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        if let popover = alert.popoverPresentationController {
            popover.sourceView = self.view
            popover.sourceRect = self.view.bounds
        }
        self.present(alert, animated: true)
    }

    private func confirmDelete(_ plugin: PluginCatalogPlugin) {
        let alert = UIAlertController(
            title: "Delete \(plugin.name)?",
            message: "The plugin and its settings will be removed.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
        alert.addAction(UIAlertAction(title: "Delete", style: .destructive) { [weak self] _ in
            PluginManager.shared.delete(pluginId: plugin.id) { [weak self] _ in
                DispatchQueue.main.async {
                    self?.filterPlugins()
                    self?.tableView.reloadData()
                }
            }
        })
        self.present(alert, animated: true)
    }

    private func install(_ plugin: PluginCatalogPlugin) {
        guard !self.installing else {
            return
        }
        self.installing = true
        self.activity.startAnimating()
        let completion: (Result<URL, PluginCatalogError>) -> Void = { [weak self] result in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }
                self.activity.stopAnimating()
                self.installing = false
                switch result {
                case let .success(url):
                    self.showInstallSheet(plugin: plugin, fileURL: url)
                case let .failure(error):
                    let alert = UIAlertController(
                        title: "Download failed",
                        message: error.description,
                        preferredStyle: .alert
                    )
                    alert.addAction(UIAlertAction(title: "OK", style: .default))
                    self.present(alert, animated: true)
                }
            }
        }
        if plugin.documentId != nil {
            PluginCatalog.downloadChannelPlugin(
                accountId: PluginManager.shared.environment.currentAccountId(),
                plugin: plugin,
                completion: completion
            )
        } else {
            PluginCatalog.download(plugin, completion: completion)
        }
    }

    private func showInstallSheet(plugin: PluginCatalogPlugin, fileURL: URL) {
        let extensionName = fileURL.pathExtension.lowercased()
        if extensionName == "elyx" || extensionName == "eaf" {
            PluginManager.shared.inspectElyx(url: fileURL) { [weak self] inspection in
                let controller = PluginElyxInstallViewController(url: fileURL, inspection: inspection) {
                    self?.navigationController?.popToRootViewController(animated: true)
                }
                self?.navigationController?.pushViewController(controller, animated: true)
            }
            return
        }
        let report = PluginAnalyzer.shared.analyzeSynchronously(
            PluginAnalysisRequest(fileURL: fileURL, name: fileURL.lastPathComponent)
        )
        let requirements = (plugin.requirements ?? "")
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        let parsed = try? PluginManifestParser.parse(fileAt: fileURL)
        let title = parsed?.name ?? plugin.name
        let version = parsed?.version ?? plugin.version
        let author = parsed?.author ?? plugin.author ?? "unknown"
        let controller = PluginAnalysisViewController(
            title: title,
            subtitle: "\(version) by \(author)",
            report: report,
            installTitle: self.state(for: plugin) == .update ? "Update" : (self.state(for: plugin) == .installed ? "Reinstall" : "Install"),
            onInstall: nil,
            requirements: requirements.isEmpty ? (parsed?.requirements ?? []) : requirements,
            trustedSource: true,
            onInstallWithEnable: { [weak self] enabled in
                PluginManager.shared.install(url: fileURL, enabled: enabled) { result in
                    DispatchQueue.main.async {
                        if let error = result.error {
                            let alert = UIAlertController(title: "Install failed", message: error, preferredStyle: .alert)
                            alert.addAction(UIAlertAction(title: "OK", style: .default))
                            self?.present(alert, animated: true)
                        } else {
                            self?.navigationController?.popToRootViewController(animated: true)
                        }
                    }
                }
            }
        )
        self.navigationController?.pushViewController(controller, animated: true)
    }
}

extension PluginCatalogRepositoryViewController: UISearchResultsUpdating {
    public func updateSearchResults(for searchController: UISearchController) {
        self.filterPlugins()
        self.tableView.reloadData()
    }
}
