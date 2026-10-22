import pytest

from voice_control.apps import (
    APPS,
    AppLoadError,
    Circle,
    HomeControl,
    PaintControl,
    Point,
    Rectangle,
    load_app,
    parse_point,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("5 5", Point(5, 5)),
        ("10, 20", Point(10, 20)),
        ("(3, 4)", Point(3, 4)),
        ("x 1 y 2", Point(1, 2)),
        ("7 and 8", Point(7, 8)),
        ("-1 2", Point(-1, 2)),
        ("the origin", Point(0, 0)),
    ],
)
def test_parse_point(text, expected):
    assert parse_point(text) == expected


@pytest.mark.parametrize("text", ["nowhere", "5", "1 2 3"])
def test_parse_point_rejects(text):
    with pytest.raises(ValueError):
        parse_point(text)


class TestPaint:
    def test_original_prototype_sentence(self):
        p = PaintControl()
        r = p.dispatch("make rectangle of width 10 and height 20 with top left corner at 5, 5")
        assert r.ok
        assert p.shapes == [Rectangle(10, 20, Point(5, 5))]

    def test_variants_and_circle(self):
        p = PaintControl()
        assert p.dispatch("Draw a rectangle width 3 height 4 at 0 0.").ok
        assert p.dispatch("draw circle with radius 2 centered at 1, 1").ok
        assert p.shapes == [Rectangle(3, 4, Point(0, 0)), Circle(2, Point(1, 1))]
        listing = p.dispatch("list shapes").output
        assert listing.splitlines() == ["1. rectangle 3x4 at (0, 0)", "2. circle r=2 at (1, 1)"]

    def test_undo_and_clear(self):
        p = PaintControl()
        assert p.dispatch("undo").error == "nothing to undo"
        p.dispatch("draw circle of radius 1 at 0 0")
        p.dispatch("draw circle of radius 2 at 0 0")
        assert p.dispatch("undo").output == "Removed circle r=2 at (0, 0)"
        assert p.dispatch("clear the canvas").output == "Cleared 1 shape(s)"
        assert p.dispatch("show canvas").output == "Canvas is empty"

    @pytest.mark.parametrize(
        "text, error",
        [
            ("make rectangle of width 0 and height 2 at 1 1", "width must be positive, got 0"),
            ("draw circle of radius 0 at 1 1", "radius must be positive, got 0"),
            ("make rectangle of width 1 and height 2 at somewhere", "could not understand position"),
        ],
    )
    def test_invalid_shapes_are_errors(self, text, error):
        p = PaintControl()
        r = p.dispatch(text)
        assert r.matched and error in r.error
        assert p.shapes == []


class TestHome:
    def test_lights(self):
        h = HomeControl()
        assert h.dispatch("Please turn on the light").ok and h.light_on
        assert h.dispatch("switch off the lights").ok and not h.light_on
        assert h.dispatch("lights on").ok and h.light_on

    def test_music(self):
        h = HomeControl()
        assert h.dispatch("stop the music").error == "nothing is playing"
        assert h.dispatch("play music now").output == "Playing music"
        assert h.dispatch("Play Bohemian Rhapsody").output == "Playing Bohemian Rhapsody"
        assert h.playing == "Bohemian Rhapsody"
        assert h.dispatch("pause").ok and h.playing is None

    def test_volume(self):
        h = HomeControl()
        assert h.dispatch("set the volume to 30 percent").ok and h.volume == 30
        assert "between 0 and 100" in h.dispatch("set volume to 101").error
        assert h.volume == 30

    def test_status(self):
        h = HomeControl()
        assert h.dispatch("status").output == "Light is off; playing nothing; volume 50"


def test_load_app_builtin_and_dotted():
    assert load_app("paint") is PaintControl
    assert load_app("voice_control.apps:HomeControl") is HomeControl
    assert set(APPS) == {"home", "paint"}


@pytest.mark.parametrize("spec", ["nope", "no_such_module_xyz:Foo", "voice_control.apps:Point", "os:path"])
def test_load_app_errors(spec):
    with pytest.raises(AppLoadError):
        load_app(spec)
