#!/usr/bin/env python3
"""AI-SecOps generic ingest API — the single sanctioned write path into ops.*
(Phase 2, workstream 2.2; backend/README.md v1 contract, rows 'scoped collectors').

Contract highlights (docs/ingest-api.md is the formal document):
  * upserts, idempotent by natural key:
      assets    -> ops.assets.asset_uid
      services  -> ops.services.service_uid  (asset must be on record first)
      software  -> ops.asset_software (asset, product, vendor, version)
      findings  -> sha256(source|rule_id|target|title) per 002-schema.sql
  * every accepted write lands with ONE ops.audit_events record in the SAME
    transaction — the audit trail is append-only, not optional.
  * scoped bearer keys from a mounted tokens file; fail-closed: missing/empty
    file refuses every write (no silent open mode).
  * least privilege: connects as the ai_secops_ingest LOGIN role (member of
    ai_secops_app, 003/004) — ops is read/write, gov is READ ONLY, so this
    process mathematically cannot touch the governance plane (ADR-002).
  * no published ports: internal `data` + `edge` networks; ingress is yours.

Endpoints (v1, aligned with backend/README.md):
    GET  /healthz                   liveness (open)
    GET  /readyz                    DB pool check (open)
    POST /api/v1/assets             scope: assets
    POST /api/v1/services           scope: services
    POST /api/v1/software           scope: software
    POST /api/v1/findings           scope: findings
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger("ingest")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

API_VERSION = "ai-secops.ingest/v1"

PGHOST = os.environ.get("PGHOST", "postgres")
PGPORT = os.environ.get("PGPORT", "5432")
PGDATABASE = os.environ.get("PGDATABASE", "ai_secops")
PGUSER = os.environ.get("PGUSER", "ai_secops_ingest")
PGPASSWORD_FILE = os.environ.get("PGPASSWORD_FILE", "/run/secrets/pg_ingest_password")
INGEST_TOKENS_FILE = os.environ.get("INGEST_TOKENS_FILE", "/run/secrets/ingest_tokens")

UID_RE = r"^[a-z0-9][a-z0-9_-]{2,62}$"

# Enum vocabularies in the models below are MIRRORED verbatim from
# infrastructure/postgres/init/002-schema.sql; pydantic rejects any other
# value with 422 naming the allowed options. Written as explicit
# Literal[...] values so the models compile on Python 3.10+ everywhere
# (star-unpacked Literal[*TUPLE] would need 3.11+).


# ---------------------------------------------------------------- tokens/auth
class Tokens:
    """Bearer-key index loaded from the mounted secrets file (never logged).

    File format, one entry per line:
        name:opaque-token:scope1 scope2 scope3
    '#'-lines and blanks are ignored. Scopes are space- or comma-separated.
    """

    def __init__(self) -> None:
        self.index: dict[str, tuple[str, frozenset[str]]] = {}

    def load(self) -> None:
        path = Path(INGEST_TOKENS_FILE)
        entries: dict[str, tuple[str, frozenset[str]]] = {}
        if path.is_file():
            for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) != 3 or not all(p.strip() for p in parts):
                    log.warning("tokens file line %d malformed — skipped", n)
                    continue
                name, token, scopes = parts
                token = token.strip()
                if not token.isascii() or any(not 33 <= ord(c) <= 126 for c in token):
                    log.warning("tokens file line %d has invalid token syntax — skipped", n)
                    continue
                entries[token] = (name.strip(), frozenset(
                    s.strip() for s in scopes.replace(",", " ").split() if s.strip()))
        self.index = entries
        if entries:
            log.info("loaded %d scoped key(s) — writes enabled", len(entries))
        else:
            log.error("INGEST KEYS NOT CONFIGURED (%s) — every write will refuse "
                      "(fail-closed); mount the ingest_tokens secret", INGEST_TOKENS_FILE)

    def check(self, authorization: str | None, scope: str) -> str:
        """Return the key name on success; raise the right HTTP error otherwise."""
        if not self.index:
            raise HTTPException(status_code=503, detail=(
                "ingest keys not configured (fail closed) — mount "
                "secrets/ingest_tokens.txt and restart"))
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="bearer key required",
                                headers={"WWW-Authenticate": "Bearer"})
        presented = authorization[7:]
        if (not presented or not presented.isascii()
                or any(not 33 <= ord(c) <= 126 for c in presented)):
            raise HTTPException(status_code=401, detail="invalid bearer key",
                                headers={"WWW-Authenticate": "Bearer"})
        for token, (name, scopes) in self.index.items():
            if hmac.compare_digest(token, presented):
                if scope not in scopes:
                    raise HTTPException(status_code=403,
                                        detail=f"key '{name}' lacks scope '{scope}'")
                return name
        raise HTTPException(status_code=401, detail="unknown key",
                            headers={"WWW-Authenticate": "Bearer"})


TOKENS = Tokens()


def auth_guard(scope: str):
    """FastAPI dependency factory: guard(scope) -> producer name."""
    def guard(authorization: Annotated[str | None, Header()] = None) -> str:
        return TOKENS.check(authorization, scope)
    guard.__name__ = f"auth_guard_{scope}"
    return guard


# ------------------------------------------------------------------------ db
def dsn() -> str:
    pw = Path(PGPASSWORD_FILE).read_text(encoding="utf-8").strip()
    return f"host={PGHOST} port={PGPORT} dbname={PGDATABASE} user={PGUSER} password={pw}"


POOL = None  # psycopg_pool.ConnectionPool, opened in lifespan


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global POOL
    from psycopg_pool import ConnectionPool
    TOKENS.load()
    POOL = ConnectionPool(dsn(), name="ingest", min_size=1, max_size=4)
    POOL.wait(timeout=30.0)
    log.info("postgres pool ready (%s@%s/%s)", PGUSER, PGHOST, PGDATABASE)
    yield
    if POOL is not None:
        POOL.close()
    log.info("shutdown complete")


def db() -> Any:
    if POOL is None:
        raise HTTPException(status_code=503, detail="connection pool not open")
    with POOL.connection() as conn:
        yield conn


# Finalize the transaction before FastAPI sends a successful response.
# Request-scoped yield cleanup runs too late to report a failed commit.
DbDep = Annotated[Any, Depends(db, scope="function")]


def resolve_asset(cur, uid: str) -> int:
    cur.execute("SELECT id FROM ops.assets WHERE asset_uid = %s", (uid,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=422, detail=(
            f"asset '{uid}' is not on record — POST it first (services, "
            "software and findings reference registered assets)"))
    return row[0]


def resolve_service(cur, uid: str, asset_id: int | None = None) -> int:
    # Hold the service's parent stable until the finding transaction finishes.
    cur.execute("SELECT id, asset_id FROM ops.services WHERE service_uid = %s FOR SHARE",
                (uid,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=422, detail=(
            f"service '{uid}' is not on record — POST it first"))
    if asset_id is not None and row[1] != asset_id:
        raise HTTPException(status_code=422,
                            detail="finding service does not belong to the supplied asset")
    return row[0]


def run_upsert(conn, sql: str, params: dict) -> tuple[int, bool]:
    """Execute one upsert; map FK violations to 422. Returns (id, created)."""
    with conn.cursor() as cur:
        try:
            cur.execute(sql, params)
        except psycopg.errors.ForeignKeyViolation as exc:
            raise HTTPException(status_code=422,
                                detail="referenced record missing or parent operation rejected") from exc
        except psycopg.errors.UniqueViolation as exc:  # lost an insert race
            raise HTTPException(status_code=409, detail=(
                "concurrent write on the same key; retry with the same payload")) from exc
        row = cur.fetchone()
    return int(row[0]), bool(row[1])


def audit(cur, producer: str, action: str, entity_type: str,
          entity_id: str, extra: dict[str, Any]) -> None:
    """One audit record per accepted write, same transaction, append-only."""
    cur.execute(
        """
        INSERT INTO ops.audit_events
            (actor_kind, actor, action, entity_type, entity_id, details)
        VALUES ('collector', %(actor)s, %(action)s, %(etype)s, %(eid)s, %(det)s)
        """,
        {"actor": f"ingest-api:{producer}", "action": action,
         "etype": entity_type, "eid": entity_id,
         "det": Jsonb({"api_version": API_VERSION, "producer": producer, **extra})})


def respond(created: bool, entry_id: int, identity: str) -> JSONResponse:
    return JSONResponse(
        status_code=201 if created else 200,
        content={"api_version": API_VERSION, "created": created,
                 "id": entry_id, "identity": identity})


# --------------------------------------------------------------------- models
class AssetIn(BaseModel):
    asset_uid: str = Field(pattern=UID_RE)
    kind: Literal["host", "vm", "container", "network_device", "appliance",
                  "site", "cluster", "cloud_account", "storage", "database",
                  "application"]
    name: str = Field(min_length=1, max_length=200)
    environment: Literal["lab", "staging", "production", "dmz", "management"] = "lab"
    exposure: Literal["internal", "edge_exposed", "public"] = "internal"
    criticality: Literal["tier1", "tier2", "tier3", "tier4"] = "tier3"
    lifecycle: Literal["planned", "active", "decommissioning",
                       "decommissioned"] = "active"
    source: Literal["discovered", "imported", "declared"] = "discovered"
    owner_team: str | None = None
    platform: str | None = None
    provider: str | None = None
    parent_asset_uid: str | None = Field(default=None, pattern=UID_RE)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class ServiceEndpoint(BaseModel):
    proto: str = Field(default="tcp", min_length=1, max_length=16)
    port: int = Field(ge=1, le=65535)
    addr: str = Field(default="", max_length=100)


class ServiceIn(BaseModel):
    service_uid: str = Field(pattern=UID_RE)
    asset_uid: str = Field(pattern=UID_RE)
    name: str = Field(min_length=1, max_length=200)
    kind: str | None = None            # 'web_app','database','api','proxy',...
    exposure: Literal["internal", "edge_exposed", "public"] | None = None   # NULL = inherit
    endpoints: list[ServiceEndpoint] = Field(default_factory=list)
    owner_team: str | None = None
    tags: list[str] = Field(default_factory=list)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class SoftwareIn(BaseModel):
    asset_uid: str = Field(pattern=UID_RE)
    product: str = Field(min_length=1, max_length=200)
    vendor: str = Field(min_length=1, max_length=100)   # part of the UNIQUE key
    version: str = Field(min_length=1, max_length=100)  # part of the UNIQUE key
    cpe: str | None = None             # cpe:2.3:*:... canonical correlation key
    purl: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: datetime | None = None


class FindingIn(BaseModel):
    source: str = Field(min_length=2, max_length=64)    # adapter id
    rule_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    severity: Literal["informational", "low", "medium", "high", "critical"]
    asset_uid: str | None = Field(default=None, pattern=UID_RE)
    service_uid: str | None = Field(default=None, pattern=UID_RE)
    evidence: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
    first_detected_at: datetime | None = None
    last_detected_at: datetime | None = None

    @model_validator(mode="after")
    def target_required(self) -> "FindingIn":
        if not self.asset_uid and not self.service_uid:
            raise ValueError("finding must target an asset and/or a service")
        return self


# ------------------------------------------------------------------------ app
app = FastAPI(title="AI-SecOps ingest API", version=API_VERSION, lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness — never fails on auth/config; reports posture instead."""
    auth = "ok" if TOKENS.index else "missing"
    db_ok = False
    try:
        if POOL is not None:
            with POOL.connection() as conn:
                conn.execute("SELECT 1")
                db_ok = True
    except Exception:
        pass
    return {"api_version": API_VERSION, "auth": auth,
            "db": "ok" if db_ok else "unreachable",
            "status": "ok" if auth == "ok" and db_ok else "degraded"}


@app.get("/readyz")
def readyz() -> dict:
    """Readiness requires configured keys and an answering Postgres pool."""
    if not TOKENS.index:
        raise HTTPException(status_code=503, detail="ingest keys not configured")
    try:
        if POOL is None:
            raise RuntimeError("pool not open")
        with POOL.connection() as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        # Driver errors can contain connection details; never expose them.
        raise HTTPException(status_code=503, detail="postgres unavailable") from exc
    return {"api_version": API_VERSION, "auth": "ok", "db": "ok", "status": "ready"}


# --------------------------------------------------------------------- assets
guard_assets = auth_guard("assets")
guard_services = auth_guard("services")
guard_software = auth_guard("software")
guard_findings = auth_guard("findings")

ASSET_SQL = """
INSERT INTO ops.assets
    (asset_uid, kind, name, environment, exposure, criticality, lifecycle,
     source, owner_team, platform, provider, parent_id, tags, metadata,
     first_seen_at, last_seen_at)
VALUES
    (%(u)s, %(k)s, %(n)s, %(en)s, %(ex)s, %(cr)s, %(lc)s, %(so)s,
     %(ot)s, %(pf)s, %(pv)s, %(pa)s, %(tg)s, %(md)s,
     COALESCE(%(fs)s, now()), COALESCE(%(ls)s, now()))
ON CONFLICT (asset_uid) DO UPDATE SET
    kind = EXCLUDED.kind,
    name = EXCLUDED.name,
    environment = EXCLUDED.environment,
    exposure = EXCLUDED.exposure,
    criticality = EXCLUDED.criticality,
    lifecycle = EXCLUDED.lifecycle,
    -- 'source' is first-wins: it records how the asset ENTERED the registry
    owner_team = COALESCE(EXCLUDED.owner_team, ops.assets.owner_team),
    platform   = COALESCE(EXCLUDED.platform,   ops.assets.platform),
    provider   = COALESCE(EXCLUDED.provider,   ops.assets.provider),
    parent_id  = COALESCE(EXCLUDED.parent_id,  ops.assets.parent_id),
    tags = EXCLUDED.tags,
    metadata = EXCLUDED.metadata,
    first_seen_at = LEAST(ops.assets.first_seen_at,
                          COALESCE(EXCLUDED.first_seen_at,
                                   ops.assets.first_seen_at)),
    last_seen_at  = GREATEST(ops.assets.last_seen_at,
                             COALESCE(EXCLUDED.last_seen_at,
                                      ops.assets.last_seen_at))
RETURNING id, (xmax::text = '0') AS created
"""


@app.post("/api/v1/assets")
def upsert_asset(body: AssetIn, conn: DbDep,
                 producer: Annotated[str, Depends(guard_assets)]) -> JSONResponse:
    parent_id = None
    if body.parent_asset_uid:
        if body.parent_asset_uid == body.asset_uid:
            raise HTTPException(status_code=422,
                                detail="parent asset_uid equals the asset itself")
        with conn.cursor() as cur:
            parent_id = resolve_asset(cur, body.parent_asset_uid)
    entry_id, created = run_upsert(conn, ASSET_SQL, {
        "u": body.asset_uid, "k": body.kind, "n": body.name,
        "en": body.environment, "ex": body.exposure, "cr": body.criticality,
        "lc": body.lifecycle, "so": body.source, "ot": body.owner_team,
        "pf": body.platform, "pv": body.provider, "pa": parent_id,
        "tg": body.tags, "md": Jsonb(body.metadata),
        "fs": body.first_seen_at, "ls": body.last_seen_at})
    with conn.cursor() as cur:
        audit(cur, producer, "created" if created else "updated", "asset",
              body.asset_uid, {"id": entry_id})
    return respond(created, entry_id, body.asset_uid)


# ------------------------------------------------------------------- services
SERVICE_SQL = """
INSERT INTO ops.services
    (service_uid, asset_id, name, kind, exposure, endpoints, owner_team, tags,
     first_seen_at, last_seen_at)
VALUES
    (%(u)s, %(ai)s, %(n)s, %(k)s, %(ex)s, %(ep)s, %(ot)s, %(tg)s,
     COALESCE(%(fs)s, now()), COALESCE(%(ls)s, now()))
ON CONFLICT (service_uid) DO UPDATE SET
    asset_id = EXCLUDED.asset_id,
    name = EXCLUDED.name,
    kind = COALESCE(EXCLUDED.kind, ops.services.kind),
    exposure = EXCLUDED.exposure,
    endpoints = EXCLUDED.endpoints,
    owner_team = COALESCE(EXCLUDED.owner_team, ops.services.owner_team),
    tags = EXCLUDED.tags,
    first_seen_at = LEAST(ops.services.first_seen_at,
                          COALESCE(EXCLUDED.first_seen_at,
                                   ops.services.first_seen_at)),
    last_seen_at  = GREATEST(ops.services.last_seen_at,
                             COALESCE(EXCLUDED.last_seen_at,
                                      ops.services.last_seen_at))
RETURNING id, (xmax::text = '0') AS created
"""


@app.post("/api/v1/services")
def upsert_service(body: ServiceIn, conn: DbDep,
                   producer: Annotated[str, Depends(guard_services)]) -> JSONResponse:
    with conn.cursor() as cur:
        asset_id = resolve_asset(cur, body.asset_uid)
    entry_id, created = run_upsert(conn, SERVICE_SQL, {
        "u": body.service_uid, "ai": asset_id, "n": body.name, "k": body.kind,
        "ex": body.exposure, "ep": Jsonb([e.model_dump() for e in body.endpoints]),
        "ot": body.owner_team, "tg": body.tags,
        "fs": body.first_seen_at, "ls": body.last_seen_at})
    with conn.cursor() as cur:
        audit(cur, producer, "created" if created else "updated", "service",
              body.service_uid, {"id": entry_id, "asset_uid": body.asset_uid})
    return respond(created, entry_id, body.service_uid)


# -------------------------------------------------------------------- software
SOFTWARE_SQL = """
INSERT INTO ops.asset_software
    (asset_id, product, vendor, version, cpe, purl, evidence, last_seen_at)
VALUES
    (%(ai)s, %(pr)s, %(ve)s, %(v)s, %(cp)s, %(pl)s, %(ev)s,
     COALESCE(%(ls)s, now()))
ON CONFLICT (asset_id, product, vendor, version) DO UPDATE SET
    cpe = COALESCE(EXCLUDED.cpe, ops.asset_software.cpe),
    purl = COALESCE(EXCLUDED.purl, ops.asset_software.purl),
    evidence = EXCLUDED.evidence,
    last_seen_at = GREATEST(ops.asset_software.last_seen_at,
                            COALESCE(EXCLUDED.last_seen_at,
                                     ops.asset_software.last_seen_at))
RETURNING id, (xmax::text = '0') AS created
"""


@app.post("/api/v1/software")
def upsert_software(body: SoftwareIn, conn: DbDep,
                    producer: Annotated[str, Depends(guard_software)]) -> JSONResponse:
    with conn.cursor() as cur:
        asset_id = resolve_asset(cur, body.asset_uid)
    entry_id, created = run_upsert(conn, SOFTWARE_SQL, {
        "ai": asset_id, "pr": body.product, "ve": body.vendor, "v": body.version,
        "cp": body.cpe, "pl": body.purl, "ev": Jsonb(body.evidence),
        "ls": body.last_seen_at})
    identity = f"{body.asset_uid}|{body.vendor}|{body.product}|{body.version}"
    with conn.cursor() as cur:
        audit(cur, producer, "created" if created else "updated", "asset_software",
              identity, {"id": entry_id, "asset_uid": body.asset_uid})
    return respond(created, entry_id, identity)


# -------------------------------------------------------------------- findings
FINDING_SQL = """
INSERT INTO ops.findings
    (fingerprint, source, rule_id, title, description, severity, asset_id,
     service_id, evidence, raw, first_detected_at, last_detected_at)
VALUES
    (%(fp)s, %(so)s, %(ru)s, %(ti)s, %(de)s, %(se)s, %(ai)s, %(si)s,
     %(ev)s, %(rw)s, %(fd)s, %(ld)s)
ON CONFLICT (fingerprint) DO UPDATE SET
    description = COALESCE(EXCLUDED.description, ops.findings.description),
    severity = EXCLUDED.severity,
    evidence = EXCLUDED.evidence,
    raw = EXCLUDED.raw,
    last_detected_at = GREATEST(ops.findings.last_detected_at,
                                EXCLUDED.last_detected_at)
RETURNING id, (xmax::text = '0') AS created
"""


@app.post("/api/v1/findings")
def upsert_finding(body: FindingIn, conn: DbDep,
                   producer: Annotated[str, Depends(guard_findings)]) -> JSONResponse:
    with conn.cursor() as cur:
        asset_id = resolve_asset(cur, body.asset_uid) if body.asset_uid else None
        service_id = (resolve_service(cur, body.service_uid, asset_id)
                      if body.service_uid else None)
    targets = [t for t in (f"asset:{body.asset_uid}" if body.asset_uid else None,
                           f"service:{body.service_uid}" if body.service_uid else None) if t]
    fingerprint = hashlib.sha256(
        "|".join([body.source, body.rule_id, "/".join(targets), body.title]).encode()
    ).hexdigest()
    entry_id, created = run_upsert(conn, FINDING_SQL, {
        "fp": fingerprint, "so": body.source, "ru": body.rule_id, "ti": body.title,
        "de": body.description, "se": body.severity, "ai": asset_id, "si": service_id,
        "ev": Jsonb(body.evidence), "rw": Jsonb(body.raw),
        "fd": body.first_detected_at, "ld": body.last_detected_at})
    with conn.cursor() as cur:
        audit(cur, producer, "created" if created else "updated", "finding",
              fingerprint, {"id": entry_id, "source": body.source,
                            "rule_id": body.rule_id, "targets": targets})
    return respond(created, entry_id, fingerprint)
