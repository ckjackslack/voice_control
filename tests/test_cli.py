import io
import json
import subprocess
import sys

import pytest

from voice_control import ScriptedRecognizer, UnrecognizedSpeech
from voice_control.cli import main


def run_cli(*argv, stdin="", factory=None):
    out, err = io.StringIO(), io.StringIO()
    code = main(
        list(argv),
        stdin=io.StringIO(stdin),
        stdout=out,
        stderr=err,
        recognizer_factory=factory,
    )
    return code, out.getvalue(), err.getvalue()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("APP", "BACKEND", "ENGINE", "LANGUAGE", "HISTORY"):
        monkeypatch.delenv(f"VOICE_CONTROL_{var}", raising=False)


def test_help_and_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "run" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "voice-control 0.2.0" in capsys.readouterr().out


def test_missing_subcommand_is_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_list_apps_and_commands():
    code, out, _ = run_cli("list", "--apps")
    assert code == 0 and "home:" in out and "paint:" in out
    code, out, _ = run_cli("list", "--app", "paint")
    assert code == 0 and out.startswith("make_rectangle:")


def test_do_executes_in_order_on_one_controller():
    code, out, _ = run_cli(
        "do", "--app", "paint", "draw circle of radius 2 at 1 1", "list shapes"
    )
    assert code == 0
    assert out.splitlines() == ["Making circle r=2 at (1, 1)", "1. circle r=2 at (1, 1)"]


def test_do_nonzero_exit_on_unrecognized_or_failed():
    code, out, _ = run_cli("do", "make coffee")
    assert code == 1 and "not recognized" in out
    code, out, _ = run_cli("do", "--app", "paint", "undo")
    assert code == 1 and "Error: nothing to undo" in out


def test_app_from_env(monkeypatch):
    monkeypatch.setenv("VOICE_CONTROL_APP", "paint")
    code, out, _ = run_cli("do", "show canvas")
    assert code == 0 and out.strip() == "Canvas is empty"


def test_bad_app_is_clean_error():
    code, out, err = run_cli("do", "--app", "nope", "x")
    assert code == 2 and out == "" and "unknown app 'nope'" in err


def test_history_appends_across_invocations_then_replay(tmp_path):
    hist = tmp_path / "h.json"
    assert run_cli("do", "-a", "paint", "--history", str(hist), "draw circle of radius 1 at 0 0")[0] == 0
    run_cli("do", "-a", "paint", "--history", str(hist), "make rectangle of width 2 and height 3 at 4 5", "nonsense")
    entries = json.loads(hist.read_text())["entries"]
    assert [e["command"] for e in entries] == ["make_circle", "make_rectangle"]

    code, out, _ = run_cli("replay", "-a", "paint", str(hist))
    assert code == 0
    assert out.splitlines() == [
        "> draw circle of radius 1 at 0 0",
        "Making circle r=1 at (0, 0)",
        "> make rectangle of width 2 and height 3 at 4 5",
        "Making rectangle 2x3 at (4, 5)",
    ]


def test_replay_errors(tmp_path):
    code, _, err = run_cli("replay", str(tmp_path / "missing.json"))
    assert code == 2 and "cannot read history" in err
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    code, _, err = run_cli("do", "--history", str(bad), "status")
    assert code == 2 and "not valid JSON" in err
    hist = tmp_path / "paint.json"
    run_cli("do", "-a", "paint", "--history", str(hist), "undo", "draw circle of radius 1 at 0 0")
    code, _, err = run_cli("replay", "-a", "home", str(hist))
    assert code == 2 and "no command named 'make_circle'" in err


def test_replay_reports_failing_entries(tmp_path):
    hist = tmp_path / "h.json"
    hist.write_text(json.dumps([{"command": "undo", "timestamp": "2024-01-07T22:03:52"}]))
    code, out, _ = run_cli("replay", "-a", "paint", str(hist))
    assert code == 1 and "Error: nothing to undo" in out


def test_unwritable_history_is_reported(tmp_path):
    code, out, err = run_cli("do", "--history", str(tmp_path / "x" / "h.json"), "lights on")
    assert code == 1 and "Turning on the light" in out and "cannot write" in err


def test_run_text_backend_reads_stdin(tmp_path):
    hist = tmp_path / "h.json"
    stdin = "turn on the light\n\nset volume to 20\nstatus\nexit\nlights off\n"
    code, out, _ = run_cli("run", "--history", str(hist), stdin=stdin)
    assert code == 0
    assert "Light is on; playing nothing; volume 20" in out
    assert out.rstrip().endswith("Bye.")
    assert len(json.loads(hist.read_text())["entries"]) == 3


def test_run_once():
    code, out, _ = run_cli("run", "--once", stdin="lights on\nlights off\n")
    assert code == 0
    assert out.splitlines() == ["You said: lights on", "Turning on the light"]


def test_run_with_fake_microphone_factory():
    seen_args = {}

    def factory(args, stdin, stdout):
        seen_args.update(vars(args))
        return ScriptedRecognizer([UnrecognizedSpeech("noise"), "Draw a circle of radius 4 at 2, 2.", "list shapes"])

    code, out, _ = run_cli(
        "run", "-a", "paint", "-b", "mic", "--engine", "sphinx", "--language", "de-DE", "--timeout", "2", factory=factory
    )
    assert code == 0
    assert seen_args["engine"] == "sphinx" and seen_args["language"] == "de-DE" and seen_args["timeout"] == 2.0
    assert out.splitlines()[0].startswith("Listening...")
    assert "(didn't catch that: noise)" in out
    assert "1. circle r=4 at (2, 2)" in out


def test_run_backend_error_exit_code():
    from voice_control import BackendError

    def factory(args, stdin, stdout):
        raise BackendError("no microphone")

    code, _, err = run_cli("run", "-b", "mic", factory=factory)
    assert code == 1 and "no microphone" in err


def test_run_keyboard_interrupt_saves_history(tmp_path):
    hist = tmp_path / "h.json"

    def factory(args, stdin, stdout):
        return ScriptedRecognizer(["lights on", KeyboardInterrupt()])

    code, out, _ = run_cli("run", "--history", str(hist), factory=factory)
    assert code == 130 and "Interrupted." in out
    assert len(json.loads(hist.read_text())["entries"]) == 1


@pytest.mark.parametrize("value", ["abc", "-1", "0"])
def test_invalid_timeout_rejected(value, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--timeout", value])
    assert exc.value.code == 2


def test_python_dash_m_entry_point():
    proc = subprocess.run(
        [sys.executable, "-m", "voice_control", "do", "status"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "Light is off; playing nothing; volume 50"
