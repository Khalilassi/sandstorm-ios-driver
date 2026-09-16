"""Device discovery for simulators and physical iPhones."""

from __future__ import annotations

import json
import logging
import os
import plistlib
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from sandstorm_ios.errors import IOSDeviceNotFound

logger = logging.getLogger("sandstorm.devices")


class DeviceKind(str, Enum):
    SIMULATOR = "simulator"
    PHYSICAL = "physical"


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    """A device Sandstorm can drive."""

    udid: str
    name: str
    kind: DeviceKind
    ios_version: str
    state: str
    developer_mode: bool | None = None
    paired: bool | None = None

    @property
    def is_simulator(self) -> bool:
        return self.kind is DeviceKind.SIMULATOR

    @property
    def destination(self) -> str:
        platform = "iOS Simulator" if self.is_simulator else "iOS"
        return f"platform={platform},id={self.udid}"

    def describe(self) -> str:
        flags = []
        if self.developer_mode is False:
            flags.append("developer-mode-off")
        if self.paired is False:
            flags.append("unpaired")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        return f"{self.name} ({self.kind.value}, iOS {self.ios_version}, {self.state}){suffix} {self.udid}"


def _run(command: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    logger.debug("exec: %s", " ".join(command))
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


# -- Simulators --------------------------------------------------------------


def discover_simulators(*, booted_only: bool = False) -> list[DeviceRecord]:
    result = _run(["xcrun", "simctl", "list", "devices", "available", "--json"])
    if result.returncode != 0:
        logger.warning("simctl failed: %s", result.stderr.strip())
        return []

    payload: dict[str, Any] = json.loads(result.stdout)
    devices: list[DeviceRecord] = []
    for runtime, entries in payload.get("devices", {}).items():
        ios_version = runtime.rsplit(".", 1)[-1].replace("iOS-", "").replace("-", ".")
        for entry in entries:
            if booted_only and entry.get("state") != "Booted":
                continue
            devices.append(
                DeviceRecord(
                    udid=entry["udid"],
                    name=entry.get("name", "Simulator"),
                    kind=DeviceKind.SIMULATOR,
                    ios_version=ios_version,
                    state=entry.get("state", "Unknown"),
                    developer_mode=True,
                    paired=True,
                )
            )
    return devices


def boot_simulator(udid: str, *, timeout: float = 180.0, show_ui: bool | None = None) -> None:
    """Boots a simulator if it is not already running (idempotent).

    ``simctl`` boots the device headless: the runtime is live and fully
    automatable, but no window appears. ``show_ui`` additionally opens
    Simulator.app and focuses this device so the run can be watched. Set
    ``SANDSTORM_HEADLESS=1`` to keep it invisible (useful on CI).
    """
    result = _run(["xcrun", "simctl", "bootstatus", udid, "-b"], timeout=timeout)
    if result.returncode != 0:
        # `bootstatus -b` boots and waits; a non-zero code usually means the
        # device was already booted.
        logger.debug("bootstatus returned %s: %s", result.returncode, result.stderr.strip())

    if show_ui is None:
        show_ui = os.environ.get("SANDSTORM_HEADLESS", "") not in {"1", "true", "yes"}
    if show_ui:
        open_simulator_ui(udid)


def open_simulator_ui(udid: str) -> None:
    """Opens Simulator.app and brings the given device to the front."""
    set_hardware_keyboard(False)
    result = _run(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid], timeout=30.0)
    if result.returncode != 0:
        logger.warning("Could not open Simulator.app: %s", result.stderr.strip())
    else:
        logger.info("Simulator window opened for %s", udid)


def set_hardware_keyboard(connected: bool) -> None:
    """Toggles Simulator.app's "Connect Hardware Keyboard".

    Text is always typed with synthesized key events (``XCUIElement.typeText``),
    never pasted. But while the hardware keyboard is connected iOS hides the
    on-screen keyboard, so typing is invisible. Disconnecting it makes the
    software keyboard appear and each keystroke visible during a run.

    Simulator.app reads this preference at launch, so call it before ``open``.
    """
    value = "true" if connected else "false"
    result = _run(
        ["defaults", "write", "com.apple.iphonesimulator", "ConnectHardwareKeyboard", "-bool", value],
        timeout=15.0,
    )
    if result.returncode != 0:
        logger.debug("Could not set ConnectHardwareKeyboard: %s", result.stderr.strip())


# -- Physical devices --------------------------------------------------------


def discover_physical_devices() -> list[DeviceRecord]:
    """Lists USB-attached iPhones.

    Prefers ``xcrun devicectl`` (Xcode 15+), falling back to
    ``pymobiledevice3`` when it is installed. Both are Apple-sanctioned paths:
    no private frameworks, no jailbreak.
    """
    devices = _devicectl_devices()
    if devices:
        return devices
    return _pymobiledevice3_devices()


def _devicectl_devices() -> list[DeviceRecord]:
    if shutil.which("xcrun") is None:
        return []
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json") as handle:
        result = _run(
            ["xcrun", "devicectl", "list", "devices", "--json-output", handle.name],
            timeout=90.0,
        )
        if result.returncode != 0:
            logger.debug("devicectl failed: %s", result.stderr.strip())
            return []
        try:
            payload = json.load(open(handle.name, "r", encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    devices: list[DeviceRecord] = []
    for entry in payload.get("result", {}).get("devices", []):
        properties = entry.get("deviceProperties", {})
        hardware = entry.get("hardwareProperties", {})
        connection = entry.get("connectionProperties", {})
        if hardware.get("platform") not in ("iOS", None):
            continue
        devices.append(
            DeviceRecord(
                udid=hardware.get("udid", entry.get("identifier", "")),
                name=properties.get("name", "iPhone"),
                kind=DeviceKind.PHYSICAL,
                ios_version=properties.get("osVersionNumber", "unknown"),
                state=connection.get("tunnelState", "unknown"),
                developer_mode=properties.get("developerModeStatus") == "enabled",
                paired=connection.get("pairingState") == "paired",
            )
        )
    return devices


def _pymobiledevice3_devices() -> list[DeviceRecord]:
    if shutil.which("pymobiledevice3") is None:
        return []
    result = _run(["pymobiledevice3", "usbmux", "list", "--no-color"], timeout=30.0)
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    devices = []
    for entry in payload:
        devices.append(
            DeviceRecord(
                udid=entry.get("Identifier", ""),
                name=entry.get("DeviceName", "iPhone"),
                kind=DeviceKind.PHYSICAL,
                ios_version=entry.get("ProductVersion", "unknown"),
                state=entry.get("ConnectionType", "USB"),
                developer_mode=None,
                paired=True,
            )
        )
    return devices


def read_developer_mode(udid: str) -> bool | None:
    """Best-effort Developer Mode probe (iOS 16+ requires it for XCTest)."""
    if shutil.which("pymobiledevice3") is None:
        return None
    result = _run(
        ["pymobiledevice3", "amfi", "developer-mode-status", "--udid", udid, "--no-color"],
        timeout=20.0,
    )
    if result.returncode != 0:
        return None
    return "true" in result.stdout.lower()


def read_installed_bundles(udid: str) -> set[str]:
    """Returns installed bundle identifiers on a physical device, if possible."""
    if shutil.which("pymobiledevice3") is None:
        return set()
    result = _run(
        ["pymobiledevice3", "apps", "list", "--udid", udid, "--no-color"], timeout=60.0
    )
    if result.returncode != 0:
        return set()
    try:
        return set(json.loads(result.stdout).keys())
    except (json.JSONDecodeError, AttributeError):
        return set()


def read_simulator_bundles(udid: str) -> set[str]:
    result = _run(["xcrun", "simctl", "listapps", udid], timeout=60.0)
    if result.returncode != 0:
        return set()
    try:
        return set(plistlib.loads(result.stdout.encode("utf-8")).keys())
    except Exception:  # noqa: BLE001 - simctl output is not always a plist
        return set()


# -- Aggregation -------------------------------------------------------------


def discover_devices(*, include_simulators: bool = True, include_physical: bool = True) -> list[DeviceRecord]:
    devices: list[DeviceRecord] = []
    if include_physical:
        devices.extend(discover_physical_devices())
    if include_simulators:
        devices.extend(discover_simulators())
    return devices


def resolve_device(udid: str | None, *, candidates: Iterable[DeviceRecord] | None = None) -> DeviceRecord:
    """Resolves a UDID, or picks a sensible default.

    Preference order when no UDID is given: booted simulator > connected
    iPhone > any available simulator.
    """
    devices = list(candidates) if candidates is not None else discover_devices()
    if udid:
        for device in devices:
            if device.udid == udid:
                return device
        raise IOSDeviceNotFound(f"No device with UDID {udid!r}. Run `sandstorm ios devices`.")

    booted = [d for d in devices if d.is_simulator and d.state == "Booted"]
    if booted:
        return booted[0]
    physical = [d for d in devices if not d.is_simulator]
    if physical:
        return physical[0]
    simulators = [d for d in devices if d.is_simulator]
    if simulators:
        return simulators[0]
    raise IOSDeviceNotFound("No iOS devices or simulators are available")
