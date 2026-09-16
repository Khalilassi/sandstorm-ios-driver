import Foundation
import XCTest

/// Internal, strategy-agnostic selector model.
///
/// The Python SDK always sends this compound shape. Single-strategy helpers
/// (`get_by_id`, `get_by_text`, ...) are a client side convenience that
/// collapses into the same structure, which keeps the agent simple.
public struct ElementSelector {
    public var elementType: String?
    public var identifier: String?
    public var label: String?
    public var text: String?
    public var value: String?
    public var predicate: String?
    public var index: Int?
    public var exact: Bool
    /// Optional parent selector, evaluated first. Enables locator chaining.
    public indirect enum Parent { case selector(ElementSelector) }
    public var parent: Parent?

    public init(json: JSONValue?) throws {
        guard let object = json?.objectValue else {
            throw AgentError.invalidParams("`selector` must be an object")
        }

        // Legacy/compact form: {"strategy": "...", "value": "..."}
        if let strategy = object["strategy"]?.stringValue {
            let raw = object["value"]?.stringValue
            switch strategy {
            case "accessibilityId", "identifier":
                identifier = raw
            case "label":
                label = raw
            case "text":
                text = raw
            case "type":
                elementType = raw
            case "predicate":
                predicate = raw
            case "index":
                index = object["value"]?.intValue
            default:
                throw AgentError.invalidParams("Unknown locator strategy '\(strategy)'")
            }
        }

        elementType = object["type"]?.stringValue ?? elementType
        identifier = object["identifier"]?.stringValue ?? identifier
        label = object["label"]?.stringValue ?? label
        text = object["text"]?.stringValue ?? text
        value = object["value_"]?.stringValue ?? value
        predicate = object["predicate"]?.stringValue ?? predicate
        index = object["index"]?.intValue ?? index
        exact = object["exact"]?.boolValue ?? true

        if let parentJSON = object["parent"], !parentJSON.isNull {
            parent = .selector(try ElementSelector(json: parentJSON))
        }

        if elementType == nil, identifier == nil, label == nil, text == nil,
           value == nil, predicate == nil, index == nil {
            throw AgentError.invalidParams("Selector has no criteria")
        }
    }

    public var description: String {
        var parts: [String] = []
        if let elementType { parts.append("type=\(elementType)") }
        if let identifier { parts.append("identifier=\(identifier)") }
        if let label { parts.append("label=\(label)") }
        if let text { parts.append("text=\(text)") }
        if let value { parts.append("value=\(value)") }
        if let predicate { parts.append("predicate=\(predicate)") }
        if let index { parts.append("index=\(index)") }
        if case .selector(let parent)? = parent { parts.append("parent=(\(parent.description))") }
        return parts.joined(separator: ", ")
    }

    /// NSPredicate built from the non-nil criteria. Evaluated inside the app
    /// process by XCTest, which keeps matching off the USB wire.
    public func buildPredicate() -> NSPredicate? {
        var predicates: [NSPredicate] = []
        let op = exact ? "==" : "CONTAINS"

        if let identifier {
            predicates.append(NSPredicate(format: "identifier \(op) %@", identifier))
        }
        if let label {
            predicates.append(NSPredicate(format: "label \(op) %@", label))
        }
        if let value {
            predicates.append(NSPredicate(format: "value \(op) %@", value))
        }
        if let text {
            predicates.append(NSCompoundPredicate(orPredicateWithSubpredicates: [
                NSPredicate(format: "label \(op) %@", text),
                NSPredicate(format: "value \(op) %@", text),
                NSPredicate(format: "title \(op) %@", text),
                NSPredicate(format: "placeholderValue \(op) %@", text)
            ]))
        }
        if let predicate {
            predicates.append(NSPredicate(format: predicate))
        }

        guard !predicates.isEmpty else { return nil }
        return predicates.count == 1 ? predicates[0] : NSCompoundPredicate(andPredicateWithSubpredicates: predicates)
    }
}

/// Maps the wire names of `XCUIElementType` onto the enum.
public enum ElementTypeMapper {
    private static let table: [String: XCUIElement.ElementType] = [
        "any": .any,
        "other": .other,
        "application": .application,
        "window": .window,
        "button": .button,
        "staticText": .staticText,
        "textField": .textField,
        "secureTextField": .secureTextField,
        "textView": .textView,
        "searchField": .searchField,
        "image": .image,
        "cell": .cell,
        "table": .table,
        "collectionView": .collectionView,
        "scrollView": .scrollView,
        "switch": .switch,
        "slider": .slider,
        "navigationBar": .navigationBar,
        "tabBar": .tabBar,
        "alert": .alert,
        "sheet": .sheet,
        "link": .link,
        "picker": .picker,
        "pickerWheel": .pickerWheel,
        "segmentedControl": .segmentedControl,
        "stepper": .stepper,
        "toggle": .toggle,
        "activityIndicator": .activityIndicator,
        "progressIndicator": .progressIndicator,
        "toolbar": .toolbar,
        "menu": .menu,
        "menuItem": .menuItem,
        "keyboard": .keyboard,
        "key": .key,
        "statusBar": .statusBar
    ]

    /// Accepts both `XCUIElementTypeButton` and `button`.
    public static func type(named name: String) -> XCUIElement.ElementType {
        var key = name
        if key.hasPrefix("XCUIElementType") {
            key = String(key.dropFirst("XCUIElementType".count))
            key = key.prefix(1).lowercased() + key.dropFirst()
        }
        return table[key] ?? .any
    }

    private static let reverseTable: [UInt: String] = {
        var result: [UInt: String] = [:]
        for (name, type) in table where name != "any" {
            result[type.rawValue] = "XCUIElementType" + name.prefix(1).uppercased() + name.dropFirst()
        }
        result[XCUIElement.ElementType.any.rawValue] = "XCUIElementTypeAny"
        return result
    }()

    public static func name(for type: XCUIElement.ElementType) -> String {
        reverseTable[type.rawValue] ?? "XCUIElementTypeOther"
    }
}
