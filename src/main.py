from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.checker import ProductEntry, check_refurb_listings
from src.config import load_config, log_config_summary
from src.notifier import notify_new_items, send_test_pushover_notification
from src.state import (
    build_match_records,
    detect_match_changes,
    load_current_matches,
    load_runtime_meta,
    load_seen_fingerprints,
    reset_state,
    save_current_matches,
    save_runtime_meta,
    save_seen_fingerprints,
)

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


def ensure_runtime_directories(state_path: Path, log_file_path: Path) -> None:
    data_dir = state_path.parent
    archive_dir = data_dir / "archive"
    logs_dir = log_file_path.parent

    data_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)


def _to_product_entry(item_id: str, record_title: str, record_url: str, record_price: str | None, record_memory: str | None, record_storage: str | None, record_source: str) -> ProductEntry:
    return ProductEntry(
        id=item_id,
        title=record_title,
        url=record_url,
        price=record_price,
        memory=record_memory,
        storage=record_storage,
        raw_text="",
        source=record_source,
    )


def run_once(*, test_notifier: bool = False, dry_run: bool = False) -> int:
    config = load_config()
    state_path = resolve_path(config.state_file)
    log_path = resolve_path(config.log_file)
    ensure_runtime_directories(state_path, log_path)
    setup_logging(config.log_file)
    logger = logging.getLogger(__name__)

    logger.info("Starting apple-refurb-watcher run.")
    log_config_summary(config)

    if test_notifier:
        logger.info("Running in --test-notifier mode.")
        send_test_pushover_notification(config)
        logger.info("Test notifier run complete.")
        return 0

    data_dir = state_path.parent
    current_matches_path = data_dir / "current_matches.json"
    runtime_meta_path = data_dir / "runtime_meta.json"

    runtime_meta = load_runtime_meta(runtime_meta_path)
    preferred_parser = runtime_meta.get("preferred_parser") or None

    parse_result = check_refurb_listings(
        source_url=config.apple_refurb_url,
        keywords=config.match_keywords,
        timeout=config.request_timeout,
        preferred_source=preferred_parser,
    )

    current_records = build_match_records(parse_result.products)
    previous_records = load_current_matches(current_matches_path)
    seen_fingerprints = load_seen_fingerprints(state_path)

    changes = detect_match_changes(current_records, previous_records, seen_fingerprints)

    logger.info(
        "State summary: seen_fingerprints=%s current_matches=%s new_changes=%s",
        len(seen_fingerprints),
        len(current_records),
        len(changes),
    )

    for change in changes:
        logger.info(
            "Change detected: type=%s fingerprint=%s title=%s price=%s url=%s",
            change.change_type,
            change.record.fingerprint,
            change.record.title,
            change.record.price,
            change.record.url,
        )

    items_to_notify = [
        _to_product_entry(
            item_id=change.record.fingerprint,
            record_title=change.record.title,
            record_url=change.record.url,
            record_price=change.record.price,
            record_memory=change.record.memory,
            record_storage=change.record.storage,
            record_source=change.record.source,
        )
        for change in changes
    ]

    if config.force_notify and parse_result.products and not items_to_notify:
        logger.info(
            "FORCE_NOTIFY enabled. Sending notifications for current matches even though no new fingerprints were detected."
        )
        items_to_notify = [
            _to_product_entry(
                item_id=record.fingerprint,
                record_title=record.title,
                record_url=record.url,
                record_price=record.price,
                record_memory=record.memory,
                record_storage=record.storage,
                record_source=record.source,
            )
            for record in current_records
        ]

    if dry_run:
        logger.info("--dry-run enabled: skipping notifications and state file writes.")
    else:
        notify_new_items(config, items_to_notify, project_root=PROJECT_ROOT)

        updated_seen = set(seen_fingerprints)
        for change in changes:
            updated_seen.add(change.record.fingerprint)
        save_seen_fingerprints(state_path, updated_seen)

        save_current_matches(current_matches_path, current_records)
        save_runtime_meta(runtime_meta_path, preferred_parser=parse_result.source)

    logger.info(
        "Run complete. parser_source=%s relevant_matches=%s new_changes=%s",
        parse_result.source,
        len(current_records),
        len(changes),
    )
    return 0


def handle_reset_state() -> int:
    config = load_config()
    state_path = resolve_path(config.state_file)
    log_path = resolve_path(config.log_file)
    ensure_runtime_directories(state_path, log_path)
    setup_logging(config.log_file)
    logger = logging.getLogger(__name__)

    data_dir = state_path.parent
    archive_dir = data_dir / "archive"
    current_matches_path = data_dir / "current_matches.json"
    runtime_meta_path = data_dir / "runtime_meta.json"

    archived_path = reset_state(state_path, archive_dir=archive_dir)
    save_current_matches(current_matches_path, [])
    save_runtime_meta(runtime_meta_path, preferred_parser=None)

    if archived_path:
        logger.info("State reset complete. Archived previous state to %s", archived_path)
    else:
        logger.info("State reset complete. No previous state file existed to archive.")

    logger.info("New empty state file created at %s", state_path)
    logger.info("Current matches cleared at %s", current_matches_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Apple Refurb Watcher")
    parser.add_argument(
        "--test-notifier",
        action="store_true",
        help="Send a standalone Pushover test notification and exit.",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Archive existing seen state and create a fresh empty state file, then exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run parsing/matching without sending notifications or updating state files.",
    )
    args = parser.parse_args()

    try:
        if args.reset_state:
            return handle_reset_state()
        return run_once(test_notifier=args.test_notifier, dry_run=args.dry_run)
    except Exception:
        logging.getLogger(__name__).exception("Fatal error in watcher run.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
