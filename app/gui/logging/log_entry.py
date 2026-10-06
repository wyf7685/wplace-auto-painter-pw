from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogEntry:
    """Immutable ANSI text and severity passed from log workers to Qt."""

    text: str
    level_no: int
