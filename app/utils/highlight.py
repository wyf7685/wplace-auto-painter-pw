import contextlib
import dataclasses
import datetime
import enum
import functools
from contextvars import ContextVar
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, cast

from bot7685_ext import LRU
from pydantic import BaseModel

from app.log import escape_tag

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

DATETIME_FIELDS = [
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "microsecond",
]


class _StyleCall(Protocol):
    def __call__(self, obj: object, /, *, escape: bool = False) -> str: ...


class _Style:
    def __getattr__(self, tag: str) -> _StyleCall:
        tags = tag.split("_")
        prefix = "".join(f"<{tag}>" for tag in reversed(tags))
        suffix = "</>" * len(tags)
        lru: LRU[str, str] = LRU(64)

        def fn(obj: object, /, *, escape: bool = False) -> str:
            text = escape_tag(str(obj)) if escape else str(obj)
            if text not in lru:
                lru[text] = f"{prefix}{text}{suffix}"
            return lru[text]

        fn.__name__ = tag
        fn.__qualname__ = f"Style.{tag}"
        setattr(self, tag, fn)
        return fn


style = _Style()


class _Unset(Enum):
    UNSET = enum.auto()


UNSET = _Unset.UNSET
type Unset = Literal[_Unset.UNSET]

_struct_indent = ContextVar[int | None]("highlight_struct_indent", default=None)
_struct_depth = ContextVar[int]("highlight_struct_depth", default=0)
_line_length = ContextVar[int]("highlight_line_length", default=120)


def with_struct_depth[F: Callable](fn: F) -> F:
    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        with _struct_depth.set(_struct_depth.get() + 1):
            return fn(*args, **kwargs)

    return cast("F", wrapper)


class Highlight:
    style: ClassVar[_Style] = style
    exclude_value: ClassVar[tuple[object, ...]] = ()

    @classmethod
    def repr(cls, data: object, /, *color: str) -> str:
        text = escape_tag(repr(data))
        if color:
            prefix = "".join(f"<{tag}>" for tag in reversed(color))
            suffix = "</>" * len(color)
            text = f"{prefix}{text}{suffix}"
        return text

    @functools.singledispatchmethod
    @classmethod
    def _handle(cls, data: object) -> str:
        if dataclasses.is_dataclass(data) and not isinstance(data, type):
            return cls.__dataclass(data)
        return cls.repr(data)

    register = _handle.register  # pyright:ignore[reportUnannotatedClassAttribute]

    @classmethod
    def apply(
        cls,
        data: object,
        /,
        indent: int | None | Unset = UNSET,
        line_length: int | Unset = UNSET,
    ) -> str:
        if indent is UNSET and line_length is UNSET:
            return cls._handle(data)
        with contextlib.ExitStack() as stack:
            if indent is not UNSET:
                stack.enter_context(_struct_indent.set(indent))
            if line_length is not UNSET:
                stack.enter_context(_line_length.set(line_length))
            return cls._handle(data)

    @classmethod
    @functools.cache
    def enum(cls, data: Enum) -> str:
        return f"<{style.g(type(data).__name__)}.{style.le(data.name)}: {cls.apply(data.value)}>"

    @register(bool)
    @classmethod
    @functools.cache
    def _(cls, data: bool) -> str:
        return style.lg(data)

    @register(int)
    @classmethod
    def _(cls, data: int) -> str:
        return cls.enum(data) if isinstance(data, Enum) else style.i_lc(data)

    @register(float)
    @classmethod
    def _(cls, data: float) -> str:
        return style.i_lc(data)

    @register(str)
    @classmethod
    def _(cls, data: str) -> str:
        if isinstance(data, Enum):
            return cls.enum(data)
        text = escape_tag(repr(data))
        return text[0] + style.c(text[1:-1]) + text[-1]

    @classmethod
    def _kv(
        cls,
        items: Iterable[tuple[str, object]],
        separator: str,
        format_key: Callable[[str], str],
        /,
    ) -> Iterable[str]:
        for key, value in items:
            if value not in cls.exclude_value:
                yield f"{format_key(key)}{separator}{cls.apply(value)}"

    @classmethod
    def _seq(cls, seq: Iterable[str], bracket: str, /) -> str:
        st, ed = bracket

        indent = _struct_indent.get()
        if indent is None:
            return f"{st}{', '.join(seq)}{ed}"

        seq = list(seq)
        if not seq:
            return bracket

        depth = _struct_depth.get()
        space = " " * indent * (depth + 1)

        if len(seq) <= 3:
            single_line = f"{st} {', '.join(seq)} {ed}"
            if len(space) + len(single_line) <= _line_length.get() and "\n" not in single_line:
                return single_line

        return f"{st}\n{',\n'.join(f'{space}{i}' for i in seq)}\n{' ' * indent * depth}{ed}"

    @register(dict)
    @classmethod
    @with_struct_depth
    def _(cls, data: dict[str, object]) -> str:
        return cls._seq(cls._kv(data.items(), ": ", style.i_le), "{}")

    @register(list)
    @classmethod
    @with_struct_depth
    def _(cls, data: list[object]) -> str:
        return cls._seq(map(cls.apply, data), "[]")

    @register(set)
    @classmethod
    @with_struct_depth
    def _(cls, data: set[object]) -> str:
        return cls._seq(map(cls.apply, data), "{}")

    @register(tuple)
    @classmethod
    @with_struct_depth
    def _(cls, data: tuple[object]) -> str:
        return cls._seq(map(cls.apply, data), "()")

    @register(datetime.datetime)
    @classmethod
    def _(cls, data: datetime.datetime) -> str:
        attrs = [cls.apply(getattr(data, name)) for name in DATETIME_FIELDS]
        if data.tzinfo is not None:
            attrs.append(style.ly(data.tzinfo))
        return f"{style.g('datetime')}({', '.join(attrs)})"

    @register(BaseModel)
    @classmethod
    @with_struct_depth
    def _(cls, data: BaseModel) -> str:
        model = type(data)
        items = ((name, getattr(data, name)) for name in model.model_fields)
        return f"{style.lg(model.__name__)}{cls._seq(cls._kv(items, '=', style.i_y), '()')}"

    @classmethod
    @with_struct_depth
    def __dataclass(cls, data: object) -> str:
        if TYPE_CHECKING:
            assert dataclasses.is_dataclass(data)
            assert not isinstance(data, type)

        items = ((field.name, getattr(data, field.name)) for field in dataclasses.fields(data))
        return f"{style.lg(type(data).__name__)}{cls._seq(cls._kv(items, '=', style.i_y), '()')}"

    del _
