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
    fingerprint: str
    config_fingerprint: str
    price_fingerprint: str
    title: str
    memory: str | None
    storage: str | None
    price: str | None
    url: str
    source: str


@dataclass(frozen=True)
class MatchChange:
    change_type: str
    record: MatchRecord


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


def build_match_record(item: ProductEntry) -> MatchRecord:
    title_norm = _normalize_text(item.title)
    memory_norm = _normalize_text(item.memory)
    storage_norm = _normalize_text(item.storage)
    price_norm = _normalize_price(item.price)
    url_norm = _normalize_url(item.url)

    config_fp = _short_hash([title_norm, memory_norm, storage_norm])
    price_fp = _short_hash([config_fp, price_norm])
    listing_fp = _short_hash([config_fp, price_norm, url_norm])

    return MatchRecord(
        fingerprint=listing_fp,
        config_fingerprint=config_fp,
        price_fingerprint=price_fp,
        title=item.title,
        memory=item.memory,
        storage=item.storage,
        price=item.price,
        url=item.url,
        source=item.source,
    )


def build_match_records(items: list[ProductEntry]) -> list[MatchRecord]:
    deduped: dict[str, MatchRecord] = {}
    for item in items:
        record = build_match_record(item)
        deduped[record.fingerprint] = record
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
                    fingerprint=str(item.get("fingerprint") or ""),
                    config_fingerprint=str(item.get("config_fingerprint") or ""),
                    price_fingerprint=str(item.get("price_fingerprint") or ""),
                    title=str(item.get("title") or ""),
                    memory=item.get("memory") or None,
                    storage=item.get("storage") or None,
                    price=item.get("price") or None,
                    url=str(item.get("url") or ""),
                    source=str(item.get("source") or ""),
                )
            )
        except Exception:
            continue

    return [record for record in records if record.fingerprint and record.title and record.url]


def save_current_matches(current_matches_file: Path, records: list[MatchRecord]) -> None:
    current_matches_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _timestamp_now(),
        "count": len(records),
        "items": [asdict(record) for record in sorted(records, key=lambda rec: rec.fingerprint)],
    }
    with current_matches_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_runtime_meta(meta_file: Path) -> dict[str, str]:
    if not meta_file.exists():
        return {}

    try:
        with meta_file.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return {
        "preferred_parser": str(payload.get("preferred_parser") or ""),
        "last_run_at": str(payload.get("last_run_at") or ""),
    }


def save_runtime_meta(meta_file: Path, preferred_parser: str | None) -> None:
    meta_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "preferred_parser": preferred_parser or "",
        "last_run_at": _timestamp_now(),
    }
    with meta_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


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
        previous_by_config.setdefault(record.config_fingerprint, []).append(record)

    changes: list[MatchChange] = []

    for record in current_records:
        if record.fingerprint in seen_fingerprints:
            continue

        previous_same_config = previous_by_config.get(record.config_fingerprint, [])
        if not previous_same_config:
            change_type = "new_config"
        else:
            previous_prices = {item.price_fingerprint for item in previous_same_config}
            previous_urls = {_normalize_url(item.url) for item in previous_same_config}
            current_url = _normalize_url(record.url)

            if record.price_fingerprint not in previous_prices:
                change_type = "price_change"
            elif current_url not in previous_urls:
                change_type = "relisted"
            else:
                change_type = "new_listing"

        changes.append(MatchChange(change_type=change_type, record=record))

    return changes
