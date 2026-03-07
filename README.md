# apple-refurb-watcher

`apple-refurb-watcher` monitors Apple's refurbished Mac store, parses structured product listings, and sends notifications when new relevant matches appear (for example, `Mac mini`, optionally `Mac Studio`). It is also set up as a reusable starter template for other scheduled watcher/scraper projects: parser pipeline, state handling, notifications, logging, and macOS `launchd` automation are already wired.

## Features

- Structured extraction pipeline with parser fallback (`json_feed` -> `json_ld` -> `html_cards`) and preferred-parser caching.
- Relevant model filtering for `Mac mini` and optional `Mac Studio`.
- Fingerprint-based state tracking to avoid duplicate alerts.
- `current_matches` snapshots and runtime metadata for change detection and parser preference.
- Pushover notifications (plus optional iMessage path already present in code).
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
  - runtime files: `seen_items.json`, `current_matches.json`, `runtime_meta.json`, archived reset files
- `logs/`: Runtime logs (ignored in git).
  - tracked placeholder: `logs/.gitkeep`
- `.env.example`: Example local configuration.
- `.gitignore`: Ignore rules for runtime artifacts and local launchd files.
- `README.md`: This guide.

## Requirements

- Python 3.11+
- macOS for `launchd` automation (manual runs work anywhere Python dependencies work)
- Dependencies in `requirements.txt` (currently `beautifulsoup4`, `python-dotenv`, `requests`)
- Optional Pushover account/app if you want push alerts

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

## Environment Configuration

All runtime config comes from `.env`.

- `APPLE_REFURB_URL`: Source page URL to fetch.
- `MATCH_KEYWORDS`: Comma-separated keywords; also controls whether `Mac Studio` is included.
- `ENABLE_PUSHOVER`: `true/false` toggle for Pushover.
- `PUSHOVER_USER_KEY`: Pushover user key.
- `PUSHOVER_APP_TOKEN`: Pushover app token.
- `ENABLE_IMESSAGE`: `true/false` toggle for iMessage notifications (optional).
- `IMESSAGE_RECIPIENT`: iMessage target (email/phone tied to Messages) when iMessage is enabled.
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
- Alerts include title, memory/storage (if found), price (if found), and product URL.

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
2. Parse structured products with fallback strategy.
3. Normalize product fields (title/url/price/memory/storage/source).
4. Filter to relevant models (`Mac mini`, optional `Mac Studio`).
5. Build compact fingerprints.
6. Compare against seen fingerprints and previous current snapshot.
7. Notify only for new changes.
8. Save updated state snapshots and runtime metadata.

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

## Future Improvements

- Split parser logic into source-specific modules.
- Add generic config-driven watcher modes.
- Add richer notification formatting/routing.
- Add a lightweight dashboard/web UI for runs/state.
- Persist richer change history (beyond latest current snapshot).
