"""G5, G6 and G8. The gates that keep this repo honest rather than working.

G6 blocks: if it fails, nothing gets committed until it is fixed.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Scanning an allowlist of "text" suffixes is how a secret in .env or a .pem walks past a
# credential gate. Skip what is definitely binary and read everything else.
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".ico",
                   ".woff", ".woff2", ".ttf", ".pyc", ".exe", ".dll"}


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
        if p.suffix.lower() not in BINARY_SUFFIXES:
            out.append(p)
    return out


CREDENTIAL_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\w*\s*[:=]\s*['\"]?[^\s'\"]{12,}"),
]


def _credential_hits(files: list[Path]) -> list[str]:
    hits = []
    for f in files:
        try:
            body = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in CREDENTIAL_PATTERNS:
            for m in pat.finditer(body):
                hits.append(f"{f.name}: {m.group(0)[:32]}")
    return hits


# ------------------------------------------------------------------ G6: blocks

def test_no_credential_shaped_strings() -> None:
    hits = _credential_hits(_text_files())
    assert not hits, "credential-shaped strings found: " + "; ".join(hits)


def test_the_credential_gate_can_actually_fail(tmp_path: Path) -> None:
    """A gate nobody has watched fail is decoration. Plant one of each and prove it fires."""
    planted = [
        ("a.env", "ANTHROPIC_API_KEY=sk-ant-api03-" + "x" * 40),
        ("b.json", '{"token": "ghp_' + "y" * 36 + '"}'),
        ("c.pem", "-----BEGIN RSA PRIVATE KEY-----\nMIIEow==\n"),
        ("d.txt", "aws_access_key_id = AKIA" + "Z" * 16),
        ("e.yml", "password: hunter2-hunter2-hunter2"),
    ]
    files = []
    for name, body in planted:
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        files.append(p)
    caught = _credential_hits(files)
    missed = [n for n, _ in planted if not any(n in h for h in caught)]
    assert not missed, "the gate would not have caught: " + ", ".join(missed)


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


# SHA-256 of each banned term, so the gate can enforce "this name never appears in the
# repo" without the gate itself being the one place the name appears. An earlier version
# kept the terms in plain text here and excluded this file from its own scan, which made
# the published claim false one file away from where it was made. Hashes fix both: this
# test needs no self-exclusion, and the scan below covers this file too.
_BANNED_HASHES = frozenset({
    "311ff2d71234e230eb559f843c1f5c548302246a365221713da47017e656e672",
    "62fd6c7860342a316c30c63d12f860125feccbf30e914d51dee6c2fdced4f606",
    "b5738c169b693bee89e1b74ebd48e0dfa53a34e8571790b7727721a0bfadc470",
    "9211da2bdb79a1bf369af43968fb152c553345fe409cd7e4bc5c43f9003d6ded",
    "101e21bef69a3df68f36ca31deb6616f10cc70e4bae8eed9ce83a9effb1fd5cb",
})


def _employer_hits(files: list[Path], banned_hashes: frozenset[str]) -> list[str]:
    """Hash every word, word pair, and joined word pair; report files matching the set."""
    hits = []
    for f in files:
        try:
            body = f.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        words = re.findall(r"[a-z0-9]+", body)
        candidates = set(words)
        for a, b in zip(words, words[1:]):
            candidates.add(f"{a} {b}")
            candidates.add(a + b)
        for c in candidates:
            if hashlib.sha256(c.encode()).hexdigest() in banned_hashes:
                try:
                    hits.append(str(f.relative_to(ROOT)))
                except ValueError:   # a planted tmp file in the self-test lives outside ROOT
                    hits.append(f.name)
                break
    return hits


def test_no_employer_identifying_content() -> None:
    """The sample catalog is fictional. Nothing from a real employer belongs here.

    Scans every text file including this one: with hashed terms there is nothing here
    a scan could object to, which is the whole point.
    """
    hits = _employer_hits(_text_files() + [SELF], _BANNED_HASHES)
    assert not hits, "employer-identifying content in: " + "; ".join(hits)


def test_the_employer_gate_can_actually_fail(tmp_path: Path) -> None:
    """Prove the hash scan fires, using a synthetic term so nothing real is printed."""
    # two words, matching the shape of the real terms: the scanner hashes unigrams,
    # bigrams, and joined bigrams, so a longer phrase would never be a candidate
    term = "synthetic employer"
    h = frozenset({hashlib.sha256(term.encode()).hexdigest()})
    clean = tmp_path / "clean.md"
    clean.write_text("an innocuous file about gateways", encoding="utf-8")
    dirty = tmp_path / "dirty.md"
    dirty.write_text(f"notes mentioning {term} in passing", encoding="utf-8")
    caught = _employer_hits([clean, dirty], h)
    assert caught == ["dirty.md"], caught


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
