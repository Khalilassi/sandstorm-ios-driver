"""Unit tests for the Xcode/SDK compatibility preflight."""

from __future__ import annotations

import pytest

from sandstorm_controller import build as build_module
from sandstorm_controller.devices import DeviceKind, DeviceRecord
from sandstorm_ios.errors import IOSSetupError


def _device(kind: DeviceKind, ios_version: str) -> DeviceRecord:
    return DeviceRecord(
        udid="00002222-000B22BB2222BB2B",
        name="Test iPhone",
        kind=kind,
        ios_version=ios_version,
        state="connected",
    )


def test_rejects_device_newer_than_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_module, "iphoneos_sdk_version", lambda: "18.1")
    with pytest.raises(IOSSetupError) as excinfo:
        build_module.verify_sdk_supports(_device(DeviceKind.PHYSICAL, "26.5.2"))
    message = str(excinfo.value)
    assert "iOS 18.1 SDK" in message
    assert "iOS 26.5.2" in message
    assert "xcode-select" in message


def test_accepts_device_at_or_below_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_module, "iphoneos_sdk_version", lambda: "26.5")
    build_module.verify_sdk_supports(_device(DeviceKind.PHYSICAL, "26.5.2"))
    build_module.verify_sdk_supports(_device(DeviceKind.PHYSICAL, "18.4"))


def test_override_allows_a_newer_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_module, "iphoneos_sdk_version", lambda: "18.1")
    monkeypatch.setenv("SANDSTORM_SKIP_SDK_CHECK", "1")
    build_module.verify_sdk_supports(_device(DeviceKind.PHYSICAL, "26.5.2"))


def test_diagnoses_missing_xcode_account() -> None:
    output = (
        "error: No Accounts: Add a new account in Accounts settings. (in target 'SandstormAgent')\n"
        "error: No profiles for 'com.sandstorm.agent.xctrunner' were found.\n"
        "DVTDeveloperAccountManager: ... missing Xcode-Token"
    )
    hint = build_module._diagnose_build_failure(output)
    assert "Settings > Accounts" in hint
    # The account error subsumes the profile error; only one remedy is offered.
    assert hint.count("- ") == 1


def test_diagnoses_missing_profile_without_account_error() -> None:
    hint = build_module._diagnose_build_failure("error: No profiles for 'com.sandstorm.demo' were found.")
    assert "--team" in hint


def test_no_diagnosis_for_unknown_failures() -> None:
    assert build_module._diagnose_build_failure("error: value of type 'X' has no member 'y'") == ""


def test_simulators_and_unknown_sdks_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_module, "iphoneos_sdk_version", lambda: "18.1")
    build_module.verify_sdk_supports(_device(DeviceKind.SIMULATOR, "26.5"))
    monkeypatch.setattr(build_module, "iphoneos_sdk_version", lambda: None)
    build_module.verify_sdk_supports(_device(DeviceKind.PHYSICAL, "26.5.2"))
