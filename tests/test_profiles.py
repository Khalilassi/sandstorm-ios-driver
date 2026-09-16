"""Unit tests for provisioning profile matching."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sandstorm_controller.profiles import ProvisioningProfile


def _profile(app_id: str, devices: tuple[str, ...] = (), expires_in_days: int = 30) -> ProvisioningProfile:
    return ProvisioningProfile(
        path=Path("/tmp/example.mobileprovision"),
        uuid="0000-1111",
        name="Example",
        team_id="ABCDE12345",
        team_name="Example Team",
        app_id=app_id,
        expires=dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=expires_in_days),
        devices=devices,
    )


def test_wildcard_profile_matches_any_bundle_id() -> None:
    profile = _profile("ABCDE12345.*")
    assert profile.is_wildcard
    assert profile.matches_bundle_id("com.company.sandstormagent.xctrunner")


def test_prefix_wildcard_matches_only_its_prefix() -> None:
    profile = _profile("ABCDE12345.com.company.*")
    assert profile.matches_bundle_id("com.company.sandstormagent.xctrunner")
    assert not profile.matches_bundle_id("com.other.app")


def test_explicit_profile_matches_exactly() -> None:
    profile = _profile("ABCDE12345.com.company.app")
    assert profile.matches_bundle_id("com.company.app")
    assert not profile.matches_bundle_id("com.company.app.xctrunner")


def test_team_prefix_is_stripped_from_the_pattern() -> None:
    assert _profile("ABCDE12345.com.company.*").bundle_id_pattern == "com.company.*"


def test_device_provisioning_is_explicit() -> None:
    profile = _profile("ABCDE12345.*", devices=("00001111-000A11AA1111AA1A",))
    assert profile.provisions_device("00001111-000A11AA1111AA1A")
    assert not profile.provisions_device("00002222-000B22BB2222BB2B")
    # A distribution profile lists no devices and cannot run development builds.
    assert not _profile("ABCDE12345.*").provisions_device("00001111-000A11AA1111AA1A")


def test_expiry_is_detected() -> None:
    assert _profile("ABCDE12345.*", expires_in_days=-1).is_expired
    assert not _profile("ABCDE12345.*", expires_in_days=1).is_expired


def test_plan_bundle_ids_derives_agent_from_an_xctrunner_profile() -> None:
    import argparse

    from sandstorm_controller.cli import _plan_bundle_ids

    args = argparse.Namespace(
        bundle_prefix=None, agent_bundle_id=None, demo_bundle_id=None
    )
    profile = _profile("ABCDE12345.com.company.automation.xctrunner")
    prefix, agent, demo = _plan_bundle_ids(profile, args)
    # The runner gets '.xctrunner' appended, so the agent must not include it.
    assert agent == "com.company.automation"
    assert prefix is None and demo is None


def test_plan_bundle_ids_uses_an_explicit_profile_verbatim() -> None:
    import argparse

    from sandstorm_controller.cli import _plan_bundle_ids

    args = argparse.Namespace(
        bundle_prefix=None, agent_bundle_id=None, demo_bundle_id=None
    )
    profile = _profile("ABCDE12345.com.company.qa.automationTest")
    # Xcode accepts a profile whose app ID equals the agent identifier for an
    # XCTest runner, which is how WebDriverAgent is signed against explicit
    # profiles; the runner itself becomes <id>.xctrunner.
    assert _plan_bundle_ids(profile, args)[1] == "com.company.qa.automationTest"


def test_signs_runner_requires_the_xctrunner_app_id() -> None:
    # Xcode matches the profile against the full runner identifier, so a profile
    # for the bare identifier signs an ordinary app but never the runner.
    assert not _profile("ABCDE12345.com.company.automation").signs_runner("com.company.automation")
    assert _profile("ABCDE12345.com.company.automation.xctrunner").signs_runner(
        "com.company.automation"
    )
    assert _profile("ABCDE12345.*").signs_runner("anything.at.all")
    assert not _profile("ABCDE12345.com.other.app").signs_runner("com.company.automation")


def test_plan_bundle_ids_prefers_explicit_flags() -> None:
    import argparse

    from sandstorm_controller.cli import _plan_bundle_ids

    args = argparse.Namespace(
        bundle_prefix=None, agent_bundle_id="com.chosen.agent", demo_bundle_id=None
    )
    profile = _profile("ABCDE12345.com.company.automation.xctrunner")
    assert _plan_bundle_ids(profile, args)[1] == "com.chosen.agent"
