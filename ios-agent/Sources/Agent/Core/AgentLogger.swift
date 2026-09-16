import Foundation

/// Structured, greppable logging. Every line is prefixed so the controller can
/// parse `xcodebuild` output for lifecycle markers such as
/// `SANDSTORM_AGENT_READY`.
public enum AgentLogger {
    public enum Level: String {
        case debug = "DEBUG"
        case info = "INFO"
        case error = "ERROR"
    }

    public static var minimumLevel: Level = {
        switch ProcessInfo.processInfo.environment["SANDSTORM_LOG_LEVEL"]?.lowercased() {
        case "debug": return .debug
        case "error": return .error
        default: return .info
        }
    }()

    private static let queue = DispatchQueue(label: "com.sandstorm.agent.log")
    private static let formatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    public static func debug(_ message: @autoclosure () -> String) { log(.debug, message()) }
    public static func info(_ message: @autoclosure () -> String) { log(.info, message()) }
    public static func error(_ message: @autoclosure () -> String) { log(.error, message()) }

    private static func log(_ level: Level, _ message: String) {
        guard level.rank >= minimumLevel.rank else { return }
        let line = "[sandstorm][\(formatter.string(from: Date()))][\(level.rawValue)] \(message)"
        queue.async { print(line) }
    }
}

private extension AgentLogger.Level {
    var rank: Int {
        switch self {
        case .debug: return 0
        case .info: return 1
        case .error: return 2
        }
    }
}
