import Foundation
import XCTest

/// The Sandstorm on-device agent.
///
/// Apple constraint
/// ----------------
/// There is no supported way to synthesize touch events on iOS outside of an
/// XCTest process. The only sanctioned entry point is a UI test bundle hosted
/// by a signed `*-Runner.app`, launched by `xcodebuild`/`XCTestBootstrap`.
/// Therefore the agent is a single test method that simply never returns until
/// the controller asks it to stop. This is the same constraint WebDriverAgent
/// lives under; we just refuse to speak WebDriver.
final class AutomationServerTests: XCTestCase {

    override func setUpWithError() throws {
        // A crashed assertion must not end the long lived session.
        continueAfterFailure = true
    }

    func testAutomationServer() throws {
        let configuration = AgentConfiguration()
        let router = CommandRouter()
        let server = CommandServer(configuration: configuration)
        server.deviceDescriptorProvider = { router.deviceDescriptor() }

        try server.start()
        AgentLogger.info("Sandstorm agent \(SandstormProtocol.agentVersion) listening on 127.0.0.1:\(configuration.port)")

        var lastActivity = Date()

        while !server.shouldStop && !router.stopRequested {
            // Pump the run loop so Network.framework callbacks are delivered
            // while we stay on the XCTest thread, which is the only thread
            // allowed to drive XCUITest APIs.
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.02))

            while let pending = server.dequeue() {
                lastActivity = Date()
                let (response, binary) = router.handle(pending.request)
                pending.connection.send(response: response, binary: binary)
            }

            if configuration.idleShutdownTimeout > 0,
               lastActivity.addingTimeInterval(configuration.idleShutdownTimeout) < Date() {
                AgentLogger.info("Idle timeout reached, shutting down")
                break
            }
        }

        server.stop()
        AgentLogger.info("SANDSTORM_AGENT_STOPPED")
    }
}
