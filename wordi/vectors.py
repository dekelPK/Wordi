"""Word-vector model: lookup, cosine similarity and nearest-neighbour ranks."""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .hebrew import candidate_forms, normalize

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Neighbors:
    """The k nearest words to a secret, nearest first."""

    secret: str
    words: tuple[str, ...]
    similarities: tuple[float, ...]  # already scaled to 0..100
    _rank: dict[str, int]

    @property
    def k(self) -> int:
        return len(self.words)

    def rank(self, word: str) -> int | None:
        """k for the nearest neighbour, 1 for the k-th nearest, None outside the top k."""
        return self._rank.get(word)

    def similarity_at(self, position: int) -> float:
        """Similarity of the n-th nearest word (1-based)."""
        return self.similarities[min(position, self.k) - 1]

    def word_at_rank(self, rank: int) -> str:
        return self.words[self.k - rank]


def _scale(sim: float) -> float:
    return round(float(sim) * 100, 2)


class VectorModel:
    def __init__(self, words: list[str], vectors: np.ndarray, *, cache_size: int = 256) -> None:
        if len(words) != vectors.shape[0]:
            raise ValueError("words and vectors length mismatch")
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.matrix: np.ndarray = matrix / norms
        self.words: list[str] = list(words)
        self.index: dict[str, int] = {w: i for i, w in enumerate(self.words)}
        self.fingerprint = hashlib.sha256("\n".join(self.words).encode()).hexdigest()[:16]
        self._cache: OrderedDict[tuple[str, int], Neighbors] = OrderedDict()
        self._cache_size = cache_size

    @classmethod
    def load(cls, path: Path) -> VectorModel:
        with np.load(path, allow_pickle=False) as data:
            words = [str(w) for w in data["words"]]
            vectors = data["vectors"]
        log.info("Loaded %d word vectors (dim %d) from %s", len(words), vectors.shape[1], path)
        return cls(words, vectors)

    def __contains__(self, word: str) -> bool:
        return word in self.index

    def __len__(self) -> int:
        return len(self.words)

    def resolve(self, raw: str) -> str | None:
        """Map user input to a vocabulary word, stripping Hebrew prefixes if needed."""
        word = normalize(raw)
        for form in candidate_forms(word):
            if form in self.index:
                return form
        return None

    def similarity(self, a: str, b: str) -> float:
        return _scale(self.matrix[self.index[a]] @ self.matrix[self.index[b]])

    def neighbors(self, secret: str, k: int = 1000) -> Neighbors:
        key = (secret, k)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        top, sims = self._top_k(secret, k)
        result = self._make_neighbors(secret, top, sims)
        self._store(key, result)
        return result

    def _top_k(self, secret: str, k: int) -> tuple[np.ndarray, np.ndarray]:
        idx = self.index[secret]
        sims = self.matrix @ self.matrix[idx]
        sims[idx] = -np.inf
        k = min(k, len(self.words) - 1)
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top], kind="stable")]
        return top, sims[top]

    def _make_neighbors(self, secret: str, idx: np.ndarray, sims: np.ndarray) -> Neighbors:
        words = tuple(self.words[i] for i in idx)
        k = len(words)
        return Neighbors(
            secret=secret,
            words=words,
            similarities=tuple(_scale(s) for s in sims),
            _rank={w: k - pos for pos, w in enumerate(words)},
        )

    def _store(self, key: tuple[str, int], value: Neighbors) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    # --- precomputed cache -------------------------------------------------

    def save_neighbors(self, path: Path, secrets: list[str], k: int = 1000) -> None:
        present = [s for s in dict.fromkeys(secrets) if s in self.index]
        k = min(k, len(self.words) - 1)
        idx = np.zeros((len(present), k), dtype=np.int32)
        sims = np.zeros((len(present), k), dtype=np.float32)
        for row, secret in enumerate(present):
            idx[row], sims[row] = self._top_k(secret, k)
        np.savez_compressed(path, secrets=np.array(present), idx=idx, sims=sims, fingerprint=np.array(self.fingerprint))

    def load_neighbors(self, path: Path) -> int:
        """Load a precomputed neighbour file into the cache; returns the number of entries loaded."""
        if not path.exists():
            return 0
        with np.load(path, allow_pickle=False) as data:
            if str(data["fingerprint"]) != self.fingerprint:
                log.warning("Ignoring %s: built for a different vector file", path)
                return 0
            secrets = [str(s) for s in data["secrets"]]
            idx, sims = data["idx"], data["sims"]
        k = idx.shape[1]
        self._cache_size = max(self._cache_size, len(secrets) + 64)
        for row, secret in enumerate(secrets):
            self._store((secret, k), self._make_neighbors(secret, idx[row], sims[row]))
        return len(secrets)
