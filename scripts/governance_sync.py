#!/usr/bin/env python3
"""AI-SecOps governance sync — filesystem store adapter v1 (Phase 2, 2.1).

Projects the validated governance artifact tree into the gov.* schema
(ADR-001: the Git/store tree is the source of truth; the database is a
projection maintained by THIS job — the only writer of gov.* rows).

Product invariants (docs/architecture.md, ADR-002):
  * VALIDATE FIRST   — any artifact that fails its JSON Schema, or the
    referential check, aborts the run BEFORE a single row is written (same
    contracts as CI).
  * UPSERT ONLY      — gov.* rows are never deleted by sync (drop-loss
    protection); orphans are reported as drift, never removed.
  * PROVENANCE       — every row carries source_path, content_sha256 and, when
    the tree is a git checkout, the HEAD commit of that sync.
  * IDEMPOTENT       — running twice converges to the same rows; each run
    updates ops.sync_state (one row per store) and records an audit event.

Usage (T1, on the stack host):
    docker compose --env-file .env --profile sync run --rm governance-sync
Validation-only (no DB writes, CI/hook friendliness):
    docker compose run --rm governance-sync --check
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import jsonschema
    import yaml
    from psycopg import connect
    from psycopg.types.json import Jsonb
except ModuleNotFoundError as exc:  # pragma: no cover - container bakes deps
    sys.exit(f"governance-sync: missing dependency {exc.name} (expected baked in image)")

ROOT = Path(os.environ.get("GOV_ROOT", "/governance")).resolve()
STORE_ID = os.environ.get("STORE_ID", "main")

# class prefix, folder, schema file — projection order respects the FK graph
# of 002-schema.sql: exceptions rows reference policies AND risks, so EX is
# written last (single transaction aborts everything on violation).
PAIRS = [
    ("POL", "policies", "policy.schema.json"),
    ("RSK", "risks", "risk.schema.json"),
    ("STD", "standards", "standard.schema.json"),
    ("ADR", "architecture", "adr.schema.json"),
    ("CTL", "controls", "compensating-control.schema.json"),
    ("EX", "exceptions", "exception.schema.json"),
]


def to_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def git_state() -> tuple[str | None, str]:
    """(head_commit, branch) — degrades gracefully when git or .git are absent.

    The job container deliberately ships WITHOUT the git binary, so the HEAD
    commit is read directly from .git files when available (loose or packed).
    """
    gitdir = ROOT / ".git"
    if shutil.which("git") is None:
        head_file = gitdir / "HEAD"
        if not head_file.is_file():
            return None, "main"
        text = head_file.read_text(encoding="utf-8").strip()
        if text.startswith("ref:"):
            ref = text[4:].strip()
            branch = ref.rsplit("/", 1)[-1] or "main"
            loose = gitdir / ref
            if loose.is_file():
                return loose.read_text(encoding="utf-8").strip() or None, branch
            packed = gitdir / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref:
                        return parts[0], branch
            return None, branch
        return (text or None), "main"

    def run(*args: str) -> str:
        try:
            p = subprocess.run(["git", "-C", str(ROOT), *args],
                               capture_output=True, text=True, timeout=15)
            return (p.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""
    head = run("rev-parse", "HEAD") or None
    branch = run("branch", "--show-current") or "main"   # detached/absent git
    return head, branch


def referential_check() -> tuple[int, str] | None:
    """Reuse scripts/check_references.py against the mounted tree (CI parity)."""
    script = ROOT / "scripts" / "check_references.py"
    if not script.exists():
        return None
    try:
        p = subprocess.run([sys.executable, str(script)],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.returncode, (p.stdout + p.stderr).strip()


def load_and_validate() -> tuple[list[tuple[str, Path, dict]], list[str]]:
    """Parse + schema-validate every artifact; abort-only contract."""
    artifacts: list[tuple[str, Path, dict]] = []
    errors: list[str] = []
    for prefix, folder, schema_file in PAIRS:
        schema = json.loads((ROOT / "schemas" / schema_file).read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for f in sorted((ROOT / folder).glob("*.yaml")):
            rel = f.relative_to(ROOT).as_posix()
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                errors.append(f"{rel}: YAML parse error: {str(exc).replace(chr(10), ' | ')[:180]}")
                continue
            if not isinstance(doc, dict):
                errors.append(f"{rel}: not a mapping")
                continue
            bad = [e.message for e in sorted(
                validator.iter_errors(doc), key=lambda e: list(e.absolute_path))]
            if bad:
                errors.append(f"{rel}: " + " | ".join(m[:120] for m in bad[:3]))
                continue
            artifacts.append((prefix, f, doc))
    return artifacts, errors


def provenance(artifacts: list[tuple[str, Path, dict]], head: str | None) -> list[dict]:
    prov = []
    for prefix, path, _doc in artifacts:
        blob = path.read_bytes()
        prov.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "commit": head,
        })
    return prov


# --------------------------------------------------------------------------
# projections — one (sql, params) per artifact class; mirrors 002-schema.sql
# --------------------------------------------------------------------------
def J(obj):
    return Jsonb(obj)


def proj_policy(doc: dict, p: dict) -> tuple[str, dict]:
    sql = """
        INSERT INTO gov.policies (policy_uid, version, title, category,
            authority, owner, review_cadence, effective_from, review_due,
            approved_by, statement, scope, requirement, control_refs, related,
            state, supersedes, source_path, source_commit, content_sha256,
            synced_at)
        VALUES (%(u)s, %(v)s, %(t)s, %(cat)s, %(au)s, %(ow)s, %(cad)s, %(ef)s,
            %(rd)s, %(ab)s, %(stm)s, %(sc)s, %(rq)s, %(cr)s, %(rel)s, %(st)s,
            %(sp)s, %(pth)s, %(cm)s, %(sh)s, now())
        ON CONFLICT (policy_uid) DO UPDATE SET
            version=EXCLUDED.version, title=EXCLUDED.title,
            category=EXCLUDED.category, authority=EXCLUDED.authority,
            owner=EXCLUDED.owner, review_cadence=EXCLUDED.review_cadence,
            effective_from=EXCLUDED.effective_from,
            review_due=EXCLUDED.review_due,
            approved_by=EXCLUDED.approved_by, statement=EXCLUDED.statement,
            scope=EXCLUDED.scope, requirement=EXCLUDED.requirement,
            control_refs=EXCLUDED.control_refs, related=EXCLUDED.related,
            state=EXCLUDED.state, supersedes=EXCLUDED.supersedes,
            source_commit=EXCLUDED.source_commit,
            content_sha256=EXCLUDED.content_sha256,
            synced_at=now(), updated_at=now()"""
    return sql, dict(
        u=doc["id"], v=doc["version"], t=doc["title"], cat=doc["category"],
        au=doc["authority"], ow=doc["owner"],
        cad=doc.get("review_cadence") or "annual",
        ef=to_date(doc.get("effective_from")), rd=to_date(doc.get("review_due")),
        ab=J(doc.get("approved_by") or []), stm=doc["statement"],
        sc=J(doc.get("scope") or {}), rq=J(doc.get("requirement") or {}),
        cr=J(doc.get("control_refs") or []), rel=J(doc.get("related") or {}),
        st=doc["state"], sp=doc.get("supersedes") or None,
        pth=p["path"], cm=p["commit"], sh=p["sha256"])


def proj_exception(doc: dict, p: dict) -> tuple[str, dict]:
    sql = """
        INSERT INTO gov.exceptions (exception_uid, version, title, policy_uid,
            policy_version, risk_uid, requested_by, requested_at, status,
            valid_from, valid_to, review_before, justification, conditions,
            compensating_controls, scope, approvers, source_path,
            source_commit, content_sha256, synced_at)
        VALUES (%(u)s, %(v)s, %(t)s, %(pu)s, %(pv)s, %(ru)s, %(rb)s, %(ra)s,
            %(st)s, %(vf)s, %(vt)s, %(rv)s, %(ju)s, %(co)s, %(ck)s, %(sc)s,
            %(ap)s, %(pth)s, %(cm)s, %(sh)s, now())
        ON CONFLICT (exception_uid) DO UPDATE SET
            version=EXCLUDED.version, title=EXCLUDED.title,
            policy_uid=EXCLUDED.policy_uid,
            policy_version=EXCLUDED.policy_version,
            risk_uid=EXCLUDED.risk_uid, requested_by=EXCLUDED.requested_by,
            requested_at=EXCLUDED.requested_at, status=EXCLUDED.status,
            valid_from=EXCLUDED.valid_from, valid_to=EXCLUDED.valid_to,
            review_before=EXCLUDED.review_before,
            justification=EXCLUDED.justification,
            conditions=EXCLUDED.conditions,
            compensating_controls=EXCLUDED.compensating_controls,
            scope=EXCLUDED.scope, approvers=EXCLUDED.approvers,
            source_commit=EXCLUDED.source_commit,
            content_sha256=EXCLUDED.content_sha256,
            synced_at=now(), updated_at=now()"""
    return sql, dict(
        u=doc["id"], v=doc["version"], t=doc["title"],
        pu=doc["policy_ref"]["id"],
        pv=str((doc.get("policy_ref") or {}).get("version") or ""),
        ru=doc["risk_ref"]["id"], rb=J(doc.get("requested_by") or {}),
        ra=to_date(doc.get("requested_at")), st=doc["status"],
        vf=to_date(doc.get("valid_from")), vt=to_date(doc.get("valid_to")),
        rv=to_date(doc.get("review_before")), ju=doc["justification"],
        co=[str(x) for x in (doc.get("conditions") or [])],
        ck=[str(x) for x in (doc.get("compensating_controls") or [])],
        sc=J(doc.get("scope") or {}), ap=J(doc.get("approvers") or []),
        pth=p["path"], cm=p["commit"], sh=p["sha256"])


def proj_risk(doc: dict, p: dict) -> tuple[str, dict]:
    sql = """
        INSERT INTO gov.risks (risk_uid, version, title, status, category,
            owner, description, asset_refs, service_refs, assessment,
            threat_statements, existing_controls, mitigation_plan, residual,
            appetite, appetite_note, acceptance, review, related, source_path,
            source_commit, content_sha256, synced_at)
        VALUES (%(u)s, %(v)s, %(t)s, %(st)s, %(cat)s, %(ow)s, %(de)s, %(ar)s,
            %(sr)s, %(asm)s, %(ts)s, %(ec)s, %(mp)s, %(re)s, %(ap)s, %(an)s,
            %(ac)s, %(rv)s, %(rel)s, %(pth)s, %(cm)s, %(sh)s, now())
        ON CONFLICT (risk_uid) DO UPDATE SET
            version=EXCLUDED.version, title=EXCLUDED.title,
            status=EXCLUDED.status, category=EXCLUDED.category,
            owner=EXCLUDED.owner, description=EXCLUDED.description,
            asset_refs=EXCLUDED.asset_refs,
            service_refs=EXCLUDED.service_refs,
            assessment=EXCLUDED.assessment,
            threat_statements=EXCLUDED.threat_statements,
            existing_controls=EXCLUDED.existing_controls,
            mitigation_plan=EXCLUDED.mitigation_plan,
            residual=EXCLUDED.residual, appetite=EXCLUDED.appetite,
            appetite_note=EXCLUDED.appetite_note,
            acceptance=EXCLUDED.acceptance, review=EXCLUDED.review,
            related=EXCLUDED.related, source_commit=EXCLUDED.source_commit,
            content_sha256=EXCLUDED.content_sha256,
            synced_at=now(), updated_at=now()"""
    return sql, dict(
        u=doc["id"], v=doc["version"], t=doc["title"], st=doc["status"],
        cat=doc["category"], ow=doc["owner"], de=doc["description"],
        ar=[str(x) for x in (doc.get("asset_refs") or [])],
        sr=[str(x) for x in (doc.get("service_refs") or [])],
        asm=J(doc.get("assessment") or {}),
        ts=[str(x) for x in (doc.get("threat_statements") or [])],
        ec=J(doc.get("existing_controls") or []),
        mp=J(doc.get("mitigation_plan") or []),
        re=J(doc.get("residual") or {}),
        ap=doc["appetite"], an=doc.get("appetite_note"),
        ac=J(doc.get("acceptance")), rv=J(doc.get("review")),
        rel=J(doc.get("related") or {}), pth=p["path"], cm=p["commit"],
        sh=p["sha256"])


def proj_standard(doc: dict, p: dict) -> tuple[str, dict]:
    sql = """
        INSERT INTO gov.standards (standard_uid, version, title, state, body,
            based_on, summary, applicability, controls, owner, effective_from,
            review, related, source_path, source_commit, content_sha256,
            synced_at)
        VALUES (%(u)s, %(v)s, %(t)s, %(st)s, %(bo)s, %(bno)s, %(sum)s,
            %(ap)s, %(ck)s, %(ow)s, %(ef)s, %(rv)s, %(rel)s, %(pth)s, %(cm)s,
            %(sh)s, now())
        ON CONFLICT (standard_uid) DO UPDATE SET
            version=EXCLUDED.version, title=EXCLUDED.title,
            state=EXCLUDED.state, body=EXCLUDED.body,
            based_on=EXCLUDED.based_on, summary=EXCLUDED.summary,
            applicability=EXCLUDED.applicability, controls=EXCLUDED.controls,
            owner=EXCLUDED.owner, effective_from=EXCLUDED.effective_from,
            review=EXCLUDED.review, related=EXCLUDED.related,
            source_commit=EXCLUDED.source_commit,
            content_sha256=EXCLUDED.content_sha256,
            synced_at=now(), updated_at=now()"""
    return sql, dict(
        u=doc["id"], v=doc["version"], t=doc["title"], st=doc["state"],
        bo=doc["body"], bno=[str(x) for x in (doc.get("based_on") or [])],
        sum=doc["summary"], ap=J(doc.get("applicability") or {}),
        ck=J(doc.get("controls") or []), ow=doc["owner"],
        ef=to_date(doc.get("effective_from")), rv=J(doc.get("review")),
        rel=J(doc.get("related") or {}), pth=p["path"], cm=p["commit"],
        sh=p["sha256"])


def proj_adr(doc: dict, p: dict) -> tuple[str, dict]:
    sql = """
        INSERT INTO gov.adrs (adr_uid, version, title, status, decided_at,
            supersedes, superseded_by, deciders, context, decision,
            options_considered, consequences, related, source_path,
            source_commit, content_sha256, synced_at)
        VALUES (%(u)s, %(v)s, %(t)s, %(st)s, %(da)s, %(ss)s, %(sb)s, %(dc)s,
            %(ctx)s, %(dec)s, %(op)s, %(co)s, %(rel)s, %(pth)s, %(cm)s,
            %(sh)s, now())
        ON CONFLICT (adr_uid) DO UPDATE SET
            version=EXCLUDED.version, title=EXCLUDED.title,
            status=EXCLUDED.status, decided_at=EXCLUDED.decided_at,
            supersedes=EXCLUDED.supersedes,
            superseded_by=EXCLUDED.superseded_by,
            deciders=EXCLUDED.deciders, context=EXCLUDED.context,
            decision=EXCLUDED.decision,
            options_considered=EXCLUDED.options_considered,
            consequences=EXCLUDED.consequences, related=EXCLUDED.related,
            source_commit=EXCLUDED.source_commit,
            content_sha256=EXCLUDED.content_sha256,
            synced_at=now(), updated_at=now()"""
    return sql, dict(
        u=doc["id"], v=doc["version"], t=doc["title"], st=doc["status"],
        da=to_date(doc.get("decided_at")),
        ss=[str(x) for x in (doc.get("supersedes") or [])],
        sb=[str(x) for x in (doc.get("superseded_by") or [])],
        dc=J(doc.get("deciders") or []), ctx=doc["context"],
        dec=doc["decision"],
        op=J(doc.get("options_considered") or []),
        co=J(doc.get("consequences") or {}), rel=J(doc.get("related") or {}),
        pth=p["path"], cm=p["commit"], sh=p["sha256"])


def proj_control(doc: dict, p: dict) -> tuple[str, dict]:
    sql = """
        INSERT INTO gov.controls (control_uid, version, title, status,
            strength, owner, description, covers_risks, supports_exceptions,
            verification, limitations, related, source_path, source_commit,
            content_sha256, synced_at)
        VALUES (%(u)s, %(v)s, %(t)s, %(st)s, %(sk)s, %(ow)s, %(de)s, %(cr)s,
            %(se)s, %(vf)s, %(lm)s, %(rel)s, %(pth)s, %(cm)s, %(sh)s, now())
        ON CONFLICT (control_uid) DO UPDATE SET
            version=EXCLUDED.version, title=EXCLUDED.title,
            status=EXCLUDED.status, strength=EXCLUDED.strength,
            owner=EXCLUDED.owner, description=EXCLUDED.description,
            covers_risks=EXCLUDED.covers_risks,
            supports_exceptions=EXCLUDED.supports_exceptions,
            verification=EXCLUDED.verification,
            limitations=EXCLUDED.limitations, related=EXCLUDED.related,
            source_commit=EXCLUDED.source_commit,
            content_sha256=EXCLUDED.content_sha256,
            synced_at=now(), updated_at=now()"""
    return sql, dict(
        u=doc["id"], v=doc["version"], t=doc["title"], st=doc["status"],
        sk=doc["strength"], ow=doc["owner"], de=doc["description"],
        cr=[str(x) for x in (doc.get("covers_risks") or [])],
        se=[str(x) for x in (doc.get("supports_exceptions") or [])],
        vf=J(doc.get("verification") or {}),
        lm=[str(x) for x in (doc.get("limitations") or [])],
        rel=J(doc.get("related") or {}), pth=p["path"], cm=p["commit"],
        sh=p["sha256"])


PROJECTORS = {
    "POL": proj_policy, "EX": proj_exception, "RSK": proj_risk,
    "STD": proj_standard, "ADR": proj_adr, "CTL": proj_control,
}

# drift detection: every gov projection table's source_path column
DRIFT_TABLES = {
    "POL": "gov.policies", "EX": "gov.exceptions", "RSK": "gov.risks",
    "STD": "gov.standards", "ADR": "gov.adrs", "CTL": "gov.controls",
}


def dsn() -> str:
    host = os.environ.get("PGHOST", "postgres")
    port = os.environ.get("PGPORT", "5432")
    db = os.environ.get("PGDATABASE", "ai_secops")
    user = os.environ.get("PGUSER", "ai_secops")
    pw_path = Path(os.environ.get("PGPASSWORD_FILE", "/run/secrets/pg_password"))
    pw = pw_path.read_text().strip()
    return f"host={host} port={port} dbname={db} user={user} password={pw}"


def main() -> int:
    check_only = "--check" in sys.argv[1:]

    print(f"== AI-SecOps governance sync — filesystem store '{STORE_ID}' ==")
    head, branch = git_state()
    print(f"   tree: {ROOT}")
    print(f"   git:  {'HEAD ' + head if head else 'not a git checkout (source_commit stays NULL)'}")

    artifacts, errors = load_and_validate()
    if errors:
        print("✗ corpus validation failures (nothing will be written):")
        for e in errors:
            print(f"   - {e}")
        print("✗ NOT SYNCED — fix the artifacts first")
        return 2
    print(f"   corpus: {len(artifacts)} artifact(s) schema-valid")

    rc = referential_check()
    if rc is not None and rc[0] != 0:
        print("✗ referential integrity failures (nothing will be written):")
        for line in rc[1].splitlines():
            print(f"   {line}")
        print("✗ NOT SYNCED")
        return 2
    if rc is not None:
        print(f"   references: all resolve ({rc[1].splitlines()[-1].strip()})")

    counts = {p: 0 for p, _, _ in PAIRS}
    for prefix, _f, _doc in artifacts:
        counts[prefix] += 1
    prov = provenance(artifacts, head)

    if check_only:
        print("✓ CHECK OK — corpus is sync-safe (no DB writes in check mode)")
        return 0

    grouped: dict[str, list[tuple[str, dict]]] = {}
    for (prefix, _p, doc), pmeta in zip(artifacts, prov):
        sql, params = PROJECTORS[prefix](doc, pmeta)
        grouped.setdefault(prefix, []).append((sql, params))

    expected = {p: set() for p in PROJECTORS}
    for (prefix, _f, _doc), pmeta in zip(artifacts, prov):
        expected[prefix].add(pmeta["path"])

    conn = None
    for attempt in range(5):
        try:
            conn = connect(dsn(), autocommit=False)
            break
        except Exception as exc:
            if attempt == 4:
                raise
            print(f"   postgres not ready ({str(exc)[:80]}); retrying…")

    drift_reports: list[str] = []
    with conn:
        with conn.transaction():
            for prefix, rows in grouped.items():
                for sql, params in rows:
                    conn.execute(sql, params)
            # drift detector: DB rows whose source_path no longer exists —
            # reported, NEVER deleted (drop-loss protection).
            for prefix, table in DRIFT_TABLES.items():
                got = {r[0] for r in conn.execute(
                    f"SELECT source_path FROM {table}").fetchall()}
                for orphan in sorted(got - expected[prefix]):
                    drift_reports.append(f"{table}: {orphan}")
            n_all = len(artifacts)
            conn.execute(
                """
                INSERT INTO ops.sync_state
                    (store, store_kind, target, branch, head_commit,
                     artifacts, status, error, synced_at)
                VALUES (%(s)s, 'filesystem', %(t)s, %(b)s, %(h)s, %(n)s,
                        'ok', NULL, now())
                ON CONFLICT (store) DO UPDATE SET
                    store_kind='filesystem', target=EXCLUDED.target,
                    branch=EXCLUDED.branch,
                    head_commit=EXCLUDED.head_commit,
                    artifacts=EXCLUDED.artifacts, status='ok', error=NULL,
                    synced_at=now()""",
                {"s": STORE_ID, "t": str(ROOT), "b": branch, "h": head,
                 "n": n_all})
            detail = {"store": STORE_ID, "artifacts": n_all,
                      "by_kind": counts, "drift": drift_reports,
                      "head_commit": head, "branch": branch}
            conn.execute(
                """
                INSERT INTO ops.audit_events
                    (actor_kind, actor, action, entity_type, entity_id, details)
                VALUES ('service', 'governance-sync', 'synced',
                        'governance_plane', %(s)s, %(d)s)""",
                {"s": STORE_ID, "d": J(detail)})

    print("   projection:")
    for prefix, count in counts.items():
        print(f"      {prefix}: {count} upsert(s) ensured")
    if drift_reports:
        print("   drift detected (protected, NOT deleted):")
        for line in drift_reports:
            print(f"      - {line}")
    else:
        print("   drift: none — projection and Git tree match 1:1")
    print(f"   sync_state[{STORE_ID}]: ok | {len(artifacts)} artifact(s) @ "
          f"{head or 'no-git'}")
    print("✓ sync complete — gov.* is a verified projection of the Git corpus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
