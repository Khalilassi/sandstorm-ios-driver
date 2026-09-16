"""Blocking TCP client that speaks the Sandstorm frame protocol."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Any, Mapping

from .errors import (
    IOSAgentConnectionError,
    IOSCommandTimeout,
    IOSProtocolError,
    IOSSessionLost,
    error_from_payload,
)
from .protocol.framing import BINARY_FRAME, JSON_FRAME, FrameReader, encode_frame
from .protocol.messages import (
    PROTOCOL_VERSION,
    Command,
    Handshake,
    Response,
    build_handshake_request,
)

logger = logging.getLogger("sandstorm.transport")

DEFAULT_COMMAND_TIMEOUT = 30.0
DEFAULT_CONNECT_TIMEOUT = 15.0


class IOSControllerClient:
    """Low level connection to a running agent.

    Responsibilities: handshake, request/response correlation, binary
    attachments, command timeouts, reconnection and health checks. Everything
    above this class (``IOSDevice`` and friends) is pure ergonomics.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8433,
        *,
        token: str | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        max_retries: int = 2,
        client_version: str = "0.1.0",
    ) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.max_retries = max_retries
        self.client_version = client_version

        self._socket: socket.socket | None = None
        self._reader: FrameReader | None = None
        self._lock = threading.RLock()
        self._next_id = 0
        self._handshake: Handshake | None = None

    # -- Lifecycle -----------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._socket is not None

    @property
    def handshake(self) -> Handshake:
        if self._handshake is None:
            raise IOSSessionLost("Not connected to an agent")
        return self._handshake

    def connect(self, *, retries: int = 0, retry_delay: float = 0.5) -> Handshake:
        """Opens the socket and performs the versioned handshake."""
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with self._lock:
                    self._open_socket()
                    self._handshake = self._perform_handshake()
                logger.info(
                    "Connected to agent %s (protocol v%s) on %s:%s",
                    self._handshake.agent_version,
                    self._handshake.protocol_version,
                    self.host,
                    self.port,
                )
                return self._handshake
            except (IOSAgentConnectionError, OSError) as exc:
                last_error = exc
                self.close()
                if attempt < retries:
                    time.sleep(retry_delay)
        raise IOSAgentConnectionError(
            f"Could not connect to the agent at {self.host}:{self.port}: {last_error}"
        )

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:  # pragma: no cover - best effort
                    pass
            self._socket = None
            self._reader = None
            self._handshake = None

    def __enter__(self) -> "IOSControllerClient":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- Commands ------------------------------------------------------------

    def invoke(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        retry: bool = True,
    ) -> Response:
        """Sends a command and returns the (successful) response.

        Raises the mapped :class:`~sandstorm_ios.errors.IOSError` subclass when
        the agent reports a failure. Set ``retry=False`` for commands whose
        side effect makes a reconnect pointless (``session.stop``).
        """
        attempts = self.max_retries + 1 if retry else 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = self._invoke_once(method, params or {}, timeout)
                if response.success:
                    return response
                raise error_from_payload(response.error or {})
            except (IOSAgentConnectionError, IOSSessionLost) as exc:
                last_error = exc
                logger.warning("Command %s failed (%s); reconnecting", method, exc)
                self.close()
                if attempt < attempts - 1:
                    try:
                        self.connect(retries=1)
                    except IOSAgentConnectionError:
                        continue
        raise IOSSessionLost(f"Lost the agent session while calling {method}: {last_error}")

    def ping(self, *, timeout: float = 5.0) -> float:
        """Round-trip health check. Returns the latency in seconds."""
        started = time.perf_counter()
        self.invoke("session.ping", timeout=timeout)
        return time.perf_counter() - started

    def is_healthy(self) -> bool:
        try:
            self.ping(timeout=3.0)
            return True
        except Exception:  # noqa: BLE001 - health checks never raise
            return False

    # -- Internals -----------------------------------------------------------

    def _open_socket(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._socket = sock
        self._reader = FrameReader(sock)

    def _perform_handshake(self) -> Handshake:
        assert self._socket is not None and self._reader is not None
        payload = build_handshake_request(self.token, self.client_version)
        self._send_json(payload)
        frame_type, data = self._reader.read_frame()
        if frame_type != JSON_FRAME:
            raise IOSProtocolError("Agent answered the handshake with a binary frame")

        message = json.loads(data)
        if message.get("success") is False:
            raise error_from_payload(message.get("error") or {})

        handshake = Handshake.from_wire(message)
        if handshake.protocol_version != PROTOCOL_VERSION:
            raise IOSProtocolError(
                f"Protocol mismatch: agent speaks v{handshake.protocol_version}, "
                f"client speaks v{PROTOCOL_VERSION}. Rebuild the agent."
            )
        return handshake

    def _invoke_once(
        self,
        method: str,
        params: Mapping[str, Any],
        timeout: float | None,
    ) -> Response:
        with self._lock:
            if self._socket is None or self._reader is None:
                raise IOSSessionLost("Not connected to an agent")

            self._next_id += 1
            command = Command(id=self._next_id, method=method, params=params)
            effective_timeout = timeout if timeout is not None else self.command_timeout
            self._socket.settimeout(effective_timeout)

            logger.debug("-> %s %s", command.method, command.params)
            self._send_json(command.to_wire())

            deadline = time.monotonic() + effective_timeout
            while True:
                frame_type, data = self._reader.read_frame()
                if frame_type != JSON_FRAME:
                    # An orphan binary frame means we lost sync with the agent.
                    raise IOSProtocolError("Unexpected binary frame")

                message = json.loads(data)
                binary: bytes | None = None
                descriptor = message.get("binary")
                if descriptor:
                    binary_type, binary = self._reader.read_frame()
                    if binary_type != BINARY_FRAME:
                        raise IOSProtocolError("Expected a binary attachment frame")
                    if len(binary) != int(descriptor.get("length", len(binary))):
                        raise IOSProtocolError("Truncated binary attachment")

                response = Response.from_wire(message, binary)
                if response.id == command.id:
                    logger.debug("<- %s success=%s", command.method, response.success)
                    return response

                logger.debug("Discarding stale response id=%s", response.id)
                if time.monotonic() > deadline:
                    raise IOSCommandTimeout(
                        f"{method} timed out after {effective_timeout}s waiting for a matching reply"
                    )

    def _send_json(self, payload: Mapping[str, Any]) -> None:
        assert self._socket is not None
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            self._socket.sendall(encode_frame(JSON_FRAME, data))
        except socket.timeout as exc:
            raise IOSCommandTimeout("Timed out writing to the agent") from exc
        except OSError as exc:
            raise IOSAgentConnectionError(f"Failed to write to the agent: {exc}") from exc
