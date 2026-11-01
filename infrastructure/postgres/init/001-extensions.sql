-- 001-extensions.sql — extensions required by the AI-SecOps schema.
-- Applied automatically by the postgres image on first init
-- (mounted under /docker-entrypoint-initdb.d in docker-compose.yml).

-- SHA-256 for content fingerprints (governance provenance stamps).
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- Trigram search for asset/service/finding text lookups (registry search).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
