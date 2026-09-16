"""Local port plumbing.

Simulators share the host's loopback interface, so a socket bound to
``127.0.0.1`` inside the simulator is directly reachable from macOS — no tunnel
needed.

Physical devices are only reachable through **usbmuxd**, Apple's USB
multiplexer (the same daemon Xcode uses). We shell out to ``iproxy`` or
``pymobiledevice3 usbmux forward``; both are userspace clients of the public
usbmux socket. No private frameworks are involved.
"""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from sandstorm_ios.errors import IOSAgentConnectionError

from .devices import DeviceRecord

logger = logging.getLogger("sandstorm.tunnel")


def allocate_port() -> int:
    """Asks the OS for a free local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(host: str, port: int, *, timeout: float = 60.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(interval)
    return False


@dataclass
class Tunnel:
    """A local endpoint that reaches the agent."""

    host: str
    local_port: int
    device_port: int
    process: Optional[subprocess.Popen] = None

    @property
    def is_active(self) -> bool:
        return self.process is None or self.process.poll() is None

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                self.process.kill()
            logger.info("Closed USB tunnel on port %s", self.local_port)

    def __enter__(self) -> "Tunnel":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_tunnel(device: DeviceRecord, device_port: int, *, local_port: int | None = None) -> Tunnel:
    """Returns a tunnel to ``device_port`` on the device."""
    if device.is_simulator:
        # The simulator's loopback *is* the host's loopback.
        return Tunnel(host="127.0.0.1", local_port=device_port, device_port=device_port)

    local_port = local_port or allocate_port()
    command = _forward_command(device.udid, local_port, device_port)
    logger.info("Opening USB tunnel %s -> %s:%s", local_port, device.name, device_port)
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)
    if process.poll() is not None:
        raise IOSAgentConnectionError(
            f"USB tunnel exited immediately (command: {' '.join(command)})"
        )
    return Tunnel(host="127.0.0.1", local_port=local_port, device_port=device_port, process=process)


def _forward_command(udid: str, local_port: int, device_port: int) -> list[str]:
    if shutil.which("iproxy"):
        return ["iproxy", f"{local_port}:{device_port}", "-u", udid]
    if shutil.which("pymobiledevice3"):
        return [
            "pymobiledevice3",
            "usbmux",
            "forward",
            str(local_port),
            str(device_port),
            "--serial",
            udid,
            "--no-color",
        ]
    raise IOSAgentConnectionError(
        "No USB forwarder found. Install one of:\n"
        "  pip install pymobiledevice3\n"
        "  brew install libimobiledevice   # provides iproxy"
    )
