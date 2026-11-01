# Governance Corpus — Source of Truth

Everything in these directories is **the product**. Databases are projections
(ADR-001); if a fact isn't in a validated artifact here, it does not exist.

## Directories

| Directory | Prefix | Meaning |
|---|---|---|
| `policies/` | `POL-` | Mandatory rules the organisation enforces. Violations surface as findings evaluated by the engine. |
| `exceptions/` | `EX-` | Time-boxed, risk-linked, separately approved deviations. |
| `risks/` | `RSK-` | Risk statements with likelihood/impact, controls, and (when accepted) named acceptance + expiry. |
| `standards/` | `STD-` | Baselines (internal or derived from CIS/NIST/ISO) that policies cite. |
| `architecture/` | `ADR-` | Architecture Decision Records — proposed/accepted/superseded/rejected, never deleted. |
| `controls/` | `CTL-` | Compensating controls with verbatim evidence references; consumed by exceptions/risks. |

## Artifact anatomy (v1 vocabulary)

Every file starts with:

```yaml
api_version: ai-secops.gov/v1
kind: policy | exception | risk | standard | adr | compensating_control
id: <PREFIX>-<NNN>          # immortal identifier, never reused
version: X.Y.Z              # semver; intent changes are major → re-approval required
state/status: ...           # lifecycle state, see CONTRIBUTING review matrix
```

- **Scope selectors** share one vocabulary
  (`docs/architecture.md` §9: `environments`, `exposures`, `asset_kinds`,
  `platforms`, `asset_uids`, `tags`). Empty list = wildcard dimension.
- **Provenance** (`source_path`, `content_sha256`, `source_commit`) is stamped by the
  governance sync service — never typed by humans.
- **Approval names** are reviewer roles people hold, not free-text intent: use
  `ciso`, `ciso-delegate`, `security-architecture`, `platform-lead`,
  `infrastructure-lead`, `risk-owner:<team>`.

## Seeded corpus

| ID | File | Teaching point |
|---|---|---|
| POL-001 | `policies/POL-001-tls-for-edge-exposed-services.yaml` | Fully specified active policy with grace + evidence requirements |
| STD-001 | `standards/STD-001-edge-exposed-service-baseline.yaml` | Standard whose controls map to policies (EDGE-2/5 also feed `recommendation_only`) |
| EX-001 | `exceptions/EX-001-lab-edge-exposure-open-webui.yaml` | 90-day exception: policy ref, risk ref, approver ≠ requester, expiry |
| RSK-001 | `risks/RSK-001-unencrypted-internal-hop-open-webui.yaml` | Accepted risk with residual scoring, controls, review date |
| CTL-001 | `controls/CTL-001-cloudflare-access-identity-gate.yaml` | Compensating control with verbatim evidence + limitations |
| ADR-001 | `architecture/ADR-001-git-first-governance-two-plane-model.yaml` | Foundational data-model decision |
| ADR-002 | `architecture/ADR-002-dedicated-internal-data-plane.yaml` | Isolation of Postgres/Qdrant/Ollama from shared containers |
| ADR-003 | `architecture/ADR-003-ports-and-adapters-product-core.yaml` | Product core vs deployment adapters |
| ADR-004 | `architecture/ADR-004-the-wedge-compose-first-adapter-defaults.yaml` | Compose-only tier; one default adapter per family |

## Lifecycle rules (binding)

1. **Draft in PR.** Every change is a pull request referencing the decision that
   authorises it (CONTRIBUTING review matrix).
2. **4-eyes.** Requester never appears in their own `approvers:`.
3. **Exceptions always expire.** `valid_to` ≤ 90 days per approval; renewal = new PR.
4. **Risks must be linked.** No `EX-*` without a `risk_ref`; no silent risk acceptance
   (`acceptance:` block requires approval + `valid_until`).
5. **Supersede, never delete.** ADRs and policies carry `supersedes`/`superseded_by`.
6. **Review dates are promises.** `review_due`/`next_review` feed the review calendar;
   overdue items are a tracked defect.

## Adding a new artifact class

Changing the corpus vocabulary (new directory/prefix, new field in the shared
selector, new enum value) is an **architecture-level change**: open an ADR and a
`schemas/**` change PR together. JSON Schemas in `schemas/` are versioned with the
`api_version` header and validated in CI before the sync service ever sees them.
