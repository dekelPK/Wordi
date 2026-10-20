FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY wordi ./wordi
COPY scripts ./scripts
COPY data/secret_words.json ./data/secret_words.json

# Build the word vectors into the image.
#   VECTORS=fasttext  stream the head of fastText cc.he.300 (~100-200 MB download)
#   VECTORS=demo      synthetic vectors, for testing the image without the download
FROM base AS vectors
ARG VECTORS=fasttext
ARG VOCAB_SIZE=50000
RUN if [ "$VECTORS" = "demo" ]; then python scripts/make_demo_vectors.py; \
    else python scripts/prepare_vectors.py --vocab-size "$VOCAB_SIZE"; fi

FROM base
COPY web ./web
COPY --from=vectors /app/data/vectors ./data/vectors
# Without WORDI_DB_URL the app uses SQLite in /app/data/db; mount a volume there to keep it.
# On hosts with an ephemeral disk (e.g. Render free) set WORDI_DB_URL to a Postgres URL instead.
ENV WORDI_DB_URL=sqlite:////app/data/db/wordi.db
RUN mkdir -p /app/data/db
EXPOSE 8000
# Hosts like Render pass the port in $PORT.
CMD ["sh", "-c", "exec uvicorn wordi.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
