"""Snapshot tree helpers: hit testing, flattening and labelling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from .locators import iter_nodes


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(self.width, 0.0) * max(self.height, 0.0)

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height

    @classmethod
    def from_node(cls, node: Mapping[str, Any]) -> "Rect":
        frame = node.get("frame") or {}
        return cls(
            x=float(frame.get("x", 0.0)),
            y=float(frame.get("y", 0.0)),
            width=float(frame.get("width", 0.0)),
            height=float(frame.get("height", 0.0)),
        )


def hit_test(root: Mapping[str, Any], x: float, y: float, *, visible_only: bool = True) -> Mapping[str, Any] | None:
    """Returns the *smallest* element whose frame contains the point.

    This is what makes "click the screenshot, select in the tree" feel right:
    the tightest hit is almost always the control the user meant.
    """
    best: Mapping[str, Any] | None = None
    best_area = float("inf")
    for node in iter_nodes(root):
        if visible_only and node.get("visible") is False:
            continue
        rect = Rect.from_node(node)
        if rect.area <= 0 or not rect.contains(x, y):
            continue
        if rect.area < best_area:
            best, best_area = node, rect.area
    return best


def find_by_path(root: Mapping[str, Any], path: str) -> Mapping[str, Any] | None:
    for node in iter_nodes(root):
        if node.get("path") == path:
            return node
    return None


def node_title(node: Mapping[str, Any]) -> str:
    """Short, human friendly label used in the hierarchy tree."""
    element_type = str(node.get("type", "")).replace("XCUIElementType", "")
    identifier = (node.get("identifier") or "").strip()
    label = (node.get("label") or "").strip()
    value = node.get("value")

    detail = identifier or label or (str(value) if isinstance(value, str) else "")
    if detail:
        detail = detail if len(detail) <= 40 else detail[:37] + "..."
        return f"{element_type} — {detail}"
    return element_type


def describe(node: Mapping[str, Any]) -> dict[str, str]:
    """Attribute table rendered in the Inspector's detail pane."""
    rect = Rect.from_node(node)
    return {
        "Type": str(node.get("type", "")),
        "Identifier": str(node.get("identifier") or ""),
        "Label": str(node.get("label") or ""),
        "Value": "" if node.get("value") is None else str(node.get("value")),
        "Title": str(node.get("title") or ""),
        "Placeholder": str(node.get("placeholder") or ""),
        "Frame": f"x={rect.x:.0f} y={rect.y:.0f} w={rect.width:.0f} h={rect.height:.0f}",
        "Enabled": str(bool(node.get("enabled", False))),
        "Visible": str(bool(node.get("visible", False))),
        "Path": str(node.get("path") or ""),
    }


def walk_with_depth(node: Mapping[str, Any], depth: int = 0) -> Iterator[tuple[Mapping[str, Any], int]]:
    yield node, depth
    for child in node.get("children", []) or []:
        yield from walk_with_depth(child, depth + 1)


def count_nodes(node: Mapping[str, Any]) -> int:
    return sum(1 for _ in iter_nodes(node))
