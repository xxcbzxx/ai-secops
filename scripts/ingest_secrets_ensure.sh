#!/usr/bin/env sh
# ingest_secrets_ensure.sh — create the ingest API's two secrets locally on the
# stack host (values are hex, NEVER printed; files are chmod 600 and live under
# infrastructure/secrets/, which .gitignore excludes). Idempotent: existing
# non-empty files are kept, so re-running never rotates silently — rotation is
# an explicit op: delete the file, re-run, then restart the ingest-api.
#   bash ~/ai-secops/scripts/ingest_secrets_ensure.sh
set -eu
cd "$(dirname "$0")/../infrastructure"
umask 077
mkdir -p secrets
python3 - <<'PY'
import os, pathlib, secrets
base = pathlib.Path("secrets"); base.mkdir(exist_ok=True)
pw = base / "pg_ingest_password.txt"
if not pw.exists() or pw.stat().st_size == 0:
    pw.write_text(secrets.token_hex(32))
tok = base / "ingest_tokens.txt"
if not tok.exists() or tok.stat().st_size == 0:
    tok.write_text(
        "homelab-collector:{}:assets services software findings\n"
        "limited-collector:{}:findings\n".format(
            secrets.token_hex(32), secrets.token_hex(32)))
for f in (pw, tok):
    os.chmod(f, 0o600)
print("SECRET-FILES-READY  sizes:", pw.stat().st_size, tok.stat().st_size)
PY
chmod 600 secrets/pg_ingest_password.txt secrets/ingest_tokens.txt
echo "view values anytime in PuTTY: cat ~/ai-secops/infrastructure/secrets/ingest_tokens.txt"
