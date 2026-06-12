"""Source plugin framework: the ``Source`` ABC and a name-based registry.

Adding a new content source means writing a new ``Source`` subclass and
decorating it with ``@register`` — no changes anywhere else. Each plugin
fetches and normalizes its content into ``ContentItem`` objects.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from opensocial.core.models import ContentItem

DEFAULT_TIMEOUT = 20.0
USER_AGENT = "OpenX/0.1 (+https://github.com/openx)"


def resolve_api_key(
    config: dict,
    *env_names: str,
    required: bool = True,
    source_name: str = "source",
) -> str | None:
    """Find an API key from config ``api_key`` or the given env vars.

    Raises ``RuntimeError`` if ``required`` and none is found, so the CLI's
    per-source error handler reports it clearly without sinking the run.
    """
    key = config.get("api_key")
    if not key:
        for env in env_names:
            key = os.environ.get(env)
            if key:
                break
    if not key and required:
        envs = " or ".join(env_names) if env_names else "an API key"
        raise RuntimeError(
            f"{source_name} requires an API key (set config 'api_key' or env {envs})"
        )
    return key


def parse_iso8601(value: str | None) -> datetime:
    """Parse an ISO-8601 timestamp, defaulting to now (UTC) on failure."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Source(ABC):
    """Base class for all content sources.

    Subclasses set ``name`` (unique, used as ``source_name`` and the registry
    key) and ``category`` (the default ``source_category``), and implement
    :meth:`fetch`.
    """

    name: str
    category: str

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    async def fetch(self) -> list[ContentItem]:
        """Fetch and normalize content into ``ContentItem`` objects."""
        raise NotImplementedError


_REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    """Class decorator that adds a ``Source`` subclass to the registry."""
    if not getattr(cls, "name", None):
        raise ValueError(f"{cls.__name__} must define a non-empty 'name'")
    if cls.name in _REGISTRY:
        raise ValueError(f"Duplicate source name: {cls.name!r}")
    _REGISTRY[cls.name] = cls
    return cls


def get_source(name: str) -> type[Source]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown source {name!r}. Available: {sorted(_REGISTRY)}"
        ) from None


def available_sources() -> list[str]:
    return sorted(_REGISTRY)
