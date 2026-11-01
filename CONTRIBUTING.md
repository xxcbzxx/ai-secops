# Contributing to AI-SecOps

AI-SecOps is a **governance product**: most changes here are not code changes, they are
changes to *what the organisation enforces, tolerates and decides*. Treat every PR
accordingly.

---

## 1. Golden rules

1. **Git is the source of truth.** Never hand-edit governance state in PostgreSQL, in
   n8n, or in a UI. All change flows through pull requests.
2. **Every governance transition is a human decision** with a named approver and a date.
   Requesters may never approve their own artifact (4-eyes rule).
3. **Exceptions always link a risk and expire.** No exceptions without `risk_ref`;
   no exceptions without `valid_to`. Renewals are new PRs, not edits that slide dates.
4. **The AI advises; the engine decides; humans approve.** AI-generated text entering
   governance must be reviewed like any human contribution and marked with its origin.
5. **IDs are forever.** `POL-001`, `RSK-004`, `EX-002`, `ADR-003` … are immutable
   identifiers. To retire content, transition state (`superseded`, `retired`) — never
   delete. Reuse is forbidden.
6. **Version every artifact.** Semver: patch for wording, minor for scope/requirement
   changes, major for intent changes (intent changes need re-approval).

## 2. Workflow

### Branches

```
main                    protected. Linear history, signed commits, required reviews.
gov/POL-014-logging     governance artifact changes (one artifact per PR preferred)
plat/<scope>-<desc>     platform code (policy-engine, backend, infrastructure…)
docs/<topic>            documentation changes
```

### Commits

Conventional Commits: `gov(policy): tighten POL-001 scope to edge-exposed services`,
`feat(engine): selector precedence rules`, `docs: data model ERD`.

### Pull requests

Every PR must state **what changed, why now, and which decision approved it**.
A governance PR template with `state / approvers / risk_ref / valid_to` checklist
lands with Phase 1 CI.

## 3. Review matrix

| Path | Required reviewers | Notes |
|---|---|---|
| `policies/**` | security-architecture **+ CISO delegate** | Intent changes = major version |
| `exceptions/**` | security-architecture **+ CISO delegate** | MUST include `risk_ref` + `valid_to` |
| `risks/**` | security-architecture + owner of affected assets | Acceptance decision recorded in-file |
| `standards/**` | security-architecture | Cite source baselines (CIS/NIST/ISO) |
| `architecture/**` (ADRs) | security-architecture + platform-lead | Superseded, never deleted |
| `controls/**` | security-architecture | Evidence must be verbatim + hashed |
| `schemas/**` | security-architecture + platform-lead | Schema evolution needs note |
| `infrastructure/**` | platform-lead + security-architecture | Touches the trust boundary |
| `policy-engine/**`, `backend/**`, `frontend/**`, `collectors/**`, `imports/**` | platform-lead | |
| `threat-intel/**` | security-architecture | Licensing & TLP review |
| `docs/**` | any governance role | |

Suggested CODEOWNERS team names: `@ai-secops/security-architecture`, `@ai-secops/ciso`,
`@ai-secops/platform-lead` (adjust to the real org when hosted).

## 4. Validation (Phase 1 CI gate)

Each governance artifact is validated by its JSON Schema in `schemas/`:

```bash
pipx install check-jsonschema

check-jsonschema --schemafile schemas/policy.schema.json              policies/*.yaml
check-jsonschema --schemafile schemas/exception.schema.json          exceptions/*.yaml
check-jsonschema --schemafile schemas/risk.schema.json               risks/*.yaml
check-jsonschema --schemafile schemas/standard.schema.json           standards/*.yaml
check-jsonschema --schemafile schemas/adr.schema.json                architecture/*.yaml
check-jsonschema --schemafile schemas/compensating-control.schema.json controls/*.yaml
```

Additional CI checks (added Phase 1):

- **Referential integrity** — every `policy_ref`, `risk_ref`, `control_ref`, `standard`
  in one artifact resolves to an existing artifact in the repository.
- **Policy-engine dry run** — directory of artifacts loads through `policy-engine` loader.
- **Lint** — `yamllint`, `ruff`, `shellcheck` for their respective areas.
- **Forbidden patterns** — secrets, `localhost` passwords, `TODO` in `state: active` artifacts.

## 5. Artifact conventions

- File name: `<ID>-<kebab-case-title>.yaml` (e.g. `EX-001-lab-edge-exposure-open-webui.yaml`).
- One artifact per file. `api_version: ai-secops.gov/v1` at the top of every file.
- `state`/`status` transitions happen in the artifact; the PR body carries the human decision.
- Anything a script computes (content hashes, source paths) must **not** be hand-written
  into artifacts — provenance fields are stamped by the governance sync service.
- Scope selectors use the shared vocabulary from `docs/architecture.md` §6
  (`environments`, `exposures`, `asset_kinds`, `platforms`, `asset_uids`, `tags`).

## 6. Engineering standards (code areas)

| Area | Standard |
|---|---|
| Backend (Phase 2) | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, ruff + mypy clean |
| Policy engine (Phase 2) | Pure, deterministic, no network, no LLM — 100% branch coverage via golden tests |
| Tests | Contract tests for ingest schemas; golden evaluation cases in `test-data/` |
| Infrastructure | No published ports for data plane; secrets via Docker/Swarm secrets; every service has a healthcheck |
| Docs | Architecture changes update `docs/` and, when architectural, open an ADR |

## 7. RAADR — Requesting an ADR

Architecture-relevant changes (trust boundaries, data model, policy language, AI role)
must record an **ADR** in `architecture/`:

1. PR announces intent: a new `architecture/ADR-00n-*.yaml` with `status: proposed`.
2. Review round with explicit comparison of options and tradeoffs.
3. Decision meeting → status: `accepted` with deciders and date; or `rejected` (kept!).
4. Superseding is recorded with `supersedes` / `superseded_by` — history is preserved.

## 8. Security disclosure

Do not open public issues for security-relevant reports about the deployment or platform.
Contact the CISO delegate / platform-lead privately; include impact and reproduction.
Platform hardening requirements live in `docs/architecture.md` §8.

## 9. What NOT to contribute in Phase 1

Please do not open PRs for: working policy-engine implementations, AI/RAG features,
scanner connectors, or frontend code. The first 30 days are foundation-only by design —
see `ROADMAP.md` scope table. Open an issue describing the idea instead; the roadmap
will absorb it in the right phase.
