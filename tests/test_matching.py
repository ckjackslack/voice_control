import pytest

from voice_control.matching import MatchType, compile_pattern, match, normalize


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Turn on the light.", "turn on the light"),
        ("  play   music!! ", "play music"),
        ("What is the status?", "what is the status"),
        ("move to 5, 5", "move to 5, 5"),
        ("", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_normalize_can_keep_case():
    assert normalize("  Play  Queen. ", lower=False) == "Play Queen"


def test_static_requires_whole_sentence():
    assert match("clear canvas", MatchType.STATIC, "clear canvas") == {}
    assert match("clear canvas", MatchType.STATIC, "please clear canvas") is None
    assert match("Clear Canvas", MatchType.STATIC, "CLEAR CANVAS") == {}


def test_substring_is_regex_search_with_groups():
    assert match("turn on the light", MatchType.SUBSTRING, "please turn on the light now") == {}
    assert match(r"dim to (?P<n>\d+)", MatchType.SUBSTRING, "please dim to 30 ok") == {"n": "30"}
    assert match("turn on the light", MatchType.SUBSTRING, "turn off the light") is None


def test_starts_with_respects_word_boundary():
    assert match("play music", MatchType.STARTS_WITH, "play music") == {}
    assert match("play music", MatchType.STARTS_WITH, "play music by queen") == {}
    assert match("play", MatchType.STARTS_WITH, "playground") is None
    assert match("play music", MatchType.STARTS_WITH, "now play music") is None


def test_all_keywords_any_order_whole_words():
    assert match("stop music", MatchType.ALL_KEYWORDS, "music please stop") == {}
    assert match("stop music", MatchType.ALL_KEYWORDS, "stop") is None
    # "on" must not be found inside "turn" / "song" (the prototype's bug)
    assert match("on", MatchType.ALL_KEYWORDS, "song turn") is None


def test_dynamic_fullmatch_named_groups_keep_case():
    pattern = r"play (?P<track>.+)"
    assert match(pattern, MatchType.DYNAMIC, "Play Bohemian Rhapsody") == {"track": "Bohemian Rhapsody"}
    assert match(r"set (?P<x>\d+)", MatchType.DYNAMIC, "set 5 please") is None


def test_dynamic_drops_unmatched_optional_groups():
    pattern = r"go (?P<dir>left|right)(?: by (?P<n>\d+))?"
    assert match(pattern, MatchType.DYNAMIC, "go left") == {"dir": "left"}
    assert match(pattern, MatchType.DYNAMIC, "go left by 3") == {"dir": "left", "n": "3"}


def test_compile_pattern_validation():
    assert compile_pattern("hello", MatchType.STATIC) is None
    assert compile_pattern("hel+o", MatchType.DYNAMIC) is not None
    with pytest.raises(ValueError, match="invalid regex"):
        compile_pattern("(unclosed", MatchType.DYNAMIC)
    with pytest.raises(ValueError, match="empty"):
        compile_pattern("  ", MatchType.STATIC)
