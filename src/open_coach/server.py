"""FastMCP server entry point for the Open Coach.

Initializes the watch provider, Strava and CoachStorage in the lifespan,
then imports all tool/resource modules for automatic registration.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from open_coach.instructions import SERVER_INSTRUCTIONS
from open_coach.storage import CoachStorage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def coach_lifespan(_server: FastMCP) -> AsyncIterator[dict]:
    """Initialize shared state for the server lifetime."""
    storage = CoachStorage()
    storage.ensure_dirs()

    from open_coach.providers import create_provider

    watch = create_provider()

    strava_client = None
    try:
        from open_coach.strava_client import get_strava_client

        strava_client = get_strava_client()
        if strava_client is not None:
            logger.info("Strava: token cache found ✓")
    except Exception as err:
        logger.warning("Strava: init failed — integration disabled. (%s)", err)

    yield {"watch": watch, "strava": strava_client, "storage": storage}


mcp = FastMCP(
    "Open Coach",
    instructions=SERVER_INSTRUCTIONS,
    lifespan=coach_lifespan,
)

# Import tool/resource modules to register them with the mcp instance
from open_coach.tools import (  # noqa: E402, F401
    activities,
    guides,
    health,
    memory,
    plans,
    race,
    recovery,
    strava,
    training,
    workout,
)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
