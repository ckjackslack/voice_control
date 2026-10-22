"""Pure text matching: how a transcribed sentence is compared with a command pattern.

Nothing here does I/O, so it is trivially testable.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Pattern


class MatchType(Enum):
    """How a command pattern is compared with the (normalized) spoken text."""

    #: The whole sentence must equal the pattern, e.g. ``"clear canvas"``.
    STATIC = "static"
    #: The pattern is a regex that must occur somewhere in the sentence.
    SUBSTRING = "substring"
    #: The sentence must start with the pattern (a plain phrase).
    STARTS_WITH = "starts_with"
    #: Every word of the pattern must appear as a word in the sentence, in any order.
    ALL_KEYWORDS = "all_keywords"
    #: The pattern is a regex that must match the *whole* sentence; named groups
    #: become handler arguments.
    DYNAMIC = "dynamic"


_WS = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[\s.!?;:]+$")
_WORD = re.compile(r"[\w']+")


def normalize(text: str, *, lower: bool = True) -> str:
    """Collapse whitespace, drop trailing sentence punctuation and (by default)
    lower-case.

    Recognizers return things like ``"Turn on the light."``; patterns are written in
    lower case without punctuation, so both sides are normalized the same way.
    """
    text = _WS.sub(" ", text.strip())
    if lower:
        text = text.lower()
    return _TRAILING_PUNCT.sub("", text)


def compile_pattern(pattern: str, match_type: MatchType) -> Pattern[str] | None:
    """Pre-compile regex-based patterns; return ``None`` for plain-phrase types.

    Raises ``ValueError`` for an invalid regular expression or an empty pattern.
    """
    if not pattern or not pattern.strip():
        raise ValueError("command pattern must not be empty")
    if match_type in (MatchType.SUBSTRING, MatchType.DYNAMIC):
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"invalid regex pattern {pattern!r}: {exc}") from exc
    return None


def match(
    pattern: str,
    match_type: MatchType,
    text: str,
    compiled: Pattern[str] | None = None,
) -> dict[str, str] | None:
    """Return the captured arguments if ``text`` matches, otherwise ``None``.

    A match without captures returns an empty dict (which is falsy, so callers must
    test ``is not None``). ``text`` should already be normalized (case may be kept:
    regexes are case-insensitive, so captured values keep the speaker's casing).
    """
    if match_type in (MatchType.SUBSTRING, MatchType.DYNAMIC):
        regex = compiled or compile_pattern(pattern, match_type)
        assert regex is not None
        m = regex.search(text) if match_type is MatchType.SUBSTRING else regex.fullmatch(text)
        if m is None:
            return None
        return {k: v for k, v in m.groupdict().items() if v is not None}

    phrase = normalize(pattern)
    text = text.lower()
    if match_type is MatchType.STATIC:
        return {} if text == phrase else None
    if match_type is MatchType.STARTS_WITH:
        # Match on a word boundary: "play music" matches "play music now" but
        # "play" must not match "playground".
        if text == phrase or text.startswith(phrase + " "):
            return {}
        return None
    if match_type is MatchType.ALL_KEYWORDS:
        words = set(_WORD.findall(text))
        return {} if all(w in words for w in _WORD.findall(phrase)) else None
    raise ValueError(f"unsupported match type: {match_type!r}")  # pragma: no cover
