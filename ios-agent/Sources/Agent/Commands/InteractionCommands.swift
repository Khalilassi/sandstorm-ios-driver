import Foundation
import UIKit
import XCTest

// MARK: - gesture.*, screen.*, alert.*, device.*

extension CommandRouter {
    // MARK: gesture

    func tapCoordinate(_ params: ParamsReader) throws -> CommandOutcome {
        let point = try params.point("at")
        try coordinate(at: point).tap()
        return CommandOutcome()
    }

    func longPressCoordinate(_ params: ParamsReader) throws -> CommandOutcome {
        let point = try params.point("at")
        try coordinate(at: point).press(forDuration: params.double("duration") ?? 1.0)
        return CommandOutcome()
    }

    func swipe(_ params: ParamsReader) throws -> CommandOutcome {
        try performDrag(params, defaultDuration: 0.1)
    }

    func drag(_ params: ParamsReader) throws -> CommandOutcome {
        try performDrag(params, defaultDuration: 0.8)
    }

    private func performDrag(_ params: ParamsReader, defaultDuration: Double) throws -> CommandOutcome {
        let from = try params.point("from")
        let to = try params.point("to")
        let duration = params.double("duration") ?? defaultDuration
        let start = try coordinate(at: from)
        let end = try coordinate(at: to)
        start.press(forDuration: duration, thenDragTo: end)
        return CommandOutcome()
    }

    /// Coordinates are normalized (0..1) relative to the active application's
    /// frame, which keeps scripts resolution independent.
    private func coordinate(at point: CGPoint) throws -> XCUICoordinate {
        let application = try requireApplication()
        guard (0...1).contains(point.x), (0...1).contains(point.y) else {
            throw AgentError.invalidParams("Coordinates must be normalized between 0 and 1")
        }
        return application.coordinate(withNormalizedOffset: CGVector(dx: point.x, dy: point.y))
    }

    // MARK: screen

    func screenshot(_ params: ParamsReader) throws -> CommandOutcome {
        let screenshot: XCUIScreenshot
        if params.bool("appOnly") ?? false {
            screenshot = try requireApplication().screenshot()
        } else {
            screenshot = XCUIScreen.main.screenshot()
        }

        let image = screenshot.image
        let scale = params.double("scale") ?? 1.0
        let quality = params.double("quality")

        let rendered = scale < 1.0 ? resize(image, by: scale) : image
        let data: Data
        let mimeType: String
        if let quality {
            guard let jpeg = rendered.jpegData(compressionQuality: CGFloat(quality)) else {
                throw AgentError(.internalError, "Failed to encode JPEG screenshot")
            }
            data = jpeg
            mimeType = "image/jpeg"
        } else {
            guard let png = rendered.pngData() else {
                throw AgentError(.internalError, "Failed to encode PNG screenshot")
            }
            data = png
            mimeType = "image/png"
        }

        return CommandOutcome(
            result: .object([
                "width": .number(Double(rendered.size.width)),
                "height": .number(Double(rendered.size.height)),
                "scale": .number(Double(rendered.scale)),
                "mimeType": .string(mimeType),
                "length": .from(data.count)
            ]),
            binary: data,
            binaryMimeType: mimeType
        )
    }

    private func resize(_ image: UIImage, by scale: Double) -> UIImage {
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
    }

    func snapshot(_ params: ParamsReader) throws -> CommandOutcome {
        let application = try requireApplication()
        let root: XCUIElement
        if let selectorJSON = params.raw("selector") {
            let selector = try ElementSelector(json: selectorJSON)
            root = try ElementResolver(application: application).requireElement(for: selector)
        } else {
            root = application
        }

        let captured: XCUIElementSnapshot
        do {
            captured = try root.snapshot()
        } catch {
            throw AgentError(.snapshotFailed, "Failed to capture accessibility snapshot: \(error)")
        }

        let options = SnapshotSerializer.Options(
            maxDepth: params.int("maxDepth") ?? 60,
            includeInvisible: params.bool("includeInvisible") ?? true,
            screenBounds: screenBounds()
        )
        let tree = SnapshotSerializer.serialize(captured, options: options)
        let bounds = screenBounds()
        return CommandOutcome(result: .object([
            "tree": tree,
            "screen": .object([
                "width": .number(Double(bounds.width)),
                "height": .number(Double(bounds.height))
            ])
        ]))
    }

    // MARK: alert

    func acceptAlert(_ params: ParamsReader) throws -> CommandOutcome {
        let alert = try currentAlert()
        let preferred = params.string("button")
        let button = preferred.map { alert.buttons[$0] } ?? alert.buttons.element(boundBy: alert.buttons.count - 1)
        guard button.exists else {
            throw AgentError(.alertNotFound, "Alert accept button not found")
        }
        button.tap()
        return CommandOutcome()
    }

    func dismissAlert(_ params: ParamsReader) throws -> CommandOutcome {
        let alert = try currentAlert()
        let preferred = params.string("button")
        let button = preferred.map { alert.buttons[$0] } ?? alert.buttons.firstMatch
        guard button.exists else {
            throw AgentError(.alertNotFound, "Alert dismiss button not found")
        }
        button.tap()
        return CommandOutcome()
    }

    func alertText(_ params: ParamsReader) throws -> CommandOutcome {
        let alert = try currentAlert()
        return CommandOutcome(result: .object(describe(alert)))
    }

    /// Non-throwing probe so callers can branch on an optional dialog without
    /// paying for an exception round trip.
    func alertInfo(_ params: ParamsReader) throws -> CommandOutcome {
        guard let alert = findAlert() else {
            return CommandOutcome(result: .object(["present": .bool(false)]))
        }
        var payload = describe(alert)
        payload["present"] = .bool(true)
        return CommandOutcome(result: .object(payload))
    }

    func setAlertPolicy(_ params: ParamsReader) throws -> CommandOutcome {
        let raw = params.string("policy") ?? "manual"
        guard let mode = AlertPolicy.Mode(rawValue: raw) else {
            throw AgentError.invalidParams("Unknown alert policy '\(raw)'")
        }
        var policy = AlertPolicy(mode: mode)
        if case .array(let buttons) = params.raw("buttons") ?? .null {
            policy.buttons = buttons.compactMap { if case .string(let s) = $0 { return s } else { return nil } }
        }
        alertPolicy = policy
        AgentLogger.info("Alert policy set to \(mode.rawValue) buttons=\(policy.buttons)")
        return CommandOutcome(result: .object([
            "policy": .string(mode.rawValue),
            "buttons": .array(policy.buttons.map { .string($0) })
        ]))
    }

    /// Dismisses/accepts a blocking dialog according to `alertPolicy`.
    ///
    /// Returns the label of the button that was tapped, or `nil` when nothing
    /// was handled. Cheap to call: a single `exists` round trip when no dialog
    /// is on screen.
    @discardableResult
    func handleInterruptionIfNeeded() -> String? {
        guard alertPolicy.mode != .manual, let alert = findAlert() else { return nil }

        let labels = alert.buttons.allElementsBoundByIndex.map { $0.label }
        guard !labels.isEmpty else { return nil }

        let chosen = alertPolicy.buttons.first { labels.contains($0) }
            ?? (alertPolicy.mode == .accept ? labels[labels.count - 1] : labels[0])

        let button = alert.buttons[chosen]
        guard button.exists else { return nil }
        button.tap()
        AgentLogger.info("Auto-handled interruption; tapped '\(chosen)'")
        return chosen
    }

    private func describe(_ alert: XCUIElement) -> [String: JSONValue] {
        let texts = alert.staticTexts.allElementsBoundByIndex.map { $0.label }
        let buttons = alert.buttons.allElementsBoundByIndex.map { $0.label }
        return [
            "text": .string(texts.joined(separator: "\n")),
            "buttons": .array(buttons.map { .string($0) })
        ]
    }

    /// System permission dialogs belong to SpringBoard, not to the app under
    /// test, so both element trees are checked. iOS also renders some system
    /// prompts (keychain "Save Password?", share sheets) as sheets rather than
    /// alerts, so both element types are considered.
    private func findAlert() -> XCUIElement? {
        guard let application = try? requireApplication() else { return nil }
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let candidates = [
            application.alerts.firstMatch,
            springboard.alerts.firstMatch,
            application.sheets.firstMatch,
            springboard.sheets.firstMatch
        ]
        return candidates.first { $0.exists }
    }

    private func currentAlert() throws -> XCUIElement {
        guard let alert = findAlert() else {
            throw AgentError(.alertNotFound, "No alert is currently presented")
        }
        return alert
    }

    // MARK: device

    func orientation(_ params: ParamsReader) throws -> CommandOutcome {
        if let requested = params.string("orientation") {
            guard let value = Self.orientations[requested] else {
                throw AgentError.invalidParams("Unknown orientation '\(requested)'")
            }
            XCUIDevice.shared.orientation = value
        }
        let current = XCUIDevice.shared.orientation
        let name = Self.orientations.first { $0.value == current }?.key ?? "unknown"
        return CommandOutcome(result: .object(["orientation": .string(name)]))
    }

    private static let orientations: [String: UIDeviceOrientation] = [
        "portrait": .portrait,
        "portraitUpsideDown": .portraitUpsideDown,
        "landscapeLeft": .landscapeLeft,
        "landscapeRight": .landscapeRight,
        "faceUp": .faceUp,
        "faceDown": .faceDown
    ]
}
