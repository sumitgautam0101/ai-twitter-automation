"""Source plugins.

Importing this package registers every built-in source via its ``@register``
decorator, so ``get_source`` / ``available_sources`` work without manual wiring.
"""

from opensocial.sources.base import (  # noqa: F401
    Source,
    available_sources,
    get_source,
    register,
)

# Import plugin modules for their registration side effects.
from opensocial.sources import (  # noqa: F401,E402
    arxiv,
    devto,
    finnhub,
    gdelt,
    github_releases,
    guardian,
    hackernews,
    medium,
    nasa,
    producthunt,
    reddit,
    rss,
    youtube,
    yfinance_source,
)
