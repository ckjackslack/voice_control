"""Command line interface: ``voice-control {run,do,list,replay}``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Sequence, TextIO

from . import __version__
from .apps import APPS, AppLoadError, load_app
from .backends import ENGINES, BackendError, Recognizer, SpeechRecognitionBackend, TextRecognizer
from .controller import Controller
from .history import History, HistoryError
from .session import run_session

ENV_PREFIX = "VOICE_CONTROL_"

#: Factory used to build the recognizer; tests replace it with a fake.
RecognizerFactory = Callable[[argparse.Namespace, TextIO, TextIO], Recognizer]


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(ENV_PREFIX + name, default)


def _float_or_none(value: str) -> float | None:
    if value.lower() in ("", "none"):
        return None
    try:
        result = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if result <= 0:
        raise argparse.ArgumentTypeError(f"must be positive: {value!r}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-control",
        description="Control an application with spoken (or typed) commands.",
        epilog=(
            "Environment defaults: VOICE_CONTROL_APP, VOICE_CONTROL_BACKEND, "
            "VOICE_CONTROL_ENGINE, VOICE_CONTROL_LANGUAGE, VOICE_CONTROL_HISTORY."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    app_opts = argparse.ArgumentParser(add_help=False)
    app_opts.add_argument(
        "-a",
        "--app",
        default=_env("APP", "home"),
        help=(
            f"controller to drive: {', '.join(sorted(APPS))} or 'module:ClassName' "
            "(default: %(default)s)"
        ),
    )
    hist_opts = argparse.ArgumentParser(add_help=False)
    hist_opts.add_argument(
        "--history",
        metavar="FILE",
        type=Path,
        default=_env("HISTORY"),
        help="append executed commands to this JSON file (created if missing)",
    )

    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND", required=True)

    run = sub.add_parser(
        "run",
        parents=[app_opts, hist_opts],
        help="listen for commands and execute them",
        description=(
            "Listen for commands (microphone or stdin) and execute them until input ends "
            "or you say 'exit' / 'stop listening'. Say 'help' to list commands."
        ),
    )
    run.add_argument(
        "-b",
        "--backend",
        choices=("text", "mic"),
        default=_env("BACKEND", "text"),
        help="input source: 'text' reads lines from stdin, 'mic' uses the microphone "
        "(default: %(default)s)",
    )
    run.add_argument(
        "--engine",
        choices=ENGINES,
        default=_env("ENGINE", "google"),
        help="speech engine for the mic backend (default: %(default)s)",
    )
    run.add_argument(
        "--language", default=_env("LANGUAGE", "en-US"), help="recognition language (default: %(default)s)"
    )
    run.add_argument("--device-index", type=int, default=None, help="microphone device index")
    run.add_argument(
        "--timeout", type=_float_or_none, default=None, help="seconds to wait for speech to start"
    )
    run.add_argument(
        "--phrase-time-limit", type=_float_or_none, default=None, help="max seconds per phrase"
    )
    run.add_argument("--once", action="store_true", help="handle a single utterance and exit")

    do = sub.add_parser(
        "do",
        parents=[app_opts, hist_opts],
        help="execute commands given as arguments (as if spoken)",
        description="Execute each TEXT argument as one spoken sentence, in order, on one controller.",
    )
    do.add_argument("texts", nargs="+", metavar="TEXT", help="sentence to execute")

    lst = sub.add_parser("list", parents=[app_opts], help="list the commands an app understands")
    lst.add_argument("--apps", action="store_true", help="list the built-in apps instead")

    replay = sub.add_parser(
        "replay", parents=[app_opts], help="re-run commands from a history file"
    )
    replay.add_argument("file", type=Path, help="history JSON file written with --history")
    return parser


def default_recognizer(args: argparse.Namespace, stdin: TextIO, stdout: TextIO) -> Recognizer:
    if args.backend == "text":
        prompt_stream = stdout if stdin.isatty() else None
        return TextRecognizer(stdin, prompt="> ", prompt_stream=prompt_stream)
    return SpeechRecognitionBackend(
        engine=args.engine,
        language=args.language,
        device_index=args.device_index,
        timeout=args.timeout,
        phrase_time_limit=args.phrase_time_limit,
    )


def _load_history(path: Path | None) -> History | None:
    if path is None:
        return None
    if path.exists():
        return History.load(path)
    return History()


def _save_history(history: History | None, path: Path | None) -> None:
    if history is not None and path is not None:
        history.save(path)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    recognizer_factory: RecognizerFactory | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_parser().parse_args(argv)

    def echo(line: str) -> None:
        print(line, file=stdout, flush=True)

    def fail(msg: str, code: int = 2) -> int:
        print(f"voice-control: error: {msg}", file=stderr)
        return code

    if args.cmd == "list" and args.apps:
        for name, cls in sorted(APPS.items()):
            echo(f"{name}: {(cls.__doc__ or '').strip()}")
        return 0

    try:
        app_cls = load_app(args.app)
    except AppLoadError as exc:
        return fail(str(exc))

    if args.cmd == "list":
        for line in app_cls.describe():
            echo(line)
        return 0

    controller: Controller = app_cls()

    if args.cmd == "replay":
        try:
            results = History.load(args.file).replay(controller)
        except HistoryError as exc:
            return fail(str(exc))
        for result in results:
            echo(f"> {result.text}")
            msg = result.message()
            if msg:
                echo(msg)
        return 0 if all(r.ok for r in results) else 1

    try:
        history = _load_history(args.history)
    except HistoryError as exc:
        return fail(str(exc))

    if args.cmd == "do":
        status = 0
        for text in args.texts:
            result = controller.dispatch(text)
            msg = result.message()
            if msg:
                echo(msg)
            if history is not None:
                history.record(result)
            if not result.ok:
                status = 1
    else:  # run
        factory = recognizer_factory or default_recognizer
        try:
            recognizer = factory(args, stdin, stdout)
            if args.backend == "mic":
                echo("Listening... say 'help' for commands, 'stop listening' to quit.")
            run_session(controller, recognizer, history=history, once=args.once, echo=echo)
            status = 0
        except BackendError as exc:
            fail(str(exc), 1)
            status = 1
        except KeyboardInterrupt:
            echo("Interrupted.")
            status = 130

    try:
        _save_history(history, args.history)
    except HistoryError as exc:
        return fail(str(exc), 1)
    return status


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
