"""Command registration and dispatch.

A *controller* is a class whose methods are decorated with :func:`command`. Each
subclass gets its own command table (collected in ``__init_subclass__``), so two
controllers never see each other's commands. Dispatch is pure: it takes text and
returns a :class:`Result`; it never touches a microphone.

Example::

    class Lights(Controller):
        @command("turn on the light", MatchType.SUBSTRING)
        def on(self):
            return "Turning on the light"

        @command(r"dim to (?P<level>\\d+) percent", MatchType.DYNAMIC)
        def dim(self, level: int):
            return f"Dimming to {level}%"
"""

from __future__ import annotations

import datetime as _dt
import inspect
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Mapping, Pattern

from .matching import MatchType, compile_pattern, match, normalize

_ATTR = "__voice_commands__"


class CommandError(Exception):
    """Raised by a handler for a user-facing failure (bad argument, invalid state).

    The message is reported back to the user instead of crashing the session.
    """


@dataclass(frozen=True)
class Command:
    """One registered command: a pattern plus the handler it triggers."""

    name: str
    pattern: str
    match_type: MatchType
    func: Callable[..., Any]
    help: str = ""
    converters: Mapping[str, Callable[[str], Any]] = field(default_factory=dict)
    compiled: Pattern[str] | None = field(default=None, compare=False, repr=False)

    def match(self, text: str) -> dict[str, str] | None:
        return match(self.pattern, self.match_type, text, self.compiled)


@dataclass
class Result:
    """Outcome of dispatching one sentence."""

    text: str
    command: str | None = None
    args: dict[str, str] = field(default_factory=dict)
    output: Any = None
    error: str | None = None
    timestamp: _dt.datetime = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))

    @property
    def matched(self) -> bool:
        return self.command is not None

    @property
    def ok(self) -> bool:
        return self.matched and self.error is None

    def message(self) -> str:
        """Human readable one-liner for the CLI."""
        if not self.matched:
            return f"Command not recognized: {self.text!r}"
        if self.error is not None:
            return f"Error: {self.error}"
        return "" if self.output is None else str(self.output)


def command(
    pattern: str,
    match_type: MatchType = MatchType.STATIC,
    *,
    help: str | None = None,
    converters: Mapping[str, Callable[[str], Any]] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a controller method as the handler for ``pattern``.

    Captured regex groups (``DYNAMIC`` / ``SUBSTRING``) are passed as keyword
    arguments. They are converted with ``converters[name]`` if given, otherwise by
    the parameter's ``int``/``float`` annotation, otherwise left as ``str``.
    A method may be decorated several times to accept alternative phrasings.
    """
    compiled = compile_pattern(pattern, match_type)  # validate early, at class definition

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        specs = list(getattr(func, _ATTR, ()))
        # Decorators apply bottom-up; insert at the front so the top-most decorator
        # is tried first, matching reading order.
        specs.insert(0, (pattern, match_type, help, dict(converters or {}), compiled))
        setattr(func, _ATTR, specs)
        return func

    return decorator


#: Name used by the original prototype; kept as an alias.
register_action = command


def _converter_for(func: Callable[..., Any], param: str) -> Callable[[str], Any] | None:
    try:
        hints = typing.get_type_hints(func)
    except Exception:  # unresolved forward references etc.
        hints = {}
    hint = hints.get(param)
    if hint in (int, float):
        return hint
    return None


class Controller:
    """Base class for anything that can be driven by voice commands."""

    commands: ClassVar[tuple[Command, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        collected: dict[tuple[str, str], Command] = {}
        # Inherited commands first (in base-class order), then this class's own.
        for base in reversed(cls.__mro__[1:]):
            for cmd in getattr(base, "commands", ()):
                collected[(cmd.name, cmd.pattern)] = cmd
        for name, member in vars(cls).items():
            for pattern, match_type, help_, convs, compiled in getattr(member, _ATTR, ()):
                doc = help_ or (inspect.getdoc(member) or "").split("\n")[0]
                collected[(name, pattern)] = Command(
                    name=name,
                    pattern=pattern,
                    match_type=match_type,
                    func=member,
                    help=doc,
                    converters=convs,
                    compiled=compiled,
                )
        cls.commands = tuple(collected.values())

    # -- lookup ---------------------------------------------------------------
    def find(self, text: str) -> tuple[Command, dict[str, str]] | None:
        """Return the first command (in definition order) matching ``text``."""
        normalized = normalize(text, lower=False)
        for cmd in self.commands:
            args = cmd.match(normalized)
            if args is not None:
                return cmd, args
        return None

    def command_names(self) -> list[str]:
        return list(dict.fromkeys(c.name for c in self.commands))

    @classmethod
    def describe(cls) -> list[str]:
        """One line per handler: name, help text and the phrasings it accepts."""
        lines = []
        by_name: dict[str, list[Command]] = {}
        for cmd in cls.commands:
            by_name.setdefault(cmd.name, []).append(cmd)
        for name, cmds in by_name.items():
            lines.append(f"{name}: {cmds[0].help}".rstrip(": "))
            for cmd in cmds:
                lines.append(f"    [{cmd.match_type.value}] {cmd.pattern}")
        return lines

    # -- execution ------------------------------------------------------------
    def dispatch(self, text: str) -> Result:
        """Match ``text`` against the registered commands and run the handler."""
        found = self.find(text)
        if found is None:
            return Result(text=text)
        cmd, raw_args = found
        return self._run(cmd, raw_args, text)

    def invoke(self, name: str, args: Mapping[str, str] | None = None, text: str = "") -> Result:
        """Run a command by handler name with raw (string) arguments, e.g. for replay."""
        for cmd in self.commands:
            if cmd.name == name:
                return self._run(cmd, dict(args or {}), text or name)
        raise KeyError(f"{type(self).__name__} has no command named {name!r}")

    def _run(self, cmd: Command, raw_args: dict[str, str], text: str) -> Result:
        result = Result(text=text, command=cmd.name, args=dict(raw_args))
        try:
            kwargs = self._convert(cmd, raw_args)
            result.output = cmd.func(self, **kwargs)
        except CommandError as exc:
            result.error = str(exc)
        return result

    @staticmethod
    def _convert(cmd: Command, raw_args: Mapping[str, str]) -> dict[str, Any]:
        params = inspect.signature(cmd.func).parameters
        accepts_any = any(p.kind is p.VAR_KEYWORD for p in params.values())
        kwargs: dict[str, Any] = {}
        for key, value in raw_args.items():
            if key not in params and not accepts_any:
                continue  # extra regex group the handler does not care about
            conv = cmd.converters.get(key) or _converter_for(cmd.func, key)
            if conv is None:
                kwargs[key] = value
                continue
            try:
                kwargs[key] = conv(value)
            except (TypeError, ValueError) as exc:
                raise CommandError(f"could not understand {key} {value!r}") from exc
        return kwargs
