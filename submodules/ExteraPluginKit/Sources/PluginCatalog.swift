import Foundation

/// A Git-hosted plugin repository, the iOS counterpart of Android's
/// `GitPluginRepository`.
///
/// A repository is identified by one URL. A GitHub repository is resolved to
/// `raw.githubusercontent.com` (and `cdn.jsdelivr.net` when a ref is pinned), so
/// the user can paste a normal GitHub link; any other HTTPS URL must point
/// directly at an `extera-plugins.json` index.
public struct PluginCatalogRepository: Codable, Equatable {
    public var id: String
    public var url: String
    public var name: String
    public var homepage: String?
    public var addedAt: Double?
    public var kind: String?
    public var peerId: Int64?
    public var username: String?
    public var peerIds: [Int64]?
    /// HTTP ETag of the last successfully downloaded Git index. It is sent as
    /// `If-None-Match`, so an unchanged repository costs one 304 response,
    /// matching Android's `GitPluginRepository.loadIndex`.
    public var etag: String?
    /// Unix time of the last successful sync, shown as the catalog subtitle.
    public var syncedAt: Double?
    /// Number of plugins in the last synced index.
    public var pluginsCount: Int?

    public var isChannel: Bool {
        return self.kind == "channel"
    }

    public var isFolder: Bool {
        return self.kind == "folder"
    }

    /// A channel from Android's trusted folder (`pPhOtEq00KhjYTc6`). It is
    /// refreshed from `chatlists.checkChatlistInvite`, not added by hand.
    public var isVerified: Bool {
        return self.kind == "verified"
    }

    public init(id: String, url: String, name: String, homepage: String? = nil, addedAt: Double? = nil, kind: String? = nil, peerId: Int64? = nil, username: String? = nil, peerIds: [Int64]? = nil, etag: String? = nil, syncedAt: Double? = nil, pluginsCount: Int? = nil) {
        self.id = id
        self.url = url
        self.name = name
        self.homepage = homepage
        self.addedAt = addedAt
        self.kind = kind
        self.peerId = peerId
        self.username = username
        self.peerIds = peerIds
        self.etag = etag
        self.syncedAt = syncedAt
        self.pluginsCount = pluginsCount
    }
}

/// Result of loading a Git repository index. A repository that answers
/// `304 Not Modified` keeps the catalog already on screen instead of
/// downloading and parsing it again.
public enum PluginCatalogLoadResult {
    case loaded(PluginCatalogIndex, String, String?)
    case notModified
}

public struct PluginCatalogPlugin: Codable {
    public var id: String
    public var name: String
    public var version: String
    public var fileURL: String
    public var fileName: String
    public var sha256: String
    public var size: Int64
    public var description: String?
    public var author: String?
    public var icon: String?
    public var appVersion: String?
    public var sdkVersion: String?
    public var requirements: String?
    public var categories: String?
    public var updatedAt: Int?
    /// Telegram-document fields for a channel catalog entry. Git entries leave
    /// them nil and carry a real `fileURL` and `sha256` instead.
    public var documentId: Int64? = nil
    public var documentAccessHash: Int64? = nil
    public var documentFileReference: String? = nil
    public var channelPeerId: Int64? = nil
    public var messageDate: Int? = nil
}

public struct PluginCatalogIndex: Codable {
    public var name: String
    public var homepage: String?
    public var plugins: [PluginCatalogPlugin]
}

public enum PluginCatalogError: Error, CustomStringConvertible {
    case invalidURL
    case unsupportedSchema(Int)
    case invalidIndex(String)
    case tooLarge
    case network(String)
    case download(String)
    case verification

    public var description: String {
        switch self {
        case .invalidURL:
            return "This is not a repository URL. Use a GitHub link or an https://…/extera-plugins.json address."
        case let .unsupportedSchema(version):
            return "The repository index uses schema \(version); this build supports schema 1."
        case let .invalidIndex(reason):
            return "The repository index is invalid: \(reason)"
        case .tooLarge:
            return "The repository index is larger than 1 MB."
        case let .network(message):
            return message
        case let .download(message):
            return message
        case .verification:
            return "The downloaded plugin does not match the size and SHA-256 published by the repository."
        }
    }
}

public enum PluginCatalog {
    public static let indexFileName = "extera-plugins.json"
    public static let schemaVersion = 1
    public static let maximumIndexSize = 1024 * 1024
    public static let maximumCategories = 3
    private static let maximumPluginSize: Int64 = 64 * 1024 * 1024

    // -- URLs ----------------------------------------------------------------

    public static func normalizeURL(_ input: String) -> String? {
        var value = input.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") {
            value.removeLast()
        }
        guard !value.isEmpty, !value.contains(where: { $0.isWhitespace }) else {
            return nil
        }

        var bare = value
        if bare.lowercased().hasPrefix("https://") {
            bare.removeFirst("https://".count)
        } else if bare.lowercased().hasPrefix("http://") {
            bare.removeFirst("http://".count)
        }
        if bare.lowercased().hasPrefix("www.") {
            bare.removeFirst("www.".count)
        }

        // github.com/owner/repo/blob/ref/path/extera-plugins.json is a file
        // view; the repository form is the tree at that directory.
        if let blob = bare.range(of: "/blob/", options: .caseInsensitive),
           bare.lowercased().hasSuffix("/" + indexFileName),
           bare.lowercased().hasPrefix("github.com/") {
            let prefix = String(bare[..<blob.lowerBound])
            let path = String(bare[blob.upperBound...])
            if path.count > indexFileName.count {
                let directory = String(path.dropLast(indexFileName.count + 1))
                bare = prefix + "/tree/" + directory
            }
        }

        if bare.lowercased().hasPrefix("github.com/") {
            let parts = bare.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
            guard parts.count >= 3, isGitHubComponent(parts[1]) else {
                return nil
            }
            var repository = parts[2]
            if repository.lowercased().hasSuffix(".git") {
                repository.removeLast(4)
            }
            guard isGitHubComponent(repository) else {
                return nil
            }
            let owner = parts[1].lowercased()
            let repo = repository.lowercased()
            if parts.count == 3 {
                return "https://github.com/\(owner)/\(repo)"
            }
            guard parts.count >= 5, parts[3].lowercased() == "tree", !parts[4].isEmpty else {
                return nil
            }
            let ref = parts[4]
            let directory = parts.count > 5 ? "/" + parts[5...].joined(separator: "/") : ""
            return "https://github.com/\(owner)/\(repo)/tree/\(ref)\(directory)"
        }

        if !value.lowercased().hasPrefix("https://") {
            value = "https://" + value
        }
        guard let url = URL(string: value),
              url.scheme?.lowercased() == "https",
              url.pathComponents.last?.lowercased() == indexFileName else {
            return nil
        }
        return url.absoluteString
    }

    private static func isGitHubComponent(_ value: String) -> Bool {
        guard !value.isEmpty else {
            return false
        }
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._")
        return value.unicodeScalars.allSatisfy { allowed.contains($0) }
    }

    public static func indexURLs(for repositoryURL: String) -> [String] {
        guard let url = URL(string: repositoryURL),
              url.host?.lowercased() == "github.com" else {
            return [repositoryURL]
        }
        let parts = url.pathComponents.filter { $0 != "/" }
        guard parts.count >= 2 else {
            return [repositoryURL]
        }
        let owner = parts[0]
        var repository = parts[1]
        if repository.lowercased().hasSuffix(".git") {
            repository.removeLast(4)
        }
        var ref = ""
        var directory = ""
        if parts.count >= 4, parts[2].lowercased() == "tree" {
            ref = parts[3]
            if parts.count > 4 {
                directory = parts[4...].joined(separator: "/")
            }
        }
        let path = directory.isEmpty ? indexFileName : directory + "/" + indexFileName
        let raw = "https://raw.githubusercontent.com/\(owner)/\(repository)/\(ref.isEmpty ? "HEAD" : ref)/\(path)"
        if ref.isEmpty {
            return [raw]
        }
        return [raw, "https://cdn.jsdelivr.net/gh/\(owner)/\(repository)@\(ref)/\(path)"]
    }

    public static func webURL(for repository: PluginCatalogRepository, index: PluginCatalogIndex?) -> String? {
        if let homepage = index?.homepage, !homepage.isEmpty {
            return homepage
        }
        return repository.url
    }

    // -- Repository links ----------------------------------------------------

    /// Android's `PluginRepositoryLinks`: a `t.me/exteraPluginRepo` link carries
    /// either a channel username (`?c=`) or a Git index URL (`?git=`), so a
    /// repository can be shared as a single tappable link.
    public static let repositoryLinkName = "exteraPluginRepo"
    public static let repositoryLinkUsernameKey = "c"
    public static let repositoryLinkGitKey = "git"

    private static func percentEncodedQueryValue(_ value: String) -> String {
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    public static func repositoryLink(for repository: PluginCatalogRepository) -> String? {
        if repository.isChannel {
            guard let username = repository.username, !username.isEmpty else {
                return nil
            }
            return "https://t.me/\(self.repositoryLinkName)?\(self.repositoryLinkUsernameKey)=\(self.percentEncodedQueryValue(username))"
        }
        if repository.isFolder || repository.url.isEmpty {
            return nil
        }
        return "https://t.me/\(self.repositoryLinkName)?\(self.repositoryLinkGitKey)=\(self.percentEncodedQueryValue(repository.url))"
    }

    public enum RepositoryLink {
        case git(String)
        case channel(String)
    }

    /// Parses `t.me/exteraPluginRepo?c=…` and `?git=…`, the links Android's
    /// `IntentsController` opens from a chat or an external browser.
    public static func parseRepositoryLink(_ url: URL) -> RepositoryLink? {
        let host = url.host?.lowercased() ?? ""
        guard host == "t.me" || host == "telegram.me" || host == "www.t.me" else {
            return nil
        }
        let parts = url.pathComponents.filter { $0 != "/" }
        guard let first = parts.first,
              first.caseInsensitiveCompare(self.repositoryLinkName) == .orderedSame else {
            return nil
        }
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        if let username = items.first(where: { $0.name == self.repositoryLinkUsernameKey })?.value,
           !username.isEmpty {
            return .channel(username)
        }
        if let git = items.first(where: { $0.name == self.repositoryLinkGitKey })?.value,
           !git.isEmpty {
            return .git(git)
        }
        return nil
    }

    // -- Index ---------------------------------------------------------------

    public static func parseIndex(data: Data, baseURL: URL) throws -> PluginCatalogIndex {
        guard data.count <= maximumIndexSize else {
            throw PluginCatalogError.tooLarge
        }
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw PluginCatalogError.invalidIndex("the document is not a JSON object")
        }
        let schema = (root["schema"] as? NSNumber)?.intValue ?? 0
        if schema > schemaVersion {
            throw PluginCatalogError.unsupportedSchema(schema)
        }
        guard schema >= 1 else {
            throw PluginCatalogError.invalidIndex("missing schema")
        }
        guard let name = stringValue(root["name"]), !name.isEmpty else {
            throw PluginCatalogError.invalidIndex("missing name")
        }
        guard let rawPlugins = root["plugins"] as? [[String: Any]] else {
            throw PluginCatalogError.invalidIndex("missing plugins")
        }
        var seen = Set<String>()
        var plugins: [PluginCatalogPlugin] = []
        for raw in rawPlugins {
            guard let plugin = parsePlugin(raw, baseURL: baseURL), seen.insert(plugin.id).inserted else {
                continue
            }
            plugins.append(plugin)
        }
        let homepage = stringValue(root["homepage"]).flatMap { value -> String? in
            guard let url = URL(string: value), url.scheme?.lowercased() == "https" else {
                return nil
            }
            return url.absoluteString
        }
        return PluginCatalogIndex(name: name, homepage: homepage, plugins: plugins)
    }

    private static func parsePlugin(_ json: [String: Any], baseURL: URL) -> PluginCatalogPlugin? {
        guard let id = stringValue(json["id"]), !id.isEmpty,
              let name = stringValue(json["name"]), !name.isEmpty,
              let version = stringValue(json["version"]), !version.isEmpty,
              let sha256 = stringValue(json["sha256"])?.lowercased(),
              isSHA256(sha256),
              let size = (json["size"] as? NSNumber)?.int64Value, size > 0, size <= maximumPluginSize,
              let file = stringValue(json["file"]),
              let resolved = URL(string: file, relativeTo: baseURL)?.absoluteURL,
              resolved.scheme?.lowercased() == "https",
              let fileName = resolved.pathComponents.last, isSafeFileName(fileName) else {
            return nil
        }
        let requirements = stringOrList(json["requirements"], limit: Int.max, separator: ", ")
        let categories = stringOrList(json["category"], limit: maximumCategories, separator: ",")
        let updatedAt = stringValue(json["updated_at"]).flatMap(parseTime)
        return PluginCatalogPlugin(
            id: id,
            name: name,
            version: version,
            fileURL: resolved.absoluteString,
            fileName: fileName,
            sha256: sha256,
            size: size,
            description: stringValue(json["description"]),
            author: stringValue(json["author"]),
            icon: stringValue(json["icon"]),
            appVersion: stringValue(json["app_version"]),
            sdkVersion: stringValue(json["sdk_version"]),
            requirements: requirements,
            categories: categories,
            updatedAt: updatedAt
        )
    }

    private static func stringValue(_ value: Any?) -> String? {
        guard let string = value as? String else {
            return nil
        }
        let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func stringOrList(_ value: Any?, limit: Int, separator: String) -> String? {
        var items: [String] = []
        if let string = value as? String {
            items = [string]
        } else if let array = value as? [Any] {
            items = array.compactMap { $0 as? String }
        }
        let values = items.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .prefix(limit)
        return values.isEmpty ? nil : values.joined(separator: separator)
    }

    private static func isSHA256(_ value: String) -> Bool {
        guard value.count == 64 else {
            return false
        }
        return value.unicodeScalars.allSatisfy { character in
            (character.value >= 48 && character.value <= 57) || (character.value >= 97 && character.value <= 102)
        }
    }

    public static func isSafeFileName(_ name: String) -> Bool {
        guard !name.isEmpty, name != ".", name != ".." else {
            return false
        }
        return !name.contains("/") && !name.contains("\\") && !name.contains("\u{0}")
    }

    private static func parseTime(_ value: String) -> Int? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) {
            return Int(date.timeIntervalSince1970)
        }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value).map { Int($0.timeIntervalSince1970) }
    }

    // -- Network -------------------------------------------------------------

    public static func loadIndex(repositoryURL: String, completion: @escaping (Result<(PluginCatalogIndex, String), PluginCatalogError>) -> Void) {
        loadIndex(repositoryURL: repositoryURL, etag: nil) { result in
            switch result {
            case let .success(.loaded(index, source, _)):
                completion(.success((index, source)))
            case .success(.notModified):
                completion(.failure(.network("The repository answered 304 Not Modified without a cached index.")))
            case let .failure(error):
                completion(.failure(error))
            }
        }
    }

    /// Loads an index and reports the response ETag. When `etag` is supplied it
    /// is sent as `If-None-Match`; an unchanged repository then answers `304`
    /// and the caller keeps the catalog already stored on the device.
    public static func loadIndex(repositoryURL: String, etag: String?, completion: @escaping (Result<PluginCatalogLoadResult, PluginCatalogError>) -> Void) {
        let urls = indexURLs(for: repositoryURL)
        loadIndex(urls: urls, index: 0, etag: etag, completion: completion)
    }

    private static func loadIndex(urls: [String], index: Int, etag: String?, completion: @escaping (Result<PluginCatalogLoadResult, PluginCatalogError>) -> Void) {
        guard index < urls.count, let url = URL(string: urls[index]) else {
            completion(.failure(.network("The repository index could not be downloaded.")))
            return
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 20
        request.setValue("ExteraPluginKit/1.0", forHTTPHeaderField: "User-Agent")
        if let etag, !etag.isEmpty {
            request.setValue(etag, forHTTPHeaderField: "If-None-Match")
        }
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error {
                if index + 1 < urls.count {
                    loadIndex(urls: urls, index: index + 1, etag: etag, completion: completion)
                } else {
                    completion(.failure(.network(error.localizedDescription)))
                }
                return
            }
            let http = response as? HTTPURLResponse
            if http?.statusCode == 304 {
                completion(.success(.notModified))
                return
            }
            guard let http, (200..<300).contains(http.statusCode), let data else {
                if index + 1 < urls.count {
                    loadIndex(urls: urls, index: index + 1, etag: etag, completion: completion)
                } else {
                    let status = http?.statusCode ?? 0
                    completion(.failure(.network("The repository index returned HTTP \(status).")))
                }
                return
            }
            do {
                let parsed = try parseIndex(data: data, baseURL: url)
                completion(.success(.loaded(parsed, url.absoluteString, http.value(forHTTPHeaderField: "ETag"))))
            } catch let catalogError as PluginCatalogError {
                completion(.failure(catalogError))
            } catch {
                completion(.failure(.invalidIndex("\(error)")))
            }
        }.resume()
    }

    /// Downloads a catalog plugin into the cache and verifies the published
    /// size and SHA-256 before returning it.
    public static func download(_ plugin: PluginCatalogPlugin, completion: @escaping (Result<URL, PluginCatalogError>) -> Void) {
        let manager = FileManager.default
        guard isSafeFileName(plugin.fileName), isSHA256(plugin.sha256) else {
            completion(.failure(.verification))
            return
        }
        let cacheRoot = manager.urls(for: .cachesDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        let directory = cacheRoot.appendingPathComponent("plugin_catalog", isDirectory: true)
            .appendingPathComponent(plugin.sha256, isDirectory: true)
        let destination = directory.appendingPathComponent(plugin.fileName)
        if let attributes = try? manager.attributesOfItem(atPath: destination.path),
           let size = (attributes[.size] as? NSNumber)?.int64Value,
           size == plugin.size,
           PluginHashing.sha256(fileAt: destination) == plugin.sha256 {
            completion(.success(destination))
            return
        }
        guard let url = URL(string: plugin.fileURL) else {
            completion(.failure(.invalidURL))
            return
        }
        try? manager.createDirectory(at: directory, withIntermediateDirectories: true)
        var request = URLRequest(url: url)
        request.timeoutInterval = 60
        request.setValue("ExteraPluginKit/1.0", forHTTPHeaderField: "User-Agent")
        URLSession.shared.downloadTask(with: request) { location, response, error in
            if let error {
                completion(.failure(.download(error.localizedDescription)))
                return
            }
            guard let location else {
                completion(.failure(.download("The download produced no file.")))
                return
            }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard (200..<300).contains(status) else {
                completion(.failure(.download("The plugin download returned HTTP \(status).")))
                return
            }
            let attributes = try? manager.attributesOfItem(atPath: location.path)
            let size = (attributes?[.size] as? NSNumber)?.int64Value ?? 0
            guard size == plugin.size, size <= maximumPluginSize else {
                try? manager.removeItem(at: location)
                completion(.failure(.verification))
                return
            }
            guard PluginHashing.sha256(fileAt: location) == plugin.sha256 else {
                try? manager.removeItem(at: location)
                completion(.failure(.verification))
                return
            }
            do {
                try? manager.removeItem(at: destination)
                try manager.moveItem(at: location, to: destination)
                completion(.success(destination))
            } catch {
                completion(.failure(.download(error.localizedDescription)))
            }
        }.resume()
    }

    // -- Telegram channels ---------------------------------------------------

    /// Resolves `@username` (or a `t.me` link) to an Android-style dialog id and
    /// adds the channel as a catalog repository.
    public static func resolveChannel(accountId: Int64, username: String, completion: @escaping (Result<(peerId: Int64, username: String?, title: String), PluginCatalogError>) -> Void) {
        var value = username.trimmingCharacters(in: .whitespacesAndNewlines)
        if let url = URL(string: value), let host = url.host?.lowercased(), host == "t.me" || host == "telegram.me" {
            value = url.pathComponents.filter { $0 != "/" }.first ?? ""
        }
        while value.hasPrefix("@") {
            value.removeFirst()
        }
        value = value.split(separator: "/").first.map(String.init) ?? value
        guard !value.isEmpty, value.count <= 64 else {
            completion(.failure(.invalidURL))
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let response = PluginManager.shared.environment.request(
                accountId, "contacts.resolveUsername", ["username": value]
            )
            if let error = response["error"] as? String {
                completion(.failure(.network(error)))
                return
            }
            let chats = response["chats"] as? [[String: Any]] ?? []
            guard let channel = chats.first(where: { ($0["_"] as? String) == "channel" }),
                  let channelId = (channel["id"] as? NSNumber)?.int64Value, channelId != 0 else {
                completion(.failure(.network("The username does not belong to a channel.")))
                return
            }
            let peerId = -1000000000000 - channelId
            let title = (channel["title"] as? String) ?? value
            let resolvedUsername = (channel["username"] as? String) ?? value
            completion(.success((peerId: peerId, username: resolvedUsername, title: title)))
        }
    }

    /// Reads a channel's history and turns every plugin document into a catalog
    /// entry. Telegram transport already verifies the bytes; the entry stores
    /// the document location instead of a URL and SHA-256.
    public static func loadChannelIndex(accountId: Int64, peerId: Int64, fallbackName: String, completion: @escaping (Result<(PluginCatalogIndex, String), PluginCatalogError>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            switch self.loadChannelMessages(accountId: accountId, peerId: peerId) {
            case let .failure(error):
                completion(.failure(error))
            case let .success((title, messages)):
                let plugins = self.channelPlugins(from: messages, peerId: peerId, accountId: accountId)
                let index = PluginCatalogIndex(
                    name: title ?? fallbackName,
                    homepage: nil,
                    plugins: plugins
                )
                completion(.success((index, "channel:\(peerId)")))
            }
        }
    }

    private static func loadChannelMessages(accountId: Int64, peerId: Int64) -> Result<(String?, [[String: Any]]), PluginCatalogError> {
        var messages: [[String: Any]] = []
        var seen = Set<Int64>()
        var offsetId: Int64 = 0
        var channelTitle: String?
        for _ in 0 ..< 10 {
            let response = PluginManager.shared.environment.request(accountId, "messages.getHistory", [
                "peer": peerId,
                "limit": 100,
                "offset_id": offsetId
            ])
            if let error = response["error"] as? String {
                return .failure(.network(error))
            }
            if channelTitle == nil {
                let chats = response["chats"] as? [[String: Any]] ?? []
                if let channel = chats.first(where: { ($0["_"] as? String) == "channel" }) {
                    channelTitle = channel["title"] as? String
                }
            }
            let batch = response["messages"] as? [[String: Any]] ?? []
            if batch.isEmpty {
                break
            }
            for message in batch {
                if let messageId = (message["id"] as? NSNumber)?.int64Value, seen.insert(messageId).inserted {
                    messages.append(message)
                }
            }
            guard let lastId = (batch.last?["id"] as? NSNumber)?.int64Value, lastId > 0 else {
                break
            }
            offsetId = lastId
            if batch.count < 100 {
                break
            }
        }
        return .success((channelTitle, messages))
    }

    /// Loads several channels into one folder catalog, keeping the newest copy
    /// of a plugin id when more than one channel publishes it.
    public static func loadFolderIndex(accountId: Int64, peerIds: [Int64], fallbackName: String, completion: @escaping (Result<(PluginCatalogIndex, String), PluginCatalogError>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            var merged: [String: PluginCatalogPlugin] = [:]
            for peerId in peerIds {
                guard case let .success((_, messages)) = self.loadChannelMessages(accountId: accountId, peerId: peerId) else {
                    continue
                }
                for plugin in self.channelPlugins(from: messages, peerId: peerId, accountId: accountId) {
                    if let existing = merged[plugin.id] {
                        if (existing.updatedAt ?? 0) < (plugin.updatedAt ?? 0) {
                            merged[plugin.id] = plugin
                        }
                    } else {
                        merged[plugin.id] = plugin
                    }
                }
            }
            let plugins = merged.values.sorted {
                $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
            }
            let index = PluginCatalogIndex(name: fallbackName, homepage: nil, plugins: plugins)
            completion(.success((index, "folder:\(fallbackName)")))
        }
    }

    /// Android's `PluginCatalogController.TRUSTED_FOLDER_SLUG`.
    public static let trustedFolderSlug = "pPhOtEq00KhjYTc6"

    /// Resolves the channels of Android's trusted folder through
    /// `chatlists.checkChatlistInvite`, the request the Android catalog makes
    /// before storing them as verified repositories.
    public static func loadVerifiedChannels(accountId: Int64, slug: String = trustedFolderSlug, completion: @escaping (Result<[(peerId: Int64, title: String, username: String?)], PluginCatalogError>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let response = PluginManager.shared.environment.request(
                accountId,
                "chatlists.checkChatlistInvite",
                ["slug": slug]
            )
            if let error = response["error"] as? String {
                completion(.failure(.network(error)))
                return
            }
            let peerValues = (response["peers"] as? [[String: Any]])
                ?? (response["already_peers"] as? [[String: Any]])
                ?? []
            var chatsById: [Int64: [String: Any]] = [:]
            for chat in (response["chats"] as? [[String: Any]]) ?? [] {
                if let id = (chat["id"] as? NSNumber)?.int64Value {
                    chatsById[id] = chat
                }
            }
            var values: [(peerId: Int64, title: String, username: String?)] = []
            var seen = Set<Int64>()
            for peer in peerValues {
                guard let constructor = peer["_"] as? String else {
                    continue
                }
                var peerId: Int64?
                var chatId: Int64?
                if constructor == "peerChannel" {
                    let id = (peer["channel_id"] as? NSNumber)?.int64Value
                        ?? (peer["channelId"] as? NSNumber)?.int64Value
                    if let id, id != 0 {
                        peerId = -1000000000000 - id
                        chatId = id
                    }
                } else if constructor == "peerChat" {
                    let id = (peer["chat_id"] as? NSNumber)?.int64Value
                        ?? (peer["chatId"] as? NSNumber)?.int64Value
                    if let id, id != 0 {
                        peerId = -id
                        chatId = id
                    }
                }
                guard let peerId, let chatId, seen.insert(peerId).inserted else {
                    continue
                }
                let chat = chatsById[chatId]
                let title = (chat?["title"] as? String) ?? "Channel \(chatId)"
                let username = (chat?["username"] as? String).flatMap { $0.isEmpty ? nil : $0 }
                values.append((peerId: peerId, title: title, username: username))
            }
            values.sort {
                $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending
            }
            completion(.success(values))
        }
    }

    /// Lists the channels in the account's dialog list for the "Choose channel"
    /// repository flow, the same picker Android opens.
    public static func loadDialogChannels(accountId: Int64, completion: @escaping (Result<[(peerId: Int64, title: String, username: String?)], PluginCatalogError>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let response = PluginManager.shared.environment.request(accountId, "messages.getDialogs", ["limit": 100])
            if let error = response["error"] as? String {
                completion(.failure(.network(error)))
                return
            }
            let chats = response["chats"] as? [[String: Any]] ?? []
            var values: [(peerId: Int64, title: String, username: String?)] = []
            for chat in chats {
                guard (chat["_"] as? String) == "channel",
                      let channelId = (chat["id"] as? NSNumber)?.int64Value, channelId != 0,
                      let title = chat["title"] as? String, !title.isEmpty else {
                    continue
                }
                let username = (chat["username"] as? String).flatMap { $0.isEmpty ? nil : $0 }
                values.append((
                    peerId: -1000000000000 - channelId,
                    title: title,
                    username: username
                ))
            }
            values.sort {
                $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending
            }
            completion(.success(values))
        }
    }

    /// Returns the dialog filters of an account, used by the "Add folder"
    /// repository flow.
    public static func loadDialogFilters(accountId: Int64, completion: @escaping (Result<[[String: Any]], PluginCatalogError>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let response = PluginManager.shared.environment.request(accountId, "messages.getDialogFilters", [:])
            if let error = response["error"] as? String {
                completion(.failure(.network(error)))
                return
            }
            let filters = response["filters"] as? [[String: Any]] ?? []
            completion(.success(filters))
        }
    }

    public static func folderTitle(from filter: [String: Any]) -> String? {
        if let title = filter["title"] as? [String: Any],
           let text = title["text"] as? String, !text.isEmpty {
            return text
        }
        if let title = filter["title"] as? String, !title.isEmpty {
            return title
        }
        return nil
    }

    public static func folderPeerIds(from filter: [String: Any]) -> [Int64] {
        var result: [Int64] = []
        for key in ["include_peers", "pinned_peers"] {
            let peers = filter[key] as? [[String: Any]] ?? []
            for peer in peers {
                guard (peer["_"] as? String) == "inputPeerChannel",
                      let channelId = (peer["channel_id"] as? NSNumber)?.int64Value,
                      channelId != 0 else {
                    continue
                }
                result.append(-1000000000000 - channelId)
            }
        }
        return Array(Set(result)).sorted()
    }

    private static func channelPlugins(from messages: [[String: Any]], peerId: Int64, accountId: Int64) -> [PluginCatalogPlugin] {
        var byId: [String: PluginCatalogPlugin] = [:]
        for message in messages {
            guard let media = message["media"] as? [String: Any],
                  (media["_"] as? String) == "messageMediaDocument",
                  let document = media["document"] as? [String: Any],
                  (document["_"] as? String) == "document",
                  let fileName = channelDocumentFileName(document),
                  isPluginFileName(fileName) else {
                continue
            }
            guard let documentId = (document["id"] as? NSNumber)?.int64Value,
                  let accessHash = (document["access_hash"] as? NSNumber)?.int64Value else {
                continue
            }
            let stem = (fileName as NSString).deletingPathExtension
            let size = (document["size"] as? NSNumber)?.int64Value ?? 0
            let date = (message["date"] as? NSNumber)?.intValue ?? 0
            let caption = (message["message"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            var plugin = PluginCatalogPlugin(
                id: stem,
                name: stem,
                version: "unknown",
                fileURL: "tg://document/\(documentId)",
                fileName: fileName,
                sha256: "",
                size: size,
                description: caption?.isEmpty == false ? caption : nil,
                author: nil,
                icon: nil,
                appVersion: nil,
                sdkVersion: nil,
                requirements: nil,
                categories: nil,
                updatedAt: date,
                documentId: documentId,
                documentAccessHash: accessHash,
                documentFileReference: document["file_reference"] as? String,
                channelPeerId: peerId,
                messageDate: date
            )
            if fileName.lowercased().hasSuffix(".plugin"),
               let source = self.channelPluginSource(accountId: accountId, plugin: plugin),
               let manifest = try? PluginManifestParser.parse(source: source) {
                plugin.id = manifest.id
                plugin.name = manifest.name
                plugin.version = manifest.version
                if !manifest.description.isEmpty {
                    plugin.description = manifest.description
                }
                if !manifest.author.isEmpty {
                    plugin.author = manifest.author
                }
                plugin.icon = manifest.icon
                plugin.appVersion = manifest.appVersionRequirement
                plugin.sdkVersion = manifest.sdkVersionRequirement
                if !manifest.requirements.isEmpty {
                    plugin.requirements = manifest.requirements.joined(separator: ", ")
                }
                plugin.categories = manifest.category
            }
            let key = plugin.id
            if let existing = byId[key] {
                if (existing.updatedAt ?? 0) < date {
                    byId[key] = plugin
                }
            } else {
                byId[key] = plugin
            }
        }
        return byId.values.sorted {
            $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
        }
    }

    /// Reads the first chunks of a `.plugin` document to show its real name and
    /// version in the channel catalog before installing it.
    private static func channelPluginSource(accountId: Int64, plugin: PluginCatalogPlugin) -> String? {
        guard let documentId = plugin.documentId,
              let accessHash = plugin.documentAccessHash else {
            return nil
        }
        let maximum = 64 * 1024
        var data = Data()
        var offset: Int64 = 0
        while data.count < maximum {
            let limit = Int32(min(32 * 1024, maximum - data.count))
            let response = PluginManager.shared.environment.request(accountId, "upload.getFile", [
                "id": documentId,
                "access_hash": accessHash,
                "file_reference": plugin.documentFileReference ?? "",
                "offset": offset,
                "limit": limit
            ])
            guard let base64 = response["bytes"] as? String,
                  let chunk = Data(base64Encoded: base64),
                  !chunk.isEmpty else {
                break
            }
            data.append(chunk)
            offset += Int64(chunk.count)
            if chunk.count < Int(limit) {
                break
            }
        }
        guard !data.isEmpty else {
            return nil
        }
        var source = String(decoding: data, as: UTF8.self)
        if let lastNewline = source.lastIndex(of: "\n") {
            source = String(source[..<lastNewline])
        }
        return source
    }

    private static func channelDocumentFileName(_ document: [String: Any]) -> String? {
        let attributes = document["attributes"] as? [[String: Any]] ?? []
        for attribute in attributes {
            if (attribute["_"] as? String) == "documentAttributeFilename",
               let fileName = attribute["file_name"] as? String,
               isSafeFileName(fileName) {
                return fileName
            }
        }
        return nil
    }

    private static func isPluginFileName(_ name: String) -> Bool {
        let value = (name as NSString).pathExtension.lowercased()
        return value == "plugin" || value == "elyx" || value == "eaf"
    }

    /// Downloads a channel catalog entry through `upload.getFile` chunks, the
    /// same bytes Android receives from `FileLoader`.
    public static func downloadChannelPlugin(accountId: Int64, plugin: PluginCatalogPlugin, completion: @escaping (Result<URL, PluginCatalogError>) -> Void) {
        guard let documentId = plugin.documentId,
              let accessHash = plugin.documentAccessHash,
              isSafeFileName(plugin.fileName) else {
            completion(.failure(.download("This catalog entry has no Telegram document.")))
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            var data = Data()
            var offset: Int64 = 0
            let limit: Int32 = 512 * 1024
            while true {
                let response = PluginManager.shared.environment.request(accountId, "upload.getFile", [
                    "id": documentId,
                    "access_hash": accessHash,
                    "file_reference": plugin.documentFileReference ?? "",
                    "offset": offset,
                    "limit": limit
                ])
                if let error = response["error"] as? String {
                    completion(.failure(.download(error)))
                    return
                }
                guard let base64 = response["bytes"] as? String,
                      let chunk = Data(base64Encoded: base64),
                      !chunk.isEmpty else {
                    break
                }
                data.append(chunk)
                offset += Int64(chunk.count)
                if (plugin.size > 0 && Int64(data.count) >= plugin.size) || chunk.count < Int(limit) {
                    break
                }
                if Int64(data.count) > maximumPluginSize {
                    completion(.failure(.verification))
                    return
                }
            }
            guard !data.isEmpty else {
                completion(.failure(.download("The document download returned no bytes.")))
                return
            }
            let manager = FileManager.default
            let cacheRoot = manager.urls(for: .cachesDirectory, in: .userDomainMask).first
                ?? URL(fileURLWithPath: NSTemporaryDirectory())
            let directory = cacheRoot.appendingPathComponent("plugin_catalog", isDirectory: true)
                .appendingPathComponent("channel-\(documentId)", isDirectory: true)
            let destination = directory.appendingPathComponent(plugin.fileName)
            do {
                try manager.createDirectory(at: directory, withIntermediateDirectories: true)
                try? manager.removeItem(at: destination)
                try data.write(to: destination)
                completion(.success(destination))
            } catch {
                completion(.failure(.download(error.localizedDescription)))
            }
        }
    }
}

/// Repositories the user added, persisted in `UserDefaults` like Android keeps
/// its catalog repositories in SQLite.
public final class PluginCatalogStore {
    public static let shared = PluginCatalogStore()

    private let defaults = UserDefaults.standard
    private let key = "extera.plugins.catalog.repositories"
    private let lock = NSLock()
    private var cached: [PluginCatalogRepository]?

    private init() {
    }

    public var repositories: [PluginCatalogRepository] {
        self.lock.lock()
        if let cached {
            self.lock.unlock()
            return cached
        }
        self.lock.unlock()
        let values: [PluginCatalogRepository]
        if let data = self.defaults.data(forKey: self.key),
           let decoded = try? JSONDecoder().decode([PluginCatalogRepository].self, from: data) {
            values = decoded
        } else {
            values = []
        }
        self.lock.lock()
        self.cached = values
        self.lock.unlock()
        return values
    }

    @discardableResult
    public func add(url: String, name: String, homepage: String?) -> PluginCatalogRepository? {
        guard let normalized = PluginCatalog.normalizeURL(url) else {
            return nil
        }
        var values = self.repositories
        if let index = values.firstIndex(where: { $0.url == normalized }) {
            values[index].name = name
            if let homepage {
                values[index].homepage = homepage
            }
        } else {
            values.append(PluginCatalogRepository(
                id: normalized,
                url: normalized,
                name: name,
                homepage: homepage,
                addedAt: Date().timeIntervalSince1970
            ))
        }
        self.save(values)
        self.postCatalogUpdated(normalized)
        return values.first { $0.url == normalized }
    }

    /// Posts Android's `pluginCatalogUpdated` with the repository id, so a
    /// plugin observing the catalog sees the same event as on Android.
    private func postCatalogUpdated(_ id: String) {
        guard PythonRuntime.shared.isStarted else {
            return
        }
        DispatchQueue.global(qos: .utility).async {
            _ = try? PythonRuntime.shared.call("notify_plugin_event", ["pluginCatalogUpdated", id])
        }
    }

    /// Adds a Telegram folder as a repository: the included channels are stored
    /// and their documents are merged into one catalog.
    @discardableResult
    public func addFolder(name: String, peerIds: [Int64], homepage: String? = nil) -> PluginCatalogRepository? {
        let peers = Array(Set(peerIds)).sorted()
        guard !peers.isEmpty else {
            return nil
        }
        let id = "folder:\(name.lowercased())"
        var values = self.repositories
        let repository = PluginCatalogRepository(
            id: id,
            url: "",
            name: name,
            homepage: homepage,
            addedAt: Date().timeIntervalSince1970,
            kind: "folder",
            peerIds: peers
        )
        if let index = values.firstIndex(where: { $0.id == id }) {
            values[index] = repository
            values[index].addedAt = self.repositories[index].addedAt
        } else {
            values.append(repository)
        }
        self.save(values)
        self.postCatalogUpdated(id)
        return values.first { $0.id == id }
    }

    /// Adds a Telegram channel as a repository, the counterpart of Android's
    /// channel catalogs. The peer id is the Android dialog id (`-100…`).
    @discardableResult
    public func addChannel(peerId: Int64, username: String?, name: String, homepage: String? = nil) -> PluginCatalogRepository? {
        guard peerId != 0 else {
            return nil
        }
        let id = "channel:\(peerId)"
        let url = username.flatMap { value -> String? in
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : "https://t.me/\(trimmed)"
        } ?? ""
        var values = self.repositories
        if let index = values.firstIndex(where: { $0.id == id }) {
            values[index].name = name
            values[index].username = username
            values[index].url = url
            if let homepage {
                values[index].homepage = homepage
            }
        } else {
            values.append(PluginCatalogRepository(
                id: id,
                url: url,
                name: name,
                homepage: homepage,
                addedAt: Date().timeIntervalSince1970,
                kind: "channel",
                peerId: peerId,
                username: username
            ))
        }
        self.save(values)
        self.postCatalogUpdated(id)
        return values.first { $0.id == id }
    }

    public func remove(id: String) {
        self.save(self.repositories.filter { $0.id != id })
        self.defaults.removeObject(forKey: self.indexKey(id))
        self.postCatalogUpdated(id)
    }

    /// Replaces the verified repositories with the current contents of Android's
    /// trusted folder. Channels that stay keep the timestamp they were first
    /// added at, the way Android's `replaceFolderRepositories` preserves it.
    @discardableResult
    public func replaceVerified(_ channels: [(peerId: Int64, title: String, username: String?)]) -> Bool {
        var values = self.repositories
        let existing = Dictionary(uniqueKeysWithValues: values
            .filter { $0.kind == "verified" }
            .map { ($0.id, $0) })
        let now = Date().timeIntervalSince1970
        var updated: [PluginCatalogRepository] = []
        for channel in channels {
            let id = "verified:\(channel.peerId)"
            var repository = existing[id] ?? PluginCatalogRepository(
                id: id,
                url: channel.username.map { "https://t.me/\($0)" } ?? "",
                name: channel.title,
                addedAt: now,
                kind: "verified",
                peerId: channel.peerId,
                username: channel.username
            )
            repository.name = channel.title
            repository.username = channel.username
            repository.url = channel.username.map { "https://t.me/\($0)" } ?? ""
            updated.append(repository)
        }
        let updatedIds = Set(updated.map { $0.id })
        values.removeAll { $0.kind == "verified" && !updatedIds.contains($0.id) }
        for repository in updated {
            if let index = values.firstIndex(where: { $0.id == repository.id }) {
                values[index] = repository
            } else {
                values.append(repository)
            }
        }
        self.save(values)
        self.postCatalogUpdated("verified")
        return true
    }

    private var verifiedRefreshKey: String {
        return "extera.plugins.catalog.verified.refreshed_at"
    }

    /// Android refreshes the trusted folder at most once every five minutes.
    public func verifiedRefreshNeeded(interval: TimeInterval = 5 * 60) -> Bool {
        let last = self.defaults.double(forKey: self.verifiedRefreshKey)
        return last <= 0 || Date().timeIntervalSince1970 - last >= interval
    }

    public func markVerifiedRefreshed() {
        self.defaults.set(Date().timeIntervalSince1970, forKey: self.verifiedRefreshKey)
    }

    /// Returns the last successfully synced catalog for a repository, so the
    /// screen can show it immediately while a refresh is in flight.
    public func cachedIndex(id: String) -> PluginCatalogIndex? {
        guard let data = self.defaults.data(forKey: self.indexKey(id)) else {
            return nil
        }
        return try? JSONDecoder().decode(PluginCatalogIndex.self, from: data)
    }

    /// Stores the index and the sync state used for `If-None-Match`.
    public func recordSync(id: String, index: PluginCatalogIndex, etag: String?) {
        var values = self.repositories
        if let position = values.firstIndex(where: { $0.id == id }) {
            values[position].syncedAt = Date().timeIntervalSince1970
            values[position].pluginsCount = index.plugins.count
            if let etag, !etag.isEmpty {
                values[position].etag = etag
            }
        }
        self.save(values)
        if let data = try? JSONEncoder().encode(index) {
            self.defaults.set(data, forKey: self.indexKey(id))
        }
        self.postCatalogUpdated(id)
    }

    private func indexKey(_ id: String) -> String {
        return "extera.plugins.catalog.index.\(id)"
    }

    private func save(_ values: [PluginCatalogRepository]) {
        self.lock.lock()
        self.cached = values
        self.lock.unlock()
        if let data = try? JSONEncoder().encode(values) {
            self.defaults.set(data, forKey: self.key)
        }
    }
}
