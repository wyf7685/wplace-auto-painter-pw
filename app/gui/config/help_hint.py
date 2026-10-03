from typing import ClassVar, override

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QEnterEvent, QHideEvent, QPainter, QPaintEvent, QPen, QRegion, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QHBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, TeachingTip, TeachingTipTailPosition, TeachingTipView, isDarkTheme, themeColor
from qfluentwidgets.components.widgets.teaching_tip import BottomTailTeachingTipManager, TopTailTeachingTipManager
from shiboken6 import isValid

from app.i18n import tr

HOVER_OPEN_DELAY_MS = 200
_HELP_TIP_GAP = 4
# Short tips stay at least this wide. Longer tips grow with the longest sentence.
_HELP_TEXT_MIN_WIDTH = 160


class _HelpTipView(TeachingTipView):
    """Teaching tip body. Each sentence is one line; nothing else wraps."""

    def __init__(self, content: str) -> None:
        super().__init__("", content, isClosable=False, tailPosition=TeachingTipTailPosition.BOTTOM)

    @override
    def _adjustText(self) -> None:
        self.titleLabel.setVisible(False)
        self.contentLabel.setVisible(True)
        self.contentLabel.setWordWrap(False)
        self.contentLabel.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.contentLabel.setText(self.content)
        lines = [line for line in self.content.splitlines() if line] or [self.content]
        metrics = self.contentLabel.fontMetrics()
        text_width = max(metrics.horizontalAdvance(line) for line in lines)
        # A few extra pixels keep the last glyph inside the label bounds.
        width = max(text_width + 4, _HELP_TEXT_MIN_WIDTH)
        self.contentLabel.setMinimumWidth(width)
        self.contentLabel.setMaximumWidth(width)


class _HelpTipPositionManager(BottomTailTeachingTipManager):
    @override
    def position(self, tip: TeachingTip) -> QPoint:
        position = super()._pos(tip) - QPoint(0, _HELP_TIP_GAP)
        target_rect = QRect(tip.target.mapToGlobal(QPoint()), tip.target.size())
        margins = tip.hBoxLayout.contentsMargins()
        size = tip.sizeHint()
        screen = tip.target.screen().availableGeometry()
        above = position.y() + margins.top() >= screen.top()
        if not above:
            position.setY(target_rect.bottom() + 1 + _HELP_TIP_GAP - margins.top())
        position.setX(max(screen.left(), min(position.x(), screen.right() - size.width() + 1)))

        manager_type = BottomTailTeachingTipManager if above else TopTailTeachingTipManager
        if not isinstance(tip.bubble.manager, manager_type):
            manager = manager_type()
            tip.bubble.manager = manager
            tip.view.manager = manager
            manager.doLayout(tip.bubble)
            tip.bubble.update()
        # Native mask scaling can round an edge inward at fractional DPI.
        input_exclusion = target_rect.adjusted(-1, -1, 1, 1).translated(-position)
        tip.setMask(QRegion(QRect(QPoint(), size)).subtracted(QRegion(input_exclusion)))
        return position


class _HelpTip(TeachingTip):
    def __init__(self, view: TeachingTipView, target: QWidget) -> None:
        super().__init__(
            view,
            target,
            duration=-1,
            tailPosition=TeachingTipTailPosition.BOTTOM,
            parent=target.window(),
            isDeleteOnClose=True,
        )
        # Shadow repaint regions must stay inside the native window when the arrow changes sides.
        bubble_rect = self.bubble.rect()
        shadow_rect = self.shadowEffect.boundingRectFor(QRectF(bubble_rect)).toAlignedRect()
        self.hBoxLayout.setContentsMargins(
            bubble_rect.left() - shadow_rect.left(),
            bubble_rect.top() - shadow_rect.top(),
            shadow_rect.right() - bubble_rect.right(),
            shadow_rect.bottom() - bubble_rect.bottom(),
        )
        self.manager = _HelpTipPositionManager()
        widget: QWidget | None = target
        while widget is not None:
            widget.installEventFilter(self)
            widget = widget.parentWidget()

    @override
    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if e.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.WindowStateChange):
            self.move(self.manager.position(self))
            return False
        return super().eventFilter(obj, e)


class _OutsideClickFilter(QObject):
    """Closes the open help tip when a press lands outside the tip and its button."""

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.MouseButtonPress or not isinstance(watched, QWidget):
            return False
        HelpHintButton.dismiss_outside(watched)
        return False


def _widget_is_inside(widget: QWidget, container: QWidget) -> bool:
    current: QWidget | None = widget
    while current is not None:
        if current is container:
            return True
        current = current.parentWidget()
    return False


def help_field_label(title_key: str, help_key: str, parent: QWidget) -> QWidget:
    """Field name plus a help button, used as a form-row label."""
    host = QWidget(parent)
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(BodyLabel(tr(title_key), host), alignment=Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(HelpHintButton(help_key, host), alignment=Qt.AlignmentFlag.AlignVCenter)
    layout.addStretch(1)
    return host


class HelpHintButton(QAbstractButton):
    """Question mark with one shared tip anchored to the visible button.

    The popup shadow must not increase the visible gap or intercept clicks on the button.
    """

    _owner: ClassVar[HelpHintButton | None] = None
    _tip: ClassVar[TeachingTip | None] = None
    _filter: ClassVar[_OutsideClickFilter | None] = None
    _open_generation: ClassVar[int] = 0

    def __init__(self, help_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.help_key = help_key
        self._pointer_inside = False
        self._suppressed = False
        self._scroll_bound = False
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_OPEN_DELAY_MS)
        self._hover_timer.timeout.connect(self._open_from_hover)
        self.setObjectName(f"helpHint.{help_key}")
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(tr("config.help.button"))
        self.setAccessibleDescription(tr(help_key))
        self.clicked.connect(self._on_clicked)
        self.destroyed.connect(self._release_tip)

    @classmethod
    def dismiss_outside(cls, watched: QWidget) -> None:
        owner = cls._owner
        tip = cls._tip
        if owner is None or tip is None or not isValid(owner) or not isValid(tip):
            return
        if _widget_is_inside(watched, owner) or _widget_is_inside(watched, tip):
            return
        owner.dismiss(suppress=False)

    def dismiss(self, *, suppress: bool) -> None:
        """Close this button's tip. `suppress` keeps hover from reopening it until the pointer leaves."""
        self._hover_timer.stop()
        self._suppressed = suppress
        if HelpHintButton._owner is self:
            HelpHintButton.close_tip()

    @classmethod
    def close_tip(cls) -> None:
        owner = cls._owner
        tip = cls._tip
        cls._owner = None
        cls._tip = None
        if owner is not None and isValid(owner):
            owner.update()
        if tip is None or not isValid(tip):
            return
        # TeachingTip destroys itself on the next event-loop turn. A newer tip must survive that signal.
        cls._open_generation += 1
        tip.close()

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        self._pointer_inside = True
        self.update()
        if not self._suppressed and not self._owns_open_tip():
            self._hover_timer.start()
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        self._pointer_inside = False
        self._suppressed = False
        self._hover_timer.stop()
        self.update()
        super().leaveEvent(event)

    @override
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._bind_scroll()

    @override
    def hideEvent(self, event: QHideEvent) -> None:
        if self._owns_open_tip():
            self.dismiss(suppress=False)
        super().hideEvent(event)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        neutral = QColor(220, 220, 220) if isDarkTheme() else QColor(90, 90, 90)
        border = themeColor() if self._owns_open_tip() else neutral
        fill = QColor(0, 0, 0, 0)
        if self._pointer_inside or self._owns_open_tip():
            fill = QColor(255, 255, 255, 36) if isDarkTheme() else QColor(0, 0, 0, 18)
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(1, 1, self.width() - 2, self.height() - 2))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(border)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "?")

    def _owns_open_tip(self) -> bool:
        return HelpHintButton._owner is self and HelpHintButton._tip is not None and isValid(HelpHintButton._tip)

    def _on_clicked(self) -> None:
        if self._owns_open_tip():
            self.dismiss(suppress=True)
            return
        if self._suppressed:
            return
        self._open_tip()

    def _open_from_hover(self) -> None:
        if not self._pointer_inside or self._suppressed or self._owns_open_tip():
            return
        self._open_tip()

    def _open_tip(self) -> None:
        self._hover_timer.stop()
        if HelpHintButton._owner is not self:
            HelpHintButton.close_tip()
        if self._owns_open_tip():
            return
        text = tr(self.help_key)
        self.setAccessibleDescription(text)
        tip = _HelpTip(_HelpTipView(text), self)
        tip.show()
        generation = HelpHintButton._open_generation
        HelpHintButton._tip = tip
        HelpHintButton._owner = self

        def forget() -> None:
            if HelpHintButton._open_generation == generation:
                HelpHintButton._tip = None
                HelpHintButton._owner = None

        tip.destroyed.connect(forget)
        HelpHintButton._ensure_filter()
        self.update()

    def _bind_scroll(self) -> None:
        if self._scroll_bound:
            return
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, QAbstractScrollArea):
                for bar in (widget.verticalScrollBar(), widget.horizontalScrollBar()):
                    if bar is not None:
                        bar.valueChanged.connect(self._on_scrolled)
                self._scroll_bound = True
                return
            widget = widget.parentWidget()

    def _on_scrolled(self, _value: int) -> None:
        owner = HelpHintButton._owner
        if owner is not None and isValid(owner) and owner.window() is self.window():
            owner.dismiss(suppress=False)

    def _release_tip(self, _obj: QObject | None = None) -> None:
        if HelpHintButton._owner is self:
            HelpHintButton.close_tip()

    @classmethod
    def _ensure_filter(cls) -> None:
        app = QApplication.instance()
        if app is None or cls._filter is not None:
            return
        cls._filter = _OutsideClickFilter(app)
        app.installEventFilter(cls._filter)
