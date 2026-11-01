# Data Model — two-plane schema (Phase 1, workstream 1.1)

Status: implemented as `infrastructure/postgres/init/002-schema.sql`
(auto-applies on first `docker compose up`; target PostgreSQL 16+).

---

## 1. Planes recap (ADR-001)

| Plane | Schema | Single writer | Content |
|---|---|---|---|
| Governance (derived) | `gov.*` | sync service only | policies, exceptions, risks, standards, ADRs, controls — each row stamped `source_path`, `source_commit`, `content_sha256` |
| Operational (native) | `ops.*` | ingest API + engine + collectors | assets, services, software, findings, evaluations, threat entries, reports, sync/audit machinery |

DB rules: artifact ids are business keys (`EX-001`), `version` semver-check-contrained,
governance tables are never hand-edited; roles `ai_secops_app / _ro / _sync`
enforce write boundaries (003-seed.sql).

## 2. ERD

```mermaid
erDiagram
  POLICIES ||--o{ EXCEPTIONS : is_excepted_by
  RISKS    ||--o{ EXCEPTIONS : motivates
  POLICIES ||--o{ EVALUATIONS : evaluated_against
  FINDINGS ||--o{ EVALUATIONS : produces
  ASSETS   ||--o{ SERVICES : hosts
  ASSETS   ||--o{ ASSET_SOFTWARE : runs
  ASSETS   ||--o{ FINDINGS : about
  SERVICES ||--o{ FINDINGS : about
  THREAT_ENTRIES }o--o{ ASSET_SOFTWARE : correlates
  STANDARDS ||--o{ CONTROLS_in : defines
  GLOBAL_ADRS ||--PER-ARTIFACT related{} : documents
```

(ADRs and controls connect via JSONB `related` structures; normalized bridge
tables are a Phase 2 optimization if the graph grows.)

## 3. Table catalog

### gov.* (projection)

| Table | Key columns | Notes |
|---|---|---|
| `gov.policies` | `policy_uid` `^POL-###` PK, `scope` JSONB, `state`, approval info definitive | Projection of YAML; `approval required for active + superseded` per schema too |
| `gov.exceptions` | `policy_uid` FK p, `risk_uid` FK risks NOT NULL | Exception without risk = schema-impossible |
| `gov.risks` | `assessment` JSONB, `residual` JSONB, `acceptance` JSONB (null until decision) | ```
dedupe via single row per RSK id |
| `gov.standards` | `controls` JSONB [{id, mapped_policies}] | controls always alongside datapoints |
| `gov.adrs` | status, supersedes[] , consequences | |
| `gov.controls` | `strength`, `verification` JSONB w/ hash + evidence ref | verbatim evidence external path |

### ops.* (native)

| Table | Key columns | Notes |
|---|---|---|
| `ops.assets` | `asset_uid` slug UNIQUE, kind, environment, exposure, criticality, lifecycle, source | gin index on tags, trigram on name |
| `ops.services` | `service_uid` UNIQUE, asset_id FK, exposure (nullable → inherits) | |
| `ops.asset_software` | product/vendor/version, `cpe` (correlation key), `purl` | unique per quintuple |
| `ops.findings` | `fingerprint` UNIQUE (idempotent ingest), asset or service id CHECK, severity, state | |
| `ops.evaluations` | finding_id FK, policy_id FK, status 7-state, `matched_artifacts` JSONB trace, engine_version | decision records — engine writes, humans never |
| `ops.threat_entries` | `threat_uid` ('nvd:CVE-...'), KEV flag, `affected_products` JSONB | Phase-3 landing table; ingestion deferred |
| `ops.sync_state` | store PK('main'), kind, head_commit, status | freshness must be visible in UI |
| `ops.audit_events` | actor kind/text, action, entity, details JSONB | every state change lands here |

## 4. Status vocabularies (single source of truth = DDL enums)

- evaluation: `compliant · violation · violation_with_exception · accepted_risk · recommendation_only` + `not_applicable · under_review`
- policy: `draft · in_review · active · superseded · retired`
- exception: `draft · pending_approval · active · expired · revoked · rejected` (+ schema-mandated validity window for active)
- risk: `identified · under_assessment · pending_decision · accepted · accepted_with_controls · mitigated · transferred · closed`
- finding: `new · evaluated · remediated · false_positive · void`

## 5. Retention / rebuild

- `gov.*` = WAS wipes + re-sync — origin must always restore determinism (proven-hash).
- `ops.findings`/`evaluations`: retention 24 months hot (t), metrics snapshots
  post-mortem (t+7y, retention table Phase 4).
- `ops.audit_events`: 7 years hot 90 days — enterprise default.
