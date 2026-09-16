"""Protocol message models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping

PROTOCOL_VERSION: Final[int] = 1
CLIENT_NAME: Final[str] = "sandstorm-python"


@dataclass(frozen=True, slots=True)
class Command:
    """A single request sent to the agent."""

    id: int
    method: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {"id": self.id, "method": self.method, "params": dict(self.params)}


@dataclass(frozen=True, slots=True)
class Response:
    """A single agent reply, with its optional binary attachment."""

    id: int
    success: bool
    result: Mapping[str, Any] = field(default_factory=dict)
    error: Mapping[str, Any] | None = None
    binary: bytes | None = None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any], binary: bytes | None = None) -> "Response":
        return cls(
            id=int(payload.get("id", -1)),
            success=bool(payload.get("success", False)),
            result=payload.get("result") or {},
            error=payload.get("error"),
            binary=binary,
        )


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Device facts reported by the agent during the handshake."""

    name: str
    ios_version: str
    model: str
    udid: str | None
    is_simulator: bool
    screen_width: float
    screen_height: float
    screen_scale: float

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> "DeviceInfo":
        screen = payload.get("screen") or {}
        return cls(
            name=str(payload.get("name", "unknown")),
            ios_version=str(payload.get("iosVersion", "unknown")),
            model=str(payload.get("model", "unknown")),
            udid=payload.get("udid"),
            is_simulator=bool(payload.get("isSimulator", False)),
            screen_width=float(screen.get("width", 0.0)),
            screen_height=float(screen.get("height", 0.0)),
            screen_scale=float(screen.get("scale", 1.0)),
        )


@dataclass(frozen=True, slots=True)
class Handshake:
    """Agent handshake reply."""

    protocol_version: int
    agent_version: str
    session_id: str
    device: DeviceInfo

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> "Handshake":
        return cls(
            protocol_version=int(payload.get("protocolVersion", 0)),
            agent_version=str(payload.get("agentVersion", "unknown")),
            session_id=str(payload.get("sessionId", "")),
            device=DeviceInfo.from_wire(payload.get("device") or {}),
        )


def build_handshake_request(token: str | None, client_version: str) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "client": CLIENT_NAME,
        "clientVersion": client_version,
        "token": token,
    }
