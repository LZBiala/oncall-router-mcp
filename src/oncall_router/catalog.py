"""The service catalog: load it, and resolve the name a tired person typed.

The catalog is data. Nothing in this module knows anything about a particular service,
team or severity, which is what lets a different catalog produce entirely different
answers with no code change.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Catalog:
    services: dict[str, Any]
    teams: dict[str, Any]
    severities: dict[str, Any]
    _alias_index: dict[str, str]

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        services = raw.get("services", {})
        index: dict[str, str] = {}
        for name, svc in services.items():
            index[_norm(name)] = name
            for alias in svc.get("aliases", []):
                # first writer wins, so a canonical name can never be shadowed by an alias
                index.setdefault(_norm(alias), name)
        return cls(
            services=services,
            teams=raw.get("teams", {}),
            severities=raw.get("severities", {}),
            _alias_index=index,
        )

    def resolve(self, typed: str) -> str | None:
        """Canonical service name for whatever the human typed, or None.

        Returns None rather than a best guess. A near-miss that silently resolves is how
        an incident ends up escalated to the wrong team with everybody confident.
        """
        if not typed:
            return None
        return self._alias_index.get(_norm(typed))

    def suggest(self, typed: str, limit: int = 3) -> list[str]:
        """Candidates to show a human who typed something unknown. Never an answer."""
        if not typed:
            return []
        hits = get_close_matches(_norm(typed), list(self._alias_index), n=limit, cutoff=0.6)
        seen: list[str] = []
        for h in hits:
            canonical = self._alias_index[h]
            if canonical not in seen:
                seen.append(canonical)
        return seen

    def team_of(self, service_name: str) -> dict[str, Any] | None:
        svc = self.services.get(service_name)
        if not svc:
            return None
        return self.teams.get(svc.get("owner"))


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().replace("_", "-").split())
