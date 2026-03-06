from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.checker import check_refurb_listings
from src.config import load_config, log_config_summary
from src.notifier import notify_new_items, send_test_pushover_notification
from src.state import diff_new_items, load_seen_ids, save_seen_ids, update_seen_with_items


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def setup_logging(log_file: Path) -> None:
    log_path = (PROJECT_ROOT / log_file).resolve() if not log_file.is_absolute() else log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def resolve_path(path: Path) -> Path:
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path


def run_once(*, test_notifier: bool = False) -> int:
    config = load_config()
    setup_logging(config.log_file)
    logger = logging.getLogger(__name__)

    logger.info("Starting apple-refurb-watcher run.")
    log_config_summary(config)

    if test_notifier:
        logger.info("Running in --test-notifier mode.")
        send_test_pushover_notification(config)
        logger.info("Test notifier run complete.")
        return 0

    state_path = resolve_path(config.state_file)

    products = check_refurb_listings(
        source_url=config.apple_refurb_url,
        keywords=config.match_keywords,
        timeout=config.request_timeout,
    )

    seen_ids = load_seen_ids(state_path)
    new_items = diff_new_items(products, seen_ids)
    logger.info(
        "State summary: seen_ids=%s current_matches=%s new_matches=%s",
        len(seen_ids),
        len(products),
        len(new_items),
    )

    items_to_notify = new_items
    if config.force_notify and products and not new_items:
        logger.info(
            "FORCE_NOTIFY enabled. Sending notifications for current matches even though all are already seen."
        )
        items_to_notify = products

    notify_new_items(config, items_to_notify, project_root=PROJECT_ROOT)

    updated_ids = update_seen_with_items(seen_ids, products)
    save_seen_ids(state_path, updated_ids)

    logger.info("Run complete. total_matches=%s new_matches=%s", len(products), len(new_items))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Apple Refurb Watcher")
    parser.add_argument(
        "--test-notifier",
        action="store_true",
        help="Send a standalone Pushover test notification and exit.",
    )
    args = parser.parse_args()

    try:
        return run_once(test_notifier=args.test_notifier)
    except Exception:
        logging.getLogger(__name__).exception("Fatal error in watcher run.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
