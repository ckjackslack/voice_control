"""Backends are tested with fakes only: no microphone, no network."""

import io
import types

import pytest

from voice_control import (
    BackendError,
    EndOfInput,
    History,
    ScriptedRecognizer,
    SpeechRecognitionBackend,
    TextRecognizer,
    UnrecognizedSpeech,
    run_session,
)
from voice_control.apps import HomeControl
from voice_control.backends import make_recognizer


# --------------------------------------------------------------------------- fakes
class FakeSR:
    """Minimal stand-in for the ``speech_recognition`` module."""

    class UnknownValueError(Exception):
        pass

    class RequestError(Exception):
        pass

    class WaitTimeoutError(Exception):
        pass

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calibrations = 0
        self.listen_kwargs = []
        self.recognize_kwargs = []
        fake = self

        class Recognizer:
            def adjust_for_ambient_noise(self, source, duration):
                fake.calibrations += 1

            def listen(self, source, **kwargs):
                fake.listen_kwargs.append(kwargs)
                item = fake.outcomes.pop(0)
                if isinstance(item, fake.WaitTimeoutError):
                    raise item  # listen() itself times out
                return item  # "audio"; recognition errors are raised by recognize_*

            def _recognize(self, audio, **kwargs):
                fake.recognize_kwargs.append(kwargs)
                if isinstance(audio, BaseException):
                    raise audio
                return audio

            recognize_google = _recognize
            recognize_sphinx = _recognize

        self.Recognizer = Recognizer


class FakeMic:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_backend(outcomes, **kw):
    sr = FakeSR(outcomes)
    return sr, SpeechRecognitionBackend(sr_module=sr, microphone=FakeMic(), quiet_alsa=False, **kw)


# --------------------------------------------------------------------------- text backends
def test_text_recognizer_skips_blank_and_comment_lines():
    rec = TextRecognizer(io.StringIO("\n# comment\n  lights on  \nstatus\n"))
    assert rec.listen() == "lights on"
    assert rec.listen() == "status"
    with pytest.raises(EndOfInput):
        rec.listen()


def test_text_recognizer_prompts_when_given_a_prompt_stream():
    out = io.StringIO()
    TextRecognizer(io.StringIO("x\n"), prompt="? ", prompt_stream=out).listen()
    assert out.getvalue() == "? "


def test_scripted_recognizer_raises_exceptions_in_sequence():
    rec = ScriptedRecognizer(["a", UnrecognizedSpeech("mumble")])
    assert rec.listen() == "a"
    with pytest.raises(UnrecognizedSpeech):
        rec.listen()
    with pytest.raises(EndOfInput):
        rec.listen()


def test_make_recognizer():
    assert isinstance(make_recognizer("text", stream=io.StringIO()), TextRecognizer)
    with pytest.raises(BackendError):
        make_recognizer("telepathy")


# --------------------------------------------------------------------------- mic backend
def test_mic_backend_transcribes_and_calibrates_once():
    sr, backend = make_backend(["turn on the light", "status"], language="pl-PL", timeout=3)
    assert backend.listen() == "turn on the light"
    assert backend.listen() == "status"
    assert sr.calibrations == 1
    assert sr.listen_kwargs[0] == {"timeout": 3, "phrase_time_limit": None}
    assert sr.recognize_kwargs[0] == {"language": "pl-PL"}


def test_mic_backend_maps_errors():
    sr = FakeSR([])
    sr.outcomes = [
        sr.UnknownValueError(),
        sr.WaitTimeoutError(),
        "   ",
        sr.RequestError("offline"),
    ]
    backend = SpeechRecognitionBackend(sr_module=sr, microphone=FakeMic(), quiet_alsa=False)
    with pytest.raises(UnrecognizedSpeech, match="could not understand"):
        backend.listen()
    with pytest.raises(UnrecognizedSpeech, match="timeout"):
        backend.listen()
    with pytest.raises(UnrecognizedSpeech, match="empty"):
        backend.listen()
    with pytest.raises(BackendError, match="google recognition failed: offline"):
        backend.listen()


def test_mic_backend_rejects_unknown_engine():
    with pytest.raises(BackendError, match="unknown engine"):
        SpeechRecognitionBackend(engine="nope", sr_module=FakeSR([]))


def test_mic_backend_missing_dependency(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "speech_recognition":
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(BackendError, match=r"voice-control\[mic\]"):
        SpeechRecognitionBackend(quiet_alsa=False)


def test_mic_backend_microphone_open_failure():
    sr = FakeSR([])

    def broken_mic(device_index=None):
        raise OSError("no default input device")

    sr.Microphone = broken_mic
    backend = SpeechRecognitionBackend(sr_module=sr, quiet_alsa=False)
    with pytest.raises(BackendError, match="cannot open microphone"):
        backend.listen()


# --------------------------------------------------------------------------- session
def test_session_runs_until_stop_word_and_records_history():
    out = []
    history = History()
    home = HomeControl()
    rec = ScriptedRecognizer(
        [
            "turn on the light",
            UnrecognizedSpeech("mumble"),
            "make coffee",
            "set volume to 999",
            "help",
            "Stop listening.",
            "turn off the light",  # never reached
        ]
    )
    stats = run_session(home, rec, history=history, echo=out.append)
    assert home.light_on is True
    assert (stats.heard, stats.executed, stats.unrecognized, stats.failed) == (5, 1, 2, 1)
    assert [e.command for e in history] == ["turn_on_light"]
    assert "Turning on the light" in out
    assert "Command not recognized: 'make coffee'" in out
    assert any(line.startswith("set_volume:") for line in out)  # help output
    assert out[-1] == "Bye."


def test_session_once_stops_after_first_utterance():
    home = HomeControl()
    seen = []
    run_session(
        home,
        ScriptedRecognizer(["lights on", "lights off"]),
        once=True,
        echo=lambda _: None,
        on_result=seen.append,
    )
    assert home.light_on and len(seen) == 1


def test_session_propagates_backend_errors():
    rec = types.SimpleNamespace(listen=lambda: (_ for _ in ()).throw(BackendError("dead")))
    with pytest.raises(BackendError):
        run_session(HomeControl(), rec, echo=lambda _: None)
