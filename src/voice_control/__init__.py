"""voice_control: drive an application with spoken (or typed) commands."""

from .backends import (
    BackendError,
    EndOfInput,
    Recognizer,
    ScriptedRecognizer,
    SpeechRecognitionBackend,
    TextRecognizer,
    UnrecognizedSpeech,
)
from .controller import Command, CommandError, Controller, Result, command, register_action
from .history import History, HistoryEntry, HistoryError
from .matching import MatchType, normalize
from .session import run_session

__version__ = "0.2.0"

__all__ = [
    "BackendError",
    "Command",
    "CommandError",
    "Controller",
    "EndOfInput",
    "History",
    "HistoryEntry",
    "HistoryError",
    "MatchType",
    "Recognizer",
    "Result",
    "ScriptedRecognizer",
    "SpeechRecognitionBackend",
    "TextRecognizer",
    "UnrecognizedSpeech",
    "command",
    "normalize",
    "register_action",
    "run_session",
]
