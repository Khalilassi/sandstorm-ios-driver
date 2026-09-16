"""Top level entry point of the SDK."""

from __future__ import annotations

import logging
import os
from typing import Any

from ..errors import IOSAgentNotRunning
from ..protocol.messages import DeviceInfo
from ..transport import IOSControllerClient
from .application import IOSApplication
from .session import IOSSession

logger = logging.getLogger("sandstorm.device")

DEFAULT_AGENT_PORT = 8433


class IOSDevice:
    """A connected iPhone or simulator running the Sandstorm agent.

    The agent must already be running; start it with::

        sandstorm ios start --udid <UDID>

    The controller prints the host/port/token it allocated, or you can let the
    SDK read them from ``SANDSTORM_AGENT_HOST`` / ``SANDSTORM_AGENT_PORT`` /
    ``SANDSTORM_TOKEN``.
    """

    def __init__(
        self,
        udid: str | None = None,
        *,
        host: str | None = None,
        port: int | None = None,
        token: str | None = None,
        command_timeout: float = 30.0,
        default_timeout: float = 10.0,
    ) -> None:
        self.udid = udid
        self.host = host or os.environ.get("SANDSTORM_AGENT_HOST", "127.0.0.1")
        self.port = port or int(os.environ.get("SANDSTORM_AGENT_PORT", DEFAULT_AGENT_PORT))
        self.token = token if token is not None else os.environ.get("SANDSTORM_TOKEN")
        self.default_timeout = default_timeout

        self._client = IOSControllerClient(
            self.host,
            self.port,
            token=self.token,
            command_timeout=command_timeout,
        )
        self._session: IOSSession | None = None

    # -- Lifecycle -----------------------------------------------------------

    def connect(self, *, retries: int = 10, retry_delay: float = 1.0) -> "IOSDevice":
        """Connects to the agent, retrying while it boots."""
        try:
            self._client.connect(retries=retries, retry_delay=retry_delay)
        except Exception as exc:
            raise IOSAgentNotRunning(
                f"No Sandstorm agent answered on {self.host}:{self.port}. "
                "Start it with `sandstorm ios start --udid <UDID>`."
            ) from exc
        self._session = IOSSession(self._client)
        logger.info(
            "Connected to %s (iOS %s), agent %s",
            self.info.name,
            self.info.ios_version,
            self._session.agent_version,
        )
        return self

    def disconnect(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> "IOSDevice":
        return self.connect()

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    # -- Accessors -----------------------------------------------------------

    @property
    def session(self) -> IOSSession:
        if self._session is None:
            raise IOSAgentNotRunning("Device is not connected; call connect() first")
        return self._session

    @property
    def info(self) -> DeviceInfo:
        return self.session.device_info

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    def app(self, bundle_id: str) -> IOSApplication:
        return IOSApplication(self.session, bundle_id, default_timeout=self.default_timeout)

    # -- Health --------------------------------------------------------------

    def ping(self) -> float:
        return self.session.ping()

    def health(self) -> dict[str, Any]:
        result = dict(self.session.result("session.info"))
        result["latency"] = self.ping()
        return result

    def stop_agent(self) -> None:
        """Ends the remote XCTest run and closes the socket."""
        self.session.stop_agent()
        self.disconnect()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"IOSDevice(udid={self.udid!r}, host={self.host!r}, port={self.port})"
