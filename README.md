# AI-SecOps

**AI-assisted Infrastructure Security Intelligence Platform**

AI-SecOps is not a vulnerability scanner. It turns your *own* security governance —
policies, exceptions, risks, standards and architecture decisions — into a machine-validated,
queryable registry, and combines it with your asset inventory, findings and threat
intelligence so that engineers, infrastructure teams, security teams, architects and
CISOs get **grounded, contextualised, explainable** guidance.

> The AI educates, explains and recommends.
> **Humans decide.**

---

## Status

| Field | Value |
|---|---|
| Phase | **1 — Foundation** |
| Deployment target | VM `ai-secops01` · Debian 13 · Docker / Docker Swarm |
| Data plane | PostgreSQL · Qdrant · Ollama · Open WebUI (internal-only) |
| Edge | Cloudflare Tunnel (zero-trust ingress) |
| Source of truth | **Git** — this repository |
| Version | `0.1.0 foundation` |

## Core principles (non-negotiable)

| # | Principle | Meaning |
|---|-----------|---------|
| 1 | **Security First** | PostgreSQL, Qdrant and Ollama never leave internal Docker networks. No published ports. |
| 2 | **Git First** | Policies, Exceptions, Risks, Standards and ADRs live in `governance/` as YAML. Git is the source of truth; the database is a rebuildable projection. |
| 3 | **Human Approval** | Every governance transition (approve policy, accept risk, grant exception) is a named, dated, auditable human decision. A requester may never approve their own artifact (4-eyes rule). |
| 4 | **Local First (default)** | Default inference is local Ollama (Qwen3 / DeepSeek-R1 candidates). Buyers without local GPUs point the LLM adapter at their own endpoint instead; data never leaves the site unless the customer explicitly configures it. |
| 5 | **Deterministic enforcement** | Compliance evaluation is a pure function. The AI never gates compliance; it advises. |
| 6 | **Grounded AI** | Recommendations must cite internal policies, exceptions, risks, ADRs, asset context and threat intel. Generic industry best practice is used only when no internal policy exists — and is always labelled *advisory*. |

## What AI-SecOps is / is not

| It IS | It is NOT |
|---|---|
| A governance registry with enforced lifecycle | A vulnerability scanner |
| A deterministic policy evaluation engine | An auto-remediation tool |
| A risk & exception intelligence layer | A document store with a chatbot |
| An advisory AI with mandatory citations | A decision maker |

## The platform's five roles

1. **Security Analyst** — correlates findings, exceptions, risks and threat intel into explanations.
2. **Security Architect** — surfaces architecture weaknesses against recorded decisions (ADRs) and standards.
3. **Governance Advisor** — keeps policy/exception/risk lifecycles honest (expiries, reviews, approvals).
4. **Infrastructure Advisor** — maps guidance to real assets and services with ownership context.
5. **Risk Advisor / Mentor** — teaches tradeoffs; proposes options with evidence, never verdicts.

## Repository map

Governance artifacts live at the repository root — like the upstream structure at
`github.com/xxcbzxx/ai-secops` this repo builds on — because they are the product.

```
ai-secops/
├── README.md               ← you are here
├── ROADMAP.md              Phase 0 – 5 delivery plan + first 30 days
├── CONTRIBUTING.md         Contribution rules & review matrix
│
├── governance.md           Git-first governance charter (lifecycles, approvals)
├── policies/               POL-xxx  Mandatory, enforceable rules
├── exceptions/             EX-xxx   Time-boxed deviations (risk ref + approver)
├── risks/                  RSK-xxx  Risk statements and acceptances
├── standards/              STD-xxx  Baselines derived from CIS/NIST/ISO/internal
├── architecture/           ADR-xxx  Architecture Decision Records
├── controls/               CTL-xxx  Compensating controls with verbatim evidence
│
├── docs/                   Documentation
│   ├── project-vision.md       Product vision, personas, AI operating principles
│   ├── architecture.md         Platform architecture, data model, deployment
│   ├── data-model.md           (Phase 1) ERD & PostgreSQL schema design
│   ├── governance-model.md     (Phase 1) Lifecycles, approvals, states
│   ├── policy-engine.md        (Phase 1) Evaluation framework design
│   └── threat-intelligence.md  (Phase 1) Feed & correlation design
│
├── schemas/                (Phase 1) JSON Schemas validating every artifact
├── infrastructure/         (Phase 1) Docker Compose, Swarm stack, Postgres init
├── backend/                (Phase 2) Ingest & Registry API (FastAPI)
├── frontend/               (Phase 2) Operator UI — registries, approvals, posture
├── collectors/             (Phase 2) Proxmox / Portainer / Cisco / OpenWRT / Cloudflare
├── imports/                (Phase 2) Bulk CSV/JSON bootstrap inventory
├── policy-engine/          (Phase 2) Deterministic evaluation engine
├── threat-intel/           (Phase 3) NVD / CISA KEV / GHSA / vendor RSS connectors
└── test-data/              Golden test assets & findings
```

Folders marked *(Phase n)* exist in the roadmap shape but are intentionally empty in
Phase 1 — see `ROADMAP.md` for scope discipline.

## Governance snapshot

| ID | Artifact | Purpose |
|---|---|---|
| `POL-001` | Encrypted transport for edge-exposed services | Anchor network policy |
| `STD-001` | Edge-Exposed Service Baseline | Standards referenced by policies |
| `EX-001` | Lab edge exposure for Open WebUI | Demonstrates the exception lifecycle |
| `RSK-001` | Unencrypted internal hop for Open WebUI | Demonstrates accepted-risk linkage |
| `CTL-001` | Cloudflare Access identity gate | Demonstrates compensating controls |
| `ADR-001` | Git-first governance & two-plane data model | Foundational architecture decision |
| `ADR-002` | Dedicated internal data plane | Data plane isolation decision |
| `ADR-003` | Ports-and-adapters product core | Environments are deployments, not specs |
| `ADR-004` | The wedge — Compose-first, adapter defaults | Solo-dev scope discipline; all options by contract |

## Quick start

```bash
# 1. Review governance content (the actual product material)
git clone <repo> ai-secops && cd ai-secops
cat policies/POL-001-*.yaml

# 2. Validate every artifact against its JSON schema (Phase 1 CI gate)
check-jsonschema --schemafile schemas/policy.schema.json governance/policies/*.yaml

# 3. Deploy the data plane to ai-secops01 (Phase 1)
cd ../infrastructure
docker stack deploy -c docker-stack.yml ai-secops
```

*Schema files and infrastructure files land in the same phase — see `ROADMAP.md` Phase 1.*

## Document index

| Document | Content |
|---|---|
| `docs/project-vision.md` | Vision, personas, AI operating principles, success metrics |
| `docs/architecture.md` | Platform architecture, trust boundaries, deployment topology |
| `ROADMAP.md` | Phased delivery plan and first-30-day execution |
| `CONTRIBUTING.md` | How to change governance and code, review matrix, conventions |

## License

To be decided before commercial distribution (consider BUSL/elastic variants for a
commercial product; governance content under CC-BY is an option). Tracked in
`ROADMAP.md` Phase 4.
