"""Locator recommendation engine.

Pure logic, no Qt: the Inspector renders what this module ranks, and the same
scoring can be reused by a future code generator or linter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

MAX_SCORE = 5


@dataclass(frozen=True, slots=True)
class LocatorSuggestion:
    """One ranked way of addressing an element."""

    strategy: str
    score: int
    unique: bool
    code: str
    reason: str

    @property
    def stars(self) -> str:
        return f"{self.score}/{MAX_SCORE}"


def iter_nodes(node: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """Depth-first walk over a normalized snapshot tree."""
    yield node
    for child in node.get("children", []) or []:
        yield from iter_nodes(child)


def _count_matches(root: Mapping[str, Any], **criteria: Any) -> int:
    count = 0
    for node in iter_nodes(root):
        if all(node.get(key) == value for key, value in criteria.items()):
            count += 1
    return count


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def recommend(
    element: Mapping[str, Any],
    root: Mapping[str, Any],
) -> list[LocatorSuggestion]:
    """Ranks locator strategies for ``element`` within its snapshot ``root``.

    Rules:

    * prefer stable unique identifiers (accessibility identifiers first);
    * labels are good but localized, so they rank below identifiers;
    * predicates are powerful but verbose;
    * index is a last resort, it breaks as soon as the layout changes;
    * coordinates are never suggested as a primary locator;
    * XPath is never generated at all.
    """
    suggestions: list[LocatorSuggestion] = []

    identifier = (element.get("identifier") or "").strip()
    label = (element.get("label") or "").strip()
    element_type = element.get("type") or ""
    value = element.get("value")

    if identifier:
        unique = _count_matches(root, identifier=identifier) == 1
        suggestions.append(
            LocatorSuggestion(
                strategy="Accessibility ID",
                score=MAX_SCORE if unique else 3,
                unique=unique,
                code=f'page.get_by_id("{_escape(identifier)}")',
                reason="Accessibility identifiers are set by developers and survive copy changes"
                if unique
                else "Identifier is not unique in this hierarchy",
            )
        )
        if not unique:
            suggestions.append(
                LocatorSuggestion(
                    strategy="Identifier + type",
                    score=4,
                    unique=_count_matches(root, identifier=identifier, type=element_type) == 1,
                    code=(
                        f'page.locator(\n'
                        f'    type="{element_type}",\n'
                        f'    identifier="{_escape(identifier)}"\n'
                        f')'
                    ),
                    reason="Narrows a duplicated identifier by element type",
                )
            )

    if label:
        unique = _count_matches(root, label=label) == 1
        suggestions.append(
            LocatorSuggestion(
                strategy="Label",
                score=4 if unique else 2,
                unique=unique,
                code=f'page.get_by_label("{_escape(label)}")',
                reason="Readable, but breaks under localization"
                if unique
                else "Several elements share this label",
            )
        )
        if element_type:
            type_unique = _count_matches(root, label=label, type=element_type) == 1
            suggestions.append(
                LocatorSuggestion(
                    strategy="Type + label",
                    score=4 if type_unique else 3,
                    unique=type_unique,
                    code=(
                        f'page.locator(\n'
                        f'    type="{element_type}",\n'
                        f'    label="{_escape(label)}"\n'
                        f')'
                    ),
                    reason="Compound match evaluated in a single NSPredicate",
                )
            )

    if isinstance(value, str) and value.strip():
        suggestions.append(
            LocatorSuggestion(
                strategy="Text",
                score=3,
                unique=_count_matches(root, value=value) == 1,
                code=f'page.get_by_text("{_escape(value)}")',
                reason="Matches label, value, title or placeholder",
            )
        )

    if identifier or label:
        predicate_parts = []
        if identifier:
            predicate_parts.append(f'identifier == "{_escape(identifier)}"')
        if label:
            predicate_parts.append(f'label == "{_escape(label)}"')
        predicate = " AND ".join(predicate_parts)
        suggestions.append(
            LocatorSuggestion(
                strategy="Predicate",
                score=3,
                unique=True,
                code=f"page.get_by_predicate('{predicate}')",
                reason="Full NSPredicate power, evaluated inside the app process",
            )
        )

    index = _index_among_siblings_of_type(root, element)
    if index is not None:
        suggestions.append(
            LocatorSuggestion(
                strategy="Index",
                score=2,
                unique=True,
                code=f'page.get_by_type("{element_type}").nth({index})',
                reason="Positional; breaks whenever the layout changes. Use as a last resort",
            )
        )

    suggestions.sort(key=lambda item: (-item.score, not item.unique, item.strategy))
    return suggestions


def _index_among_siblings_of_type(
    root: Mapping[str, Any], element: Mapping[str, Any]
) -> int | None:
    element_type = element.get("type")
    if not element_type:
        return None
    same_type = [node for node in iter_nodes(root) if node.get("type") == element_type]
    for position, node in enumerate(same_type):
        if node.get("path") == element.get("path"):
            return position
    return None


def best_locator(element: Mapping[str, Any], root: Mapping[str, Any]) -> LocatorSuggestion | None:
    suggestions = recommend(element, root)
    return suggestions[0] if suggestions else None


def format_report(suggestions: Sequence[LocatorSuggestion]) -> str:
    """Renders the ranking table shown in the Inspector."""
    if not suggestions:
        return "No locator could be recommended for this element."
    width = max(len(item.strategy) for item in suggestions)
    lines = [f"{item.strategy.ljust(width)}: {item.stars}" for item in suggestions]
    return "\n".join(lines)
