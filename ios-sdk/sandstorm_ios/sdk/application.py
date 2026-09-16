"""Application lifecycle handle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Mapping, Sequence

from .page import IOSPage

if TYPE_CHECKING:  # pragma: no cover
    from .session import IOSSession

logger = logging.getLogger("sandstorm.app")


class IOSApplication:
    """One application under test, addressed by bundle identifier."""

    def __init__(self, session: "IOSSession", bundle_id: str, *, default_timeout: float = 10.0) -> None:
        self._session = session
        self._bundle_id = bundle_id
        self._page = IOSPage(session, default_timeout=default_timeout)

    @property
    def bundle_id(self) -> str:
        return self._bundle_id

    @property
    def page(self) -> IOSPage:
        return self._page

    def launch(
        self,
        *,
        arguments: Sequence[str] | None = None,
        environment: Mapping[str, str] | None = None,
        relaunch: bool = False,
        timeout: float = 30.0,
    ) -> "IOSApplication":
        self._session.invoke(
            "app.launch",
            {
                "bundleId": self._bundle_id,
                "arguments": list(arguments or []),
                "environment": dict(environment or {}),
                "relaunch": relaunch,
                "timeout": timeout,
            },
            timeout=timeout + 15.0,
        )
        logger.info("Launched %s", self._bundle_id)
        return self

    def activate(self) -> "IOSApplication":
        self._session.invoke("app.activate", {"bundleId": self._bundle_id})
        return self

    def terminate(self) -> "IOSApplication":
        self._session.invoke("app.terminate", {"bundleId": self._bundle_id})
        return self

    @property
    def is_running(self) -> bool:
        result = self._session.result("app.state", {"bundleId": self._bundle_id})
        return bool(result.get("running", False))

    def __enter__(self) -> "IOSApplication":
        return self.launch()

    def __exit__(self, *_: object) -> None:
        self.terminate()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"IOSApplication({self._bundle_id!r})"
