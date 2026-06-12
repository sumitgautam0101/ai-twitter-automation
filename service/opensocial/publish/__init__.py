"""Publishing: post a draft to a platform (X today), behind one interface.

:class:`~opensocial.publish.base.Publisher` is the contract; an X
implementation (Tweepy) and a dry-run implementation ship. Selection respects
the fail-safe default — see :func:`~opensocial.publish.base.get_publisher`.
"""

from opensocial.publish.base import (  # noqa: F401
    DryRunPublisher,
    PublishResult,
    Publisher,
    estimate_cost,
    get_publisher,
)
