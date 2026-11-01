# AI-SecOps governance sync job — filesystem store adapter (Phase 2, 2.1).
#
# Build context is the REPO ROOT so code paths are stable relative to the
# Dockerfile:
#   docker compose --env-file .env --profile sync build governance-sync
# The governance corpus itself is NOT baked in — it is bind-mounted
# read-only at /governance at runtime (code changes rebuild; corpus changes
# sync live).
FROM python:3.13-slim

WORKDIR /app

COPY scripts/governance_sync.py ./scripts/governance_sync.py
RUN pip install --no-cache-dir "psycopg[binary]>=3.2" "pyyaml>=6.0.1" "jsonschema>=4.21"

ENTRYPOINT ["python", "/app/scripts/governance_sync.py"]
