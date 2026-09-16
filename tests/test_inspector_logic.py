"""Tests for the Inspector's Qt-free logic (hit testing + locator ranking)."""

from __future__ import annotations

from sandstorm_inspector.hierarchy import Rect, describe, find_by_path, hit_test, node_title
from sandstorm_inspector.locators import best_locator, format_report, recommend

TREE = {
    "type": "XCUIElementTypeWindow",
    "identifier": "",
    "label": "",
    "value": None,
    "enabled": True,
    "visible": True,
    "path": "0",
    "frame": {"x": 0, "y": 0, "width": 393, "height": 852},
    "children": [
        {
            "type": "XCUIElementTypeButton",
            "identifier": "login_button",
            "label": "Login",
            "value": None,
            "enabled": True,
            "visible": True,
            "path": "0.0",
            "frame": {"x": 100, "y": 600, "width": 180, "height": 50},
        },
        {
            "type": "XCUIElementTypeStaticText",
            "identifier": "",
            "label": "Login",
            "value": None,
            "enabled": True,
            "visible": True,
            "path": "0.1",
            "frame": {"x": 100, "y": 200, "width": 180, "height": 30},
        },
    ],
}


def test_hit_test_picks_the_smallest_containing_element() -> None:
    node = hit_test(TREE, 150, 620)
    assert node is not None and node["identifier"] == "login_button"


def test_hit_test_falls_back_to_the_window() -> None:
    node = hit_test(TREE, 5, 5)
    assert node is not None and node["type"] == "XCUIElementTypeWindow"


def test_hit_test_ignores_invisible_nodes() -> None:
    hidden = dict(TREE, children=[dict(TREE["children"][0], visible=False)])
    node = hit_test(hidden, 150, 620)
    assert node is not None and node["type"] == "XCUIElementTypeWindow"


def test_find_by_path() -> None:
    assert find_by_path(TREE, "0.1")["label"] == "Login"
    assert find_by_path(TREE, "9.9") is None


def test_accessibility_identifier_ranks_highest() -> None:
    suggestions = recommend(TREE["children"][0], TREE)
    top = suggestions[0]
    assert top.strategy == "Accessibility ID"
    assert top.score == 5
    assert top.code == 'page.get_by_id("login_button")'


def test_ambiguous_label_is_downranked() -> None:
    suggestions = recommend(TREE["children"][1], TREE)
    label = next(item for item in suggestions if item.strategy == "Label")
    assert label.unique is False
    assert label.score == 2
    # Type + label disambiguates the duplicate, so it must rank above the label.
    assert suggestions[0].score >= label.score


def test_index_is_always_the_last_resort() -> None:
    suggestions = recommend(TREE["children"][0], TREE)
    index = next(item for item in suggestions if item.strategy == "Index")
    assert index.score == 2
    assert suggestions[-1].score <= index.score


def test_no_xpath_or_coordinates_are_ever_generated() -> None:
    for node in (TREE, TREE["children"][0], TREE["children"][1]):
        for suggestion in recommend(node, TREE):
            assert "//" not in suggestion.code
            assert "xpath" not in suggestion.code.lower()
            assert "tap(" not in suggestion.code


def test_best_locator_and_report() -> None:
    best = best_locator(TREE["children"][0], TREE)
    assert best is not None and best.score == 5
    report = format_report(recommend(TREE["children"][0], TREE))
    assert "Accessibility ID" in report and "5/5" in report


def test_node_title_and_describe() -> None:
    assert node_title(TREE["children"][0]) == "Button — login_button"
    attributes = describe(TREE["children"][0])
    assert attributes["Identifier"] == "login_button"
    assert attributes["Frame"] == "x=100 y=600 w=180 h=50"


def test_rect_area_and_contains() -> None:
    rect = Rect(0, 0, 10, 10)
    assert rect.area == 100
    assert rect.contains(5, 5) and not rect.contains(11, 5)
