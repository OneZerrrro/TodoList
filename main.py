import sys
import json
import base64
from pathlib import Path
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QTimer,
    Signal,
    QVariantAnimation,
)
from PySide6.QtGui import QMouseEvent, QPainterPath, QRegion, QLinearGradient, QColor, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QTextEdit,
    QListWidgetItem,
    QListWidget,
    QLabel,
    QGraphicsDropShadowEffect,
    QStyledItemDelegate,
    QCheckBox,
)

# 兼容 PyInstaller 打包：如果被打包，则数据存放在 exe 所在目录；否则放在代码所在目录
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent
TODO_JSON_PATH = BASE_DIR / "todolist.json"

colors = {
            "bg": "#d3e3fb",
            "fg": "#1a1c20",
            "hover_gray": "#bdcce3",
            "press_gray": "#a9b6ca",
            "hover_red": "#e81123",
            "press_red": "#df667b",
            "input_bg": "#ffffff",
            "close_icon_active": "#d3e3fb",
        }
light_colors = colors.copy()
dark_colors = {
            "bg": "#1f2020",
            "fg": "#ffffff",
            "hover_gray": "#363737",
            "press_gray": "#4c4d4d",
            "hover_red": "#e81123",
            "press_red": "#971722",
            "input_bg": "#3c3c3c",
            "close_icon_active": "#ffffff",
        }

def generate_app_icon():
    from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QIcon
    from PySide6.QtCore import Qt
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    
    # 绘制一个清新的绿色圆角背景作为任务栏图标的基础
    painter.setBrush(QColor("#4CAF50"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
    
    # 绘制白色的对勾
    pen = QPen(QColor("white"))
    pen.setWidth(6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(18, 34, 28, 44)
    painter.drawLine(28, 44, 48, 20)
    painter.end()
    return QIcon(pixmap)

def get_checkmark_url(color_hex: str) -> str:
    from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
    from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice
    
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    
    pen = QPen(QColor(color_hex))
    pen.setWidth(4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    
    # 手绘对勾
    painter.drawLine(6, 16, 13, 23)
    painter.drawLine(13, 23, 26, 8)
    painter.end()
    
    # 将动态生成的图片保存到专门的临时或者运行时目录中，解决某些系统无法读 base64 png 的问题
    color_name = "dark" if color_hex == "#ffffff" else "light"
    file_path = BASE_DIR / f".check_{color_name}.png"
    pixmap.save(str(file_path), "PNG")
    return file_path.as_posix()

def update_button_style(btn: QPushButton):
    kwargs = btn.property("style_kwargs") or {}
    
    def resolve_color(key_or_val, default_key):
        if not key_or_val:
            return colors[default_key]
        if key_or_val in colors:
            return colors[key_or_val]
        return key_or_val

    dc = resolve_color(kwargs.get("DefaultColor"), "bg")
    hc = resolve_color(kwargs.get("HoverColor"), "hover_gray")
    pc = resolve_color(kwargs.get("PressColor"), "press_gray")
    fc = resolve_color(kwargs.get("FontColor"), "fg")
    fhc = resolve_color(kwargs.get("FontHoverColor"), "fg")
    fpc = resolve_color(kwargs.get("FontPressColor"), "fg")

    btn.setStyleSheet(
        f"""
        QPushButton {{
            background-color: {dc};
            color: {fc};
            border: none;
            font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
            font-size: 11pt;
        }}
        QPushButton:hover {{
            background-color: {hc};
            color: {fhc};
        }}
        QPushButton:pressed {{
            background-color: {pc};
            color: {fpc};
        }}
        """
    )


def create_button(parent: QWidget, text: str, command, w: int = 44, h: int = 40,
                  DefaultColor:str=None, HoverColor:str=None, PressColor:str=None,
                  FontColor:str=None, FontHoverColor:str=None, FontPressColor:str=None) -> QPushButton:
    """创建带悬停与按压效果的普通按钮
    """
    btn = QPushButton(text, parent)
    btn.setFixedSize(w, h)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    
    # 将动态配置保存到按钮实例上，以备热更新时重算
    btn.setProperty("style_kwargs", {
        "DefaultColor": DefaultColor, "HoverColor": HoverColor, "PressColor": PressColor,
        "FontColor": FontColor, "FontHoverColor": FontHoverColor, "FontPressColor": FontPressColor
    })
    update_button_style(btn)
    
    btn.clicked.connect(command)
    return btn


class TodoListWidget(QListWidget):
    """强制内部拖拽为 MoveAction，并使用自定义插入逻辑避免覆盖。"""

    moved = Signal()
    placeholder_role = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._placeholder_item: QListWidgetItem | None = None
        self._placeholder_row: int | None = None
        self._drag_item: QListWidgetItem | None = None
        self._dragging = False
        self._press_pos: QPoint | None = None
        self._press_row: int | None = None
        self._row_offsets: dict[int, int] = {}
        self._offset_anims: list[QVariantAnimation] = []
        self._drag_overlay: QWidget | None = None
        self._drag_overlay_offset = 0
        self._drag_grab_offset = 0
        self._last_target_row: int | None = None
        self.setItemDelegate(_OffsetItemDelegate(self))

    def _compute_target_row(self, center_y: int) -> int:
        if self.count() == 0:
            return 0

        placeholder_h = 0
        p_row = self._placeholder_row
        if p_row is not None and self._placeholder_item is not None:
            placeholder_h = self.visualRect(self.indexFromItem(self._placeholder_item)).height()

        target_row = 0
        for row in range(self.count()):
            item = self.item(row)
            if item is None or item.isHidden():
                continue
            if item.data(self.placeholder_role):
                continue
                
            rect = self.visualRect(self.indexFromItem(item))
            
            # 还原出如果【没有占位符存在时】各元素的纯理论底部Y坐标
            theoretical_bottom = rect.bottom()
            if p_row is not None and row > p_row:
                theoretical_bottom -= placeholder_h
            
            if center_y <= theoretical_bottom:
                return target_row
                
            target_row += 1

        return target_row

    def _clear_placeholder(self) -> None:
        if self._placeholder_item is None:
            return
        row = self.row(self._placeholder_item)
        if row >= 0:
            self.takeItem(row)
        self._placeholder_item = None
        self._placeholder_row = None

    def _animate_shift(self, old_row: int, new_row: int) -> None:
        if old_row == new_row:
            return
        row_height = self.sizeHintForRow(0) or 24
        
        # Calculate which indices in the NEW list need to be visually shifted
        if new_row < old_row:
            # Placeholder moved up. Items shifted down physically.
            # We offset them negatively to start from their old higher position.
            affected = range(new_row + 1, old_row + 1)
            delta = -row_height
        else:
            # Placeholder moved down. Items shifted up physically.
            # We offset them positively to start from their old lower position.
            affected = range(old_row, new_row)
            delta = row_height

        for row in affected:
            self._row_offsets[row] = delta
            anim = QVariantAnimation(self)
            anim.setDuration(150)
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            anim.setStartValue(delta)
            anim.setEndValue(0)

            def make_update(r: int):
                def _update(value):
                    self._row_offsets[r] = int(value)
                    self.viewport().update()
                return _update

            anim.valueChanged.connect(make_update(row))

            def _cleanup():
                self._row_offsets.pop(row, None)
            anim.finished.connect(_cleanup)
            anim.start()
            self._offset_anims.append(anim)

    def _ensure_placeholder(self, row: int) -> None:
        row = self._apply_hysteresis(row)
        if self._placeholder_item is None:
            placeholder = QListWidgetItem("")
            placeholder.setData(self.placeholder_role, True)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            placeholder.setSizeHint(QSize(self.viewport().width(), self.sizeHintForRow(0) or 24))
            self._placeholder_item = placeholder
            self.insertItem(row, placeholder)
            self._placeholder_row = self.row(self._placeholder_item)
            self._last_target_row = self._placeholder_row
            return

        if self._placeholder_row == row:
            return

        current_row = self.row(self._placeholder_item)
        if current_row >= 0:
            self.takeItem(current_row)
        self.insertItem(row, self._placeholder_item)
        new_row = self.row(self._placeholder_item)
        old_row = self._placeholder_row if self._placeholder_row is not None else current_row
        self._placeholder_row = new_row
        if old_row is not None and new_row is not None:
            self._animate_shift(old_row, new_row)
        self._last_target_row = new_row

    def _apply_hysteresis(self, candidate_row: int) -> int:
        return candidate_row

    def _begin_drag(self) -> None:
        if self._press_row is None or self._press_row < 0:
            return
        item = self.item(self._press_row)
        if item is None:
            return
        rect = self.visualRect(self.indexFromItem(item))
        if self._press_pos is not None:
            self._drag_grab_offset = self._press_pos.y() - rect.top()
        self._drag_item = self.takeItem(self._press_row)
        if self._drag_item is None:
            return
        self._dragging = True
        self._ensure_placeholder(self._press_row)
        self._show_drag_overlay(self._drag_item)

    def _finish_drag(self, event_pos: QPoint) -> None:
        if not self._dragging or self._drag_item is None:
            return
        center_y = self._drag_overlay_center_y()
        target_row = self._compute_target_row(center_y)
        if self._placeholder_item is not None:
            placeholder_row = self.row(self._placeholder_item)
            if placeholder_row >= 0:
                self.takeItem(placeholder_row)
                if placeholder_row < target_row:
                    target_row -= 1
            self._placeholder_item = None
            self._placeholder_row = None
        source_row = self.row(self._drag_item)
        if source_row >= 0:
            self.takeItem(source_row)
        target_row = max(0, min(target_row, self.count()))
        self.insertItem(target_row, self._drag_item)
        self.setCurrentRow(target_row)
        self._drag_item = None
        self._dragging = False
        self._hide_drag_overlay()
        self.viewport().update()
        self.update()
        self.moved.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_row = self.row(self.itemAt(self._press_pos))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or self._press_row is None:
            super().mouseMoveEvent(event)
            return
        if not self._dragging:
            if (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
                super().mouseMoveEvent(event)
                return
            self._begin_drag()

        if self._dragging:
            self._move_drag_overlay(event.position().toPoint())
            center_y = self._drag_overlay_center_y()
            self._ensure_placeholder(self._compute_target_row(center_y))
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._finish_drag(event.position().toPoint())
            self._press_pos = None
            self._press_row = None
            event.accept()
            return
        self._press_pos = None
        self._press_row = None
        super().mouseReleaseEvent(event)

    def _show_drag_overlay(self, item: QListWidgetItem) -> None:
        if self._drag_overlay is None:
            overlay = _DragOverlay(self.viewport())
            label = QLabel(overlay)
            label.setObjectName("dragOverlayLabel")
            label.setStyleSheet("#dragOverlayLabel { padding-left: 10px; font-size: 11pt; }")
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            overlay._label = label  # type: ignore[attr-defined]
            self._drag_overlay = overlay

        label = self._drag_overlay._label  # type: ignore[attr-defined]
        label.setText(item.text())
        row_height = self.sizeHintForRow(0) or 24
        width = self.viewport().width()
        shadow_h = 8
        self._drag_overlay.resize(width, row_height + 2 * shadow_h)
        label.resize(width, row_height)
        label.move(0, shadow_h)
        self._drag_overlay_offset = (self._drag_grab_offset if self._press_pos else row_height // 2) + shadow_h
        self._drag_overlay.move(0, self._press_pos.y() - self._drag_overlay_offset)
        self._drag_overlay.show()

    def _hide_drag_overlay(self) -> None:
        if self._drag_overlay is not None:
            self._drag_overlay.hide()

    def _move_drag_overlay(self, pos: QPoint) -> None:
        if self._drag_overlay is None:
            return
        shadow_h = 8
        height_full = self._drag_overlay.height()
        card_h = height_full - 2 * shadow_h
        top = pos.y() - self._drag_overlay_offset
        min_top = -shadow_h
        max_top = self.viewport().height() - shadow_h - card_h
        top = max(min_top, min(top, max_top))
        self._drag_overlay.move(0, top)

    def _drag_overlay_center_y(self) -> int:
        if self._drag_overlay is None:
            return 0
        return self._drag_overlay.y() + self._drag_overlay.height() // 2


class _OffsetItemDelegate(QStyledItemDelegate):
    def __init__(self, list_widget: TodoListWidget):
        super().__init__(list_widget)
        self._list_widget = list_widget

    def paint(self, painter, option, index):
        row = index.row()
        offset = self._list_widget._row_offsets.get(row, 0)
        if offset != 0:
            painter.save()
            painter.translate(0, offset)
            super().paint(painter, option, index)
            painter.restore()
            return
        super().paint(painter, option, index)


class _DragOverlay(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setObjectName("dragOverlay")
        self.shadow_h = 8

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPainterPath, QColor, QLinearGradient, QBrush
        
        q = QPainter(self)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        rect = self.rect()
        card_rect = QRect(1, self.shadow_h, rect.width() - 2, rect.height() - 2 * self.shadow_h)
        
        qp = QPainterPath()
        qp.addRoundedRect(card_rect, 6, 6)
        q.fillPath(qp, QColor(255, 255, 255, 100))

        top_rect = QRect(card_rect.left(), card_rect.top() - self.shadow_h, card_rect.width(), self.shadow_h)
        bottom_rect = QRect(card_rect.left(), card_rect.bottom(), card_rect.width(), self.shadow_h)

        top_grad = QLinearGradient(top_rect.left(), top_rect.bottom(), top_rect.left(), top_rect.top())
        top_grad.setColorAt(0.0, QColor(60, 60, 60, 200))
        top_grad.setColorAt(1.0, QColor(60, 60, 60, 0))

        bottom_grad = QLinearGradient(bottom_rect.left(), bottom_rect.top(), bottom_rect.left(), bottom_rect.bottom())
        bottom_grad.setColorAt(0.0, QColor(60, 60, 60, 200))
        bottom_grad.setColorAt(1.0, QColor(60, 60, 60, 0))

        q.fillRect(top_rect, QBrush(top_grad))
        q.fillRect(bottom_rect, QBrush(bottom_grad))


class AppControllor:
    """应用控制器，负责窗口切换、动画及数据读写。

    数据以单一内存变量 `self.data` 维护，结构与 `todolist.json` 基本一致：
    - `meta`: 窗口位置、主题等元信息
    - `Todo`: 待办列表
    """

    def __init__(self):
        self._anim: QPropertyAnimation | None = None
        self._anim_group: QSequentialAnimationGroup | None = None
        self._editor_restore_rect: QRect | None = None
        self.data: dict = self.load_data()
        self.side: bool = self.to_bool(self.data["meta"].get("side", False))
        self.y_position: int = int(self.data["meta"].get("yPosition", 200))
        self.is_dark_mode: bool = self.to_bool(self.data["meta"].get("dark_mode", False))
        self._apply_global_colors()

        self.editor = EditWindow(self)
        self.edge = EdgeWindow(self)
        self.todo = TodoWindow(self)
        self.settings = SettingsWindow(self)
        self.todo_expanded_size = QSize(250, 300)
        self.editor_normal_size = QSize(300, 400)
        self.normalize_y_position()
        self.sync_data()
        self.editor.show()

    def _apply_global_colors(self):
        src = dark_colors if self.is_dark_mode else light_colors
        for k, v in src.items():
            colors[k] = v

    def set_dark_mode(self, checked: bool):
        self.is_dark_mode = checked
        self.data["meta"]["dark_mode"] = str(checked)
        self.sync_data()
        self._apply_global_colors()
        self.editor.apply_theme()
        self.todo.apply_theme()
        self.edge.apply_theme()
        self.settings.apply_theme()

    @staticmethod
    def to_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)

    def _default_data(self) -> dict:
        return {
            "meta": {
                "side": False,
                "font": "default",
                "dark_mode": False,
                "yPosition": 200,
            },
            "Todo": [],
        }

    def load_data(self) -> dict:
        """从磁盘加载完整数据结构。"""
        default_data = self._default_data()
        try:
            with open(TODO_JSON_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            loaded = default_data

        data = {
            "meta": {
                "side": self.to_bool(loaded.get("meta", {}).get("side", default_data["meta"]["side"])),
                "font": loaded.get("meta", {}).get("font", default_data["meta"]["font"]),
                "dark_mode": loaded.get("meta", {}).get("dark_mode", default_data["meta"]["dark_mode"]),
                "yPosition": int(loaded.get("meta", {}).get("yPosition", default_data["meta"]["yPosition"])),
            },
            "Todo": loaded.get("Todo", []),
        }
        self._normalize_todos(data)
        return data

    def reload_data(self) -> None:
        """按需从磁盘重载（例如重新进入编辑窗口时）。"""
        self.data = self.load_data()
        self.side = self.to_bool(self.data["meta"].get("side", self.side))
        self.y_position = int(self.data["meta"].get("yPosition", self.y_position))
        self.normalize_y_position()

    def sync_data(self) -> None:
        """将内存数据回写到 JSON。"""
        self.data["meta"]["side"] = self.side
        self.data["meta"]["yPosition"] = self.y_position
        self._normalize_todos(self.data)

        with open(TODO_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)

    def _normalize_todos(self, data: dict) -> None:
        """标准化 Todo 列表，保证 uid/order 连续且 done 为 bool。"""
        todos = data.get("Todo", [])
        normalized = []
        for index, item in enumerate(todos):
            done_val = item.get("done", False)
            done_bool = self.to_bool(done_val)
            normalized.append(
                {
                    "uid": int(item.get("uid", index)),
                    "text": str(item.get("text", "")),
                    "done": done_bool,
                    "order": int(item.get("order", index)),
                }
            )

        normalized.sort(key=lambda it: int(it.get("order", 0)))
        for index, item in enumerate(normalized):
            item["order"] = index

        data["Todo"] = normalized

    def sorted_todos(self) -> list[dict]:
        """返回按 order 排序后的 Todo 列表。"""
        todos = list(self.data.get("Todo", []))
        todos.sort(key=lambda item: int(item.get("order", 0)))
        return todos

    def apply_editor_lines(self, text: str) -> None:
        """将编辑器多行文本同步为 Todo 列表并持久化。

        Args:
            text: 编辑框中的全部文本，每行一项。
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        old_todos = self.sorted_todos()
        new_todos = []
        for index, line in enumerate(lines):
            if index < len(old_todos):
                uid = old_todos[index].get("uid", index)
                done = self.to_bool(old_todos[index].get("done", False))
            else:
                existing_uids = [int(todo.get("uid", -1)) for todo in old_todos + new_todos]
                uid = (max(existing_uids) + 1) if existing_uids else 0
                done = False

            new_todos.append(
                {
                    "uid": int(uid),
                    "text": line,
                    "done": done,
                    "order": index,
                }
            )

        self.data["Todo"] = new_todos
        self.sync_data()

    def apply_todo_items(self, items: list[dict]) -> None:
        """将 Todo 窗口当前项写回内存并持久化。"""
        normalized = []
        for index, item in enumerate(items):
            normalized.append(
                {
                    "uid": int(item.get("uid", index)),
                    "text": str(item.get("text", "")),
                    "done": self.to_bool(item.get("done", False)),
                    "order": index,
                }
            )
        self.data["Todo"] = normalized
        self.sync_data()

    def normalize_y_position(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        max_y = max(screen.top(), screen.bottom() - self.edge.height() + 1)
        self.y_position = max(screen.top(), min(self.y_position, max_y))
        self.data["meta"]["yPosition"] = self.y_position

    def update_y_position(self, y: int) -> None:
        self.y_position = int(y)
        self.normalize_y_position()
        self.sync_data()

    def update_side(self, side_is_right: bool) -> None:
        self.side = side_is_right
        self.data["meta"]["side"] = self.side
        self.sync_data()

    def _edge_target_rect(self) -> QRect:
        screen = QApplication.primaryScreen().availableGeometry()
        y = max(screen.top(), min(self.y_position, screen.bottom() - self.edge.height() + 1))
        if not self.side:
            x = -9
        else:
            x = screen.width() - self.edge.width() + 9
        return QRect(x, y, self.edge.width(), self.edge.height())

    def _todo_target_rect(self) -> QRect:
        edge_rect = self._edge_target_rect()
        if not self.side:
            x = edge_rect.x() + 9
        else:
            x = edge_rect.x() - self.todo_expanded_size.width() + 9
        return QRect(x, edge_rect.y(), self.todo_expanded_size.width(), self.todo_expanded_size.height())

    def _animate_geometry(self, window: QMainWindow, start_rect: QRect, end_rect: QRect, on_finished=None) -> None:
        self._anim = QPropertyAnimation(window, b"geometry")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(start_rect)
        self._anim.setEndValue(end_rect)
        if on_finished is not None:
            self._anim.finished.connect(on_finished)
        self._anim.start()

    def show_edge(self, source: str = "todo", animated: bool = True):
        edge_rect = self._edge_target_rect()
        screen = QApplication.primaryScreen().availableGeometry()

        def finish_to_edge():
            self.todo.hide()
            self.editor.hide()
            self.edge.setGeometry(edge_rect)
            self.edge.show()

        if source == "editor" and self.editor.isVisible() and animated:
            self._editor_restore_rect = self.editor.geometry()
            self.todo.hide()
            self.edge.hide()
            self._animate_geometry(self.editor, self.editor.geometry(), edge_rect, finish_to_edge)
            return

        if source == "todo" and self.todo.isVisible() and animated:
            collapsed_w = self.edge.width()
            collapsed_h = self.edge.height()
            if not self.side:
                offscreen_x = -collapsed_w
            else:
                offscreen_x = screen.left() + screen.width()

            offscreen_rect = QRect(offscreen_x, edge_rect.y(), collapsed_w, collapsed_h)

            collapse_anim = QPropertyAnimation(self.todo, b"geometry")
            collapse_anim.setDuration(170)
            collapse_anim.setEasingCurve(QEasingCurve.Type.InCubic)
            collapse_anim.setStartValue(self.todo.geometry())
            collapse_anim.setEndValue(offscreen_rect)

            edge_in_anim = QPropertyAnimation(self.edge, b"geometry")
            edge_in_anim.setDuration(160)
            edge_in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            edge_in_anim.setStartValue(offscreen_rect)
            edge_in_anim.setEndValue(edge_rect)

            self._anim_group = QSequentialAnimationGroup()
            self._anim_group.addAnimation(collapse_anim)
            self._anim_group.addAnimation(edge_in_anim)

            def before_edge_in():
                self.todo.hide()
                self.editor.hide()
                self.edge.setGeometry(offscreen_rect)
                self.edge.show()

            collapse_anim.finished.connect(before_edge_in)
            self._anim_group.finished.connect(finish_to_edge)

            self.editor.hide()
            self.edge.hide()
            self._anim_group.start()
            return

        finish_to_edge()

    def show_todo(self, animated: bool = True):
        edge_rect = self._edge_target_rect()
        todo_rect = self._todo_target_rect()

        self.editor.hide()
        self.edge.hide()
        self.todo.setGeometry(edge_rect)
        self.todo.refresh_from_model()
        self.todo.show()

        if animated:
            self._animate_geometry(self.todo, edge_rect, todo_rect)
        else:
            self.todo.setGeometry(todo_rect)

    def _editor_target_rect(self) -> QRect:
        screen = QApplication.primaryScreen().availableGeometry()
        if self._editor_restore_rect is not None:
            target = QRect(self._editor_restore_rect)
        else:
            base_x = self.todo.x() if self.todo.isVisible() else 200
            base_y = self.todo.y() if self.todo.isVisible() else self.y_position
            target = QRect(base_x, base_y, self.editor_normal_size.width(), self.editor_normal_size.height())

        max_x = screen.right() - target.width() + 1
        max_y = screen.bottom() - target.height() + 1
        target.moveLeft(max(screen.left(), min(target.x(), max_x)))
        target.moveTop(max(screen.top(), min(target.y(), max_y)))
        return target

    def show_editor(self, source: str = "todo", animated: bool = True):
        self.reload_data()
        self.editor.refresh_from_model()
        self.edge.hide()
        target_rect = self._editor_target_rect()

        if source == "todo" and self.todo.isVisible() and animated:
            start_rect = self.todo.geometry()
            self.editor.setGeometry(start_rect)
            self.editor.show()
            self.todo.hide()
            self._animate_geometry(self.editor, start_rect, target_rect)
            return

        self.todo.hide()
        self.editor.setGeometry(target_rect)
        self.editor.show()

class SettingsWindow(QMainWindow):
    def __init__(self, controller: "AppControllor"):
        super().__init__()
        self.controller = controller
        self.resize(250, 150)
        self.setWindowTitle("设置")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.drag_offset: QPoint | None = None
        self.setup_ui()

    def setup_ui(self):
        root = QWidget(self)
        root.setObjectName("settings_root")
        self.setCentralWidget(root)
        
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 头部标题栏
        self.top_bar = QFrame(root)
        self.top_bar.setFixedHeight(40)
        self.top_bar.installEventFilter(self)
        
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(10, 0, 0, 0)
        
        title_label = QLabel("设置", self.top_bar)
        title_label.setObjectName("settings_title")
        top_layout.addWidget(title_label)
        top_layout.addStretch()
        
        self.btn_close = create_button(self.top_bar, "✕", self.close, HoverColor="hover_red", PressColor="press_red", FontHoverColor="close_icon_active", FontPressColor="close_icon_active")
        top_layout.addWidget(self.btn_close)
        
        main_layout.addWidget(self.top_bar)
        
        # 内容区域
        self.content_widget = QWidget()
        self.content_widget.setObjectName("settings_content")
        content_layout = QHBoxLayout(self.content_widget)
        
        label_dm = QLabel("黑夜模式")
        label_dm.setObjectName("settings_label")
        content_layout.addWidget(label_dm)
        
        self.checkbox_dm = QCheckBox()
        self.checkbox_dm.setChecked(self.controller.is_dark_mode)
        self.checkbox_dm.toggled.connect(self.controller.set_dark_mode)
        content_layout.addWidget(self.checkbox_dm)
        
        main_layout.addWidget(self.content_widget)
        self.apply_theme()
    
    def apply_theme(self):
        check_url = get_checkmark_url(colors['fg'])
        self.centralWidget().setStyleSheet(f"""
            QWidget#settings_root {{
                background-color: {colors['bg']};
                border: 1px solid {colors['press_gray']};
            }}
            QWidget#settings_content {{
                background-color: {colors['input_bg']};
            }}
            QLabel#settings_title, QLabel#settings_label {{
                color: {colors['fg']};
                font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 11pt;
            }}
            QCheckBox {{
                color: {colors['fg']};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {colors['press_gray']};
                border-radius: 4px;
                background-color: transparent;
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {colors['fg']};
            }}
            QCheckBox::indicator:checked {{
                background-color: transparent;
                border: 1px solid {colors['fg']};
                image: url("{check_url}");
            }}
        """)
        self.top_bar.setStyleSheet(f"background-color: {colors['bg']};")
        update_button_style(self.btn_close)

    def eventFilter(self, watched, event):
        if watched == self.top_bar:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                if isinstance(event, QMouseEvent) and self.drag_offset is not None:
                    self.move(event.globalPosition().toPoint() - self.drag_offset)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.drag_offset = None
                return True
        return super().eventFilter(watched, event)


class EditWindow(QMainWindow):
    """无边框待办窗口，包含自定义标题栏按钮与拖拽移动。
    Returns:
        None
    """
    def __init__(self, controller: AppControllor):
        super().__init__()
        self.controller = controller
        self._syncing_from_model = False
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self.flush_editor_text)
        self.resize(300, 400)
        self.setWindowTitle("Todo List")
        self.setWindowIcon(generate_app_icon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.drag_offset: QPoint | None = None
        self.setup_ui()

    def apply_theme(self):
        self.root.setStyleSheet(f"QWidget#root {{ background-color: {colors['bg']}; }}")
        self.top_bar.setStyleSheet(f"""
            QFrame {{ background-color: {colors['bg']}; }}
            QLabel#window_title {{
                color: {colors['fg']};
                font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 11pt;
                font-weight: bold;
            }}
        """)
        self.input_bar.setStyleSheet(f"background-color: {colors['bg']};")
        self.input_box.setStyleSheet(f"""
            QTextEdit {{
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 11pt;
                background-color: {colors['input_bg']};
                color: {colors['fg']};
            }}"""
        )
        update_button_style(self.btn_setting)
        update_button_style(self.btn_min)
        update_button_style(self.btn_close)

    def setup_ui(self):
        """构建窗口主界面"""
        self.root = QWidget(self)
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)

        main_layout = QVBoxLayout(self.root)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.top_bar = QFrame(self.root)
        self.top_bar.setFixedHeight(40)
        self.top_bar.installEventFilter(self)

        # ===== 底部输入区域 =====
        self.input_bar = QFrame(self.root)
        input_layout = QHBoxLayout(self.input_bar)
        input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_box = QTextEdit(self.input_bar)
        self.input_box.setPlaceholderText("今天想要做些什么？")
        
        input_layout.addWidget(self.input_box, 1)
        self.input_box.textChanged.connect(self.on_editor_text_changed)

        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(10, 0, 0, 0)
        top_layout.setSpacing(0)
        
        title_label = QLabel("Todo List", self.top_bar)
        title_label.setObjectName("window_title")
        top_layout.addWidget(title_label)
        
        top_layout.addStretch()

        self.btn_setting = create_button(self.top_bar, "⚙", self.open_setting)
        self.btn_min = create_button(self.top_bar, "—", self.minimize)
        self.btn_close = create_button(self.top_bar, "✕", self.close, 
                                  HoverColor="hover_red", PressColor="press_red",
                                  FontHoverColor="close_icon_active", FontPressColor="close_icon_active")

        top_layout.addWidget(self.btn_setting); top_layout.addWidget(self.btn_min); top_layout.addWidget(self.btn_close)

        main_layout.addWidget(self.top_bar)
        main_layout.addWidget(self.input_bar)
        
        self.apply_theme()
        self.refresh_from_model()

    def refresh_from_model(self) -> None:
        """从控制器数据刷新编辑框显示。"""
        todos = self.controller.sorted_todos()
        text = "\n".join(todo.get("text", "") for todo in todos)
        self._syncing_from_model = True
        self.input_box.setPlainText(text)
        self._syncing_from_model = False

    def on_editor_text_changed(self) -> None:
        """编辑框内容变化时，实时同步到内存与 JSON。"""
        if self._syncing_from_model:
            return
        self._debounce_timer.start(200)

    def flush_editor_text(self) -> None:
        """防抖后统一落盘并刷新 Todo 列表。"""
        if self._syncing_from_model:
            return
        self.controller.apply_editor_lines(self.input_box.toPlainText())
        self.controller.todo.refresh_from_model()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """处理顶部栏拖拽移动窗口。
        Args:
            watched: 被监听对象。
            event: 事件对象。
        Returns:
            bool: 是否已处理该事件。
        """
        if isinstance(watched, QFrame):
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse_event = event
                if isinstance(mouse_event, QMouseEvent) and mouse_event.button() == Qt.MouseButton.LeftButton:
                    self.drag_offset = mouse_event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                mouse_event = event
                if isinstance(mouse_event, QMouseEvent) and self.drag_offset is not None:
                    self.move(mouse_event.globalPosition().toPoint() - self.drag_offset)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.drag_offset = None
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        """窗口尺寸变化时更新圆角。"""
        super().resizeEvent(event)

    def open_setting(self):
        """打开设置入口。"""
        self.controller.settings.show()
        self.controller.settings.raise_()
        self.controller.settings.activateWindow()

    def minimize(self):
        """最小化"""
        self.controller.update_y_position(self.y())
        self.controller.show_edge(source="editor", animated=True)

    def closeEvent(self, event):
        """关闭主窗口时自动关闭附属窗口并退出进程。"""
        if hasattr(self.controller, 'settings') and self.controller.settings:
            self.controller.settings.close()
        QApplication.instance().quit()
        super().closeEvent(event)

    def run(self):
        """显示并运行窗口。"""
        self.show()

class EdgeWindow(QMainWindow):
    def apply_theme(self):
        self.setStyleSheet(f"background-color: {colors['bg']};")

    def __init__(self, controller: "AppControllor"):
        super().__init__()
        self.controller = controller
        self.setFixedWidth(18)
        self.setFixedHeight(100)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.apply_theme()

    def show_edge(self):
        target = self.controller._edge_target_rect()
        self.setGeometry(target)
        self.show()

    def enterEvent(self, event):
        self.controller.show_todo()
    
class TodoWindow(QMainWindow):
    def apply_theme(self):
        check_url = get_checkmark_url(colors['fg'])
        self.root.setStyleSheet(f"""
            QWidget#root {{
                background-color: {colors['bg']};
            }}
            QListWidget {{
                font-size: 11pt;
                outline: none;
                background-color: {colors['input_bg']};
                color: {colors['fg']};
                border: none;
            }}
            QListWidget::item {{
                padding: 1px;
            }}
            QListWidget::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {colors['press_gray']};
                border-radius: 4px;
                background-color: transparent;
            }}
            QListWidget::indicator:hover {{
                border: 1px solid {colors['fg']};
            }}
            QListWidget::indicator:checked {{
                background-color: transparent;
                border: 1px solid {colors['fg']};
                image: url("{check_url}");
            }}
        """)
        self.top_bar.setStyleSheet(f"""
            QFrame {{ background-color: {colors['bg']}; }}
            QLabel#window_title {{
                color: {colors['fg']};
                font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 11pt;
                font-weight: bold;
            }}
        """)
        update_button_style(self.btn_edit)
        update_button_style(self.btn_close)

    def __init__(self, controller: "AppControllor"):
        super().__init__()
        self.controller = controller
        self.drag_offset: QPoint | None = None
        self._ignore_next_leave = False
        self._syncing_from_model = False
        self._is_reordering = False
        self._suppress_auto_hide = False
        self.resize(250, 300)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.root = QWidget(self)
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)
        
        layout = QVBoxLayout(self.root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.list_layout = TodoListWidget()
        self.list_layout.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        self.list_layout.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_layout.itemChanged.connect(self.on_item_changed)
        self.list_layout.moved.connect(self.on_rows_moved)

        self.top_bar = QFrame(self.root)
        self.top_bar.setFixedHeight(30)
        self.top_bar.installEventFilter(self)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(10, 0, 0, 0)
        top_layout.setSpacing(0)
        
        title_label = QLabel("待办事项", self.top_bar)
        title_label.setObjectName("window_title")
        top_layout.addWidget(title_label)
        
        top_layout.addStretch()
        
        self.btn_edit = create_button(self.top_bar, "🖊", self.open_editor, h=30)
        self.btn_close = create_button(self.top_bar, "✕", self.close, h=30,
                           HoverColor="hover_red", PressColor="press_red",
                           FontHoverColor="close_icon_active", FontPressColor="close_icon_active")

        top_layout.addWidget(self.btn_edit)
        top_layout.addWidget(self.btn_close)

        layout.addWidget(self.top_bar)
        layout.addWidget(self.list_layout)
        
        self.apply_theme()
        self.refresh_from_model()

    def open_editor(self):
        self._ignore_next_leave = True
        self.controller.show_editor(source="todo", animated=True)

    def closeEvent(self, event):
        """确保从 Todo 状态关闭时彻底结束进程"""
        QApplication.instance().quit()
        super().closeEvent(event)

    def leaveEvent(self, event: QEvent):
        if self._ignore_next_leave:
            self._ignore_next_leave = False
            return
        if self._is_reordering or self._suppress_auto_hide:
            return
        if self.list_layout.state() == QAbstractItemView.State.EditingState:
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return
        self.controller.show_edge(source="todo", animated=True)
        
    def eventFilter(self, watched, event: QEvent):
        if not hasattr(self, "list_layout"):
            return super().eventFilter(watched, event)

        if watched in (self.list_layout, self.list_layout.viewport()):
            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                self._is_reordering = True
                self._suppress_auto_hide = True
            elif event.type() in (QEvent.Type.Drop, QEvent.Type.DragLeave):
                self._is_reordering = False
                self._suppress_auto_hide = False
            return super().eventFilter(watched, event)

        if watched == self.top_bar:
            if event.type() == QEvent.Type.MouseButtonPress:
                if isinstance(event, QMouseEvent) and event.button() == Qt.LeftButton:
                    clicked_child = self.top_bar.childAt(event.position().toPoint())
                    if clicked_child in (self.btn_edit, self.btn_close):
                        return False
                    self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                if isinstance(event, QMouseEvent) and self.drag_offset is not None:
                    self.move(event.globalPosition().toPoint() - self.drag_offset)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self.drag_offset is not None:
                    self.drag_offset = None
                    screen = QApplication.primaryScreen().availableGeometry()
                    center_x = self.geometry().center().x()
                    mid = screen.left() + screen.width() / 2
                    # True 表示右侧，False 表示左侧
                    self.controller.update_side(center_x > mid)
                    self.controller.update_y_position(self.y())
                    # 松开鼠标后直接切换为 edge 形态
                    self.controller.show_edge(source="todo", animated=True)
                    return True

        return super().eventFilter(watched, event)

    def refresh_from_model(self) -> None:
        """按 order 从内存数据刷新 Todo 列表。"""
        self._syncing_from_model = True
        self.list_layout.clear()
        for item in self.controller.sorted_todos():
            list_item = QListWidgetItem(item.get("text", ""))
            list_item.setFlags(
                list_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            is_done = self.controller.to_bool(item.get("done", False))
            list_item.setCheckState(Qt.CheckState.Checked if is_done else Qt.CheckState.Unchecked)
            list_item.setData(Qt.ItemDataRole.UserRole, int(item.get("uid", 0)))
            self.list_layout.addItem(list_item)
        self._syncing_from_model = False

    def _collect_items_for_save(self) -> list[dict]:
        """收集当前列表项，生成可持久化数据。"""
        items = []
        for row in range(self.list_layout.count()):
            list_item = self.list_layout.item(row)
            if self.list_layout.item(row).data(TodoListWidget.placeholder_role):
                continue
            text = list_item.text().strip()
            if not text:
                continue
            items.append(
                {
                    "uid": int(list_item.data(Qt.ItemDataRole.UserRole) or row),
                    "text": text,
                    "done": list_item.checkState() == Qt.CheckState.Checked,
                }
            )
        return items

    def on_item_changed(self, item: QListWidgetItem) -> None:
        """单项文本或勾选状态变化后，实时落盘。"""
        if self._syncing_from_model:
            return
        if self._is_reordering:
            return
        self.controller.apply_todo_items(self._collect_items_for_save())
        self.controller.editor.refresh_from_model()
        self.refresh_from_model()

    def on_rows_moved(self, *_args) -> None:
        """拖拽排序完成后，重排 order 并同步。"""
        if self._syncing_from_model:
            return
        self.controller.apply_todo_items(self._collect_items_for_save())
        self.controller.editor.refresh_from_model()
        self._is_reordering = False
        self._suppress_auto_hide = False
        self.refresh_from_model()

def main():
    """程序入口函数。"""
    app = QApplication(sys.argv)
    
    # 设置全局默认字体（优先使用苹方，以此类推）
    global_font = app.font()
    global_font.setFamilies(["PingFang SC", "Microsoft YaHei", "Segoe UI", "sans-serif"])
    app.setFont(global_font)
    
    window = AppControllor()
    window.editor.run()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()