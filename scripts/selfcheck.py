#!/usr/bin/env python3
"""AI-SecOps platform self-check — the boot/acceptance gate (Phase 1).

Run ON ai-secops01 after `docker compose up -d`:

    python3 scripts/selfcheck.py            # or with the chat profile loaded too
    python3 scripts/selfcheck.py --json     # machine-readable output

What it checks (the "thing" the platform must verify to call itself ready):

  A. CONTAINERS — every expected service is running and healthy
     (postgres + qdrant mandatory; ollama/openwebui optional by profile).
  B. DATABASE  — the two-plane schema is actually applied:
     schemas gov+ops exist, core tables exist, ops.sync_state has its row,
     least-privilege roles exist.
  C. ISOLATION — no service publishes host ports (Security First rule).
  D. CORPUS    — governance artifacts pass schema validation + referential
     integrity (CI parity, runs on the VM when python3 + deps are present).
  E. BACKUPS   — a pg_dump archive exists in backups/ (drill gate).

   F. INGEST    — generic ingest API healthy, keys configured, least-privilege
      role exists (Phase 2.2; WARN + guide if the `api` profile is off).

Exit code: 0 = ready, 1 = not ready (CI-style). Individual checks degrade to
WARN where appropriate (optional features) but FAIL on core violations.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infrastructure"

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"
results: list[dict] = []


def record(check: str, status: str, detail: str = "") -> bool:
    results.append({"check": check, "status": status, "detail": detail})
    return status != FAIL


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, f"missing binary: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def docker_compose(*args: str) -> tuple[int, str]:
    base = ["docker", "compose", "--env-file", ".env"]
    return run(base + list(args), cwd=INFRA)


def psql(sql: str, db: str = "ai_secops", user: str = "ai_secops") -> tuple[int, str]:
    return docker_compose("exec", "-T", "postgres", "psql", "-U", user, "-d", db, "-Atc", sql)


# --------------------------------------------------------------------------- A
def check_containers() -> bool:
    ok = True
    code, out = docker_compose("ps", "--format", "json", "--all")
    if code != 0:
        return record("A.containers", FAIL, f"docker compose ps failed: {out[:200]}")
    records = []
    for line in out.splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except ValueError as e:
                return record("A.containers", FAIL, f"parse error: {e}")
    services = {
        str(r.get("Service", r.get("Name", f"container-{i}"))): r
        for i, r in enumerate(records)
    }

    mandatory = {"postgres", "qdrant"}
    optional = {"ollama", "openwebui"}
    for name, svc in services.items():
        svc_name = svc.get("Service", name)
        status = str(svc.get("Status", svc.get("State", "")))
        healthy = "healthy" in status.lower() or "running" in status.lower()
        if svc_name in mandatory:
            ok &= record(f"A.container.{svc_name}", OK if healthy else FAIL, status)
        elif svc_name in optional:
            ok &= record(f"A.container.{svc_name}", OK, f"optional loaded: {status}")
    missing = [s for s in mandatory if s not in [svc.get("Service") for svc in services.values()]]
    for m in missing:
        ok &= record(f"A.container.{m}", FAIL, "not running")
    return ok


# --------------------------------------------------------------------------- B
def check_database() -> bool:
    ok = True
    code, out = psql("SELECT count(*) FROM pg_namespace WHERE nspname IN ('gov','ops');")
    if code != 0:
        return record("B.schema", FAIL, f"postgres unreachable: {out[:200]}")
    ok &= record("B.schema", OK if out == "2" else FAIL, f"schemas found: {out}")

    code, out = psql(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema IN ('gov','ops');"
    )
    ok &= record("B.tables", OK if code == 0 and int(out or 0) >= 13 else FAIL,
                 f"tables: {out} (expect ≥ 13 incl. views excluded)")

    code, out = psql("SELECT store, status FROM ops.sync_state LIMIT 1;")
    ok &= record("B.sync_state", OK if code == 0 and out else FAIL, out or "no row")

    code, out = psql(
        "SELECT count(*) FROM pg_roles "
        "WHERE rolname IN ('ai_secops_app','ai_secops_ro','ai_secops_sync');"
    )
    ok &= record("B.roles", OK if out == "3" else WARN, f"least-privilege roles: {out}")
    return ok


# --------------------------------------------------------------------------- C
def check_isolation() -> bool:
    code, out = docker_compose(
        "ps", "--format", "{{.Name}}", "--filter", "status=running")
    containers = [l.strip() for l in out.splitlines() if l.strip()]
    published = []
    for c in containers:
        rc, out = run(["docker", "inspect", "-f",
                       "{{json .HostConfig.PortBindings}}", c])
        if rc == 0 and out not in ("null", "", "{}"):
            published.append(c)
    detail = "no published ports" if not published else f"PUBLISHED: {published}"
    return record("C.isolation", FAIL if published else OK, detail)


# --------------------------------------------------------------------------- D
def check_corpus() -> bool:
    py_ok = shutil.which("python3") is not None
    try:
        import yaml  # noqa: F401
        import jsonschema  # noqa: F401
        have_deps = True
    except ImportError:
        have_deps = False
    if not py_ok or not have_deps:
        return record("D.corpus", SKIP, "run locally: pip install check-jsonschema pyyaml")
    ok = True
    pairs = [
        ("policies", "policy.schema.json"),
        ("exceptions", "exception.schema.json"),
        ("risks", "risk.schema.json"),
        ("standards", "standard.schema.json"),
        ("architecture", "adr.schema.json"),
        ("controls", "compensating-control.schema.json"),
    ]
    schemas_root = ROOT / "schemas"
    for folder, schema in pairs:
        files = sorted((ROOT / folder).glob("*.yaml"))
        if not files:
            ok &= record(f"D.schema.{schema}", WARN, "no artifacts found")
            continue
        from jsonschema import Draft202012Validator
        schema_doc = json.loads((schemas_root / schema).read_text())
        v = Draft202012Validator(schema_doc)
        bad = []
        for f in files:
            try:
                doc = yaml.safe_load(f.read_text())
            except yaml.YAMLError as e:
                bad.append(f"{f.name}: YAML parse error: "
                           f"{str(e).replace(chr(10), ' | ')[:200]}")
                continue
            for err in v.iter_errors(doc if doc is not None else {}):
                bad.append(f"{f.name}: {err.message[:100]}")
        ok &= record(f"D.{schema}", FAIL if bad else OK, "; ".join(bad) or f"{len(files)} artifact(s)")
    rc, out = run([sys.executable, str(ROOT / "scripts" / "check_references.py")], cwd=ROOT)
    ok &= record("D.references", OK if rc == 0 else FAIL, out[:300])
    return ok


# --------------------------------------------------------------------------- E
def check_backups() -> bool:
    bdir = INFRA / "backups"
    dumps = sorted(bdir.glob("*.dump")) if bdir.exists() else []
    if not dumps:
        return record("E.backups", WARN, "no pg_dump archive yet — run the restore drill")
    return record("E.backups", OK, f"latest: {dumps[-1].name}")


# --------------------------------------------------------------------------- F
def check_ingest() -> bool:
    """F. INGEST — the ops-plane write path is alive (Phase 2, workstream 2.2)."""
    code, out = run(["docker", "inspect", "-f", "{{.State.Health.Status}}",
                     "ai-secops-ingest-api-1"])
    if code != 0 or out.strip() != "healthy":
        return record("F.ingest.api", WARN,
                      f"not up (profile 'api' off) — health={out or 'absent'}; "
                      "start: docker compose --env-file .env --profile api up -d")
    ok = record("F.ingest.api", OK, out.strip())
    code, out = docker_compose("exec", "-T", "ingest-api", "python", "-c",
        "import urllib.request as u;"
        "print(u.urlopen('http://127.0.0.1:8000/healthz', timeout=5).read().decode())")
    ok &= record("F.ingest.healthz",
                 OK if code == 0 and ('"status":"ok"' in out or '"status": "ok"' in out) else FAIL,
                 (out.replace(chr(10), " ") or "no output")[:160])
    code, out = psql("SELECT count(*) FROM pg_roles "
                     "WHERE rolname = 'ai_secops_ingest' AND rolcanlogin;")
    ok &= record("F.ingest.role", OK if code == 0 and out == "1" else FAIL,
                 f"ai_secops_ingest login role: {out or '0'}")
    return ok


def main() -> int:
    results.clear()
    check_containers()
    check_database()
    check_isolation()
    check_corpus()
    check_backups()
    check_ingest()

    fmt = (sys.argv[1:2] + [None])[0]
    if fmt == "--json":
        print(json.dumps(results, indent=2))
    else:
        w = max(len(r["check"]) for r in results)
        for r in results:
            print(f"{r['status']:4}  {r['check']:{w}}  {r['detail']}")
        print("-" * 60)
    failed = any(r["status"] == FAIL for r in results)
    print(("✗ NOT READY" if failed else "✓ READY") + " — ai-secops platform self-check")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
