"""ANSI SGR → QTextCharFormat converter for Qt text widgets.

Handles the SGR subset that loguru emits with ``colorize=True``:

  - Standard / bright foreground  ESC[3Xm / ESC[9Xm   (X = 0–7)
  - Standard / bright background  ESC[4Xm / ESC[10Xm
  - Bold / dim / normal weight    ESC[1m  / ESC[2m  / ESC[22m
  - Underline on / off            ESC[4m  / ESC[24m
  - Reset                         ESC[0m  or  ESC[m

256-colour and RGB sequences (ESC[38;2;…m etc.) are intentionally ignored;
they do not appear in loguru's standard log output.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from PyQt6.QtGui import QColor, QTextCharFormat

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


def _apply_sgr(params_str: str, fmt: QTextCharFormat) -> QTextCharFormat:
    """Return a *new* QTextCharFormat with the SGR parameter string applied.

    *params_str* is the content between ``ESC[`` and ``m`` (may be empty
    for a bare reset ``ESC[m``).
    """
    fmt = QTextCharFormat(fmt)
    params = [int(p) for p in params_str.split(";") if p] if params_str else [0]

    for p in params:
        if p == 0:  # full reset
            fmt = _base_fmt()
        elif p == 1:  # bold
            fmt.setFontWeight(700)
        elif p == 2:  # dim / faint
            fmt.setFontWeight(300)
        elif p == 22:  # normal weight
            fmt.setFontWeight(400)
        elif p == 4:  # underline on
            fmt.setFontUnderline(True)
        elif p == 24:  # underline off
            fmt.setFontUnderline(False)
        elif 30 <= p <= 37:  # standard foreground
            fmt.setForeground(_PALETTE[p - 30])
        elif p == 39:  # default foreground
            fmt.setForeground(DEFAULT_FG)
        elif 40 <= p <= 47:  # standard background
            fmt.setBackground(_PALETTE[p - 40])
        elif p == 49:  # default background
            fmt.clearBackground()
        elif 90 <= p <= 97:  # bright foreground
            fmt.setForeground(_PALETTE[p - 90 + 8])
        elif 100 <= p <= 107:  # bright background
            fmt.setBackground(_PALETTE[p - 100 + 8])
        # unrecognised codes are silently skipped

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
