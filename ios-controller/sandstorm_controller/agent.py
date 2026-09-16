"""Starts, supervises and stops the on-device XCTest agent."""

from __future__ import annotations

import logging
import os
import re
import secrets
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from sandstorm_ios import IOSDevice
from sandstorm_ios.errors import IOSAgentNotRunning

from .build import TEST_IDENTIFIER, AgentBuilder, BuildResult, patch_xctestrun
from .devices import DeviceRecord, boot_simulator
from .tunnel import Tunnel, allocate_port, open_tunnel, wait_for_port

logger = logging.getLogger("sandstorm.agent")

READY_PATTERN = re.compile(r"SANDSTORM_AGENT_READY port=(\d+)")
AGENT_LOG_PATTERN = re.compile(r"\[sandstorm]")

#: Failures that a restart can never fix; each maps to an actionable message.
FATAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"Developer App Certificate is not trusted|profile has not been explicitly trusted"),
        "The agent is installed but iOS will not launch it: the developer certificate is not "
        "trusted on the device. On the iPhone open Settings -> General -> VPN & Device Management "
        "-> your Apple ID -> Trust, then run `sandstorm ios start` again.",
    ),
    (
        re.compile(r"device is locked|passcode-protected and locked"),
        "The device is locked. Unlock the iPhone (and disable auto-lock) and try again.",
    ),
    (
        re.compile(r"Developer Mode disabled|developer mode is not enabled"),
        "Developer Mode is off. Enable Settings -> Privacy & Security -> Developer Mode, reboot, "
        "then try again.",
    ),
    (
        re.compile(r"No profiles for .* were found|requires a provisioning profile"),
        "Signing failed: no provisioning profile for the agent bundle id. Re-run "
        "`sandstorm ios setup --udid <UDID>` with a valid Apple ID signed into Xcode.",
    ),
)
DEFAULT_DEVICE_PORT = 8433


@dataclass
class AgentHandle:
    """Everything a client needs to talk to a running agent."""

    device: DeviceRecord
    host: str
    port: int
    token: str
    runner: "AgentRunner"
    tunnel: Tunnel

    def client_device(self, **kwargs) -> IOSDevice:
        """Builds a connected :class:`IOSDevice` for this agent."""
        return IOSDevice(
            self.device.udid, host=self.host, port=self.port, token=self.token, **kwargs
        ).connect()

    def environment(self) -> dict[str, str]:
        """Environment variables that let a separate process attach."""
        return {
            "SANDSTORM_AGENT_HOST": self.host,
            "SANDSTORM_AGENT_PORT": str(self.port),
            "SANDSTORM_TOKEN": self.token,
            "SANDSTORM_UDID": self.device.udid,
        }

    def stop(self) -> None:
        self.runner.stop()
        self.tunnel.close()


@dataclass
class AgentRunner:
    """Runs ``xcodebuild test-without-building`` and keeps it alive.

    Apple constraint: UI automation events can only be synthesized from a
    signed XCTest runner process launched through Apple's own testing stack.
    There is no supported daemon we could install instead, so the controller
    owns an ``xcodebuild`` child process for the lifetime of the session.
    """

    device: DeviceRecord
    builder: AgentBuilder = field(default_factory=AgentBuilder)
    device_port: int = DEFAULT_DEVICE_PORT
    token: str = field(default_factory=lambda: secrets.token_hex(16))
    log_level: str = "info"
    auto_restart: bool = True
    on_log: Callable[[str], None] | None = None

    _ready_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _crashed_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _process: subprocess.Popen | None = field(default=None, init=False, repr=False)
    _reader: threading.Thread | None = field(default=None, init=False, repr=False)
    _supervisor: threading.Thread | None = field(default=None, init=False, repr=False)
    _stopping: bool = field(default=False, init=False, repr=False)
    _build: BuildResult | None = field(default=None, init=False, repr=False)
    _restarts: int = field(default=0, init=False, repr=False)
    _fatal_error: str | None = field(default=None, init=False, repr=False)

    # -- Lifecycle -----------------------------------------------------------

    def start(self, *, ready_timeout: float = 240.0) -> AgentHandle:
        terminate_stale_runners(self.device.udid)

        if self.device.is_simulator:
            boot_simulator(self.device.udid)

        self._build = self.builder.locate_build(self.device)
        self._spawn()

        deadline = time.monotonic() + ready_timeout
        while not self._ready_event.wait(timeout=1.0):
            # Fail fast on errors a restart cannot fix (untrusted certificate,
            # locked device, ...) instead of waiting out the whole timeout.
            if self._fatal_error or self._crashed_event.is_set() or time.monotonic() > deadline:
                break

        if not self._ready_event.is_set():
            self.stop()
            raise IOSAgentNotRunning(
                self._fatal_error
                or f"Agent did not report READY within {ready_timeout}s. "
                "Run with SANDSTORM_VERBOSE=1 to see the xcodebuild output."
            )

        tunnel = open_tunnel(self.device, self.device_port)
        if not wait_for_port(tunnel.host, tunnel.local_port, timeout=60.0):
            tunnel.close()
            self.stop()
            raise IOSAgentNotRunning(
                f"Agent port {tunnel.local_port} never accepted a connection"
            )

        if self.auto_restart:
            self._start_supervisor()

        logger.info("Agent ready on %s:%s", tunnel.host, tunnel.local_port)
        return AgentHandle(
            device=self.device,
            host=tunnel.host,
            port=tunnel.local_port,
            token=self.token,
            runner=self,
            tunnel=tunnel,
        )

    def stop(self) -> None:
        self._stopping = True
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                process.kill()
        self._process = None
        logger.info("Agent stopped")

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # -- Internals -----------------------------------------------------------

    def _spawn(self) -> None:
        assert self._build is not None
        self._ready_event.clear()
        self._crashed_event.clear()
        self._fatal_error = None

        patched = patch_xctestrun(
            self._build.xctestrun_path,
            self._build.xctestrun_path.parent / "Sandstorm.patched.xctestrun",
            environment={
                "SANDSTORM_PORT": str(self.device_port),
                "SANDSTORM_TOKEN": self.token,
                "SANDSTORM_LOG_LEVEL": self.log_level,
            },
        )

        command = [
            "xcodebuild",
            "test-without-building",
            "-xctestrun",
            str(patched),
            "-destination",
            self.device.destination,
            f"-only-testing:{TEST_IDENTIFIER}",
        ]
        logger.info("Launching agent: %s", " ".join(command))
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "NSUnbufferedIO": "YES"},
        )
        self._reader = threading.Thread(target=self._pump_output, daemon=True, name="sandstorm-agent-log")
        self._reader.start()

    def _pump_output(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        verbose = os.environ.get("SANDSTORM_VERBOSE") == "1"
        for line in process.stdout:
            line = line.rstrip()
            if READY_PATTERN.search(line):
                self._ready_event.set()
            for pattern, hint in FATAL_PATTERNS:
                if pattern.search(line):
                    self._fatal_error = hint
                    break
            if self.on_log is not None:
                self.on_log(line)
            if verbose:
                logger.info("xcodebuild| %s", line)
            elif AGENT_LOG_PATTERN.search(line):
                logger.debug("agent| %s", line)
        if not self._stopping:
            self._crashed_event.set()
            if self._fatal_error:
                logger.error("%s", self._fatal_error)
            else:
                logger.warning("xcodebuild exited unexpectedly (code %s)", process.poll())

    def _start_supervisor(self) -> None:
        def supervise() -> None:
            while not self._stopping:
                if self._crashed_event.wait(timeout=1.0):
                    if self._stopping:
                        return
                    if self._fatal_error:
                        # Restarting cannot fix a device-side/config problem; it
                        # would only hide the real error behind a retry loop.
                        logger.error("Not restarting the agent: %s", self._fatal_error)
                        return
                    self._restarts += 1
                    logger.warning("Restarting the agent (attempt %s)", self._restarts)
                    try:
                        self._spawn()
                        self._ready_event.wait(timeout=240.0)
                    except Exception as exc:  # noqa: BLE001 - keep supervising
                        logger.error("Agent restart failed: %s", exc)
                        time.sleep(5.0)

        self._supervisor = threading.Thread(target=supervise, daemon=True, name="sandstorm-agent-supervisor")
        self._supervisor.start()


def terminate_stale_runners(udid: str, *, timeout: float = 10.0) -> int:
    """Kills XCTest runners left over from a previous session on this device.

    Two `xcodebuild test` processes cannot share a device: the second one tears
    the first one down, which surfaces as the agent closing the connection
    mid-command. Orphans are easy to create (Ctrl-C, a crashed script), so the
    runner clears them before starting instead of failing mysteriously later.

    The supervising controller is terminated too. Killing only the `xcodebuild`
    child is not enough: the previous session's supervisor would simply restart
    it and both runners would fight over the device.
    """
    try:
        listing = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,command="],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0

    protected = {os.getpid(), os.getppid()}
    targets: list[tuple[int, str]] = []
    for line in listing.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) < 3:
            continue
        pid_text, ppid_text, command = fields
        if "xcodebuild" not in command or "test-without-building" not in command or udid not in command:
            continue
        try:
            pid, ppid = int(pid_text), int(ppid_text)
        except ValueError:
            continue
        if pid not in protected:
            targets.append((pid, "runner"))
        if ppid not in protected and ppid > 1:
            targets.append((ppid, "supervisor"))

    killed = 0
    # Supervisors first, so they cannot respawn the runner we are about to kill.
    for pid, kind in sorted(targets, key=lambda item: item[1]):
        logger.warning("Terminating stale agent %s pid=%s on %s", kind, pid, udid)
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except OSError as exc:
            logger.debug("Could not terminate pid %s: %s", pid, exc)

    if killed:
        time.sleep(2.0)
    return killed


def start_agent(
    device: DeviceRecord,
    *,
    device_port: int | None = None,
    token: str | None = None,
    log_level: str = "info",
    ready_timeout: float = 240.0,
) -> AgentHandle:
    """Convenience wrapper used by the CLI and the Inspector."""
    port = device_port or (allocate_port() if device.is_simulator else DEFAULT_DEVICE_PORT)
    runner = AgentRunner(
        device=device,
        device_port=port,
        token=token or secrets.token_hex(16),
        log_level=log_level,
    )
    return runner.start(ready_timeout=ready_timeout)
