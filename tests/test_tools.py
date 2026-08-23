"""RED-first tests for the four tools.

Written before the implementation. Each tool has a happy path and a fails-closed path,
because gate G2 says a tool that guesses is worse than a tool that declines: a confident
wrong escalation at 2am costs more than an honest "I do not know".
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from oncall_router import tools
from oncall_router.catalog import Catalog

CATALOG = Path(__file__).resolve().parents[1] / "catalog.toml"


@pytest.fixture(scope="module")
def cat() -> Catalog:
    return Catalog.load(CATALOG)


# --------------------------------------------------------------------------- who_owns

def test_who_owns_resolves_the_canonical_name(cat: Catalog) -> None:
    got = tools.who_owns(cat, "api-gateway")
    assert got["found"] is True
    assert got["service"] == "api-gateway"
    assert got["team"] == "Edge Gateway"
    assert got["tier"] == 1
    assert got["contact"] == "@edge-oncall"


def test_who_owns_resolves_the_name_a_tired_person_types(cat: Catalog) -> None:
    # during an incident nobody types the canonical name
    for typed in ("gateway", "APIGW", "  the gateway  ", "Edge"):
        got = tools.who_owns(cat, typed)
        assert got["found"] is True, typed
        assert got["service"] == "api-gateway", typed


def test_who_owns_declines_rather_than_guessing(cat: Catalog) -> None:
    got = tools.who_owns(cat, "billing-engine")
    assert got["found"] is False
    assert got.get("team") is None
    # it may offer candidates, but it must not present one as the answer
    assert "did_you_mean" in got
    assert isinstance(got["did_you_mean"], list)


# ---------------------------------------------------------------- escalation_path

def test_escalation_path_sev1_walks_every_hop_then_the_next_team(cat: Catalog) -> None:
    got = tools.escalation_path(cat, "api-gateway", "sev1")
    assert got["found"] is True
    roles = [h["role"] for h in got["hops"]]
    assert roles[:3] == ["primary on-call", "network duty", "engineering manager"]
    # sev1 keeps climbing into incident command
    assert any(h["team"] == "Platform Incident Command" for h in got["hops"])
    # the clock runs from impact start, so it must never go backwards when the chain
    # crosses into another team
    minutes = [h["at_minute"] for h in got["hops"]]
    assert minutes == sorted(minutes)
    assert minutes == [5, 10, 25, 30]


def test_escalation_path_sev3_stops_at_the_first_hop(cat: Catalog) -> None:
    got = tools.escalation_path(cat, "reporting-batch", "sev3")
    assert got["found"] is True
    assert len(got["hops"]) == 1


def test_escalation_path_refuses_an_unknown_severity(cat: Catalog) -> None:
    got = tools.escalation_path(cat, "api-gateway", "sev9")
    assert got["found"] is False
    assert got["hops"] == []
    assert "sev9" in got["reason"]


# ------------------------------------------------------------------------ playbook

def test_playbook_returns_the_symptom_steps(cat: Catalog) -> None:
    got = tools.playbook(cat, "api-gateway", "latency")
    assert got["found"] is True
    assert got["matched"] == "latency"
    assert any("p99" in step for step in got["steps"])


def test_playbook_falls_back_to_general_and_says_so(cat: Catalog) -> None:
    got = tools.playbook(cat, "api-gateway", "cosmic-rays")
    assert got["found"] is True
    assert got["matched"] == "general"
    assert got["fell_back"] is True   # the caller must be able to tell


def test_playbook_declines_for_an_unknown_service(cat: Catalog) -> None:
    got = tools.playbook(cat, "billing-engine", "latency")
    assert got["found"] is False
    assert got["steps"] == []


# --------------------------------------------------------------------- impact_clock

def test_impact_clock_reports_the_hop_we_should_be_on(cat: Catalog) -> None:
    start = dt.datetime(2026, 8, 23, 14, 0, tzinfo=dt.timezone.utc)
    now = start + dt.timedelta(minutes=17)
    got = tools.impact_clock(cat, "api-gateway", "sev1", start.isoformat(), now.isoformat())
    assert got["found"] is True
    assert got["elapsed_minutes"] == 17
    # 5 and 10 minute hops are due; the 25 minute hop is not
    assert got["current_hop"]["at_minute"] == 10
    assert [h["at_minute"] for h in got["overdue"]] == [5, 10]
    assert got["next_hop"]["at_minute"] == 25


def test_impact_clock_measures_from_impact_not_from_the_ticket(cat: Catalog) -> None:
    # the whole point of the tool: two incidents, same ticket time, different impact starts
    ticket = dt.datetime(2026, 8, 23, 14, 30, tzinfo=dt.timezone.utc)
    early = dt.datetime(2026, 8, 23, 14, 0, tzinfo=dt.timezone.utc)
    late = dt.datetime(2026, 8, 23, 14, 28, tzinfo=dt.timezone.utc)
    a = tools.impact_clock(cat, "api-gateway", "sev1", early.isoformat(), ticket.isoformat())
    b = tools.impact_clock(cat, "api-gateway", "sev1", late.isoformat(), ticket.isoformat())
    assert a["elapsed_minutes"] == 30 and b["elapsed_minutes"] == 2
    assert len(a["overdue"]) > len(b["overdue"])


def test_impact_clock_requires_an_explicit_timestamp(cat: Catalog) -> None:
    got = tools.impact_clock(cat, "api-gateway", "sev1", "sometime this afternoon", None)
    assert got["found"] is False
    assert "timestamp" in got["reason"].lower()


def test_impact_clock_refuses_a_start_in_the_future(cat: Catalog) -> None:
    start = dt.datetime(2026, 8, 23, 15, 0, tzinfo=dt.timezone.utc)
    now = start - dt.timedelta(minutes=10)
    got = tools.impact_clock(cat, "api-gateway", "sev1", start.isoformat(), now.isoformat())
    assert got["found"] is False


# ------------------------------------------------------------- the catalog is data

def test_a_different_catalog_gives_different_answers(tmp_path: Path) -> None:
    """G4: swapping the catalog changes every answer with no code edit."""
    alt = tmp_path / "alt.toml"
    alt.write_text(
        """
[teams.moon-team]
name = "Moon Team"
hours = "24x7"
escalation = [ { role = "primary on-call", handle = "@moon", within_minutes = 7 } ]

[services.api-gateway]
aliases = []
owner = "moon-team"
tier = 2
description = "Same name, different world."

[services.api-gateway.runbook]
general = ["Ask the Moon Team."]

[severities.sev1]
description = "x"
hops = "all"
""".strip(),
        encoding="utf-8",
    )
    got = tools.who_owns(Catalog.load(alt), "api-gateway")
    assert got["team"] == "Moon Team"
    assert got["contact"] == "@moon"
