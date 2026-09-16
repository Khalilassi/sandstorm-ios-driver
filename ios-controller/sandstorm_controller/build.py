"""Builds and signs the XCTest agent once, then caches the ``.xctestrun``.

The agent is **not** rebuilt per test run: `sandstorm ios setup` produces a
`.xctestrun` plus a signed `SandstormAgent-Runner.app`, and
`sandstorm ios start` only executes `test-without-building`.
"""

from __future__ import annotations

import glob
import importlib.util
import logging
import os
import plistlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sandstorm_ios.errors import IOSSetupError

from .devices import DeviceRecord

logger = logging.getLogger("sandstorm.build")

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_PATH = REPO_ROOT / "ios-agent" / "SandstormAgent.xcodeproj"
SCHEME = "SandstormAgent"
DERIVED_DATA = REPO_ROOT / "build" / "derived"
TEST_IDENTIFIER = "SandstormAgent/AutomationServerTests/testAutomationServer"


@dataclass(frozen=True, slots=True)
class XcodeEnvironment:
    """What we could detect about the local toolchain."""

    xcode_path: str
    xcode_version: str
    signing_identities: tuple[str, ...]

    @property
    def has_signing_identity(self) -> bool:
        return bool(self.signing_identities)


@dataclass(frozen=True, slots=True)
class BuildResult:
    xctestrun_path: Path
    products_dir: Path
    runner_app: Path | None
    demo_app: Path | None


def iphoneos_sdk_version() -> str | None:
    """Returns the iOS SDK version bundled with the selected Xcode, e.g. ``18.1``."""
    result = subprocess.run(
        ["xcrun", "--sdk", "iphoneos", "--show-sdk-version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def verify_sdk_supports(device: DeviceRecord) -> None:
    """Fails fast when Xcode is too old to build for the device's iOS version.

    Xcode can only install and debug on devices whose major iOS version is at
    most that of its bundled SDK. Without this check the failure surfaces much
    later as an unrelated "Failed writing xctestrun file" error.
    """
    if device.is_simulator:
        return
    sdk = iphoneos_sdk_version()
    if not sdk:
        return
    try:
        sdk_major = int(sdk.split(".")[0])
        device_major = int(device.ios_version.split(".")[0])
    except (ValueError, IndexError):
        return
    if device_major > sdk_major:
        if os.environ.get("SANDSTORM_SKIP_SDK_CHECK") == "1":
            logger.warning(
                "Xcode ships the iOS %s SDK but %s runs iOS %s. Continuing because "
                "SANDSTORM_SKIP_SDK_CHECK=1; installing onto the device will only work "
                "if a matching DeviceSupport bundle is present.",
                sdk,
                device.name,
                device.ios_version,
            )
            return
        raise IOSSetupError(
            f"This Xcode ships the iOS {sdk} SDK but {device.name} runs iOS {device.ios_version}.\n"
            f"Xcode cannot normally build, sign or install onto a device newer than its SDK.\n"
            f"Install an Xcode with the iOS {device_major}.x SDK and select it:\n"
            f"  sudo xcode-select -s /Applications/Xcode-<version>.app/Contents/Developer\n"
            f"Set SANDSTORM_SKIP_SDK_CHECK=1 to try anyway (see docs/PHYSICAL_DEVICE.md).\n"
            f"(Simulators are unaffected; `sandstorm ios setup --udid <SIM_UDID>` still works.)"
        )


def configure_project(
    *,
    bundle_prefix: str | None = None,
    demo_bundle_id: str | None = None,
    agent_bundle_id: str | None = None,
    signing_style: str = "Automatic",
    team: str | None = None,
    demo_profile: str | None = None,
    agent_profile: str | None = None,
    include_demo: bool = True,
) -> tuple[str, str]:
    """Regenerates the Xcode project with the requested identifiers and signing.

    Returns the ``(demo_bundle_id, agent_bundle_id)`` actually written. Bundle
    identifiers have to be baked into the project rather than passed on the
    xcodebuild command line, because a command-line override applies to every
    target at once while the demo app and the agent need different values.
    """
    generator_path = REPO_ROOT / "tools" / "generate_xcodeproj.py"
    spec = importlib.util.spec_from_file_location("sandstorm_xcodeproj", generator_path)
    if spec is None or spec.loader is None:
        raise IOSSetupError(f"Cannot load the project generator at {generator_path}")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    demo = demo_bundle_id or (
        f"{bundle_prefix}.sandstormdemo" if bundle_prefix else generator.DEMO_BUNDLE_ID
    )
    agent = agent_bundle_id or (
        f"{bundle_prefix}.sandstormagent" if bundle_prefix else generator.AGENT_BUNDLE_ID
    )
    generator.write_project(
        demo_bundle_id=demo,
        agent_bundle_id=agent,
        signing_style=signing_style,
        team=team,
        demo_profile=demo_profile,
        agent_profile=agent_profile,
        include_demo=include_demo,
    )
    logger.info("Project configured: demo=%s agent=%s (%s signing)", demo, agent, signing_style.lower())
    return demo, agent


def _diagnose_build_failure(output: str) -> str:
    """Turns well-known xcodebuild signing failures into actionable remedies."""
    hints: list[str] = []
    if "No Accounts" in output or "missing Xcode-Token" in output:
        hints.append(
            "Xcode has no usable Apple ID, so it cannot create provisioning profiles.\n"
            "  Open Xcode > Settings > Accounts, remove any account shown as invalid,\n"
            "  then click + and sign in again. A free Apple ID (Personal Team) is enough.\n"
            "  A signing certificate on the machine is not sufficient: creating a profile\n"
            "  requires a signed-in account."
        )
    if "No profiles for" in output and "No Accounts" not in output:
        hints.append(
            "No provisioning profile matched the agent's bundle identifiers.\n"
            "  Confirm the Apple ID in Xcode > Settings > Accounts belongs to the signing\n"
            "  team, or pass the right one with `--team <TEAM_ID>`."
        )
    if "Unable to find a destination matching" in output:
        hints.append(
            "The device was not visible to Xcode. Check the cable, unlock the phone and\n"
            "  confirm it appears in `sandstorm ios devices` as `connected`."
        )
    if not hints:
        return ""
    return "\n\nLikely cause:\n" + "\n".join(f"- {hint}" for hint in hints)


def detect_xcode() -> XcodeEnvironment:
    if shutil.which("xcodebuild") is None:
        raise IOSSetupError("xcodebuild is not on PATH. Install Xcode and run `xcode-select --install`.")

    version = subprocess.run(
        ["xcodebuild", "-version"], capture_output=True, text=True, check=False
    )
    if version.returncode != 0:
        raise IOSSetupError(f"`xcodebuild -version` failed: {version.stderr.strip()}")

    path = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, check=False)
    identities = _signing_identities()
    return XcodeEnvironment(
        xcode_path=path.stdout.strip(),
        xcode_version=version.stdout.splitlines()[0].strip(),
        signing_identities=identities,
    )


def _signing_identities() -> tuple[str, ...]:
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ()
    identities = []
    for line in result.stdout.splitlines():
        if '"' in line:
            identities.append(line.split('"')[1])
    return tuple(identities)


def detect_development_team() -> str | None:
    """Finds a usable ``DEVELOPMENT_TEAM`` without asking the user for one.

    A free "Personal Team" still has a Team ID, but Xcode never shows it
    prominently. It is stored as the Organisational Unit of the signing
    certificate, so it can be read straight from the keychain; Xcode's own
    ``IDEProvisioningTeams`` preference is used as a fallback.

    Returns ``None`` when no Apple ID has been added to Xcode yet — that step is
    GUI-only and cannot be scripted.
    """
    certificates = subprocess.run(
        ["security", "find-certificate", "-a", "-c", "Apple Development", "-p"],
        capture_output=True,
        text=True,
        check=False,
    )
    if certificates.returncode == 0 and certificates.stdout.strip():
        subject = subprocess.run(
            ["openssl", "x509", "-noout", "-subject"],
            input=certificates.stdout,
            capture_output=True,
            text=True,
            check=False,
        )
        match = re.search(r"OU\s*=\s*([A-Z0-9]{10})", subject.stdout)
        if match:
            return match.group(1)

    teams = subprocess.run(
        ["defaults", "read", "com.apple.dt.Xcode", "IDEProvisioningTeams"],
        capture_output=True,
        text=True,
        check=False,
    )
    if teams.returncode == 0:
        match = re.search(r'teamID"?\s*=\s*"?([A-Z0-9]{10})', teams.stdout)
        if match:
            return match.group(1)

    return None


class AgentBuilder:
    """Wraps the two xcodebuild invocations we need."""

    def __init__(
        self,
        *,
        project_path: Path = PROJECT_PATH,
        scheme: str = SCHEME,
        derived_data: Path = DERIVED_DATA,
    ) -> None:
        self.project_path = project_path
        self.scheme = scheme
        self.derived_data = derived_data

    # -- Build ---------------------------------------------------------------

    def build_for_testing(
        self,
        device: DeviceRecord,
        *,
        development_team: str | None = None,
        configuration: str = "Debug",
        timeout: float = 1800.0,
        signing_style: str = "Automatic",
    ) -> BuildResult:
        verify_sdk_supports(device)
        command = [
            "xcodebuild",
            "build-for-testing",
            "-project",
            str(self.project_path),
            "-scheme",
            self.scheme,
            "-configuration",
            configuration,
            "-destination",
            device.destination,
            "-derivedDataPath",
            str(self.derived_data),
            "-quiet",
        ]
        if not device.is_simulator and signing_style == "Manual":
            # Signing settings are baked into the project by configure_project();
            # -allowProvisioningUpdates would need an Apple ID, which is exactly
            # what manual signing exists to avoid.
            logger.info("Manual signing: using the provisioning profiles already installed")
        elif not device.is_simulator:
            team = (
                development_team
                or os.environ.get("SANDSTORM_DEVELOPMENT_TEAM")
                or detect_development_team()
            )
            if not team:
                raise IOSSetupError(
                    "Building for a physical device needs a signing team, and none could be "
                    "detected. Sign in with an Apple ID in Xcode -> Settings -> Accounts (a free "
                    "Personal Team is enough), then retry. You can also pass --team <TEAM_ID> or "
                    "set SANDSTORM_DEVELOPMENT_TEAM."
                )
            logger.info("Signing with team %s", team)
            command += [
                f"DEVELOPMENT_TEAM={team}",
                "CODE_SIGN_STYLE=Automatic",
                "-allowProvisioningUpdates",
            ]

        logger.info("Building the agent for %s", device.describe())
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            # `-quiet` sends compiler and signing diagnostics to stdout while
            # stderr only carries incidental noise, so report both.
            output = "\n".join(part for part in (result.stdout, result.stderr) if part.strip())
            raise IOSSetupError(
                "Agent build failed:\n" + output[-8000:] + _diagnose_build_failure(output)
            )
        return self.locate_build(device)

    # -- Artifacts -----------------------------------------------------------

    def locate_build(self, device: DeviceRecord) -> BuildResult:
        platform = "iphonesimulator" if device.is_simulator else "iphoneos"
        pattern = str(self.derived_data / "Build" / "Products" / f"*_{platform}*.xctestrun")
        matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if not matches:
            raise IOSSetupError(
                f"No .xctestrun for {platform} in {self.derived_data}. Run `sandstorm ios setup` first."
            )

        xctestrun = Path(matches[0])
        products = xctestrun.parent
        configuration_dir = next(
            (p for p in products.iterdir() if p.is_dir() and p.name.endswith(platform)),
            products,
        )
        runner = configuration_dir / "SandstormAgent-Runner.app"
        demo = configuration_dir / "SandstormDemo.app"
        return BuildResult(
            xctestrun_path=xctestrun,
            products_dir=configuration_dir,
            runner_app=runner if runner.exists() else None,
            demo_app=demo if demo.exists() else None,
        )

    # -- Install -------------------------------------------------------------

    def install_demo_app(self, device: DeviceRecord, build: BuildResult) -> None:
        """Installs the bundled demo app (handy for the first milestone)."""
        if build.demo_app is None:
            return
        if device.is_simulator:
            subprocess.run(
                ["xcrun", "simctl", "install", device.udid, str(build.demo_app)],
                check=False,
                capture_output=True,
            )
        elif shutil.which("xcrun"):
            subprocess.run(
                ["xcrun", "devicectl", "device", "install", "app", "--device", device.udid, str(build.demo_app)],
                check=False,
                capture_output=True,
            )


def patch_xctestrun(
    source: Path,
    destination: Path,
    *,
    environment: dict[str, str],
) -> Path:
    """Injects agent environment variables into a copy of the ``.xctestrun``.

    ``xcodebuild`` only forwards ``TEST_RUNNER_``-prefixed variables when a
    *scheme* is used; with ``-xctestrun`` we must write them into the plist.
    Handles both FormatVersion 1 (flat) and 2 (TestConfigurations) layouts.
    """
    payload = plistlib.loads(source.read_bytes())

    def patch_target(target: dict) -> None:
        env = dict(target.get("EnvironmentVariables") or {})
        env.update(environment)
        target["EnvironmentVariables"] = env
        # A long-lived agent must never be killed by the per-test timeout.
        target["TestTimeoutsEnabled"] = False
        target["DefaultTestExecutionTimeAllowance"] = 0

    if "TestConfigurations" in payload:
        for configuration in payload["TestConfigurations"]:
            for target in configuration.get("TestTargets", []):
                patch_target(target)
    else:
        for key, value in payload.items():
            if key.startswith("__") or not isinstance(value, dict):
                continue
            patch_target(value)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(plistlib.dumps(payload))
    return destination
