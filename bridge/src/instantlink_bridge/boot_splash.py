"""Early LCD boot splash entry point."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from instantlink_bridge.config import DEFAULT_CONFIG_PATH, load_config
from instantlink_bridge.ui.display import create_display
from instantlink_bridge.ui.models import UiMode, UiSnapshot

LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Draw a static splash frame and exit."""

    parser = argparse.ArgumentParser(description="Draw the InstantLink Bridge boot splash")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"config file path (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=0.25,
        help="seconds to keep the process alive after drawing",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = load_config(args.config)
    display = create_display()
    display.set_idle_stage("active")
    display.render(
        UiSnapshot(
            mode=UiMode.BOOTING,
            ftp_host=config.ftp.host,
            printer_status_message="Starting bridge",
        )
    )
    LOGGER.info("boot_splash.rendered")
    time.sleep(max(0.0, args.hold))


if __name__ == "__main__":
    main()
