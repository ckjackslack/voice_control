import pytest

from voice_control import CommandError, Controller, MatchType, command, register_action


class Lights(Controller):
    def __init__(self):
        self.calls = []

    @command("turn on the light", MatchType.SUBSTRING)
    @command("lights on")
    def on(self):
        """Switch it on."""
        self.calls.append("on")
        return "on"

    @command(r"dim to (?P<level>\d+)(?: percent)?", MatchType.DYNAMIC)
    def dim(self, level: int):
        if level > 100:
            raise CommandError("too bright")
        return level

    @command(r"say (?P<words>.+)", MatchType.DYNAMIC, help="Echo words")
    def say(self, words):
        return words

    @command(r"ratio (?P<r>[\d.]+) (?P<unused>\w+)", MatchType.DYNAMIC)
    def ratio(self, r: float):
        return r

    @command(r"pair (?P<v>.+)", MatchType.DYNAMIC, converters={"v": lambda s: tuple(s.split())})
    def pair(self, v):
        return v


class Other(Controller):
    @register_action("ping")
    def ping(self):
        return "pong"


def test_commands_are_per_class():
    assert {c.name for c in Lights.commands} == {"on", "dim", "say", "ratio", "pair"}
    assert [c.name for c in Other.commands] == ["ping"]
    assert Other().dispatch("turn on the light").matched is False


def test_subclass_inherits_and_extends():
    class MoreLights(Lights):
        @command("blink")
        def blink(self):
            return "blink"

    names = MoreLights().command_names()
    assert names[0] == "on" and names[-1] == "blink"
    assert MoreLights().dispatch("blink").output == "blink"
    assert "blink" not in Lights().command_names()


def test_static_dispatch_and_alternative_phrasing():
    c = Lights()
    assert c.dispatch("Lights on!").output == "on"
    assert c.dispatch("could you turn on the light please").output == "on"
    assert c.calls == ["on", "on"]


def test_dynamic_args_converted_by_annotation():
    r = Lights().dispatch("dim to 40 percent")
    assert r.ok and r.output == 40 and isinstance(r.output, int)
    assert r.args == {"level": "40"}  # raw strings are kept for history


def test_float_conversion_and_extra_groups_ignored():
    assert Lights().dispatch("ratio 1.5 foo").output == 1.5


def test_bad_conversion_becomes_error_not_exception():
    r = Lights().dispatch("ratio 1.2.3 foo")
    assert r.matched and not r.ok
    assert "could not understand r" in r.error


def test_custom_converter():
    assert Lights().dispatch("pair a b").output == ("a", "b")


def test_unannotated_args_stay_strings():
    assert Lights().dispatch("say Hello World").output == "Hello World"


def test_command_error_is_reported():
    r = Lights().dispatch("dim to 500")
    assert r.command == "dim" and r.error == "too bright"
    assert r.message() == "Error: too bright"


def test_unrecognized():
    r = Lights().dispatch("make coffee")
    assert not r.matched and not r.ok
    assert "not recognized" in r.message()


def test_unexpected_exceptions_propagate():
    class Buggy(Controller):
        @command("boom")
        def boom(self):
            raise ZeroDivisionError

    with pytest.raises(ZeroDivisionError):
        Buggy().dispatch("boom")


def test_first_defined_command_wins():
    class Ordered(Controller):
        @command("play music", MatchType.STARTS_WITH)
        def music(self):
            return "music"

        @command(r"play (?P<x>.+)", MatchType.DYNAMIC)
        def anything(self, x):
            return x

    assert Ordered().dispatch("play music loud").output == "music"
    assert Ordered().dispatch("play jazz").output == "jazz"


def test_invoke_by_name():
    c = Lights()
    assert c.invoke("dim", {"level": "7"}).output == 7
    with pytest.raises(KeyError):
        c.invoke("nope")


def test_invalid_pattern_fails_at_definition_time():
    with pytest.raises(ValueError):

        class Bad(Controller):
            @command("(oops", MatchType.DYNAMIC)
            def x(self):
                pass


def test_describe_lists_help_and_patterns():
    lines = Lights.describe()
    assert lines[0] == "on: Switch it on."
    assert "    [substring] turn on the light" in lines
    assert "    [static] lights on" in lines
    assert "say: Echo words" in lines
