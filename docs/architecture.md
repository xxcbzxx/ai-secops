# Architecture — AI-SecOps (product + reference deployment)

Status: Accepted (ADR-001 … ADR-004) · Owner: security-architecture · Updated: 2026-11-01

---

## 1. The rule that fixes everything: product ≠ deployment

The platform is defined once as **product core + adapter families**. A specific
environment — from a solo engineer's homelab (`ai-secops01`: Proxmox, OpenWRT,
n8n, Portainer, Cloudflare Tunnel, Ollama) to an enterprise cluster — is just a
**deployment that selects adapters**. No homelab-specific choice is baked into
the product definition.

| Layer | Product core (fixed) | Adapter family (pluggable) |
|---|---|---|
| Ingress | Assumes HTTP + auth at the edge | Reverse proxy: Traefik/Nginx/Caddy/tunnel (customer choice) |
| Identity | Sessions, RBAC decisions, audit | Local accounts + API keys (default) · OIDC/SSO · customer IdP |
| LLM | Grounding contract, citation checks (docs/project-vision.md §5) | Local Ollama (default) · OpenAI-compatible/BYOK · Anthropic · (later) vendor-hosted |
| Governance store | File format, schema validation, sync semantics | Filesystem volume (default) · Git forge adapters (GitHub/GitLab/Gitea/Bitbucket) · NAS/SharePoint via file-share sync (Graph API adapter later) |
| Findings input | Ingest contract, fingerprinting, dedupe | Generic JSON ingest API (v1) · scanner adapters (Wazuh, OpenVAS, Trivy…) later |
| Discovery | Inventory reconciliation logic | Proxmox / Portainer / generic SNMP adapters (later) |
| Frameworks | Mapping schema, pack loader | CIS Controls pack (first) · NIST CSF · ISO 27001 · region-specific packs |

**AI-SecOps runs its own data plane everywhere** (PostgreSQL, Qdrant — ADR-002):
the product never depends on customers' general-purpose shared containers.

## 2. Deployment tiers

| Tier | Target | Shape | Status |
|---|---|---|---|
| **T1 — Compose** (v1 shipped) | Solo–SMB, departmental, air-gapped | `docker compose` single host; all internal networks; volumes for data + governance store; NAS/SharePoint reach via mounted file share | **default** |
| T2 — K8s/Helm (post-wedge) | Enterprise scale, HA expectations | Helm chart, HA Postgres, queued workers, secrets mgmt | Phase 5 |
| SaaS (only if demand proves) | Managed subscriptions | Multi-tenant stack; not built before revenue signal | undecided |

Principle: **one deployment tier until traction** (solo-dev wedge, ADR-004).
Everything above T1 stays *designable* (adapter contracts) but unbuilt.

## 3. Product core services (identical in every deployment)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Product core (runs as containers on one compose network set)        │
│                                                                      │
│  api ─────── ingest + registry + reports (stateless HTTP)           │
│  engine ──── deterministic policy evaluation (pure function)        │
│  sync ────── governance store │→ validated projection in Postgres   │
│  web ─────── operator UI (read-only registries, posture, reviews)   │
│  agent ───── grounded assistant (Phase 3; cites corpus only)        │
│                                                                      │
└──────┬───────────────────┬──────────────────────┬───────────────────┘
       │ adapter           │ adapter              │ adapter
   [ingress/auth]      [governance store]      [LLM provider]
       │                   │                      │
   customer proxy     filesystem / forge /    ollama / BYOK /
   + API keys +       nas/sharepoint sync     anthropic / hosted
   local account/OIDC (volume)                 (config-selected)
       │
   postgres ◀── two-plane data model (ADR-001) ──▶ qdrant (Phase 3 vectors)
```

Every core service is stateless except `postgres`; scale path = run two
`api` replicas behind the customer's proxy (T2 adds queuing).

## 4. Adapter contracts (the enterprise-still-hard)

1. **Identity adapter** — three support levels shipped as *options*, not roadmap debt
   (you chose "all supported"):
   - collectors/services: scoped, rotatable **API keys** (always on);
   - humans: **local accounts** (default for T1) **and/or** **OIDC SSO** to the
     customer's Keycloak/Authentik/Auth0/Microsoft Entra (config flag; same RBAC
     underneath: `viewer|analyst|governance-lead|admin`).
2. **LLM adapter** — OpenAI-compatible `chat/completions` as the wire contract;
   `ollama` (local), `openai` (BYK key), `byo-endpoint` (customer URL) all speak it.
   Grounding rules identical regardless of which provider answers.
3. **Governance store adapter** — pull-model: sync reads artifacts from a canonical
   directory tree (`policies/ exceptions/ risks/ standards/ architecture/ controls/`).
   - `filesystem` (default): bind-mount; a NAS/SharePoint that syncs a folder
     into that mount works with **zero extra code** (2-way sync tools caveat:
     treat the mount as authoritative).
   - forge adapters: implemented LATER — read-only polling (no webhooks) of the
     same directory layout on a branch.
4. **Framework pack adapter** — versioned mapping files shipped under `standards/`
   + loader: control text, control id, framework refs, evidence hints. **First
   pack: CIS Controls v8.1** (shipping references/mappings, not verbatim CIS text —
   licensing note below). Same loader later consumes NIST CSF / ISO 27001 packs so
   any country-relevant framework is a data addition, not code.
5. **Findings source adapter** — v1 ships the **generic JSON ingest API** only:
   documented schema (`schemas/finding.schema.json`), fingerprint dedupe,
   collector API keys. Scanner-specific adapters (Wazuh/OSQuery/OpenVAS/Trivy)
   become thin translators on top of the same contract.

## 5. Reference deployment — `ai-secops01` (development/feedback environment)

This homelab is the dogfooding site — its specifics live here and in
`infrastructure/`, not in the product definition:

- Single host, Debian 13, Docker (Compose mode; Swarm inherited from the host is
  available but T1 uses plain Compose).
- Networks: `edge` (web UI + api behind the tunnel), `app`, `data` (postgres/qdrant internal-only) and `ai` (optional profile).
- Cloudflare Tunnel with Access policy = the ingress adapter in use (equivalent
  to any enterprise proxy).
- Ollama optional via `profiles: ["ai"]` — no product functionality depends on it in Phase 1.
- This environment documents an edge-exposure worked example: POL-001 / EX-001 /
  RSK-001 / CTL-001 corpus remains the golden teaching trail (north-star loop).
- This is where adapters get tested before being offered to customers,
  Proxmox/OpenWRT/n8n observations enter only as collector work.

## 6. Two-plane data model (ADR-001) — unchanged by the enterprise pivot

- **Governance plane = Git/store artifacts** (human-decided, PR-reviewed, 4-eyes)
- **Operational plane = PostgreSQL** (assets, services, software, findings,
  evaluations, threat entries, reports, audit trail — machine-written)
- Bridges: optional declared "asset cards"; the engine joins both planes; DB
  governance tables are readonly outside the sync service.

## 7. Evaluation engine (unchanged in the enterprise pivot; summary)

Pure function finding + context → decision record; pipeline
scope → conformance → exception → accepted-risk → compensating-control →
violation / recommendation-only; outputs a seven-status enum (the five required
outcomes + `not_applicable`, `under_review`). The full engine design document
lands in Phase 1 per `ROADMAP.md` (workstream 1.6).

## 8. Security controls (v1 commitments — enterprise gates moved IN)

| Control | v1 commitment |
|---|---|
| Ingress | Only through the customer's proxy; **no published ports** from data/ai nets |
| AuthN | API keys (collectors) + local accounts (v1 default); **OIDC adapter shipped at feature-complete in v1.x** (customer IdP of choice) |
| RBAC | `viewer / analyst / governance-lead / admin` in the data model from day one |
| Audit | Every state transition + ingest event recorded in `ops.audit_events`; export JSON |
| Data | Customer data stays local by default; the LLM adapter visibly SHOWS if BYOK sends anything external |
| Secrets | Compose secrets / K8s secrets; never in artifacts |
| Platform self-check | The platform runs its own baseline (STD-001) on its deployment — dogfood gate |

## 9. Licensing & content obligations (commercial gates, tracked in ROADMAP)

| Item | Rule |
|---|---|
| CIS Controls content | Mapping only (control numbers/titles/refs); verbatim text redistribution needs CIS written permission |
| NVD/CVE/KEV/GHSA | Check oracle/API terms before ingestion code ships |
| Code license | Decide before sale (BUSL vs Apache open-core); governance corpus under CC-BY candidate |
| Trademarks | "AI-SecOps" + brand needed for commercial identity |

## 10. Decision record index (see `architecture/` directory)

| ADR | Title | Status |
|---|---|---|
| ADR-001 | Git-first governance & two-plane data model | accepted |
| ADR-002 | Dedicated internal data plane (owned instances) | accepted |
| ADR-003 | Ports-and-adapters product core; environments = deployments, not specs | accepted |
| ADR-004 | The wedge: Compose-only tier, adapter defaults, all-options architecture | accepted |

## 11. What changed vs the first draft of these docs

| Earlier (homelab-shaped) | Now (product-standard) |
|---|---|
| Ollama/Open WebUI/n8n/Proxmox as requirements | Bundled as adapter examples, used in the reference deployment only |
| Cloudflare Tunnel as the edge | Any ingress with authentication; tunnel = one adapter |
| Swarm/as-stack deployment | Compose-first tier (T1), Helm designed for later |
| RBAC/SSO "Phase 4" | AuthN adapter config from v1; RBAC matrix in data model day one |
| One framework anchor assumption | Framework pack loader; CIS pack first, others add by data |
| Engine-only outcomes listed | Same engine (unchanged), but surrounded by pluggable contracts |

## 12. Open questions (non-blocking, tracked)

1. Which reverse proxy to bless in docs (Traefik recommended for compose tiers)?
2. Do we support an S3/MinIO adapter for org report storage (large PDFs)?
3. Windows/Mac packaging beyond compose (installer? docker desktop profiles)?
4. Is a "gray release" playbook needed for air-gapped customers (offline pack)?
