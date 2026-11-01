# test-data/ — Golden cases (Phase 1 contract, Phase 2 runner)

This directory holds the evidence that the engine means what the docs claim.
It starts as contract examples; in Phase 2 it becomes the golden test corpus
for `policy-engine`:

| Planned file | Content |
|---|---|
| `assets-sample.json` | assets matching the seeded corpus (ai-secops01 + Proxmox cluster + edge router), valid per `schemas/asset.schema.json` |
| `findings-tls-openwebui.json` | the POL-001/EX-001/RSK-001 finding used in the north-star scenario |
| `cases/` | one directory per evaluation case: input bundle + expected outcome record |

Golden rule: an engine change that flips any expected outcome here requires a
visible governance outcome — either the engine was wrong, or the corpus
(policy/exception/risk) needs review. Silence is not an option.
