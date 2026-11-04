# ROADMAP

Status owner: security-architecture · Last updated: 2026-11-04
Context: **solo developer, focused wedge** (ADR-004) · deployment **T1-Compose only** until traction · findings via **generic ingest API** · framework **pack loader** (CIS first)

## Current VM baseline — 4 November 2026

Read-only discovery confirmed healthy PostgreSQL, Qdrant, ingest, and Ollama;
nine governance projections match repository hashes. The inventory, findings,
evaluations, and threat tables are empty. Open WebUI and an ingress container
were not present. Historical `ai-secops01` acceptance notes below are retained;
current VM hostname is `ai-secops`.

The approved first milestone is **ingest integrity and trustworthy readiness**:
malformed-token handling, consistent finding targets, transaction completion before
success, fail-closed readiness, reliable container checks, and regression tests/CI.
Implemented on `plat/ingest-integrity-readiness`: 79 regression tests pass;
all six governance schema gates, reference checks, weakness sweep (including
8 detector self-tests), dependency consistency, and the updated read-only live
self-check pass on the VM. Source validation does not constitute deployment. See `docs/deployment-inventory.md` for test commands and limits.

Operational hold points require separate approval: reconcile repository versus
`/opt/ai-secops` Compose/storage definitions; restrict audit privileges; replace
superuser sync credentials; validate scheduled backups and isolated restores.
Do not apply grants, migrations, restarts, or deployment during this milestone.

Next: complete `docs/governance-model.md` and `docs/policy-engine.md`, implement
pure deterministic engine v1 with golden outcomes, then populate an approved
inventory and add registry/posture reads. `docs/threat-intelligence.md`, framework
packs, collectors/n8n, correlation, and grounded AI follow later. These referenced
design documents are currently absent, not completed Phase 1 deliverables.

---

## 0. Delivery strategy

| Phase | Object | Outcome |
|---|---|---|
| 0 | Repository & governance seed ✅ | Source of truth + worked example loop (POL-001/EX-001/RSK-001/CTL-001) |
| **1** | Foundation: data model, governance model, asset model, T1 docker architecture, engine design | Deployable platform skeleton (design docs + DDL + compose), validated corpus, CI |
| **2** | Wedge v0.1: sync + ingest API + engine v1 + minimal UI + CIS pack skeleton | First real posture for an external deployment |
| 3 | Intelligence: grounded assistant (pluggable LLM), feed connectors behind ingest OR direct | The differentiator |
| 4 | Enterprise tier: OIDC adapter GA, forge adapters, Helm reach (design only in v1.x) | Enterprise sell |
| 5 | Commercialisation: licensing, packaging, multi-tenant/SaaS decision | Product |

Rules carried from `docs/architecture.md`:

1. **Determinism before AI** — the engine is a pure function; the AI never gates compliance.
2. **Git/store before database** — governance plane is files; database is a projection (ADR-001).
3. **One tier, one wedge** — Compose-only; adapters contract-first but not implemented until needed (ADR-003/ADR-004).
4. **Homelab = reference deployment** — environment-specific work (Proxmox/Cloudflare specifics) lives in adapters, never in the core (ADR-003).

---

## 1. Phase 0 — done (this state)

Deliverables: repository, docs, seeded corpus demonstrating every artifact class and
every lifecycle field; ADR-001…ADR-002 recorded; ADR-003…ADR-004 added after the
enterprise pivot; `docs/architecture.md` rewritten as product + reference deployment.

---

## 2. Phase 1 — Foundation (next ~30 days)

**Objective:** build the foundation only. **No AI features.**

**Deployment status (2026-11-01):** T1 stack live on `ai-secops01` (Debian 13,
Docker 29, PG 17.11 / Qdrant v1.13.4, internal-only networks, no published
ports) — `scripts/selfcheck.py` `✓ READY` (A/B/C/E green; D corpus validation
deferred to CI on that host); backup archive created and restore round-trip
verified into a scratch DB.

| # | Workstream | Deliverables | Accepted when |
|---|---|---|---|
| 1.1 | Data model | `docs/data-model.md` + PostgreSQL DDL (`infrastructure/postgres/init/`), ERD, enum vocabulary incl. RBAC roles | DDL applies ✅ cleanly on PG 17.11 (ai-secops01, 2026-11-01); ERD review pending |
| 1.2 | Governance model | `docs/governance-model.md`: lifecycle state machines, approval matrix, review calendar | Walkthrough of POL/EX/RSK lifecycles done |
| 1.3 | Asset model | classification + `schemas/asset.schema.json`, `finding.schema.json` | Two real assets and one real finding round-trip the contract |
| 1.4 | Schemas & CI | JSON Schemas for 6 governance classes + referential-integrity CI | CI blocks invalid governance PRs |
| 1.5 | Compose architecture | `infrastructure/docker-compose.yml` (T1) + `.env.example` + backup/restore drill; Postgres/Qdrant/Ollama adapter defaults (ollama profile optional); ingress adapter docs (Traefik/tunnel) | ✅ Clean VM (ai-secops01, 2026-11-01): compose up works, internal-only data/ai nets, dump→scratch-DB restore verified |
| 1.6 | Engine design | `docs/policy-engine.md` + interface skeleton (types, selector, decision record; **no logic**) | Pipeline walk-through reproduces the five required outcomes on paper w/ RSK-001/EX-001 |
| 1.7 | Threat intel design | `docs/threat-intelligence.md`: feed map, licensing/TLP, correlation strategy; **no connectors** | NVD/KEV/GHSA ingestion deferred by design |
| 1.8 | Baseline inventory | `imports/*.csv` + first import of reference-deployment assets | ≥ 10 assets with owner/environment/exposure populated |

Exit: demo shows repo validates in CI, T1 deploys and restores cleanly, inventory
has ≥ 10 assets, and the engine *design* reproduces the required outcomes on the
seeded corpus. **No demo features built yet — by design.**

### Suggested solo rhythm (30 days)

| Week | Focus |
|---|---|
| 1 | 1.5 deployment + backup drill; repo hosting w/ protected `main`; CODEOWNERS, PR template |
| 2 | 1.8 + 1.2: import reference-deployment inventory; governance workshop on the seeded corpus (extend to 5–8 policies as real observations appear; EX/RSK/CTL review round) |
| 3 | 1.1 + 1.4: DDL applied to a staging compose Postgres; 6 schemas merged; CI green |
| 4 | 1.6 + 1.7: engine framework walkthrough; threat intel design review; Phase 2 go/no-go |

---

## 3. Phase 2 — Wedge v0.1 (weeks 5–8): the sellable slice

The wedge for `docker compose up` customers:

| Workstream | Deliverables | Exit criteria |
|---|---|---|
| Governance sync ✅ | Store adapter v1 (**filesystem only**): validated projection into Postgres; provenance stamps (path/hash/commit); idempotent; drift detector | ✅ Verified on ai-secops01 (2026-11-01): rebuildable gov plane, safe wipe-and-resync, none-drift parity |
| Generic ingest API ✅ | FastAPI v1 (`ai-secops.ingest/v1`): assets/services/software/findings idempotent upserts (natural keys + fingerprint), scoped bearer keys, audit-per-write, least-privilege `ai_secops_ingest` role (ops rw / gov ro) | ✅ Verified on ai-secops01 (2026-11-02): 25-check acceptance drill green — auth 401/403, same-id idempotency, 422-without-rows integrity, DB+audit reality, teardown; selfcheck F-gate added, ✓ READY |
| Engine v1 | Deterministic pipeline per `docs/policy-engine.md`; decision records in DB; golden tests from `test-data/` | All five required outcomes + `not_applicable`; reproducible records |
| CIS pack skeleton | Loader + starter pack (mappings only, per-core controls) + 1 mapped policy beyond POL-001 | A policy citing the pack evaluates end-to-end |
| Minimal UI | Posture page + registries (read-only) + review queues (expiring exceptions) | Local accounts only; clearly positioned as read-only |
| Reference deployment hardening | STD-001 self-check on own deployment; logging fixture | Platform passes its own baseline check |

**Explicitly deferred (in original plans, not in the wedge):** OIDC GA, forge
adapters, Helm, scanner adapters, KEV connectors, reports.

---

## 4. Phase 3 — Intelligence (weeks 9–14)

| Workstream | Notes |
|---|---|
| Grounded assistant | Agent service speaking the **LLM adapter contract** (Ollama default; OpenAI-compatible BYOK endpoint option). Qdrant vectors over the governance corpus + asset cards + correlated threat entries |
| Grounding contract enforcement | Mandatory citations; refusal mode; the "advisory-only" labelling |
| Feed connectors | NVD, CISA KEV, GitHub Advisories behind the ingester's JSON contract, license-checked; or via generic ingest |
| Correlation | `asset_software` (CPE/purl) ↔ `affected_products`; KEV × exposure priority queue |
| Golden Q&A set | Corpus-grounded answers on POL-001/EX-001/RSK-001/ADR-001; drift > 0 blocks release |

## 5. Phase 4 (design now, build on traction signals)

- **OIDC SSO GA** (customer IdP: Keycloak/Authentik/Auth0/Entra) + RBAC improvements.
- **Forge adapters** (GitHub/GitLab/Gitea/Bitbucket, read-only polling).
- **SharePoint/NAS**: document the file-share sync pattern; Graph API adapter only if demanded.
- **Helm/T2 chart** for enterprise expectations (HA Postgres, queue).
- Reports generation, SIEM audit-exhook, scanner adapters (Wazuh/OpenVAS/Trivy translators).

## 6. Phase 5 — Commercialisation

1. License: code (BUSL vs Apache open-core) + corpus (CC-BY candidate); trademark
2. Packaging: signed images, offline/air-gapped playbooks, installer UX
3. Framework packs by region (CIS, NIST, ISO…) — data-only extensions
4. SaaS evaluation only if a real subscriber demand appears
5. Charted metrics: time-to-first-posture, exception cycle time, review-debt burn-down

---

## 7. Standing quality gates (every phase)

| Gate | Requirement |
|---|---|
| Security review | Against `docs/architecture.md` §8 |
| Governance integrity | Schema validation + referential integrity on every PR |
| Reversibility | T1 dataplane re-deployable; DB recomposable from store |
| Tooling discipline | No demo feature enters a phase without a linked exit criterion |
| Homelab firewall | Anything that could only run on ai-secops01 must live as an adapter, never in the core |

## 8. Top standing risks

| Risk | Mitigation |
|---|---|
| Solo-dev burnout / scope creep | Wedge definition fixed; deferred lists are contractual |
| LLM quality on the default Ollama path | Grounding contract + refusal mode; BYOK option for accuracy-critical buyers |
| "All options" ambition outruns solo effort | Adapters are contract-first, one default each; alternative implementations lead on customer demand |
| Content/licensing traps (CIS, feeds) | Mapping-only strategy; oracle terms checked pre-code |
| Exception fatigue / review debt | Expiry enforcement + review queues are wedge UI features |
| Platform-as-first-customer breaks | STD-001 self-check is a wedge fixture |
