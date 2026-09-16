"""The internal selector model shared by the SDK, controller and Inspector."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

Strategy = Literal[
    "accessibilityId",
    "identifier",
    "label",
    "text",
    "type",
    "predicate",
    "index",
]

#: Deliberately no XPath. It is slow over IPC, brittle against layout changes,
#: and it has no native XCUITest equivalent (Appium emulates it by serialising
#: the whole tree on every query).
SUPPORTED_STRATEGIES: tuple[str, ...] = (
    "accessibilityId",
    "identifier",
    "label",
    "text",
    "type",
    "predicate",
    "index",
)


@dataclass(frozen=True, slots=True)
class Selector:
    """A compound element selector.

    Every criterion is ANDed together by the agent in a single ``NSPredicate``,
    which means matching happens inside the application process instead of over
    the USB link.
    """

    type: str | None = None
    identifier: str | None = None
    label: str | None = None
    text: str | None = None
    value: str | None = None
    predicate: str | None = None
    index: int | None = None
    exact: bool = True
    parent: "Selector | None" = None

    # -- Factories -----------------------------------------------------------

    @classmethod
    def by_strategy(cls, strategy: Strategy, value: str | int) -> "Selector":
        if strategy in ("accessibilityId", "identifier"):
            return cls(identifier=str(value))
        if strategy == "label":
            return cls(label=str(value))
        if strategy == "text":
            return cls(text=str(value))
        if strategy == "type":
            return cls(type=str(value))
        if strategy == "predicate":
            return cls(predicate=str(value))
        if strategy == "index":
            return cls(index=int(value))
        raise ValueError(
            f"Unsupported locator strategy {strategy!r}; supported: {', '.join(SUPPORTED_STRATEGIES)}"
        )

    def child(self, **criteria: Any) -> "Selector":
        """Returns a selector scoped to descendants of this one (chaining)."""
        return Selector(parent=self, **criteria)

    def with_index(self, index: int) -> "Selector":
        return replace(self, index=index)

    # -- Serialisation -------------------------------------------------------

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"exact": self.exact}
        if self.type is not None:
            payload["type"] = self.type
        if self.identifier is not None:
            payload["identifier"] = self.identifier
        if self.label is not None:
            payload["label"] = self.label
        if self.text is not None:
            payload["text"] = self.text
        if self.value is not None:
            # ``value_`` avoids colliding with the compact {strategy, value} form.
            payload["value_"] = self.value
        if self.predicate is not None:
            payload["predicate"] = self.predicate
        if self.index is not None:
            payload["index"] = self.index
        if self.parent is not None:
            payload["parent"] = self.parent.to_wire()
        return payload

    def describe(self) -> str:
        parts = [
            f"{name}={value!r}"
            for name, value in (
                ("type", self.type),
                ("identifier", self.identifier),
                ("label", self.label),
                ("text", self.text),
                ("value", self.value),
                ("predicate", self.predicate),
                ("index", self.index),
            )
            if value is not None
        ]
        if self.parent is not None:
            parts.append(f"parent=({self.parent.describe()})")
        return ", ".join(parts) or "<empty>"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.describe()
