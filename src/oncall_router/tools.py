"""The five tools.

Every one of them is a pure function of (catalog, arguments). No clock, no network, no
global state: the caller supplies "now" so the answers are reproducible and testable.

They all fail closed. An unknown service does not resolve to the nearest match, and an
unknown severity does not fall back to the quietest one. A confident wrong escalation at
2am costs more than an honest "I do not know".
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from .catalog import Catalog


def who_owns(cat: Catalog, service: str) -> dict[str, Any]:
    """Which team owns this service, and how do I reach them right now."""
    name = cat.resolve(service)
    if not name:
        return {
            "found": False,
            "asked_for": service,
            "team": None,
            "did_you_mean": cat.suggest(service),
            "reason": f"No service matches {service!r} in this catalog.",
        }
    svc = cat.services[name]
    team = cat.team_of(name)
    if not team:
        return {
            "found": False,
            "asked_for": service,
            "service": name,
            "team": None,
            "reason": (f"Service {name!r} names owner {svc.get('owner')!r}, which this "
                       f"catalog does not define. Fix the catalog before escalating."),
        }
    chain = team.get("escalation") or []
    if not chain:
        return {
            "found": False,
            "asked_for": service,
            "service": name,
            "team": team.get("name"),
            "reason": (f"Team {team.get('name')!r} owns {name!r} but lists no contacts. "
                       f"There is nobody to page."),
        }
    first = chain[0]
    return {
        "found": True,
        "asked_for": service,
        "service": name,
        "description": svc.get("description", ""),
        "tier": svc.get("tier"),
        "team": team.get("name"),
        "hours": team.get("hours"),
        "contact": first.get("handle"),
        "contact_role": first.get("role"),
    }


def escalation_path(cat: Catalog, service: str, severity: str) -> dict[str, Any]:
    """Who to wake, in what order, and how long each hop gets."""
    name = cat.resolve(service)
    if not name:
        return {
            "found": False,
            "hops": [],
            "did_you_mean": cat.suggest(service),
            "reason": f"No service matches {service!r} in this catalog.",
        }
    sev = cat.severities.get(severity.strip().lower()) if severity else None
    if not sev:
        known = ", ".join(sorted(cat.severities))
        return {
            "found": False,
            "hops": [],
            "reason": f"Unknown severity {severity!r}. This catalog defines: {known}.",
        }

    hops = _walk(cat, name, sev.get("hops", 1))
    if not hops:
        owner = cat.services[name].get("owner")
        return {
            "found": False,
            "service": name,
            "hops": [],
            "reason": (f"No escalation chain resolves for {name!r}: it names owner "
                       f"{owner!r}, which this catalog either does not define or leaves "
                       f"without contacts. Nothing to escalate to."),
        }
    return {
        "found": True,
        "service": name,
        "severity": severity.strip().lower(),
        "severity_meaning": sev.get("description", ""),
        "hops": hops,
    }


def playbook(cat: Catalog, service: str, symptom: str | None = None) -> dict[str, Any]:
    """What the runbook says to check first."""
    name = cat.resolve(service)
    if not name:
        return {
            "found": False,
            "steps": [],
            "did_you_mean": cat.suggest(service),
            "reason": f"No service matches {service!r} in this catalog.",
        }
    book = cat.services[name].get("runbook", {})
    key = (symptom or "").strip().lower()
    if key and key in book:
        return {"found": True, "service": name, "matched": key,
                "fell_back": False, "steps": list(book[key])}
    # unmatched symptom is not an error, but the caller must be able to tell
    return {
        "found": True,
        "service": name,
        "matched": "general",
        "fell_back": bool(key),
        "asked_for": symptom,
        "steps": list(book.get("general", [])),
        "known_symptoms": sorted(k for k in book if k != "general"),
    }


def impact_clock(
    cat: Catalog,
    service: str,
    severity: str,
    impact_start: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Given when impact started, which hop should we be on, and what is overdue.

    Measured from impact start rather than from ticket creation. Those are not the same
    moment, and the gap between them is where escalation quietly runs late.
    """
    start, start_aware = _parse(impact_start)
    if start is None:
        return {"found": False, "reason": "impact_start must be an ISO 8601 timestamp, "
                                          "for example 2026-08-23T14:00:00Z."}
    current, now_aware = _parse(now) if now else (None, False)
    if now and current is None:
        return {"found": False, "reason": "now must be an ISO 8601 timestamp when supplied."}
    if current is None:
        return {"found": False, "reason": "now is required as an ISO 8601 timestamp: this "
                                          "tool never assumes the current time for you."}
    if start_aware != now_aware:
        # Assuming UTC for the naive one would inflate or deflate elapsed time by the
        # caller's whole offset, and report the wrong hop with total confidence.
        naked = "impact_start" if not start_aware else "now"
        return {"found": False,
                "reason": (f"{naked} carries no timezone offset while the other does. "
                           f"Supply both with offsets, or neither.")}
    if current < start:
        return {"found": False,
                "reason": "impact_start is after now. Check the timestamps before escalating."}

    path = escalation_path(cat, service, severity)
    if not path["found"]:
        return {"found": False, "reason": path["reason"], **{k: v for k, v in path.items()
                                                             if k == "did_you_mean"}}

    elapsed = int((current - start).total_seconds() // 60)
    overdue = [h for h in path["hops"] if h["at_minute"] <= elapsed]
    upcoming = [h for h in path["hops"] if h["at_minute"] > elapsed]
    return {
        "found": True,
        "service": path["service"],
        "severity": path["severity"],
        "impact_start": start.isoformat(),
        "now": current.isoformat(),
        "elapsed_minutes": elapsed,
        "current_hop": overdue[-1] if overdue else None,
        "overdue": overdue,
        "next_hop": upcoming[0] if upcoming else None,
        "minutes_to_next": (upcoming[0]["at_minute"] - elapsed) if upcoming else None,
        "note": "Elapsed time is measured from impact start, not from ticket creation.",
    }


_PHASES = [
    # (phase, starts at, ends at) - the plain-words timeline of every incident
    ("detect", "impact_start", "detected"),        # how long until anyone knew
    ("react", "detected", "acknowledged"),         # how long until someone engaged
    ("mitigate", "acknowledged", "mitigated"),     # how long until customers stopped feeling it
    ("resolve", "mitigated", "resolved"),          # cleanup; impact already over
]

# What each dominant phase means, and which of THIS server's tools shrinks it next time.
# detect carries no tool on purpose: detection lives in alerting, and pointing at one of
# these four tools would be pretending. Honest scope beats a confident wrong referral.
# Two tenses, because a closed incident is a verdict and an open one is a situation.
_PHASE_NOTES = {
    "detect": ("The minutes went to finding out. This server cannot shrink that phase: "
               "detection lives in your alerting. Alert on symptoms customers feel, not "
               "on causes you guessed in advance, and page on the symptom.", None),
    "react": ("The minutes went to finding the right person. That is exactly what "
              "who_owns and escalation_path exist to shrink: the route was knowable "
              "before the incident, so put it where the assistant can reach it.",
              "escalation_path"),
    "mitigate": ("The minutes went to deciding what to try. Keep the first three moves "
                 "in the runbook so nobody invents them at 2am - that is what playbook "
                 "serves, and rollback usually beats diagnosis while customers hurt.",
                 "playbook"),
}
_PHASE_NOTES_OPEN = {
    "detect": ("Impact is running and nothing says anyone knows yet. If a human is "
               "already looking, record detected; if not, this is your alerting gap, "
               "live, right now.", None),
    "react": ("Someone knows and nobody is engaged yet. This is the exact minute "
              "escalation_path exists for: get the next hop moving.", "escalation_path"),
    "mitigate": ("A responder is engaged and customers still feel it. playbook has the "
                 "first moves; while customers hurt, rollback usually beats diagnosis.",
                 "playbook"),
}
# What a referral cannot supply itself, so the caller is never handed a call that will
# be refused verbatim the moment they make it.
_TOOL_ALSO_NEEDS = {"escalation_path": ["severity"], "playbook": []}


def mttx_review(
    cat: Catalog,
    impact_start: str,
    detected: str | None = None,
    acknowledged: str | None = None,
    mitigated: str | None = None,
    resolved: str | None = None,
    now: str | None = None,
    service: str | None = None,
) -> dict[str, Any]:
    """Where did the minutes go: Detect, React, Mitigate - measured, never guessed.

    The other four tools serve the first ten minutes of an incident. This one serves the
    day after: given the timestamps you actually have, it measures each phase, names the
    one that ate the incident, and points at the tool or practice that shrinks it next
    time. A phase is measured only when both of its endpoints were supplied - a missing
    milestone is reported as unmeasured, never interpolated.

    Deliberately absent: a grade. Thresholds for "good" MTTx vary by an order of
    magnitude across teams, tiers, and industries, so a grade here would be a number
    nobody could defend. The shares and the dominant phase are facts; judging them
    belongs to the team that owns the service.
    """
    if not impact_start:
        return {"found": False, "reason": "impact_start is required: nothing about an "
                                          "incident can be measured without knowing when "
                                          "impact began."}
    stamps: dict[str, dt.datetime] = {}
    awareness: dict[str, bool] = {}
    supplied = {"impact_start": impact_start, "detected": detected,
                "acknowledged": acknowledged, "mitigated": mitigated,
                "resolved": resolved, "now": now}
    for field, value in supplied.items():
        if value is None:
            continue
        parsed, aware = _parse(value)
        if parsed is None:
            return {"found": False,
                    "reason": f"{field} must be an ISO 8601 timestamp, for example "
                              f"2026-08-24T14:00:00Z. Got {value!r}."}
        if len(str(value).strip()) <= 10:
            # fromisoformat reads a bare date as midnight, which would invent the time of
            # day and, with it, an entire phantom phase. A date is not a timestamp.
            return {"found": False,
                    "reason": f"{field} is a date with no time of day ({value!r}). An "
                              f"incident is timed in minutes; supply the time, for "
                              f"example 2026-08-24T14:00:00Z."}
        stamps[field] = parsed
        awareness[field] = aware
    if "impact_start" not in stamps:
        return {"found": False, "reason": "impact_start is required: nothing about an "
                                          "incident can be measured without knowing when "
                                          "impact began."}
    if len(set(awareness.values())) > 1:
        naked = sorted(f for f, a in awareness.items() if not a)
        return {"found": False,
                "reason": (f"{', '.join(naked)} carr{'y' if len(naked) > 1 else 'ies'} no "
                           f"timezone offset while other timestamps do. Supply all with "
                           f"offsets, or none - mixing them silently shifts every phase "
                           f"by your whole UTC offset.")}

    # Milestones must not run backwards. Compare each against the latest earlier one that
    # was actually supplied, and name the exact pair when they disagree.
    order = ["impact_start", "detected", "acknowledged", "mitigated", "resolved"]
    prev_field = "impact_start"
    for field in order[1:]:
        if field not in stamps:
            continue
        if stamps[field] < stamps[prev_field]:
            return {"found": False,
                    "reason": (f"{field} ({stamps[field].isoformat()}) is before "
                               f"{prev_field} ({stamps[prev_field].isoformat()}). Check "
                               f"the timestamps before drawing any conclusion from them.")}
        prev_field = field

    if "resolved" in stamps and "mitigated" not in stamps:
        return {"found": False,
                "reason": "resolved was supplied without mitigated. A resolved incident "
                          "is not an open one, and the mitigate phase cannot be measured "
                          "without its endpoint - supply mitigated, or drop resolved if "
                          "the incident is genuinely still open."}
    incident_open = "mitigated" not in stamps
    if incident_open and "now" not in stamps:
        if len(stamps) == 1:
            return {"found": False,
                    "reason": "Nothing to measure yet: supply now to review an open "
                              "incident, or milestones to review a closed one."}
        return {"found": False,
                "reason": "This incident has no mitigated timestamp, so it reads as "
                          "still open. Supply now to measure the open phase - this tool "
                          "never assumes the current time for you."}
    if "now" in stamps:
        latest = max(v for f, v in stamps.items() if f != "now")
        if stamps["now"] < latest:
            late = [f for f, v in stamps.items() if f != "now" and v > stamps["now"]]
            return {"found": False,
                    "reason": (f"now is before {' and '.join(sorted(late))}. A milestone "
                               f"in the future of now is a typo, not a timeline.")}

    svc_name = None
    team = None
    if service is not None:      # an explicit empty string is caller input, not an omission
        svc_name = cat.resolve(service)
        if not svc_name:
            return {"found": False, "asked_for": service,
                    "did_you_mean": cat.suggest(service),
                    "reason": f"No service matches {service!r} in this catalog."}
        team_data = cat.team_of(svc_name)
        team = team_data.get("name") if team_data else None

    # All internal arithmetic runs in SECONDS. An adversarial pass proved that flooring
    # to minutes first lets the display corrupt the analysis: a phase that ate 30% of a
    # three-minute incident reported a 0% share, and dominance was decided by which phase
    # happened to cross a minute boundary. Minutes are how the answer is DISPLAYED;
    # seconds are how it is decided.
    phases: list[dict[str, Any]] = []
    secs: dict[str, float] = {}
    total_s = ((stamps["mitigated"] - stamps["impact_start"]).total_seconds()
               if not incident_open else None)
    total_impact = int(total_s // 60) if total_s is not None else None
    for name, a, b in _PHASES:
        if a in stamps and b in stamps:
            s = (stamps[b] - stamps[a]).total_seconds()
            secs[name] = s
            share = (round(s / total_s * 100)
                     if total_s and name != "resolve" else None)
            phases.append({"name": name, "minutes": int(s // 60),
                           "share_of_impact": share,
                           "from": a, "to": b})
    # the customer-facing three always report their absence; resolve is optional cleanup
    # and only counts as unmeasured when a resolved stamp implied it should exist
    unmeasured = [n for n, a, b in _PHASES
                  if not (a in stamps and b in stamps)
                  and (n != "resolve" or "resolved" in stamps)]

    # dominance: the measured customer-facing phase that ate the most time. resolve is
    # excluded because impact had already stopped - a long cleanup must not outvote the
    # minutes customers actually felt. Three honesty rules bound it:
    #   - an OPEN incident gets no verdict; the useful answer is the phase bleeding NOW,
    #     named in the present tense, and the referral routes on that instead
    #   - a CLOSED incident where more time hides in unmeasured phases than in the
    #     largest measured one gets no verdict. Naming a dominant phase from mostly
    #     missing data is exactly the confident wrong answer this server exists to refuse.
    #   - an exact tie is DISCLOSED, never broken by list order. A coin flip presented
    #     as a measurement steers the retro toward the wrong fix.
    measured = [n for n in secs if n != "resolve"]
    dominant = None
    note = None
    referral_phase = None
    open_phase = None
    if incident_open:
        # the phase after the LATEST supplied milestone. Scanning forward here once blamed
        # detection while the acknowledged stamp proved detection was long over.
        open_phase = next((n for n, a, b in reversed(_PHASES[:3])
                           if a in stamps and b not in stamps), None)
        referral_phase = open_phase
        note = _PHASE_NOTES_OPEN.get(open_phase, (None, None))[0] if open_phase else None
    elif measured:
        top_s = max(secs[n] for n in measured)
        tied = sorted(n for n in measured if secs[n] == top_s)
        unmeasured_s = (total_s or 0) - sum(secs[n] for n in measured)
        if unmeasured_s > top_s:
            missing = sorted(b for n, a, b in _PHASES[:3] if b not in stamps)
            gap_min = int(unmeasured_s // 60)
            note = (f"{gap_min} of the {total_impact} impact minutes fall in unmeasured "
                    f"phases ({', '.join(n for n in unmeasured if n != 'resolve')}), so no "
                    f"phase can honestly be called dominant. Supplying "
                    f"{' and '.join(missing)} would settle it.")
        elif len(tied) > 1:
            note = (f"{' and '.join(tied)} are tied exactly, so no single phase can "
                    f"honestly be called dominant. The retro should look at "
                    f"{'both' if len(tied) == 2 else 'all of them'}.")
        else:
            dominant = tied[0]
            referral_phase = dominant
            note = _PHASE_NOTES.get(dominant, (None, None))[0]
    notes_table = _PHASE_NOTES_OPEN if incident_open else _PHASE_NOTES
    next_tool = None
    next_tool_name = notes_table.get(referral_phase, (None, None))[1] if referral_phase else None
    if next_tool_name:
        args: dict[str, Any] = {}
        if svc_name:
            args["service"] = svc_name
        next_tool = {"name": next_tool_name, "arguments": args}
        also = [f for f in _TOOL_ALSO_NEEDS.get(next_tool_name, [])]
        if also:
            next_tool["also_needs"] = also

    out: dict[str, Any] = {
        "found": True,
        "incident_open": incident_open,
        "phases": phases,
        "unmeasured": unmeasured,
        "total_impact_minutes": total_impact,
        "dominant_phase": dominant,
        "dominant_note": note,
        "next_tool": next_tool,
        "note": "A phase is measured only when both endpoints were supplied. No grade on "
                "purpose: thresholds belong to the team that owns the service.",
    }
    if svc_name:
        out["service"] = svc_name
        out["team"] = team
    if incident_open:
        last = max(v for f, v in stamps.items() if f != "now")
        out["open_phase"] = open_phase
        out["minutes_in_open_phase"] = int((stamps["now"] - last).total_seconds() // 60)
    return out


# ----------------------------------------------------------------------- internals

def _walk(cat: Catalog, service_name: str, hops_rule: Any) -> list[dict[str, Any]]:
    """Flatten the escalation chain, following next_hop when the rule says to keep going."""
    unlimited = isinstance(hops_rule, str) and hops_rule.strip().lower() == "all"
    limit = None if unlimited else int(hops_rule)

    out: list[dict[str, Any]] = []
    team_key = cat.services[service_name].get("owner")
    seen: set[str] = set()
    # Each team states its timings relative to its own involvement. The clock a responder
    # cares about runs from impact start, so when the chain climbs to the next team we
    # carry the elapsed total forward. Without this the sequence goes 5, 10, 25, 5 and
    # "which hop should we be on" stops meaning anything.
    offset = 0

    while team_key and team_key not in seen:
        seen.add(team_key)
        team = cat.teams.get(team_key)
        if not team:
            break
        last = offset
        for step in team.get("escalation", []):
            minute = offset + int(step.get("within_minutes", 0))
            last = max(last, minute)
            out.append({
                "team": team.get("name"),
                "role": step.get("role"),
                "handle": step.get("handle"),
                "at_minute": minute,
            })
            if limit is not None and len(out) >= limit:
                return out
        offset = last
        team_key = team.get("next_hop") if unlimited else None

    # A catalog edited under pressure can list contacts out of order. The clock reads this
    # list positionally, so sort it here rather than trusting the file. Stable, so equal
    # minutes keep the order the catalog gave them.
    out.sort(key=lambda h: h["at_minute"])
    return out


def _parse(value: str | None) -> tuple[dt.datetime | None, bool]:
    """Returns (timestamp, had_offset). Awareness is reported, never silently invented."""
    if not value or not isinstance(value, str):
        return None, False
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None, False
    aware = parsed.tzinfo is not None
    if not aware:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed, aware
