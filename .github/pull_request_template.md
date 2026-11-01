<!-- AI-SecOps PR checklist — keep it short; CI enforces the machine parts. -->

## What

<!-- one paragraph; what changed and why -->

## Governance impact

- [ ] Corpus change? I ran `python scripts/check_references.py` and `check-jsonschema` locally (CI runs both)
- [ ] New/changed artifacts list their related ids (`POL-/EX-/RSK-/STD-/ADR-/CTL-`)
- [ ] No secrets, no credentials, no customer data in diffs
- [ ] Infrastructure changes keep the two-plane rule: `gov.*` written only by sync; no published ports introduced

## Product discipline (ADR-004)

- [ ] This change serves the Phase 2 wedge — no "all the options" creep
- [ ] New adapter behaviour is contract-first (documented before implemented)

## Verification

<!-- commands run / tests added / before-after evidence -->
