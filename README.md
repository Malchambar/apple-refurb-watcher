# apple-refurb-watcher

`apple-refurb-watcher` monitors Apple's refurbished Mac store, parses structured product listings, and sends notifications when relevant matches appear or disappear (for example, `Mac mini`, optionally `Mac Studio`). It is also set up as a reusable starter template for other scheduled watcher/scraper projects: parser pipeline, state handling, notifications, logging, and macOS `launchd` automation are already wired.

## Features

- Structured extraction pipeline with parser fallback (`json_ld` -> `html_cards` -> `json_feed`) and preferred-parser caching.
- Targeted parsing path first (structured product scripts and product-card links) before broader discovery fallbacks.
- Relevant model filtering for `Mac mini` and optional `Mac Studio`.
- Fingerprint-based state tracking to avoid duplicate alerts.
- `current_matches` snapshots for active relevant listings (with first/last-seen timestamps).
- Listing/config identity model (`listing_id` vs `config_id`) for lifecycle tracking and future trend analysis.
- `listing_history.json` events for disappeared listings with dwell-time data.
- Pushover notifications (plus optional iMessage path already present in code).
- Removed-inventory notifications when previously relevant products disappear from the current snapshot.
- Startup notification support (`Watcher Started`) for first successful run in a fresh runtime lifecycle.
- Optional heartbeat notifications when no successful Pushover alert has been sent recently.
- Heartbeat status summary counters (polls/zero-match/matching activity since last successful notification).
- Manual state reset with archive support.
- macOS `launchd` scheduling via tracked plist template + install script.
- Runtime directory auto-creation at startup (`logs/`, `data/`, `data/archive/`).
- Git-friendly runtime handling (`.gitignore` + `.gitkeep` placeholders).

## Repository Structure

- `src/`: Core app logic.
  - `checker.py`: Fetching + structured parsing pipeline.
  - `state.py`: fingerprints, seen/current/runtime state, reset/archive logic.
  - `notifier.py`: Pushover/iMessage notifications.
  - `main.py`: CLI entrypoint and run orchestration.
- `scripts/`: Utility scripts.
  - `run_watcher.sh`: Convenience runner.
  - `install_launch_agent.sh`: Installs per-user LaunchAgent plist from template.
- `launchd/`: LaunchAgent template tracked in git.
  - `apple-refurb-watcher.plist.template`
- `data/`: Runtime state (ignored in git).
  - tracked placeholder: `data/archive/.gitkeep`
- runtime files: `seen_items.json`, `current_matches.json`, `listing_history.json`, `runtime_meta.json` (includes parser preference and last successful notification timestamp), archived reset files
  - `runtime_meta.json` also tracks startup-notify flag and lightweight poll counters used in heartbeat summaries
- `logs/`: Runtime logs (ignored in git).
  - tracked placeholder: `logs/.gitkeep`
- `.env.example`: Example local configuration.
- `.gitignore`: Ignore rules for runtime artifacts and local launchd files.
- `README.md`: This guide.

## Requirements

- Python 3.11+
- macOS for `launchd` automation (manual runs work anywhere Python dependencies work)
- Dependencies in `requirements.txt` (runtime: `beautifulsoup4`, `python-dotenv`, `requests`; tooling: `ruff`, `black`)
- Optional Pushover account/app if you want push alerts

## Code Style and Linting

This project uses:

- Ruff for linting (including import sorting rules)
- Black for formatting

Run checks:

```bash
ruff check .
black .
```

Run autofix formatting/lint cleanup:

```bash
ruff check . --fix
black .
```

## Quick Start

1. Clone the repo.
2. Create a virtual environment.
3. Install dependencies.
4. Create local `.env`.
5. Run once manually.

```bash
git clone <your-repo-url>
cd apple-refurb-watcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.main
```

## Using The JSON MVP Tag

If you want the original lightweight JSON-based watcher (before the SQLAlchemy/SQLite refactor), use the `v1-json-mvp` tag.

- Use `main` if you want the current/default project version.
- Use `v1-json-mvp` if you want the simpler baseline MVP.

Clone directly at the tag:

```bash
git clone --branch v1-json-mvp --depth 1 https://github.com/Malchambar/apple-refurb-watcher.git
```

Or switch an existing clone to the tag:

```bash
git fetch --tags
git checkout v1-json-mvp
```

Create your own working branch from the tag:

```bash
git checkout -b my-json-mvp-work v1-json-mvp
```

## Environment Configuration

All runtime config comes from `.env`.

- `APPLE_REFURB_URL`: Source page URL to fetch.
- `MATCH_KEYWORDS`: Comma-separated keywords; also controls whether `Mac Studio` is included.
- `ENABLE_PUSHOVER`: `true/false` toggle for Pushover.
- `PUSHOVER_USER_KEY`: Pushover user key.
- `PUSHOVER_APP_TOKEN`: Pushover app token.
- `ENABLE_IMESSAGE`: `true/false` toggle for iMessage notifications (optional).
- `IMESSAGE_RECIPIENT`: iMessage target (email/phone tied to Messages) when iMessage is enabled.
- `HEARTBEAT_ENABLED`: `true/false` toggle for heartbeat notifications (default `false`).
- `HEARTBEAT_INTERVAL_HOURS`: Heartbeat interval in hours (default `6`).
- `STARTUP_NOTIFY_ENABLED`: `true/false` toggle for startup notification on fresh runtime lifecycle (default `true`).
- `STATE_FILE`: Path for seen fingerprint state file (default `data/seen_items.json`).
- `LOG_FILE`: Path for watcher log file (default `logs/watcher.log`).
- `REQUEST_TIMEOUT`: HTTP timeout in seconds.
- `FORCE_NOTIFY`: If `true`, can send notifications even when all current matches are already seen.
- `TEST_MODE`: Backward-compat alias influencing default `FORCE_NOTIFY` behavior.

## Running Manually

Normal run:

```bash
python -m src.main
```

Dry run (parsing + matching only; no notifications or state writes):

```bash
python -m src.main --dry-run
```

Reset state (archive seen state, clear seen/current/runtime files, then exit):

```bash
python -m src.main --reset-state
```

Standalone notifier test:

```bash
python -m src.main --test-notifier
```

## Notifications

Pushover is the primary alert path in this project.

- Enable with `ENABLE_PUSHOVER=true`.
- Provide `PUSHOVER_USER_KEY` and `PUSHOVER_APP_TOKEN`.
- Availability alerts use concise titles like `Mac Studio available` and include parsed config details (chip/CPU/GPU, memory/storage), price, and URL.
- Removed alerts include dwell time in the title (for example `Mac Studio gone after 3h 12m`) plus key config/price details.
- Startup notification uses title `Watcher Started` and message `apple-refurb-watcher is running.`.
- Startup notification is sent once for a fresh runtime lifecycle (for example, after reset/reinstall/runtime metadata reset), not every poll.
- Heartbeat uses title `Watcher Heartbeat` with a compact status summary:
  - polls since last successful notification
  - zero-match polls since last successful notification
  - matching polls since last successful notification
  - matching products seen since last successful notification
- Heartbeat is sent only when:
  - `HEARTBEAT_ENABLED=true`
  - no successful Pushover notification (product alert, startup alert, or prior heartbeat) has occurred within `HEARTBEAT_INTERVAL_HOURS`
- Successful real inventory notifications (new items or removed items) and startup notifications count as activity and suppress heartbeat until the interval elapses.

Quick credential sanity check with `curl`:

```bash
curl -sS https://api.pushover.net/1/messages.json \
  -d "token=<PUSHOVER_APP_TOKEN>" \
  -d "user=<PUSHOVER_USER_KEY>" \
  -d "title=Watcher Test" \
  -d "message=Credential check"
```

Do not commit real keys.

## macOS launchd Setup

This repo tracks only a template plist:

- `launchd/apple-refurb-watcher.plist.template`

Install a real user-specific LaunchAgent plist:

```bash
./scripts/install_launch_agent.sh
```

What the installer does:

- Builds label: `com.$(id -un).apple-refurb-watcher`
- Replaces template placeholders (`__LABEL__`, `__PROJECT_DIR__`)
- Writes plist to `~/Library/LaunchAgents/<label>.plist`
- Unloads existing matching agent (if present)
- Loads the new plist

Useful commands:

```bash
LABEL="com.$(id -un).apple-refurb-watcher"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl list | grep apple-refurb
launchctl print gui/$(id -u)/${LABEL}
cat "$PLIST"
```

Reload after template/script updates:

```bash
launchctl unload "$PLIST"
./scripts/install_launch_agent.sh
```

Unload/disable:

```bash
launchctl unload "$PLIST"
```

## Runtime Files and Git Behavior

- Runtime logs and JSON state files are intentionally gitignored.
- `.gitkeep` files keep empty directory structure in git (`logs/.gitkeep`, `data/archive/.gitkeep`).
- Local generated launchd plists (`launchd/*.plist` and installed plist under `~/Library/LaunchAgents`) are not tracked.

This keeps commits clean and makes the repo portable across machines/users.

## How Matching Works

1. Fetch Apple refurb page HTML.
2. Parse targeted structured product data first (`json_ld`, then product cards); fall back to discovered JSON feed only if needed.
3. Normalize product fields and identities:
   - `listing_id`: specific listing instance identity
   - `config_id`: grouped machine configuration identity for trend analysis
4. Filter to relevant models (`Mac mini`, optional `Mac Studio`).
5. Build compact fingerprints and reconcile first/last seen timestamps.
6. Compare current relevant snapshot vs previous relevant snapshot to detect:
   - newly available relevant products
   - removed relevant products
7. Send inventory alerts for new/removed changes.
8. For removals, compute dwell time from `first_seen_at`/`last_seen_at` and append event rows to `listing_history.json`.
9. Save updated state snapshots and runtime metadata.
10. If no real inventory alert succeeded, startup/heartbeat logic applies based on last successful notification timestamp.

## Adapting This Repo for Other Watcher/Scraper Projects

You can keep most of the scaffolding and swap target-specific logic.

- Replace parser logic in `src/checker.py` for your new source.
- Update matching rules/keywords in `.env` and checker filters.
- Reuse `src/state.py` fingerprint + change detection approach.
- Reuse notifications in `src/notifier.py`.
- Reuse scheduling with `scripts/install_launch_agent.sh` + plist template.

Good template use cases:

- Another Apple inventory watcher.
- Real-estate listing/article watcher.
- Competitor price monitor.
- Product restock watcher.

## Troubleshooting

- Wrong Python interpreter / stale venv:
  - Recreate venv and reinstall requirements.
  - Verify `python -m src.main` uses the intended interpreter.
- `launchd` path issues:
  - Rerun `./scripts/install_launch_agent.sh` after moving repo path.
- Stale installed LaunchAgent plist:
  - `launchctl unload "$PLIST"` then rerun installer.
- `.gitignore` vs `.gitkeep` confusion:
  - `.gitkeep` preserves folders; runtime files in those folders stay ignored.
- Pushover works with `curl` but not in app:
  - Check `.env` values, `ENABLE_PUSHOVER=true`, and logs for missing credentials.
- No notifications received:
  - There may be no new matching products; run with `--dry-run` and inspect logs/state files.
- Removed notifications not appearing:
  - Confirm `current_matches.json` previously contained the relevant item and now it does not.
  - Check logs for `Removed detected` entries and notification credential issues.
- Dwell duration looks short:
  - Dwell is calculated from observed polling windows (`first_seen_at` to `last_seen_at`), not from the exact Apple delist timestamp.
- Heartbeat not appearing:
  - Confirm `HEARTBEAT_ENABLED=true`.
  - Check `HEARTBEAT_INTERVAL_HOURS` and `data/runtime_meta.json` (`last_successful_notification_at` may still be recent).
- Startup notification not appearing:
  - Confirm `STARTUP_NOTIFY_ENABLED=true`.
  - Check `data/runtime_meta.json`; if `startup_notification_sent` is already `true`, startup alert will not repeat on each poll.
- Shutdown/crash notifications:
  - Not implemented from inside the watcher. Unexpected stops generally cannot self-report because the process is no longer running.

## Future Improvements

- Split parser logic into source-specific modules.
- Add generic config-driven watcher modes.
- Add richer notification formatting/routing.
- Add a lightweight dashboard/web UI for runs/state.
- Persist richer change history (beyond latest current snapshot).
