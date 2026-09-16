"""``sandstorm`` command line interface."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from typing import Sequence

from sandstorm_ios import IOSDevice
from sandstorm_ios.errors import IOSError

from .agent import DEFAULT_DEVICE_PORT, start_agent
from .build import AgentBuilder, configure_project, detect_xcode, iphoneos_sdk_version
from .profiles import ProvisioningProfile, find_profile, list_profiles
from .devices import discover_devices, read_developer_mode, resolve_device

logger = logging.getLogger("sandstorm.cli")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# -- Commands ----------------------------------------------------------------


def cmd_devices(args: argparse.Namespace) -> int:
    devices = discover_devices(
        include_simulators=not args.physical_only,
        include_physical=not args.simulators_only,
    )
    if args.json:
        print(json.dumps([d.__dict__ | {"kind": d.kind.value} for d in devices], indent=2, default=str))
        return 0
    if not devices:
        print("No devices found.")
        return 1
    for device in devices:
        print(f"  {device.describe()}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    environment = detect_xcode()
    print(f"Xcode:    {environment.xcode_version}")
    print(f"Path:     {environment.xcode_path}")
    sdk = iphoneos_sdk_version()
    if sdk:
        print(f"iOS SDK:  {sdk}")
    if environment.has_signing_identity:
        print(f"Signing:  {len(environment.signing_identities)} identity(ies) available")
    else:
        print("Signing:  none found (simulator-only setup)")

    device = resolve_device(args.udid)
    print(f"Target:   {device.describe()}")

    if not device.is_simulator:
        developer_mode = device.developer_mode
        if developer_mode is None:
            developer_mode = read_developer_mode(device.udid)
        if developer_mode is False:
            print(
                "Developer Mode is OFF. Enable it on the device: "
                "Settings > Privacy & Security > Developer Mode."
            )
            return 2

    builder = AgentBuilder()
    signing_style = "Manual" if args.profile else "Automatic"
    if args.profile or args.bundle_prefix or args.agent_bundle_id or args.demo_bundle_id:
        profile = find_profile(args.profile) if args.profile else None
        if args.profile and profile is None:
            print(f"No installed provisioning profile named or with UUID '{args.profile}'.")
            print("Run `sandstorm ios profiles` to list what is available.")
            return 2

        prefix, agent_id, demo_id = _plan_bundle_ids(profile, args)
        include_demo = not args.no_demo
        if profile is not None and not profile.is_wildcard and include_demo:
            # An explicit profile can only cover the runner, so the bundled demo
            # app would fail to sign and abort the whole build.
            print("Profile is explicit; skipping the bundled demo app (--no-demo implied).")
            include_demo = False

        team = args.team or (profile.team_id if profile else None)
        profile_name = profile.name if profile else None
        demo_id, agent_id = configure_project(
            bundle_prefix=prefix,
            demo_bundle_id=demo_id,
            agent_bundle_id=agent_id,
            signing_style=signing_style,
            team=team,
            demo_profile=profile_name,
            agent_profile=profile_name,
            include_demo=include_demo,
        )
        print(f"Agent:    {agent_id} (runner {agent_id}.xctrunner)")
        print(f"Demo:     {demo_id}" if include_demo else "Demo:     not built")
        if profile is not None:
            print(f"Profile:  {profile.describe()}")
            if not profile.signs_runner(agent_id) and not args.force:
                print(
                    f"\nThis profile cannot sign an XCTest runner.\n"
                    f"  profile app ID : {profile.bundle_id_pattern}\n"
                    f"  runner bundle  : {profile.required_app_id(agent_id)}\n\n"
                    f"XCTest installs the runner under the '.xctrunner' identifier and Xcode\n"
                    f"matches the profile against that full string, so an explicit profile must\n"
                    f"itself end in '.xctrunner'. This is why WebDriverAgent's IntegrationApp\n"
                    f"builds against such a profile while its runner does not.\n\n"
                    f"Ask for one of these, then re-run:\n"
                    f"  - an App ID and development profile for "
                    f"{profile.required_app_id(agent_id)}, or\n"
                    f"  - a wildcard profile, e.g. {agent_id.rsplit('.', 1)[0]}.*\n\n"
                    f"The profile must be iOS App Development and include {device.udid}.\n"
                    f"Pass --force to attempt the build anyway."
                )
                return 2
            if not device.is_simulator and not profile.provisions_device(device.udid):
                print(f"          WARNING: the profile does not provision {device.udid}")

    build = builder.build_for_testing(
        device, development_team=args.team, signing_style=signing_style
    )
    builder.install_demo_app(device, build)

    print(f"xctestrun: {build.xctestrun_path}")
    print(f"runner:    {build.runner_app}")
    print("Setup complete. Start the agent with `sandstorm ios start`.")
    return 0


def _plan_bundle_ids(
    profile: ProvisioningProfile | None, args: argparse.Namespace
) -> tuple[str | None, str | None, str | None]:
    """Chooses bundle identifiers, deriving them from an explicit profile.

    An explicit (non-wildcard) profile can only sign one identifier. XCTest
    always installs the runner as ``<agent id>.xctrunner``, so a profile whose
    app ID ends in ``.xctrunner`` tells us exactly what the agent must be
    called; anything else cannot sign an XCTest runner at all.
    """
    prefix = args.bundle_prefix
    agent = args.agent_bundle_id
    demo = args.demo_bundle_id

    if profile is not None and not agent and not prefix:
        agent = profile.agent_bundle_id_for_runner()

    if prefix:
        agent = agent or f"{prefix}.sandstormagent"
        demo = demo or f"{prefix}.sandstormdemo"
    return prefix, agent, demo


def cmd_profiles(args: argparse.Namespace) -> int:
    profiles = list_profiles(include_expired=args.all)
    if not profiles:
        print("No provisioning profiles are installed.")
        print("Copy a .mobileprovision file into")
        print("  ~/Library/Developer/Xcode/UserData/Provisioning Profiles/")
        return 1

    device = resolve_device(args.udid) if args.udid else None
    for profile in profiles:
        print(profile.describe())
        print(f"  uuid     {profile.uuid}")
        print(f"  team     {profile.team_id} {profile.team_name}".rstrip())
        print(f"  app id   {profile.bundle_id_pattern}")
        print(f"  expires  {profile.expires:%Y-%m-%d}" if profile.expires else "  expires  unknown")
        print(f"  devices  {len(profile.devices)}")
        if device is not None and not device.is_simulator:
            covered = "yes" if profile.provisions_device(device.udid) else "NO"
            print(f"  covers {device.name}: {covered}")
        print()
    if device is not None:
        print("Use one with:")
        print(f"  sandstorm ios setup --udid {device.udid} --profile '<name or uuid>' \\")
        print("      --bundle-prefix <prefix matching the profile's app id>")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    device = resolve_device(args.udid)
    handle = start_agent(
        device,
        device_port=args.port,
        token=args.token,
        log_level="debug" if args.verbose else "info",
    )

    print("Agent ready.")
    print(f"  device : {device.describe()}")
    print(f"  host   : {handle.host}")
    print(f"  port   : {handle.port}")
    print(f"  token  : {handle.token}")
    print("\nExport these to attach from another shell:")
    for key, value in handle.environment().items():
        print(f"  export {key}={value}")

    stopping = False

    def _shutdown(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("\nPress Ctrl+C to stop.")
    try:
        while not stopping:
            time.sleep(0.5)
    finally:
        handle.stop()
    return 0


def cmd_ping(args: argparse.Namespace) -> int:
    """Milestone 1: PING from Python, PONG from the device."""
    device = IOSDevice(args.udid, host=args.host, port=args.port, token=args.token)
    device.connect(retries=args.retries)
    info = device.info
    latency = device.ping()
    print(f"PONG from {info.name} (iOS {info.ios_version}, {'simulator' if info.is_simulator else 'device'})")
    print(f"  agent    : {device.session.agent_version}")
    print(f"  session  : {device.session.session_id}")
    print(f"  latency  : {latency * 1000:.1f} ms")
    print(f"  screen   : {info.screen_width:.0f}x{info.screen_height:.0f} @{info.screen_scale:.0f}x")
    device.disconnect()
    return 0


def cmd_inspector(args: argparse.Namespace) -> int:
    try:
        from sandstorm_inspector.app import main as inspector_main
    except ImportError as exc:  # pragma: no cover - optional dependency
        print(f"Inspector requires PySide6: pip install 'sandstorm-ios[inspector]' ({exc})")
        return 1
    return inspector_main(
        host=args.host, port=args.port, token=args.token, bundle_id=args.bundle_id
    )


# -- Parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sandstorm", description="Sandstorm iOS Driver")
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="group", required=True)

    ios = subparsers.add_parser("ios", help="iOS device commands")
    ios_sub = ios.add_subparsers(dest="command", required=True)

    devices = ios_sub.add_parser("devices", help="List simulators and connected iPhones")
    devices.add_argument("--json", action="store_true")
    devices.add_argument("--simulators-only", action="store_true")
    devices.add_argument("--physical-only", action="store_true")
    devices.set_defaults(func=cmd_devices)

    setup = ios_sub.add_parser("setup", help="Detect Xcode, build, sign and install the agent")
    setup.add_argument("--udid")
    setup.add_argument("--team", help="DEVELOPMENT_TEAM for physical devices")
    setup.add_argument(
        "--profile",
        help="Provisioning profile name or UUID. Switches to manual signing, which "
        "works without an Apple ID in Xcode. See `sandstorm ios profiles`.",
    )
    setup.add_argument(
        "--bundle-prefix",
        help="Rebrand the agent and demo bundle identifiers, e.g. com.company, so they "
        "fall under an existing wildcard profile",
    )
    setup.add_argument(
        "--agent-bundle-id",
        help="Exact agent identifier. The installed runner becomes <id>.xctrunner, which "
        "is what an explicit provisioning profile must match.",
    )
    setup.add_argument("--demo-bundle-id", help="Exact demo app identifier")
    setup.add_argument(
        "--no-demo",
        action="store_true",
        help="Do not build the bundled demo app, so only the agent needs a profile",
    )
    setup.add_argument(
        "--force",
        action="store_true",
        help="Build even when the chosen profile cannot sign the XCTest runner",
    )
    setup.set_defaults(func=cmd_setup)

    profiles = ios_sub.add_parser("profiles", help="List installed provisioning profiles")
    profiles.add_argument("--udid", help="Report whether each profile provisions this device")
    profiles.add_argument("--all", action="store_true", help="Include expired profiles")
    profiles.set_defaults(func=cmd_profiles)

    start = ios_sub.add_parser("start", help="Start the XCTest agent and the tunnel")
    start.add_argument("--udid")
    start.add_argument("--port", type=int, default=None, help="Agent port on the device")
    start.add_argument("--token", default=None)
    start.set_defaults(func=cmd_start)

    ping = ios_sub.add_parser("ping", help="Ping a running agent")
    ping.add_argument("--udid")
    ping.add_argument("--host", default=None)
    ping.add_argument("--port", type=int, default=None)
    ping.add_argument("--token", default=None)
    ping.add_argument("--retries", type=int, default=3)
    ping.set_defaults(func=cmd_ping)

    inspector = ios_sub.add_parser("inspector", help="Launch the desktop Inspector")
    inspector.add_argument("--host", default=None)
    inspector.add_argument("--port", type=int, default=None)
    inspector.add_argument("--token", default=None)
    inspector.add_argument(
        "--bundle-id", default=None, help="Pre-fill the app bundle identifier field"
    )
    inspector.set_defaults(func=cmd_inspector)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    try:
        return int(args.func(args))
    except IOSError as exc:
        logger.error("%s: %s", type(exc).__name__, exc)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
