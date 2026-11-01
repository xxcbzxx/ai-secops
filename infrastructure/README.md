# infrastructure/ — Deploying on `ai-secops01` (Debian 13, Docker)

T1 product deployment per ADR-004: single-host `docker compose`. The reference
deployment may run Swarm on the host — it is irrelevant to this stack.

## 0. Prereqs on the VM

Debian 13 with Docker Engine + compose plugin:

```bash
curl -fsSL https://get.docker.com | sh
docker compose version   # verify
```

Clone this repository (the compose file mounts `./postgres/init` read-only and
the governance store mounts default to the repo checkout via `../` — sync in
Phase 2 uses the same checkout):

```bash
mkdir -p /opt/ai-secops && cd /opt/ai-secops
git clone <your-remote> ai-secops && cd ai-secops
```

## 0.1 Access via jumphost (bastion)

If `ai-secops01` is only reachable through a jump/bastion host, every deploy,
verify and drill command uses an SSH proxy chain — no product change:

```bash
# one-time interactive test of the chain:
ssh -J jumpuser@jump-host.lan deployer@ai-secops01-internal-ip 'hostname && docker --version'

# alias it once (workstation ~/.ssh/config) so every later command is plain `ssh aiseq01`:
Host aiseq01
  HostName <internal-ip-of-ai-secops01>
  User deployer
  ProxyJump jumpuser@jump-host.lan
  IdentitiesOnly yes
  IdentityFile ~/.ssh/id_ed25519_ai_secops
```

Key install follows the same chain: `ssh -J ... deployer@vm 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys' < ~/.ssh/id_ed25519_ai_secops.pub` →
scp the **public** key through the jumphost; the private key never leaves the
workstation. Deployment then proceeds exactly as §2+ below (commands unchanged,
just prefixed with `ssh aiseq01` or executed inside the session).

> If the intent is instead to **run** the deployment ON the jumphost itself:
> acceptable when it is the only Linux host, but a bastion doubles as crown-jewel
> housing — see `docs/architecture.md` §8; we would split ingress/data onto the
> ai-secops01 host the moment it is available.

## 1. Secrets (never committed)

```bash
cd infrastructure
mkdir -p secrets
openssl rand -hex 16 | tr -d '\n' > secrets/pg_password.txt
chmod 640 secrets/pg_password.txt

cp .env.example .env
openssl rand -hex 32 | tr -d '\n'    # paste as QDRANT_API_KEY
openssl rand -hex 48                  # paste as WEBUI_SECRET_KEY
```

## 3. Bring up the data plane — the one-command way

Inside any existing session on the VM (PuTTY included):

```bash
sudo bash <repo>/infrastructure/deploy.sh
```

`deploy.sh` handles docker install (if absent), repo fetch/refresh, secret
generation (locally, 0600), `compose up`, and runs `selfcheck.py` for you.
Manual reproduction of what it does:

```bash
cd infrastructure
mkdir -p backups                      # pg_dump archives land here (selfcheck §E)
docker compose --env-file .env up -d          # postgres + qdrant
# optional:
docker compose --profile ai --env-file .env up -d     # + ollama
docker compose --profile ai --profile chat --env-file .env up -d   # + openwebui
```

First init applies the two-plane schema automatically
(`postgres/init/001-extensions.sql`, `002-schema.sql`, `003-seed.sql`).

## 4. Verify

```bash
docker exec -it ai-secops-postgres-1 \
  psql -U ai_secops -d ai_secops -c "\dn"                 # gov + ops schemas
docker exec -it ai-secops-postgres-1 \
  psql -U ai_secops -d ai_secops -c \
  "\dt gov.*" && \dt ops.*
docker exec -it ai-secops-postgres-1 \
  psql -U ai_secops -d ai_secops -c "SELECT * FROM ops.sync_state;"  # 1 row, 'pending'
docker exec -it ai-secops-postgres-1 \
  psql -U ai_secops -d ai_secops -c "\d gov.policies"     # provenance columns present
```

Qdrant:

```bash
docker exec ai-secops-qdrant-1 /qdrant/qdrant --version
# health via API key over the data network only (no published ports by design)
```

## 5. Validate the governance corpus (schema gate, same as CI)

On the repo root (any machine with Python 3.11+, or on the VM itself):

```bash
pip install check-jsonschema pyyaml
python3 scripts/selfcheck.py          # ← the boot/acceptance gate: A–E checks
```

`selfcheck.py` verifies: containers healthy · two-plane schema applied ·
`ops.sync_state` row + roles present · **no published host ports** · corpus
validates · backups exist. Exit 0 = platform is "ready". Per-block schema runs
are still available for debugging:

```bash
pip install check-jsonschema pyyaml
check-jsonschema --schemafile schemas/policy.schema.json              policies/*.yaml
check-jsonschema --schemafile schemas/exception.schema.json          exceptions/*.yaml
check-jsonschema --schemafile schemas/risk.schema.json               risks/*.yaml
check-jsonschema --schemafile schemas/standard.schema.json           standards/*.yaml
check-jsonschema --schemafile schemas/adr.schema.json                architecture/*.yaml
check-jsonschema --schemafile schemas/compensating-control.schema.json controls/*.yaml
python3 scripts/check_references.py                                  # referential integrity
```

## 6. Ingress (the ONLY outside path)

No service publishes ports. Your reverse proxy joins the attachable `edge`
network and serves `ai-secops-openwebui-1:8080` (when the `chat` profile is on):

```bash
# Cloudflare Tunnel example (runs wherever your tunnel lives):
docker network connect ai-secops_edge cloudflared
# then add the tunnel route → http://openwebui:8080 and enforce Access policy
```

Any org-equivalent works identically: Traefik/Caddy/Nginx container attached to
`ai-secops_edge`, or an SSO gateway in front. The product never requires
which one — the ingress adapter is your choice (ADR-003/ADR-004).

## 7. Air-gapped / offline pulls

`ai` network is `internal: true`, so Ollama cannot pull models itself.
Pull on a connected machine, bake the models into the volume, ship that volume:

```bash
# on a connected host:
docker run --rm -d --name ollama-pull -v tls-ollama:/root/.ollama ollama/ollama
docker exec ollama-pull ollama pull qwen3:8b
docker stop ollama-pull
docker volume export tls-ollama > ollama.vol          # or `tar` the volume dir
# on ai-secops01:
docker volume import  ollama_data ollama.vol && docker compose up -d ollama
```

Documented per-version in `runbook-offline.md` (Phase 3).

## 8. Backup + restore drill (acceptance test)

```bash
# nightly-ish (cron on host or a timer in Phase 2):
docker exec <postgres-container> sh -c \
  'pg_dump -U ai_secops -d ai_secops -Fc' > backups/ai_secops_$(date +%F).dump

# restore drill — prove a clean restore works on an EMPTY db before trusting it:
drop everything (or fresh volume), then:
cat backups/ai_secops_<date>.dump | docker exec -i <pg-container> \
  pg_restore -U ai_secops -d ai_secops --clean --if-exists
```

Also mirror the Git repository (the governance plane) to a second remote.
**The DB governance tables are a projection; the backup that must never die is
this repo.**

## 9. Scope of this deployment (Phase 1)

Running today: postgres, qdrant, (optional) ollama, (optional) open-webui.
Deliberately absent until Phase 2 per `ROADMAP.md`: backend API, sync job,
engine, project UI. Set `COMPOSE_PROFILES=ai,chat` in `.env` to keep profiles
persistent across `docker compose up` runs.
