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
    heartbeat_enabled: bool
    heartbeat_interval_hours: float
    startup_notify_enabled: bool
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


def load_config() -> AppConfig:
    env_file = PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=env_file)

    apple_refurb_url = os.getenv("APPLE_REFURB_URL", "https://www.apple.com/shop/refurbished/mac")
    match_keywords = _parse_keywords(os.getenv("MATCH_KEYWORDS", "Mac mini"))
    enable_pushover = _parse_bool(os.getenv("ENABLE_PUSHOVER"), default=False)
    pushover_user_key = os.getenv("PUSHOVER_USER_KEY", "").strip()
    pushover_app_token = os.getenv("PUSHOVER_APP_TOKEN", "").strip()
    enable_imessage = _parse_bool(os.getenv("ENABLE_IMESSAGE"), default=False)
    imessage_recipient = os.getenv("IMESSAGE_RECIPIENT", "").strip()
    heartbeat_enabled = _parse_bool(os.getenv("HEARTBEAT_ENABLED"), default=False)
    startup_notify_enabled = _parse_bool(
        os.getenv("STARTUP_NOTIFY_ENABLED"),
        default=True,
    )

    heartbeat_interval_raw = os.getenv("HEARTBEAT_INTERVAL_HOURS", "6").strip()
    try:
        heartbeat_interval_hours = float(heartbeat_interval_raw)
        if heartbeat_interval_hours <= 0:
            heartbeat_interval_hours = 6.0
    except ValueError:
        heartbeat_interval_hours = 6.0

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
        heartbeat_enabled=heartbeat_enabled,
        heartbeat_interval_hours=heartbeat_interval_hours,
        startup_notify_enabled=startup_notify_enabled,
        state_file=state_file,
        log_file=log_file,
        request_timeout=request_timeout,
        force_notify=force_notify,
        env_file=env_file,
    )


def log_config_summary(config: AppConfig) -> None:
    logger.info(
        "Config loaded from .env path: %s exists=%s", config.env_file, config.env_file.exists()
    )
    summary_template = (
        "Config summary: keywords=%s enable_pushover=%s enable_imessage=%s "
        "force_notify=%s startup_notify_enabled=%s heartbeat_enabled=%s "
        "heartbeat_interval_hours=%s timeout=%s"
    )
    logger.info(
        summary_template,
        ", ".join(config.match_keywords),
        config.enable_pushover,
        config.enable_imessage,
        config.force_notify,
        config.startup_notify_enabled,
        config.heartbeat_enabled,
        config.heartbeat_interval_hours,
        config.request_timeout,
    )
    credential_template = (
        "Credential presence: pushover_user_key_present=%s "
        "pushover_app_token_present=%s imessage_recipient_present=%s"
    )
    logger.info(
        credential_template,
        bool(config.pushover_user_key),
        bool(config.pushover_app_token),
        bool(config.imessage_recipient),
    )
