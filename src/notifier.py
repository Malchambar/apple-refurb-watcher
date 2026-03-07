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


def _short_label(item: ProductEntry) -> str:
    if item.family:
        return item.family
    lowered = item.title.lower()
    if "mac studio" in lowered:
        return "Mac Studio"
    if "mac mini" in lowered:
        return "Mac mini"
    return item.title.replace("Refurbished", "").strip() or item.title


def _format_config_line(item: ProductEntry) -> str | None:
    parts: list[str] = []
    if item.chip:
        parts.append(item.chip)
    if item.cpu_cores is not None:
        parts.append(f"{item.cpu_cores}C CPU")
    if item.gpu_cores is not None:
        parts.append(f"{item.gpu_cores}C GPU")
    if not parts:
        return None
    return ", ".join(parts)


def _format_specs_line(item: ProductEntry) -> str | None:
    parts = [part for part in [item.memory, item.storage] if part]
    if not parts:
        return None
    return ", ".join(parts)


def _format_duration(seconds: int | None) -> str:
    total = max(int(seconds or 0), 0)
    hours, rem = divmod(total, 3600)
    minutes, _ = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m"
    return "<1m"


def _format_item_message(item: ProductEntry) -> str:
    lines: list[str] = []
    config_line = _format_config_line(item)
    specs_line = _format_specs_line(item)
    if config_line:
        lines.append(config_line)
    if specs_line:
        lines.append(specs_line)
    if item.price:
        lines.append(item.price)
    lines.append(item.url)
    return "\n".join(lines)


def _format_group_message(items: list[ProductEntry], max_items: int = 3) -> str:
    lines = [f"{len(items)} inventory match(es) found"]
    for item in items[:max_items]:
        descriptor = _short_label(item)
        if item.price:
            descriptor = f"{descriptor} ({item.price})"
        lines.append(descriptor)
        config_line = _format_config_line(item)
        specs_line = _format_specs_line(item)
        if config_line:
            lines.append(config_line)
        if specs_line:
            lines.append(specs_line)
        lines.append(item.url)
    if len(items) > max_items:
        lines.append(f"...and {len(items) - max_items} more")
    return "\n".join(lines)


def _format_message(items: list[ProductEntry]) -> str:
    if len(items) == 1:
        return _format_item_message(items[0])
    return _format_group_message(items)


def _format_removed_item_message(item: ProductEntry) -> str:
    lines: list[str] = [f"{_short_label(item)} no longer listed."]
    config_line = _format_config_line(item)
    specs_line = _format_specs_line(item)
    if config_line:
        lines.append(config_line)
    if specs_line:
        lines.append(specs_line)
    if item.price:
        lines.append(item.price)
    return "\n".join(lines)


def _format_removed_group_message(items: list[ProductEntry], max_items: int = 3) -> str:
    lines = [f"{len(items)} previously seen match(es) removed"]
    for item in items[:max_items]:
        descriptor = _short_label(item)
        if item.dwell_seconds is not None:
            descriptor = f"{descriptor} gone after {_format_duration(item.dwell_seconds)}"
        if item.price:
            descriptor = f"{descriptor} ({item.price})"
        lines.append(descriptor)
        config_line = _format_config_line(item)
        specs_line = _format_specs_line(item)
        if config_line:
            lines.append(config_line)
        if specs_line:
            lines.append(specs_line)
    if len(items) > max_items:
        lines.append(f"...and {len(items) - max_items} more")
    return "\n".join(lines)


def _format_removed_message(items: list[ProductEntry]) -> str:
    if len(items) == 1:
        return _format_removed_item_message(items[0])
    return _format_removed_group_message(items)


def send_pushover_alert(config: AppConfig, message: str, *, title: str = "Apple Refurb Alert") -> bool:
    logger.info("send_pushover_alert called. enable_pushover=%s", config.enable_pushover)

    if not config.enable_pushover:
        logger.info("Pushover disabled by config; skipping.")
        return False

    if not config.pushover_user_key or not config.pushover_app_token:
        logger.warning(
            "Pushover enabled but credentials are missing; skipping Pushover notification."
        )
        return False

    try:
        payload = {
            "token": config.pushover_app_token,
            "user": config.pushover_user_key,
            "title": title,
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
        return True
    except Exception as exc:
        logger.exception("Failed to send Pushover notification: %s", exc)
        return False


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


def notify_new_items(config: AppConfig, items: list[ProductEntry], project_root: Path) -> bool:
    if not items:
        logger.info("No new matching items found.")
        return False

    logger.info("New matching items detected: %s", len(items))
    for item in items:
        logger.info(
            "NEW: %s | url=%s | memory=%s | storage=%s | price=%s | source=%s",
            item.title,
            item.url,
            item.memory,
            item.storage,
            item.price,
            item.source,
        )

    message = _format_message(items)
    title = "Apple Refurb Alert"
    if len(items) == 1:
        title = f"{_short_label(items[0])} available"

    pushover_sent = send_pushover_alert(config, message, title=title)
    send_imessage_alert(config, message, project_root=project_root)

    if not config.enable_pushover and not config.enable_imessage:
        logger.info("Notifications disabled; console/log output used as fallback.")
        print(message)
    return pushover_sent


def notify_removed_items(config: AppConfig, items: list[ProductEntry], project_root: Path) -> bool:
    if not items:
        logger.info("No removed matching items found.")
        return False

    logger.info("Removed matching items detected: %s", len(items))
    for item in items:
        logger.info(
            "REMOVED: %s | url=%s | memory=%s | storage=%s | price=%s | source=%s",
            item.title,
            item.url,
            item.memory,
            item.storage,
            item.price,
            item.source,
        )

    message = _format_removed_message(items)
    title = "Inventory Removed"
    if len(items) == 1:
        title = f"{_short_label(items[0])} gone after {_format_duration(items[0].dwell_seconds)}"
    pushover_sent = send_pushover_alert(config, message, title=title)
    send_imessage_alert(config, message, project_root=project_root)

    if not config.enable_pushover and not config.enable_imessage:
        logger.info("Notifications disabled; console/log output used as fallback.")
        print(message)
    return pushover_sent


def send_startup_notification(config: AppConfig) -> bool:
    logger.info("Sending watcher startup notification.")
    sent = send_pushover_alert(
        config,
        "apple-refurb-watcher is running.",
        title="Watcher Started",
    )
    if sent:
        logger.info("Startup notification sent.")
    else:
        logger.info("Startup notification skipped or failed.")
    return sent


def send_heartbeat_notification(
    config: AppConfig,
    *,
    polls_since_last_notification: int,
    zero_match_polls: int,
    matching_polls: int,
    matching_products_seen: int,
) -> bool:
    logger.info("Sending watcher heartbeat notification.")
    message_lines = [
        "apple-refurb-watcher is still running.",
        f"Polls since last message: {polls_since_last_notification}",
        f"Zero-match polls: {zero_match_polls}",
        f"Matching polls: {matching_polls}",
        f"Matching products seen: {matching_products_seen}",
    ]
    sent = send_pushover_alert(
        config,
        "\n".join(message_lines),
        title="Watcher Heartbeat",
    )
    if sent:
        logger.info("Heartbeat notification sent.")
    else:
        logger.info("Heartbeat notification skipped or failed.")
    return sent


def send_test_pushover_notification(config: AppConfig) -> None:
    message = "Apple Refurb Watcher test notification."
    logger.info("Triggering standalone Pushover test notification.")
    send_pushover_alert(config, message, title="Apple Refurb Alert")
