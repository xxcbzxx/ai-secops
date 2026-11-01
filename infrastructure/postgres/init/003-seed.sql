-- 003-seed.sql — minimal, idempotent seed: DB roles (least privilege) and
-- the sync-state row that the governance sync service (Phase 2) will own.

-- ---------------------------------------------------------------------------
-- Group roles (no passwords; attach a LOGIN role per service in Phase 2)
--   ai_secops_app   : ingest/registry API  -> ops (rw), gov (ro)
--   ai_secops_ro    : UI/reporting reads   -> all read
--   ai_secops_sync  : governance sync      -> gov (rw), ops sync_state (rw)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_secops_app') THEN
    CREATE ROLE ai_secops_app NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_secops_ro') THEN
    CREATE ROLE ai_secops_ro NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_secops_sync') THEN
    CREATE ROLE ai_secops_sync NOLOGIN;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA gov, ops TO ai_secops_app, ai_secops_ro, ai_secops_sync;
GRANT SELECT ON ALL TABLES IN SCHEMA gov, ops TO ai_secops_app, ai_secops_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ops TO ai_secops_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA gov TO ai_secops_sync;
GRANT SELECT, INSERT, UPDATE ON ops.sync_state, ops.audit_events TO ai_secops_sync;
ALTER DEFAULT PRIVILEGES IN SCHEMA gov, ops
  GRANT SELECT ON TABLES TO ai_secops_ro;

-- ---------------------------------------------------------------------------
-- Sync state hoodie: one row per governance store adapter.
-- The filesystem store (T1 default) is pre-registered; nothing else exists yet.
-- ---------------------------------------------------------------------------
INSERT INTO ops.sync_state (store, store_kind, target, branch, status)
VALUES (
  'main',
  'filesystem',
  './',                       -- compose mounts the repo checkout here
  'main',
  'pending'
)
ON CONFLICT (store) DO NOTHING;
