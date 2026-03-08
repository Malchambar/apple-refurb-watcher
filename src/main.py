from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.checker import ProductEntry, check_refurb_listings
from src.config import load_config, log_config_summary
from src.notifier import (
    notify_new_items,
    notify_removed_items,
    send_heartbeat_notification,
    send_startup_notification,
    send_test_pushover_notification,
)
from src.state import (
    append_listing_history_events,
    build_match_records,
    detect_match_changes,
    detect_removed_matches,
    get_last_successful_notification_at,
    increment_run_counters,
    is_heartbeat_due,
    load_current_matches,
    load_runtime_meta,
    load_seen_fingerprints,
    reconcile_current_match_timestamps,
    record_successful_notification,
    reset_state,
    save_current_matches,
    save_runtime_meta,
    save_seen_fingerprints,
    was_startup_notification_sent,
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


def _to_product_entry(
    item_id: str,
    record_title: str,
    record_url: str,
    record_price: str | None,
    record_family: str | None,
    record_chip: str | None,
    record_cpu_cores: int | None,
    record_gpu_cores: int | None,
    record_memory: str | None,
    record_storage: str | None,
    record_source: str,
    record_dwell_seconds: int | None = None,
) -> ProductEntry:
    return ProductEntry(
        id=item_id,
        title=record_title,
        url=record_url,
        price=record_price,
        family=record_family,
        chip=record_chip,
        cpu_cores=record_cpu_cores,
        gpu_cores=record_gpu_cores,
        memory=record_memory,
        storage=record_storage,
        raw_text="",
        source=record_source,
        dwell_seconds=record_dwell_seconds,
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
    listing_history_path = data_dir / "listing_history.json"
    runtime_meta_path = data_dir / "runtime_meta.json"

    runtime_meta = load_runtime_meta(runtime_meta_path)
    preferred_parser = runtime_meta.get("preferred_parser") or None

    parse_result = check_refurb_listings(
        source_url=config.apple_refurb_url,
        keywords=config.match_keywords,
        timeout=config.request_timeout,
        preferred_source=preferred_parser,
    )

    previous_records = load_current_matches(current_matches_path)
    run_now = datetime.now(UTC)
    current_records = reconcile_current_match_timestamps(
        build_match_records(parse_result.products),
        previous_records,
        now=run_now,
    )
    seen_fingerprints = load_seen_fingerprints(state_path)

    changes = detect_match_changes(current_records, previous_records, seen_fingerprints)
    removed_matches = detect_removed_matches(current_records, previous_records, now=run_now)

    logger.info(
        "State summary: seen_fingerprints=%s current_matches=%s new_changes=%s removed_changes=%s",
        len(seen_fingerprints),
        len(current_records),
        len(changes),
        len(removed_matches),
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
    for removed in removed_matches:
        logger.info(
            "Removed detected: listing_id=%s title=%s dwell_seconds=%s",
            removed.record.listing_id,
            removed.record.title,
            removed.dwell_seconds,
        )

    items_to_notify = [
        _to_product_entry(
            item_id=change.record.fingerprint,
            record_title=change.record.title,
            record_url=change.record.url,
            record_price=change.record.price,
            record_family=change.record.family,
            record_chip=change.record.chip,
            record_cpu_cores=change.record.cpu_cores,
            record_gpu_cores=change.record.gpu_cores,
            record_memory=change.record.memory,
            record_storage=change.record.storage,
            record_source=change.record.source,
        )
        for change in changes
    ]

    if config.force_notify and parse_result.products and not items_to_notify:
        logger.info(
            "FORCE_NOTIFY enabled. Sending notifications for current matches even though "
            "no new fingerprints were detected."
        )
        items_to_notify = [
            _to_product_entry(
                item_id=record.fingerprint,
                record_title=record.title,
                record_url=record.url,
                record_price=record.price,
                record_family=record.family,
                record_chip=record.chip,
                record_cpu_cores=record.cpu_cores,
                record_gpu_cores=record.gpu_cores,
                record_memory=record.memory,
                record_storage=record.storage,
                record_source=record.source,
            )
            for record in current_records
        ]

    if dry_run:
        logger.info("--dry-run enabled: skipping notifications and state file writes.")
    else:
        runtime_meta = increment_run_counters(
            runtime_meta_path,
            had_matches=bool(current_records),
            match_count=len(current_records),
            preferred_parser=parse_result.source,
        )

        added_notification_sent = notify_new_items(
            config,
            items_to_notify,
            project_root=PROJECT_ROOT,
        )
        removed_notification_sent = notify_removed_items(
            config,
            [
                _to_product_entry(
                    item_id=removed.record.fingerprint,
                    record_title=removed.record.title,
                    record_url=removed.record.url,
                    record_price=removed.record.price,
                    record_family=removed.record.family,
                    record_chip=removed.record.chip,
                    record_cpu_cores=removed.record.cpu_cores,
                    record_gpu_cores=removed.record.gpu_cores,
                    record_memory=removed.record.memory,
                    record_storage=removed.record.storage,
                    record_source=removed.record.source,
                    record_dwell_seconds=removed.dwell_seconds,
                )
                for removed in removed_matches
            ],
            project_root=PROJECT_ROOT,
        )
        inventory_notification_sent = added_notification_sent or removed_notification_sent

        startup_notification_sent = False
        heartbeat_sent = False
        if inventory_notification_sent:
            logger.info(
                "Heartbeat skipped because an inventory notification succeeded in this run."
            )
            record_successful_notification(
                runtime_meta_path,
                preferred_parser=parse_result.source,
            )
        else:
            startup_already_sent = was_startup_notification_sent(runtime_meta)
            if config.startup_notify_enabled and not startup_already_sent:
                startup_notification_sent = send_startup_notification(config)
                if startup_notification_sent:
                    record_successful_notification(
                        runtime_meta_path,
                        preferred_parser=parse_result.source,
                        startup_notification_sent=True,
                    )
                else:
                    logger.info("Startup notification attempt did not succeed; continuing.")
            elif config.startup_notify_enabled and startup_already_sent:
                logger.info(
                    "Startup notification already sent for current runtime lifecycle; skipping."
                )

            if not startup_notification_sent and config.heartbeat_enabled:
                last_successful_notification_at = get_last_successful_notification_at(runtime_meta)
                heartbeat_due = is_heartbeat_due(
                    heartbeat_enabled=config.heartbeat_enabled,
                    heartbeat_interval_hours=config.heartbeat_interval_hours,
                    last_successful_notification_at=last_successful_notification_at,
                    now=datetime.now(UTC),
                )
                if heartbeat_due:
                    heartbeat_sent = send_heartbeat_notification(
                        config,
                        polls_since_last_notification=int(
                            runtime_meta.get("runs_since_last_successful_notification", 0)
                        ),
                        zero_match_polls=int(
                            runtime_meta.get(
                                "zero_match_runs_since_last_successful_notification",
                                0,
                            )
                        ),
                        matching_polls=int(
                            runtime_meta.get(
                                "matching_runs_since_last_successful_notification",
                                0,
                            )
                        ),
                        matching_products_seen=int(
                            runtime_meta.get(
                                "matching_products_seen_since_last_successful_notification",
                                0,
                            )
                        ),
                    )
                    if heartbeat_sent:
                        record_successful_notification(
                            runtime_meta_path,
                            preferred_parser=parse_result.source,
                        )
                else:
                    logger.info(
                        "Heartbeat skipped: recent successful notification exists within %s "
                        "hour(s).",
                        config.heartbeat_interval_hours,
                    )
            elif not startup_notification_sent:
                logger.info("Heartbeat disabled by config; skipping heartbeat check.")

        if startup_notification_sent:
            logger.info("Heartbeat skipped because a startup notification succeeded in this run.")

        if not inventory_notification_sent and not startup_notification_sent and not heartbeat_sent:
            save_runtime_meta(
                runtime_meta_path,
                preferred_parser=parse_result.source,
            )

        removed_fingerprints = {removed.record.fingerprint for removed in removed_matches}
        updated_seen = set(seen_fingerprints) - removed_fingerprints
        for change in changes:
            updated_seen.add(change.record.fingerprint)
        save_seen_fingerprints(state_path, updated_seen)

        append_listing_history_events(listing_history_path, removed_matches)
        save_current_matches(current_matches_path, current_records)

    logger.info(
        "Run complete. parser_source=%s relevant_matches=%s new_changes=%s removed_changes=%s",
        parse_result.source,
        len(current_records),
        len(changes),
        len(removed_matches),
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
    listing_history_path = data_dir / "listing_history.json"
    runtime_meta_path = data_dir / "runtime_meta.json"

    archived_path = reset_state(state_path, archive_dir=archive_dir)
    save_current_matches(current_matches_path, [])
    save_runtime_meta(
        runtime_meta_path,
        preferred_parser="",
        reset_last_successful_notification=True,
        startup_notification_sent=False,
        total_poll_runs=0,
        reset_since_last_successful_notification=True,
    )

    if archived_path:
        logger.info("State reset complete. Archived previous state to %s", archived_path)
    else:
        logger.info("State reset complete. No previous state file existed to archive.")

    logger.info("New empty state file created at %s", state_path)
    logger.info("Current matches cleared at %s", current_matches_path)
    logger.info("Listing history retained at %s", listing_history_path)
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
