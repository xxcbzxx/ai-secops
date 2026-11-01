#!/usr/bin/env bash
# AI-SecOps — one-shot git bootstrap to host the repository (run ON the host
# that will hold/push the checkout: the VM here, the workstation elsewhere).
# Idempotent: re-runs converge to the same history. Identity is the operator's
# GitHub noreply profile; adjust via environment:
#   GIT_AUTHOR  GIT_EMAIL  ORIGIN_URL  bash scripts/git_bootstrap.sh
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/ai-secops}"
ORIGIN_URL="${ORIGIN_URL:-https://github.com/xxcbzxx/ai-secops.git}"
GIT_AUTHOR="${GIT_AUTHOR:-xxcbzxx}"
GIT_EMAIL="${GIT_EMAIL:-xxcbzxx@users.noreply.github.com}"

cd "$REPO_DIR"
chmod -R u+rwX . 2>/dev/null || true

if [[ ! -d .git ]]; then
  git init -b main
fi
git config user.name  "$GIT_AUTHOR"
git config user.email "$GIT_EMAIL"
git config core.autocrlf false
git config core.filemode false

group_commit() {
  local msg="$1"; shift
  local p
  for p in "$@"; do git add "$p" 2>/dev/null || true; done
  if ! git diff --cached --quiet; then
    git commit -q -m "$msg"
    echo "committed: $msg"
  else
    echo "(unchanged) \"$msg\""
  fi
}

group_commit "align(ai-secops): phase 1 foundation - product docs, governance model, CI gates" \
  README.md CONTRIBUTING.md governance.md ROADMAP.md requirements.txt docs .github
group_commit "align(governance): seeded corpus POL-EX-RSK-STD-ADR-CTL + JSON schemas" \
  policies exceptions risks standards architecture controls schemas
group_commit "ops(infrastructure): T1 compose stack, two-plane DDL, deploy + backup drill" \
  infrastructure
group_commit "feat(sync): filesystem store adapter v1 - gov projection, provenance, drift protection" \
  scripts threat-intel backend collectors frontend policy-engine test-data imports

git remote add origin "$ORIGIN_URL" 2>/dev/null \
  || git remote set-url origin "$ORIGIN_URL"

echo
echo "--- git log --------------------------------------------------------"
git log --oneline
echo "--- status ---------------------------------------------------------"
git status --short
echo "next: git push -u origin main   (interactive credentials held by the operator)"
