#!/usr/bin/env python3
"""Prepare a compact Hebrew word-vector file for Wordi.

Default source: fastText Common Crawl Hebrew vectors (cc.he.300.vec.gz, 1.2 GB compressed).
That file is sorted by word frequency, so we *stream* it and stop as soon as we have the
--vocab-size most frequent Hebrew words (plus any curated secret words found a little further
down). In practice that reads ~100-200 MB of the download, not the whole file.

Alternatively pass --input with a local file:
  *.vec / *.vec.gz / *.txt   word2vec text format (parsed directly, no gensim needed)
  *.bin                      fastText binary (needs gensim) or word2vec binary (--word2vec-binary)
  *.kv / *.model             gensim KeyedVectors / Word2Vec model (needs gensim)

Output: data/vectors/he.npz  (words + float16 L2-normalised vectors)
        data/vectors/neighbors.npz  (top-1000 neighbours of every secret word)

Examples:
  python scripts/prepare_vectors.py
  python scripts/prepare_vectors.py --vocab-size 30000
  python scripts/prepare_vectors.py --input ~/Downloads/wiki.he.vec
"""

from __future__ import annotations

import argparse
import gzip
import io
import sys
import time
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wordi.hebrew import is_hebrew_word, normalize  # noqa: E402
from wordi.vectors import VectorModel  # noqa: E402
from wordi.words import load_secret_words  # noqa: E402

CC_HE_URL = "https://dl.fbaipublicfiles.com/fasttext/vectors-crawl/cc.he.300.vec.gz"


class _CountingReader(io.RawIOBase):
    """Wraps a stream and counts bytes read (for progress output)."""

    def __init__(self, raw: io.BufferedIOBase) -> None:
        self.raw = raw
        self.count = 0

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray) -> int:  # type: ignore[override]
        data = self.raw.read(len(b))
        n = len(data)
        b[:n] = data
        self.count += n
        return n


def iter_text_vectors(lines: Iterable[str]) -> Iterator[tuple[str, np.ndarray]]:
    it = iter(lines)
    first = next(it).rstrip("\n").split(" ")
    if len(first) != 2:  # no "<count> <dim>" header line
        it = iter([" ".join(first), *it])
    for line in it:
        parts = line.rstrip().split(" ")
        if len(parts) < 10:
            continue
        yield parts[0], np.asarray(parts[1:], dtype=np.float32)


def iter_gensim_vectors(path: Path, word2vec_binary: bool) -> Iterator[tuple[str, np.ndarray]]:
    try:
        from gensim.models import KeyedVectors, Word2Vec
        from gensim.models.fasttext import load_facebook_vectors
    except ImportError:
        sys.exit("This input format needs gensim: pip install gensim")
    if path.suffix == ".bin" and not word2vec_binary:
        kv = load_facebook_vectors(str(path))
    elif path.suffix == ".bin":
        kv = KeyedVectors.load_word2vec_format(str(path), binary=True)
    elif path.suffix == ".model":
        kv = Word2Vec.load(str(path)).wv
    else:
        kv = KeyedVectors.load(str(path))
    for word in kv.index_to_key:  # frequency order
        yield word, kv[word]


def select(
    pairs: Iterable[tuple[str, np.ndarray]], vocab_size: int, wanted: set[str], max_lines: int
) -> tuple[list[str], list[np.ndarray]]:
    words: list[str] = []
    vectors: list[np.ndarray] = []
    seen: set[str] = set()
    missing = set(wanted)
    start = time.time()
    for n, (raw, vec) in enumerate(pairs, 1):
        word = normalize(raw)
        if n % 20000 == 0:
            print(f"  read {n:,} lines, kept {len(words):,} words ({time.time() - start:.0f}s)", file=sys.stderr)
        if n > max_lines:
            break
        if len(word) < 2 or word in seen or not is_hebrew_word(word):
            continue
        if len(words) >= vocab_size and word not in missing:
            if not missing:
                break
            continue
        seen.add(word)
        missing.discard(word)
        words.append(word)
        vectors.append(vec)
    if missing:
        print(f"  {len(missing)} secret words not found: {sorted(missing)[:30]}", file=sys.stderr)
    return words, vectors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, help="local vector file (default: stream cc.he.300.vec.gz)")
    ap.add_argument("--url", default=CC_HE_URL, help="URL of a word2vec-text .vec.gz to stream")
    ap.add_argument("--word2vec-binary", action="store_true", help="treat a .bin input as word2vec, not fastText")
    ap.add_argument("--vocab-size", type=int, default=50_000)
    ap.add_argument(
        "--max-lines",
        type=int,
        default=200_000,
        help="stop scanning after this many lines (about 1 MB of download per 1000 lines)",
    )
    ap.add_argument("--secret-words", type=Path, default=ROOT / "data" / "secret_words.json")
    ap.add_argument("--output", type=Path, default=ROOT / "data" / "vectors" / "he.npz")
    ap.add_argument("--neighbors-output", type=Path, default=ROOT / "data" / "vectors" / "neighbors.npz")
    ap.add_argument("--no-neighbors", action="store_true", help="skip precomputing secret-word neighbours")
    args = ap.parse_args()

    secrets = load_secret_words(args.secret_words)
    wanted = set(secrets)

    if args.input is None:
        print(f"Streaming {args.url} (stops early once the vocabulary is complete)", file=sys.stderr)
        response = urllib.request.urlopen(args.url)  # noqa: S310 (fixed https URL or user-provided)
        counter = _CountingReader(response)
        text = io.TextIOWrapper(gzip.GzipFile(fileobj=io.BufferedReader(counter)), encoding="utf-8", errors="replace")
        words, vectors = select(iter_text_vectors(text), args.vocab_size, wanted, args.max_lines)
        response.close()
        print(f"  downloaded {counter.count / 1e6:.0f} MB", file=sys.stderr)
    elif args.input.suffix in {".vec", ".txt", ".gz"}:
        opener = gzip.open if args.input.suffix == ".gz" else open
        with opener(args.input, "rt", encoding="utf-8", errors="replace") as f:
            words, vectors = select(iter_text_vectors(f), args.vocab_size, wanted, args.max_lines)
    else:
        pairs = iter_gensim_vectors(args.input, args.word2vec_binary)
        words, vectors = select(pairs, args.vocab_size, wanted, args.max_lines)

    if not words:
        sys.exit("No Hebrew words found in the input.")
    matrix = np.vstack(vectors).astype(np.float32)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.output, words=np.array(words), vectors=matrix.astype(np.float16))
    size = args.output.stat().st_size / 1e6
    print(f"Wrote {len(words):,} words × {matrix.shape[1]} dims to {args.output} ({size:.0f} MB)", file=sys.stderr)

    if not args.no_neighbors:
        model = VectorModel.load(args.output)
        model.save_neighbors(args.neighbors_output, secrets)
        print(f"Wrote secret-word neighbours to {args.neighbors_output}", file=sys.stderr)


if __name__ == "__main__":
    main()
