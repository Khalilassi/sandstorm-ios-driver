"""Sandstorm iOS Driver — Python SDK.

A lightweight, Playwright-flavoured automation API for real iPhones and
simulators that talks to a minimal on-device XCTest agent. No Appium, no
WebDriverAgent, no WebDriver protocol.
"""

from .errors import (
    IOSAgentConnectionError,
    IOSAgentNotRunning,
    IOSAppLaunchError,
    IOSCommandTimeout,
    IOSDeviceNotFound,
    IOSElementNotFound,
    IOSElementNotInteractable,
    IOSError,
    IOSProtocolError,
    IOSSessionLost,
)
from .sdk.application import IOSApplication
from .sdk.device import IOSDevice
from .sdk.locator import Locator
from .sdk.page import IOSPage
from .sdk.session import IOSSession

__all__ = [
    "IOSDevice",
    "IOSApplication",
    "IOSPage",
    "IOSSession",
    "Locator",
    "IOSError",
    "IOSDeviceNotFound",
    "IOSAgentNotRunning",
    "IOSAgentConnectionError",
    "IOSElementNotFound",
    "IOSElementNotInteractable",
    "IOSCommandTimeout",
    "IOSAppLaunchError",
    "IOSSessionLost",
    "IOSProtocolError",
]

__version__ = "0.1.0"
