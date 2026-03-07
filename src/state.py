from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.checker import ProductEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchRecord:
    listing_id: str
    config_id: str
    fingerprint: str
    config_fingerprint: str
    price_fingerprint: str
    title: str
    family: str | None
    chip: str | None
    cpu_cores: int | None
    gpu_cores: int | None
    memory: str | None
    storage: str | None
    price: str | None
    url: str
    source: str
    first_seen_at: str
    last_seen_at: str


@dataclass(frozen=True)
class MatchChange:
    change_type: str
    record: MatchRecord


@dataclass(frozen=True)
class RemovedMatch:
    record: MatchRecord
    disappeared_at: str
    dwell_seconds: int


def _timestamp_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _normalize_price(value: str | None) -> str:
    raw = _normalize_text(value)
    return raw.replace(" ", "") if raw else "none"


def _normalize_url(value: str) -> str:
    return value.strip().lower().rstrip("/")


def _short_hash(parts: list[str]) -> str:
    joined = "|".join(parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def _extract_listing_id(url: str, fallback_parts: list[str]) -> str:
    normalized = _normalize_url(url)
    if "/shop/product/" in normalized:
        tail = normalized.split("/shop/product/", 1)[1].split("/", 1)[0].strip()
        if tail:
            return tail
    if normalized:
        return normalized
    return _short_hash(fallback_parts)


def _build_config_id(
    *,
    family_norm: str,
    chip_norm: str,
    cpu_norm: str,
    gpu_norm: str,
    memory_norm: str,
    storage_norm: str,
) -> str:
    parts = [
        family_norm or "unknown-family",
        chip_norm or "unknown-chip",
        cpu_norm or "unknown-cpu",
        gpu_norm or "unknown-gpu",
        memory_norm or "unknown-memory",
        storage_norm or "unknown-storage",
    ]
    return _short_hash(parts)


def build_match_record(item: ProductEntry) -> MatchRecord:
    family_norm = _normalize_text(item.family)
    chip_norm = _normalize_text(item.chip)
    cpu_norm = _normalize_text(str(item.cpu_cores) if item.cpu_cores is not None else "")
    gpu_norm = _normalize_text(str(item.gpu_cores) if item.gpu_cores is not None else "")
    title_norm = _normalize_text(item.title)
    memory_norm = _normalize_text(item.memory)
    storage_norm = _normalize_text(item.storage)
    price_norm = _normalize_price(item.price)
    url_norm = _normalize_url(item.url)

    listing_id = _extract_listing_id(
        item.url,
        fallback_parts=[title_norm, url_norm, price_norm],
    )
    config_id = _build_config_id(
        family_norm=family_norm,
        chip_norm=chip_norm,
        cpu_norm=cpu_norm,
        gpu_norm=gpu_norm,
        memory_norm=memory_norm,
        storage_norm=storage_norm,
    )
    config_fp = _short_hash([config_id, title_norm])
    price_fp = _short_hash([config_fp, price_norm])
    listing_fp = _short_hash([listing_id, config_fp, price_norm, url_norm])

    return MatchRecord(
        listing_id=listing_id,
        config_id=config_id,
        fingerprint=listing_fp,
        config_fingerprint=config_fp,
        price_fingerprint=price_fp,
        title=item.title,
        family=item.family,
        chip=item.chip,
        cpu_cores=item.cpu_cores,
        gpu_cores=item.gpu_cores,
        memory=item.memory,
        storage=item.storage,
        price=item.price,
        url=item.url,
        source=item.source,
        first_seen_at="",
        last_seen_at="",
    )


def build_match_records(items: list[ProductEntry]) -> list[MatchRecord]:
    deduped: dict[str, MatchRecord] = {}
    for item in items:
        record = build_match_record(item)
        deduped[record.listing_id] = record
    return list(deduped.values())


def load_seen_fingerprints(state_file: Path) -> set[str]:
    if not state_file.exists():
        return set()

    try:
        with state_file.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except json.JSONDecodeError:
        logger.warning("State file is invalid JSON. Starting from empty seen fingerprints.")
        return set()
    except OSError as exc:
        logger.exception("Failed reading state file: %s", exc)
        return set()

    if isinstance(payload, dict):
        values = payload.get("seen_fingerprints") or payload.get("seen_ids") or []
    else:
        values = []
    return {str(value) for value in values}


def save_seen_fingerprints(state_file: Path, seen_fingerprints: set[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seen_fingerprints": sorted(seen_fingerprints),
        "updated_at": _timestamp_now(),
    }
    with state_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_current_matches(current_matches_file: Path) -> list[MatchRecord]:
    if not current_matches_file.exists():
        return []

    try:
        with current_matches_file.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except json.JSONDecodeError:
        logger.warning("Current matches file is invalid JSON. Ignoring previous current matches.")
        return []
    except OSError as exc:
        logger.exception("Failed reading current matches file: %s", exc)
        return []

    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    records: list[MatchRecord] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            records.append(
                MatchRecord(
                    listing_id=str(item.get("listing_id") or ""),
                    config_id=str(item.get("config_id") or ""),
                    fingerprint=str(item.get("fingerprint") or ""),
                    config_fingerprint=str(item.get("config_fingerprint") or ""),
                    price_fingerprint=str(item.get("price_fingerprint") or ""),
                    title=str(item.get("title") or ""),
                    family=item.get("family") or None,
                    chip=item.get("chip") or None,
                    cpu_cores=int(item["cpu_cores"]) if item.get("cpu_cores") is not None else None,
                    gpu_cores=int(item["gpu_cores"]) if item.get("gpu_cores") is not None else None,
                    memory=item.get("memory") or None,
                    storage=item.get("storage") or None,
                    price=item.get("price") or None,
                    url=str(item.get("url") or ""),
                    source=str(item.get("source") or ""),
                    first_seen_at=str(item.get("first_seen_at") or ""),
                    last_seen_at=str(item.get("last_seen_at") or ""),
                )
            )
        except Exception:
            continue

    return [
        record
        for record in records
        if record.fingerprint and record.title and record.url and record.listing_id
    ]


def save_current_matches(current_matches_file: Path, records: list[MatchRecord]) -> None:
    current_matches_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _timestamp_now(),
        "count": len(records),
        "items": [asdict(record) for record in sorted(records, key=lambda rec: rec.fingerprint)],
    }
    with current_matches_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _parse_utc_iso(value: str | None) -> datetime | None:
    raw = (value or "").strip()
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


def reconcile_current_match_timestamps(
    current_records: list[MatchRecord],
    previous_records: list[MatchRecord],
    *,
    now: datetime | None = None,
) -> list[MatchRecord]:
    now_utc = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    previous_by_listing = {record.listing_id: record for record in previous_records}
    reconciled: list[MatchRecord] = []

    for record in current_records:
        previous = previous_by_listing.get(record.listing_id)
        first_seen_at = previous.first_seen_at if previous and previous.first_seen_at else now_utc
        reconciled.append(
            MatchRecord(
                listing_id=record.listing_id,
                config_id=record.config_id,
                fingerprint=record.fingerprint,
                config_fingerprint=record.config_fingerprint,
                price_fingerprint=record.price_fingerprint,
                title=record.title,
                family=record.family,
                chip=record.chip,
                cpu_cores=record.cpu_cores,
                gpu_cores=record.gpu_cores,
                memory=record.memory,
                storage=record.storage,
                price=record.price,
                url=record.url,
                source=record.source,
                first_seen_at=first_seen_at,
                last_seen_at=now_utc,
            )
        )

    return reconciled


def load_listing_history(history_file: Path) -> list[dict[str, object]]:
    if not history_file.exists():
        return []
    try:
        with history_file.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def append_listing_history_events(history_file: Path, removed_matches: list[RemovedMatch]) -> None:
    if not removed_matches:
        return

    existing = load_listing_history(history_file)
    for removed in removed_matches:
        existing.append(
            {
                "listing_id": removed.record.listing_id,
                "config_id": removed.record.config_id,
                "title": removed.record.title,
                "url": removed.record.url,
                "price": removed.record.price,
                "family": removed.record.family,
                "chip": removed.record.chip,
                "cpu_cores": removed.record.cpu_cores,
                "gpu_cores": removed.record.gpu_cores,
                "memory": removed.record.memory,
                "storage": removed.record.storage,
                "source": removed.record.source,
                "first_seen_at": removed.record.first_seen_at,
                "last_seen_at": removed.record.last_seen_at,
                "disappeared_at": removed.disappeared_at,
                "dwell_seconds": removed.dwell_seconds,
            }
        )

    history_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _timestamp_now(),
        "event_count": len(existing),
        "events": existing,
    }
    with history_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _runtime_meta_defaults() -> dict[str, object]:
    return {
        "preferred_parser": "",
        "last_run_at": "",
        "last_successful_notification_at": "",
        "startup_notification_sent": False,
        "total_poll_runs": 0,
        "runs_since_last_successful_notification": 0,
        "zero_match_runs_since_last_successful_notification": 0,
        "matching_runs_since_last_successful_notification": 0,
        "matching_products_seen_since_last_successful_notification": 0,
        "removed_alerted_fingerprints": [],
    }


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def load_runtime_meta(meta_file: Path) -> dict[str, object]:
    if not meta_file.exists():
        return _runtime_meta_defaults()

    try:
        with meta_file.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _runtime_meta_defaults()

    if not isinstance(payload, dict):
        return _runtime_meta_defaults()

    defaults = _runtime_meta_defaults()
    return {
        "preferred_parser": str(payload.get("preferred_parser") or defaults["preferred_parser"]),
        "last_run_at": str(payload.get("last_run_at") or defaults["last_run_at"]),
        "last_successful_notification_at": str(
            payload.get("last_successful_notification_at")
            or defaults["last_successful_notification_at"]
        ),
        "startup_notification_sent": _coerce_bool(
            payload.get("startup_notification_sent"),
            default=bool(defaults["startup_notification_sent"]),
        ),
        "total_poll_runs": _coerce_int(payload.get("total_poll_runs")),
        "runs_since_last_successful_notification": _coerce_int(
            payload.get("runs_since_last_successful_notification")
        ),
        "zero_match_runs_since_last_successful_notification": _coerce_int(
            payload.get("zero_match_runs_since_last_successful_notification")
        ),
        "matching_runs_since_last_successful_notification": _coerce_int(
            payload.get("matching_runs_since_last_successful_notification")
        ),
        "matching_products_seen_since_last_successful_notification": _coerce_int(
            payload.get("matching_products_seen_since_last_successful_notification")
        ),
        "removed_alerted_fingerprints": [
            str(item)
            for item in payload.get("removed_alerted_fingerprints", [])
            if isinstance(item, str) and item.strip()
        ]
        if isinstance(payload.get("removed_alerted_fingerprints"), list)
        else [],
    }


def save_runtime_meta(
    meta_file: Path,
    *,
    preferred_parser: str | None = None,
    last_successful_notification_at: str | None = None,
    reset_last_successful_notification: bool = False,
    startup_notification_sent: bool | None = None,
    total_poll_runs: int | None = None,
    runs_since_last_successful_notification: int | None = None,
    zero_match_runs_since_last_successful_notification: int | None = None,
    matching_runs_since_last_successful_notification: int | None = None,
    matching_products_seen_since_last_successful_notification: int | None = None,
    removed_alerted_fingerprints: set[str] | list[str] | None = None,
    reset_since_last_successful_notification: bool = False,
    last_run_at: str | None = None,
) -> None:
    existing = load_runtime_meta(meta_file)
    parser_value = str(existing.get("preferred_parser", ""))
    if preferred_parser is not None:
        parser_value = preferred_parser

    successful_value = str(existing.get("last_successful_notification_at", ""))
    if reset_last_successful_notification:
        successful_value = ""
    elif last_successful_notification_at is not None:
        successful_value = last_successful_notification_at

    startup_sent = _coerce_bool(
        existing.get("startup_notification_sent"),
        default=False,
    )
    if startup_notification_sent is not None:
        startup_sent = startup_notification_sent

    total_runs_value = _coerce_int(existing.get("total_poll_runs"))
    if total_poll_runs is not None:
        total_runs_value = max(total_poll_runs, 0)

    runs_since_value = _coerce_int(
        existing.get("runs_since_last_successful_notification")
    )
    zero_match_since_value = _coerce_int(
        existing.get("zero_match_runs_since_last_successful_notification")
    )
    matching_runs_since_value = _coerce_int(
        existing.get("matching_runs_since_last_successful_notification")
    )
    matching_products_since_value = _coerce_int(
        existing.get("matching_products_seen_since_last_successful_notification")
    )

    if runs_since_last_successful_notification is not None:
        runs_since_value = max(runs_since_last_successful_notification, 0)
    if zero_match_runs_since_last_successful_notification is not None:
        zero_match_since_value = max(zero_match_runs_since_last_successful_notification, 0)
    if matching_runs_since_last_successful_notification is not None:
        matching_runs_since_value = max(matching_runs_since_last_successful_notification, 0)
    if matching_products_seen_since_last_successful_notification is not None:
        matching_products_since_value = max(
            matching_products_seen_since_last_successful_notification,
            0,
        )

    if reset_since_last_successful_notification:
        runs_since_value = 0
        zero_match_since_value = 0
        matching_runs_since_value = 0
        matching_products_since_value = 0

    removed_alerted_value = {
        str(item).strip()
        for item in (existing.get("removed_alerted_fingerprints") or [])
        if str(item).strip()
    }
    if removed_alerted_fingerprints is not None:
        removed_alerted_value = {
            str(item).strip()
            for item in removed_alerted_fingerprints
            if str(item).strip()
        }

    meta_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "preferred_parser": parser_value,
        "last_run_at": last_run_at or _timestamp_now(),
        "last_successful_notification_at": successful_value,
        "startup_notification_sent": startup_sent,
        "total_poll_runs": total_runs_value,
        "runs_since_last_successful_notification": runs_since_value,
        "zero_match_runs_since_last_successful_notification": zero_match_since_value,
        "matching_runs_since_last_successful_notification": matching_runs_since_value,
        "matching_products_seen_since_last_successful_notification": matching_products_since_value,
        "removed_alerted_fingerprints": sorted(removed_alerted_value),
    }
    with meta_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def get_last_successful_notification_at(runtime_meta: dict[str, object]) -> datetime | None:
    raw = (runtime_meta.get("last_successful_notification_at") or "").strip()
    if not raw:
        return None

    candidate = raw
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def update_last_successful_notification_at(
    meta_file: Path,
    *,
    timestamp: datetime | None = None,
    preferred_parser: str | None = None,
) -> str:
    timestamp_utc = (timestamp or datetime.now(UTC)).astimezone(UTC).isoformat()
    save_runtime_meta(
        meta_file,
        preferred_parser=preferred_parser,
        last_successful_notification_at=timestamp_utc,
    )
    return timestamp_utc


def get_removed_alerted_fingerprints(runtime_meta: dict[str, object]) -> set[str]:
    raw = runtime_meta.get("removed_alerted_fingerprints")
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if isinstance(item, str) and item.strip()}


def was_startup_notification_sent(runtime_meta: dict[str, object]) -> bool:
    return _coerce_bool(runtime_meta.get("startup_notification_sent"), default=False)


def increment_run_counters(
    meta_file: Path,
    *,
    had_matches: bool,
    match_count: int,
    preferred_parser: str | None = None,
) -> dict[str, object]:
    existing = load_runtime_meta(meta_file)

    total_runs = _coerce_int(existing.get("total_poll_runs")) + 1
    runs_since = _coerce_int(existing.get("runs_since_last_successful_notification")) + 1
    zero_match_runs = _coerce_int(
        existing.get("zero_match_runs_since_last_successful_notification")
    )
    matching_runs = _coerce_int(
        existing.get("matching_runs_since_last_successful_notification")
    )
    matching_products_seen = _coerce_int(
        existing.get("matching_products_seen_since_last_successful_notification")
    )

    if had_matches:
        matching_runs += 1
        matching_products_seen += max(match_count, 0)
    else:
        zero_match_runs += 1

    save_runtime_meta(
        meta_file,
        preferred_parser=preferred_parser,
        total_poll_runs=total_runs,
        runs_since_last_successful_notification=runs_since,
        zero_match_runs_since_last_successful_notification=zero_match_runs,
        matching_runs_since_last_successful_notification=matching_runs,
        matching_products_seen_since_last_successful_notification=matching_products_seen,
    )
    return load_runtime_meta(meta_file)


def record_successful_notification(
    meta_file: Path,
    *,
    timestamp: datetime | None = None,
    preferred_parser: str | None = None,
    startup_notification_sent: bool | None = None,
    removed_alerted_fingerprints: set[str] | list[str] | None = None,
) -> str:
    timestamp_utc = (timestamp or datetime.now(UTC)).astimezone(UTC).isoformat()
    save_runtime_meta(
        meta_file,
        preferred_parser=preferred_parser,
        last_successful_notification_at=timestamp_utc,
        startup_notification_sent=startup_notification_sent,
        removed_alerted_fingerprints=removed_alerted_fingerprints,
        reset_since_last_successful_notification=True,
    )
    return timestamp_utc


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

    reference_now = now or datetime.now(UTC)
    if last_successful_notification_at is None:
        return True

    elapsed_seconds = (reference_now - last_successful_notification_at).total_seconds()
    threshold_seconds = heartbeat_interval_hours * 3600
    return elapsed_seconds >= threshold_seconds


def archive_state(state_file: Path, archive_dir: Path | None = None) -> Path | None:
    if not state_file.exists():
        return None

    destination_dir = archive_dir or (state_file.parent / "archive")
    destination_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = destination_dir / f"seen_items_{timestamp}.json"
    archive_path.write_text(state_file.read_text(encoding="utf-8"), encoding="utf-8")
    return archive_path


def reset_state(state_file: Path, archive_dir: Path | None = None) -> Path | None:
    archived = archive_state(state_file, archive_dir=archive_dir)
    save_seen_fingerprints(state_file, set())
    return archived


def detect_match_changes(
    current_records: list[MatchRecord],
    previous_records: list[MatchRecord],
    seen_fingerprints: set[str],
) -> list[MatchChange]:
    previous_by_config: dict[str, list[MatchRecord]] = {}
    for record in previous_records:
        previous_by_config.setdefault(record.config_id, []).append(record)

    changes: list[MatchChange] = []

    for record in current_records:
        if record.fingerprint in seen_fingerprints:
            continue

        previous_same_config = previous_by_config.get(record.config_id, [])
        if not previous_same_config:
            change_type = "new_config"
        else:
            previous_prices = {item.price_fingerprint for item in previous_same_config}
            previous_listings = {item.listing_id for item in previous_same_config}

            if record.price_fingerprint not in previous_prices:
                change_type = "price_change"
            elif record.listing_id not in previous_listings:
                change_type = "relisted"
            else:
                change_type = "new_listing"

        changes.append(MatchChange(change_type=change_type, record=record))

    return changes


def detect_removed_matches(
    current_records: list[MatchRecord],
    previous_records: list[MatchRecord],
    *,
    now: datetime | None = None,
) -> list[RemovedMatch]:
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    current_listing_ids = {record.listing_id for record in current_records}
    removed: list[RemovedMatch] = []

    for previous in previous_records:
        if not previous.listing_id or previous.listing_id in current_listing_ids:
            continue

        first_seen = _parse_utc_iso(previous.first_seen_at) or now_utc
        last_seen = _parse_utc_iso(previous.last_seen_at) or first_seen
        dwell_seconds = max(0, int((last_seen - first_seen).total_seconds()))
        removed.append(
            RemovedMatch(
                record=previous,
                disappeared_at=now_utc.isoformat(),
                dwell_seconds=dwell_seconds,
            )
        )

    return sorted(removed, key=lambda item: item.record.listing_id)
