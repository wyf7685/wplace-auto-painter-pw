# ruff: noqa:N802
# pyright: reportIncompatibleMethodOverride=false
import contextlib
from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget


class ImageDropLabel(QLabel):
    """接受图片拖放并显示预览的 QLabel，支持鼠标绘制矩形并导出透明背景模板图。

    - 鼠标左键按下开始绘制，拖动更新矩形，松开结束。
    - 使用 `create_masked_template` 生成只保留矩形区域的透明图片，图片尺寸与原始一致。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("拖放图片到此处或点击上传")
        self.setStyleSheet("border: 2px dashed #aaa; padding: 10px;")
        self.setAcceptDrops(True)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.setMouseTracking(True)

        self.setFixedHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.filepath: str | None = None

        self._orig_pixmap: QPixmap | None = None
        self._display_pixmap: QPixmap | None = None

        self._offset_x = 0
        self._offset_y = 0

        self._panning = False
        self._pan_last_pos: QPoint | None = None

        self._select_start: QPoint | None = None
        self._select_end: QPoint | None = None
        self._is_drawing = False

    # --- Drag & drop ---
    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:
        md = ev.mimeData()
        if md is not None and md.hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev: QDropEvent) -> None:
        md = ev.mimeData()
        if md is None:
            return
        urls = md.urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if Path(path).is_file():
            self.set_image(path)

    # --- 显示与坐标映射 ---
    def set_image(self, path: str) -> None:
        pix = QPixmap(path)
        if pix.isNull():
            self.setText("无法打开该图片")
            self.filepath = None
            self._orig_pixmap = None
            self._display_pixmap = None
            return
        self.filepath = path
        self._orig_pixmap = pix

        label_w = max(1, self.width())
        label_h = max(1, self.height())
        self._scale = min(1.0, min(label_w / max(1, pix.width()), label_h / max(1, pix.height())))
        disp_w = max(1, int(pix.width() * self._scale))
        disp_h = max(1, int(pix.height() * self._scale))
        aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        transf_mode = Qt.TransformationMode.SmoothTransformation
        self._display_pixmap = pix.scaled(disp_w, disp_h, aspect_mode, transf_mode)

        label_w = self.width()
        label_h = self.height()
        display_w = self._display_pixmap.width()
        display_h = self._display_pixmap.height()
        self._offset_x = (label_w - display_w) // 2 if display_w <= label_w else 0
        self._offset_y = (label_h - display_h) // 2 if display_h <= label_h else 0


        self.setPixmap(QPixmap())
        self.update()
        # 重置选择框
        self._select_start = None
        self._select_end = None
        self._is_drawing = False
        self.update()

    def has_selection(self) -> bool:
        return self._select_start is not None and self._select_end is not None

    def getSelectionDisplayRect(self) -> QRect | None:
        if not self.has_selection() or self._display_pixmap is None:
            return None
        p1 = self._select_start
        p2 = self._select_end
        if p1 is None or p2 is None:
            return None
        x1 = min(p1.x(), p2.x())
        y1 = min(p1.y(), p2.y())
        x2 = max(p1.x(), p2.x())
        y2 = max(p1.y(), p2.y())
        return QRect(x1, y1, x2 - x1, y2 - y1)

    def getSelectionOriginalRect(self) -> QRect | None:
        """将显示坐标映射回原始图片坐标并返回 QRect（在原始图片坐标系中）。"""
        if not self.has_selection() or self._orig_pixmap is None or self._display_pixmap is None:
            return None
        disp = self._display_pixmap
        orig = self._orig_pixmap
        # display pixmap 相对于 label 的左上偏移
        label_w = self.width()
        label_h = self.height()
        # 若图片小于控件，则偏移为居中；否则使用当前偏移
        dx = (label_w - disp.width()) // 2 if disp.width() <= label_w else self._offset_x
        dy = (label_h - disp.height()) // 2 if disp.height() <= label_h else self._offset_y

        rect = self.getSelectionDisplayRect()
        if rect is None:
            return None

        # 将 display 坐标映射到原始坐标
        sx = orig.width() / disp.width()
        sy = orig.height() / disp.height()

        x1 = int((rect.x() - dx) * sx)
        y1 = int((rect.y() - dy) * sy)
        x2 = int((rect.x() + rect.width() - dx) * sx)
        y2 = int((rect.y() + rect.height() - dy) * sy)

        x1 = max(0, min(orig.width() - 1, x1))
        y1 = max(0, min(orig.height() - 1, y1))
        x2 = max(0, min(orig.width(), x2))
        y2 = max(0, min(orig.height(), y2))

        return QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))

    # --- 鼠标绘制 ---
    def mousePressEvent(self, ev: QMouseEvent) -> None:
        # 右键开始平移（手抓拖动），左键开始绘制选区
        if ev.button() == Qt.MouseButton.RightButton and self._display_pixmap is not None:
            self._panning = True
            self._pan_last_pos = ev.pos()
            # 改变光标为闭合手形以提示处于拖动状态
            with contextlib.suppress(Exception):
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() == Qt.MouseButton.LeftButton and self._display_pixmap is not None:
            self._select_start = ev.pos()
            self._select_end = ev.pos()
            self._is_drawing = True
            self.update()
    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if self._is_drawing:
            self._select_end = ev.pos()
            self.update()
        # 平移逻辑优先
        if self._panning and self._pan_last_pos is not None and self._display_pixmap is not None:
            last = self._pan_last_pos
            dx = ev.pos().x() - last.x()
            dy = ev.pos().y() - last.y()
            disp = self._display_pixmap
            label_w = self.width()
            label_h = self.height()
            # 只有当显示图片比控件大的时候允许平移
            if disp.width() > label_w:
                min_x = label_w - disp.width()
                max_x = 0
                self._offset_x = max(min_x, min(self._offset_x + dx, max_x))
            else:
                # 保持居中
                self._offset_x = (label_w - disp.width()) // 2

            if disp.height() > label_h:
                min_y = label_h - disp.height()
                max_y = 0
                self._offset_y = max(min_y, min(self._offset_y + dy, max_y))
            else:
                self._offset_y = (label_h - disp.height()) // 2

            # 同步调整现有选区（选区以 widget 坐标系存储）
            if self._select_start is not None:
                self._select_start = QPoint(self._select_start.x() + dx, self._select_start.y() + dy)
            if self._select_end is not None:
                self._select_end = QPoint(self._select_end.x() + dx, self._select_end.y() + dy)

            self._pan_last_pos = ev.pos()
            self.update()
            return

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton and self._is_drawing:
            self._select_end = ev.pos()
            self._is_drawing = False
            self.update()
        if ev.button() == Qt.MouseButton.RightButton and self._panning:
            # 结束平移
            self._panning = False
            self._pan_last_pos = None
            with contextlib.suppress(Exception):
                self.unsetCursor()
            self.update()

    def wheelEvent(self, a0: QWheelEvent) -> None:
        # 简化实现：在固定的预览区域内按比例缩放显示图片，并按比例更新选区位置（若存在）。
        if self._orig_pixmap is None:
            return

        delta = a0.angleDelta().y()
        if delta == 0:
            return

        factor = 1.1 if delta > 0 else (1.0 / 1.1)
        old_scale = getattr(self, "_scale", 1.0)
        new_scale = old_scale * factor
        new_scale = max(0.1, min(8.0, new_scale))
        if abs(new_scale - old_scale) < 1e-6:
            return

        orig = self._orig_pixmap
        new_w = max(1, int(orig.width() * new_scale))
        new_h = max(1, int(orig.height() * new_scale))
        aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        transf_mode = Qt.TransformationMode.SmoothTransformation
        new_disp = orig.scaled(new_w, new_h, aspect_mode, transf_mode)

        label_w = self.width()
        label_h = self.height()
        old_disp = self._display_pixmap
        # 当前旧偏移（可能为居中或先前平移的值）
        old_off_x = self._offset_x
        old_off_y = self._offset_y

        # 计算缩放中心：当且仅当正在右键平移时，使用平移记录的位置作为指针中心；否则使用控件中心
        if self._panning and self._pan_last_pos is not None and old_disp is not None:
            pos = self._pan_last_pos
        else:
            pos = QPoint(label_w // 2, label_h // 2)

        # 只有当鼠标/锚点位于图片显示区域内时，才做基于指针的缩放，否则以中心缩放
        use_pointer = (
            old_disp is not None
            and old_disp.width() > 0
            and old_disp.height() > 0
            and old_off_x <= pos.x() <= old_off_x + old_disp.width()
            and old_off_y <= pos.y() <= old_off_y + old_disp.height()
        )

        if use_pointer:
            assert old_disp is not None

            rel_x = (pos.x() - old_off_x) / old_disp.width()
            rel_y = (pos.y() - old_off_y) / old_disp.height()
            raw_new_off_x = int(pos.x() - rel_x * new_disp.width())
            raw_new_off_y = int(pos.y() - rel_y * new_disp.height())

            if new_disp.width() <= label_w:
                new_off_x = (label_w - new_disp.width()) // 2
            else:
                min_x = label_w - new_disp.width()
                new_off_x = max(min_x, min(raw_new_off_x, 0))

            if new_disp.height() <= label_h:
                new_off_y = (label_h - new_disp.height()) // 2
            else:
                min_y = label_h - new_disp.height()
                new_off_y = max(min_y, min(raw_new_off_y, 0))

            # 偏移差：将选区一并移动
            delta_x = new_off_x - old_off_x
            delta_y = new_off_y - old_off_y
            if self._select_start is not None:
                self._select_start = QPoint(self._select_start.x() + delta_x, self._select_start.y() + delta_y)
            if self._select_end is not None:
                self._select_end = QPoint(self._select_end.x() + delta_x, self._select_end.y() + delta_y)

            self._offset_x = new_off_x
            self._offset_y = new_off_y
        else:
            # 中心缩放：按比例映射选区到新的 display，并将图片居中或按 new offsets 计算
            new_off_x = (label_w - new_disp.width()) // 2
            new_off_y = (label_h - new_disp.height()) // 2
            if self.has_selection() and old_disp is not None and old_disp.width() > 0 and old_disp.height() > 0:
                s = self._select_start
                e = self._select_end
                if s is not None and e is not None:
                    sx = (s.x() - old_off_x) / old_disp.width()
                    sy = (s.y() - old_off_y) / old_disp.height()
                    ex = (e.x() - old_off_x) / old_disp.width()
                    ey = (e.y() - old_off_y) / old_disp.height()
                    sxpos = int(new_off_x + sx * new_disp.width())
                    sypos = int(new_off_y + sy * new_disp.height())
                    self._select_start = QPoint(sxpos, sypos)
                    expos = int(new_off_x + ex * new_disp.width())
                    eypos = int(new_off_y + ey * new_disp.height())
                    self._select_end = QPoint(expos, eypos)

            self._offset_x = new_off_x
            self._offset_y = new_off_y

        self._scale = new_scale
        self._display_pixmap = new_disp

        self.setPixmap(QPixmap())
        self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """
        自定义绘制函数，支持偏移绘制和平移。
        还会绘制选区覆盖层。
        """
        super().paintEvent(a0)
        if self._display_pixmap is not None:
            painter = QPainter(self)
            # 绘制 pixmap 到当前偏移位置
            painter.drawPixmap(self._offset_x, self._offset_y, self._display_pixmap)
            # 绘制选区覆盖层
            if self.has_selection():
                rect = self.getSelectionDisplayRect()
                if rect is not None:
                    pen_color = QColor(255, 0, 0)
                    painter.setPen(pen_color)
                    brush_color = QColor(255, 0, 0, 50)
                    painter.setBrush(brush_color)
                    painter.drawRect(rect)
            painter.end()


    def create_masked_template(self, file_id_base: str, dest_dir: Path) -> Path | None:
        """生成一个与原始图片同尺寸的 PNG，只有选区内的内容保留，其他区域全透明。

        返回生成的目标路径（Path），失败时返回 None。
        文件名格式: {file_id_base}(x:{startx},y:{starty},w:{width},h:{height}).png
        """
        if self.filepath is None:
            return None
        if self._orig_pixmap is None:
            return None
        sel = self.getSelectionOriginalRect()
        if sel is None:
            return None

        try:
            orig_img = QImage(self.filepath)
            if orig_img.isNull():
                return None

            w = orig_img.width()
            h = orig_img.height()

            # 创建透明背景的大图
            result = QImage(w, h, QImage.Format.Format_ARGB32)
            result.fill(Qt.GlobalColor.transparent)

            # 复制选区到对应位置
            painter = QPainter(result)
            src_rect = sel
            # 绘制选区内容
            painter.drawImage(src_rect.topLeft(), orig_img.copy(src_rect))
            painter.end()

            startx = sel.x()
            starty = sel.y()
            width = sel.width()
            height = sel.height()
            new_name = f"{file_id_base}_({startx},{starty},{width},{height}).png"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / new_name
            ok = result.save(str(dest), "PNG")
            if not ok:
                return None

            # 更新内部 filepath 以指向新生成的文件
            self.set_image(str(dest))
        except Exception:
            return None
        else:
            return dest
