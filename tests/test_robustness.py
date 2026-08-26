"""Everything an adversarial QA pass found before this repo went public.

Written RED-first against the state of the code at that moment. Each test names the
promise it defends, because every one of these was a place the README claimed something
the code did not do.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from oncall_router import tools
from oncall_router.catalog import Catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog.toml"


@pytest.fixture(scope="module")
def cat() -> Catalog:
    return Catalog.load(CATALOG)


def _talk(messages: list[dict], catalog: Path | None = None) -> subprocess.CompletedProcess:
    payload = "".join(json.dumps(m) + "\n" for m in messages)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "oncall_router.server", "--catalog", str(catalog or CATALOG)],
        input=payload, capture_output=True, text=True, timeout=60, cwd=str(ROOT), env=env,
    )


# ------------------------------------------------- the server must survive bad input

@pytest.mark.parametrize("bad_args", [
    {"service": 123},                       # a model emitting a bare number is routine
    {"service": ["gateway"]},
    {"service": None},
])
def test_a_badly_typed_argument_does_not_kill_the_session(bad_args) -> None:
    """The worst possible failure for something pitched on 2am reliability."""
    proc = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "who_owns", "arguments": bad_args}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "who_owns", "arguments": {"service": "gateway"}}},
    ])
    assert proc.returncode == 0, proc.stderr
    replies = {json.loads(l)["id"]: json.loads(l) for l in proc.stdout.splitlines() if l.strip()}
    # the bad call is answered, and the good call that follows it still works
    assert 2 in replies and 3 in replies, "the session died: " + proc.stderr[-300:]
    good = json.loads(replies[3]["result"]["content"][0]["text"])
    assert good["found"] is True and good["team"] == "Edge Gateway"


def test_a_malformed_message_does_not_kill_the_session() -> None:
    """Malformed ARGUMENTS were covered; malformed MESSAGES were not.

    The guards for these existed (a JSONDecodeError catch, an isinstance check on the
    parsed value) but nothing exercised them, so a refactor could have deleted either
    without a single test going red. Interleave garbage between two good calls and
    require the session to survive all of it.
    """
    payload = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        "not json at all {{{",
        '"a bare string"',            # valid JSON, not an object
        "[1, 2, 3]",                  # valid JSON, an array
        "12345",
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": "who_owns", "arguments": {"service": "gateway"}}}),
    ]) + "\n"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    proc = subprocess.run(
        [sys.executable, "-m", "oncall_router.server", "--catalog", str(CATALOG)],
        input=payload, capture_output=True, text=True, timeout=60, cwd=str(ROOT), env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    replies = {json.loads(l).get("id") for l in proc.stdout.splitlines() if l.strip()}
    assert 9 in replies, "the good call after the garbage got no reply: " + proc.stderr[-300:]


def test_a_null_params_field_does_not_kill_the_session() -> None:
    proc = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": None},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "who_owns", "arguments": {"service": "auth"}}},
    ])
    assert proc.returncode == 0, proc.stderr
    ids = {json.loads(l).get("id") for l in proc.stdout.splitlines() if l.strip()}
    assert 3 in ids, "the session died on a null params field"


def test_errors_do_not_leak_the_deployment_path() -> None:
    """A traceback carrying C:\\Users\\... tells a stranger where this was built."""
    proc = _talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "who_owns", "arguments": {"service": 123}}},
    ])
    combined = proc.stdout + proc.stderr
    assert "Traceback" not in combined
    assert "OneDrive" not in combined and "C:\\Users" not in combined


def test_a_non_ascii_service_name_survives_the_transport() -> None:
    """MCP requires UTF-8. Windows text mode defaults to the locale codepage."""
    alt = ROOT / "tests" / "_utf8_catalog.toml"
    alt.write_text(
        '[teams.equipe]\nname = "Equipe Paiements"\nhours = "24x7"\n'
        'escalation = [ { role = "astreinte", handle = "@paiements", within_minutes = 5 } ]\n\n'
        '[services.paiements-securise]\naliases = ["paiement"]\nowner = "equipe"\ntier = 1\n'
        'description = "Chaine de paiement securisee."\n\n'
        '[services.paiements-securise.runbook]\ngeneral = ["Verifier la file d attente."]\n\n'
        '[severities.sev1]\ndescription = "x"\nhops = "all"\n',
        encoding="utf-8", newline="\n",
    )
    try:
        proc = _talk([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "who_owns", "arguments": {"service": "paiements-securise"}}},
        ], catalog=alt)
        assert proc.returncode == 0, proc.stderr
        body = json.loads(json.loads(proc.stdout.splitlines()[1])["result"]["content"][0]["text"])
        assert body["found"] is True, body
        assert body["team"] == "Equipe Paiements"
    finally:
        alt.unlink(missing_ok=True)


# ------------------------------------------- fails closed means closed, not empty

def _broken(tmp_path: Path, body: str) -> Catalog:
    p = tmp_path / "broken.toml"
    p.write_text(body, encoding="utf-8", newline="\n")
    return Catalog.load(p)


DANGLING = """
[teams.real-team]
name = "Real Team"
hours = "24x7"
escalation = [ { role = "primary", handle = "@real", within_minutes = 5 } ]

[services.orphan]
aliases = []
owner = "ghost-team"
tier = 1
description = "Its owner does not exist in this catalog."

[services.orphan.runbook]
general = ["nothing"]

[severities.sev1]
description = "x"
hops = "all"
"""


def test_a_service_whose_owner_does_not_exist_fails_closed(tmp_path: Path) -> None:
    """Four hours into an outage, 'nothing overdue' is the most dangerous answer there is."""
    cat = _broken(tmp_path, DANGLING)
    assert tools.who_owns(cat, "orphan")["found"] is False
    path = tools.escalation_path(cat, "orphan", "sev1")
    assert path["found"] is False
    assert "ghost-team" in path["reason"]


def test_a_team_with_no_contacts_fails_closed(tmp_path: Path) -> None:
    cat = _broken(tmp_path, """
[teams.empty-team]
name = "Empty Team"
hours = "24x7"
escalation = []

[services.lonely]
aliases = []
owner = "empty-team"
tier = 1
description = "Owner exists but lists nobody."

[services.lonely.runbook]
general = ["nothing"]

[severities.sev1]
description = "x"
hops = "all"
""")
    assert tools.escalation_path(cat, "lonely", "sev1")["found"] is False


def test_impact_clock_fails_closed_on_an_unknown_service(cat: Catalog) -> None:
    got = tools.impact_clock(cat, "billing-engine", "sev1",
                             "2026-08-23T14:00:00Z", "2026-08-23T14:10:00Z")
    assert got["found"] is False


def test_impact_clock_fails_closed_on_an_unknown_severity(cat: Catalog) -> None:
    got = tools.impact_clock(cat, "api-gateway", "sev9",
                             "2026-08-23T14:00:00Z", "2026-08-23T14:10:00Z")
    assert got["found"] is False
    assert "sev9" in got["reason"]


# ----------------------------------------------------------------- clock correctness

def test_a_naive_timestamp_beside_an_aware_one_is_refused(cat: Catalog) -> None:
    """Assuming UTC for a naive value silently inflates elapsed time by the caller's offset."""
    got = tools.impact_clock(cat, "api-gateway", "sev1",
                             "2026-08-23T14:00:00",            # no offset
                             "2026-08-23T14:20:00+02:00")      # offset
    assert got["found"] is False
    assert "offset" in got["reason"].lower() or "timezone" in got["reason"].lower()


def test_both_naive_is_still_allowed(cat: Catalog) -> None:
    got = tools.impact_clock(cat, "api-gateway", "sev1",
                             "2026-08-23T14:00:00", "2026-08-23T14:20:00")
    assert got["found"] is True
    assert got["elapsed_minutes"] == 20


def test_hops_come_back_in_clock_order_even_if_the_catalog_is_untidy(tmp_path: Path) -> None:
    cat = _broken(tmp_path, """
[teams.messy]
name = "Messy Team"
hours = "24x7"
escalation = [
  { role = "manager", handle = "@m", within_minutes = 30 },
  { role = "primary", handle = "@p", within_minutes = 5 },
]

[services.svc]
aliases = []
owner = "messy"
tier = 1
description = "Escalation listed out of order."

[services.svc.runbook]
general = ["x"]

[severities.sev1]
description = "x"
hops = "all"
""")
    hops = tools.escalation_path(cat, "svc", "sev1")["hops"]
    minutes = [h["at_minute"] for h in hops]
    assert minutes == sorted(minutes), minutes
    clock = tools.impact_clock(cat, "svc", "sev1",
                               "2026-08-23T14:00:00Z", "2026-08-23T14:10:00Z")
    assert clock["current_hop"]["role"] == "primary"


# ---------------------------------------------------------- the suggestion is real

def test_a_typo_gets_a_suggestion(cat: Catalog) -> None:
    """suggest() could be gutted to return [] with the old suite still green."""
    got = tools.who_owns(cat, "payment-orchestator")
    assert got["found"] is False
    assert "payment-orchestrator" in got["did_you_mean"]
