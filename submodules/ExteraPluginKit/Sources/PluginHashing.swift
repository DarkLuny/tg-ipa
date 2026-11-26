import Foundation
#if canImport(CryptoKit)
import CryptoKit
#else
import CommonCrypto
#endif

public enum PluginHashing {
    public static func sha256(_ data: Data) -> String {
        #if canImport(CryptoKit)
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
        #else
        var digest = [UInt8](repeating: 0, count: Int(CC_SHA256_DIGEST_LENGTH))
        data.withUnsafeBytes { buffer in
            _ = CC_SHA256(buffer.baseAddress, CC_LONG(data.count), &digest)
        }
        return digest.map { String(format: "%02x", $0) }.joined()
        #endif
    }

    public static func sha256(fileAt url: URL) -> String? {
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }
        return self.sha256(data)
    }
}
