import CryptoKit
import Foundation

public enum CachePrivacy: Sendable { case publicReadOnly, privateContent }

public struct CachedResponse: Codable, Equatable, Sendable {
    public let data: Data
    public let etag: String?
    public let storedAt: Date
    public let expiresAt: Date

    public init(data: Data, etag: String?, storedAt: Date = .now, expiresAt: Date) {
        self.data = data
        self.etag = etag
        self.storedAt = storedAt
        self.expiresAt = expiresAt
    }

    public var isStale: Bool {
        expiresAt <= .now
    }
}

public actor DiskResponseCache: PrivateDataClearing {
    private let directory: URL
    private let maximumBytes: Int
    private let fileManager: FileManager
    private let metrics: NetworkMetrics?
    private let encoder = PropertyListEncoder()
    private let decoder = PropertyListDecoder()

    public init(
        directory: URL,
        maximumBytes: Int = 32 * 1024 * 1024,
        fileManager: FileManager = .default,
        metrics: NetworkMetrics? = nil
    ) {
        self.directory = directory
        self.maximumBytes = max(0, maximumBytes)
        self.fileManager = fileManager
        self.metrics = metrics
    }

    public func value(forKey key: String, privacy: CachePrivacy = .publicReadOnly) async throws -> CachedResponse? {
        guard privacy == .publicReadOnly else { return nil }
        let url = fileURL(for: key)
        guard fileManager.fileExists(atPath: url.path) else { return nil }
        do {
            let value = try decoder.decode(CachedResponse.self, from: Data(contentsOf: url))
            await metrics?.recordCacheHit()
            return value
        } catch { try? fileManager.removeItem(at: url); return nil }
    }

    public func insert(_ response: CachedResponse, forKey key: String, privacy: CachePrivacy = .publicReadOnly) throws {
        guard privacy == .publicReadOnly, maximumBytes > 0 else { return }
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try encoder.encode(response)
        guard data.count <= maximumBytes else { return }
        try data.write(to: fileURL(for: key), options: .atomic)
        try trimIfNeeded()
    }

    public func clearPrivateData() async {
        // Only explicitly safe, read-only responses enter this cache. Logout still
        // clears it so account-scoped metadata cannot cross sessions.
        try? fileManager.removeItem(at: directory)
    }

    private func fileURL(for key: String) -> URL {
        let digest = SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
        return directory.appending(path: digest).appendingPathExtension("cache")
    }

    private func trimIfNeeded() throws {
        let keys: Set<URLResourceKey> = [.contentModificationDateKey, .fileSizeKey, .isRegularFileKey]
        let urls = try fileManager.contentsOfDirectory(at: directory, includingPropertiesForKeys: Array(keys))
        var entries: [(URL, Date, Int)] = try urls.compactMap { url in
            let values = try url.resourceValues(forKeys: keys)
            guard values.isRegularFile == true else { return nil }
            return (url, values.contentModificationDate ?? .distantPast, values.fileSize ?? 0)
        }
        var total = entries.reduce(0) { $0 + $1.2 }
        entries.sort { $0.1 < $1.1 }
        for entry in entries where total > maximumBytes {
            try fileManager.removeItem(at: entry.0)
            total -= entry.2
        }
    }
}
