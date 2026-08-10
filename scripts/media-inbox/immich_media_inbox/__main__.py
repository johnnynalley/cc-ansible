"""Service entry point."""

from __future__ import annotations

import logging
import signal
import sys
import threading

from . import __version__
from .clients import ImmichClient, SeerrClient
from .config import Config
from .scanner import Scanner
from .store import Store


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.from_env()
    store = Store(config.database_path)
    immich = ImmichClient(
        config.immich_url,
        config.immich_api_key,
        request_delay_ms=config.api_request_delay_ms,
    )
    seerr = SeerrClient(
        config.seerr_url,
        config.seerr_api_key,
        request_delay_ms=config.api_request_delay_ms,
    )
    scanner = Scanner(config, store, immich, seerr)
    scanner.start()
    stopped = threading.Event()

    def shutdown(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.getLogger(__name__).info(
        "starting headless Immich Media Inbox %s (requests_enabled=%s)",
        __version__,
        config.requests_enabled,
    )
    try:
        stopped.wait()
    finally:
        scanner.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
