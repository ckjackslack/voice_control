"""Speech (or text) input backends.

Every backend implements :class:`Recognizer`: ``listen()`` blocks until one
utterance is available and returns its text. Backends signal:

* :class:`EndOfInput` – no more input (EOF on stdin); the session ends normally.
* :class:`UnrecognizedSpeech` – something was heard but not understood; the session
  carries on.
* :class:`BackendError` – the backend cannot work (no microphone, missing package,
  recognition service unreachable); the session stops with an error.

The microphone backend imports ``speech_recognition`` lazily, so the package and its
tests work on machines without PyAudio or a microphone.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import IO, Any, Callable, Iterable, Iterator, Protocol, runtime_checkable


class EndOfInput(Exception):
    """The input source is exhausted."""


class UnrecognizedSpeech(Exception):
    """Audio was captured but could not be turned into text."""


class BackendError(RuntimeError):
    """The backend is unusable (missing dependency, no device, service error)."""


@runtime_checkable
class Recognizer(Protocol):
    def listen(self) -> str:  # pragma: no cover - protocol
        ...


class TextRecognizer:
    """Reads one command per line from a text stream (stdin by default).

    Handy for trying out a controller without a microphone and for scripting:
    ``printf 'turn on the light\\n' | voice-control run --backend text``.
    """

    def __init__(
        self,
        stream: IO[str] | None = None,
        prompt: str = "> ",
        prompt_stream: IO[str] | None = None,
    ) -> None:
        self.stream = stream if stream is not None else sys.stdin
        self.prompt = prompt
        self.prompt_stream = prompt_stream

    def listen(self) -> str:
        while True:
            if self.prompt and self.prompt_stream is not None:
                self.prompt_stream.write(self.prompt)
                self.prompt_stream.flush()
            line = self.stream.readline()
            if not line:
                raise EndOfInput
            line = line.strip()
            if line and not line.startswith("#"):
                return line


class ScriptedRecognizer:
    """Returns pre-defined utterances in order; useful in tests and demos.

    An item that is an exception instance is raised instead of returned, which lets
    tests simulate recognition failures.
    """

    def __init__(self, utterances: Iterable[str | BaseException]) -> None:
        self._it: Iterator[str | BaseException] = iter(utterances)

    def listen(self) -> str:
        try:
            item = next(self._it)
        except StopIteration:
            raise EndOfInput from None
        if isinstance(item, BaseException):
            raise item
        return item


ENGINES = ("google", "sphinx")


class SpeechRecognitionBackend:
    """Microphone input transcribed with the ``SpeechRecognition`` package.

    ``engine="google"`` uses the free Google Web Speech API (needs internet);
    ``engine="sphinx"`` uses offline CMU Sphinx (needs ``pocketsphinx``).
    ``sr_module`` and ``microphone`` can be injected for testing.
    """

    def __init__(
        self,
        engine: str = "google",
        language: str = "en-US",
        device_index: int | None = None,
        timeout: float | None = None,
        phrase_time_limit: float | None = None,
        calibrate_seconds: float = 0.5,
        sr_module: Any = None,
        microphone: Any = None,
        quiet_alsa: bool = True,
    ) -> None:
        if engine not in ENGINES:
            raise BackendError(f"unknown engine {engine!r}; choose from {', '.join(ENGINES)}")
        self.engine = engine
        self.language = language
        self.timeout = timeout
        self.phrase_time_limit = phrase_time_limit
        self.calibrate_seconds = calibrate_seconds
        if sr_module is None:
            try:
                import speech_recognition as sr_module  # type: ignore[no-redef]
            except ImportError as exc:
                raise BackendError(
                    "the microphone backend needs SpeechRecognition and PyAudio: "
                    "pip install 'voice-control[mic]'"
                ) from exc
        self.sr = sr_module
        self.recognizer = sr_module.Recognizer()
        self._microphone = microphone
        self._device_index = device_index
        self._calibrated = False
        if quiet_alsa:
            silence_alsa_errors()

    @property
    def microphone(self) -> Any:
        if self._microphone is None:
            try:
                self._microphone = self.sr.Microphone(device_index=self._device_index)
            except (AttributeError, OSError) as exc:
                raise BackendError(f"cannot open microphone: {exc}") from exc
        return self._microphone

    def listen(self) -> str:
        sr = self.sr
        with self.microphone as source:
            if not self._calibrated and self.calibrate_seconds > 0:
                self.recognizer.adjust_for_ambient_noise(source, duration=self.calibrate_seconds)
                self._calibrated = True
            try:
                audio = self.recognizer.listen(
                    source, timeout=self.timeout, phrase_time_limit=self.phrase_time_limit
                )
            except sr.WaitTimeoutError as exc:
                raise UnrecognizedSpeech("no speech detected before timeout") from exc
        return self.transcribe(audio)

    def transcribe(self, audio: Any) -> str:
        sr = self.sr
        recognize: Callable[..., str] = getattr(self.recognizer, f"recognize_{self.engine}")
        try:
            text = recognize(audio, language=self.language)
        except sr.UnknownValueError as exc:
            raise UnrecognizedSpeech("could not understand audio") from exc
        except sr.RequestError as exc:
            raise BackendError(f"{self.engine} recognition failed: {exc}") from exc
        if not isinstance(text, str) or not text.strip():
            raise UnrecognizedSpeech("empty transcription")
        return text


_alsa_handler: Any = None


def silence_alsa_errors() -> bool:
    """Install a no-op ALSA error handler so PortAudio's device probing does not spam
    stderr with "ALSA lib ..." lines (what the prototype tried to achieve with a stray
    ``import sounddevice``). Returns ``True`` if the handler was installed.
    Safe no-op where libasound is not available.
    """
    global _alsa_handler
    if _alsa_handler is not None:
        return True
    name = ctypes.util.find_library("asound")
    if not name:
        return False
    try:
        lib = ctypes.cdll.LoadLibrary(name)
        handler_type = ctypes.CFUNCTYPE(
            None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p
        )
        handler = handler_type(lambda *_: None)
        lib.snd_lib_error_set_handler(handler)
    except (OSError, AttributeError):
        return False
    _alsa_handler = handler  # keep a reference so it is not garbage collected
    return True


BACKENDS = ("text", "mic")


def make_recognizer(name: str, **options: Any) -> Recognizer:
    """Build a backend by name: ``text`` (stdin) or ``mic`` (SpeechRecognition)."""
    if name == "text":
        return TextRecognizer(**options)
    if name == "mic":
        return SpeechRecognitionBackend(**options)
    raise BackendError(f"unknown backend {name!r}; choose from {', '.join(BACKENDS)}")
