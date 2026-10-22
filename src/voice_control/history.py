"""Command history: record executed commands, save/load JSON, replay."""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

if TYPE_CHECKING:  # pragma: no cover
    from .controller import Controller, Result

FORMAT_VERSION = 1


class HistoryError(ValueError):
    """The history file is missing, unreadable or malformed."""


@dataclass(frozen=True)
class HistoryEntry:
    command: str
    args: dict[str, str]
    text: str
    timestamp: _dt.datetime

    @classmethod
    def from_result(cls, result: "Result") -> "HistoryEntry":
        if result.command is None:
            raise ValueError("only matched commands can be recorded")
        return cls(result.command, dict(result.args), result.text, result.timestamp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "args": self.args,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "HistoryEntry":
        if not isinstance(data, dict):
            raise HistoryError(f"history entry must be an object, got {type(data).__name__}")
        try:
            name = data["command"]
            args = data.get("args", {}) or {}
            text = data.get("text", name)
            ts = _dt.datetime.fromisoformat(data["timestamp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoryError(f"malformed history entry {data!r}: {exc}") from exc
        if not isinstance(name, str) or not isinstance(args, dict):
            raise HistoryError(f"malformed history entry {data!r}")
        return cls(name, {str(k): str(v) for k, v in args.items()}, str(text), ts)


@dataclass
class History:
    entries: list[HistoryEntry] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[HistoryEntry]:
        return iter(self.entries)

    def record(self, result: "Result") -> bool:
        """Add a successfully executed command; ignore unmatched/failed ones."""
        if not result.ok:
            return False
        self.entries.append(HistoryEntry.from_result(result))
        return True

    def extend(self, entries: Iterable[HistoryEntry]) -> None:
        self.entries.extend(entries)

    # -- persistence ----------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps(
            {"version": FORMAT_VERSION, "entries": [e.to_dict() for e in self.entries]},
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> "History":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HistoryError(f"history is not valid JSON: {exc}") from exc
        if isinstance(data, list):  # bare list of entries is accepted too
            items = data
        elif isinstance(data, dict) and isinstance(data.get("entries"), list):
            items = data["entries"]
        else:
            raise HistoryError("history JSON must be a list or an object with 'entries'")
        return cls([HistoryEntry.from_dict(item) for item in items])

    def save(self, path: str | Path) -> None:
        try:
            Path(path).write_text(self.to_json() + "\n", encoding="utf-8")
        except OSError as exc:
            raise HistoryError(f"cannot write history file {str(path)!r}: {exc.strerror}") from exc

    @classmethod
    def load(cls, path: str | Path) -> "History":
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise HistoryError(f"cannot read history file {str(path)!r}: {exc.strerror}") from exc
        return cls.from_json(raw)

    # -- replay ---------------------------------------------------------------
    def replay(self, controller: "Controller") -> list["Result"]:
        """Re-run every entry against ``controller`` by handler name.

        Raises :class:`HistoryError` if an entry names a command the controller
        does not have (e.g. history recorded with a different app).
        """
        results = []
        for entry in self.entries:
            try:
                results.append(controller.invoke(entry.command, entry.args, entry.text))
            except KeyError as exc:
                raise HistoryError(str(exc.args[0])) from exc
        return results
