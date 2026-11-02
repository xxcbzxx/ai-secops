#!/usr/bin/env python3
"""AI-SecOps weakness sweep — secrets & TODO markers must not ship in the
governance corpus (the "Weakness sweep" step of validate-governance.yml).

Why a script: CI run #1 failed in <1 s because the previous inline `grep`
was a quoting puzzle — a ["'"] character class cannot be spliced inside a
single-quoted shell string, so the whole check died on a bash syntax error
before scanning a single line. A script file is transport- and
shell-immune, unit-testable (--self-test) and re-usable from anywhere:

    python scripts/weakness_sweep.py              # scan github corpus
    python3 ~/ai-secops/scripts/weakness_sweep.py # same, on the VM

What it scans: every *.yaml / *.yml under the six governance dirs
(policies, exceptions, risks, standards, architecture, controls).

Finding classes (either one fails the build, exit code 1):
  SECRETS  a key whose name suggests a credential (password, api key,
           secret, token, credentials, ...) assigned a secret-SHAPED
           value: a contiguous run of >= 12 secret-ish characters
           (alnum + base64 symbols), quoted or bare. Values are always
           MASKED in output — Actions logs are public; nothing echoes.
  TODO     TODO / FIXME / XXX markers (case-sensitive, word-bounded) —
           unfinished governance is not shipped governance.

Exit codes: 0 = clean / self-test passed; 1 = findings / self-test
mismatch; 2 = usage/configuration error (e.g. a corpus dir is missing).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIRS = ("policies", "exceptions", "risks", "standards",
               "architecture", "controls")
GLOBS = ("*.yaml", "*.yml")

SECRET_LINE_RE = re.compile(
    r"(?i)(password|passphrase|api[_-]?key|secret|token|credentials?)"
    r'\s*[:=]\s*["\']?([A-Za-z0-9+/=_-]{12,})["\']?')
TODO_RE = re.compile(r"(?<![A-Za-z])(TODO|FIXME|XXX)(?![A-Za-z])")

OK, FAIL, USAGE = 0, 1, 2


def _utf8_streams() -> None:
    """Locale-proof stdout/stderr: Windows consoles may default to cp1252,
    which cannot encode ✓/✗ — rebind to UTF-8 (backslash-safe) so the sweep
    behaves identically on Windows, the runner, and the VM."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and \
                getattr(stream, "encoding", "").lower() not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, OSError):
                pass


_utf8_streams()


def mask(value: str) -> str:
    """Never echo a matched value; CI logs on a public repo are world-read."""
    return f"{value[:2]}…(len={len(value)})"


def scan_text(text: str) -> list[tuple[str, int, str]]:
    """Scan one document; return (class, lineno, detail) findings."""
    findings: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        m = SECRET_LINE_RE.search(line)
        if m is not None:
            key = m.group(1).strip().lower()
            findings.append((
                "SECRETS", lineno,
                f"key '{key}' assigned a secret-shaped literal "
                f"(masked: {mask(m.group(2))})"))
        m = TODO_RE.search(line)
        if m is not None:
            findings.append((
                "TODO", lineno,
                f"unfinished-governance marker '{m.group(1)}' in artifact text"))
    return findings


def scan_corpus() -> tuple[int, list[tuple[str, str, int, str]]]:
    """Scan the six governance dirs; return (n_files, [relpath, class, line, detail])."""
    scanned = 0
    hits: list[tuple[str, str, int, str]] = []
    for name in CORPUS_DIRS:
        d = REPO_ROOT / name
        if not d.is_dir():
            print(f"error: expected governance dir '{name}' not found under "
                  f"{REPO_ROOT} — repository drift", file=sys.stderr)
            sys.exit(USAGE)
        for path in sorted(p for pat in GLOBS for p in d.glob(pat)):
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            for cls, lineno, detail in scan_text(text):
                hits.append((str(path.relative_to(REPO_ROOT)), cls, lineno, detail))
    return scanned, hits


# ------------------------------------------------------------------ self-test
# fixtures: (line, expected class or None). Values are obviously synthetic
# fixtures, not secrets; the sweep would only SEE them in --self-test runs.
FIXTURES: list[tuple[str, str | None]] = [
    ('password: "fixedexampleofasecret"', "SECRETS"),
    ("api_key: 'abcdef123456ghij'", "SECRETS"),
    ("token: 01234567890abcdeffedcba", "SECRETS"),
    ("description: TODO replace the acting delegate name", "TODO"),
    ("notes: FIXME before promotion review", "TODO"),
    ("summary: Quarterly control review by the asset owner", None),
    ("secret_reference: POL-001-appendix-a", None),
    ("password_policy: follow COMPANY base standard", None),
]


def self_test() -> int:
    """Prove the detectors fire on bad fixtures and stay silent on clean ones."""
    bad = 0
    for line, expected in FIXTURES:
        got = scan_text(line)
        classes = [cls for cls, _l, _d in got]
        if expected is None:
            ok = classes == []
            shown = "no finding" if ok else f"unexpected {classes}"
        else:
            ok = classes == [expected]
            shown = expected if ok else f"got {classes or 'nothing'}"
        label = "OK  " if ok else "FAIL"
        print(f"{label} {line[:58]:<58} -> {shown}")
        bad += not ok
    if bad:
        print(f"✗ self-test: {bad}/{len(FIXTURES)} fixture(s) wrong")
        return FAIL
    print(f"✓ self-test: {len(FIXTURES)}/{len(FIXTURES)} fixture assertions passed")
    return OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="AI-SecOps governance weakness sweep "
                    "(secrets & TODO markers; fails the build on findings)")
    ap.add_argument("--self-test", action="store_true",
                    help="run detector fixtures instead of scanning")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    print(f"== weakness sweep — {len(CORPUS_DIRS)} governance dir(s) "
          f"under {REPO_ROOT.name}/ ==")
    scanned, hits = scan_corpus()
    if hits:
        for rel, cls, lineno, detail in hits:
            print(f"FAIL  {cls:<7} {rel}:{lineno}  {detail}")
        print(f"✗ {len(hits)} finding(s) across {scanned} artifact(s) — "
              "never ship secrets or unfinished governance")
        return FAIL
    print(f"OK    {scanned} governance artifact(s) scanned — "
          "no secrets, no TODO markers")
    return OK


if __name__ == "__main__":
    sys.exit(main())
