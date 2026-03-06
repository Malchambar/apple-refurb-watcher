from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.checker import check_refurb_listings
from src.config import load_config
from src.notifier import notify_new_items
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


def run_once() -> int:
    config = load_config()
    setup_logging(config.log_file)
    logger = logging.getLogger(__name__)

    logger.info("Starting apple-refurb-watcher run.")

    state_path = resolve_path(config.state_file)

    products = check_refurb_listings(
        source_url=config.apple_refurb_url,
        keywords=config.match_keywords,
        timeout=config.request_timeout,
    )

    seen_ids = load_seen_ids(state_path)
    new_items = diff_new_items(products, seen_ids)

    notify_new_items(config, new_items, project_root=PROJECT_ROOT)

    updated_ids = update_seen_with_items(seen_ids, products)
    save_seen_ids(state_path, updated_ids)

    logger.info("Run complete. total_matches=%s new_matches=%s", len(products), len(new_items))
    return 0


def main() -> int:
    try:
        return run_once()
    except Exception:
        logging.getLogger(__name__).exception("Fatal error in watcher run.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
