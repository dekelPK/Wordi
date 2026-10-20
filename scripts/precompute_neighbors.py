#!/usr/bin/env python3
"""Precompute the top-1000 neighbours of every curated secret word.

Run again whenever the vector file or data/secret_words.json changes. The server also
computes neighbours on demand, so this is an optimisation, not a requirement.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wordi.vectors import VectorModel  # noqa: E402
from wordi.words import load_secret_words  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vectors", type=Path, default=ROOT / "data" / "vectors" / "he.npz")
    ap.add_argument("--secret-words", type=Path, default=ROOT / "data" / "secret_words.json")
    ap.add_argument("--output", type=Path, default=ROOT / "data" / "vectors" / "neighbors.npz")
    ap.add_argument("-k", type=int, default=1000)
    args = ap.parse_args()

    model = VectorModel.load(args.vectors)
    secrets = load_secret_words(args.secret_words)
    start = time.time()
    model.save_neighbors(args.output, secrets, args.k)
    found = sum(s in model for s in secrets)
    print(f"{found}/{len(secrets)} secret words → {args.output} in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
