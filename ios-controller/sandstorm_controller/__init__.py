"""Sandstorm iOS Driver — macOS controller.

Discovers devices, builds/installs the XCTest agent, starts the long-lived
XCTest runner, forwards the USB tunnel and hands a ready-to-use connection to
the Python SDK.
"""

from .agent import AgentHandle, AgentRunner
from .build import AgentBuilder, BuildResult, XcodeEnvironment
from .devices import DeviceKind, DeviceRecord, discover_devices, resolve_device
from .tunnel import Tunnel, open_tunnel

__all__ = [
    "AgentRunner",
    "AgentHandle",
    "AgentBuilder",
    "BuildResult",
    "XcodeEnvironment",
    "DeviceRecord",
    "DeviceKind",
    "discover_devices",
    "resolve_device",
    "Tunnel",
    "open_tunnel",
]

__version__ = "0.1.0"
