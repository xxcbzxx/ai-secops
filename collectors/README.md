# collectors/ — Discovery & evidence adapters (Phase 2)

Collectors observe the operational estate and push findings/inventory into the
backend API. They are **read-only** against targets, idempotent, and scoped.

| Planned collector | Target | Protocol | Notes |
|---|---|---|---|
| `proxmox/` | VM/CT inventory | Proxmox API | assets + per-guest metadata |
| `portainer/` | Docker/Swarm workloads | Portainer API | exposure mapping (published ports, networks) |
| `cloudflare/` | Tunnel + Access surfaces | Cloudflare API | edge_exposed service truth |
| `network/` | Cisco + OpenWRT estate | SNMP / SSH | optional; may ship as n8n workflows first |
| `n8n-workflows/` | quick-win collectors | HTTP | use only until a Python collector exists; workflows must be exported to Git (config-dir pattern) |

Collector contract:

- Authenticate with one scoped key each; least privilege.
- Emit `schemas/asset.schema.json` + `schemas/finding.schema.json` payloads.
- Fingerprints make re-runs idempotent (no duplicate findings).
- Every run logs observed counts to the audit trail; failure is visible, not silent.
