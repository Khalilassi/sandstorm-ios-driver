import Foundation
import XCTest

// MARK: - element.*

extension CommandRouter {
    func findElement(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        let element = try resolver().requireElement(for: selector, timeout: params.timeout(default: 0))
        return CommandOutcome(result: attributes(of: element))
    }

    func findElements(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        let query = try resolver().query(for: selector)
        let limit = params.int("limit") ?? 50
        // `count` is a single IPC round trip; allElementsBoundByIndex is another.
        let elements = query.allElementsBoundByIndex.prefix(limit)
        return CommandOutcome(result: .object([
            "count": .from(elements.count),
            "elements": .array(elements.map { attributes(of: $0) })
        ]))
    }

    func elementExists(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        let element = try resolver().element(for: selector)
        let timeout = params.timeout(default: 0)
        let exists = timeout > 0 ? element.waitForExistence(timeout: timeout) : element.exists
        return CommandOutcome(result: .object(["exists": .bool(exists)]))
    }

    func elementAttributes(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        let element = try resolver().requireElement(for: selector, timeout: params.timeout(default: 0))
        return CommandOutcome(result: attributes(of: element, includeHittable: true))
    }

    func tapElement(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        try withInterruptionRecovery {
            let element = try resolver().requireElement(for: selector, timeout: params.timeout(default: 5))
            try requireInteractable(element, selector: selector)
            element.tap()
        }
        return CommandOutcome()
    }

    func longPressElement(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        let duration = params.double("duration") ?? 1.0
        try withInterruptionRecovery {
            let element = try resolver().requireElement(for: selector, timeout: params.timeout(default: 5))
            try requireInteractable(element, selector: selector)
            element.press(forDuration: duration)
        }
        return CommandOutcome()
    }

    func typeText(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        let text = try params.requiredString("text")
        let shouldClear = params.bool("clear") ?? false
        try withInterruptionRecovery {
            let element = try resolver().requireElement(for: selector, timeout: params.timeout(default: 5))
            try requireInteractable(element, selector: selector)

            if shouldClear {
                clearText(of: element)
            }
            if !element.hasFocus {
                element.tap()
            }
            element.typeText(text)
        }
        return CommandOutcome()
    }

    func clearElement(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        try withInterruptionRecovery {
            let element = try resolver().requireElement(for: selector, timeout: params.timeout(default: 5))
            try requireInteractable(element, selector: selector)
            clearText(of: element)
        }
        return CommandOutcome()
    }

    /// Runs an interaction, clearing any dialog that is blocking it.
    ///
    /// Three things happen, all skipped while the policy is `.manual` so the
    /// default path costs nothing:
    ///
    /// 1. a dialog already on screen is cleared first, because it would swallow
    ///    this interaction;
    /// 2. a failure caused by a dialog is retried once;
    /// 3. a dialog that appears *during* the interaction is cleared and the
    ///    interaction is replayed — iOS delivers the touch to the dialog, not to
    ///    the app, so the action silently did nothing. This mirrors what
    ///    XCTest's own UI interruption monitor does.
    func withInterruptionRecovery(_ body: () throws -> Void) throws {
        handleInterruptionIfNeeded()
        do {
            try body()
        } catch let error as AgentError {
            guard error.code == .elementNotFound || error.code == .elementNotInteractable,
                  handleInterruptionIfNeeded() != nil else {
                throw error
            }
            try body()
            return
        }

        guard alertPolicy.mode != .manual else { return }
        // Dialogs are presented asynchronously; give the UI a moment to settle
        // before deciding that the interaction landed.
        _ = RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(interruptionSettleDelay))
        guard handleInterruptionIfNeeded() != nil else { return }

        do {
            AgentLogger.info("Replaying interaction that may have been swallowed by an interruption")
            try body()
        } catch let error as AgentError where error.code == .elementNotFound {
            // The target is gone, so the original interaction did land and the
            // dialog was a consequence of it rather than the cause of a lost
            // touch. Nothing to replay.
            AgentLogger.info("Interaction had already taken effect; no replay needed")
        }
    }

    /// Waits are executed **inside the agent** so a 10 second wait costs one
    /// round trip instead of dozens of polling requests over USB.
    ///
    /// The condition is polled directly instead of through
    /// `XCTNSPredicateExpectation`: the expectation only re-evaluates on its own
    /// schedule and needs an uninterrupted `XCTWaiter` run, which does not mix
    /// with the agent's own run-loop pump — it reported timeouts for elements
    /// that demonstrably existed. Each poll is a query inside the app process,
    /// so no USB traffic is involved.
    func waitForElement(_ params: ParamsReader) throws -> CommandOutcome {
        let selector = try params.requiredSelector()
        let state = params.string("state") ?? "visible"
        let timeout = params.timeout(default: 10)
        let element = try resolver().element(for: selector)

        let satisfied: (XCUIElement) -> Bool
        switch state {
        case "exists":
            satisfied = { $0.exists }
        case "not_exists":
            satisfied = { !$0.exists }
        case "visible":
            satisfied = { $0.exists && $0.isHittable }
        case "not_visible":
            satisfied = { !$0.exists || !$0.isHittable }
        case "enabled":
            satisfied = { $0.exists && $0.isEnabled }
        default:
            throw AgentError.invalidParams("Unsupported wait state '\(state)'")
        }

        let deadline = Date().addingTimeInterval(timeout)
        var handledInterruption = false
        repeat {
            if satisfied(element) {
                return CommandOutcome(result: .object([
                    "state": .string(state),
                    "handledInterruption": .bool(handledInterruption)
                ]))
            }
            if handleInterruptionIfNeeded() != nil {
                handledInterruption = true
                continue
            }
            _ = RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.2))
        } while Date() < deadline

        throw AgentError(
            .timeout,
            "Timed out after \(timeout)s waiting for state '\(state)' on element (\(selector.description))"
        )
    }

    // MARK: - Helpers

    func attributes(of element: XCUIElement, includeHittable: Bool = false) -> JSONValue {
        guard element.exists else { return .object(["exists": .bool(false)]) }
        let frame = element.frame
        var object: [String: JSONValue] = [
            "exists": .bool(true),
            "type": .string(ElementTypeMapper.name(for: element.elementType)),
            "identifier": .string(element.identifier),
            "label": .string(element.label),
            "value": stringify(element.value),
            "title": .string(element.title),
            "placeholder": .from(element.placeholderValue),
            "enabled": .bool(element.isEnabled),
            "selected": .bool(element.isSelected),
            "frame": .object([
                "x": .number(Double(frame.origin.x)),
                "y": .number(Double(frame.origin.y)),
                "width": .number(Double(frame.size.width)),
                "height": .number(Double(frame.size.height))
            ])
        ]
        if includeHittable {
            object["hittable"] = .bool(element.isHittable)
        }
        return .object(object)
    }

    private func requireInteractable(_ element: XCUIElement, selector: ElementSelector) throws {
        guard element.isEnabled else {
            throw AgentError(
                .elementNotInteractable,
                "Element is disabled (\(selector.description))"
            )
        }
    }

    private func clearText(of element: XCUIElement) {
        guard let current = element.value as? String, !current.isEmpty else { return }
        if !element.hasFocus {
            element.tap()
        }
        let deletes = String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count)
        element.typeText(deletes)
    }

    private func stringify(_ value: Any?) -> JSONValue {
        switch value {
        case .none: return .null
        case let string as String: return .string(string)
        case let bool as Bool: return .bool(bool)
        case let number as NSNumber: return .number(number.doubleValue)
        case let other?: return .string(String(describing: other))
        }
    }
}
