import Foundation
import Security

public protocol RefreshTokenStore: Sendable {
    func load() async throws -> String?
    func save(_ token: String) async throws
    func delete() async throws
}

public enum CredentialStoreError: Error, Equatable, Sendable { case keychain(status: Int32) }

public actor KeychainRefreshTokenStore: RefreshTokenStore {
    private let service: String
    private let account: String

    public init(service: String = "com.jiale.StockMonitor.auth", account: String = "refresh-token") {
        self.service = service
        self.account = account
    }

    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    public func load() throws -> String? {
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &item)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess, let data = item as? Data, let token = String(data: data, encoding: .utf8) else {
            throw CredentialStoreError.keychain(status: status)
        }
        return token
    }

    public func save(_ token: String) throws {
        let data = Data(token.utf8)
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecItemNotFound {
            var insertion = query
            insertion.merge(attributes) { _, new in new }
            let addStatus = SecItemAdd(insertion as CFDictionary, nil)
            guard addStatus == errSecSuccess else { throw CredentialStoreError.keychain(status: addStatus) }
        } else if updateStatus != errSecSuccess {
            throw CredentialStoreError.keychain(status: updateStatus)
        }
    }

    public func delete() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw CredentialStoreError.keychain(status: status)
        }
    }
}

public actor InMemoryRefreshTokenStore: RefreshTokenStore {
    private var token: String?
    public init(token: String? = nil) {
        self.token = token
    }

    public func load() -> String? {
        token
    }

    public func save(_ token: String) {
        self.token = token
    }

    public func delete() {
        token = nil
    }
}
