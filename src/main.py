from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.checker import ProductEntry, check_refurb_listings
from src.config import AppConfig, load_config, log_config_summary
from src.db import get_session, init_db
from src.notifier import (
    notify_new_items,
    notify_removed_items,
    send_heartbeat_notification,
    send_startup_notification,
    send_test_pushover_notification,
)
from src.state import (
    create_poll_run,
    finish_poll_run_failure,
    finish_poll_run_success,
    get_heartbeat_counters,
    get_last_successful_notification_at,
    get_preferred_parser,
    increment_run_counters,
    is_heartbeat_due,
    matches_alert_filter,
    record_successful_notification,
    reset_database_state,
    set_preferred_parser,
    sync_inventory_snapshot,
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


def _resolve_sqlite_path(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    return Path(database_url.replace("sqlite:///", "", 1))


def ensure_runtime_directories(config: AppConfig) -> None:
    log_path = (PROJECT_ROOT / config.log_file).resolve() if not config.log_file.is_absolute() else config.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    sqlite_path = _resolve_sqlite_path(config.database_url)
    if sqlite_path is not None:
        db_path = (PROJECT_ROOT / sqlite_path).resolve() if not sqlite_path.is_absolute() else sqlite_path
        db_path.parent.mkdir(parents=True, exist_ok=True)


def _to_product_entry(item: ProductEntry) -> ProductEntry:
    return ProductEntry(
        id=item.id,
        title=item.title,
        url=item.url,
        price=item.price,
        family=item.family,
        chip=item.chip,
        cpu_cores=item.cpu_cores,
        gpu_cores=item.gpu_cores,
        memory=item.memory,
        storage=item.storage,
        raw_text=item.raw_text,
        source=item.source,
        dwell_seconds=item.dwell_seconds,
    )


def _count_relevant_products(products: list[ProductEntry], keywords: list[str]) -> int:
    return sum(1 for product in products if matches_alert_filter(product, keywords))


def run_once(*, test_notifier: bool = False, dry_run: bool = False) -> int:
    config = load_config()
    ensure_runtime_directories(config)
    setup_logging(config.log_file)
    logger = logging.getLogger(__name__)

    init_db(config.database_url)

    logger.info("Starting apple-refurb-watcher run.")
    log_config_summary(config)

    if test_notifier:
        logger.info("Running in --test-notifier mode.")
        send_test_pushover_notification(config)
        logger.info("Test notifier run complete.")
        return 0

    if dry_run:
        with get_session(config.database_url) as session:
            preferred_parser = get_preferred_parser(session)
        parse_result = check_refurb_listings(
            source_url=config.apple_refurb_url,
            timeout=config.request_timeout,
            preferred_source=preferred_parser,
        )
        relevant_count = _count_relevant_products(parse_result.products, config.match_keywords)
        logger.info(
            "--dry-run: parser_source=%s total_products=%s relevant_products=%s (no DB writes, no notifications)",
            parse_result.source,
            len(parse_result.products),
            relevant_count,
        )
        return 0

    pending_error: Exception | None = None
    with get_session(config.database_url) as session:
        poll_run = create_poll_run(session)
        try:
            preferred_parser = get_preferred_parser(session)
            parse_result = check_refurb_listings(
                source_url=config.apple_refurb_url,
                timeout=config.request_timeout,
                preferred_source=preferred_parser,
            )
            sync_result = sync_inventory_snapshot(
                session,
                poll_run_id=poll_run.id,
                products=parse_result.products,
                alert_keywords=config.match_keywords,
                now=datetime.now(UTC),
            )

            logger.info(
                "Inventory summary: total_products=%s relevant_products=%s new_alerts=%s removed_alerts=%s",
                sync_result.total_products_found,
                sync_result.relevant_products_found,
                len(sync_result.new_alert_products),
                len(sync_result.removed_alert_products),
            )

            increment_run_counters(
                session,
                had_matches=sync_result.relevant_products_found > 0,
                match_count=sync_result.relevant_products_found,
            )
            set_preferred_parser(session, parse_result.source)

            added_notification_sent = notify_new_items(
                config,
                [_to_product_entry(item) for item in sync_result.new_alert_products],
                project_root=PROJECT_ROOT,
            )
            removed_notification_sent = notify_removed_items(
                config,
                [_to_product_entry(item) for item in sync_result.removed_alert_products],
                project_root=PROJECT_ROOT,
            )

            inventory_notification_sent = added_notification_sent or removed_notification_sent
            startup_notification_sent = False
            heartbeat_sent = False

            if inventory_notification_sent:
                logger.info("Heartbeat skipped because an inventory notification succeeded in this run.")
                record_successful_notification(session)
            else:
                startup_already_sent = was_startup_notification_sent(session)
                if config.startup_notify_enabled and not startup_already_sent:
                    startup_notification_sent = send_startup_notification(config)
                    if startup_notification_sent:
                        record_successful_notification(session, startup_notification_sent=True)
                    else:
                        logger.info("Startup notification attempt did not succeed; continuing.")
                elif config.startup_notify_enabled and startup_already_sent:
                    logger.info("Startup notification already sent for current runtime lifecycle; skipping.")

                if not startup_notification_sent and config.heartbeat_enabled:
                    last_successful_notification_at = get_last_successful_notification_at(session)
                    heartbeat_due = is_heartbeat_due(
                        heartbeat_enabled=config.heartbeat_enabled,
                        heartbeat_interval_hours=config.heartbeat_interval_hours,
                        last_successful_notification_at=last_successful_notification_at,
                        now=datetime.now(UTC),
                    )
                    if heartbeat_due:
                        runs_since, zero_match, matching_runs, matching_products = get_heartbeat_counters(session)
                        heartbeat_sent = send_heartbeat_notification(
                            config,
                            polls_since_last_notification=runs_since,
                            zero_match_polls=zero_match,
                            matching_polls=matching_runs,
                            matching_products_seen=matching_products,
                        )
                        if heartbeat_sent:
                            record_successful_notification(session)
                    else:
                        logger.info(
                            "Heartbeat skipped: recent successful notification exists within %s hour(s).",
                            config.heartbeat_interval_hours,
                        )
                elif not startup_notification_sent:
                    logger.info("Heartbeat disabled by config; skipping heartbeat check.")

            finish_poll_run_success(
                poll_run,
                parser_source=parse_result.source,
                total_products_found=sync_result.total_products_found,
                relevant_products_found=sync_result.relevant_products_found,
                finished_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.exception("Run failed.")
            finish_poll_run_failure(
                poll_run,
                parser_source=None,
                total_products_found=0,
                relevant_products_found=0,
                error_message=str(exc),
                finished_at=datetime.now(UTC),
            )
            pending_error = exc

    if pending_error:
        raise pending_error

    logger.info("Run complete.")
    return 0


def handle_reset_state() -> int:
    config = load_config()
    ensure_runtime_directories(config)
    setup_logging(config.log_file)
    logger = logging.getLogger(__name__)

    init_db(config.database_url)
    with get_session(config.database_url) as session:
        reset_database_state(session)

    logger.info("Database state reset complete for %s", config.database_url)
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
        help="Clear DB-backed run/listing/state tables, then exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run parsing only without notifications or DB writes.",
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
