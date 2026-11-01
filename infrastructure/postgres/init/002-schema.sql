-- 002-schema.sql — AI-SecOps two-plane database (Phase 1, workstream 1.1)
--
--   gov = projection of the Git governance plane (written ONLY by the sync
--         service; every row carries exact provenance: path, hash, commit).
--   ops = operational plane (assets, services, software, findings,
--         evaluations, threat entries, reports?, sync/audit machinery).
--
-- Conventions
--   * artifact ids are immutable business keys (POL-001, EX-001, ...)
--   * semver everywhere ('1.0.0'), dates are SQL DATE, instants timestamptz
--   * accidental-drop protection: NOTHING here is drop-on-sync; sync upserts.

BEGIN;

CREATE SCHEMA IF NOT EXISTS gov;
CREATE SCHEMA IF NOT EXISTS ops;
COMMENT ON SCHEMA gov IS 'Read-mostly projection of governance Git artifacts. Rebuildable; single writer = sync service.';
COMMENT ON SCHEMA ops IS 'Operational plane: inventory, findings, evaluations, threat intel, sync/audit state.';

-- updated_at helper -------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- enums -------------------------------------------------------------------
CREATE TYPE ops.severity      AS ENUM ('informational','low','medium','high','critical');
CREATE TYPE ops.asset_kind    AS ENUM ('host','vm','container','network_device','appliance','site','cluster','cloud_account','storage','database','application');
CREATE TYPE ops.environment   AS ENUM ('lab','staging','production','dmz','management');
CREATE TYPE ops.exposure      AS ENUM ('internal','edge_exposed','public');
CREATE TYPE ops.criticality   AS ENUM ('tier1','tier2','tier3','tier4');
CREATE TYPE ops.lifecycle     AS ENUM ('planned','active','decommissioning','decommissioned');
CREATE TYPE ops.asset_source  AS ENUM ('discovered','imported','declared');
CREATE TYPE ops.finding_state AS ENUM ('new','evaluated','remediated','false_positive','void');
CREATE TYPE ops.eval_status   AS ENUM ('compliant','violation','violation_with_exception','accepted_risk','recommendation_only','not_applicable','under_review');
CREATE TYPE ops.threat_source AS ENUM ('nvd','cve','cisa_kev','ghsa','vendor_rss','manual');
CREATE TYPE ops.tlp           AS ENUM ('red','amber','amber_strict','green','clear');
CREATE TYPE ops.actor_kind    AS ENUM ('human','system','service','collector','ai_advisor');
CREATE TYPE ops.action_kind   AS ENUM ('created','updated','approved','rejected','revoked','expired','evaluated','imported','synced','regenerated','voided');
CREATE TYPE ops.sync_status   AS ENUM ('pending','syncing','ok','degraded','error');
CREATE TYPE gov.policy_state    AS ENUM ('draft','in_review','active','superseded','retired');
CREATE TYPE gov.exception_status AS ENUM ('draft','pending_approval','active','expired','revoked','rejected');
CREATE TYPE gov.risk_status     AS ENUM ('identified','under_assessment','pending_decision','accepted','accepted_with_controls','mitigated','transferred','closed');
CREATE TYPE gov.risk_band       AS ENUM ('low','medium','high','critical');
CREATE TYPE gov.control_strength AS ENUM ('strong','partial','compensating','weak');
CREATE TYPE gov.control_state   AS ENUM ('draft','active','retired');
CREATE TYPE gov.adr_state       AS ENUM ('proposed','accepted','superseded','rejected','deprecated');
CREATE TYPE gov.standard_state  AS ENUM ('adopted','current','revised','retired');
CREATE TYPE gov.control_mapping AS ENUM ('full','partial','aligned');

-- ===========================================================================
-- GOVERNANCE PLANE (schema gov) — projection; single writer: the sync service
-- ===========================================================================
CREATE TABLE gov.policies (
    policy_uid       TEXT PRIMARY KEY CHECK (policy_uid ~ '^POL-[0-9]{3}$'),
    version          TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    title            TEXT NOT NULL,
    category         TEXT NOT NULL,
    authority        TEXT NOT NULL,
    owner            TEXT NOT NULL,
    review_cadence   TEXT NOT NULL DEFAULT 'annual',
    effective_from   DATE  NOT NULL,
    review_due       DATE,
    approved_by      JSONB NOT NULL DEFAULT '[]'::jsonb,
    statement        TEXT  NOT NULL,
    scope            JSONB NOT NULL,             -- selector, see asset model doc
    requirement      JSONB NOT NULL DEFAULT '{}'::jsonb,
    control_refs     JSONB NOT NULL DEFAULT '[]'::jsonb,
    related          JSONB NOT NULL DEFAULT '{}'::jsonb,
    state            gov.policy_state NOT NULL,
    supersedes       TEXT,
    source_path      TEXT NOT NULL UNIQUE,
    source_commit    TEXT,
    content_sha256   TEXT NOT NULL,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE gov.policies IS
 'POL-* artifacts. writer = sync service. state/approvals mirror the YAML.';

CREATE TABLE gov.risks (
    risk_uid         TEXT PRIMARY KEY CHECK (risk_uid ~ '^RSK-[0-9]{3}$'),
    version          TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    title            TEXT NOT NULL,
    status           gov.risk_status NOT NULL,
    category         TEXT NOT NULL,
    owner            TEXT NOT NULL,
    description      TEXT NOT NULL,
    asset_refs       TEXT [] NOT NULL DEFAULT '{}',
    service_refs     TEXT [] NOT NULL DEFAULT '{}',
    assessment       JSONB NOT NULL,             -- inherent likelihood/impact/score/band
    threat_statements TEXT [] NOT NULL DEFAULT '{}',
    existing_controls JSONB NOT NULL DEFAULT '[]'::jsonb,
    mitigation_plan  JSONB NOT NULL DEFAULT '[]'::jsonb,
    residual         JSONB NOT NULL,
    appetite         TEXT NOT NULL,
    appetite_note    TEXT,
    acceptance       JSONB,                      -- null until a human decides
    review           JSONB,
    related          JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_path      TEXT NOT NULL UNIQUE,
    source_commit    TEXT,
    content_sha256   TEXT NOT NULL,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE gov.exceptions (
    exception_uid    TEXT PRIMARY KEY CHECK (exception_uid ~ '^EX-[0-9]{3}$'),
    version          TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    title            TEXT NOT NULL,
    policy_uid       TEXT NOT NULL REFERENCES gov.policies(policy_uid) ON UPDATE CASCADE,
    policy_version   TEXT NOT NULL,
    risk_uid         TEXT NOT NULL REFERENCES gov.risks(risk_uid) ON UPDATE CASCADE, -- mandatory link (hard rule)
    requested_by     JSONB NOT NULL,
    requested_at     DATE  NOT NULL,
    status           gov.exception_status NOT NULL,
    valid_from       DATE,
    valid_to         DATE,
    review_before    DATE,
    justification    TEXT NOT NULL,
    conditions       TEXT [] NOT NULL DEFAULT '{}',
    compensating_controls TEXT [] NOT NULL DEFAULT '{}',   -- CTL ids
    scope            JSONB NOT NULL,
    approvers        JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_path      TEXT NOT NULL UNIQUE,
    source_commit    TEXT,
    content_sha256   TEXT NOT NULL,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN gov.exceptions.risk_uid IS
 'Hard rule: no exception without a linked risk (CI + sync enforce).';

CREATE TABLE gov.standards (
    standard_uid     TEXT PRIMARY KEY CHECK (standard_uid ~ '^STD-[0-9]{3}$'),
    version          TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    title            TEXT NOT NULL,
    state            gov.standard_state NOT NULL,
    body             TEXT  NOT NULL,             -- 'internal' | framework id
    based_on         TEXT [] NOT NULL DEFAULT '{}',
    summary          TEXT NOT NULL,
    applicability    JSONB NOT NULL DEFAULT '{}'::jsonb,
    controls         JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{id, title, requirement, mapped_policies, evidence_hints}]
    owner            TEXT NOT NULL,
    effective_from   DATE,
    review           JSONB,
    related          JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_path      TEXT NOT NULL UNIQUE,
    source_commit    TEXT,
    content_sha256   TEXT NOT NULL,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE gov.adrs (
    adr_uid          TEXT PRIMARY KEY CHECK (adr_uid ~ '^ADR-[0-9]{3}$'),
    version          TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    title            TEXT NOT NULL,
    status           gov.adr_state NOT NULL,
    decided_at       DATE,
    supersedes       TEXT [] NOT NULL DEFAULT '{}',
    superseded_by    TEXT [] NOT NULL DEFAULT '{}',
    deciders         JSONB NOT NULL DEFAULT '[]'::jsonb,
    context          TEXT NOT NULL,
    decision         TEXT NOT NULL,
    options_considered JSONB NOT NULL DEFAULT '[]'::jsonb,
    consequences     JSONB NOT NULL DEFAULT '{}'::jsonb,
    related          JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_path      TEXT NOT NULL UNIQUE,
    source_commit    TEXT,
    content_sha256   TEXT NOT NULL,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE gov.controls (
    control_uid      TEXT PRIMARY KEY CHECK (control_uid ~ '^CTL-[0-9]{3}$'),
    version          TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    title            TEXT NOT NULL,
    status           gov.control_state NOT NULL,
    strength         gov.control_strength NOT NULL,
    owner            TEXT NOT NULL,
    description      TEXT NOT NULL,
    covers_risks     TEXT [] NOT NULL DEFAULT '{}',
    supports_exceptions TEXT [] NOT NULL DEFAULT '{}',
    verification     JSONB NOT NULL DEFAULT '{}'::jsonb, -- method, evidence_ref+hash, verified_by/at, review_cadence
    limitations      TEXT [] NOT NULL DEFAULT '{}',
    related          JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_path      TEXT NOT NULL UNIQUE,
    source_commit    TEXT,
    content_sha256   TEXT NOT NULL,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===========================================================================
-- OPERATIONAL PLANE (schema ops) — machine-written
-- ===========================================================================
CREATE TABLE ops.assets (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_uid    TEXT UNIQUE NOT NULL CHECK (asset_uid ~ '^[a-z0-9][a-z0-9_-]{2,62}$'),
    kind         ops.asset_kind NOT NULL,
    name         TEXT NOT NULL,
    environment  ops.environment NOT NULL DEFAULT 'lab',
    exposure     ops.exposure NOT NULL DEFAULT 'internal',
    criticality  ops.criticality NOT NULL DEFAULT 'tier3',
    lifecycle    ops.lifecycle NOT NULL DEFAULT 'active',
    source       ops.asset_source NOT NULL DEFAULT 'discovered',
    owner_team   TEXT,
    platform     TEXT,          -- e.g. 'Debian 13', 'IOS-XE'
    provider     TEXT,          -- collector id: 'proxmox','portainer','manual'
    parent_id    BIGINT REFERENCES ops.assets(id) ON DELETE SET NULL,
    tags         TEXT [] NOT NULL DEFAULT '{}',
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ,
    last_seen_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_assets_kind  ON ops.assets (kind);
CREATE INDEX ix_assets_env   ON ops.assets (environment, exposure);
CREATE INDEX ix_assets_tags  ON ops.assets USING gin (tags);
CREATE INDEX ix_assets_name  ON ops.assets USING gin (name gin_trgm_ops);

CREATE TABLE ops.services (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    service_uid   TEXT UNIQUE NOT NULL,
    asset_id      BIGINT NOT NULL REFERENCES ops.assets(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    kind          TEXT,           -- 'web_app','database','api','proxy',...
    exposure      ops.exposure,   -- NULL = inherit from asset
    endpoints     JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{proto, port, addr}]
    owner_team    TEXT,
    tags          TEXT [] NOT NULL DEFAULT '{}',
    first_seen_at TIMESTAMPTZ,
    last_seen_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_services_asset ON ops.services (asset_id);
CREATE INDEX ix_services_expo  ON ops.services (exposure);

CREATE TABLE ops.asset_software (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id     BIGINT NOT NULL REFERENCES ops.assets(id) ON DELETE CASCADE,
    product      TEXT NOT NULL,
    vendor       TEXT,
    version      TEXT,
    cpe          TEXT,          -- cpe:2.3:*:... canonical key for correlation
    purl         TEXT,
    evidence     JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ,
    last_seen_at  TIMESTAMPTZ,
    UNIQUE (asset_id, product, vendor, version)
);

CREATE TABLE ops.findings (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fingerprint   TEXT UNIQUE NOT NULL,       -- sha256(source+rule+target+title); ingest idempotency
    source        TEXT NOT NULL,              -- adapter id, e.g. 'ingest','proxmox','manual'
    rule_id       TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    severity      ops.severity NOT NULL,
    asset_id      BIGINT REFERENCES ops.assets(id),
    service_id    BIGINT REFERENCES ops.services(id),
    evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw           JSONB NOT NULL DEFAULT '{}'::jsonb,
    state         ops.finding_state NOT NULL DEFAULT 'new',
    first_detected_at TIMESTAMPTZ,
    last_detected_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT findings_target CHECK (asset_id IS NOT NULL OR service_id IS NOT NULL)
);
CREATE INDEX ix_findings_asset ON ops.findings (asset_id);
CREATE INDEX ix_findings_state ON ops.findings (state, severity);

CREATE TABLE ops.evaluations (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    finding_id     BIGINT NOT NULL REFERENCES ops.findings(id) ON DELETE CASCADE,
    policy_id      TEXT REFERENCES gov.policies(policy_uid),  -- NULL => recommendation-only, no policy exists
    exception_id   TEXT,
    risk_id        TEXT,
    control_id     TEXT,
    status         ops.eval_status NOT NULL,
    rationale      TEXT NOT NULL,
    matched_artifacts JSONB NOT NULL DEFAULT '{}'::jsonb, -- {policies:[],exceptions:[],risks:[],controls:[],standards:[]}
    engine_version TEXT NOT NULL,
    decided_by     TEXT   NOT NULL DEFAULT 'policy-engine',
    decided_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_eval_finding  ON ops.evaluations (finding_id);
CREATE INDEX ix_eval_status   ON ops.evaluations (status);
CREATE INDEX ix_eval_latest   ON ops.evaluations (policy_id, status, decided_at DESC);

CREATE TABLE ops.threat_entries (       -- Phase 3 landing table; ingestion deferred
    threat_uid     TEXT UNIQUE NOT NULL,     -- e.g. 'nvd:CVE-2024-21412'
    source         ops.threat_source NOT NULL,
    source_id      TEXT NOT NULL,
    title          TEXT NOT NULL,
    summary        TEXT,
    cvss           NUMERIC(3,1),
    epss           NUMERIC(6,5),
    kev            BOOLEAN NOT NULL DEFAULT FALSE,
    kev_added_at   DATE,
    published_at   DATE,
    affected_products JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [cpe/purl]
    refs           JSONB NOT NULL DEFAULT '[]'::jsonb,  -- upstream 'references' list (renamed: reserved SQL keyword)
    tlp            ops.tlp NOT NULL DEFAULT 'amber',
    raw            JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX ix_threat_kev ON ops.threat_entries (kev) WHERE kev;

-- machinery: sync state + audit trail --------------------------------------
CREATE TABLE ops.sync_state (
    store        TEXT PRIMARY KEY,             -- 'main'
    store_kind   TEXT NOT NULL DEFAULT 'filesystem',  -- filesystem | gitforge | sharepoint
    target       TEXT NOT NULL,                -- bind-dir or forge remote
    branch       TEXT NOT NULL DEFAULT 'main',
    head_commit  TEXT,
    artifacts    INTEGER,
    status       ops.sync_status NOT NULL DEFAULT 'pending',
    error        TEXT,
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ops.audit_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_kind  ops.actor_kind NOT NULL,
    actor       TEXT NOT NULL,
    action      ops.action_kind NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT,
    details     JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ix_audit_time     ON ops.audit_events (occurred_at DESC);
CREATE INDEX ix_audit_entity   ON ops.audit_events (entity_type, entity_id);

-- reporting views -----------------------------------------------------------
CREATE OR REPLACE VIEW ops.v_active_exceptions AS
SELECT e.*, p.title AS policy_title
FROM gov.exceptions e JOIN gov.policies p USING (policy_uid)
WHERE e.status = 'active'
  AND e.valid_from <= CURRENT_DATE AND e.valid_to > CURRENT_DATE;

CREATE OR REPLACE VIEW ops.v_expired_posture AS   -- exhausts the review queue
SELECT * FROM gov.exceptions
WHERE status = 'active' AND (review_before <= CURRENT_DATE OR valid_to   <= CURRENT_DATE);

-- ===========================================================================
-- triggers & housekeeping
-- ===========================================================================
CREATE OR REPLACE TRIGGER trg_touch_updated_at BEFORE UPDATE ON ops.assets
FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();
CREATE OR REPLACE TRIGGER trg_touch_updated_at BEFORE UPDATE ON ops.services
FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();
CREATE OR REPLACE TRIGGER trg_touch_updated_at BEFORE UPDATE ON ops.findings
FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();
-- (gov.* rows are replace-on-sync; updated_at mirrors the upstream file's own
-- review timestamps — never edited ad hoc in the DB)

COMMIT;
