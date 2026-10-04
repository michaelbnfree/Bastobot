#!/bin/bash
# Daily disk space check — alerts via Telegram when usage crosses threshold.
# Uses a /var/run marker to avoid repeated alerts at the same usage level.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/telegram_env.sh"
load_telegram_token || exit 1

THRESHOLD="${THRESHOLD:-75}"
CRITICAL=90
NOTIFIED_MARKER="${NOTIFIED_MARKER:-/var/run/barry-disk-alert-notified}"

DISK_PCT=$(df / | awk 'NR==2 {print $5}' | tr -d '%')

if [ "${DISK_PCT:-0}" -lt "$THRESHOLD" ]; then
    rm -f "$NOTIFIED_MARKER"
    exit 0
fi

[ -f "$NOTIFIED_MARKER" ] && exit 0

TIMESTAMP=$(date -u '+%b %d, %Y %H:%M UTC')
DISK_USED=$(df -h / | awk 'NR==2 {print $3}')
DISK_TOTAL=$(df -h / | awk 'NR==2 {print $2}')
DISK_AVAIL=$(df -h / | awk 'NR==2 {print $4}')

if [ "$DISK_PCT" -ge "$CRITICAL" ]; then
    ICON="🚨"
    LABEL="CRITICAL"
else
    ICON="⚠️"
    LABEL="WARNING"
fi

MESSAGE="${ICON} Disk ${LABEL} on bastobot (${TIMESTAMP}).
Usage: ${DISK_PCT}% (${DISK_USED} of ${DISK_TOTAL} used, ${DISK_AVAIL} free)
Consider: docker system prune -f or clearing old logs."

send_telegram "$MESSAGE" || exit 1

touch "$NOTIFIED_MARKER"
exit 0
