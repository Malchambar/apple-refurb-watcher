from __future__ import annotations

import json
import logging
from pathlib import Path

from src.checker import ProductEntry

logger = logging.getLogger(__name__)


def _item_id(item: ProductEntry) -> str:
    return f"{item.title}::{item.url}"


def load_seen_ids(state_file: Path) -> set[str]:
    if not state_file.exists():
        return set()

    try:
        with state_file.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except json.JSONDecodeError:
        logger.warning("State file is invalid JSON. Starting from empty state.")
        return set()
    except OSError as exc:
        logger.exception("Failed reading state file: %s", exc)
        return set()

    ids = payload.get("seen_ids", []) if isinstance(payload, dict) else []
    return {str(item_id) for item_id in ids}


def save_seen_ids(state_file: Path, seen_ids: set[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"seen_ids": sorted(seen_ids)}
    with state_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def diff_new_items(items: list[ProductEntry], seen_ids: set[str]) -> list[ProductEntry]:
    return [item for item in items if _item_id(item) not in seen_ids]


def update_seen_with_items(seen_ids: set[str], items: list[ProductEntry]) -> set[str]:
    updated = set(seen_ids)
    for item in items:
        updated.add(_item_id(item))
    return updated
