from bot7685_ext.wplace.consts import ALL_COLORS, ColorName
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ElevatedCardWidget, LineEdit, ListWidget, PushButton


class PreferredColorsEditor(QWidget):
    """Fluent editor for preferred colors based on ALL_COLORS mapping."""

    def __init__(self) -> None:
        super().__init__()
        self._color_map: dict[ColorName, tuple[int, int, int]] = dict(ALL_COLORS)

        self._hint_label = BodyLabel("Pick colors from the left list, then reorder priority on the right")

        self._filter_edit = LineEdit()
        self._filter_edit.setPlaceholderText("Filter by name or hex (#RRGGBB)")
        self._filter_edit.textChanged.connect(self._refresh_available_list)

        self._available_list = ListWidget()
        self._available_list.setMinimumHeight(160)
        self._available_list.setSelectionMode(ListWidget.SelectionMode.SingleSelection)
        self._available_list.itemDoubleClicked.connect(self._on_add_clicked)

        self._selected_list = ListWidget()
        self._selected_list.setMinimumHeight(160)
        self._selected_list.setSelectionMode(ListWidget.SelectionMode.SingleSelection)
        self._selected_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._selected_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._selected_list.itemDoubleClicked.connect(self._on_remove_clicked)

        self._add_btn = PushButton("Add ->")
        self._add_btn.clicked.connect(self._on_add_clicked)

        self._remove_btn = PushButton("<- Remove")
        self._remove_btn.clicked.connect(self._on_remove_clicked)

        self._clear_btn = PushButton("Clear")
        self._clear_btn.clicked.connect(self._on_clear_clicked)

        left_card = ElevatedCardWidget(self)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(6)
        left_layout.addWidget(BodyLabel("Available Colors"))
        left_layout.addWidget(self._filter_edit)
        left_layout.addWidget(self._available_list)

        right_card = ElevatedCardWidget(self)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(6)
        right_layout.addWidget(BodyLabel("Priority (Top = Highest)"))
        right_layout.addWidget(self._selected_list)

        ops_layout = QVBoxLayout()
        ops_layout.setSpacing(8)
        ops_layout.addStretch()
        ops_layout.addWidget(self._add_btn)
        ops_layout.addWidget(self._remove_btn)
        ops_layout.addWidget(self._clear_btn)
        ops_layout.addStretch()

        list_row = QHBoxLayout()
        list_row.setSpacing(10)
        list_row.addWidget(left_card, stretch=1)
        list_row.addLayout(ops_layout)
        list_row.addWidget(right_card, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self._hint_label)
        root.addLayout(list_row)

        self._refresh_available_list()

    @staticmethod
    def _hex_of(rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

    @staticmethod
    def _swatch_icon(rgb: tuple[int, int, int]) -> QIcon:
        pixmap = QPixmap(14, 14)
        pixmap.fill(QColor(*rgb))
        return QIcon(pixmap)

    def _make_item(self, name: str) -> QListWidgetItem:
        assert name in self._color_map, f"Color name '{name}' not found in color map"
        rgb = self._color_map[name]
        item = QListWidgetItem(f"{name}  {self._hex_of(rgb)}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        item.setToolTip(f"RGB: {rgb[0]}, {rgb[1]}, {rgb[2]}")
        item.setIcon(self._swatch_icon(rgb))
        return item

    def set_colors(self, colors: list[str]) -> None:
        self._selected_list.clear()
        seen: set[str] = set()
        for color in colors:
            value = str(color).strip()
            if not value or value in seen or value not in self._color_map:
                continue
            self._selected_list.addItem(self._make_item(value))
            seen.add(value)
        self._refresh_available_list()

    def colors(self) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for idx in range(self._selected_list.count()):
            item = self._selected_list.item(idx)
            if item is None:
                continue
            raw = item.data(Qt.ItemDataRole.UserRole)
            value = str(raw).strip() if raw is not None else ""
            if not value or value in seen:
                continue
            result.append(value)
            seen.add(value)
        return result

    def _refresh_available_list(self) -> None:
        query = self._filter_edit.text().strip().lower()
        selected = set(self.colors())
        self._available_list.clear()

        for name, rgb in self._color_map.items():
            if name in selected:
                continue

            hex_value = self._hex_of(rgb).lower()
            if query and query not in name.lower() and query not in hex_value:
                continue

            self._available_list.addItem(self._make_item(name))

    def _on_add_clicked(self) -> None:
        item = self._available_list.currentItem()
        if item is None:
            return

        raw = item.data(Qt.ItemDataRole.UserRole)
        name = str(raw).strip() if raw is not None else ""
        if not name or name in set(self.colors()):
            return

        self._selected_list.addItem(self._make_item(name))
        self._selected_list.setCurrentRow(self._selected_list.count() - 1)
        self._refresh_available_list()

    def _on_remove_clicked(self) -> None:
        row = self._selected_list.currentRow()
        if row < 0:
            return

        self._selected_list.takeItem(row)
        if self._selected_list.count() == 0:
            self._refresh_available_list()
            return

        self._selected_list.setCurrentRow(min(row, self._selected_list.count() - 1))
        self._refresh_available_list()

    def _on_clear_clicked(self) -> None:
        if self._selected_list.count() == 0:
            return
        self._selected_list.clear()
        self._refresh_available_list()
