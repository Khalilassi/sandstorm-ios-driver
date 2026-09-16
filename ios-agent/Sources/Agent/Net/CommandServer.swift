import Foundation
import Network

/// A single command pulled off the wire, waiting to be executed on the XCTest
/// main thread.
public struct PendingCommand {
    public let request: RequestMessage
    public let connection: AgentConnection
}

/// Wraps an `NWConnection` and owns its frame parsing state.
public final class AgentConnection {
    private let connection: NWConnection
    private let codec = FrameCodec()
    private let encoder = JSONEncoder()
    private let queue: DispatchQueue
    private let lock = NSLock()

    public private(set) var isHandshakeComplete = false
    public private(set) var sessionId: String = ""

    public var onFrame: ((Frame, AgentConnection) -> Void)?
    public var onClose: ((AgentConnection) -> Void)?

    init(connection: NWConnection, queue: DispatchQueue) {
        self.connection = connection
        self.queue = queue
        self.encoder.outputFormatting = []
    }

    func start() {
        connection.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            switch state {
            case .failed, .cancelled:
                self.onClose?(self)
            default:
                break
            }
        }
        connection.start(queue: queue)
        receive()
    }

    private func receive() {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 256 * 1024) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let data, !data.isEmpty {
                self.codec.append(data)
                do {
                    while let frame = try self.codec.nextFrame() {
                        self.onFrame?(frame, self)
                    }
                } catch {
                    AgentLogger.error("Frame decoding failed: \(error)")
                    self.close()
                    return
                }
            }
            if isComplete || error != nil {
                self.onClose?(self)
                self.close()
                return
            }
            self.receive()
        }
    }

    func markHandshakeComplete(sessionId: String) {
        lock.lock()
        defer { lock.unlock() }
        isHandshakeComplete = true
        self.sessionId = sessionId
    }

    public func send(frame: Frame) {
        connection.send(content: frame.encoded(), completion: .contentProcessed { error in
            if let error {
                AgentLogger.error("Send failed: \(error)")
            }
        })
    }

    public func sendJSON<T: Encodable>(_ value: T) {
        do {
            let payload = try encoder.encode(value)
            send(frame: Frame(type: .json, payload: payload))
        } catch {
            AgentLogger.error("Encoding failed: \(error)")
        }
    }

    /// Sends a response plus, when present, its trailing binary frame.
    public func send(response: ResponseMessage, binary: Data?) {
        sendJSON(response)
        if let binary {
            send(frame: Frame(type: .binary, payload: binary))
        }
    }

    public func close() {
        connection.cancel()
    }
}

/// Minimal TCP command server. It never speaks HTTP and never exposes
/// WebDriver endpoints; it only reads length prefixed frames.
public final class CommandServer {
    private let configuration: AgentConfiguration
    private let queue = DispatchQueue(label: "com.sandstorm.agent.net")
    private let decoder = JSONDecoder()
    private var listener: NWListener?

    private let pendingLock = NSLock()
    private var pending: [PendingCommand] = []
    private var connections: [AgentConnection] = []

    private(set) var shouldStop = false
    public var deviceDescriptorProvider: (() -> DeviceDescriptor)?

    public init(configuration: AgentConfiguration) {
        self.configuration = configuration
    }

    public func start() throws {
        let parameters = NWParameters.tcp
        parameters.allowLocalEndpointReuse = true

        let listener: NWListener
        if configuration.bindAllInterfaces {
            listener = try NWListener(using: parameters, on: configuration.nwPort)
        } else {
            // Only reachable through the USB tunnel (device) or host loopback
            // (simulator). See docs/SECURITY.md. The port travels with the
            // endpoint, so it must not also be passed to the initializer.
            parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: configuration.nwPort)
            listener = try NWListener(using: parameters)
        }

        let port = configuration.port
        listener.newConnectionHandler = { [weak self] nwConnection in
            self?.accept(nwConnection)
        }
        listener.stateUpdateHandler = { state in
            switch state {
            case .ready:
                AgentLogger.info("SANDSTORM_AGENT_READY port=\(port)")
            case .failed(let error):
                AgentLogger.error("Listener failed: \(error)")
            default:
                break
            }
        }
        listener.start(queue: queue)
        self.listener = listener
    }

    public func stop() {
        shouldStop = true
        connections.forEach { $0.close() }
        listener?.cancel()
    }

    public func requestStop() {
        shouldStop = true
    }

    private func accept(_ nwConnection: NWConnection) {
        let connection = AgentConnection(connection: nwConnection, queue: queue)
        connection.onFrame = { [weak self] frame, conn in
            self?.handle(frame: frame, on: conn)
        }
        connection.onClose = { [weak self] conn in
            self?.remove(conn)
        }
        connections.append(connection)
        connection.start()
        AgentLogger.info("Client connected")
    }

    private func remove(_ connection: AgentConnection) {
        connections.removeAll { $0 === connection }
    }

    private func handle(frame: Frame, on connection: AgentConnection) {
        guard frame.type == .json else {
            AgentLogger.error("Unexpected binary frame from client")
            return
        }

        if !connection.isHandshakeComplete {
            performHandshake(payload: frame.payload, on: connection)
            return
        }

        do {
            let request = try decoder.decode(RequestMessage.self, from: frame.payload)
            pendingLock.lock()
            pending.append(PendingCommand(request: request, connection: connection))
            pendingLock.unlock()
        } catch {
            AgentLogger.error("Malformed request: \(error)")
            connection.sendJSON(ResponseMessage.failure(
                id: -1,
                error: AgentError(.protocolError, "Malformed request payload")
            ))
        }
    }

    private func performHandshake(payload: Data, on connection: AgentConnection) {
        do {
            let handshake = try decoder.decode(HandshakeRequest.self, from: payload)

            guard handshake.protocolVersion == SandstormProtocol.version else {
                throw AgentError(
                    .protocolError,
                    "Unsupported protocol version \(handshake.protocolVersion); agent speaks \(SandstormProtocol.version)"
                )
            }
            guard configuration.isTokenValid(handshake.token) else {
                throw AgentError(.unauthorized, "Invalid or missing session token")
            }

            let sessionId = UUID().uuidString
            connection.markHandshakeComplete(sessionId: sessionId)

            let device = deviceDescriptorProvider?() ?? DeviceDescriptor(
                name: "unknown",
                iosVersion: "unknown",
                model: "unknown",
                udid: nil,
                isSimulator: false,
                screen: ScreenDescriptor(width: 0, height: 0, scale: 1)
            )
            connection.sendJSON(HandshakeResponse(
                protocolVersion: SandstormProtocol.version,
                agentVersion: SandstormProtocol.agentVersion,
                sessionId: sessionId,
                device: device
            ))
            AgentLogger.info("Handshake completed with \(handshake.client)/\(handshake.clientVersion) session=\(sessionId)")
        } catch let error as AgentError {
            connection.sendJSON(ResponseMessage.failure(id: 0, error: error))
            connection.close()
        } catch {
            connection.sendJSON(ResponseMessage.failure(id: 0, error: AgentError(.protocolError, "Malformed handshake")))
            connection.close()
        }
    }

    /// Pops the next queued command. Called from the XCTest thread.
    public func dequeue() -> PendingCommand? {
        pendingLock.lock()
        defer { pendingLock.unlock() }
        return pending.isEmpty ? nil : pending.removeFirst()
    }
}
