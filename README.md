# apple-refurb-watcher

`apple-refurb-watcher` polls Apple’s refurbished Mac category, stores all observed Mac inventory in SQLite via SQLAlchemy, and sends notifications only for configured alert targets (for example `Mac mini`, `Mac Studio`).

## What Changed On This Branch

- Data storage is now DB-first (`SQLite + SQLAlchemy`), not JSON-first runtime state.
- Ingestion and alerting are now explicitly separated:
  - collect/store all refurb Mac inventory
  - alert only on configured keywords/families
- Listing lifecycle is tracked in DB (`appeared`, `still available`, `disappeared`).
- Startup/heartbeat/product alerts still exist conceptually, now backed by DB app-state.

If you want the original lightweight JSON MVP baseline, use the `v1-json-mvp` tag on `main`.

## Architecture

- `src/checker.py`: fetch + structured parsing (`json_ld -> html_cards -> json_feed` with preferred parser cache).
- `src/models.py`: SQLAlchemy ORM schema.
- `src/db.py`: engine/session/init helpers.
- `src/state.py`: DB-backed inventory sync, run metadata, heartbeat/startup state.
- `src/notifier.py`: Pushover/iMessage notifications.
- `src/main.py`: orchestration and CLI.

## Schema Overview

- `PollRun`: one watcher cycle (`started_at`, `finished_at`, parser, counts, status, error).
- `ProductConfig`: normalized configuration grouping (`config_key`, family/chip/cpu/gpu/memory/storage).
- `Listing`: listing lifecycle (`listing_key`, first/last seen, disappeared_at, availability flag).
- `ListingObservation`: per-run listing observation snapshots.
- `AppState`: key/value operational metadata (preferred parser, startup flag, heartbeat counters, last successful notification timestamp).

## Identity Model

- `listing_key`: specific listing instance identity (Apple product identifier/URL-derived fallback).
- `config_key`: normalized configuration identity for grouping/analytics.

This supports “track each listing lifecycle” and “aggregate by machine configuration” at the same time.

## Notifications

- Availability alerts for relevant targets only (for example `Mac Studio available`).
- Disappearance alerts for relevant targets only (for example `Mac Studio gone after 3h 12m`).
- Startup notification (`Watcher Started`) on first fresh lifecycle run.
- Heartbeat notification on configured interval when no successful real notification happened recently.
- Any successful availability/disappearance alert counts as activity and suppresses heartbeat.

## Configuration (`.env`)

- `APPLE_REFURB_URL`: category URL to poll.
- `MATCH_KEYWORDS`: alert filter only (ingestion still stores all parsed products).
- `DATABASE_URL`: SQLite URL (default in example: `sqlite:///data/apple_refurb_watcher.db`).
- `ENABLE_PUSHOVER`, `PUSHOVER_USER_KEY`, `PUSHOVER_APP_TOKEN`: Pushover settings.
- `ENABLE_IMESSAGE`, `IMESSAGE_RECIPIENT`: optional iMessage channel.
- `STARTUP_NOTIFY_ENABLED`: startup notification toggle.
- `HEARTBEAT_ENABLED`, `HEARTBEAT_INTERVAL_HOURS`: heartbeat behavior.
- `LOG_FILE`, `REQUEST_TIMEOUT`, `FORCE_NOTIFY`.
- `TEST_MODE`: legacy alias used as a fallback default for `FORCE_NOTIFY`.

## Quick Start

```bash
git clone <your-repo-url>
cd apple-refurb-watcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.main
```

## Run Commands

- Normal run:
```bash
python -m src.main
```

- Dry run (parse only, no DB writes, no notifications):
```bash
python -m src.main --dry-run
```

- Reset DB-backed state:
```bash
python -m src.main --reset-state
```

- Send standalone notifier test:
```bash
python -m src.main --test-notifier
```

## launchd

Existing launchd template/installer flow is unchanged:

```bash
./scripts/install_launch_agent.sh
```

Important operational notes:

- This watcher is a scheduled short-lived process, not a long-running daemon.
- `launchd` invokes `scripts/run_watcher.sh` each interval (`RunAtLoad` + `StartInterval` in the plist).
- `.env` changes are picked up on the next scheduled run because each run starts a new Python process.
- If you are switching branches while the LaunchAgent is enabled, unload first to avoid code/state mismatches:

```bash
LABEL="com.$(id -un).apple-refurb-watcher"
launchctl bootout "gui/$(id -u)/${LABEL}" || true
```

After switching branches, reinstall/reload:

```bash
./scripts/install_launch_agent.sh
```

## Database Inspection

Use `sqlite3` directly:

```bash
sqlite3 data/apple_refurb_watcher.db ".tables"
sqlite3 data/apple_refurb_watcher.db "select id, started_at, parser_source, total_products_found, relevant_products_found, status from arw_poll_runs order by id desc limit 10;"
sqlite3 data/apple_refurb_watcher.db "select listing_key, title, last_known_available, first_seen_at, last_seen_at, disappeared_at from arw_listings order by updated_at desc limit 20;"
sqlite3 data/apple_refurb_watcher.db "select config_key, family, chip, cpu_cores, gpu_cores, memory_gb, storage_gb from arw_product_configs limit 20;"
```

## Testing Guide

1. Database initialization
```bash
rm -f data/apple_refurb_watcher.db
python -m src.main --dry-run
sqlite3 data/apple_refurb_watcher.db ".tables"
```
Expected: DB file exists, tables exist.

2. Normal run stores products
```bash
python -m src.main
sqlite3 data/apple_refurb_watcher.db "select id, total_products_found, relevant_products_found, status from arw_poll_runs order by id desc limit 1;"
sqlite3 data/apple_refurb_watcher.db "select count(*) from arw_listings;"
sqlite3 data/apple_refurb_watcher.db "select count(*) from arw_listing_observations;"
```
Expected: latest poll run is `success`, listings/observations populated.

3. Alert filtering still works while storing all
```bash
# edit .env -> MATCH_KEYWORDS=Mac mini
python -m src.main
sqlite3 data/apple_refurb_watcher.db "select total_products_found, relevant_products_found from arw_poll_runs order by id desc limit 1;"
```
Expected: `total_products_found` tracks all parsed inventory; `relevant_products_found` tracks keyword-filtered subset used for alert decisions.

4. Disappearance detection still works
```bash
# seed one available listing as previously seen, then run
sqlite3 data/apple_refurb_watcher.db "update arw_listings set last_known_available=1, first_seen_at='2026-03-01T00:00:00+00:00', last_seen_at='2026-03-01T02:30:00+00:00' where id=(select id from arw_listings limit 1);"
python -m src.main
sqlite3 data/apple_refurb_watcher.db "select listing_key, last_known_available, disappeared_at from arw_listings where last_known_available=0 limit 5;"
```
Expected: listings absent from current poll transition to unavailable with `disappeared_at` set; relevant ones trigger removal alerts once per disappearance event.

5. Startup / heartbeat still works
```bash
# first run after reset
python -m src.main --reset-state
python -m src.main
# then run again quickly
python -m src.main
```
Expected: startup alert on fresh lifecycle (if enabled), then heartbeat behavior based on interval + successful notifications.

6. Verify heartbeat suppression after real alert
```bash
python -m src.main
sqlite3 data/apple_refurb_watcher.db "select key, value from arw_app_state where key in ('last_successful_notification_at','runs_since_last_successful_notification');"
```
Expected: successful availability/disappearance alert updates `last_successful_notification_at` and resets `runs_since_last_successful_notification`.

## Notes

- Timestamps are UTC.
- `create_all()` is used for schema creation in this branch (no migration framework yet).
- Old JSON runtime files are no longer the primary state system; SQLite is now the source of truth.
- `MATCH_KEYWORDS` controls alerting only; ingestion still stores all parsed inventory from `APPLE_REFURB_URL`.
