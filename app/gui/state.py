import dataclasses
from typing import ClassVar

from pydantic import TypeAdapter
from PySide6.QtCore import QPoint, QSize

from app.const import DATA_DIR

_GUI_STATE_FILE = DATA_DIR / "gui_state.json"


@dataclasses.dataclass
class MainWindowState:
    top_left: tuple[int, int] | None = None
    size: tuple[int, int] | None = None

    @property
    def top_left_point(self) -> QPoint | None:
        if self.top_left is None:
            return None
        return QPoint(*self.top_left)

    @top_left_point.setter
    def top_left_point(self, point: QPoint | None) -> None:
        if point is None:
            self.top_left = None
        else:
            self.top_left = (point.x(), point.y())

    @property
    def size_value(self) -> QSize | None:
        if self.size is None:
            return None
        return QSize(*self.size)

    @size_value.setter
    def size_value(self, value: QSize | None) -> None:
        if value is None:
            self.size = None
        else:
            self.size = (value.width(), value.height())


@dataclasses.dataclass
class GUIState:
    _instance: ClassVar[GUIState | None] = None

    main_window: MainWindowState = dataclasses.field(default_factory=MainWindowState)

    @classmethod
    def load(cls) -> GUIState:
        if cls._instance is not None:
            return cls._instance

        if _GUI_STATE_FILE.is_file():
            try:
                state = _state_ta.validate_json(_GUI_STATE_FILE.read_bytes())
            except Exception:
                state = cls()
        else:
            state = cls()

        cls._instance = state
        return state

    @classmethod
    def save(cls) -> None:
        _GUI_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GUI_STATE_FILE.write_bytes(_state_ta.dump_json(cls.load()))


_state_ta = TypeAdapter(GUIState)
