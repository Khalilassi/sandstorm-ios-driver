"""Discovery and inspection of installed provisioning profiles.

Manual code signing is the only option on machines where an Apple ID cannot be
added to Xcode. That requires knowing which profiles already exist, which team
they belong to, which app IDs they cover and which devices they provision --
none of which Xcode surfaces from the command line.
"""

from __future__ import annotations

import datetime as _datetime
import logging
import plistlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("sandstorm.profiles")

PROFILE_DIRECTORIES = (
    Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    Path.home() / "Library/MobileDevice/Provisioning Profiles",
)


@dataclass(frozen=True)
class ProvisioningProfile:
    """One installed ``.mobileprovision`` file."""

    path: Path
    uuid: str
    name: str
    team_id: str
    team_name: str
    app_id: str
    expires: _datetime.datetime | None
    devices: tuple[str, ...] = field(default=())
    platforms: tuple[str, ...] = field(default=())

    @property
    def is_wildcard(self) -> bool:
        return self.app_id.endswith("*")

    @property
    def is_expired(self) -> bool:
        if self.expires is None:
            return False
        return self.expires < _datetime.datetime.now(tz=self.expires.tzinfo)

    @property
    def bundle_id_pattern(self) -> str:
        """The app ID with the leading team prefix removed."""
        prefix = f"{self.team_id}."
        if self.app_id.startswith(prefix):
            return self.app_id[len(prefix) :]
        return self.app_id

    def matches_bundle_id(self, bundle_id: str) -> bool:
        pattern = self.bundle_id_pattern
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            return bundle_id.startswith(pattern[:-1])
        return bundle_id == pattern

    def provisions_device(self, udid: str) -> bool:
        # An empty device list means a distribution profile, which cannot be
        # used for development builds; treat it as not provisioning anything.
        return udid in self.devices

    def signs_runner(self, agent_bundle_id: str) -> bool:
        """Whether this profile can sign the XCTest runner for ``agent_bundle_id``.

        XCTest installs the runner as ``<agent id>.xctrunner`` and Xcode matches
        the profile against that full identifier, so an explicit profile must
        itself end in ``.xctrunner``. A profile for the bare identifier signs an
        ordinary app only -- this is why WebDriverAgent's IntegrationApp builds
        against such a profile while its runner does not.
        """
        return self.matches_bundle_id(f"{agent_bundle_id}.xctrunner")

    def required_app_id(self, agent_bundle_id: str) -> str:
        """The App ID that must exist for this agent's runner to be signed."""
        return f"{agent_bundle_id}.xctrunner"

    def agent_bundle_id_for_runner(self) -> str | None:
        """The agent identifier this explicit profile implies, if any."""
        if self.is_wildcard:
            return None
        pattern = self.bundle_id_pattern
        if pattern.endswith(".xctrunner"):
            return pattern[: -len(".xctrunner")]
        return pattern

    def describe(self) -> str:
        flags = []
        if self.is_expired:
            flags.append("EXPIRED")
        if self.is_wildcard:
            flags.append("wildcard")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        return f"{self.name} ({self.bundle_id_pattern}, team {self.team_id}){suffix}"


def _decode(path: Path) -> dict | None:
    """Reads the CMS-signed plist inside a ``.mobileprovision`` file."""
    result = subprocess.run(
        ["security", "cms", "-D", "-i", str(path)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        logger.debug("Could not decode %s", path)
        return None
    try:
        return plistlib.loads(result.stdout)
    except (plistlib.InvalidFileException, ValueError):
        logger.debug("Malformed profile %s", path)
        return None


def _to_profile(path: Path, payload: dict) -> ProvisioningProfile | None:
    entitlements = payload.get("Entitlements") or {}
    app_id = entitlements.get("application-identifier") or ""
    teams = payload.get("TeamIdentifier") or []
    if not app_id or not teams:
        return None
    return ProvisioningProfile(
        path=path,
        uuid=str(payload.get("UUID", "")),
        name=str(payload.get("Name", path.stem)),
        team_id=str(teams[0]),
        team_name=str(payload.get("TeamName", "")),
        app_id=str(app_id),
        expires=payload.get("ExpirationDate"),
        devices=tuple(payload.get("ProvisionedDevices") or ()),
        platforms=tuple(payload.get("Platform") or ()),
    )


def list_profiles(*, include_expired: bool = False) -> list[ProvisioningProfile]:
    """Returns every installed provisioning profile, newest expiry first."""
    profiles: list[ProvisioningProfile] = []
    seen: set[str] = set()
    for directory in PROFILE_DIRECTORIES:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.mobileprovision")) + sorted(
            directory.glob("*.provisionprofile")
        ):
            payload = _decode(path)
            if payload is None:
                continue
            profile = _to_profile(path, payload)
            if profile is None or profile.uuid in seen:
                continue
            seen.add(profile.uuid)
            if profile.is_expired and not include_expired:
                continue
            profiles.append(profile)
    profiles.sort(key=lambda p: (p.expires is None, p.expires), reverse=True)
    return profiles


def find_profile(reference: str) -> ProvisioningProfile | None:
    """Looks a profile up by UUID or by name."""
    for profile in list_profiles(include_expired=True):
        if reference in (profile.uuid, profile.name):
            return profile
    return None


def usable_profiles(
    udid: str | None = None, bundle_ids: tuple[str, ...] = ()
) -> list[ProvisioningProfile]:
    """Profiles that provision the device and cover every supplied bundle ID."""
    candidates = []
    for profile in list_profiles():
        if udid and not profile.provisions_device(udid):
            continue
        if bundle_ids and not all(profile.matches_bundle_id(b) for b in bundle_ids):
            continue
        candidates.append(profile)
    return candidates
