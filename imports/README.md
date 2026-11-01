# imports/ — Bulk bootstrap inventory (Phase 2)

Before collectors run, hand-curated inventory gets the platform its first
usable asset model. CSV/JSON here is validated by `schemas/asset.schema.json`
and tagged `source: declared|imported` (not `discovered`).

| Planned file | Purpose |
|---|---|
| `assets.csv` | one row per asset: uid, kind, name, environment, exposure, criticality, owner_team, platform |
| `services.json` | exposure details per service (ports, protocols, endpoint) |
| `assets-sample.csv` | worked example matching the seeded corpus (ai-secops01, Proxmox cluster, edge router) |

Import rules:

- `asset_uid` is a stable slug; never rename — collectors must reconcile to it.
- Unknown `environment`/`exposure` values fail validation (shared vocabulary in
  `docs/architecture.md` §9).
- `source` is respected: imports never overwrite `discovered` observation data,
  they enrich it (declared overlay, `docs/architecture.md` §6).
