import numpy as np

from scripts.prepare_vectors import iter_text_vectors, select


def _lines(tokens: list[str], header: bool = True) -> list[str]:
    rows = [f"{t} " + " ".join(["0.5"] * 12) + "\n" for t in tokens]
    return ([f"{len(tokens)} 12\n"] if header else []) + rows


def test_iter_text_vectors_with_and_without_header() -> None:
    for header in (True, False):
        pairs = list(iter_text_vectors(_lines(["כלב", "חתול"], header)))
        assert [w for w, _ in pairs] == ["כלב", "חתול"]
        assert pairs[0][1].shape == (12,) and pairs[0][1].dtype == np.float32


def test_select_filters_and_keeps_late_secret_words() -> None:
    tokens = [",", "the", "ה", "בית", "בית", "שָׁלוֹם", "abc", "ספר", "דלת", "חלון", "ג'ירפה", "שמש"]
    words, vectors = select(iter_text_vectors(_lines(tokens)), vocab_size=3, wanted={"ג'ירפה", "חסר"}, max_lines=100)
    # punctuation, English, single letters and duplicates dropped; niqqud stripped;
    # the secret word past the cutoff is still kept
    assert words == ["בית", "שלום", "ספר", "ג'ירפה"]
    assert len(vectors) == 4
