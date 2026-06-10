"""Source plugin framework: the ``Source`` ABC and a name-based registry.

Adding a new content source means writing a new ``Source`` subclass and
decorating it with ``@register`` — no changes anywhere else. Each plugin
fetches and normalizes its content into ``ContentItem`` objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from opensocial.core.models import ContentItem

DEFAULT_TIMEOUT = 20.0
USER_AGENT = "OpenSocial/0.1 (+https://github.com/opensocial)"


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
