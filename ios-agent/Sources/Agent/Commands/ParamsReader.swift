import Foundation

/// Small typed reader over a command's `params` object.
public struct ParamsReader {
    private let object: [String: JSONValue]
    private let method: String

    public init(_ params: JSONValue?, method: String) {
        self.object = params?.objectValue ?? [:]
        self.method = method
    }

    public func raw(_ key: String) -> JSONValue? {
        guard let value = object[key], !value.isNull else { return nil }
        return value
    }

    public func string(_ key: String) -> String? { raw(key)?.stringValue }
    public func int(_ key: String) -> Int? { raw(key)?.intValue }
    public func double(_ key: String) -> Double? { raw(key)?.doubleValue }
    public func bool(_ key: String) -> Bool? { raw(key)?.boolValue }

    public func requiredString(_ key: String) throws -> String {
        guard let value = string(key) else {
            throw AgentError.invalidParams("`\(key)` is required for \(method)")
        }
        return value
    }

    public func requiredDouble(_ key: String) throws -> Double {
        guard let value = double(key) else {
            throw AgentError.invalidParams("`\(key)` is required for \(method)")
        }
        return value
    }

    public func requiredSelector(_ key: String = "selector") throws -> ElementSelector {
        try ElementSelector(json: raw(key))
    }

    /// Reads a normalized point, accepting either `{"x": .., "y": ..}` or `[x, y]`.
    public func point(_ key: String) throws -> CGPoint {
        guard let value = raw(key) else {
            throw AgentError.invalidParams("`\(key)` is required for \(method)")
        }
        if let object = value.objectValue,
           let x = object["x"]?.doubleValue, let y = object["y"]?.doubleValue {
            return CGPoint(x: x, y: y)
        }
        if let array = value.arrayValue, array.count == 2,
           let x = array[0].doubleValue, let y = array[1].doubleValue {
            return CGPoint(x: x, y: y)
        }
        throw AgentError.invalidParams("`\(key)` must be {x, y} or [x, y]")
    }

    public func timeout(default fallback: TimeInterval = 0) -> TimeInterval {
        double("timeout") ?? fallback
    }
}
