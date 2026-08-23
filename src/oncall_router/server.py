"""MCP server exposing the four tools over stdio.

The transport layer is deliberately thin. Everything that decides anything lives in
tools.py as pure functions, so the behaviour is testable without a client and the server
is just wiring.

Two things this file takes seriously, both learned from an adversarial review:

Nothing a client sends may end the session. A model emitting a bare number where a string
was declared is an everyday occurrence, and a server pitched on reliability at 2am cannot
answer that by dying and taking its other three tools with it.

Errors carry a short generic message. A traceback would disclose the build path of whoever
deployed it, which is nobody's business.

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
                "severity": {"type": "string",
                             "description": "A severity defined by the catalog, for example sev1."},
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
                "impact_start": {"type": "string",
                                 "description": "ISO 8601, e.g. 2026-08-23T14:00:00Z"},
                "now": {"type": "string", "description": "ISO 8601. Required."},
            },
            "required": ["service", "severity", "impact_start", "now"],
        },
    },
]

# what each tool's string fields are called, so the boundary can check them
_STRING_FIELDS = {
    "who_owns": ("service",),
    "escalation_path": ("service", "severity"),
    "playbook": ("service", "symptom"),
    "impact_clock": ("service", "severity", "impact_start", "now"),
}


def _typecheck(name: str, args: dict[str, Any]) -> str | None:
    """The inputSchema declares strings. Say so plainly instead of raising later."""
    for field in _STRING_FIELDS.get(name, ()):
        value = args.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            return (f"{field} must be a string, got {type(value).__name__}. "
                    f"This tool will not guess what you meant.")
    return None


def dispatch(cat: Catalog, name: str, args: Any) -> dict[str, Any]:
    """Route one tool call. Unknown names and bad shapes fail closed like everything else."""
    if not isinstance(args, dict):
        return {"found": False, "reason": "arguments must be an object."}
    bad = _typecheck(name, args)
    if bad:
        return {"found": False, "reason": bad}

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


def _send(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _reply(request_id: Any, result: Any) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _handle(cat: Catalog, msg: dict[str, Any]) -> None:
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        _reply(mid, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "oncall-router", "version": "0.1.0"},
        })
    elif method == "tools/list":
        _reply(mid, {"tools": TOOLS})
    elif method == "tools/call":
        out = dispatch(cat, params.get("name", ""), params.get("arguments", {}))
        _reply(mid, {"content": [{"type": "text", "text": json.dumps(out, indent=2)}],
                     "isError": not out.get("found", False)})
    elif mid is not None:
        # a request we do not implement deserves a real JSON-RPC error, not an empty result
        _error(mid, -32601, f"Method not found: {method}")
    # anything with no id is a notification: acknowledge nothing, which is the protocol


def serve(cat: Catalog) -> None:
    """Minimal JSON-RPC loop over stdio.

    Written against the wire protocol directly so the server has no dependencies at all.
    A production deployment would use the official SDK; this keeps the repo installable
    with nothing but a Python interpreter, which is the point.
    """
    # MCP requires UTF-8. On Windows the default is the locale codepage, which turns a
    # non-ASCII service name into mojibake and reports a real service as missing.
    #
    # reconfigure() rather than rebinding sys.stdout to a fresh TextIOWrapper: the rebind
    # drops the last reference to the original wrapper, whose finalizer then closes the
    # very buffer the replacement is writing to, and the first reply disappears.
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except (AttributeError, ValueError):
        pass   # already wrapped, or a stream that cannot be reconfigured

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue

        try:
            _handle(cat, msg)
        except Exception:
            # One bad message must never end the session. The message stays generic on
            # purpose: a traceback here would print the deployment path to whoever asked.
            mid = msg.get("id")
            if mid is not None:
                _error(mid, -32603, "Internal error handling that request.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Route an incident to the team that owns it.")
    ap.add_argument("--catalog", default=os.environ.get("ONCALL_CATALOG", "catalog.toml"))
    ns = ap.parse_args(argv)
    path = Path(ns.catalog)
    if not path.exists():
        sys.stderr.write(f"catalog not found: {path.name}\n")
        return 2
    try:
        cat = Catalog.load(path)
    except Exception as exc:
        sys.stderr.write(f"catalog could not be read: {type(exc).__name__}\n")
        return 2
    serve(cat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
