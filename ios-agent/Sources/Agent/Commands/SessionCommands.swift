import Foundation
import UIKit
import XCTest

// MARK: - session.* and app.*

extension CommandRouter {
    func ping(_ params: ParamsReader) throws -> CommandOutcome {
        CommandOutcome(result: .object([
            "pong": .bool(true),
            "agentVersion": .string(SandstormProtocol.agentVersion),
            "timestamp": .number(Date().timeIntervalSince1970)
        ]))
    }

    func info(_ params: ParamsReader) throws -> CommandOutcome {
        let device = deviceDescriptor()
        return CommandOutcome(result: .object([
            "agentVersion": .string(SandstormProtocol.agentVersion),
            "protocolVersion": .from(SandstormProtocol.version),
            "uptime": .number(Date().timeIntervalSince(startedAt)),
            "activeBundleId": .from(activeBundleIdentifier),
            "device": .object([
                "name": .string(device.name),
                "iosVersion": .string(device.iosVersion),
                "model": .string(device.model),
                "isSimulator": .bool(device.isSimulator),
                "screen": .object([
                    "width": .number(device.screen.width),
                    "height": .number(device.screen.height),
                    "scale": .number(device.screen.scale)
                ])
            ])
        ]))
    }

    func stopSession(_ params: ParamsReader) throws -> CommandOutcome {
        stopRequested = true
        return CommandOutcome(result: .object(["stopping": .bool(true)]))
    }

    func launchApp(_ params: ParamsReader) throws -> CommandOutcome {
        let bundleId = try params.requiredString("bundleId")
        let application = XCUIApplication(bundleIdentifier: bundleId)

        if let arguments = params.raw("arguments")?.arrayValue {
            application.launchArguments = arguments.compactMap { $0.stringValue }
        }
        if let environment = params.raw("environment")?.objectValue {
            application.launchEnvironment = environment.compactMapValues { $0.stringValue }
        }

        let relaunch = params.bool("relaunch") ?? false
        let timeout = params.timeout(default: 30)

        // `XCUIApplication.launch()` always terminates a running app first, so
        // it would throw away an existing session. When the caller did not ask
        // for a relaunch, attach to the running instance instead.
        if !relaunch, application.state != .notRunning {
            if application.state != .runningForeground {
                application.activate()
            }
            guard application.wait(for: .runningForeground, timeout: timeout) else {
                throw AgentError(
                    .appLaunchFailed,
                    "Application '\(bundleId)' did not reach the foreground",
                    details: .object(["state": .from(Int(application.state.rawValue))])
                )
            }
            setActiveApplication(application, bundleIdentifier: bundleId)
            return CommandOutcome(result: .object([
                "bundleId": .string(bundleId),
                "state": .from(Int(application.state.rawValue)),
                "attached": .bool(true)
            ]))
        }

        if relaunch, application.state != .notRunning {
            application.terminate()
        }

        application.launch()

        guard application.wait(for: .runningForeground, timeout: timeout) else {
            throw AgentError(
                .appLaunchFailed,
                "Application '\(bundleId)' did not reach the foreground",
                details: .object(["state": .from(Int(application.state.rawValue))])
            )
        }

        setActiveApplication(application, bundleIdentifier: bundleId)
        return CommandOutcome(result: .object([
            "bundleId": .string(bundleId),
            "state": .from(Int(application.state.rawValue))
        ]))
    }

    func activateApp(_ params: ParamsReader) throws -> CommandOutcome {
        let bundleId = params.string("bundleId") ?? activeBundleIdentifier
        guard let bundleId else {
            throw AgentError.invalidParams("`bundleId` is required for app.activate")
        }
        let application = XCUIApplication(bundleIdentifier: bundleId)
        application.activate()
        setActiveApplication(application, bundleIdentifier: bundleId)
        return CommandOutcome(result: .object(["state": .from(Int(application.state.rawValue))]))
    }

    func terminateApp(_ params: ParamsReader) throws -> CommandOutcome {
        let bundleId = params.string("bundleId") ?? activeBundleIdentifier
        guard let bundleId else {
            throw AgentError.invalidParams("`bundleId` is required for app.terminate")
        }
        XCUIApplication(bundleIdentifier: bundleId).terminate()
        return CommandOutcome(result: .object(["bundleId": .string(bundleId)]))
    }

    func appState(_ params: ParamsReader) throws -> CommandOutcome {
        let bundleId = params.string("bundleId") ?? activeBundleIdentifier
        guard let bundleId else {
            throw AgentError.invalidParams("`bundleId` is required for app.state")
        }
        let state = XCUIApplication(bundleIdentifier: bundleId).state
        return CommandOutcome(result: .object([
            "bundleId": .string(bundleId),
            "state": .from(Int(state.rawValue)),
            "running": .bool(state == .runningForeground || state == .runningBackground)
        ]))
    }
}
