from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogEntry:
    """Immutable ANSI log record sequenced within a bridge's lifetime."""

    text: str
    level_no: int
    sequence: int
