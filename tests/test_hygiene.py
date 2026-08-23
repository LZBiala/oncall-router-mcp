"""G5, G6 and G8. The gates that keep this repo honest rather than working.

G6 blocks: if it fails, nothing gets committed until it is fixed.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".toml", ".md", ".yml", ".yaml", ".txt", ".cfg"}


SELF = Path(__file__).resolve()


def _text_files() -> list[Path]:
    """Every text file except this one.

    A guard that scans the whole repo scans itself, and this file necessarily contains
    every string it forbids. Excluding it is the difference between a working check and
    a check that can only ever fail.
    """
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.resolve() == SELF:
            continue
        if any(part in {".git", "__pycache__", ".pytest_cache", ".venv"} for part in p.parts):
            continue
        if p.suffix.lower() in TEXT_SUFFIXES:
            out.append(p)
    return out


# ------------------------------------------------------------------ G6: blocks

def test_no_credential_shaped_strings() -> None:
    patterns = [
        re.compile(r"sk-[A-Za-z0-9]{16,}"),
        re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ]
    hits = []
    for f in _text_files():
        body = f.read_text(encoding="utf-8", errors="ignore")
        for pat in patterns:
            for m in pat.finditer(body):
                hits.append(f"{f.relative_to(ROOT)}: {m.group(0)[:40]}")
    assert not hits, "credential-shaped strings found: " + "; ".join(hits)


def test_no_outbound_network_in_the_source() -> None:
    """The server answers from a local file. Nothing here should reach the network."""
    banned = ("requests.", "urllib.request", "httpx.", "socket.socket", "aiohttp")
    hits = []
    for f in (ROOT / "src").rglob("*.py"):
        body = f.read_text(encoding="utf-8")
        for token in banned:
            if token in body:
                hits.append(f"{f.relative_to(ROOT)}: {token}")
    assert not hits, "network access in a server that reads a local file: " + "; ".join(hits)


def test_no_employer_identifying_content() -> None:
    """The sample catalog is fictional. Nothing from a real employer belongs here."""
    banned = ("wells fargo", "wellsfargo", "servicenow", "sharepoint", "splunk")
    hits = []
    for f in _text_files():
        body = f.read_text(encoding="utf-8", errors="ignore").lower()
        for token in banned:
            if token in body:
                hits.append(f"{f.relative_to(ROOT)}: {token}")
    assert not hits, "employer-identifying content: " + "; ".join(hits)


def test_no_third_party_imports() -> None:
    """Zero dependencies is a feature. tomllib is stdlib on 3.11+."""
    allowed_top = {
        "__future__", "argparse", "dataclasses", "datetime", "difflib", "io", "json",
        "os", "pathlib", "re", "subprocess", "sys", "tomllib", "typing",
    }
    hits = []
    for f in (ROOT / "src").rglob("*.py"):
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(?:from|import)\s+([A-Za-z_][\w]*)", line)
            if m and not line.strip().startswith("from ."):
                mod = m.group(1)
                if mod not in allowed_top and mod != "oncall_router":
                    hits.append(f"{f.relative_to(ROOT)}: {mod}")
    assert not hits, "unexpected import: " + "; ".join(hits)


# ------------------------------------------------------------------ G8: craft

def test_hyphens_only_and_no_slop() -> None:
    slop = ("best in class", "cutting-edge", "seamless", "leverage the", "world-class",
            "proven track record", "delve", "revolutioniz", "game-changer")
    problems = []
    for f in _text_files():
        body = f.read_text(encoding="utf-8", errors="ignore")
        if "—" in body or "–" in body:
            problems.append(f"{f.relative_to(ROOT)}: em or en dash")
        low = body.lower()
        for s in slop:
            if s in low:
                problems.append(f"{f.relative_to(ROOT)}: {s!r}")
    assert not problems, "; ".join(problems)


# ------------------------------------------------------------------ G5: drift

def test_the_committed_transcript_still_regenerates() -> None:
    """The docs are a claim. If the code changed, the claim must change with it."""
    committed = ROOT / "docs" / "TRANSCRIPT.md"
    assert committed.exists(), "run: python tools/demo.py --write"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "demo.py")],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == committed.read_text(encoding="utf-8"), (
        "docs/TRANSCRIPT.md is stale. Regenerate it with: python tools/demo.py --write"
    )
