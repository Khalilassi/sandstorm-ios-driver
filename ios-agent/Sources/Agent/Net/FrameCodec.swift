import Foundation

/// Sandstorm frame types.
///
/// Wire format (all integers big endian):
///
///     +--------+------------------+------------------+
///     | type   | length (uint32)  | payload          |
///     | uint8  | 4 bytes          | `length` bytes   |
///     +--------+------------------+------------------+
///
/// A `.json` frame carrying a `binary` descriptor is always immediately
/// followed by exactly one `.binary` frame on the same connection. This avoids
/// base64 inflation for screenshots.
public enum FrameType: UInt8 {
    case json = 0x01
    case binary = 0x02
}

public struct Frame {
    public let type: FrameType
    public let payload: Data

    public init(type: FrameType, payload: Data) {
        self.type = type
        self.payload = payload
    }

    public func encoded() -> Data {
        var data = Data(capacity: payload.count + FrameCodec.headerSize)
        data.append(type.rawValue)
        var length = UInt32(payload.count).bigEndian
        withUnsafeBytes(of: &length) { data.append(contentsOf: $0) }
        data.append(payload)
        return data
    }
}

/// Incremental frame parser. Feed it bytes, pull out whole frames.
public final class FrameCodec {
    public static let headerSize = 5
    public static let maxPayloadSize = 64 * 1024 * 1024

    private var buffer = Data()

    public init() {}

    public func append(_ data: Data) {
        buffer.append(data)
    }

    /// Returns the next complete frame, or `nil` when more bytes are required.
    public func nextFrame() throws -> Frame? {
        guard buffer.count >= Self.headerSize else { return nil }

        let header = buffer.prefix(Self.headerSize)
        let bytes = [UInt8](header)
        guard let type = FrameType(rawValue: bytes[0]) else {
            throw AgentError(.protocolError, "Unknown frame type \(bytes[0])")
        }

        let length = (UInt32(bytes[1]) << 24) | (UInt32(bytes[2]) << 16) | (UInt32(bytes[3]) << 8) | UInt32(bytes[4])
        guard length <= UInt32(Self.maxPayloadSize) else {
            throw AgentError(.protocolError, "Frame payload of \(length) bytes exceeds limit")
        }

        let total = Self.headerSize + Int(length)
        guard buffer.count >= total else { return nil }

        let payload = buffer.subdata(in: Self.headerSize..<total)
        buffer.removeSubrange(0..<total)
        return Frame(type: type, payload: payload)
    }
}
