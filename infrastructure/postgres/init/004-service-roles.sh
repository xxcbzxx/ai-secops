# 004-service-roles.sh — attach LOGIN roles to the Phase-2 group roles of
# 003-seed.sql. Runs inside the postgres container:
#   * automatically on first init (docker-entrypoint-initdb.d: non-executable
#     .sh files are sourced by the entrypoint),
#   * on a LIVE database: docker cp into the running container, then
#     `docker exec -e POSTGRES_USER=... -e POSTGRES_DB=... <c> sh /tmp/004...sh`.
# Contract: the secret files hold HEX-ONLY passwords (openssl rand -hex /
# secrets.token_hex) so they need no SQL quoting. Rotating = edit the secret
# file, re-run this script (ALTER ROLE keeps the grant memberships intact).
set -eu
: "${POSTGRES_USER:=ai_secops}"
: "${POSTGRES_DB:=ai_secops}"
PSQL="psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB"

ensure_login_role() {   # $1 role, $2 group role, $3 secret file
  role="$1"; group="$2"; secret="$3"
  if ! [ -s "$secret" ]; then
    echo "004: no secret file for $role ($secret) — ROLE NOT CREATED" >&2
    return 0
  fi
  pw=$(cat "$secret")
  exists=$($PSQL -Atq -c "SELECT 1 FROM pg_roles WHERE rolname = '$role';" || true)
  if [ "$exists" = "1" ]; then
    $PSQL -q -c "ALTER ROLE \"${role}\" LOGIN PASSWORD '${pw}';"
  else
    $PSQL -q -c "CREATE ROLE \"${role}\" LOGIN IN ROLE \"${group}\" PASSWORD '${pw}';"
  fi
  echo "004: login role $role ensured (IN ROLE $group)"
}

# ingest/registry API -> ai_secops_app: ops rw, gov ro (ADR-002)
ensure_login_role ai_secops_ingest ai_secops_app /run/secrets/pg_ingest_password

# Sequences: identity/bigserial INSERT paths need USAGE (+SELECT) granted to
# the app group — 003 granted TABLES; sequences only here (idempotent, and
# also fixes this on live databases upgraded with this script).
$PSQL -q <<'EOSQL'
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ops TO ai_secops_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
  GRANT USAGE, SELECT ON SEQUENCES TO ai_secops_app;
EOSQL
echo "004: ops sequence grants ensured for ai_secops_app"
