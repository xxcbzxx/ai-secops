# threat-intel/ — Feed connectors & correlation (Phase 3)

Design-first area: connectors are NOT implemented in Phase 1 (`ROADMAP.md`).
Repository artefacts land in this order:

1. `docs/threat-intelligence.md` (Phase 1) — feed map, licensing, TLP, correlation strategy.
2. `imports/` (Phase 3) — manual JSONL entry format for early, reviewed intake:
   `{"threat_uid": "nvd:CVE-...", ..., "tlp": "amber", ...}` — one entry per line.
3. Connectors (Phase 3): NVD (API key), CISA KEV (hourly), GitHub Security
   Advisories, vendor RSS — all deduplicated by fingerprint, all append-only.

Correlation strategy (DB-backed, designed now):

```
ops.threat_entries (affected_products: CPE/purl)
        ⋈ ops.asset_software (observed CPE/purl)
        → candidate exposure list
        → KEV flag × (edge_exposed OR public) = priority queue
```

Rules:

- Feeds are checked against their license terms before ingestion code exists
  (NVD terms, MITRE/CPE dictionary, GitHub/OSV licensing).
- Corpus is internal-confidential regardless of feed (TLP:RED as data plane).
- A threat entry never modifies governance state — it enriches evaluations
  and advisory context only.
