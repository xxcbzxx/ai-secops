#!/usr/bin/env bash
# AI-SecOps — one-command T1 deploy, designed to run INSIDE your PuTTY session.
#
#   Option A (repo on GitHub already):
#       sudo bash infrastructure/deploy.sh
#   Option B (fresh VM, no repo yet):
#       curl -fsSL -o deploy.sh <url-of-this-file-or-path>        # or pscp it over
#       sudo REPO_URL=https://github.com/xxcbzxx/ai-secops.git bash deploy.sh
#
# What it does (idempotent — safe to re-run):
#   0. verifies/installs Docker (Debian)   1. fetches/refreshes the repo
#   2. generates secrets + .env ON THE VM  3. `docker compose up -d` (data plane)
#   4. runs scripts/selfcheck.py           5. prints verify + next steps
#
# Everything sensitive (pg password, API keys) is generated here, on this VM,
# with umask 077 — NEVER passed over the network or typed into chat.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/ai-secops}"
REPO_URL="${REPO_URL:-https://github.com/xxcbzxx/ai-secops.git}"
PROFILES="${PROFILES:-}"    # add "ai,chat" to also load ollama/open-webui now

log()  { printf '\n\033[0;36m== %s\033[0m\n' "$*"; }
step() { printf '   \033[0;32m+\033[0m %s\n' "$*"; }

# SUDO resolution:
#   SUDO_AVOID=1 -> run sudo-less (docker-group user)
#   SUDO_FORCE=1 -> force sudo
#   default: sudo when not root
if [[ $(id -u) -eq 0 ]]; then
  SUDO=""
elif [[ -n "${SUDO_AVOID:-}" ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

# ---------------------------------------------------------------- 0. prereqs
log "0. host prerequisites (Debian 13)"
if ! command -v docker >/dev/null 2>&1; then
  step "docker not found — installing"
  curl -fsSL https://get.docker.com | sh
else
  step "docker present: $(docker --version)"
fi
docker compose version >/dev/null 2>&1 || {
  step "compose plugin missing — installing (apt)"
  $SUDO apt-get update -y && $SUDO apt-get install -y docker-compose-plugin
}
step "compose: $(docker compose version 2>/dev/null || echo fallback)"
command -v openssl >/dev/null || { $SUDO apt-get update -y && $SUDO apt-get install -y openssl; }
command -v git >/dev/null    || { $SUDO apt-get update -y && $SUDO apt-get install -y git;  }

# ---------------------------------------------------------------- 1. repo
log "1. repository @ ${REPO_DIR}"
if [[ -d "${REPO_DIR}" && -n "$(ls -A "${REPO_DIR}" 2>/dev/null)" ]]; then
  step "checkout present — keeping as-is (transport: git/scp/pscp, caller's choice)"
elif [[ -n "${REPO_URL}" ]]; then
  step "cloning"
  $SUDO mkdir -p "$(dirname "${REPO_DIR}")"
  $SUDO git clone "${REPO_URL}" "${REPO_DIR}"
else
  echo "FATAL: ${REPO_DIR} empty/missing and no REPO_URL given" >&2
  exit 1
fi
cd "${REPO_DIR}/infrastructure"
# Windows/OneDrive transports can strip write bits — self-heal ownership perms.
chmod -R u+rwX "${REPO_DIR}" || true

# ---------------------------------------------------------------- 2. secrets
log "2. secrets + .env (generated here, on ${HOSTNAME})"
umask 077
mkdir -p secrets backups
if [[ ! -s secrets/pg_password.txt ]]; then
  openssl rand -hex 16 | tr -d '\n' > secrets/pg_password.txt
  step "secrets/pg_password.txt created"
else
  step "pg password file kept"
fi
if [[ ! -f .env ]]; then
  QDRANT_API_KEY="$(openssl rand -hex 32)"
  WEBUI_SECRET_KEY="$(openssl rand -hex 48)"
  cat > .env <<EOF
POSTGRES_DB=ai_secops
POSTGRES_USER=ai_secops
TZ=UTC
QDRANT_API_KEY=${QDRANT_API_KEY}
WEBUI_SECRET_KEY=${WEBUI_SECRET_KEY}
EOF
  chmod 600 .env
  step ".env created (values generated locally, 0600)"
else
  step ".env kept"
fi

# ---------------------------------------------------------------- 3. compose
log "3. bringing up the data plane"
if [[ -n "${PROFILES}" ]]; then
  COMPOSE_PROFILES="${PROFILES}" $SUDO docker compose up -d
else
  $SUDO docker compose up -d
fi
$SUDO docker compose ps

# ---------------------------------------------------------------- 4. selfcheck
log "4. platform self-check"
if command -v python3 >/dev/null 2>&1; then
  ( pip3 install -q --user --break-system-packages pyyaml jsonschema 2>/dev/null ) || true
  $SUDO python3 "${REPO_DIR}/scripts/selfcheck.py" || true
  step "full gate re-runnable anytime: python3 /opt/ai-secops/scripts/selfcheck.py"
else
  step "python3 missing — skip; install apt python3 then re-run selfcheck"
fi

# ---------------------------------------------------------------- 5. next
log "5. verify + next steps"
cat <<'NEXT'
  pg data plane:
    docker exec -it ai-secops-postgres-1 psql -U ai_secops -d ai_secops -c '\dn'

  open a chat surface (optional, via your existing tunnel):
    sudo COMPOSE_PROFILES="ai,chat" docker compose --env-file .env up -d
    docker network connect ai-secops_edge cloudflared
    # add tunnel route -> http://openwebui:8080 and enforce Access policy

  backups drill:
    docker exec ai-secops-postgres-1 \
      sh -c 'pg_dump -U ai_secops -d ai_secops -Fc' > backups/ai_secops_$(date +%F).dump

NEXT
log "done — corpus is the product; sync/engine/UI land in Phase 2"
