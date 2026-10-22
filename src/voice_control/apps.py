"""Built-in example controllers and loading of user-defined ones.

* ``home``  – the prototype's ``TestControl``: lights and music, with state.
* ``paint`` – the prototype's ``PaintAppControl``: build a list of shapes by voice.

Your own controller can be loaded with ``--app package.module:ClassName``.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass

from .controller import CommandError, Controller, command
from .matching import MatchType


class HomeControl(Controller):
    """Toy smart-home: a light, a music player and its volume."""

    def __init__(self) -> None:
        self.light_on = False
        self.playing: str | None = None
        self.volume = 50

    @command(r"\b(?:turn|switch) on the lights?\b", MatchType.SUBSTRING)
    @command("lights on")
    def turn_on_light(self) -> str:
        """Turn the light on."""
        self.light_on = True
        return "Turning on the light"

    @command(r"\b(?:turn|switch) off the lights?\b", MatchType.SUBSTRING)
    @command("lights off")
    def turn_off_light(self) -> str:
        """Turn the light off."""
        self.light_on = False
        return "Turning off the light"

    @command("play music", MatchType.STARTS_WITH)
    def play_music(self) -> str:
        """Start playing music."""
        self.playing = "music"
        return "Playing music"

    @command(r"play (?P<track>.+)", MatchType.DYNAMIC)
    def play_track(self, track: str) -> str:
        """Play a named track."""
        self.playing = track
        return f"Playing {track}"

    @command("stop music", MatchType.ALL_KEYWORDS)
    @command("pause")
    def stop_music(self) -> str:
        """Stop the music."""
        if self.playing is None:
            raise CommandError("nothing is playing")
        self.playing = None
        return "Music stopped"

    @command(r"set (?:the )?volume to (?P<level>\d+)(?: percent| %)?", MatchType.DYNAMIC)
    def set_volume(self, level: int) -> str:
        """Set the volume (0-100)."""
        if not 0 <= level <= 100:
            raise CommandError(f"volume must be between 0 and 100, got {level}")
        self.volume = level
        return f"Volume set to {level}"

    @command("status")
    def status(self) -> str:
        """Report the current state."""
        light = "on" if self.light_on else "off"
        music = self.playing or "nothing"
        return f"Light is {light}; playing {music}; volume {self.volume}"


@dataclass(frozen=True)
class Point:
    x: int
    y: int

    def __str__(self) -> str:
        return f"({self.x}, {self.y})"


_INT = re.compile(r"-?\d+")


def parse_point(text: str) -> Point:
    """Parse a spoken position such as ``"10 20"``, ``"10, 20"``, ``"x 10 y 20"``,
    ``"10 and 20"`` or ``"the origin"``."""
    cleaned = text.strip().lower()
    if cleaned in ("origin", "the origin", "zero zero"):
        return Point(0, 0)
    numbers = _INT.findall(cleaned)
    if len(numbers) != 2:
        raise ValueError(f"expected two coordinates in {text!r}")
    return Point(int(numbers[0]), int(numbers[1]))


@dataclass(frozen=True)
class Rectangle:
    width: int
    height: int
    top_left: Point

    def __str__(self) -> str:
        return f"rectangle {self.width}x{self.height} at {self.top_left}"


@dataclass(frozen=True)
class Circle:
    radius: int
    center: Point

    def __str__(self) -> str:
        return f"circle r={self.radius} at {self.center}"


def _positive(name: str, value: int) -> None:
    if value <= 0:
        raise CommandError(f"{name} must be positive, got {value}")


class PaintControl(Controller):
    """Build up a drawing (a list of shapes) by voice."""

    def __init__(self) -> None:
        self.shapes: list[Rectangle | Circle] = []

    @command(
        r"(?:make|draw) (?:a )?rectangle (?:of )?width (?P<width>\d+) (?:and )?height "
        r"(?P<height>\d+)(?: with (?:the )?top left corner)? at (?P<position>.+)",
        MatchType.DYNAMIC,
        converters={"position": parse_point},
    )
    def make_rectangle(self, width: int, height: int, position: Point) -> str:
        """Add a rectangle: 'make rectangle of width 10 and height 20 with top left corner at 5 5'."""
        _positive("width", width)
        _positive("height", height)
        shape = Rectangle(width, height, position)
        self.shapes.append(shape)
        return f"Making {shape}"

    @command(
        r"(?:make|draw) (?:a )?circle (?:of |with )?radius (?P<radius>\d+) "
        r"(?:centered |centred )?at (?P<position>.+)",
        MatchType.DYNAMIC,
        converters={"position": parse_point},
    )
    def make_circle(self, radius: int, position: Point) -> str:
        """Add a circle: 'draw circle of radius 5 at 10 10'."""
        _positive("radius", radius)
        shape = Circle(radius, position)
        self.shapes.append(shape)
        return f"Making {shape}"

    @command("list shapes")
    @command("show canvas")
    def list_shapes(self) -> str:
        """List the shapes on the canvas."""
        if not self.shapes:
            return "Canvas is empty"
        return "\n".join(f"{i}. {s}" for i, s in enumerate(self.shapes, 1))

    @command("undo")
    def undo(self) -> str:
        """Remove the last shape."""
        if not self.shapes:
            raise CommandError("nothing to undo")
        return f"Removed {self.shapes.pop()}"

    @command("clear canvas")
    @command("clear the canvas")
    def clear(self) -> str:
        """Remove all shapes."""
        count = len(self.shapes)
        self.shapes.clear()
        return f"Cleared {count} shape(s)"


APPS: dict[str, type[Controller]] = {"home": HomeControl, "paint": PaintControl}


class AppLoadError(ValueError):
    pass


def load_app(spec: str) -> type[Controller]:
    """Resolve ``spec`` to a Controller subclass.

    ``spec`` is either a built-in name (``home``, ``paint``) or ``module:ClassName``.
    """
    if spec in APPS:
        return APPS[spec]
    if ":" not in spec:
        raise AppLoadError(
            f"unknown app {spec!r}; use one of {', '.join(sorted(APPS))} or 'module:ClassName'"
        )
    module_name, _, attr = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise AppLoadError(f"cannot import {module_name!r}: {exc}") from exc
    cls = getattr(module, attr, None)
    if not (isinstance(cls, type) and issubclass(cls, Controller)):
        raise AppLoadError(f"{spec!r} is not a voice_control.Controller subclass")
    return cls
