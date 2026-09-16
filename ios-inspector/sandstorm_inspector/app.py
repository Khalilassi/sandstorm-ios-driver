"""PySide6 desktop Inspector for the Sandstorm iOS Driver.

PySide6 was chosen over Tauri/Electron for the MVP: the Inspector already needs
the Python SDK in-process, so a Qt window removes an entire IPC layer, a
JavaScript toolchain and a packaging step.

Launch it with::

    sandstorm ios inspector --host 127.0.0.1 --port 8433 --token <token>
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from sandstorm_ios import IOSDevice
from sandstorm_ios.errors import IOSError

from .hierarchy import Rect, describe, find_by_path, hit_test, node_title
from .locators import LocatorSuggestion, best_locator, recommend
from .recorder import Recorder, describe_target, function_name

try:
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import QColor, QGuiApplication, QPen, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGraphicsPixmapItem,
        QGraphicsRectItem,
        QGraphicsScene,
        QGraphicsView,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QStatusBar,
        QTabWidget,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - optional dependency
    raise SystemExit(
        "The Inspector needs PySide6. Install it with:\n"
        "    pip install 'sandstorm-ios[inspector]'"
    ) from exc

logger = logging.getLogger("sandstorm.inspector")

HIGHLIGHT_COLOR = QColor(0, 122, 255)


class ScreenshotView(QGraphicsView):
    """Screenshot canvas with element highlighting and click-to-select."""

    def __init__(self, on_click) -> None:
        super().__init__()
        self._on_click = on_click
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(self.renderHints())
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._highlight: QGraphicsRectItem | None = None
        self._points_size: tuple[float, float] = (1.0, 1.0)

    def set_screenshot(self, data: bytes, point_size: tuple[float, float]) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self._scene.clear()
        self._highlight = None
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._points_size = point_size
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def highlight(self, rect: Rect) -> None:
        if self._pixmap_item is None:
            return
        if self._highlight is not None:
            self._scene.removeItem(self._highlight)

        scale_x, scale_y = self._pixel_scale()
        pen = QPen(HIGHLIGHT_COLOR)
        pen.setWidth(3)
        self._highlight = self._scene.addRect(
            QRectF(rect.x * scale_x, rect.y * scale_y, rect.width * scale_x, rect.height * scale_y),
            pen,
            QColor(0, 122, 255, 40),
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self._pixmap_item is not None:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._pixmap_item is not None:
            scene_point: QPointF = self.mapToScene(event.position().toPoint())
            scale_x, scale_y = self._pixel_scale()
            if scale_x and scale_y:
                self._on_click(scene_point.x() / scale_x, scene_point.y() / scale_y)
        super().mousePressEvent(event)

    def _pixel_scale(self) -> tuple[float, float]:
        if self._pixmap_item is None:
            return 1.0, 1.0
        pixmap = self._pixmap_item.pixmap()
        width, height = self._points_size
        return (pixmap.width() / width if width else 1.0, pixmap.height() / height if height else 1.0)


class InspectorWindow(QMainWindow):
    """Main Inspector window."""

    def __init__(self, host: str, port: int, token: str | None, bundle_id: str = "com.sandstorm.demo") -> None:
        super().__init__()
        self.setWindowTitle("Sandstorm iOS Inspector")
        self.resize(1360, 900)

        self._device = IOSDevice(host=host, port=port, token=token)
        self._host = host
        self._port = port
        self._snapshot: Mapping[str, Any] | None = None
        self._selected: Mapping[str, Any] | None = None
        self._point_size = (1.0, 1.0)
        self._default_bundle_id = bundle_id
        self._include_invisible = False
        self._recorder = Recorder()

        self._build_ui()
        QTimer.singleShot(0, self._connect)

    # -- UI ------------------------------------------------------------------

    def _build_ui(self) -> None:
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 8, 8, 0)

        self._device_label = QLabel("Not connected")
        self._bundle_input = QLineEdit(self._default_bundle_id)
        self._bundle_input.setPlaceholderText("Bundle identifier")

        launch_button = QPushButton("Launch")
        launch_button.clicked.connect(self._launch_app)
        self._relaunch_toggle = QCheckBox("Fresh")
        self._relaunch_toggle.setToolTip(
            "Terminate a running instance first, so a recorded test replays "
            "from the same state it was recorded in."
        )
        self._relaunch_toggle.setChecked(True)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)

        self._invisible_toggle = QCheckBox("Invisible")
        self._invisible_toggle.setToolTip(
            "Include off-screen nodes. Much slower on large apps."
        )
        self._invisible_toggle.setChecked(self._include_invisible)
        self._invisible_toggle.toggled.connect(self._set_include_invisible)

        self._auto_refresh = QComboBox()
        self._auto_refresh.addItems(["Manual", "2 s", "5 s"])
        self._auto_refresh.currentIndexChanged.connect(self._update_auto_refresh)

        toolbar_layout.addWidget(QLabel("Device:"))
        toolbar_layout.addWidget(self._device_label, 1)
        toolbar_layout.addWidget(QLabel("App:"))
        toolbar_layout.addWidget(self._bundle_input, 1)
        toolbar_layout.addWidget(launch_button)
        toolbar_layout.addWidget(self._relaunch_toggle)
        toolbar_layout.addWidget(refresh_button)
        toolbar_layout.addWidget(self._invisible_toggle)
        toolbar_layout.addWidget(self._auto_refresh)

        self._screenshot_view = ScreenshotView(self._select_at_point)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["UI Hierarchy"])
        self._tree.currentItemChanged.connect(self._tree_selection_changed)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.addWidget(self._screenshot_view)
        top_splitter.addWidget(self._tree)
        top_splitter.setSizes([620, 740])

        details = QGroupBox("Selected element")
        self._details_form = QFormLayout(details)
        self._detail_fields: dict[str, QLineEdit] = {}
        for name in ("Type", "Identifier", "Label", "Value", "Frame", "Enabled", "Visible"):
            field = QLineEdit()
            field.setReadOnly(True)
            self._detail_fields[name] = field
            self._details_form.addRow(f"{name}:", field)

        locators = QGroupBox("Suggested locators")
        locators_layout = QVBoxLayout(locators)
        self._locator_output = QPlainTextEdit()
        self._locator_output.setReadOnly(True)
        self._locator_output.setMinimumHeight(140)
        copy_button = QPushButton("Copy locator")
        copy_button.clicked.connect(self._copy_locator)
        locators_layout.addWidget(self._locator_output)
        locators_layout.addWidget(copy_button)

        detail_splitter = QSplitter(Qt.Orientation.Horizontal)
        detail_splitter.addWidget(details)
        detail_splitter.addWidget(locators)
        detail_splitter.addWidget(self._build_recorder_panel())
        detail_splitter.setSizes([420, 460, 480])

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        for title, handler in (
            ("Tap", self._action_tap),
            ("Type", self._action_type),
            ("Clear", self._action_clear),
            ("Long Press", self._action_long_press),
            ("Swipe Up", self._action_swipe),
            ("Wait For", self._action_wait_for),
            ("Assert Visible", self._action_assert_visible),
            ("Assert Text", self._action_assert_text),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(title)
            button.clicked.connect(handler)
            actions_layout.addWidget(button)
        actions_layout.addStretch(1)

        layout = QVBoxLayout()
        layout.addWidget(toolbar)
        layout.addWidget(top_splitter, 3)
        layout.addWidget(detail_splitter, 2)
        layout.addWidget(actions)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)
        self._update_code_preview()
    # -- Recorder panel ------------------------------------------------------

    def _build_recorder_panel(self) -> QWidget:
        panel = QGroupBox("Recorder")
        layout = QVBoxLayout(panel)

        controls = QHBoxLayout()
        self._record_button = QPushButton("● Record")
        self._record_button.setCheckable(True)
        self._record_button.setToolTip(
            "While recording, every action below is appended as a test step."
        )
        self._record_button.toggled.connect(self._toggle_recording)

        self._case_name = QLineEdit("recorded flow")
        self._case_name.setPlaceholderText("Test case name")
        self._case_name.textChanged.connect(lambda _: self._update_code_preview())

        self._style_box = QComboBox()
        self._style_box.addItems(["pytest", "script"])
        self._style_box.currentIndexChanged.connect(lambda _: self._update_code_preview())

        controls.addWidget(self._record_button)
        controls.addWidget(self._case_name, 1)
        controls.addWidget(self._style_box)

        self._step_list = QListWidget()
        self._step_list.setMinimumHeight(110)

        self._code_preview = QPlainTextEdit()
        self._code_preview.setReadOnly(True)
        self._code_preview.setMinimumHeight(110)

        buttons = QHBoxLayout()
        for title, handler in (
            ("Undo", self._recorder_undo),
            ("Clear", self._recorder_clear),
            ("Screenshot step", self._action_record_screenshot),
            ("Copy code", self._copy_code),
            ("Save as\u2026", self._save_code),
        ):
            button = QPushButton(title)
            button.clicked.connect(handler)
            buttons.addWidget(button)

        tabs = QTabWidget()
        tabs.addTab(self._step_list, "Steps")
        tabs.addTab(self._code_preview, "Code")
        self._recorder_tabs = tabs

        layout.addLayout(controls)
        layout.addWidget(tabs, 1)
        layout.addLayout(buttons)
        return panel

    def _toggle_recording(self, active: bool) -> None:
        if active:
            self._recorder.start()
            self._record_button.setText("■ Stop")
            self._record_button.setStyleSheet("color: #c0392b; font-weight: bold;")
            bundle = self._bundle_input.text().strip()
            self.statusBar().showMessage(f"Recording {bundle or 'session'}\u2026")
        else:
            self._recorder.stop()
            self._record_button.setText("● Record")
            self._record_button.setStyleSheet("")
            self.statusBar().showMessage(f"Recording stopped, {len(self._recorder)} step(s)", 4000)
        self._update_code_preview()

    def _on_step_recorded(self, step) -> None:
        if step is None:
            return
        self._step_list.addItem(step.summary)
        self._step_list.scrollToBottom()
        self._update_code_preview()

    def _recorder_undo(self) -> None:
        if self._recorder.undo() is None:
            return
        self._step_list.takeItem(self._step_list.count() - 1)
        self._update_code_preview()

    def _recorder_clear(self) -> None:
        if len(self._recorder) and QMessageBox.question(
            self, "Clear recording", f"Discard {len(self._recorder)} recorded step(s)?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._recorder.clear()
        self._step_list.clear()
        self._update_code_preview()

    def _generated_code(self) -> str:
        return self._recorder.generate(
            bundle_id=self._bundle_input.text().strip() or self._default_bundle_id,
            name=self._case_name.text().strip() or "recorded flow",
            style=self._style_box.currentText(),
            host=self._host,
            port=self._port,
        )

    def _update_code_preview(self) -> None:
        self._code_preview.setPlainText(self._generated_code())

    def _copy_code(self) -> None:
        QGuiApplication.clipboard().setText(self._generated_code())
        self.statusBar().showMessage("Test code copied to the clipboard", 3000)

    def _save_code(self) -> None:
        suggested = f"{function_name(self._case_name.text().strip() or 'recorded flow')}.py"
        path, _ = QFileDialog.getSaveFileName(self, "Save test case", suggested, "Python (*.py)")
        if not path:
            return
        Path(path).write_text(self._generated_code(), encoding="utf-8")
        self.statusBar().showMessage(f"Saved {path}", 5000)

    # -- Session -------------------------------------------------------------

    def _connect(self) -> None:
        try:
            self._device.connect(retries=3)
        except IOSError as exc:
            QMessageBox.critical(self, "Connection failed", str(exc))
            return
        info = self._device.info
        self._device_label.setText(f"{info.name} — iOS {info.ios_version}")
        self._point_size = (info.screen_width, info.screen_height)
        self.statusBar().showMessage("Connected", 3000)
        self.refresh()

    @property
    def _page(self):
        bundle = self._bundle_input.text().strip()
        return self._device.app(bundle).page

    def _launch_app(self) -> None:
        bundle = self._bundle_input.text().strip()
        if not bundle:
            return
        relaunch = self._relaunch_toggle.isChecked()
        if self._run(
            lambda: self._device.app(bundle).launch(relaunch=relaunch), f"Launched {bundle}"
        ):
            self._on_step_recorded(self._recorder.record_launch(bundle, relaunch=relaunch))
        self.refresh()

    def refresh(self) -> None:
        """Pulls one screenshot and one hierarchy snapshot."""
        if not self._device.is_connected:
            return
        self.statusBar().showMessage("Refreshing\u2026")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            page = self._page
            image = page.screenshot()
            # Large production apps have very deep trees; capturing invisible
            # nodes can push a single snapshot past a minute.
            snapshot = page.snapshot(
                max_depth=40,
                include_invisible=self._include_invisible,
                timeout=150.0,
            )
        except IOSError as exc:
            self.statusBar().showMessage(f"Refresh failed: {exc}", 8000)
            return
        finally:
            QApplication.restoreOverrideCursor()

        screen = snapshot.get("screen") or {}
        self._point_size = (
            float(screen.get("width") or self._point_size[0]),
            float(screen.get("height") or self._point_size[1]),
        )
        self._snapshot = snapshot.get("tree")
        self._screenshot_view.set_screenshot(image, self._point_size)
        self._populate_tree()
        self.statusBar().showMessage("Refreshed", 2000)

    def _set_include_invisible(self, checked: bool) -> None:
        self._include_invisible = checked
        self.refresh()

    def _update_auto_refresh(self, index: int) -> None:
        self._refresh_timer.stop()
        if index == 1:
            self._refresh_timer.start(2000)
        elif index == 2:
            self._refresh_timer.start(5000)

    # -- Tree ----------------------------------------------------------------

    def _populate_tree(self) -> None:
        self._tree.clear()
        if self._snapshot is None:
            return

        def add(node: Mapping[str, Any], parent: QTreeWidgetItem | None) -> None:
            item = QTreeWidgetItem([node_title(node)])
            item.setData(0, Qt.ItemDataRole.UserRole, node.get("path"))
            if parent is None:
                self._tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in node.get("children", []) or []:
                add(child, item)

        add(self._snapshot, None)
        self._tree.expandToDepth(3)

    def _tree_selection_changed(self, current: QTreeWidgetItem | None, _: QTreeWidgetItem | None) -> None:
        if current is None or self._snapshot is None:
            return
        path = current.data(0, Qt.ItemDataRole.UserRole)
        node = find_by_path(self._snapshot, path)
        if node is not None:
            self._select(node, sync_tree=False)

    def _select_at_point(self, x: float, y: float) -> None:
        if self._snapshot is None:
            return
        node = hit_test(self._snapshot, x, y)
        if node is not None:
            self._select(node, sync_tree=True)

    def _select(self, node: Mapping[str, Any], *, sync_tree: bool) -> None:
        self._selected = node
        self._screenshot_view.highlight(Rect.from_node(node))

        attributes = describe(node)
        for name, field in self._detail_fields.items():
            field.setText(attributes.get(name, ""))

        suggestions = recommend(node, self._snapshot or node)
        lines = []
        for suggestion in suggestions:
            unique = "unique" if suggestion.unique else "ambiguous"
            lines.append(f"{suggestion.strategy:<18} {suggestion.stars}  ({unique}) — {suggestion.reason}")
        if suggestions:
            lines.append("")
            lines.append(suggestions[0].code)
        self._locator_output.setPlainText("\n".join(lines))

        if sync_tree:
            self._sync_tree_selection(node.get("path"))

    def _sync_tree_selection(self, path: str | None) -> None:
        if path is None:
            return
        iterator = self._tree.findItems("", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive)
        for item in iterator:
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                self._tree.setCurrentItem(item)
                self._tree.scrollToItem(item)
                return

    # -- Actions -------------------------------------------------------------

    def _normalized_center(self) -> tuple[float, float] | None:
        if self._selected is None:
            return None
        rect = Rect.from_node(self._selected)
        width, height = self._point_size
        if not width or not height:
            return None
        return ((rect.x + rect.width / 2) / width, (rect.y + rect.height / 2) / height)

    def _selected_suggestion(self) -> LocatorSuggestion | None:
        """Best locator for the selection, or ``None`` when nothing is selected.

        The Inspector executes and records this very suggestion, so a recorded
        script reproduces exactly what was clicked.
        """
        if self._selected is None or self._snapshot is None:
            return None
        return best_locator(self._selected, self._snapshot)

    def _require_locator(self) -> tuple[Any, LocatorSuggestion] | None:
        suggestion = self._selected_suggestion()
        if suggestion is None:
            self.statusBar().showMessage("Select an element first", 4000)
            return None
        return suggestion.build(self._page), suggestion

    @property
    def _target_name(self) -> str:
        return describe_target(self._selected)

    def _action_tap(self) -> None:
        suggestion = self._selected_suggestion()
        if suggestion is not None:
            locator = suggestion.build(self._page)
            if self._run(locator.tap, f"Tapped {self._target_name}"):
                self._on_step_recorded(
                    self._recorder.record_tap(suggestion.inline_code, self._target_name)
                )
            self.refresh()
            return
        point = self._normalized_center()
        if point is None:
            self.statusBar().showMessage("Select an element first", 4000)
            return
        if self._run(lambda: self._page.tap(*point), "Tapped"):
            self._on_step_recorded(self._recorder.record_tap(None, "point", point))
        self.refresh()

    def _action_long_press(self) -> None:
        suggestion = self._selected_suggestion()
        if suggestion is not None:
            locator = suggestion.build(self._page)
            if self._run(locator.long_press, f"Long pressed {self._target_name}"):
                self._on_step_recorded(
                    self._recorder.record_long_press(suggestion.inline_code, self._target_name)
                )
            self.refresh()
            return
        point = self._normalized_center()
        if point is None:
            self.statusBar().showMessage("Select an element first", 4000)
            return
        if self._run(lambda: self._page.long_press(*point), "Long pressed"):
            self._on_step_recorded(self._recorder.record_long_press(None, "point", point))
        self.refresh()

    def _action_type(self) -> None:
        resolved = self._require_locator()
        if resolved is None:
            return
        locator, suggestion = resolved
        text, accepted = QInputDialog.getText(self, "Type text", "Text to type:")
        if not accepted or not text:
            return
        if self._run(lambda: locator.fill(text), f"Typed into {self._target_name}"):
            self._on_step_recorded(
                self._recorder.record_fill(suggestion.inline_code, self._target_name, text)
            )
        self.refresh()

    def _action_clear(self) -> None:
        resolved = self._require_locator()
        if resolved is None:
            return
        locator, suggestion = resolved
        if self._run(locator.clear, f"Cleared {self._target_name}"):
            self._on_step_recorded(
                self._recorder.record_clear(suggestion.inline_code, self._target_name)
            )
        self.refresh()

    def _action_swipe(self) -> None:
        start, end = (0.5, 0.75), (0.5, 0.25)
        if self._run(lambda: self._page.swipe(start, end), "Swiped"):
            self._on_step_recorded(self._recorder.record_swipe(start, end))
        self.refresh()

    def _action_wait_for(self) -> None:
        resolved = self._require_locator()
        if resolved is None:
            return
        locator, suggestion = resolved
        states = ["visible", "exists", "enabled", "not_visible", "not_exists"]
        state, accepted = QInputDialog.getItem(self, "Wait for", "State:", states, 0, False)
        if not accepted:
            return
        if self._run(
            lambda: locator.wait_for(state=state, timeout=10.0),
            f"{self._target_name} is {state}",
        ):
            self._on_step_recorded(
                self._recorder.record_wait_for(suggestion.inline_code, self._target_name, state)
            )

    def _action_assert_visible(self) -> None:
        resolved = self._require_locator()
        if resolved is None:
            return
        locator, suggestion = resolved
        try:
            visible = locator.is_visible()
        except IOSError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return
        self.statusBar().showMessage(
            f"{self._target_name} is {'visible' if visible else 'NOT visible'}", 4000
        )
        if visible:
            self._on_step_recorded(
                self._recorder.record_assert_visible(suggestion.inline_code, self._target_name)
            )

    def _action_assert_text(self) -> None:
        resolved = self._require_locator()
        if resolved is None:
            return
        locator, suggestion = resolved
        try:
            current = locator.text_content()
        except IOSError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return
        text, accepted = QInputDialog.getText(
            self, "Assert text", "Expected text:", text=current
        )
        if not accepted:
            return
        self._on_step_recorded(
            self._recorder.record_assert_text(suggestion.inline_code, self._target_name, text)
        )
        if text != current:
            self.statusBar().showMessage(
                f"Recorded, but the element currently reads {current!r}", 6000
            )

    def _action_record_screenshot(self) -> None:
        name, accepted = QInputDialog.getText(
            self, "Screenshot step", "File name:", text="screen.png"
        )
        if not accepted or not name:
            return
        step = self._recorder.record_screenshot(name)
        if step is None:
            self.statusBar().showMessage("Start recording first", 4000)
            return
        self._on_step_recorded(step)

    def _copy_locator(self) -> None:
        if self._selected is None or self._snapshot is None:
            return
        suggestions = recommend(self._selected, self._snapshot)
        if not suggestions:
            return
        QGuiApplication.clipboard().setText(suggestions[0].code)
        self.statusBar().showMessage("Locator copied", 2000)

    def _run(self, action, success_message: str) -> bool:
        """Runs an agent call, reports it, and returns whether it succeeded."""
        try:
            action()
        except IOSError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return False
        self.statusBar().showMessage(success_message, 2000)
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if len(self._recorder):
            choice = QMessageBox.question(
                self,
                "Unsaved recording",
                f"{len(self._recorder)} recorded step(s) have not been saved. Save now?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if choice == QMessageBox.StandardButton.Save:
                self._save_code()
        self._refresh_timer.stop()
        self._device.disconnect()
        super().closeEvent(event)


def main(
    host: str | None = None,
    port: int | None = None,
    token: str | None = None,
    bundle_id: str | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO)
    host = host or os.environ.get("SANDSTORM_AGENT_HOST", "127.0.0.1")
    port = port or int(os.environ.get("SANDSTORM_AGENT_PORT", "8433"))
    token = token if token is not None else os.environ.get("SANDSTORM_TOKEN")
    bundle_id = bundle_id or os.environ.get("SANDSTORM_BUNDLE_ID", "com.sandstorm.demo")

    app = QApplication(sys.argv)
    app.setApplicationName("Sandstorm Inspector")
    window = InspectorWindow(host, port, token, bundle_id)
    window.show()
    # Launched from a terminal, macOS leaves the window behind the shell and
    # gives it no focus; force it to the front.
    window.raise_()
    window.activateWindow()
    _activate_on_macos()
    return app.exec()


def _activate_on_macos() -> None:
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyRegular

        shared = NSApplication.sharedApplication()
        shared.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        shared.activateIgnoringOtherApps_(True)
    except Exception:  # noqa: BLE001 - pyobjc is optional, focus is cosmetic
        logging.getLogger("sandstorm.inspector").debug("Could not force-activate the window")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
