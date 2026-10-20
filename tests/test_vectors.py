import numpy as np
import pytest

from wordi.vectors import VectorModel

from .conftest import make_model


def test_similarity_is_scaled_cosine(model: VectorModel) -> None:
    a, b = model.matrix[model.index["כלב"]], model.matrix[model.index["גור"]]
    assert model.similarity("כלב", "גור") == pytest.approx(float(a @ b) * 100, abs=0.01)
    assert model.similarity("כלב", "גור") == model.similarity("גור", "כלב")
    assert model.similarity("כלב", "כלב") == pytest.approx(100, abs=0.01)


def test_vectors_are_normalised() -> None:
    m = VectorModel(["אא", "בב"], np.array([[3.0, 4.0], [0.0, 2.0]]))
    assert np.allclose(np.linalg.norm(m.matrix, axis=1), 1)
    assert m.similarity("אא", "בב") == 80.0


def test_neighbor_ranks(model: VectorModel) -> None:
    nb = model.neighbors("כלב", 1000)
    assert nb.k == 1000
    assert "כלב" not in nb.words
    # nearest first, ranks count down from k
    assert nb.words[:3] == ("גור", "הגור", "ביתי")
    assert nb.rank("גור") == 1000
    assert nb.rank("הגור") == 999
    assert nb.rank(nb.words[-1]) == 1
    assert nb.word_at_rank(999) == "הגור"
    assert list(nb.similarities) == sorted(nb.similarities, reverse=True)
    assert nb.similarity_at(1) == nb.similarities[0]
    assert nb.similarity_at(1000) == nb.similarities[999]
    # a word outside the top k has no rank
    outside = next(w for w in model.words if w != "כלב" and w not in nb.words)
    assert nb.rank(outside) is None
    assert model.similarity(outside, "כלב") <= nb.similarity_at(1000)


def test_neighbors_are_cached(model: VectorModel) -> None:
    assert model.neighbors("חתול") is model.neighbors("חתול")


def test_resolve_prefers_exact_then_strips_prefixes(model: VectorModel) -> None:
    assert model.resolve("הגור") == "הגור"  # exact form exists
    assert model.resolve("לגור") == "גור"
    assert model.resolve("וּבַכֶּלֶב") == "כלב"
    assert model.resolve("כלבלב") is None


def test_precomputed_neighbors_roundtrip(tmp_path) -> None:
    path = tmp_path / "nb.npz"
    m1 = make_model()
    m1.save_neighbors(path, ["כלב", "חתול", "לא-קיים"])
    m2 = make_model()
    assert m2.load_neighbors(path) == 2
    assert m2.neighbors("כלב").words == m1.neighbors("כלב").words
    # a cache built for another vocabulary is ignored
    other = make_model(n_filler=1200)
    assert other.load_neighbors(path) == 0
