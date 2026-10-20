"""A deliberately small profanity filter for display names (Hebrew + English)."""

from __future__ import annotations

import re

# Matched anywhere in the name (spaces removed, leetspeak folded).
_SUBSTRINGS = (
    "fuck",
    "fuk",
    "shit",
    "bitch",
    "cunt",
    "dick",
    "pussy",
    "nigger",
    "nigga",
    "faggot",
    "whore",
    "slut",
    "asshole",
    "bastard",
    "cock",
    "penis",
    "porn",
    "nazi",
    "hitler",
    "זונה",
    "שרמוט",
    "מזדיינ",
    "לזיינ",
    "זיונ",
    "מניאק",
    "קוקסינל",
    "היטלר",
    "נאצי",
    "כושי",
    "בנזונה",
    "כוסאמ",
    "כוסעמ",
    "מפגר",
    "מטומטמ",
)
# Matched as whole words only, because they are also innocent words or common substrings.
_WORDS = ("כוס", "זינ", "חרא", "תחת", "הומו", "אנס", "ass", "sex", "cum", "tits", "rape", "fag")

_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_LEET = str.maketrans("013457@$!", "oieastasi")


def _fold(text: str) -> str:
    return text.lower().translate(_FINALS).translate(_LEET)


def is_profane(name: str) -> bool:
    folded = _fold(name)
    compact = re.sub(r"[\s_.\-]+", "", folded)
    if any(bad in compact for bad in _SUBSTRINGS):
        return True
    words = set(folded.split())
    return any(bad in words for bad in _WORDS)
