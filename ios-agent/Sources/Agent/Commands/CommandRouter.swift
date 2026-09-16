import Foundation
import UIKit
import XCTest

/// Dispatches protocol methods onto handlers.
///
/// Every handler runs on the XCTest main thread (see
/// `AutomationServerTests.testAutomationServer`), because XCUITest APIs must
/// not be driven from arbitrary background queues.
public final class CommandRouter {
    /// How the agent reacts to a dialog that is blocking the app under test.
    ///
    /// iOS shows system interruptions ("Save Password?", notification
    /// permission, ...) at times the test cannot predict. When a policy other
    /// than `.manual` is active the agent dismisses/accepts them itself, which
    /// is both more reliable and cheaper than polling from the host.
    public struct AlertPolicy {
        public enum Mode: String {
            case manual
            case dismiss
            case accept
        }

        public var mode: Mode = .manual
        /// Button labels to prefer, in order, before falling back to `mode`.
        public var buttons: [String] = []
    }

    public private(set) var activeApplication: XCUIApplication?
    public private(set) var activeBundleIdentifier: String?
    public var alertPolicy = AlertPolicy()
    /// How long to let the UI settle before deciding an interaction was
    /// swallowed by a dialog. Only paid when an alert policy is active.
    public var interruptionSettleDelay: TimeInterval = 0.6
    public let startedAt = Date()
    public var stopRequested = false

    private var cachedScreenBounds: CGRect?

    public init() {}

    public func handle(_ request: RequestMessage) -> (ResponseMessage, Data?) {
        let params = ParamsReader(request.params, method: request.method)
        do {
            let outcome = try execute(method: request.method, params: params)
            var response = ResponseMessage.ok(id: request.id, result: outcome.result)
            if let binary = outcome.binary {
                response.binary = BinaryDescriptor(
                    length: binary.count,
                    encoding: "raw",
                    mimeType: outcome.binaryMimeType
                )
            }
            return (response, outcome.binary)
        } catch let error as AgentError {
            AgentLogger.error("\(request.method) failed: \(error.code.rawValue) \(error.message)")
            return (ResponseMessage.failure(id: request.id, error: error), nil)
        } catch {
            AgentLogger.error("\(request.method) crashed: \(error)")
            return (ResponseMessage.failure(id: request.id, error: .internalError(error)), nil)
        }
    }

    private func execute(method: String, params: ParamsReader) throws -> CommandOutcome {
        switch method {
        // session
        case "session.ping": return try ping(params)
        case "session.info": return try info(params)
        case "session.stop": return try stopSession(params)
        case "session.setAlertPolicy": return try setAlertPolicy(params)

        // app
        case "app.launch": return try launchApp(params)
        case "app.terminate": return try terminateApp(params)
        case "app.activate": return try activateApp(params)
        case "app.state": return try appState(params)

        // element
        case "element.find": return try findElement(params)
        case "element.findAll": return try findElements(params)
        case "element.exists": return try elementExists(params)
        case "element.getAttributes": return try elementAttributes(params)
        case "element.tap": return try tapElement(params)
        case "element.longPress": return try longPressElement(params)
        case "element.typeText": return try typeText(params)
        case "element.clear": return try clearElement(params)
        case "element.waitFor": return try waitForElement(params)

        // gesture
        case "gesture.tap": return try tapCoordinate(params)
        case "gesture.longPress": return try longPressCoordinate(params)
        case "gesture.swipe": return try swipe(params)
        case "gesture.drag": return try drag(params)

        // screen
        case "screen.screenshot": return try screenshot(params)
        case "screen.snapshot": return try snapshot(params)

        // alert
        case "alert.accept": return try acceptAlert(params)
        case "alert.dismiss": return try dismissAlert(params)
        case "alert.text": return try alertText(params)
        case "alert.info": return try alertInfo(params)

        // device
        case "device.orientation": return try orientation(params)

        default:
            throw AgentError(.unknownMethod, "Unknown method '\(method)'")
        }
    }

    // MARK: - Shared state

    func setActiveApplication(_ application: XCUIApplication, bundleIdentifier: String) {
        activeApplication = application
        activeBundleIdentifier = bundleIdentifier
    }

    func requireApplication() throws -> XCUIApplication {
        guard let application = activeApplication else {
            throw AgentError(.noActiveApp, "No active application; call app.launch first")
        }
        return application
    }

    func resolver() throws -> ElementResolver {
        ElementResolver(application: try requireApplication())
    }

    /// Screen bounds in points. Cached because the only reliable public way to
    /// obtain it is through a screenshot.
    func screenBounds() -> CGRect {
        if let cachedScreenBounds { return cachedScreenBounds }
        let size = XCUIScreen.main.screenshot().image.size
        let bounds = CGRect(origin: .zero, size: size)
        cachedScreenBounds = bounds
        return bounds
    }

    func deviceDescriptor() -> DeviceDescriptor {
        let device = UIDevice.current
        let bounds = screenBounds()
        return DeviceDescriptor(
            name: device.name,
            iosVersion: device.systemVersion,
            model: device.model,
            udid: ProcessInfo.processInfo.environment["SIMULATOR_UDID"],
            isSimulator: isSimulator,
            screen: ScreenDescriptor(
                width: Double(bounds.width),
                height: Double(bounds.height),
                scale: Double(UIScreen.main.scale)
            )
        )
    }

    var isSimulator: Bool {
        ProcessInfo.processInfo.environment["SIMULATOR_UDID"] != nil
    }
}
