"""The four tools.

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
