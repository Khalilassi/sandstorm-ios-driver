import Foundation
import XCTest

/// Turns an `ElementSelector` into an `XCUIElement` / `XCUIElementQuery`.
///
/// All matching is expressed as a single `NSPredicate` applied to one
/// descendants query so that XCTest evaluates it inside the target application
/// in one round trip instead of walking the tree from the runner process.
public struct ElementResolver {
    private let application: XCUIApplication

    public init(application: XCUIApplication) {
        self.application = application
    }

    public func query(for selector: ElementSelector) -> XCUIElementQuery {
        var root: XCUIElementQuery
        if case .selector(let parentSelector)? = selector.parent {
            root = query(for: parentSelector).element.descendants(matching: elementType(of: selector))
        } else {
            root = application.descendants(matching: elementType(of: selector))
        }
        if let predicate = selector.buildPredicate() {
            root = root.matching(predicate)
        }
        return root
    }

    public func element(for selector: ElementSelector) -> XCUIElement {
        let query = query(for: selector)
        if let index = selector.index {
            return query.element(boundBy: index)
        }
        return query.firstMatch
    }

    /// Resolves and asserts existence, converting the miss into a typed error.
    public func requireElement(for selector: ElementSelector, timeout: TimeInterval = 0) throws -> XCUIElement {
        let element = self.element(for: selector)
        if element.exists { return element }
        if timeout > 0, element.waitForExistence(timeout: timeout) { return element }
        throw AgentError.elementNotFound(selector.description)
    }

    private func elementType(of selector: ElementSelector) -> XCUIElement.ElementType {
        guard let name = selector.elementType else { return .any }
        return ElementTypeMapper.type(named: name)
    }
}
