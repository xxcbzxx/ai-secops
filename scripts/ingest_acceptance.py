#!/usr/bin/env python3
"""AI-SecOps ingest acceptance drill (Phase 2, workstream 2.2).

Runs INSIDE the ingest-api container (only it can hold the operator's token
without printing it, and probe the API as a client would):

    docker compose --env-file .env --profile api exec -T ingest-api \
        python /app/scripts/ingest_acceptance.py

What it proves (exit 0 = accepted; 2 = an invariant failed):
  A AUTH        healthz/readyz open; missing key -> 401; unknown key -> 401;
                key without the endpoint scope -> 403.
  B IDEMPOTENCY same POST twice -> 201 then 200 with the SAME id.
  C INTEGRITY   bad payloads -> 422 with NO row written; unknown parents
                (asset/service) -> 422.
  D REALITY     rows + one audit record per accepted write, matching counts.
  E TEARDOWN    drill rows are deleted again; audit rows remain (append-only).
Re-running is safe: prior drill rows are cleaned first.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psycopg

BASE = os.environ.get("ACCEPT_BASE", "http://127.0.0.1:8000")
TOKEN_FILE = os.environ.get("INGEST_TOKENS_FILE", "/run/secrets/ingest_tokens")
SCOPES_ALL = ("assets", "services", "software", "findings")

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"OK    {msg}")


def expect(cond: bool, msg: str) -> None:
    if cond:
        ok(msg)
    else:
        failures.append(msg)
        print(f"FAIL  {msg}")


def call(method: str, path: str, payload=None, token=None) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, (json.loads(raw) if raw else {})
        except ValueError:
            return exc.code, {"raw": raw.decode("utf-8", "replace")[:400]}


# ---- keys: full-scope key for writes, limited key for the 403 negative test
full = limited = None
for raw in Path(TOKEN_FILE).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    parts = line.split(":")
    if len(parts) != 3:
        continue
    _name, token, scopes = parts
    sc = frozenset(scopes.replace(",", " ").split())
    if set(SCOPES_ALL) <= sc and full is None:
        full = token
    if sc and sc < set(SCOPES_ALL) and limited is None:
        limited = token

ASSET_UID = "tap-accept-001"
SERVICE_UID = "tap-accept-001-svc"
RUN_TAG = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

ASSET = {"asset_uid": ASSET_UID, "kind": "vm", "name": "Acceptance canary (2.2)",
         "environment": "lab", "exposure": "internal", "criticality": "tier3",
         "lifecycle": "active", "source": "declared", "owner_team": "platform",
         "provider": "ingest-acceptance", "tags": ["ingest-acceptance"],
         "metadata": {"run": RUN_TAG}}
SERVICE = {"service_uid": SERVICE_UID, "asset_uid": ASSET_UID,
           "name": "Acceptance canary service", "kind": "web_app",
           "tags": ["ingest-acceptance"],
           "endpoints": [{"proto": "tcp", "port": 5900, "addr": "10.0.0.9"}]}
SOFTWARE = {"asset_uid": ASSET_UID, "product": "openssl", "vendor": "openssl",
            "version": "3.5.4", "purl": "pkg:generic/openssl@3.5.4",
            "evidence": {"how": "dpkg"}}
FINDING = {"source": "acceptance-canary", "rule_id": "2.2.canary",
           "title": "Ingest acceptance canary finding", "severity": "low",
           "asset_uid": ASSET_UID, "evidence": {"run": RUN_TAG},
           "raw": {"drill": "2.2"}}
EXPECTED_FP = hashlib.sha256("|".join(
    ["acceptance-canary", "2.2.canary", f"asset:{ASSET_UID}", FINDING["title"]]).
    encode()).hexdigest()


def dconn() -> psycopg.Connection:
    pw_path = os.environ.get("PGPASSWORD_FILE", "/run/secrets/pg_ingest_password")
    pw = Path(pw_path).read_text(encoding="utf-8").strip()
    return psycopg.connect(
        f"host={os.environ.get('PGHOST', 'postgres')} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ.get('PGDATABASE', 'ai_secops')} "
        f"user={os.environ.get('PGUSER', 'ai_secops_ingest')} password={pw}")


def cleanup(cur) -> None:
    """Remove drill rows; findings first (no cascade), asset cascades the rest."""
    cur.execute("DELETE FROM ops.findings WHERE source = 'acceptance-canary'")
    cur.execute("DELETE FROM ops.services WHERE service_uid = %s", (SERVICE_UID,))
    cur.execute("DELETE FROM ops.asset_software WHERE asset_id = "
                "(SELECT id FROM ops.assets WHERE asset_uid = %s)", (ASSET_UID,))
    cur.execute("DELETE FROM ops.assets WHERE asset_uid = %s", (ASSET_UID,))


def audit_count(cur, eid: str) -> int:
    cur.execute("SELECT count(*) FROM ops.audit_events WHERE entity_id = %s", (eid,))
    return int(cur.fetchone()[0])


def main() -> int:
    print(f"== AI-SecOps ingest acceptance — {BASE} (run {RUN_TAG}) ==")
    if full is None:
        print("FAIL  no token covering all four scopes in the tokens file")
        return 2

    # ---- A: open probes + auth negatives -----------------------------------
    code, body = call("GET", "/healthz")
    expect(code == 200 and body.get("status") == "ok",
           f"healthz open: {body.get('status')}/{body.get('auth')}/{body.get('db')}")
    code, body = call("GET", "/readyz")
    expect(code == 200 and body.get("status") == "ready", "readyz: db pool live")

    code, _ = call("POST", "/api/v1/assets", ASSET)
    expect(code == 401, "no Authorization header -> 401")
    code, _ = call("POST", "/api/v1/assets", ASSET, token="not-a-real-key")
    expect(code == 401, "unknown key -> 401")
    if limited:
        code, _ = call("POST", "/api/v1/assets", ASSET, token=limited)
        expect(code == 403, "key without 'assets' scope -> 403")
    else:
        print("WARN  no limited-scope key in tokens file; 403 case not exercised")

    # ---- clean slate --------------------------------------------------------
    with dconn() as conn, conn.cursor() as cur:
        cleanup(cur)

    # ---- B/C: happy path + idempotency + integrity ---------------------------
    code, body = call("POST", "/api/v1/assets", ASSET, token=full)
    expect(code == 201 and body.get("created") is True,
           f"asset -> 201 created (id={body.get('id')})")
    asset_id = body.get("id")
    code, body = call("POST", "/api/v1/assets", ASSET, token=full)
    expect(code == 200 and body.get("created") is False
           and body.get("id") == asset_id, "asset re-POST -> 200, same id")

    code, body = call("POST", "/api/v1/services", SERVICE, token=full)
    expect(code == 201 and body.get("created") is True, "service -> 201 created")
    svc_id = body.get("id")
    code, body = call("POST", "/api/v1/services", SERVICE, token=full)
    expect(code == 200 and body.get("id") == svc_id, "service re-POST -> 200, same id")
    code, _ = call("POST", "/api/v1/services",
                   {**SERVICE, "service_uid": "tap-accept-001-x",
                    "asset_uid": "no-such-asset"}, token=full)
    expect(code == 422, "service on unknown asset -> 422")

    code, _ = call("POST", "/api/v1/software",
                   {**SOFTWARE, "asset_uid": "no-such-asset"}, token=full)
    expect(code == 422, "software on unknown asset -> 422")
    code, body = call("POST", "/api/v1/software", SOFTWARE, token=full)
    expect(code == 201 and body.get("created") is True, "software -> 201 created")
    code, body = call("POST", "/api/v1/software", SOFTWARE, token=full)
    expect(code == 200 and body.get("created") is False, "software re-POST -> 200")

    code, body = call("POST", "/api/v1/findings", FINDING, token=full)
    expect(code == 201 and body.get("identity") == EXPECTED_FP,
           "finding -> 201, fingerprint matches sha256 contract")
    fp = body.get("identity")
    code, body = call("POST", "/api/v1/findings", FINDING, token=full)
    expect(code == 200 and body.get("id") == body.get("id") and fp == body.get("identity"),
           "finding re-POST -> 200, same fingerprint")

    code, _ = call("POST", "/api/v1/findings",
                   {**FINDING, "severity": "catastrophic"}, token=full)
    expect(code == 422, "bad severity -> 422")
    code, _ = call("POST", "/api/v1/findings",
                   {**FINDING, "asset_uid": None, "service_uid": None}, token=full)
    expect(code == 422, "finding with no target -> 422")
    code, _ = call("POST", "/api/v1/findings",
                   {**FINDING, "service_uid": "no-such-service"}, token=full)
    expect(code == 422, "finding on unknown service -> 422")
    code, _ = call("POST", "/api/v1/assets",
                   {**ASSET, "asset_uid": "TAP-BAD-UID"}, token=full)
    expect(code == 422, "malformed asset_uid -> 422")

    # ---- D: rows + audit reality checks --------------------------------------
    with dconn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ops.assets WHERE asset_uid = %s", (ASSET_UID,))
        expect(cur.fetchone()[0] == 1, "db: asset row exists")
        cur.execute("SELECT count(*) FROM ops.asset_software WHERE asset_id = %s",
                    (asset_id,))
        expect(cur.fetchone()[0] == 1, "db: software row exists")
        cur.execute("SELECT count(*) FROM ops.audit_events "
                    "WHERE entity_id = %s AND entity_type = 'asset'", (ASSET_UID,))
        expect(cur.fetchone()[0] == 2, "db: 2 audit records for asset (created+updated)")
        cur.execute("SELECT count(*) FROM ops.audit_events "
                    "WHERE entity_id = %s AND entity_type = 'finding'", (fp,))
        expect(cur.fetchone()[0] == 2, "db: 2 audit records for finding (created+updated)")
        cur.execute("SELECT count(*) FROM ops.findings WHERE fingerprint = %s", (fp,))
        expect(cur.fetchone()[0] == 1, "db: exactly one finding row (no duplicates)")

    # ---- E: teardown -----------------------------------------------------------
    with dconn() as conn, conn.cursor() as cur:
        cleanup(cur)
    with dconn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ops.assets WHERE asset_uid = %s", (ASSET_UID,))
        expect(cur.fetchone()[0] == 0, "teardown: drill rows removed, audit trail kept")

    if failures:
        print(f"✗ ACCEPTANCE FAILED — {len(failures)} failed expectation(s)")
        return 2
    print("✓ ACCEPTANCE OK — ingest contract v1 verified end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
