# backend/ — Ingest & Registry API (Phase 2)

FastAPI (Python 3.12) service that gives collectors and the UI a single,
authorised surface to the operational plane — and **only** the operational
plane (governance writes are Git+PR territory, ADR-001).

Planned surface (v1 contract sketch):

| Endpoint group | Purpose | Write? |
|---|---|---|
| `/healthz`, `/readyz` | probes incl. git-sync freshness | read |
| `/api/v1/assets`, `/services`, `/software` | inventory upsert (idempotent, fingerprinted) | scoped collectors |
| `/api/v1/findings` | finding ingest (uniqueness by fingerprint) | scoped collectors |
| `/api/v1/evaluations` | engine decision records (internal) | engine only |
| `/api/v1/policies`, `/exceptions`, `/risks`, `/standards`, `/adrs`, `/controls` | registry **read-only** projection of Git | never |
| `/api/v1/reports` | posture/compliance reports | generators |
| `/api/v1/audit` | audit trail query | read |

Auth model: scoped, rotatable API keys per collector in Phase 2; OIDC + RBAC
for humans in Phase 4. Rule: anything a collector writes must be re-derivable
by re-running the collector.
