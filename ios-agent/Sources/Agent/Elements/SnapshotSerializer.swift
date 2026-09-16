import Foundation
import XCTest

/// Serializes the accessibility tree into the normalized Sandstorm JSON shape.
///
/// Performance note
/// ---------------
/// Reading properties off individual `XCUIElement` instances is expensive:
/// every access is a synchronous IPC round trip into the application under
/// test. `XCUIElement.snapshot()` (public since Xcode 11) captures the **whole**
/// subtree in a *single* round trip and returns plain in-process value objects,
/// so the recursive walk below is pure local work. This is the difference
/// between ~1 IPC call and ~N IPC calls per hierarchy dump.
public enum SnapshotSerializer {
    public struct Options {
        public var maxDepth: Int
        public var includeInvisible: Bool
        public var screenBounds: CGRect

        public init(maxDepth: Int = 60, includeInvisible: Bool = true, screenBounds: CGRect) {
            self.maxDepth = maxDepth
            self.includeInvisible = includeInvisible
            self.screenBounds = screenBounds
        }
    }

    public static func serialize(_ snapshot: XCUIElementSnapshot, options: Options) -> JSONValue {
        node(snapshot, path: "0", depth: 0, options: options) ?? .null
    }

    private static func node(
        _ snapshot: XCUIElementSnapshot,
        path: String,
        depth: Int,
        options: Options
    ) -> JSONValue? {
        let frame = snapshot.frame
        let visible = isVisible(frame: frame, in: options.screenBounds)
        if !visible && !options.includeInvisible { return nil }

        var object: [String: JSONValue] = [
            "type": .string(ElementTypeMapper.name(for: snapshot.elementType)),
            "identifier": .string(snapshot.identifier),
            "label": .string(snapshot.label),
            "value": stringify(snapshot.value),
            "title": .string(snapshot.title),
            "placeholder": .from(snapshot.placeholderValue),
            "enabled": .bool(snapshot.isEnabled),
            "selected": .bool(snapshot.isSelected),
            "visible": .bool(visible),
            "path": .string(path),
            "frame": .object([
                "x": .number(Double(frame.origin.x)),
                "y": .number(Double(frame.origin.y)),
                "width": .number(Double(frame.size.width)),
                "height": .number(Double(frame.size.height))
            ])
        ]

        if depth < options.maxDepth {
            let children = snapshot.children.enumerated().compactMap { index, child in
                node(child, path: "\(path).\(index)", depth: depth + 1, options: options)
            }
            if !children.isEmpty {
                object["children"] = .array(children)
            }
        } else if !snapshot.children.isEmpty {
            object["truncated"] = .bool(true)
        }

        return .object(object)
    }

    /// Heuristic visibility.
    ///
    /// Apple does not expose a `visible` flag on `XCUIElementSnapshot`
    /// (`isHittable` only exists on the far more expensive `XCUIElement`), so
    /// we approximate it with a non-empty frame that intersects the screen.
    /// Occlusion by sibling views is not detected.
    private static func isVisible(frame: CGRect, in screen: CGRect) -> Bool {
        guard frame.width > 0, frame.height > 0 else { return false }
        guard !screen.isEmpty else { return true }
        return frame.intersects(screen)
    }

    private static func stringify(_ value: Any?) -> JSONValue {
        switch value {
        case .none: return .null
        case let string as String: return .string(string)
        case let bool as Bool: return .bool(bool)
        case let number as NSNumber: return .number(number.doubleValue)
        case let other?: return .string(String(describing: other))
        }
    }
}
