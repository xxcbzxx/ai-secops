# Generic ingest API — contract v1 (`ai-secops.ingest/v1`)

Phase 2 workstream 2.2. The service is the **single sanctioned write path into
the ops.\* operational plane** (ADR-002): external producers POST JSON, the
API validates against the DDL vocabulary and upserts idempotently, and every
accepted write produces exactly one `ops.audit_events` record in the *same*
transaction.

Governance (`gov.*`) is Git+PR territory (ADR-001) — this API cannot write it
even if a key leaked: the DB role (`ai_secops_ingest`, from
`postgres/init/004`) is **ops = read/write, gov = read only**.

## 0. First-run setup (operator, on the VM)

```bash
cd ~/ai-secops/infrastructure && umask 077
python3 -c 'import secrets;print(secrets.token_hex(32))' > secrets/pg_ingest_password.txt
{
  printf 'homelab-collector:';  python3 -c 'import secrets;print(secrets.token_hex(32))' | tr -d "\n"; printf ':assets services software findings\n'
  printf 'limited-collector:';  python3 -c 'import secrets;print(secrets.token_hex(32))' | tr -d "\n"; printf ':findings\n'
} > secrets/ingest_tokens.txt
chmod 600 secrets/*
```

Bring it up:

```bash
docker compose --env-file .env --profile api up -d        # postgres recreate + ingest-api
docker compose --env-file .env --profile api build ingest-api   # only after code changes
```

The ingest role is attached automatically on fresh init (`004-service-roles.sh`)
or manually on an existing volume:

```bash
docker cp postgres/init/004-service-roles.sh ai-secops-postgres-1:/tmp/004.sh
docker exec -e POSTGRES_USER=ai_secops -e POSTGRES_DB=ai_secops \
  ai-secops-postgres-1 sh /tmp/004.sh
```

## 1. Network posture

No published ports, ever. The container sits on:

- **`edge`** — attach *your* ingress (reverse proxy / tunnel container) and
  route a hostname to `ingest-api:8000`.
- **`data`** — in-stack callers (policy engine, future UI workers).

Quick probe from a throwaway container:

```bash
docker run --rm --network ai-secops_edge curlimages/curl \
  -sS http://ingest-api:8000/healthz
```

## 2. Auth — scoped, rotatable keys

Bearer keys from `secrets/ingest_tokens.txt` (mounted at
`/run/secrets/ingest_tokens`), one per line:

```
name:opaque-token:scope1 scope2 ...
```

| Element | Rule |
|---|---|
| `name` | stored in audit `details.producer`; must not contain `:` |
| token  | must not contain `:`; `openssl rand -hex 32` recommended |
| scopes | whitespace/comma list, subset of `assets services software findings` |

Responses: missing/unknown key → **401**; valid key without the endpoint scope
→ **403**; missing/empty tokens file → **503** on every write (fail closed).
Rotation = edit the file, then `docker compose --env-file .env --profile api
restart ingest-api`.

## 3. Endpoints

| Method | Path | Scope | Upsert key |
|---|---|---|---|
| GET  | `/healthz` | open (reports auth + db posture) | — |
| GET  | `/readyz`  | open (503 unless DB answers) | — |
| POST | `/api/v1/assets`   | `assets`   | `asset_uid` |
| POST | `/api/v1/services` | `services` | `service_uid` (asset must exist first) |
| POST | `/api/v1/software` | `software` | `(asset, product, vendor, version)` |
| POST | `/api/v1/findings` | `findings` | `sha256(source \| rule_id \| target \| title)` |

Write responses are **201 created** / **200 updated** (same id), body:
`{"api_version", "created", "id", "identity"}`. Errors: **422** for
validation/integrity (unknown parent asset/service, malformed uid, invalid
enum), **409** for a rare concurrent insert race (retry the same payload).

All enums mirror `002-schema.sql` exactly (`asset_kind`, `environment`,
`exposure`, `criticality`, `lifecycle`, `asset_source`, `severity`) — anything
else is rejected with 422 naming the allowed values.

## 4. Merge semantics (the idempotency contract)

- **Latest-wins** core fields: `kind`, `name`, `environment`, `exposure`,
  `criticality`, `lifecycle`, `tags`, `metadata`, `endpoints`, `severity`,
  `evidence`, `raw`.
- **Update-only-if-sent**: `owner_team`, `platform`, `provider`, `cpe`, `purl`,
  `kind` on services, `description` on findings.
- **First-wins**: asset `source`, `first_seen_at`, `first_detected_at`,
  `id`s.
- **Timestamps merge**: `min(first_seen_at)`, `max(last_seen_at)`,
  `max(last_detected_at)`.
- Findings `state` (`new/evaluated/...`) is **never** touched by ingest — that
  is the policy engine's decision record domain (workstream 2.3).
- "Anything a collector writes must be re-derivable by re-running the
  collector" (backend/README.md): duplicated deliveries collapse into the same
  row, so re-running collectors is cheap and audit-visible.

## 5. Example — a scanner posting a finding

```bash
TOKEN=$(head -1 YOUR-COPY-of-ingest_tokens.txt | cut -d: -f2)

curl -sS -X POST https://ingest.YOUR-DOMAIN/api/v1/findings \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "source": "trivy-proxy",
    "rule_id": "CVE-2024-21412",
    "title": "Microsoft Defender SmartScreen bypass",
    "severity": "high",
    "asset_uid": "win11-admin-01",
    "evidence": {"cpe": "cpe:2.3:o:microsoft:windows_11:23h2"},
    "raw": {"scanner_version": "0.50.1"}
  }'
```

`{"api_version":"ai-secops.ingest/v1","created":true,"id":4,"identity":"9fa4…"}`

## 6. Acceptance drill

```bash
docker compose --env-file .env --profile api exec -T ingest-api \
  python /app/scripts/ingest_acceptance.py
```

Covers auth (401/403), idempotency (same id on re-POST), integrity negatives
(422 without rows), DB + audit reality checks, and tear-down. Safe to re-run.
