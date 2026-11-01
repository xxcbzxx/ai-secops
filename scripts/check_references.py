#!/usr/bin/env python3
"""AI-SecOps referential integrity checker (CI gate #2).

Verifies that every artifact reference in the governance corpus resolves to
an artifact that exists in the repository. Exit 1 (CI-fail) on any violation.

Scope of checks:
  - policy.related   → policies / risks / exceptions / standards / adrs
  - policy.control_refs.standard → standards/*.yaml id
      (control VALUES, e.g. EDGE-1, live inside the standard's controls[])
  - exception.policy_ref.id → policies; exception.risk_ref.id → risks
      exception.compensating_controls[] → controls
  - risk.related / risk.existing_controls[] / acceptance-linked ids
  - standard.mapped_policies[] (inside controls) → policies
  - ctl.covers_risks[] → risks; supports_exceptions[] → exceptions
  - adr.related / supersedes[] / superseded_by[] → adrs
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DIRS = {
    "POL": ("policies", "policy.schema.json"),
    "EX": ("exceptions", "exception.schema.json"),
    "RSK": ("risks", "risk.schema.json"),
    "STD": ("standards", "standard.schema.json"),
    "ADR": ("architecture", "adr.schema.json"),
    "CTL": ("controls", "compensating-control.schema.json"),
}


def load_corpus() -> tuple[dict[str, dict], dict[str, set[str]], list[str]]:
    artifacts: dict[str, dict] = {}
    errors: list[str] = []
    for prefix, (folder, schema_file) in DIRS.items():
        d = ROOT / folder
        if not d.exists():
            continue
        for f in sorted(d.glob("*.yaml")):
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 (report, don't crash)
                errors.append(f"{f.relative_to(ROOT)}: YAML parse error: {exc}")
                continue
            if not isinstance(doc, dict):
                errors.append(f"{f.relative_to(ROOT)}: not a mapping")
                continue
            uid = doc.get("id", "")
            if not re.fullmatch(rf"{prefix}-[0-9]{{3}}", str(uid)):
                errors.append(f"{f.relative_to(ROOT)}: bad or missing id '{uid}'")
                continue
            artifacts[uid] = doc
            # cross-check folder vs id prefix
            if not str(uid).startswith(prefix):
                errors.append(f"{f.relative_to(ROOT)}: id {uid} outside {folder}/")
    # standards keep a registry of control ids for policy control_refs checks
    std_controls: dict[str, set[str]] = {}
    for uid, doc in artifacts.items():
        if uid.startswith("STD-"):
            ids = {c.get("id") for c in doc.get("controls", []) if isinstance(c, dict)}
            std_controls[uid] = {i for i in ids if i}
    return artifacts, std_controls, errors


def rlist(doc: dict, *path: str) -> list[str]:
    node: object = doc
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
        if node is None:
            return []
    return node if isinstance(node, list) else []


def rid(doc: dict, *path: str) -> str | None:
    node: object = doc
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
        if node is None:
            return None
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return node.get("id")
    return None


def check() -> list[str]:
    artifacts, std_controls, errors = load_corpus()  # type: ignore[misc]

    def exists(uid: object, kinds: tuple[str, ...]) -> bool:
        """A reference is valid iff a string id in the corpus; non-string refs
        (dict/None) are reported as errors, never crash the checker."""
        return isinstance(uid, str) and any(
            uid.startswith(k) and uid in artifacts for k in kinds)

    KIND_PREFIX = {
        "policies": ("POL-",),
        "exceptions": ("EX-",),
        "risks": ("RSK-",),
        "standards": ("STD-",),
        "adrs": ("ADR-",),
        "controls": ("CTL-",),
    }
    for uid, doc in artifacts.items():
        rel = doc.get("related", {}) if isinstance(doc.get("related"), dict) else {}
        for group in KIND_PREFIX:
            for ref in rlist(doc, "related", group):
                if not exists(ref, KIND_PREFIX[group]):
                    errors.append(f"{uid}.related.{group}: unknown artifact '{ref}'")

    # POL-*
    for uid, doc in artifacts.items():
        if not uid.startswith("POL-"):
            continue
        for cr in rlist(doc, "control_refs"):
            std = cr.get("standard") if isinstance(cr, dict) else None
            ctl = cr.get("control") if isinstance(cr, dict) else None
            if std and not exists(std, ("STD-",)):
                errors.append(f"{uid}.control_refs: unknown standard '{std}'")
            if std and ctl and ctl not in std_controls.get(std, set()):
                errors.append(f"{uid}.control_refs: standard {std} has no control '{ctl}'")

    # EX-*
    for uid, doc in artifacts.items():
        if uid.startswith("EX-"):
            p = rid(doc, "policy_ref")
            r = rid(doc, "risk_ref")
            if not exists(p, ("POL-",)):
                errors.append(f"{uid}.policy_ref: unknown policy '{p}'")
            if not exists(r, ("RSK-",)):
                errors.append(f"{uid}.risk_ref: unknown risk '{r}' (mandatory)")
            for c in rlist(doc, "compensating_controls"):
                cid = c.get("id") if isinstance(c, dict) else c
                if not exists(cid, ("CTL-",)):
                    errors.append(f"{uid}.compensating_controls: unknown control '{cid}'")

    # RSK-*
    for uid, doc in artifacts.items():
        if not uid.startswith("RSK-"):
            continue
        for c in rlist(doc, "existing_controls"):
            if not exists(c, ("CTL-",)):
                errors.append(f"{uid}.existing_controls: unknown control '{c}'")

    # STD controls → policies
    for uid, doc in artifacts.items():
        if uid.startswith("STD-"):
            for c in rlist(doc, "controls"):
                if isinstance(c, dict):
                    for p in c.get("mapped_policies", []):
                        if not exists(p, ("POL-",)):
                            errors.append(f"{uid}.controls[{c.get('id')}]: unknown policy '{p}'")

    # CTL-*
    for uid, doc in artifacts.items():
        if uid.startswith("CTL-"):
            for r in rlist(doc, "covers_risks"):
                if r and not exists(r, ("RSK-",)):
                    errors.append(f"{uid}.covers_risks: unknown risk '{r}'")
            for e in rlist(doc, "supports_exceptions"):
                if e and not exists(e, ("EX-",)):
                    errors.append(f"{uid}.supports_exceptions: unknown exception '{e}'")

    # ADR-*
    for uid, doc in artifacts.items():
        if uid.startswith("ADR-"):
            for field in ("supersedes", "superseded_by"):
                for ref in rlist(doc, field):
                    if not exists(ref, ("ADR-",)):
                        errors.append(f"{uid}.{field}: unknown adr '{ref}'")

    return errors


def main() -> int:
    errors = check()
    if errors:
        print("✗ referential integrity failures:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✓ referential integrity OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
