"""Hebrew text helpers: input normalisation and prefix stripping."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

# Single-letter prefixes (ה, ו, ב, ל, מ, כ, ש) that attach to the following word.
PREFIX_LETTERS = "הובלמכש"
MAX_PREFIX_LEN = 3
MIN_STEM_LEN = 2

_COMBINING_MARKS = re.compile(r"[֑-ׇ]")  # cantillation + niqqud
_QUOTE_MAP = str.maketrans({"׳": "'", "’": "'", "‘": "'", "`": "'", "״": '"', "“": '"', "”": '"'})
HEBREW_WORD_RE = re.compile(r"^[א-ת][א-ת'\"]*$")


def normalize(raw: str) -> str:
    """Canonical form of user input: no niqqud, ASCII quote marks, trimmed."""
    text = unicodedata.normalize("NFKD", raw)  # also unfolds presentation forms (U+FB1D..)
    text = _COMBINING_MARKS.sub("", text)
    text = unicodedata.normalize("NFC", text).translate(_QUOTE_MAP)
    text = text.strip().strip("'\".,!?;:-־ ")
    return text


def is_hebrew_word(word: str) -> bool:
    return bool(HEBREW_WORD_RE.match(word))


def candidate_forms(word: str) -> Iterator[str]:
    """The word itself, then the word with up to MAX_PREFIX_LEN prefix letters removed."""
    yield word
    for n in range(1, MAX_PREFIX_LEN + 1):
        if len(word) - n < MIN_STEM_LEN or word[n - 1] not in PREFIX_LETTERS:
            return
        yield word[n:]
