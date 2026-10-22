"""The listen -> dispatch -> report loop, independent of any concrete backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .backends import EndOfInput, Recognizer, UnrecognizedSpeech
from .controller import Controller, Result
from .history import History
from .matching import normalize

DEFAULT_STOP_WORDS = ("exit", "quit", "stop listening", "goodbye")
HELP_WORDS = ("help", "what can i say")


@dataclass
class SessionStats:
    heard: int = 0
    executed: int = 0
    unrecognized: int = 0
    failed: int = 0


def run_session(
    controller: Controller,
    recognizer: Recognizer,
    *,
    history: History | None = None,
    once: bool = False,
    stop_words: tuple[str, ...] = DEFAULT_STOP_WORDS,
    echo: Callable[[str], None] = print,
    on_result: Callable[[Result], None] | None = None,
) -> SessionStats:
    """Keep listening and dispatching until input ends, a stop word is spoken, or
    (with ``once``) after the first utterance. Backend errors propagate."""
    stats = SessionStats()
    stops = {normalize(w) for w in stop_words}
    while True:
        try:
            text = recognizer.listen()
        except EndOfInput:
            break
        except UnrecognizedSpeech as exc:
            stats.unrecognized += 1
            echo(f"(didn't catch that: {exc})")
            if once:
                break
            continue

        stats.heard += 1
        echo(f"You said: {text}")
        if normalize(text) in stops:
            echo("Bye.")
            break

        if normalize(text) in HELP_WORDS:
            for line in controller.describe():
                echo(line)
            if once:
                break
            continue

        result = controller.dispatch(text)
        if result.ok:
            stats.executed += 1
        elif result.matched:
            stats.failed += 1
        else:
            stats.unrecognized += 1
        message = result.message()
        if message:
            echo(message)
        if history is not None:
            history.record(result)
        if on_result is not None:
            on_result(result)
        if once:
            break
    return stats
