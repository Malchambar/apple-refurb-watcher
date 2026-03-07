#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
USER_NAME="$(id -un)"
LABEL="com.${USER_NAME}.apple-refurb-watcher"

TEMPLATE_PATH="${PROJECT_DIR}/launchd/apple-refurb-watcher.plist.template"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
OUTPUT_PATH="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"

if [[ ! -f "${TEMPLATE_PATH}" ]]; then
  echo "Template not found: ${TEMPLATE_PATH}" >&2
  exit 1
fi

mkdir -p "${LAUNCH_AGENTS_DIR}"

escape_for_sed() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

escaped_label="$(escape_for_sed "${LABEL}")"
escaped_project_dir="$(escape_for_sed "${PROJECT_DIR}")"

sed \
  -e "s|__LABEL__|${escaped_label}|g" \
  -e "s|__PROJECT_DIR__|${escaped_project_dir}|g" \
  "${TEMPLATE_PATH}" > "${OUTPUT_PATH}"

# Unload existing registration if present.
launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
launchctl unload "${OUTPUT_PATH}" >/dev/null 2>&1 || true

launchctl load "${OUTPUT_PATH}"

cat <<MSG
LaunchAgent installed successfully.
Label: ${LABEL}
Plist: ${OUTPUT_PATH}
Project: ${PROJECT_DIR}
MSG
