# apple-refurb-watcher

A small macOS-friendly Python watcher for Apple's U.S. refurbished Mac store.

It checks the refurbished Macs page once per run, keeps only relevant structured products (`Mac mini`, optional `Mac Studio`), and alerts only on meaningful new changes.

## Purpose

- Watch Apple's refurb inventory for relevant Mac mini (and optionally Mac Studio) listings.
- Avoid duplicate alerts with compact product fingerprints.
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
- `STATE_FILE`: Path to seen fingerprint file (default: `data/seen_items.json`).
- `LOG_FILE`: Path to log file.
- `REQUEST_TIMEOUT`: HTTP timeout in seconds.

## Parsing Strategy (Structured First)

The checker keeps the structured pipeline and uses parser preference caching:

1. Preferred parser from `data/runtime_meta.json` (if available) is attempted first.
2. Falls back through the standard pipeline:
   - `json_feed`
   - `json_ld`
   - `html_cards`

After parsing structured products, the watcher immediately filters to relevant models:

- Always `Mac mini`
- `Mac Studio` only if your configured keywords include studio

## Fingerprint and State Strategy

For each relevant product, the watcher builds compact hashes:

- `config_fingerprint`: normalized `title + memory + storage`
- `price_fingerprint`: `config_fingerprint + price`
- `fingerprint`: `config_fingerprint + price + url`

This allows distinguishing:

- new configuration (`new_config`)
- price changes on an existing configuration (`price_change`)
- relisted entries with a new URL (`relisted`)

State files:

- `data/seen_items.json`: already-alerted listing fingerprints
- `data/current_matches.json`: exact relevant matches from the latest run
- `data/runtime_meta.json`: parser preference and last run timestamp
- `data/archive/seen_items_YYYYmmdd_HHMMSS.json`: archived seen state on reset

## Manual Test (Single Run)

Normal run:

```bash
python3 -m src.main
```

Dry run (no notifications, no state writes):

```bash
python3 -m src.main --dry-run
```

Reset state (archive + clear, then exit):

```bash
python3 -m src.main --reset-state
```

Or use the helper script:

```bash
./scripts/run_watcher.sh
```

## launchd (LaunchAgent)

The repo tracks only a template plist:

- `launchd/apple-refurb-watcher.plist.template`

Generate and install your user-specific LaunchAgent plist:

```bash
./scripts/install_launch_agent.sh
```

The installer generates:

- `~/Library/LaunchAgents/com.<your-username>.apple-refurb-watcher.plist`

and loads it with label:

- `com.<your-username>.apple-refurb-watcher`

Reload after plist updates:

```bash
LABEL="com.$(id -un).apple-refurb-watcher"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
launchctl unload "$PLIST"
./scripts/install_launch_agent.sh
```

## Notes

- Apple page structure and feed behavior may change over time. If JSON feed discovery or selectors stop yielding products, update `src/checker.py` parser heuristics.
- Runtime directories (`logs/`, `data/`, `data/archive/`) are auto-created at startup.
- Runtime logs/state are intentionally gitignored; `.gitkeep` files preserve directory structure only.
