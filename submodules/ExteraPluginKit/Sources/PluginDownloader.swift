import Foundation

/// Downloads a Telegram document through `upload.getFile` in chunks, the same
/// request a channel catalog uses, and stores it in the plugin cache.
///
/// `FileLoader.loadFile` calls this on a background thread and `getPathToAttach`
/// then finds the file where Android's `FileLoader` would have put it.
enum PluginDownloader {
    static func download(
        accountId: Int64,
        fileId: Int64,
        accessHash: Int64,
        fileReference: Data,
        fileName: String,
        size: Int64,
        kind: String = "document",
        thumbSize: String = ""
    ) -> [String: Any] {
        guard fileId != 0 else {
            return ["error": "file id is required"]
        }
        let safeName = PluginCatalog.isSafeFileName(fileName) ? fileName : "doc_\(fileId)"
        let cache = FileManager.default.temporaryDirectory
        let destination = cache.appendingPathComponent(safeName)
        if let attributes = try? FileManager.default.attributesOfItem(atPath: destination.path),
           let existing = (attributes[.size] as? NSNumber)?.int64Value,
           existing > 0, size <= 0 || existing == size {
            return ["path": destination.path, "size": existing, "cached": true]
        }
        let reference = fileReference.base64EncodedString()
        var data = Data()
        var offset: Int64 = 0
        let limit: Int32 = 512 * 1024
        while true {
            let response = PluginManager.shared.environment.request(accountId, "upload.getFile", [
                "id": fileId,
                "access_hash": accessHash,
                "file_reference": reference,
                "offset": offset,
                "limit": limit,
                "kind": kind,
                "thumb_size": thumbSize
            ])
            if let error = response["error"] as? String {
                return ["error": error]
            }
            guard let text = response["bytes"] as? String,
                  let chunk = Data(base64Encoded: text), !chunk.isEmpty else {
                break
            }
            data.append(chunk)
            offset += Int64(chunk.count)
            if size > 0 && offset >= size {
                break
            }
            if Int64(chunk.count) < Int64(limit) {
                break
            }
        }
        guard !data.isEmpty else {
            return ["error": "the download returned no bytes"]
        }
        do {
            try data.write(to: destination, options: .atomic)
        } catch {
            return ["error": "could not write the file: \(error)"]
        }
        return ["path": destination.path, "size": data.count]
    }
}
