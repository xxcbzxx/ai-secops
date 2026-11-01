# policy-engine/ — Deterministic evaluation engine (Phase 2)

The engine is the enforcement boundary of AI-SecOps: a **pure function**
finding + context → decision record. No network, no LLM, no randomness
(`docs/architecture.md` §8).

Pipeline (design; implementation starts Phase 2):

1. Scope → `not_applicable`
2. Conformance → `compliant`
3. Exception → `violation_with_exception`
4. Accepted risk → `accepted_risk`
5. Compensating controls → severity/recommendation adjustment
6. Fall-through → `violation`
7. Standard-only domain → `recommendation_only`

Deliverables tracked in `ROADMAP.md` Phase 1 (design walkthrough) and
Phase 2 (implementation + golden tests in `test-data/`).

Working language: Python 3.12, package `policy_engine`, importable and
dockerised as part of the backend in Phase 2.
