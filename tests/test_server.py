"""G1: the tools answer through a real client speaking the wire protocol.

Not "the function returns a dict". A subprocess is started, initialize and tools/list are
exchanged, and every advertised tool is called for real.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog.toml"


def _talk(messages: list[dict]) -> list[dict]:
    """Send JSON-RPC messages to the server over stdio and collect the replies."""
    payload = "".join(json.dumps(m) + "\n" for m in messages)
    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": ""}
    proc = subprocess.run(
        [sys.executable, "-m", "oncall_router.server", "--catalog", str(CATALOG)],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(ROOT), env={**dict(__import__("os").environ), **env},
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]


def test_server_initializes_and_advertises_five_tools() -> None:
    out = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ])
    init, listing = out[0], out[1]
    assert init["result"]["serverInfo"]["name"] == "oncall-router"
    names = {t["name"] for t in listing["result"]["tools"]}
    assert names == {"who_owns", "escalation_path", "playbook", "impact_clock",
                     "mttx_review"}
    # every advertised tool declares what it needs
    for t in listing["result"]["tools"]:
        assert t["description"].strip()
        assert t["inputSchema"]["required"]


@pytest.mark.parametrize(
    "name,args,expect",
    [
        ("who_owns", {"service": "gateway"}, lambda r: r["team"] == "Edge Gateway"),
        ("escalation_path", {"service": "auth", "severity": "sev2"},
         lambda r: len(r["hops"]) == 2),
        ("playbook", {"service": "payments", "symptom": "stuck-queue"},
         lambda r: r["matched"] == "stuck-queue"),
        ("impact_clock", {"service": "gateway", "severity": "sev1",
                          "impact_start": "2026-08-23T14:00:00Z",
                          "now": "2026-08-23T14:12:00Z"},
         lambda r: r["elapsed_minutes"] == 12 and r["current_hop"]["at_minute"] == 10),
        ("mttx_review", {"impact_start": "2026-08-24T14:00:00Z",
                         "detected": "2026-08-24T14:10:00Z",
                         "acknowledged": "2026-08-24T14:15:00Z",
                         "mitigated": "2026-08-24T14:45:00Z",
                         "service": "cart"},
         lambda r: r["dominant_phase"] == "mitigate" and r["service"] == "checkout"),
    ],
)
def test_each_tool_answers_through_the_client(name, args, expect) -> None:
    out = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": name, "arguments": args}},
    ])
    body = json.loads(out[1]["result"]["content"][0]["text"])
    assert body["found"] is True, body
    assert expect(body), body


def test_an_unknown_tool_fails_closed() -> None:
    out = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "delete_production", "arguments": {}}},
    ])
    body = json.loads(out[1]["result"]["content"][0]["text"])
    assert body["found"] is False
