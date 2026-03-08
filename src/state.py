from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from src.checker import ProductEntry
from src.models import AppState, Listing, ListingObservation, PollRun, ProductConfig

logger = logging.getLogger(__name__)

STATE_LAST_SUCCESS_AT = "last_successful_notification_at"
STATE_STARTUP_SENT = "startup_notification_sent"
STATE_PREFERRED_PARSER = "preferred_parser"
STATE_TOTAL_RUNS = "total_poll_runs"
STATE_RUNS_SINCE_NOTIFY = "runs_since_last_successful_notification"
STATE_ZERO_MATCH_RUNS = "zero_match_runs_since_last_successful_notification"
STATE_MATCHING_RUNS = "matching_runs_since_last_successful_notification"
STATE_MATCHING_PRODUCTS = "matching_products_seen_since_last_successful_notification"


@dataclass(frozen=True)
class InventorySyncResult:
    new_alert_products: list[ProductEntry]
    removed_alert_products: list[ProductEntry]
    total_products_found: int
    relevant_products_found: int


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    return value.astimezone(UTC)


def _short_hash(parts: list[str]) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    pattern = r"\b" + re.escape(phrase).replace(r"\ ", r"\s+") + r"\b"
    return re.search(pattern, text) is not None


def _extract_listing_key(item: ProductEntry) -> str:
    stable = (item.id or "").strip().lower()
    if stable:
        return stable
    return _short_hash([_normalize_text(item.title), _normalize_text(item.url), _normalize_text(item.price)])


def _extract_memory_gb(value: str | None) -> int | None:
    match = re.search(r"(\d+)\s*gb", value or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_storage_gb(value: str | None) -> int | None:
    text = (value or "").lower()
    match_tb = re.search(r"(\d+)\s*tb", text)
    if match_tb:
        return int(match_tb.group(1)) * 1024
    match_gb = re.search(r"(\d+)\s*gb", text)
    if match_gb:
        return int(match_gb.group(1))
    return None


def _build_config_key(item: ProductEntry) -> str:
    parts = [
        _normalize_text(item.family),
        _normalize_text(item.chip),
        str(item.cpu_cores or ""),
        str(item.gpu_cores or ""),
        str(_extract_memory_gb(item.memory) or ""),
        str(_extract_storage_gb(item.storage) or ""),
    ]
    return _short_hash(parts)


def matches_alert_filter(item: ProductEntry, keywords: list[str]) -> bool:
    if not keywords:
        return False
    title_norm = _normalize_text(item.title)
    family_norm = _normalize_text(item.family)
    chip_norm = _normalize_text(item.chip)

    for keyword in keywords:
        key_norm = _normalize_text(keyword)
        if not key_norm:
            continue
        if _contains_phrase(title_norm, key_norm):
            return True
        if family_norm and key_norm == family_norm:
            return True
        if chip_norm and _contains_phrase(chip_norm, key_norm):
            return True
    return False


def _find_state(session: Session, key: str) -> AppState | None:
    # Check pending objects first so repeated updates in the same transaction
    # reuse one row instead of staging duplicate INSERTs for the same PK.
    for pending in session.new:
        if isinstance(pending, AppState) and pending.key == key:
            return pending
    return session.get(AppState, key)


def _get_state_str(session: Session, key: str, default: str = "") -> str:
    row = _find_state(session, key)
    if row is None:
        return default
    return row.value


def _set_state(session: Session, key: str, value: str) -> None:
    row = _find_state(session, key)
    if row is None:
        row = AppState(key=key, value=value)
        session.add(row)
    else:
        row.value = value


def _get_state_int(session: Session, key: str, default: int = 0) -> int:
    raw = _get_state_str(session, key, str(default)).strip()
    try:
        return max(int(raw), 0)
    except ValueError:
        return default


def _set_state_int(session: Session, key: str, value: int) -> None:
    _set_state(session, key, str(max(value, 0)))


def _get_state_bool(session: Session, key: str, default: bool = False) -> bool:
    raw = _get_state_str(session, key, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _set_state_bool(session: Session, key: str, value: bool) -> None:
    _set_state(session, key, "true" if value else "false")


def _get_state_datetime(session: Session, key: str) -> datetime | None:
    raw = _get_state_str(session, key, "").strip()
    if not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _set_state_datetime(session: Session, key: str, value: datetime) -> None:
    _set_state(session, key, value.astimezone(UTC).isoformat())


def create_poll_run(session: Session, *, started_at: datetime | None = None) -> PollRun:
    run = PollRun(started_at=_utc_now(started_at), status="running")
    session.add(run)
    session.flush()
    return run


def finish_poll_run_success(
    poll_run: PollRun,
    *,
    parser_source: str,
    total_products_found: int,
    relevant_products_found: int,
    finished_at: datetime | None = None,
) -> None:
    poll_run.finished_at = _utc_now(finished_at)
    poll_run.parser_source = parser_source
    poll_run.total_products_found = total_products_found
    poll_run.relevant_products_found = relevant_products_found
    poll_run.status = "success"
    poll_run.error_message = None


def finish_poll_run_failure(
    poll_run: PollRun,
    *,
    error_message: str,
    parser_source: str | None = None,
    total_products_found: int = 0,
    relevant_products_found: int = 0,
    finished_at: datetime | None = None,
) -> None:
    poll_run.finished_at = _utc_now(finished_at)
    poll_run.parser_source = parser_source
    poll_run.total_products_found = total_products_found
    poll_run.relevant_products_found = relevant_products_found
    poll_run.status = "failure"
    poll_run.error_message = error_message[:2000]


def get_preferred_parser(session: Session) -> str | None:
    value = _get_state_str(session, STATE_PREFERRED_PARSER, "").strip()
    return value or None


def set_preferred_parser(session: Session, parser_source: str) -> None:
    _set_state(session, STATE_PREFERRED_PARSER, parser_source)


def sync_inventory_snapshot(
    session: Session,
    *,
    poll_run_id: int,
    products: list[ProductEntry],
    alert_keywords: list[str],
    now: datetime | None = None,
) -> InventorySyncResult:
    observed_at = _utc_now(now)
    products_by_listing: dict[str, ProductEntry] = {}
    for product in products:
        listing_key = _extract_listing_key(product)
        products_by_listing[listing_key] = product

    new_alert_products: list[ProductEntry] = []
    removed_alert_products: list[ProductEntry] = []
    relevant_products_found = 0

    existing_available_stmt: Select[tuple[Listing]] = select(Listing).where(Listing.last_known_available.is_(True))
    existing_available = session.scalars(existing_available_stmt).all()
    existing_available_by_key = {listing.listing_key: listing for listing in existing_available}

    for listing_key, product in products_by_listing.items():
        is_relevant = matches_alert_filter(product, alert_keywords)
        if is_relevant:
            relevant_products_found += 1

        config_key = _build_config_key(product)
        config = session.scalar(select(ProductConfig).where(ProductConfig.config_key == config_key))
        if config is None:
            config = ProductConfig(
                config_key=config_key,
                family=product.family,
                title_normalized=_normalize_text(product.title),
                chip=product.chip,
                cpu_cores=product.cpu_cores,
                gpu_cores=product.gpu_cores,
                memory_gb=_extract_memory_gb(product.memory),
                storage_gb=_extract_storage_gb(product.storage),
                raw_title_example=product.title,
            )
            session.add(config)
            session.flush()
        else:
            config.family = product.family
            config.title_normalized = _normalize_text(product.title)
            config.chip = product.chip
            config.cpu_cores = product.cpu_cores
            config.gpu_cores = product.gpu_cores
            config.memory_gb = _extract_memory_gb(product.memory)
            config.storage_gb = _extract_storage_gb(product.storage)
            config.raw_title_example = product.title

        listing = session.scalar(select(Listing).where(Listing.listing_key == listing_key))
        newly_available = False
        if listing is None:
            listing = Listing(
                listing_key=listing_key,
                product_config_id=config.id,
                title=product.title,
                url=product.url,
                price_text=product.price,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                disappeared_at=None,
                last_known_available=True,
            )
            session.add(listing)
            session.flush()
            newly_available = True
        else:
            if not listing.last_known_available:
                newly_available = True
                listing.first_seen_at = observed_at
                listing.disappeared_at = None
            listing.product_config_id = config.id
            listing.title = product.title
            listing.url = product.url
            listing.price_text = product.price
            listing.last_seen_at = observed_at
            listing.last_known_available = True

        session.add(
            ListingObservation(
                poll_run_id=poll_run_id,
                listing_id=listing.id,
                observed_at=observed_at,
                price_text=product.price,
                available=True,
            )
        )

        if newly_available and is_relevant:
            new_alert_products.append(product)

    current_listing_keys = set(products_by_listing.keys())
    removed_listings = [
        listing
        for key, listing in existing_available_by_key.items()
        if key not in current_listing_keys
    ]
    for listing in removed_listings:
        listing.last_known_available = False
        listing.disappeared_at = observed_at
        session.add(
            ListingObservation(
                poll_run_id=poll_run_id,
                listing_id=listing.id,
                observed_at=observed_at,
                price_text=listing.price_text,
                available=False,
            )
        )

        config = listing.product_config
        dwell_seconds = max(0, int((listing.last_seen_at - listing.first_seen_at).total_seconds()))
        removed_product = ProductEntry(
            id=listing.listing_key,
            title=listing.title,
            url=listing.url,
            price=listing.price_text,
            family=config.family if config else None,
            chip=config.chip if config else None,
            cpu_cores=config.cpu_cores if config else None,
            gpu_cores=config.gpu_cores if config else None,
            memory=f"{config.memory_gb}GB RAM" if config and config.memory_gb else None,
            storage=f"{config.storage_gb // 1024}TB SSD"
            if config and config.storage_gb and config.storage_gb % 1024 == 0 and config.storage_gb >= 1024
            else (f"{config.storage_gb}GB SSD" if config and config.storage_gb else None),
            raw_text="",
            source="db",
            dwell_seconds=dwell_seconds,
        )
        if matches_alert_filter(removed_product, alert_keywords):
            removed_alert_products.append(removed_product)

    return InventorySyncResult(
        new_alert_products=new_alert_products,
        removed_alert_products=removed_alert_products,
        total_products_found=len(products_by_listing),
        relevant_products_found=relevant_products_found,
    )


def increment_run_counters(session: Session, *, had_matches: bool, match_count: int) -> None:
    total_runs = _get_state_int(session, STATE_TOTAL_RUNS) + 1
    runs_since = _get_state_int(session, STATE_RUNS_SINCE_NOTIFY) + 1
    zero_match_runs = _get_state_int(session, STATE_ZERO_MATCH_RUNS)
    matching_runs = _get_state_int(session, STATE_MATCHING_RUNS)
    matching_products = _get_state_int(session, STATE_MATCHING_PRODUCTS)

    if had_matches:
        matching_runs += 1
        matching_products += max(match_count, 0)
    else:
        zero_match_runs += 1

    _set_state_int(session, STATE_TOTAL_RUNS, total_runs)
    _set_state_int(session, STATE_RUNS_SINCE_NOTIFY, runs_since)
    _set_state_int(session, STATE_ZERO_MATCH_RUNS, zero_match_runs)
    _set_state_int(session, STATE_MATCHING_RUNS, matching_runs)
    _set_state_int(session, STATE_MATCHING_PRODUCTS, matching_products)


def get_heartbeat_counters(session: Session) -> tuple[int, int, int, int]:
    return (
        _get_state_int(session, STATE_RUNS_SINCE_NOTIFY),
        _get_state_int(session, STATE_ZERO_MATCH_RUNS),
        _get_state_int(session, STATE_MATCHING_RUNS),
        _get_state_int(session, STATE_MATCHING_PRODUCTS),
    )


def get_last_successful_notification_at(session: Session) -> datetime | None:
    return _get_state_datetime(session, STATE_LAST_SUCCESS_AT)


def was_startup_notification_sent(session: Session) -> bool:
    return _get_state_bool(session, STATE_STARTUP_SENT, default=False)


def record_successful_notification(session: Session, *, startup_notification_sent: bool | None = None) -> None:
    now = _utc_now()
    _set_state_datetime(session, STATE_LAST_SUCCESS_AT, now)
    if startup_notification_sent is not None:
        _set_state_bool(session, STATE_STARTUP_SENT, startup_notification_sent)
    _set_state_int(session, STATE_RUNS_SINCE_NOTIFY, 0)
    _set_state_int(session, STATE_ZERO_MATCH_RUNS, 0)
    _set_state_int(session, STATE_MATCHING_RUNS, 0)
    _set_state_int(session, STATE_MATCHING_PRODUCTS, 0)


def is_heartbeat_due(
    *,
    heartbeat_enabled: bool,
    heartbeat_interval_hours: float,
    last_successful_notification_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if not heartbeat_enabled:
        return False
    if heartbeat_interval_hours <= 0:
        return True

    reference_now = _utc_now(now)
    if last_successful_notification_at is None:
        return True

    elapsed_seconds = (reference_now - last_successful_notification_at).total_seconds()
    return elapsed_seconds >= heartbeat_interval_hours * 3600


def reset_database_state(session: Session) -> None:
    session.query(ListingObservation).delete()
    session.query(Listing).delete()
    session.query(ProductConfig).delete()
    session.query(PollRun).delete()
    session.query(AppState).delete()
