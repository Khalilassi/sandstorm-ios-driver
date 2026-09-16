"""Page level API: locator factories, gestures, screenshots and snapshots."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from ..errors import IOSError
from ..protocol.selector import Selector, Strategy
from .locator import Locator

if TYPE_CHECKING:  # pragma: no cover
    from .session import IOSSession

logger = logging.getLogger("sandstorm.page")

Point = tuple[float, float]


class IOSPage:
    """The current screen of the application under test."""

    def __init__(self, session: "IOSSession", *, default_timeout: float = 10.0) -> None:
        self._session = session
        self._default_timeout = default_timeout

    @property
    def session(self) -> "IOSSession":
        return self._session

    def set_default_timeout(self, timeout: float) -> None:
        self._default_timeout = timeout

    # -- Locator factories ---------------------------------------------------

    def locator(self, **criteria: Any) -> Locator:
        """Builds a compound locator, e.g. ``page.locator(type=..., label=...)``."""
        return Locator(self._session, Selector(**criteria), timeout=self._default_timeout)

    def get_by_id(self, identifier: str) -> Locator:
        """Matches the accessibility identifier. The most stable strategy."""
        return self.locator(identifier=identifier)

    get_by_accessibility_id = get_by_id

    def get_by_text(self, text: str, *, exact: bool = True) -> Locator:
        """Matches label, value, title or placeholder."""
        return self.locator(text=text, exact=exact)

    def get_by_label(self, label: str, *, exact: bool = True) -> Locator:
        return self.locator(label=label, exact=exact)

    def get_by_type(self, element_type: str) -> Locator:
        return self.locator(type=element_type)

    def get_by_predicate(self, predicate: str) -> Locator:
        """Escape hatch: a raw ``NSPredicate`` evaluated by XCTest."""
        return self.locator(predicate=predicate)

    def by_strategy(self, strategy: Strategy, value: str | int) -> Locator:
        return Locator(
            self._session, Selector.by_strategy(strategy, value), timeout=self._default_timeout
        )

    # -- Gestures ------------------------------------------------------------

    def tap(self, x: float, y: float) -> None:
        """Taps a normalized (0..1) coordinate."""
        self._session.invoke("gesture.tap", {"at": {"x": x, "y": y}})

    def long_press(self, x: float, y: float, *, duration: float = 1.0) -> None:
        self._session.invoke(
            "gesture.longPress", {"at": {"x": x, "y": y}, "duration": duration}
        )

    def swipe(self, from_: Point, to: Point, *, duration: float = 0.3) -> None:
        self._session.invoke(
            "gesture.swipe",
            {
                "from": {"x": from_[0], "y": from_[1]},
                "to": {"x": to[0], "y": to[1]},
                "duration": duration,
            },
        )

    def drag(self, from_: Point, to: Point, *, duration: float = 0.8) -> None:
        self._session.invoke(
            "gesture.drag",
            {
                "from": {"x": from_[0], "y": from_[1]},
                "to": {"x": to[0], "y": to[1]},
                "duration": duration,
            },
        )

    def scroll_down(self, *, distance: float = 0.6) -> None:
        center = 0.5
        self.swipe((center, 0.5 + distance / 2), (center, 0.5 - distance / 2))

    def scroll_up(self, *, distance: float = 0.6) -> None:
        center = 0.5
        self.swipe((center, 0.5 - distance / 2), (center, 0.5 + distance / 2))

    # -- Screen --------------------------------------------------------------

    def screenshot(
        self,
        path: str | Path | None = None,
        *,
        scale: float = 1.0,
        quality: float | None = None,
        app_only: bool = False,
    ) -> bytes:
        """Captures the screen.

        Bytes travel in a dedicated binary frame, never base64.
        """
        params: dict[str, Any] = {"scale": scale, "appOnly": app_only}
        if quality is not None:
            params["quality"] = quality

        response = self._session.invoke("screen.screenshot", params, timeout=60.0)
        if response.binary is None:
            raise IOSError("Agent returned a screenshot without its binary payload")
        if path is not None:
            Path(path).write_bytes(response.binary)
        return response.binary

    def snapshot(
        self,
        *,
        max_depth: int = 60,
        include_invisible: bool = True,
        selector: Selector | None = None,
        timeout: float = 60.0,
    ) -> Mapping[str, Any]:
        """Returns the normalized accessibility hierarchy."""
        params: dict[str, Any] = {
            "maxDepth": max_depth,
            "includeInvisible": include_invisible,
        }
        if selector is not None:
            params["selector"] = selector.to_wire()
        return self._session.result("screen.snapshot", params, timeout=timeout)

    # -- Alerts --------------------------------------------------------------

    def accept_alert(self, button: str | None = None) -> None:
        self._session.invoke("alert.accept", {"button": button} if button else {})

    def dismiss_alert(self, button: str | None = None) -> None:
        self._session.invoke("alert.dismiss", {"button": button} if button else {})

    def alert_text(self) -> str:
        return str(self._session.result("alert.text").get("text", ""))

    def set_alert_policy(
        self,
        policy: str = "dismiss",
        buttons: Sequence[str] | None = None,
    ) -> None:
        """Lets the **agent** handle blocking dialogs on its own.

        iOS raises system interruptions ("Save Password?", notification
        permission, ...) at moments a test cannot predict, and they steal every
        subsequent tap. With a policy active the agent clears them during finds,
        interactions and waits — no host round trips and no sprinkled checks.

        :param policy: ``"manual"`` (default agent behaviour), ``"dismiss"``
            (tap the first/left button) or ``"accept"`` (tap the last button).
        :param buttons: Button labels to prefer, in order, before the policy
            fallback — e.g. ``["Not Now", "Don't Allow", "Cancel"]``.
        """
        params: dict[str, Any] = {"policy": policy}
        if buttons:
            params["buttons"] = list(buttons)
        self._session.invoke("session.setAlertPolicy", params)

    def alert_info(self) -> dict[str, Any]:
        """Non-throwing probe: ``{"present": bool, "text": str, "buttons": [str]}``."""
        return self._session.result("alert.info")

    def alert_present(self) -> bool:
        return bool(self.alert_info().get("present", False))

    def handle_alert_if_present(self, button: str | None = None, *, accept: bool = False) -> bool:
        """Dismiss (or accept) a system/app dialog only if one is showing.

        Returns ``True`` when a dialog was handled. Useful for the optional iOS
        prompts ("Save Password?", notification permission) that appear
        non-deterministically in the middle of a flow.
        """
        if not self.alert_present():
            return False
        if accept:
            self.accept_alert(button)
        else:
            self.dismiss_alert(button)
        return True

    # -- Device --------------------------------------------------------------

    def orientation(self, value: str | None = None) -> str:
        params = {"orientation": value} if value else {}
        return str(self._session.result("device.orientation", params).get("orientation", "unknown"))
