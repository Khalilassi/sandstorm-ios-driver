"""Session bookkeeping on top of :class:`IOSControllerClient`."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from ..errors import IOSSessionLost
from ..protocol.messages import DeviceInfo, Response
from ..transport import IOSControllerClient

logger = logging.getLogger("sandstorm.session")


class IOSSession:
    """A live automation session against one agent.

    Wraps the transport and keeps the negotiated device facts around so that
    higher level objects (pages, locators) can translate normalized coordinates
    without extra round trips.
    """

    def __init__(self, client: IOSControllerClient) -> None:
        self._client = client

    @property
    def client(self) -> IOSControllerClient:
        return self._client

    @property
    def session_id(self) -> str:
        return self._client.handshake.session_id

    @property
    def agent_version(self) -> str:
        return self._client.handshake.agent_version

    @property
    def device_info(self) -> DeviceInfo:
        return self._client.handshake.device

    @property
    def is_alive(self) -> bool:
        return self._client.is_connected and self._client.is_healthy()

    def invoke(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        retry: bool = True,
    ) -> Response:
        if not self._client.is_connected:
            raise IOSSessionLost("Session is closed")
        return self._client.invoke(method, params, timeout=timeout, retry=retry)

    def result(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        return self.invoke(method, params, timeout=timeout).result

    def ping(self) -> float:
        return self._client.ping()

    def stop_agent(self) -> None:
        """Asks the agent to end its XCTest run gracefully."""
        try:
            # The agent tears the socket down as it stops, so a dropped
            # connection here is the expected outcome, not a failure.
            self.invoke("session.stop", timeout=5.0, retry=False)
        except Exception as exc:  # noqa: BLE001 - shutdown is best effort
            logger.debug("Agent did not acknowledge session.stop: %s", exc)
        finally:
            self._client.close()

    def close(self) -> None:
        self._client.close()
