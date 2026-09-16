"""Recorder and code generator tests. No Qt involved."""

from __future__ import annotations

import ast

import pytest

from sandstorm_inspector.locators import best_locator, inline
from sandstorm_inspector.recorder import Recorder, describe_target, function_name, summarize

TREE = {
    "path": "0",
    "type": "XCUIElementTypeApplication",
    "identifier": "",
    "label": "Demo",
    "frame": {"x": 0, "y": 0, "width": 390, "height": 844},
    "children": [
        {
            "path": "0/0",
            "type": "XCUIElementTypeTextField",
            "identifier": "username",
            "label": "Username",
            "frame": {"x": 20, "y": 100, "width": 350, "height": 44},
            "children": [],
        },
        {
            "path": "0/1",
            "type": "XCUIElementTypeButton",
            "identifier": "",
            "label": "Login",
            "frame": {"x": 20, "y": 200, "width": 350, "height": 44},
            "children": [],
        },
    ],
}


def _recorder() -> Recorder:
    recorder = Recorder()
    recorder.start()
    return recorder


def test_nothing_is_recorded_until_started() -> None:
    recorder = Recorder()
    assert recorder.record_tap('page.get_by_id("a")', "a") is None
    assert len(recorder) == 0

    recorder.start()
    assert recorder.record_tap('page.get_by_id("a")', "a") is not None
    assert len(recorder) == 1

    recorder.stop()
    assert recorder.record_tap('page.get_by_id("b")', "b") is None
    assert len(recorder) == 1


def test_undo_and_clear() -> None:
    recorder = _recorder()
    recorder.record_launch("com.acme.app")
    recorder.record_tap('page.get_by_id("a")', "a")
    assert len(recorder) == 2

    undone = recorder.undo()
    assert undone is not None and undone.action == "tap"
    assert len(recorder) == 1

    recorder.clear()
    assert len(recorder) == 0
    assert recorder.undo() is None


def test_tap_falls_back_to_coordinates_without_a_locator() -> None:
    recorder = _recorder()
    step = recorder.record_tap(None, "point", (0.5, 0.25))
    assert step is not None
    assert step.code == "page.tap(0.5000, 0.2500)"
    assert step.uses_coordinates

    assert recorder.record_tap(None, "point") is None


def test_text_is_escaped_in_generated_code() -> None:
    recorder = _recorder()
    recorder.record_fill('page.get_by_id("q")', "q", 'say "hi"\\now')
    code = recorder.steps[0].code
    assert code == 'page.get_by_id("q").fill("say \\"hi\\"\\\\now")'
    ast.parse(code)


def test_launch_defaults_to_a_fresh_start() -> None:
    recorder = _recorder()
    recorder.record_launch("com.acme.app")
    recorder.record_launch("com.acme.app", relaunch=False)
    assert recorder.steps[0].code == "app.launch(relaunch=True)"
    assert recorder.steps[1].code == "app.launch()"


def test_generated_pytest_module_is_valid_python() -> None:
    recorder = _recorder()
    recorder.record_launch("com.acme.app")
    recorder.record_fill('page.get_by_id("username")', "username", "khalil")
    recorder.record_tap('page.get_by_label("Login")', "Login")
    recorder.record_wait_for('page.get_by_text("Welcome")', "Welcome", "visible")
    recorder.record_assert_visible('page.get_by_text("Welcome")', "Welcome")
    recorder.record_assert_text('page.get_by_id("title")', "title", "Home")
    recorder.record_swipe((0.5, 0.75), (0.5, 0.25))
    recorder.record_screenshot("home.png")
    recorder.record_terminate("com.acme.app")

    code = recorder.generate(bundle_id="com.acme.app", name="Login works")
    ast.parse(code)
    assert "def test_login_works(device):" in code
    assert 'BUNDLE_ID = "com.acme.app"' in code
    assert "device.disconnect()" in code
    assert 'page.get_by_id("username").fill("khalil")' in code
    assert "import os" in code and "import pytest" in code


def test_generated_script_style_is_valid_python() -> None:
    recorder = _recorder()
    recorder.record_launch("com.acme.app")
    recorder.record_tap('page.get_by_id("go")', "go")

    code = recorder.generate(bundle_id="com.acme.app", style="script", port=9000)
    ast.parse(code)
    assert "def main() -> None:" in code
    assert "    finally:" in code
    assert '"9000"' in code
    assert "import os" in code


def test_empty_recording_still_generates_runnable_code() -> None:
    code = Recorder().generate(bundle_id="com.acme.app")
    ast.parse(code)
    assert "nothing was recorded" in code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Login works", "test_login_works"),
        ("test_already_prefixed", "test_already_prefixed"),
        ("  ", "test_recorded_flow"),
        ("2 factor auth", "test_2_factor_auth"),
        ("checkout: pay!", "test_checkout_pay"),
    ],
)
def test_function_name(raw: str, expected: str) -> None:
    assert function_name(raw) == expected


def test_describe_target_prefers_identifier_then_label() -> None:
    assert describe_target(TREE["children"][0]) == "username"
    assert describe_target(TREE["children"][1]) == "Login"
    assert describe_target({"type": "XCUIElementTypeCell"}) == "XCUIElementTypeCell"
    assert describe_target(None) == "screen"


def test_recorded_locator_matches_the_suggestion_shown() -> None:
    suggestion = best_locator(TREE["children"][0], TREE)
    assert suggestion is not None

    recorder = _recorder()
    step = recorder.record_tap(suggestion.inline_code, describe_target(TREE["children"][0]))
    assert step is not None
    assert step.code == 'page.get_by_id("username").tap()'
    assert suggestion.criteria == {"identifier": "username"}


def test_inline_collapses_multiline_locators() -> None:
    multiline = 'page.locator(\n    type="XCUIElementTypeButton",\n    label="Login"\n)'
    assert inline(multiline) == 'page.locator(type="XCUIElementTypeButton", label="Login")'
    ast.parse(inline(multiline))


def test_summarize_numbers_the_steps() -> None:
    recorder = _recorder()
    recorder.record_launch("com.acme.app")
    recorder.record_tap('page.get_by_id("a")', "a")
    assert summarize(recorder.steps).splitlines() == [
        "  1. launch  com.acme.app  [fresh]",
        "  2. tap  a",
    ]
