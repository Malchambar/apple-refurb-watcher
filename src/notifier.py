from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import requests

from src.checker import ProductEntry
from src.config import AppConfig

logger = logging.getLogger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def _truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}...<truncated>"


def _format_message(items: list[ProductEntry]) -> str:
    lines = ["New Apple Refurb Match(es):"]
    for item in items:
        lines.append(f"- {item.title}")
        lines.append(f"  {item.url}")
    return "\n".join(lines)


def send_pushover_alert(config: AppConfig, message: str) -> None:
    logger.info("send_pushover_alert called. enable_pushover=%s", config.enable_pushover)

    if not config.enable_pushover:
        logger.info("Pushover disabled by config; skipping.")
        return

    if not config.pushover_user_key or not config.pushover_app_token:
        logger.warning(
            "Pushover enabled but credentials are missing; skipping Pushover notification."
        )
        return

    try:
        payload = {
            "token": config.pushover_app_token,
            "user": config.pushover_user_key,
            "title": "Apple Refurb Watcher",
            "message": message,
        }
        logger.info("Attempting Pushover HTTP POST to %s", PUSHOVER_URL)
        response = requests.post(
            PUSHOVER_URL,
            data=payload,
            timeout=config.request_timeout,
        )
        logger.info(
            "Pushover response status=%s body=%s",
            response.status_code,
            _truncate(response.text.strip()),
        )
        response.raise_for_status()
        logger.info("Pushover notification sent.")
    except Exception as exc:
        logger.exception("Failed to send Pushover notification: %s", exc)


def send_imessage_alert(config: AppConfig, message: str, project_root: Path) -> None:
    if not config.enable_imessage:
        return

    if not config.imessage_recipient:
        logger.warning("iMessage enabled but IMESSAGE_RECIPIENT is missing.")
        return

    script_path = project_root / "scripts" / "send_imessage.scpt"
    if not script_path.exists():
        logger.error("iMessage AppleScript not found at %s", script_path)
        return

    try:
        subprocess.run(
            [
                "osascript",
                str(script_path),
                config.imessage_recipient,
                message,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("iMessage notification sent.")
    except subprocess.CalledProcessError as exc:
        logger.exception(
            "Failed to send iMessage notification. stderr=%s", exc.stderr.strip()
        )


def notify_new_items(config: AppConfig, items: list[ProductEntry], project_root: Path) -> None:
    if not items:
        logger.info("No new matching items found.")
        return

    message = _format_message(items)

    logger.info("New matching items detected: %s", len(items))
    for item in items:
        logger.info("NEW: %s | %s", item.title, item.url)

    send_pushover_alert(config, message)
    send_imessage_alert(config, message, project_root=project_root)

    if not config.enable_pushover and not config.enable_imessage:
        logger.info("Notifications disabled; console/log output used as fallback.")
        print(message)


def send_test_pushover_notification(config: AppConfig) -> None:
    message = "Apple Refurb Watcher test notification."
    logger.info("Triggering standalone Pushover test notification.")
    send_pushover_alert(config, message)
