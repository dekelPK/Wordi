# Wordi — architecture

## File structure

```
wordi/                     Python package (FastAPI backend)
  config.py                Settings from environment variables
  hebrew.py                Normalisation (niqqud, geresh), prefix stripping
  vectors.py               VectorModel: load .npz, cosine similarity, top-k neighbours, cache
  words.py                 Secret-word list, Asia/Jerusalem calendar, deterministic daily word
  db.py                    Engine / session factory
  models.py                SQLAlchemy ORM (schema below)
  schemas.py               Pydantic request/response models
  game.py                  Game rules: sessions, guesses, hints, give-up
  leaderboard.py           Name validation, submission, ranking queries
  profanity.py             Hebrew + English blocklist
  ratelimit.py             In-memory sliding-window rate limiter (middleware)
  api.py                   HTTP routes
  main.py                  App factory (create_app) + static file serving
web/                       Frontend (vanilla JS + Tailwind, RTL)
  index.html, app.js, app.css (built, committed)
tailwind/                  Tailwind source + config (only needed to rebuild app.css)
data/
  secret_words.json        Curated secret words (365+)
  vectors/                 Prepared vectors + neighbour cache (git-ignored)
scripts/
  prepare_vectors.py       Download/convert embeddings -> compact .npz
  precompute_neighbors.py  Top-1000 neighbours for every secret word
  make_demo_vectors.py     Synthetic vectors for development/tests (no semantics)
tests/                     pytest suite
Dockerfile, requirements.txt, README.md
```

## Vector file format

`data/vectors/he.npz`: `words` (unicode array, frequency order) and `vectors`
(float16, L2-normalised, shape `n × 300`). Loaded into a float32 matrix at startup
(~60 MB for 50K words); a similarity is a dot product, top-k is one mat-vec + `argpartition`.

`data/vectors/neighbors.npz`: per secret word the 1000 nearest word indices + similarities,
keyed by a fingerprint of the vector file so a stale cache is ignored.

## Rank convention

Like Semantle: among the secret's 1000 nearest neighbours, the closest has rank **1000/1000**,
the 1000th closest has rank **1/1000**. Words outside the top 1000 have no rank ("cold").

## DB schema (SQLite)

```
game_sessions
  id               TEXT PK            random 128-bit hex (unguessable)
  player_id        TEXT  NOT NULL     anonymous UUID (localStorage + cookie)
  mode             TEXT  NOT NULL     'daily' | 'free'
  puzzle_number    INT   NULL         daily only
  secret_word      TEXT  NOT NULL     never sent to the client before solve/give-up
  created_at       DATETIME
  first_guess_at   DATETIME NULL      timer start (server clock)
  solved_at        DATETIME NULL
  gave_up_at       DATETIME NULL
  used_hint        BOOL
  guess_count      INT                non-hint guesses
  UNIQUE (player_id, puzzle_number) WHERE mode = 'daily'   -- one official attempt per day

guesses
  id               INT PK
  session_id       TEXT FK -> game_sessions.id
  seq              INT                1-based order
  word             TEXT               resolved vocabulary word
  similarity       FLOAT
  rank             INT NULL
  is_hint          BOOL
  created_at       DATETIME
  UNIQUE (session_id, word)

leaderboard_entries
  id               INT PK
  session_id       TEXT FK UNIQUE
  player_id        TEXT
  puzzle_number    INT
  name             TEXT               validated plain text
  guess_count      INT                copied from the server-side session
  duration_ms      INT                solved_at - first_guess_at (server clock)
  submitted_at     DATETIME
  UNIQUE (player_id, puzzle_number)
  INDEX (puzzle_number, guess_count, duration_ms, submitted_at)
```

The client never submits a score: `POST /api/leaderboard` only carries a session id and a
name; guess count and time come from rows the server wrote while the game was played.
