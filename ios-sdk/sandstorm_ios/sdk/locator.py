"""Playwright-style element locators."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping

from ..errors import IOSElementNotFound
from ..protocol.selector import Selector

if TYPE_CHECKING:  # pragma: no cover
    from .session import IOSSession

logger = logging.getLogger("sandstorm.locator")

WaitState = Literal["exists", "not_exists", "visible", "not_visible", "enabled"]


@dataclass(frozen=True, slots=True)
class Frame:
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> "Frame":
        return cls(
            x=float(payload.get("x", 0.0)),
            y=float(payload.get("y", 0.0)),
            width=float(payload.get("width", 0.0)),
            height=float(payload.get("height", 0.0)),
        )

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


@dataclass(frozen=True, slots=True)
class ElementAttributes:
    """A snapshot of one element's attributes at a point in time."""

    exists: bool
    type: str = ""
    identifier: str = ""
    label: str = ""
    value: Any = None
    title: str = ""
    placeholder: str | None = None
    enabled: bool = False
    selected: bool = False
    visible: bool | None = None
    frame: Frame = Frame(0, 0, 0, 0)

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> "ElementAttributes":
        return cls(
            exists=bool(payload.get("exists", False)),
            type=str(payload.get("type", "")),
            identifier=str(payload.get("identifier", "")),
            label=str(payload.get("label", "")),
            value=payload.get("value"),
            title=str(payload.get("title", "")),
            placeholder=payload.get("placeholder"),
            enabled=bool(payload.get("enabled", False)),
            selected=bool(payload.get("selected", False)),
            visible=payload.get("hittable", payload.get("visible")),
            frame=Frame.from_wire(payload.get("frame") or {}),
        )


class Locator:
    """A lazy handle to an element.

    Nothing is resolved until an action is performed, exactly like a Playwright
    locator. Resolution always happens agent-side so that a retry never costs a
    USB round trip per candidate element.
    """

    def __init__(self, session: "IOSSession", selector: Selector, *, timeout: float = 10.0) -> None:
        self._session = session
        self._selector = selector
        self._timeout = timeout

    # -- Refinement ----------------------------------------------------------

    @property
    def selector(self) -> Selector:
        return self._selector

    def nth(self, index: int) -> "Locator":
        return Locator(self._session, self._selector.with_index(index), timeout=self._timeout)

    def first(self) -> "Locator":
        return self.nth(0)

    def locator(self, **criteria: Any) -> "Locator":
        """Scopes a new locator to descendants of this one."""
        return Locator(self._session, self._selector.child(**criteria), timeout=self._timeout)

    def with_timeout(self, timeout: float) -> "Locator":
        return Locator(self._session, self._selector, timeout=timeout)

    # -- Queries -------------------------------------------------------------

    def exists(self, *, timeout: float = 0.0) -> bool:
        result = self._session.result(
            "element.exists", {"selector": self._selector.to_wire(), "timeout": timeout}
        )
        return bool(result.get("exists", False))

    def count(self, *, limit: int = 50) -> int:
        result = self._session.result(
            "element.findAll", {"selector": self._selector.to_wire(), "limit": limit}
        )
        return int(result.get("count", 0))

    def all(self, *, limit: int = 50) -> list[ElementAttributes]:
        result = self._session.result(
            "element.findAll", {"selector": self._selector.to_wire(), "limit": limit}
        )
        return [ElementAttributes.from_wire(item) for item in result.get("elements", [])]

    def attributes(self, *, timeout: float | None = None) -> ElementAttributes:
        result = self._session.result(
            "element.getAttributes",
            {"selector": self._selector.to_wire(), "timeout": self._resolve_timeout(timeout)},
        )
        return ElementAttributes.from_wire(result)

    def text_content(self) -> str:
        attributes = self.attributes()
        return attributes.label or str(attributes.value or "") or attributes.title

    def is_visible(self) -> bool:
        return bool(self.attributes().visible)

    def is_enabled(self) -> bool:
        return self.attributes().enabled

    # -- Actions -------------------------------------------------------------

    def tap(self, *, timeout: float | None = None) -> "Locator":
        self._session.invoke(
            "element.tap",
            {"selector": self._selector.to_wire(), "timeout": self._resolve_timeout(timeout)},
        )
        return self

    click = tap

    def long_press(self, *, duration: float = 1.0, timeout: float | None = None) -> "Locator":
        self._session.invoke(
            "element.longPress",
            {
                "selector": self._selector.to_wire(),
                "duration": duration,
                "timeout": self._resolve_timeout(timeout),
            },
        )
        return self

    def fill(self, text: str, *, timeout: float | None = None) -> "Locator":
        """Clears the field and types ``text`` (Playwright semantics)."""
        self._session.invoke(
            "element.typeText",
            {
                "selector": self._selector.to_wire(),
                "text": text,
                "clear": True,
                "timeout": self._resolve_timeout(timeout),
            },
        )
        return self

    def type_text(self, text: str, *, timeout: float | None = None) -> "Locator":
        """Appends ``text`` without clearing."""
        self._session.invoke(
            "element.typeText",
            {
                "selector": self._selector.to_wire(),
                "text": text,
                "clear": False,
                "timeout": self._resolve_timeout(timeout),
            },
        )
        return self

    def clear(self, *, timeout: float | None = None) -> "Locator":
        self._session.invoke(
            "element.clear",
            {"selector": self._selector.to_wire(), "timeout": self._resolve_timeout(timeout)},
        )
        return self

    def wait_for(self, *, state: WaitState = "visible", timeout: float | None = None) -> "Locator":
        """Waits for ``state``.

        The wait loop runs inside the XCTest agent, so a 10 second wait is one
        request instead of dozens of polls across the USB tunnel.
        """
        effective = self._resolve_timeout(timeout)
        self._session.invoke(
            "element.waitFor",
            {"selector": self._selector.to_wire(), "state": state, "timeout": effective},
            timeout=effective + 10.0,
        )
        return self

    def require(self) -> ElementAttributes:
        attributes = self.attributes()
        if not attributes.exists:
            raise IOSElementNotFound(f"Element not found: {self._selector.describe()}")
        return attributes

    def _resolve_timeout(self, timeout: float | None) -> float:
        return self._timeout if timeout is None else timeout

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Locator({self._selector.describe()})"
