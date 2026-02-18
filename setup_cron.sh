#!/usr/bin/env bash
# setup_cron.sh — Install the 15-minute cron job for the Polymarket bot.
#
# Usage: bash setup_cron.sh [/path/to/python]
#
# If no Python path is given, the script looks for a virtualenv at
#   ./venv/bin/python  then falls back to the system python3.
#
# The log is written to bot.log in the same directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_SCRIPT="$SCRIPT_DIR/run_bot.py"
LOG_FILE="$SCRIPT_DIR/bot.log"

# --- Resolve Python interpreter ---
if [[ $# -ge 1 ]]; then
  PYTHON="$1"
elif [[ -x "$SCRIPT_DIR/venv/bin/python" ]]; then
  PYTHON="$SCRIPT_DIR/venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON="$(command -v python3)"
else
  echo "ERROR: Could not find a Python interpreter. Pass the path as an argument."
  exit 1
fi

echo "Using Python: $PYTHON"
echo "Bot script:   $BOT_SCRIPT"
echo "Log file:     $LOG_FILE"

# --- Build cron line ---
CRON_LINE="*/15 * * * * $PYTHON $BOT_SCRIPT >> $LOG_FILE 2>&1"

# --- Add to crontab if not already present ---
EXISTING_CRONTAB="$(crontab -l 2>/dev/null || true)"

if echo "$EXISTING_CRONTAB" | grep -qF "$BOT_SCRIPT"; then
  echo ""
  echo "A cron entry for $BOT_SCRIPT already exists:"
  echo "$EXISTING_CRONTAB" | grep "$BOT_SCRIPT"
  echo ""
  echo "No changes made. To update, remove the existing entry first with:"
  echo "  crontab -e"
else
  (echo "$EXISTING_CRONTAB"; echo "$CRON_LINE") | crontab -
  echo ""
  echo "Cron job installed successfully."
  echo "Entry: $CRON_LINE"
  echo ""
  echo "Verify with:  crontab -l"
  echo "View logs:    tail -f $LOG_FILE"
fi
