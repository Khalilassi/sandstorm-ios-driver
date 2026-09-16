"""Sandstorm iOS Inspector — desktop UI explorer.

The ranking and hit-testing logic lives in :mod:`locators` and
:mod:`hierarchy` and is importable without PySide6; only :mod:`app` needs Qt.
"""

from .hierarchy import Rect, describe, find_by_path, hit_test, node_title
from .locators import LocatorSuggestion, best_locator, format_report, recommend

__all__ = [
    "recommend",
    "best_locator",
    "format_report",
    "LocatorSuggestion",
    "hit_test",
    "find_by_path",
    "describe",
    "node_title",
    "Rect",
]

__version__ = "0.1.0"
