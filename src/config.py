from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    apple_refurb_url: str
    match_keywords: list[str]
    enable_pushover: bool
    pushover_user_key: str
    pushover_app_token: str
    enable_imessage: bool
    imessage_recipient: str
    state_file: Path
    log_file: Path
    request_timeout: float


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_keywords(value: str | None) -> list[str]:
    if not value:
        return ["Mac mini"]
    parts = [part.strip() for part in value.split(",")]
    return [part for part in parts if part] or ["Mac mini"]


def load_config() -> AppConfig:
    load_dotenv()

    apple_refurb_url = os.getenv(
        "APPLE_REFURB_URL", "https://www.apple.com/shop/refurbished/mac"
    )
    match_keywords = _parse_keywords(os.getenv("MATCH_KEYWORDS", "Mac mini"))
    enable_pushover = _parse_bool(os.getenv("ENABLE_PUSHOVER"), default=False)
    pushover_user_key = os.getenv("PUSHOVER_USER_KEY", "").strip()
    pushover_app_token = os.getenv("PUSHOVER_APP_TOKEN", "").strip()
    enable_imessage = _parse_bool(os.getenv("ENABLE_IMESSAGE"), default=False)
    imessage_recipient = os.getenv("IMESSAGE_RECIPIENT", "").strip()

    state_file = Path(os.getenv("STATE_FILE", "data/seen_items.json"))
    log_file = Path(os.getenv("LOG_FILE", "logs/watcher.log"))

    timeout_raw = os.getenv("REQUEST_TIMEOUT", "15").strip()
    try:
        request_timeout = float(timeout_raw)
    except ValueError:
        request_timeout = 15.0

    return AppConfig(
        apple_refurb_url=apple_refurb_url,
        match_keywords=match_keywords,
        enable_pushover=enable_pushover,
        pushover_user_key=pushover_user_key,
        pushover_app_token=pushover_app_token,
        enable_imessage=enable_imessage,
        imessage_recipient=imessage_recipient,
        state_file=state_file,
        log_file=log_file,
        request_timeout=request_timeout,
    )
