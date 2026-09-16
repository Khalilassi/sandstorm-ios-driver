"""Typed exception hierarchy shared by the controller and the SDK."""

from __future__ import annotations

from typing import Any, Mapping


class IOSError(Exception):
    """Base class for every Sandstorm failure."""

    code: str = "SANDSTORM_ERROR"

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: Mapping[str, Any] = details or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.details:
            return f"{self.message} ({self.details})"
        return self.message


class IOSDeviceNotFound(IOSError):
    code = "DEVICE_NOT_FOUND"


class IOSAgentNotRunning(IOSError):
    code = "AGENT_NOT_RUNNING"


class IOSAgentConnectionError(IOSError):
    code = "AGENT_CONNECTION_ERROR"


class IOSProtocolError(IOSError):
    code = "PROTOCOL_ERROR"


class IOSUnauthorized(IOSError):
    code = "UNAUTHORIZED"


class IOSElementNotFound(IOSError):
    code = "ELEMENT_NOT_FOUND"


class IOSElementNotInteractable(IOSError):
    code = "ELEMENT_NOT_INTERACTABLE"


class IOSStaleElement(IOSError):
    code = "STALE_ELEMENT"


class IOSCommandTimeout(IOSError):
    code = "TIMEOUT"


class IOSAppLaunchError(IOSError):
    code = "APP_LAUNCH_FAILED"


class IOSSessionLost(IOSError):
    code = "SESSION_LOST"


class IOSSetupError(IOSError):
    code = "SETUP_ERROR"


#: Maps agent error codes (see ``AgentErrorCode`` in Swift) onto SDK exceptions.
AGENT_ERROR_MAP: dict[str, type[IOSError]] = {
    "UNKNOWN_METHOD": IOSProtocolError,
    "INVALID_PARAMS": IOSProtocolError,
    "PROTOCOL_ERROR": IOSProtocolError,
    "UNAUTHORIZED": IOSUnauthorized,
    "ELEMENT_NOT_FOUND": IOSElementNotFound,
    "ELEMENT_NOT_INTERACTABLE": IOSElementNotInteractable,
    "STALE_ELEMENT": IOSStaleElement,
    "APP_LAUNCH_FAILED": IOSAppLaunchError,
    "NO_ACTIVE_APP": IOSAppLaunchError,
    "ALERT_NOT_FOUND": IOSElementNotFound,
    "TIMEOUT": IOSCommandTimeout,
    "SNAPSHOT_FAILED": IOSError,
    "INTERNAL_ERROR": IOSError,
}


def error_from_payload(payload: Mapping[str, Any]) -> IOSError:
    """Rebuilds a typed exception from an agent error payload."""
    code = str(payload.get("code", "INTERNAL_ERROR"))
    message = str(payload.get("message", "Unknown agent error"))
    exc_type = AGENT_ERROR_MAP.get(code, IOSError)
    error = exc_type(message, details=payload.get("details") or {})
    error.code = code
    return error
