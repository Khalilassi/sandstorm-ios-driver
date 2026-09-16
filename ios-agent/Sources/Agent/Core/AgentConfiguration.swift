import Foundation
import Network

/// Runtime configuration for the on-device agent.
///
/// Everything is supplied through environment variables because that is the
/// only channel `xcodebuild` reliably forwards into an XCTest runner process:
/// variables prefixed with `TEST_RUNNER_` are injected into the runner with the
/// prefix stripped.
public struct AgentConfiguration {
    public static let defaultPort: UInt16 = 8433

    public let port: UInt16
    public let token: String?
    public let bindAllInterfaces: Bool
    public let idleShutdownTimeout: TimeInterval

    public var nwPort: NWEndpoint.Port {
        NWEndpoint.Port(rawValue: port) ?? NWEndpoint.Port(rawValue: Self.defaultPort)!
    }

    public init(environment: [String: String] = ProcessInfo.processInfo.environment) {
        self.port = environment["SANDSTORM_PORT"].flatMap { UInt16($0) } ?? Self.defaultPort
        let token = environment["SANDSTORM_TOKEN"]
        self.token = (token?.isEmpty ?? true) ? nil : token
        self.bindAllInterfaces = environment["SANDSTORM_BIND_ALL"] == "1"
        self.idleShutdownTimeout = environment["SANDSTORM_IDLE_TIMEOUT"].flatMap { TimeInterval($0) } ?? 0
    }

    /// When the controller supplies a token, clients must present it.
    /// When no token is configured (local development on a simulator) the
    /// handshake is accepted without one.
    public func isTokenValid(_ candidate: String?) -> Bool {
        guard let expected = token else { return true }
        guard let candidate, candidate.count == expected.count else { return false }
        // Constant time comparison.
        return zip(expected.utf8, candidate.utf8).reduce(0) { $0 | ($1.0 ^ $1.1) } == 0
    }
}
