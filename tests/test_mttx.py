"""mttx_review: where the minutes went, and which tool shrinks them next time.

Written RED-first on 2026-08-24, before the tool existed. The rubric these encode is
frozen in the project vault; the short version: measure only what was supplied, refuse
exactly what is wrong, never grade, and route the responder back into the server.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncall_router.catalog import Catalog  # noqa: E402
from oncall_router import tools            # noqa: E402
from oncall_router import server           # noqa: E402

CAT = Catalog.load(ROOT / "catalog.toml")

# A tidy closed incident: 10 minutes to detect, 5 to react, 30 to mitigate, 15 to clean up.
T0 = "2026-08-24T14:00:00Z"
T_DETECTED = "2026-08-24T14:10:00Z"
T_ACKED = "2026-08-24T14:15:00Z"
T_MITIGATED = "2026-08-24T14:45:00Z"
T_RESOLVED = "2026-08-24T15:00:00Z"


def review(**kw):
    return tools.mttx_review(CAT, **kw)


# ------------------------------------------------------------------ R1: measures true

def test_closed_incident_measures_true():
    r = review(impact_start=T0, detected=T_DETECTED, acknowledged=T_ACKED,
               mitigated=T_MITIGATED, resolved=T_RESOLVED)
    assert r["found"] is True
    phases = {p["name"]: p for p in r["phases"]}
    assert phases["detect"]["minutes"] == 10
    assert phases["react"]["minutes"] == 5
    assert phases["mitigate"]["minutes"] == 30
    assert phases["resolve"]["minutes"] == 15
    assert r["total_impact_minutes"] == 45          # impact stops at mitigation
    assert r["dominant_phase"] == "mitigate"
    shares = [p["share_of_impact"] for p in r["phases"] if p["name"] != "resolve"]
    assert 99 <= sum(shares) <= 101                 # rounding, but nothing missing


def test_resolve_never_dominates():
    # a huge cleanup tail must not outvote the phases customers actually felt
    r = review(impact_start=T0, detected=T_DETECTED, acknowledged=T_ACKED,
               mitigated=T_MITIGATED, resolved="2026-08-24T20:00:00Z")
    assert r["dominant_phase"] == "mitigate"


# ------------------------------------------------------------------ R2: the loop closes

def test_react_dominant_routes_to_escalation_path():
    r = review(impact_start=T0, detected="2026-08-24T14:02:00Z",
               acknowledged="2026-08-24T14:40:00Z", mitigated=T_MITIGATED,
               service="checkout")
    assert r["dominant_phase"] == "react"
    assert r["next_tool"]["name"] == "escalation_path"
    assert r["next_tool"]["arguments"]["service"] == "checkout"


def test_mitigate_dominant_routes_to_playbook():
    r = review(impact_start=T0, detected=T_DETECTED, acknowledged=T_ACKED,
               mitigated="2026-08-24T16:00:00Z", service="checkout")
    assert r["dominant_phase"] == "mitigate"
    assert r["next_tool"]["name"] == "playbook"


def test_detect_dominant_is_honest_about_scope():
    r = review(impact_start=T0, detected="2026-08-24T15:30:00Z",
               acknowledged="2026-08-24T15:35:00Z", mitigated="2026-08-24T15:40:00Z")
    assert r["dominant_phase"] == "detect"
    # detection lives in alerting, and the tool says so instead of pretending to help
    assert r["next_tool"] is None
    assert "alert" in r["dominant_note"].lower()


# ------------------------------------------------------------------ R3: open incidents

def test_open_incident_requires_now():
    r = review(impact_start=T0, detected=T_DETECTED)
    assert r["found"] is False
    assert "now" in r["reason"]


def test_open_incident_names_the_bleeding_phase():
    r = review(impact_start=T0, detected=T_DETECTED, now="2026-08-24T14:30:00Z")
    assert r["found"] is True
    assert r["open_phase"] == "react"               # detected but nobody engaged yet
    assert r["minutes_in_open_phase"] == 20
    assert r["total_impact_minutes"] is None        # impact has not stopped


def test_impact_start_alone_with_now_is_the_detect_phase():
    r = review(impact_start=T0, now="2026-08-24T14:07:00Z")
    assert r["found"] is True
    assert r["open_phase"] == "detect"
    assert r["minutes_in_open_phase"] == 7


def test_now_before_a_milestone_is_refused():
    r = review(impact_start=T0, detected=T_DETECTED, now="2026-08-24T14:05:00Z")
    assert r["found"] is False
    assert "detected" in r["reason"]


# ------------------------------------------------------------------ R4: refusals name the defect

def test_out_of_order_names_the_pair():
    r = review(impact_start=T0, detected=T_ACKED, acknowledged=T_DETECTED,
               mitigated=T_MITIGATED)
    assert r["found"] is False
    assert "acknowledged" in r["reason"] and "detected" in r["reason"]


def test_mixed_timezone_awareness_is_refused():
    r = review(impact_start="2026-08-24T14:00:00", detected=T_DETECTED,
               acknowledged=T_ACKED, mitigated=T_MITIGATED)
    assert r["found"] is False
    assert "offset" in r["reason"]


def test_unknown_service_fails_closed_with_suggestions():
    r = review(impact_start=T0, detected=T_DETECTED, acknowledged=T_ACKED,
               mitigated=T_MITIGATED, service="chekout")
    assert r["found"] is False
    assert "checkout" in r.get("did_you_mean", [])


def test_nothing_to_measure_is_refused():
    r = review(impact_start=T0)
    assert r["found"] is False


def test_garbage_timestamp_is_refused():
    r = review(impact_start="yesterday-ish", detected=T_DETECTED,
               acknowledged=T_ACKED, mitigated=T_MITIGATED)
    assert r["found"] is False
    assert "ISO 8601" in r["reason"]


# ------------------------------------------------------------------ R5: partial is partial

def test_missing_middle_milestone_is_unmeasured_not_guessed():
    r = review(impact_start=T0, acknowledged=T_ACKED, mitigated=T_MITIGATED)
    assert r["found"] is True
    assert "detect" in r["unmeasured"] and "react" in r["unmeasured"]
    phases = {p["name"]: p for p in r["phases"]}
    assert phases["mitigate"]["minutes"] == 30
    # 30 of 45 impact minutes are measured, so the measured phase may still claim dominance
    assert r["dominant_phase"] == "mitigate"


def test_dominance_declines_when_most_minutes_are_unmeasured():
    # detect is 10 of 45; the other 35 hide in unmeasured react+mitigate. Naming detect
    # dominant would be a confident answer drawn from mostly missing data.
    r = review(impact_start=T0, detected=T_DETECTED, mitigated=T_MITIGATED)
    assert r["found"] is True
    assert r["dominant_phase"] is None
    assert "unmeasured" in r["dominant_note"]
    assert "acknowledged" in r["dominant_note"]      # it names the stamp that would settle it


def test_rounding_dust_does_not_impeach_a_fully_measured_incident():
    # a 3-minute incident whose phases floor to 0+0+1 of a 3-minute total: the missing
    # minutes are rounding, not absent milestones, and the verdict must stand
    r = review(impact_start="2026-08-24T14:00:00Z",
               detected="2026-08-24T14:00:54Z",
               acknowledged="2026-08-24T14:01:48Z",
               mitigated="2026-08-24T14:03:00Z")
    assert r["found"] is True
    assert r["unmeasured"] == []
    assert r["dominant_phase"] == "mitigate"


def test_open_incident_routes_on_the_bleeding_phase_not_a_premature_verdict():
    r = review(impact_start=T0, detected=T_DETECTED, now="2026-08-24T14:30:00Z",
               service="checkout")
    assert r["incident_open"] is True
    assert r["dominant_phase"] is None               # the incident is not over yet
    assert r["open_phase"] == "react"
    # bleeding in react: the useful referral is the escalation path, right now
    assert r["next_tool"]["name"] == "escalation_path"


def test_zero_minute_phase_is_fine():
    r = review(impact_start=T0, detected=T0, acknowledged=T_ACKED,
               mitigated=T_MITIGATED)
    phases = {p["name"]: p for p in r["phases"]}
    assert phases["detect"]["minutes"] == 0
    assert r["found"] is True


# ------------------------------------------------------------------ R6: no grade

def test_no_grade_anywhere():
    r = review(impact_start=T0, detected=T_DETECTED, acknowledged=T_ACKED,
               mitigated=T_MITIGATED, resolved=T_RESOLVED)
    flat = str(sorted(r.keys())).lower()
    assert "grade" not in flat and "score" not in flat


# ---------------------------------------------------- adversarial QA round (2026-08-24)
# Every case below was found by an adversarial pass that RAN the tool, and each was
# reproduced before it was fixed. The theme: fails-closed applies to analytics too.

def test_resolved_without_mitigated_is_a_defective_timeline():
    # resolved proves the incident is over; missing mitigated makes it read as open.
    # The old behavior called it open and counted phantom minutes from the resolved stamp.
    r = review(impact_start=T0, detected=T_DETECTED, acknowledged=T_ACKED,
               resolved=T_RESOLVED, now="2026-08-24T18:00:00Z")
    assert r["found"] is False
    assert "resolved" in r["reason"] and "mitigated" in r["reason"]


def test_open_phase_is_the_one_after_the_latest_milestone():
    # acknowledged supplied, detected skipped: the incident is in its MITIGATE phase.
    # The old scan picked the first gap and blamed detection with full confidence.
    r = review(impact_start=T0, acknowledged="2026-08-24T14:30:00Z",
               now="2026-08-24T15:00:00Z", service="checkout")
    assert r["found"] is True
    assert r["open_phase"] == "mitigate"
    assert r["minutes_in_open_phase"] == 30           # measured from acknowledged
    assert r["next_tool"]["name"] == "playbook"       # and the referral matches the phase


def test_exact_ties_are_disclosed_not_crowned():
    r = review(impact_start="2026-08-24T12:00:00Z", detected="2026-08-24T12:30:00Z",
               acknowledged="2026-08-24T13:00:00Z", mitigated="2026-08-24T13:30:00Z")
    assert r["dominant_phase"] is None
    for name in ("detect", "react", "mitigate"):
        assert name in r["dominant_note"]              # the note names every tied phase


def test_sub_minute_incident_gets_no_verdict_from_zero_rows():
    # three 59-second phases floor to 0/0/0 displayed minutes; in seconds they are an
    # exact three-way tie, and a tie is disclosed rather than broken by list order
    r = review(impact_start="2026-08-24T12:00:00Z", detected="2026-08-24T12:00:59Z",
               acknowledged="2026-08-24T12:01:58Z", mitigated="2026-08-24T12:02:57Z")
    assert r["found"] is True
    assert r["dominant_phase"] is None


def test_shares_come_from_seconds_not_floored_minutes():
    # 54s + 54s + 72s: floored minutes say 0/0/1, the truth says 30/30/40
    r = review(impact_start="2026-08-24T12:00:00Z", detected="2026-08-24T12:00:54Z",
               acknowledged="2026-08-24T12:01:48Z", mitigated="2026-08-24T12:03:00Z")
    shares = {p["name"]: p["share_of_impact"] for p in r["phases"]}
    assert shares["detect"] == 30 and shares["react"] == 30 and shares["mitigate"] == 40
    assert r["dominant_phase"] == "mitigate"


def test_empty_string_service_is_refused_like_any_other_unknown():
    r = review(impact_start=T0, detected=T_DETECTED, acknowledged=T_ACKED,
               mitigated=T_MITIGATED, service="")
    assert r["found"] is False


def test_a_bare_date_cannot_time_an_incident():
    # datetime.fromisoformat happily reads 2026-08-24 as midnight, which invents a time
    # of day and with it a 600-minute detect phase. A date is not a timestamp. All the
    # stamps here are naive so the timezone rule cannot mask the hole.
    r = review(impact_start="2026-08-24", detected="2026-08-24T14:10:00",
               acknowledged="2026-08-24T14:15:00", mitigated="2026-08-24T14:45:00")
    assert r["found"] is False
    assert "time" in r["reason"].lower()


def test_the_referral_names_what_it_cannot_supply():
    # escalation_path also requires a severity mttx_review never learned; the referral
    # says so instead of handing over a call that will be refused verbatim
    r = review(impact_start=T0, detected="2026-08-24T14:02:00Z",
               acknowledged="2026-08-24T14:40:00Z", mitigated=T_MITIGATED,
               service="checkout")
    assert r["next_tool"]["name"] == "escalation_path"
    assert "severity" in r["next_tool"].get("also_needs", [])


def test_open_incident_note_speaks_in_the_present_tense():
    r = review(impact_start=T0, detected=T_DETECTED, now="2026-08-24T14:30:00Z")
    assert r["open_phase"] == "react"
    assert "went" not in r["dominant_note"]            # the minutes are still going


def test_missing_impact_start_gets_the_required_field_refusal():
    r = review(impact_start="")
    assert r["found"] is False
    assert "required" in r["reason"]


# ------------------------------------------------------------------ R7: the boundary holds

def test_dispatch_routes_mttx_review():
    out = server.dispatch(CAT, "mttx_review", {
        "impact_start": T0, "detected": T_DETECTED, "acknowledged": T_ACKED,
        "mitigated": T_MITIGATED})
    assert out["found"] is True and out["dominant_phase"] == "mitigate"


def test_dispatch_typechecks_strings():
    out = server.dispatch(CAT, "mttx_review", {"impact_start": 1400})
    assert out["found"] is False and "string" in out["reason"]


def test_tool_is_listed_with_a_schema():
    entry = next((t for t in server.TOOLS if t["name"] == "mttx_review"), None)
    assert entry is not None
    assert "impact_start" in entry["inputSchema"]["properties"]
    assert entry["inputSchema"]["required"] == ["impact_start"]


# ------------------------------------------------------------------ R8: the teaching example

def test_checkout_resolves_from_the_names_people_type():
    for alias in ("checkout", "cart", "buy button", "the checkout"):
        assert CAT.resolve(alias) == "checkout", alias


def test_checkout_has_an_owner_and_a_runbook():
    r = tools.who_owns(CAT, "cart")
    assert r["found"] is True and r["service"] == "checkout"
    p = tools.playbook(CAT, "checkout")
    assert p["found"] is True and p["steps"]
