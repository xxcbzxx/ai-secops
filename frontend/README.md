# frontend/ — Operator UI (Phase 2)

React + TypeScript (Vite) read-only operator surface built on the backend API.

Planned pages, in build order:

1. **Posture dashboard** — counts per engine outcome over time, drill-down to findings.
2. **Registries** — assets, services, policies, exceptions, risks, standards, ADRs, controls (read-only projection).
3. **Review queues** — expiring exceptions, risks past review date, controls past verification.
4. **Finding detail** — the citation trail: policy ↔ exception ↔ risk ↔ control ↔ ADR.
5. **Reports** — generated posture/compliance documents (Phase 4; AI drafts, human publishes).

Design rule: the UI mirrors Git; it never writes governance state. Changes are
always driven through Git PRs (`CONTRIBUTING.md`) — the UI may deep-link to a PR
but never replaces it. Approval flows land in Phase 4 and still write via PR.
