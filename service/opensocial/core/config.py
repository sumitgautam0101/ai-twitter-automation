"""Niche profile loading.

Phase 1 keeps niche config on disk as JSON. A niche names which sources it
enables and the per-source settings (feeds, queries, limits). Later phases
mirror this into the ``niche_profiles`` DB table for the dashboard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NicheConfig:
    slug: str
    display_name: str
    enabled: bool = True
    # source_name -> per-source settings dict
    sources: dict[str, dict] = field(default_factory=dict)
    # The X account (PlatformAccount.id) that owns this niche; ``None`` when
    # unassigned. Fetching is account-agnostic — this only scopes the per-niche
    # post-creation / publishing stages.
    account_id: str | None = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "NicheConfig":
        return cls(
            slug=data["slug"],
            display_name=data.get("display_name", data["slug"]),
            enabled=data.get("enabled", True),
            sources=data.get("sources", {}) or {},
            account_id=niche_account_id(data),
            raw=data,
        )


def niche_account_id(raw_config: dict) -> str | None:
    """The owning account id stored in a niche's raw config, or ``None``.

    Empty / blank values normalize to ``None`` so an unassigned niche is
    unambiguous.
    """
    value = (raw_config or {}).get("account_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def load_niche(path: str | Path) -> NicheConfig:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return NicheConfig.from_dict(data)


def load_all_niches(config_dir: str | Path) -> list[NicheConfig]:
    config_dir = Path(config_dir)
    niches: list[NicheConfig] = []
    for path in sorted(config_dir.glob("*.json")):
        niches.append(load_niche(path))
    return niches
