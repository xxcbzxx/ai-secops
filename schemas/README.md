# schemas/ — JSON Schemas for every governance artifact (Phase 1)

One schema per artifact class, validated by CI on every PR
(`CONTRIBUTING.md` §4):

| Planned file | Validates |
|---|---|
| `policy.schema.json` | `policies/POL-*.yaml` |
| `exception.schema.json` | `exceptions/EX-*.yaml` |
| `risk.schema.json` | `risks/RSK-*.yaml` |
| `standard.schema.json` | `standards/STD-*.yaml` |
| `adr.schema.json` | `architecture/ADR-*.yaml` |
| `compensating-control.schema.json` | `controls/CTL-*.yaml` |
| `asset.schema.json` | ingest/imports asset contract |
| `finding.schema.json` | ingest finding contract |

Draft version: JSON Schema **2020-12**. Schemas change only together with the
`api_version` header in governance artifacts, in the same PR, reviewed by
security-architecture + platform-lead.

Manual local run:

```bash
check-jsonschema --schemafile policy.schema.json ../policies/*.yaml
```
