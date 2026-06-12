"""Publisher contract, cost model, and the dry-run default.

The fail-safe rule (absorbed from the reference implementation): unless
``POST_DRY_RUN`` is explicitly switched off, :func:`get_publisher` returns a
:class:`DryRunPublisher` that only *describes* what would post. Going live also
requires real credentials, so a misconfigured live attempt degrades to dry-run
rather than erroring mid-run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Cost strategy from project.md: text-only posts are far cheaper than ones that
# include the source link.
COST_TEXT_ONLY = 0.015
COST_WITH_LINK = 0.20


def estimate_cost(*, included_source_link: bool) -> float:
    return COST_WITH_LINK if included_source_link else COST_TEXT_ONLY


@dataclass
class PublishResult:
    ok: bool
    platform_post_id: str | None = None
    platform_post_url: str | None = None
    error: str | None = None
    dry_run: bool = False


class Publisher(ABC):
    platform: str = "x"
    dry_run: bool = False

    @abstractmethod
    def publish(self, *, text: str, media_url: str | None = None) -> PublishResult:
        raise NotImplementedError


class DryRunPublisher(Publisher):
    """Records what *would* post without calling any platform API."""

    def __init__(self, platform: str = "x") -> None:
        self.platform = platform
        self.dry_run = True

    def publish(self, *, text: str, media_url: str | None = None) -> PublishResult:
        return PublishResult(ok=True, dry_run=True, platform_post_id=None)


def get_publisher(settings, *, credentials: dict | None = None) -> Publisher:
    """Pick a publisher honoring the dry-run fail-safe.

    Returns a live :class:`~opensocial.publish.x.XPublisher` only when
    ``settings.dry_run`` is false *and* credentials are present; otherwise a
    :class:`DryRunPublisher`.
    """
    if settings.dry_run or not credentials:
        return DryRunPublisher()
    from opensocial.publish.x import XPublisher

    return XPublisher(credentials)
