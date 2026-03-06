# apple-refurb-watcher

A small macOS-friendly Python watcher for Apple's U.S. refurbished Mac store.

It checks the refurbished Macs page once per run, matches listings by keyword (default: `Mac mini`), and alerts only when **new** matching items appear.

## Purpose

- Watch Apple's refurb Mac listings for specific model keywords.
- Avoid duplicate alerts by storing previously seen matches.
- Run cleanly with macOS `launchd` as a periodic one-shot job.

## Requirements

- macOS
- Python 3.11+

## Setup

1. Clone or copy this project.
2. Create and activate a virtualenv:

```bash
cd apple-refurb-watcher
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Configuration

Copy `.env.example` to `.env` and edit values:

```bash
cp .env.example .env
```

Environment variables:

- `APPLE_REFURB_URL`: Apple page URL to fetch.
- `MATCH_KEYWORDS`: Comma-separated keywords (example: `Mac mini,Mac Studio`).
- `ENABLE_PUSHOVER`: `true`/`false`.
- `PUSHOVER_USER_KEY`: Pushover user key.
- `PUSHOVER_APP_TOKEN`: Pushover app token.
- `ENABLE_IMESSAGE`: `true`/`false`.
- `IMESSAGE_RECIPIENT`: iMessage handle (phone or email used by Messages).
- `STATE_FILE`: Path to JSON state file.
- `LOG_FILE`: Path to log file.
- `REQUEST_TIMEOUT`: HTTP timeout in seconds.

## Manual Test (Single Run)

Run one check manually:

```bash
.venv/bin/python -m src.main
```

Or use the helper script:

```bash
./scripts/run_watcher.sh
```

## launchd (LaunchAgent)

The provided plist is in:

- `launchd/com.martin.apple-refurb-watcher.plist`

Copy it into your user LaunchAgents directory and load it:

```bash
mkdir -p ~/Library/LaunchAgents
cp launchd/com.martin.apple-refurb-watcher.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.martin.apple-refurb-watcher.plist
launchctl enable gui/$(id -u)/com.martin.apple-refurb-watcher
```

### Unload / Reload

Unload:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.martin.apple-refurb-watcher.plist
```

Reload:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.martin.apple-refurb-watcher.plist
launchctl enable gui/$(id -u)/com.martin.apple-refurb-watcher
```

## Troubleshooting

- If iMessage alerts fail, grant Automation permissions in macOS:
  - `System Settings` -> `Privacy & Security` -> `Automation`
  - Allow your terminal (or launchd-invoked process context) to control `Messages`.
- Confirm the recipient can be messaged from the Messages app manually.
- Check `logs/watcher.log` and launchd stdout/stderr logs for errors.
- If `python` is "command not found" with pyenv, use `.venv/bin/python` (or `venv/bin/python`) or `python3` explicitly.

## Notes

- Apple's HTML structure can change over time. If parsing stops finding expected items, update `src/checker.py` selectors and text extraction logic.
