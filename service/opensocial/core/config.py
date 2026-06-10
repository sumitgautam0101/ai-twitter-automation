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
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "NicheConfig":
        return cls(
            slug=data["slug"],
            display_name=data.get("display_name", data["slug"]),
            enabled=data.get("enabled", True),
            sources=data.get("sources", {}) or {},
            raw=data,
        )


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
