"""Background worker entrypoint:  python -m app.worker"""

from __future__ import annotations

import asyncio
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs.runner import run_forever


def main() -> None:
    configure_logging()
    get_settings()  # fail fast on invalid configuration
    stop = asyncio.Event()

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_forever(stop)

    asyncio.run(_main())


if __name__ == "__main__":
    main()
