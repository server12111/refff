import logging
from flyerapi import Flyer as FlyerClient

from config import config

logger = logging.getLogger(__name__)

_client: FlyerClient | None = None


def _get_client() -> FlyerClient | None:
    """Return a cached Flyer client, or None if FLYER_KEY is not set."""
    if not config.FLYER_KEY:
        return None
    global _client
    if _client is None:
 _client = FlyerClient(config.FLYER_KEY, debug=True)
    return _client


async def check_subscription(user_id: int, language_code: str | None = None) -> bool:
    """
    Check whether the user has subscribed to all required Flyer channels.

    Returns True if:
      - FLYER_KEY is not configured (feature disabled), or
      - the user has subscribed to all channels.

    Returns False if the user is missing at least one subscription.
    When False is returned, Flyer has already sent the subscription wall
    to the user — no additional message is needed.
    """
    client = _get_client()
    if client is None:
        return True

    try:
        return await client.check(
            user_id=user_id,
            language_code=language_code or "en",
        )
    except Exception as exc:
        logger.warning("Flyer API error for user %s: %s", user_id, exc)
        return True  # on error — allow access so users are not blocked

