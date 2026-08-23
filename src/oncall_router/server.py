"""MCP server exposing the four tools over stdio.

The transport layer is deliberately thin. Everything that decides anything lives in
tools.py as pure functions, so the behaviour is testable without a client and the server
is just wiring.

Run:  python -m oncall_router.server --catalog catalog.toml
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .catalog import Catalog
from . import tools

TOOLS: list[dict[str, Any]] = [
    {
        "name": "who_owns",
        "description": (
            "Which team owns a service and how to reach them right now. Accepts the name "
            "someone would actually type during an incident, including aliases. Returns "
            "found=false with suggestions rather than guessing at a near match."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"service": {"type": "string", "description": "Service name or alias."}},
            "required": ["service"],
        },
    },
    {
        "name": "escalation_path",
        "description": (
            "Who to wake for this service at this severity, in order, with the minute each "
            "hop is due measured from impact start. Refuses an unknown severity rather than "
            "defaulting to the quietest one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "severity": {"type": "string", "description": "A severity defined by the catalog, for example sev1."},
            },
            "required": ["service", "severity"],
        },
    },
    {
        "name": "playbook",
        "description": (
            "What the runbook says to check first. Falls back to the service's general steps "
            "when the symptom is unknown, and says so with fell_back=true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "symptom": {"type": "string", "description": "Optional, for example latency."},
            },
            "required": ["service"],
        },
    },
    {
        "name": "impact_clock",
        "description": (
            "Given when impact started, which escalation hop should be active now and which "
            "are overdue. Time is measured from impact start rather than ticket creation. "
            "Requires an explicit now timestamp: it never assumes the current time."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "severity": {"type": "string"},
                "impact_start": {"type": "string", "description": "ISO 8601, e.g. 2026-08-23T14:00:00Z"},
                "now": {"type": "string", "description": "ISO 8601. Required."},
            },
            "required": ["service", "severity", "impact_start", "now"],
        },
    },
]


def dispatch(cat: Catalog, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Route one tool call. Unknown tool names fail closed like everything else."""
    if name == "who_owns":
        return tools.who_owns(cat, args.get("service", ""))
    if name == "escalation_path":
        return tools.escalation_path(cat, args.get("service", ""), args.get("severity", ""))
    if name == "playbook":
        return tools.playbook(cat, args.get("service", ""), args.get("symptom"))
    if name == "impact_clock":
        return tools.impact_clock(
            cat, args.get("service", ""), args.get("severity", ""),
            args.get("impact_start", ""), args.get("now"),
        )
    return {"found": False, "reason": f"Unknown tool {name!r}."}


def _reply(request_id: Any, result: Any) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()


def serve(cat: Catalog) -> None:
    """Minimal JSON-RPC loop over stdio.

    Written against the wire protocol directly so the server has no dependencies at all.
    A production deployment would use the official SDK; this keeps the repo installable
    with nothing but a Python interpreter, which is the point.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            _reply(mid, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "oncall-router", "version": "0.1.0"},
            })
        elif method == "tools/list":
            _reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params", {})
            out = dispatch(cat, params.get("name", ""), params.get("arguments", {}))
            _reply(mid, {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]})
        elif mid is not None:
            _reply(mid, {})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Route an incident to the team that owns it.")
    ap.add_argument("--catalog", default=os.environ.get("ONCALL_CATALOG", "catalog.toml"))
    ns = ap.parse_args(argv)
    path = Path(ns.catalog)
    if not path.exists():
        sys.stderr.write(f"catalog not found: {path}\n")
        return 2
    serve(Catalog.load(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
