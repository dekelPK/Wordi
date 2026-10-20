#!/usr/bin/env python3
"""Generate SYNTHETIC vectors so the app can run without downloading real embeddings.

Similarities are fake: words that sit near each other in data/secret_words.json (which is
grouped by topic) share a topic component, so "כלב" is close to "חתול" but nothing deeper.
Use scripts/prepare_vectors.py for real gameplay.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wordi.vectors import VectorModel  # noqa: E402
from wordi.words import load_secret_words  # noqa: E402

PREFIXES = ("ה", "ו", "ב", "ל", "מ", "וה", "שה", "כש")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secret-words", type=Path, default=ROOT / "data" / "secret_words.json")
    ap.add_argument("--output", type=Path, default=ROOT / "data" / "vectors" / "he.npz")
    ap.add_argument("--neighbors-output", type=Path, default=ROOT / "data" / "vectors" / "neighbors.npz")
    ap.add_argument("--dim", type=int, default=64)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    base = load_secret_words(args.secret_words)
    group_size = 12
    topics = rng.normal(size=(len(base) // group_size + 1, args.dim))
    words: list[str] = []
    vectors: list[np.ndarray] = []
    for i, word in enumerate(base):
        vec = topics[i // group_size] * 0.9 + rng.normal(size=args.dim)
        words.append(word)
        vectors.append(vec)
        # Prefixed inflections of every other word, close to the base form (like real embeddings).
        if i % 2 == 0:
            for prefix in PREFIXES:
                words.append(prefix + word)
                vectors.append(vec + rng.normal(scale=0.6, size=args.dim))

    matrix = np.vstack(vectors).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.output, words=np.array(words), vectors=matrix.astype(np.float16))
    model = VectorModel.load(args.output)
    model.save_neighbors(args.neighbors_output, base)
    print(f"Wrote {len(words)} SYNTHETIC demo vectors to {args.output}")


if __name__ == "__main__":
    main()
