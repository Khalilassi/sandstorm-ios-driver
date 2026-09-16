"""Test-case recorder.

Every action performed in the Inspector can be appended to a script. The module
is deliberately Qt-free so the code generator can be unit tested, reused by a
CLI, or driven by a future headless recorder.

The generator emits the same Playwright-style calls a human would write by
hand: locator-first, coordinates only when no element was selected.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Sequence

Style = Literal["pytest", "script"]

_IDENTIFIER_RE = re.compile(r"[^0-9a-zA-Z]+")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass(frozen=True, slots=True)
class Step:
    """One recorded action.

    :param action: Machine-readable kind, e.g. ``tap`` or ``fill``.
    :param code: The exact Python statement to emit, without indentation.
    :param summary: One line shown in the Inspector's step list.
    :param locator: Locator expression used, when the step targeted an element.
    """

    action: str
    code: str
    summary: str
    locator: str | None = None

    @property
    def uses_coordinates(self) -> bool:
        return self.locator is None and "page.tap(" in self.code


@dataclass
class Recorder:
    """Collects :class:`Step` objects and renders them as a test script."""

    steps: list[Step] = field(default_factory=list)
    _recording: bool = False

    # -- State ---------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        self._recording = True

    def stop(self) -> None:
        self._recording = False

    def clear(self) -> None:
        self.steps.clear()

    def undo(self) -> Step | None:
        return self.steps.pop() if self.steps else None

    def __len__(self) -> int:
        return len(self.steps)

    # -- Capture -------------------------------------------------------------

    def record(self, step: Step) -> Step | None:
        """Appends ``step`` when recording is active, otherwise ignores it."""
        if not self._recording:
            return None
        self.steps.append(step)
        return step

    def record_launch(self, bundle_id: str, *, relaunch: bool = True) -> Step | None:
        """Records a launch.

        ``relaunch`` terminates a running instance first, which is what makes a
        replayed recording start from the same state it was recorded in.
        """
        call = "app.launch(relaunch=True)" if relaunch else "app.launch()"
        suffix = "  [fresh]" if relaunch else ""
        return self.record(Step("launch", call, f"launch  {bundle_id}{suffix}"))

    def record_terminate(self, bundle_id: str) -> Step | None:
        return self.record(
            Step("terminate", "app.terminate()", f"terminate  {bundle_id}")
        )

    def record_tap(self, locator: str | None, target: str, point: tuple[float, float] | None = None) -> Step | None:
        if locator:
            return self.record(Step("tap", f"{locator}.tap()", f"tap  {target}", locator))
        if point is None:
            return None
        x, y = point
        return self.record(
            Step("tap", f"page.tap({x:.4f}, {y:.4f})", f"tap  ({x:.3f}, {y:.3f})")
        )

    def record_long_press(
        self,
        locator: str | None,
        target: str,
        point: tuple[float, float] | None = None,
        duration: float = 1.0,
    ) -> Step | None:
        if locator:
            return self.record(
                Step(
                    "long_press",
                    f"{locator}.long_press(duration={duration})",
                    f"long press  {target}",
                    locator,
                )
            )
        if point is None:
            return None
        x, y = point
        return self.record(
            Step(
                "long_press",
                f"page.long_press({x:.4f}, {y:.4f}, duration={duration})",
                f"long press  ({x:.3f}, {y:.3f})",
            )
        )

    def record_fill(self, locator: str, target: str, text: str) -> Step | None:
        return self.record(
            Step("fill", f'{locator}.fill("{_escape(text)}")', f"fill  {target} = {text!r}", locator)
        )

    def record_clear(self, locator: str, target: str) -> Step | None:
        return self.record(Step("clear", f"{locator}.clear()", f"clear  {target}", locator))

    def record_swipe(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        duration: float = 0.3,
    ) -> Step | None:
        return self.record(
            Step(
                "swipe",
                f"page.swipe(({start[0]:.3f}, {start[1]:.3f}), "
                f"({end[0]:.3f}, {end[1]:.3f}), duration={duration})",
                f"swipe  ({start[0]:.2f}, {start[1]:.2f}) -> ({end[0]:.2f}, {end[1]:.2f})",
            )
        )

    def record_wait_for(self, locator: str, target: str, state: str = "visible", timeout: float = 10.0) -> Step | None:
        return self.record(
            Step(
                "wait_for",
                f'{locator}.wait_for(state="{state}", timeout={timeout})',
                f"wait for  {target}  [{state}]",
                locator,
            )
        )

    def record_assert_visible(self, locator: str, target: str) -> Step | None:
        return self.record(
            Step(
                "assert_visible",
                f'assert {locator}.is_visible(), "{_escape(target)} is not visible"',
                f"assert visible  {target}",
                locator,
            )
        )

    def record_assert_text(self, locator: str, target: str, text: str) -> Step | None:
        return self.record(
            Step(
                "assert_text",
                f'assert {locator}.text_content() == "{_escape(text)}"',
                f"assert text  {target} == {text!r}",
                locator,
            )
        )

    def record_screenshot(self, path: str) -> Step | None:
        return self.record(
            Step("screenshot", f'page.screenshot("{_escape(path)}")', f"screenshot  {path}")
        )

    def record_alert(self, accept: bool, button: str | None = None) -> Step | None:
        call = "accept_alert" if accept else "dismiss_alert"
        argument = f'"{_escape(button)}"' if button else ""
        return self.record(
            Step(
                "alert",
                f"page.{call}({argument})",
                f"{'accept' if accept else 'dismiss'} alert" + (f"  [{button}]" if button else ""),
            )
        )

    # -- Code generation -----------------------------------------------------

    def generate(
        self,
        *,
        bundle_id: str,
        name: str = "recorded flow",
        style: Style = "pytest",
        host: str = "127.0.0.1",
        port: int = 8433,
    ) -> str:
        """Renders the recorded steps as runnable Python."""
        body = [step.code for step in self.steps] or ["pass  # nothing was recorded"]
        if style == "pytest":
            return _render_pytest(_header(name, bundle_id), body, bundle_id, name, host, port)
        return _render_script(
            _header(name, bundle_id, "python this_file.py"), body, bundle_id, host, port
        )


def function_name(name: str, *, prefix: str = "test_") -> str:
    """Turns a free-form title into a valid, readable function name."""
    cleaned = _IDENTIFIER_RE.sub("_", name).strip("_").lower()
    if not cleaned:
        cleaned = "recorded_flow"
    if cleaned.startswith(prefix):
        return cleaned
    if not prefix and cleaned[0].isdigit():
        return f"case_{cleaned}"
    return f"{prefix}{cleaned}"


def _header(name: str, bundle_id: str, run_hint: str = "pytest this_file.py") -> list[str]:
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return [
        '"""' + name,
        "",
        f"Recorded with the Sandstorm iOS Inspector on {stamp}.",
        f"App under test: {bundle_id}",
        "",
        "Run it against a started agent:",
        "    sandstorm ios start --udid <UDID> --token <token>",
        f"    {run_hint}",
        '"""',
    ]


def _connection(host: str, port: int, *, extra_imports: Sequence[str] = ()) -> list[str]:
    lines = ["import os"]
    lines += list(extra_imports)
    lines += [
        "",
        "from sandstorm_ios import IOSDevice",
        "",
        f'HOST = os.environ.get("SANDSTORM_AGENT_HOST", "{host}")',
        f'PORT = int(os.environ.get("SANDSTORM_AGENT_PORT", "{port}"))',
        'TOKEN = os.environ.get("SANDSTORM_TOKEN")',
    ]
    return lines


def _render_pytest(
    header: Sequence[str],
    body: Sequence[str],
    bundle_id: str,
    name: str,
    host: str,
    port: int,
) -> str:
    lines: list[str] = [
        *header,
        "",
        *_connection(host, port, extra_imports=["", "import pytest"]),
        "",
    ]
    lines += [
        f'BUNDLE_ID = "{_escape(bundle_id)}"',
        "",
        "",
        '@pytest.fixture(scope="module")',
        "def device():",
        "    device = IOSDevice(host=HOST, port=PORT, token=TOKEN)",
        "    device.connect(retries=3)",
        "    yield device",
        "    device.disconnect()",
        "",
        "",
        f"def {function_name(name)}(device):",
        "    app = device.app(BUNDLE_ID)",
        "    page = app.page",
        "",
    ]
    lines += [f"    {line}" for line in body]
    return "\n".join(lines) + "\n"


def _render_script(
    header: Sequence[str],
    body: Sequence[str],
    bundle_id: str,
    host: str,
    port: int,
) -> str:
    lines: list[str] = [*header, "", *_connection(host, port), "", f'BUNDLE_ID = "{_escape(bundle_id)}"', "", ""]
    lines += [
        "def main() -> None:",
        "    device = IOSDevice(host=HOST, port=PORT, token=TOKEN)",
        "    device.connect(retries=3)",
        "    try:",
        "        app = device.app(BUNDLE_ID)",
        "        page = app.page",
        "",
    ]
    lines += [f"        {line}" for line in body]
    lines += [
        "    finally:",
        "        device.disconnect()",
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
    ]
    return "\n".join(lines) + "\n"


def describe_target(node: Mapping[str, Any] | None) -> str:
    """Short human label for a snapshot node, used in step summaries."""
    if not node:
        return "screen"
    for key in ("identifier", "label", "title"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = node.get("value")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(node.get("type") or "element")


def summarize(steps: Iterable[Step]) -> str:
    """Compact multi-line preview used by tests and the status bar."""
    return "\n".join(f"{index + 1:>3}. {step.summary}" for index, step in enumerate(steps))
