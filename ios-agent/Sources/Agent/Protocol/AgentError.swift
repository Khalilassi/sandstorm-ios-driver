import Foundation

/// Stable, machine readable error codes shared with the Python SDK.
///
/// Keep in sync with `sandstorm_ios.protocol.errors.ErrorCode`.
public enum AgentErrorCode: String {
    case unknownMethod = "UNKNOWN_METHOD"
    case invalidParams = "INVALID_PARAMS"
    case elementNotFound = "ELEMENT_NOT_FOUND"
    case elementNotInteractable = "ELEMENT_NOT_INTERACTABLE"
    case staleElement = "STALE_ELEMENT"
    case appLaunchFailed = "APP_LAUNCH_FAILED"
    case noActiveApp = "NO_ACTIVE_APP"
    case alertNotFound = "ALERT_NOT_FOUND"
    case timeout = "TIMEOUT"
    case snapshotFailed = "SNAPSHOT_FAILED"
    case unauthorized = "UNAUTHORIZED"
    case protocolError = "PROTOCOL_ERROR"
    case internalError = "INTERNAL_ERROR"
}

public struct AgentError: Error {
    public let code: AgentErrorCode
    public let message: String
    public let details: JSONValue?

    public init(_ code: AgentErrorCode, _ message: String, details: JSONValue? = nil) {
        self.code = code
        self.message = message
        self.details = details
    }

    public static func invalidParams(_ message: String) -> AgentError {
        AgentError(.invalidParams, message)
    }

    public static func elementNotFound(_ selectorDescription: String) -> AgentError {
        AgentError(
            .elementNotFound,
            "Element was not found: \(selectorDescription)",
            details: .object(["selector": .string(selectorDescription)])
        )
    }

    public static func internalError(_ error: Error) -> AgentError {
        AgentError(.internalError, String(describing: error))
    }
}
