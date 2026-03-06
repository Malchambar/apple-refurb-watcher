from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    force_notify: bool
    env_file: Path


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_keywords(value: str | None) -> list[str]:
    if not value:
        return ["Mac mini"]
    parts = [part.strip() for part in value.split(",")]
    return [part for part in parts if part] or ["Mac mini"]


def mask_secret(value: str, unmasked_chars: int = 4) -> str:
    if not value:
        return "<empty>"
    if len(value) <= (unmasked_chars * 2):
        return "*" * len(value)
    return f"{value[:unmasked_chars]}...{value[-unmasked_chars:]}"


def load_config() -> AppConfig:
    env_file = PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=env_file)

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
    force_notify = _parse_bool(
        os.getenv("FORCE_NOTIFY"),
        default=_parse_bool(os.getenv("TEST_MODE"), default=False),
    )

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
        force_notify=force_notify,
        env_file=env_file,
    )


def log_config_summary(config: AppConfig) -> None:
    logger.info("Config loaded from .env path: %s exists=%s", config.env_file, config.env_file.exists())
    logger.info(
        "Config summary: keywords=%s enable_pushover=%s enable_imessage=%s force_notify=%s timeout=%s",
        ", ".join(config.match_keywords),
        config.enable_pushover,
        config.enable_imessage,
        config.force_notify,
        config.request_timeout,
    )
    logger.info(
        "Credential presence: pushover_user_key=%s pushover_app_token=%s imessage_recipient=%s",
        mask_secret(config.pushover_user_key),
        mask_secret(config.pushover_app_token),
        mask_secret(config.imessage_recipient),
    )
