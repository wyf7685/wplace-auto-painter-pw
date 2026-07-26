import contextlib
from pathlib import Path
from typing import override

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget
from qfluentwidgets import isDarkTheme, qconfig, themeColor

from app.gui.i18n import tr

_MIN_SCALE = 0.1
_MAX_SCALE = 8.0
_ZOOM_STEP = 1.1


class ImageDropLabel(QLabel):
    """接受图片拖放并显示预览的 QLabel，支持鼠标框选并读取选区坐标。

    - 鼠标左键按下开始框选，拖动更新矩形，松开结束；右键拖动平移，滚轮缩放。
    - 选区始终以 **原始图片坐标** 存储，因此缩放、平移、控件尺寸变化都不会使其失真。
    - `selection_rect` 返回选区在原始图片坐标系下的 (x, y, w, h)。
    - 用户实际改动选区时发出 `selection_changed`，便于调用方区分"未编辑"与"已清空"。
    """

    selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(tr("image_drop.placeholder"))
        self._update_style()
        qconfig.themeChanged.connect(self._update_style)
        self.setAcceptDrops(True)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)
        self.filepath: str | None = None

        self._orig_pixmap: QPixmap | None = None
        self._display_pixmap: QPixmap | None = None
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0

        self._panning = False
        self._pan_last_pos: QPoint | None = None

        # 选区端点，原始图片坐标系
        self._sel_start: QPointF | None = None
        self._sel_end: QPointF | None = None
        self._is_drawing = False

    def _update_style(self) -> None:
        border_color = "rgba(255, 255, 255, 0.3)" if isDarkTheme() else "rgba(0, 0, 0, 0.2)"
        text_color = "white" if isDarkTheme() else "black"
        hover_bg = "rgba(255, 255, 255, 0.05)" if isDarkTheme() else "rgba(0, 0, 0, 0.03)"

        self.setStyleSheet(f"""
            ImageDropLabel {{
                border: 2px dashed {border_color};
                border-radius: 8px;
                padding: 10px;
                color: {text_color};
                font-family: 'Segoe UI', 'Microsoft YaHei';
                font-size: 16px;
                background-color: transparent;
            }}
            ImageDropLabel:hover {{
                background-color: {hover_bg};
            }}
        """)

    # --- Drag & drop ---
    @override
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    @override
    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if Path(path).is_file():
            self.set_image(path)

    # --- 显示与坐标映射 ---
    def set_image(self, path: str) -> None:
        pix = QPixmap(path)
        if pix.isNull():
            self.setText(tr("image_drop.invalid_image"))
            self.filepath = None
            self._orig_pixmap = None
            self._display_pixmap = None
            self.clear_selection()
            return

        self.filepath = path
        self._orig_pixmap = pix
        self._scale = min(1.0, self.width() / max(1, pix.width()), self.height() / max(1, pix.height()))
        self._scale = max(_MIN_SCALE, self._scale)
        self._rescale()
        self._center_offsets()

        self.setPixmap(QPixmap())
        self.clear_selection()

    def _rescale(self) -> None:
        """按当前 `_scale` 重建显示用 pixmap。仅在缩放或换图时调用。"""
        if (orig := self._orig_pixmap) is None:
            self._display_pixmap = None
            return

        self._display_pixmap = orig.scaled(
            max(1, round(orig.width() * self._scale)),
            max(1, round(orig.height() * self._scale)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _display_size(self) -> tuple[int, int]:
        if (disp := self._display_pixmap) is None:
            return (0, 0)
        return (disp.width(), disp.height())

    @staticmethod
    def _clamp_offset(offset: int, extent: int, label_extent: int) -> int:
        """图片小于控件时居中，否则夹住边缘避免出现空白。"""
        if extent <= label_extent:
            return (label_extent - extent) // 2
        return max(label_extent - extent, min(offset, 0))

    def _center_offsets(self) -> None:
        disp_w, disp_h = self._display_size()
        self._offset_x = self._clamp_offset(0, disp_w, self.width())
        self._offset_y = self._clamp_offset(0, disp_h, self.height())

    def _clamp_offsets(self) -> None:
        disp_w, disp_h = self._display_size()
        self._offset_x = self._clamp_offset(self._offset_x, disp_w, self.width())
        self._offset_y = self._clamp_offset(self._offset_y, disp_h, self.height())

    def _to_origin(self, point: QPoint) -> QPointF | None:
        """控件坐标 -> 原始图片坐标，并夹入图片范围内。"""
        if (orig := self._orig_pixmap) is None or self._scale <= 0:
            return None

        x = (point.x() - self._offset_x) / self._scale
        y = (point.y() - self._offset_y) / self._scale
        return QPointF(
            max(0.0, min(float(orig.width()), x)),
            max(0.0, min(float(orig.height()), y)),
        )

    def _to_display(self, point: QPointF) -> QPoint:
        return QPoint(
            round(point.x() * self._scale) + self._offset_x,
            round(point.y() * self._scale) + self._offset_y,
        )

    # --- 选区 ---
    def has_selection(self) -> bool:
        return self._sel_start is not None and self._sel_end is not None

    def clear_selection(self) -> None:
        self._sel_start = None
        self._sel_end = None
        self._is_drawing = False
        self.update()

    def get_selection_display_rect(self) -> QRect | None:
        """选区在当前控件坐标系下的矩形，用于绘制。"""
        if self._sel_start is None or self._sel_end is None:
            return None

        p1 = self._to_display(self._sel_start)
        p2 = self._to_display(self._sel_end)
        x1, x2 = sorted((p1.x(), p2.x()))
        y1, y2 = sorted((p1.y(), p2.y()))
        return QRect(x1, y1, x2 - x1, y2 - y1)

    def get_selection_origin_rect(self) -> QRect | None:
        """选区在原始图片坐标系下的矩形。空选区返回 None。"""
        if (orig := self._orig_pixmap) is None or self._sel_start is None or self._sel_end is None:
            return None

        x1, x2 = sorted((self._sel_start.x(), self._sel_end.x()))
        y1, y2 = sorted((self._sel_start.y(), self._sel_end.y()))

        left = max(0, min(orig.width() - 1, int(x1)))
        top = max(0, min(orig.height() - 1, int(y1)))
        right = max(left + 1, min(orig.width(), round(x2)))
        bottom = max(top + 1, min(orig.height(), round(y2)))
        return QRect(left, top, right - left, bottom - top)

    def set_selection_from_original_rect(self, rect: QRect) -> None:
        """根据原始图片坐标系下的 QRect 设置选区。"""
        if self._orig_pixmap is None:
            return

        self._sel_start = QPointF(rect.x(), rect.y())
        self._sel_end = QPointF(rect.x() + rect.width(), rect.y() + rect.height())
        self.update()

    def selection_rect(self) -> tuple[int, int, int, int] | None:
        """返回选区在原始图片坐标系下的 (x, y, w, h)；无图或无选区时返回 None。"""
        if self.filepath is None or (rect := self.get_selection_origin_rect()) is None:
            return None
        return (rect.x(), rect.y(), rect.width(), rect.height())

    # --- 事件 ---
    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        # 选区存于原图坐标系，无需重映射；只要保持偏移量合法即可。
        self._clamp_offsets()
        self.update()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._display_pixmap is None:
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._panning = True
            self._pan_last_pos = event.pos()
            with contextlib.suppress(Exception):
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.LeftButton:
            self._sel_start = self._sel_end = self._to_origin(event.pos())
            self._is_drawing = self._sel_start is not None
            self.update()

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning and self._pan_last_pos is not None:
            delta = event.pos() - self._pan_last_pos
            self._offset_x += delta.x()
            self._offset_y += delta.y()
            self._clamp_offsets()
            self._pan_last_pos = event.pos()
            self.update()
        elif self._is_drawing:
            self._sel_end = self._to_origin(event.pos())
            self.update()

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing:
            self._sel_end = self._to_origin(event.pos())
            self._is_drawing = False
            self.update()
            self.selection_changed.emit()
        elif event.button() == Qt.MouseButton.RightButton and self._panning:
            self._panning = False
            self._pan_last_pos = None
            with contextlib.suppress(Exception):
                self.unsetCursor()
            self.update()

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._orig_pixmap is None or (delta := event.angleDelta().y()) == 0:
            return

        new_scale = self._scale * (_ZOOM_STEP if delta > 0 else 1 / _ZOOM_STEP)
        new_scale = max(_MIN_SCALE, min(_MAX_SCALE, new_scale))
        if abs(new_scale - self._scale) < 1e-6:
            return

        # 保持光标下的图像内容不动
        anchor = event.position().toPoint()
        origin_at_anchor = self._to_origin(anchor)

        self._scale = new_scale
        self._rescale()

        if origin_at_anchor is not None:
            self._offset_x = round(anchor.x() - origin_at_anchor.x() * new_scale)
            self._offset_y = round(anchor.y() - origin_at_anchor.y() * new_scale)
        self._clamp_offsets()

        self.setPixmap(QPixmap())
        self.update()

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._display_pixmap is None:
            return

        painter = QPainter(self)
        painter.drawPixmap(self._offset_x, self._offset_y, self._display_pixmap)
        if (rect := self.get_selection_display_rect()) is not None:
            color = themeColor()
            painter.setPen(color)
            color.setAlpha(50)
            painter.setBrush(color)
            painter.drawRect(rect)
        painter.end()
