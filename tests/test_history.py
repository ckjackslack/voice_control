import datetime as dt
import json

import pytest

from voice_control import History, HistoryEntry, HistoryError
from voice_control.apps import HomeControl, PaintControl, Point, Rectangle
from voice_control.controller import Result


def test_records_only_successful_commands():
    p = PaintControl()
    h = History()
    assert h.record(p.dispatch("draw circle of radius 1 at 0 0"))
    assert not h.record(p.dispatch("gibberish"))
    assert not h.record(p.dispatch("draw circle of radius 0 at 0 0"))
    assert [e.command for e in h] == ["make_circle"]
    assert h.entries[0].args == {"radius": "1", "position": "0 0"}


def test_save_load_roundtrip_and_replay(tmp_path):
    p = PaintControl()
    h = History()
    for text in [
        "make rectangle of width 10 and height 20 with top left corner at 5, 5",
        "draw circle of radius 3 at 1 1",
        "undo",
    ]:
        h.record(p.dispatch(text))
    path = tmp_path / "h.json"
    h.save(path)

    data = json.loads(path.read_text())
    assert data["version"] == 1 and len(data["entries"]) == 3

    loaded = History.load(path)
    assert [e.command for e in loaded] == ["make_rectangle", "make_circle", "undo"]
    assert loaded.entries[0].timestamp == h.entries[0].timestamp

    fresh = PaintControl()
    results = loaded.replay(fresh)
    assert all(r.ok for r in results)
    assert fresh.shapes == [Rectangle(10, 20, Point(5, 5))] == p.shapes


def test_replay_against_wrong_app_raises():
    h = History([HistoryEntry("make_circle", {}, "x", dt.datetime.now())])
    with pytest.raises(HistoryError, match="no command named"):
        h.replay(HomeControl())


def test_accepts_bare_list_and_missing_optional_fields():
    raw = json.dumps([{"command": "status", "timestamp": "2024-01-04T21:52:35"}])
    h = History.from_json(raw)
    assert h.entries[0].text == "status" and h.entries[0].args == {}


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '"a string"',
        '{"entries": 3}',
        "[1]",
        '[{"timestamp": "2024-01-01T00:00:00"}]',
        '[{"command": "x", "timestamp": "yesterday"}]',
        '[{"command": "x", "args": [], "timestamp": "2024-01-01T00:00:00"}]',
    ],
)
def test_malformed_history(raw):
    with pytest.raises(HistoryError):
        History.from_json(raw)


def test_load_missing_and_save_unwritable(tmp_path):
    with pytest.raises(HistoryError, match="cannot read"):
        History.load(tmp_path / "missing.json")
    with pytest.raises(HistoryError, match="cannot write"):
        History().save(tmp_path / "no" / "such" / "dir.json")


def test_entry_from_unmatched_result_rejected():
    with pytest.raises(ValueError):
        HistoryEntry.from_result(Result(text="x"))
