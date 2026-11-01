# Project Vision — AI-SecOps

Status: Accepted (ADR-001) · Owner: security-architecture · Updated: 2026-11-01

---

## 1. Elevator pitch

> Every organisation writes security governance — policies, exceptions, accepted risks,
> standards, architecture decisions — and then loses track of it. Spreadsheets drift,
> wikis rot, and the gap between *documented intent* and *operational reality* becomes
> the real attack surface.
>
> **AI-SecOps makes your governance machine-readable, machine-challenged and
> measurable.** It evaluates real findings against real policies, knows which
> exceptions and accepted risks legitimately cover violations, and uses an on-premise
> AI to explain posture, tradeoffs and options — always with citations, never with
> authority. Engineers stay in command; the platform does the remembering,
> correlating and questioning.

## 2. The five capabilities (inherited from the upstream mission)

| Capability | What it means in AI-SecOps |
|---|---|
| **Asset Intelligence** | A continuously reconciled inventory of assets, services, exposure and ownership — discovered from Proxmox, Docker/Swarm, Cisco, OpenWRT and Cloudflare, enriched with declared context. |
| **Threat Intelligence** | CVEs (NVD), CISA KEV, GitHub Advisories and vendor feeds correlated to *your* software inventory — with KEV × edge-exposure prioritisation. |
| **Policy Intelligence** | The deterministic evaluation engine: findings → policies → exceptions → accepted risks → compensating controls → the five compliance outcomes. |
| **AI-Guided Analysis** | On-premise LLM (Ollama/Qwen3 · DeepSeek-R1) that explains, teaches and recommends, grounded strictly in the internal governance corpus. |
| **Risk Correlation** | Findings, threats, exceptions and decisions linked to risks so that risk acceptance is a living, reviewed, expiring state — not a signed PDF in a drawer. |

## 3. Product pillars

1. **The registry is the product.** If your governance corpus is wrong, everything else
   is decoration. Hence: Git-first, schema-validated, review-gated, versioned.
2. **Posture is a projection, not a pile.** Posture exhibitions for CISO reports are
   computed from evaluations, not hand-maintained slides.
3. **Every answer is traceable.** Any recommendation must trace to artifact IDs
   (`POL-`, `EX-`, `RSK-`, `CTL-`, `ADR-`), asset context, or threat entry — or explicitly
   say: *"No internal policy covers this; industry best practice, labelled advisory-only."*
4. **The platform is its own best demo.** Its own deployment must pass its own
   policies (encrypted transport, auth, logging) — the platform eats its own data.

## 4. Personas and jobs-to-be-done

| Persona | Primary jobs |
|---|---|
| **Engineer** | "What exactly am I expected to do about this finding, per *our* policy — not generic docs? What's the deadline, what grace, what's already accepted?" |
| **Infrastructure team** | "Which of my VMs/services are edge-exposed, which risks have been accepted about them, and what do I need to fix before the next review?" |
| **Security team** | "Which violations are covered by legitimate exceptions vs. true gaps? What's expiring this month? Which actions are past SLA?" |
| **Security architect** | "Where does architecture contradict our recorded decisions? What will breaking this ADR cost in policy terms?" |
| **CISO** | "Show me posture and the story behind it: accepted risks, compensating controls, review debt — with the audit trail." |

## 5. AI operating principles — the grounding contract

This is the constitutional document for the AI layer (enforced from Phase 3):

1. **Internal context first.** Policies, exceptions, risks, ADRs, standards, controls
   and asset context have precedence — in that order — over generic knowledge.
2. **Generic best practice is a fallback, not a peer.** Used only when no internal
   policy covers the domain, and always labelled *"advisory-only, no internal policy"*.
3. **Mandatory citations.** Recommendations cite artifact ID + version + asset context
   + threat source. Uncited recommendations are system failures.
4. **Refusal mode is valid.** If the corpus lacks grounding, the AI says so and asks
   what should be created (e.g. "raise a policy draft"), instead of inventing authority.
5. **Advisory-only authority.** AI output can never: change state, grant exceptions,
   accept risks, approve anything, or bypass the deterministic engine.
6. **Explain tradeoffs.** For any recommendation, the AI must name: benefits, costs,
   risks, deadline/residual risk, and who the requesting/approving roles are.
7. **Teach.** The platform is a mentor — it educates engineers on the *why* behind a
   policy, using the linked standards (CIS/NIST/ISO mappings) and historic decisions.

## 6. Human decision gates (where machines must stop)

| Decision | Human gate |
|---|---|
| Approve a policy | CISO delegate + security-architecture (PR review) |
| Grant an exception | Named approver ≠ requester; needs a risk_ref and expiry |
| Accept a risk | Risk owner signs in-file acceptance; review date is mandatory |
| Verify a compensating control | Evidence is verbatim + hashed; a human verifies references and dates |
| Publish a report | AI drafts, human approves publish |
| Override an engine outcome | Only as a Git change + ADR/exception — never an inline DB edit |

## 7. What we deliberately are NOT

- **Not a scanner.** We correlate others' evidence — collectors, imports, feeds.
- **Not an auto-remediator.** No tool-level write actions to infrastructure, ever.
- **Not a GRC suite clone.** Workflow theatre (endless forms) is an anti-goal;
  the unit of work here is a *schema-validated artifact in Git*.
- **Not a cloud-dependent product.** The deployment must stay functional, private
  and fully local without any SaaS dependency (except optional edge routing/CDN).

## 8. Success metrics (target state)

| Metric | Definition | Target |
|---|---|---|
| Governance coverage | % of edge-exposed services covered by ≥ 1 active policy | ≥ 95% |
| Exception hygiene | % of active exceptions with risk_ref, approver, unexpired `valid_to` | 100% |
| Review debt | Artifacts past `review_due` or past control re-verification | ≤ 5% |
| Decision latency | PR → merged governance decision median | ≤ 3 working days |
| Grounding rate | % of AI recommendations with ≥ 1 verification path | ≥ 95% |
| Posture story | % of violations classified into a documented outcome bucket | 100% |

## 9. North-star scenario

> A discovery adapter reports a new finding: a tunnel-exposed admin UI reachable
> without direct TLS termination. The engine classifies it, within seconds, as
> **Violation-with-Exception**, citing `EX-001` (90-day window), `RSK-001` (accepted
> residual risk), and `CTL-001` (Cloudflare Access control with evidence hash). The
> engineer asks "why?"; the AI explains with citations and shows the expiry date,
> the renewal rule, and the mitigation plan. Nobody opened a spreadsheet.

That one loop — **finding → policy → exception → risk → control → explanation →
decision** — is the whole product. Everything in the roadmap exists to make it true
at scale.
