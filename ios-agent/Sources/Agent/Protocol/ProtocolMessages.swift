import Foundation

public enum SandstormProtocol {
    /// Bumped whenever the wire format changes in a backwards incompatible way.
    public static let version = 1
    public static let agentVersion = "0.1.0"
}

// MARK: - Handshake

public struct HandshakeRequest: Decodable {
    public let protocolVersion: Int
    public let client: String
    public let clientVersion: String
    public let token: String?
}

public struct DeviceDescriptor: Encodable {
    public let name: String
    public let iosVersion: String
    public let model: String
    public let udid: String?
    public let isSimulator: Bool
    public let screen: ScreenDescriptor
}

public struct ScreenDescriptor: Encodable {
    public let width: Double
    public let height: Double
    public let scale: Double
}

public struct HandshakeResponse: Encodable {
    public let protocolVersion: Int
    public let agentVersion: String
    public let sessionId: String
    public let device: DeviceDescriptor
}

// MARK: - Requests / responses

public struct RequestMessage: Decodable {
    public let id: Int
    public let method: String
    public let params: JSONValue?
}

/// Describes a binary frame that immediately follows a JSON response frame.
public struct BinaryDescriptor: Encodable {
    public let length: Int
    public let encoding: String
    public let mimeType: String
}

public struct ErrorPayload: Encodable {
    public let code: String
    public let message: String
    public let details: JSONValue?
}

public struct ResponseMessage: Encodable {
    public let id: Int
    public let success: Bool
    public var result: JSONValue?
    public var error: ErrorPayload?
    public var binary: BinaryDescriptor?

    public static func ok(id: Int, result: JSONValue = .emptyObject) -> ResponseMessage {
        ResponseMessage(id: id, success: true, result: result, error: nil, binary: nil)
    }

    public static func failure(id: Int, error: AgentError) -> ResponseMessage {
        ResponseMessage(
            id: id,
            success: false,
            result: nil,
            error: ErrorPayload(code: error.code.rawValue, message: error.message, details: error.details),
            binary: nil
        )
    }
}

/// The result of executing a single command.
public struct CommandOutcome {
    public var result: JSONValue
    public var binary: Data?
    public var binaryMimeType: String

    public init(result: JSONValue = .emptyObject, binary: Data? = nil, binaryMimeType: String = "application/octet-stream") {
        self.result = result
        self.binary = binary
        self.binaryMimeType = binaryMimeType
    }
}
