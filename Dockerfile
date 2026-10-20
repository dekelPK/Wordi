FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY wordi ./wordi
COPY web ./web
COPY scripts ./scripts
COPY data/secret_words.json ./data/secret_words.json

# Vectors are mounted (or baked in) at /app/data/vectors; the SQLite DB lives in /app/data/db.
ENV WORDI_DB_URL=sqlite:////app/data/db/wordi.db \
    WORDI_TRUST_PROXY=0
RUN mkdir -p /app/data/db /app/data/vectors
VOLUME ["/app/data/db"]
EXPOSE 8000
CMD ["uvicorn", "wordi.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
