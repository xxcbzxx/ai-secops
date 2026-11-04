# Verified deployment and development baseline

Inspected 4 November 2026 on `ai-secops` over verified Tailscale SSH. This is an
observed inventory, not a deployment manifest. Recheck it before operational work.

## Development boundary

- Develop, test, and build directly on the Debian 13 VM as `ai-secops`.
- Existing checkout: `/home/ai-secops/ai-secops`; GitHub: `xxcbzxx/ai-secops`.
- Codex Cloud is only an SSH/orchestration client. Keep strict host-key checking.
- Use feature branches and meaningful local commits. Push only with explicit approval.
- Do not reinstall or recreate existing infrastructure to establish a dev environment.
- System configuration, system dependencies, Docker service/network changes, database
  migrations, restarts/deployments, security-policy changes, and destructive actions
  each require explicit approval. Development approval does not authorize deployment.

## Observed runtime

Debian 13.7, Python 3.13.5, Docker 29.9.2, Compose 5.6.1. Approximately 31 GiB RAM
and 161 GiB available disk at discovery. All four containers were healthy and had
no published host ports.

| Container | Configuration source | Networks | Persistent storage |
|---|---|---|---|
| `ai-secops-postgres-1` | Repository `infrastructure/docker-compose.yml` | `ai-secops_data` (internal) | Docker named volume `ai-secops_pg_data` |
| `ai-secops-qdrant-1` | Repository Compose | `ai-secops_data` (internal) | Docker named volume `ai-secops_qdrant_data` |
| `ai-secops-ingest-api-1` | Repository Compose | `ai-secops_data`, `ai-secops_edge` | None; read-only secret mounts |
| `ai-secops-ollama-1` | `/opt/ai-secops/compose.yaml` plus Qdrant/Ollama overlays | `ai_inference` (internal) | `/srv/ai-secops/ollama`, including its home subdirectory |

PostgreSQL was 17.11; Qdrant was v1.13.4. Ollama had `qwen3:4b` (approximately
2.5 GB), a digest-pinned image, non-root UID, dropped capabilities, and
no-new-privileges. The repository API is not connected to the inference network.
No Open WebUI, ingress/tunnel, n8n, engine, or collector container was observed.
External infrastructure and integrations were not inventoried.

The ingest API was the only member of `ai-secops_edge`. PostgreSQL/Qdrant had
no published ports; unauthenticated Qdrant collection access returned 401.
SSH listened on host IPv4/IPv6 wildcard addresses; firewall reachability was not
established. Membership of the VM's Docker group grants powerful host access.

## Deployment drift: operational hold point

`/opt/ai-secops` also contains PostgreSQL/Qdrant definitions, using different
networks, digest pins, hardening, and `/srv` storage. Those definitions do not
represent the running PostgreSQL/Qdrant containers. Both Compose configurations
use the `ai-secops` project identity.

Do not run a generic Compose update from either directory as a reconciliation
step. It can select different services, storage, or networks. First prepare and
approve a service-by-service plan identifying authoritative manifests, current
volume contents, verified backups, rollback, and maintenance scope. Do not remove
or replace either data location. `/srv/ai-secops` contents were permission-restricted
and were not inspected.

## Data and governance baseline

The database contained nine projected governance artifacts and 16 audit events.
Assets, services, software, findings, evaluations, and threat entries each had
zero rows. All nine governance hashes matched repository files and carried commit
provenance. The filesystem sync row reported `ok`, last synced 2 November 2026.

The repository's original platform self-check passed. A 56,264-byte backup named
`ai_secops_2026-11-01.dump` existed. A successful restore is recorded in earlier
roadmap notes but was not repeated. No application backup timer was identified;
cron, external schedulers, off-host copies, retention, and recovery remain unverified.
The self-check's backup-exists result does not establish recovery readiness.

## Separate approval required: security remediation

These are findings and proposed follow-up work, not applied changes:

1. The ingest role can update/delete `ops.audit_events`; prepare narrower grants
   and audit protections. Audit insertion is transactional in application code,
   but database-enforced immutability is not implemented.
2. Governance sync uses the database superuser; prepare a dedicated login using
   the existing sync group role, with reviewed sequence/table privileges.
3. Reconcile the split deployment, persistence, secret handling, and container
   hardening. Preserve the isolated data/inference networks.
4. Establish approved backup scheduling, retention, off-host storage, and an
   isolated restore exercise before making recovery claims.

No grants, migration, deployment, or infrastructure changes accompany this milestone.
Tenant isolation, engine execution, and AI integrations are separate future work.

## User-local development and tests

Run on the VM, in the existing checkout. This tested bootstrap uses the existing
system pip to manage a pipless virtual environment; Debian's missing ensurepip
module therefore does not require a system package installation.

```bash
cd /home/ai-secops/ai-secops
python3 -m venv --without-pip "$HOME/.venvs/ai-secops-dev"
python3 -m pip --python "$HOME/.venvs/ai-secops-dev" install -r requirements-dev.txt
"$HOME/.venvs/ai-secops-dev/bin/python" -m pytest -q
```

Check the pipless environment's dependencies with the system pip selector:

```bash
python3 -m pip --python "$HOME/.venvs/ai-secops-dev" check
```

The regression suite uses ASGI requests, synthetic token files in pytest temporary
storage, and database/Docker doubles. It does not run the production lifespan,
read secrets, create containers, or touch the live database. Transaction tests
verify application boundaries with a pool double; they do not replace PostgreSQL
integration tests, migration validation, or an approved staging acceptance drill.
Runtime package pins match versions observed in the running API; governance and
transitive dependencies are not fully locked. Starlette currently emits a
TestClient/httpx deprecation warning; tests pass with the pinned combination.

A read-only live check is available separately:

```bash
cd /home/ai-secops/ai-secops
"$HOME/.venvs/ai-secops-dev/bin/python" scripts/selfcheck.py
```

Do not run `scripts/ingest_acceptance.py` as a read-only check: it inserts and
deletes canary records. Deployment, image builds, and runtime acceptance must be
planned separately. Source-level test success does not mean the running image
contains the changes.

## Milestone validation — 4 November 2026

- 79 application/self-check regression tests passed on VM Python 3.13.
- Six governance schema gates passed across nine artifacts; references resolve.
- Weakness sweep passed; its detector fixture assertions passed 8/8.
- User-local dependency consistency check and Git whitespace check passed.
- Updated read-only live self-check passed against the existing containers.
- No production acceptance writes, image builds, migrations, restarts,
  deployments, security-policy changes, or GitHub pushes were performed.

The live self-check confirms current runtime posture; it does not validate the
new source in a deployed image. Real PostgreSQL rollback/concurrency verification
remains a staging integration task requiring separate approval.

## Approved ingest rollout — 4 November 2026

After explicit deployment approval, source commit
`3ae05173b4ed343ca28a724f5631b28e924e2fcc` was built directly on the VM using a
minimal context containing only the Dockerfile's two copied source files.
The verified image is retained as `ai-secops-ingest-api:milestone-3ae0517`;
the previous image is retained as `ai-secops-ingest-api:rollback-ad77aef344ef`.
Only `ingest-api` was recreated using repository Compose with
`--no-deps --no-build --pull never`. PostgreSQL, Qdrant, and Ollama container IDs
and start times were unchanged. No networks, published ports, migrations,
privileges, or secret files were changed.

Live `/healthz`, `/readyz`, `/openapi.json`, and `/docs` returned 200. Missing and
malformed bearer authentication returned 401. Operational inventory/finding rows
remained zero and audit rows remained 16. The updated platform self-check passed.
Real PostgreSQL write/rollback and concurrency integration tests were not run.

Deployment records are stored outside Git at
`~/.local/state/ai-secops/deployments/3ae0517/`. GitHub push was attempted but
blocked because VM HTTPS Git authentication is not configured; no SSH key,
credential helper, GitHub token binding, or GitHub CLI session was available.
Do not put credentials into this document or Git remotes.

### View the live API without exposing a host port

From a computer on the tailnet, with the independently verified VM host key
already trusted by that computer's SSH client, keep this command running:

```bash
ssh -o StrictHostKeyChecking=yes -N -L 127.0.0.1:18000:172.18.0.2:8000 ai-secops@100.107.201.39
```

Open `http://127.0.0.1:18000/docs` for API documentation, or `/readyz` for readiness.
This is the ingest API, not the future operator dashboard. Local forwarding was
verified through Tailscale SSH. Closing SSH closes access. The destination is the
current ingest edge-network container IP; recheck it after container recreation:

```bash
docker inspect -f '{{(index .NetworkSettings.Networks "ai-secops_edge").IPAddress}}' ai-secops-ingest-api-1
```

No persistent ingress or public endpoint was added. API writes still require a
scoped collector credential; do not experiment with write endpoints on live data.
