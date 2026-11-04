# AI-SecOps generic ingest API — the sanctioned write path into ops.* (Phase
# 2, workstream 2.2). Code + acceptance drill are baked; configuration is via
# env + secrets. Build context is the REPO ROOT:
#   docker compose --env-file .env --profile api build ingest-api
FROM python:3.13-slim

WORKDIR /app

COPY backend/ingest/app.py ./app.py
COPY scripts/ingest_acceptance.py ./scripts/ingest_acceptance.py
RUN pip install --no-cache-dir "fastapi==0.162.0" "uvicorn==0.54.0" "psycopg[binary,pool]==3.3.6" \
    "psycopg-pool==3.3.3" "pydantic==2.14.2" "starlette==1.10.0"

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/readyz', timeout=4)"]

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
