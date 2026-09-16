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
from typing import Any, Mapping

from sandstorm_ios import IOSDevice
from sandstorm_ios.errors import IOSError

from .hierarchy import Rect, describe, find_by_path, hit_test, node_title
from .locators import recommend

try:
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import QColor, QGuiApplication, QPen, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
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
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QStatusBar,
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
        self._snapshot: Mapping[str, Any] | None = None
        self._selected: Mapping[str, Any] | None = None
        self._point_size = (1.0, 1.0)
        self._default_bundle_id = bundle_id
        self._include_invisible = False

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
        detail_splitter.setSizes([680, 680])

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        for title, handler in (
            ("Tap", self._action_tap),
            ("Type", self._action_type),
            ("Long Press", self._action_long_press),
            ("Swipe Up", self._action_swipe),
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
        self._run(lambda: self._device.app(bundle).launch(), f"Launched {bundle}")
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

    def _action_tap(self) -> None:
        point = self._normalized_center()
        if point is None:
            return
        self._run(lambda: self._page.tap(*point), "Tapped")
        self.refresh()

    def _action_long_press(self) -> None:
        point = self._normalized_center()
        if point is None:
            return
        self._run(lambda: self._page.long_press(*point), "Long pressed")
        self.refresh()

    def _action_type(self) -> None:
        if self._selected is None:
            return
        text, accepted = QInputDialog.getText(self, "Type text", "Text to type:")
        if not accepted or not text:
            return
        identifier = self._selected.get("identifier")
        page = self._page
        locator = (
            page.get_by_id(identifier)
            if identifier
            else page.get_by_label(self._selected.get("label") or "")
        )
        self._run(lambda: locator.fill(text), "Typed")
        self.refresh()

    def _action_swipe(self) -> None:
        self._run(lambda: self._page.swipe((0.5, 0.75), (0.5, 0.25)), "Swiped")
        self.refresh()

    def _copy_locator(self) -> None:
        if self._selected is None or self._snapshot is None:
            return
        suggestions = recommend(self._selected, self._snapshot)
        if not suggestions:
            return
        QGuiApplication.clipboard().setText(suggestions[0].code)
        self.statusBar().showMessage("Locator copied", 2000)

    def _run(self, action, success_message: str) -> None:
        try:
            action()
            self.statusBar().showMessage(success_message, 2000)
        except IOSError as exc:
            self.statusBar().showMessage(str(exc), 5000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
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
