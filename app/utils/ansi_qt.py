"""ANSI SGR → QTextCharFormat converter for Qt text widgets.

Covers the full SGR subset that loguru can emit with ``colorize=True``.
The ``Style``, ``Fore``, ``Back`` constants are mirrored from loguru's
``_colorizer`` module so the mapping stays in sync with its output.

Text style
~~~~~~~~~~
  on:  bold (1), dim (2), italic (3), underline (4), strike (9)
  off: normal (22), italic-off (23), underline-off (24), strike-off (29)
  no Qt equivalent, silently ignored: blink (5), reverse (7), hide (8)

Colour
~~~~~~
  Foreground  standard (30-37), default (39), bright (90-97)
              256-colour  ESC[38;5;Nm
              true-colour ESC[38;2;R;G;Bm
  Background  standard (40-47), default (49), bright (100-107)
              256-colour  ESC[48;5;Nm
              true-colour ESC[48;2;R;G;Bm

Reset
~~~~~
  ESC[0m or ESC[m
"""

import re
from collections.abc import Iterable, Iterator
from typing import Final

from PySide6.QtGui import QColor, QTextCharFormat


class Style:
    RESET_ALL = 0
    BOLD = 1
    DIM = 2
    ITALIC = 3
    UNDERLINE = 4
    BLINK = 5
    REVERSE = 7
    HIDE = 8
    STRIKE = 9
    NORMAL = 22


class Fore:
    BLACK = 30
    RED = 31
    GREEN = 32
    YELLOW = 33
    BLUE = 34
    MAGENTA = 35
    CYAN = 36
    WHITE = 37
    RESET = 39

    LIGHTBLACK_EX = 90
    LIGHTRED_EX = 91
    LIGHTGREEN_EX = 92
    LIGHTYELLOW_EX = 93
    LIGHTBLUE_EX = 94
    LIGHTMAGENTA_EX = 95
    LIGHTCYAN_EX = 96
    LIGHTWHITE_EX = 97


class Back:
    BLACK = 40
    RED = 41
    GREEN = 42
    YELLOW = 43
    BLUE = 44
    MAGENTA = 45
    CYAN = 46
    WHITE = 47
    RESET = 49

    LIGHTBLACK_EX = 100
    LIGHTRED_EX = 101
    LIGHTGREEN_EX = 102
    LIGHTYELLOW_EX = 103
    LIGHTBLUE_EX = 104
    LIGHTMAGENTA_EX = 105
    LIGHTCYAN_EX = 106
    LIGHTWHITE_EX = 107


# Splits a log line into alternating plain-text and ESC[…m tokens.
_SGR_RE: Final = re.compile(r"(\x1b\[[0-9;]*m)")

# Windows Terminal default 16-colour palette (indices 0-7 normal, 8-15 bright).
_PALETTE: Final[tuple[QColor, ...]] = (
    QColor(0x0C, 0x0C, 0x0C),  # 0  black
    QColor(0xC5, 0x0F, 0x1F),  # 1  red
    QColor(0x13, 0xA1, 0x0E),  # 2  green
    QColor(0xC1, 0x9C, 0x00),  # 3  yellow
    QColor(0x00, 0x37, 0xDA),  # 4  blue
    QColor(0x88, 0x17, 0x98),  # 5  magenta
    QColor(0x3A, 0x96, 0xDD),  # 6  cyan
    QColor(0xCC, 0xCC, 0xCC),  # 7  white
    QColor(0x76, 0x76, 0x76),  # 8  bright black (dark grey)
    QColor(0xE7, 0x48, 0x56),  # 9  bright red
    QColor(0x16, 0xC6, 0x0C),  # 10 bright green
    QColor(0xF9, 0xF1, 0xA5),  # 11 bright yellow
    QColor(0x3B, 0x78, 0xFF),  # 12 bright blue
    QColor(0xB4, 0x00, 0x9E),  # 13 bright magenta
    QColor(0x61, 0xD6, 0xD6),  # 14 bright cyan
    QColor(0xF2, 0xF2, 0xF2),  # 15 bright white
)

# Exported: consumed by LogWindow to style the editor widget background.
DEFAULT_FG: Final = QColor(0xF2, 0xF2, 0xF2)
LOG_BG: Final = QColor(0x1E, 0x1E, 0x1E)  # VS Code Dark+ background


def _base_fmt() -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(DEFAULT_FG)
    return fmt


# ── 256-colour support ─────────────────────────────────────────────────────────


def _cube_component(c: int) -> int:
    """Map a 6-level cube axis value (0-5) to an 8-bit intensity."""
    return 0 if c == 0 else 55 + c * 40


def _palette_256(n: int) -> QColor:
    """Convert an xterm 256-colour index to QColor.

    Layout:
      0-15   : the 16 named colours in ``_PALETTE``
      16-231 : 6×6×6 colour cube
      232-255: 24-step greyscale ramp (8, 18, …, 238)
    """
    if n < 16:
        return _PALETTE[n]
    if n < 232:
        n -= 16
        r, g, b = n // 36, (n // 6) % 6, n % 6
        return QColor(_cube_component(r), _cube_component(g), _cube_component(b))
    v = 8 + (n - 232) * 10
    return QColor(v, v, v)


def _consume_color(it: Iterator[int], selector: int, fmt: QTextCharFormat) -> None:
    """Consume the sub-params of an extended-colour sequence (38 or 48).

    Handles both 256-colour (selector;5;n) and true-colour (selector;2;R;G;B).
    Mutates *fmt* in place.  Silently does nothing on malformed sequences.
    """
    try:
        mode = next(it)
        if mode == 5:  # 256-colour
            color = _palette_256(next(it))
        elif mode == 2:  # true-colour
            color = QColor(next(it), next(it), next(it))
        else:
            return
    except StopIteration:
        return

    if selector == 38:
        fmt.setForeground(color)
    else:
        fmt.setBackground(color)


# ── SGR state machine ──────────────────────────────────────────────────────────


def _apply_sgr(params_str: str, fmt: QTextCharFormat) -> QTextCharFormat:
    """Return a *new* QTextCharFormat with the SGR parameter string applied.

    *params_str* is the content between ``ESC[`` and ``m`` (may be empty
    for a bare reset ``ESC[m``).
    """
    fmt = QTextCharFormat(fmt)
    raw = [int(p) for p in params_str.split(";") if p] if params_str else [0]
    it: Iterator[int] = iter(raw)

    for p in it:
        if p == Style.RESET_ALL:
            fmt = _base_fmt()
        elif p == Style.BOLD:
            fmt.setFontWeight(700)
        elif p == Style.DIM:
            fmt.setFontWeight(300)
        elif p == Style.ITALIC:
            fmt.setFontItalic(True)
        elif p == Style.UNDERLINE:
            fmt.setFontUnderline(True)
        elif p == Style.STRIKE:
            fmt.setFontStrikeOut(True)
        elif p == Style.NORMAL:
            fmt.setFontWeight(400)
        elif p == 23:  # italic off
            fmt.setFontItalic(False)
        elif p == 24:  # underline off
            fmt.setFontUnderline(False)
        elif p == 29:  # strikethrough off
            fmt.setFontStrikeOut(False)
        elif Fore.BLACK <= p <= Fore.WHITE:
            fmt.setForeground(_PALETTE[p - Fore.BLACK])
        elif p == Fore.RESET:
            fmt.setForeground(DEFAULT_FG)
        elif Fore.LIGHTBLACK_EX <= p <= Fore.LIGHTWHITE_EX:
            fmt.setForeground(_PALETTE[p - Fore.LIGHTBLACK_EX + 8])
        elif Back.BLACK <= p <= Back.WHITE:
            fmt.setBackground(_PALETTE[p - Back.BLACK])
        elif p == Back.RESET:
            fmt.clearBackground()
        elif Back.LIGHTBLACK_EX <= p <= Back.LIGHTWHITE_EX:
            fmt.setBackground(_PALETTE[p - Back.LIGHTBLACK_EX + 8])
        elif p in (38, 48):  # extended colour: consume sub-params from the iterator
            _consume_color(it, p, fmt)
        # Style.BLINK (5), Style.REVERSE (7), Style.HIDE (8): no Qt equivalent, skip

    return fmt


def iter_segments(text: str) -> Iterable[tuple[str, QTextCharFormat]]:
    """Yield ``(plain_text, format)`` pairs for each visually distinct run in *text*.

    Typical usage::

        cursor = edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for segment, fmt in iter_segments(ansi_line):
            cursor.insertText(segment, fmt)
    """
    fmt = _base_fmt()
    for token in _SGR_RE.split(text):
        if not token:
            continue
        if token[0] == "\x1b":
            # token is "ESC[…m"; strip the 2-char prefix ESC[ and trailing m
            fmt = _apply_sgr(token[2:-1], fmt)
        else:
            yield token, fmt
