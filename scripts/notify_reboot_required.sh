#!/bin/bash
# Checks for a pending kernel/system reboot and alerts via Telegram.
# Notifies once per pending reboot; the marker lives in /var/run/ so it
# clears automatically after the reboot happens.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/telegram_env.sh"
load_telegram_token || exit 1

REBOOT_FLAG="${REBOOT_FLAG:-/var/run/reboot-required}"
NOTIFIED_MARKER="${NOTIFIED_MARKER:-/var/run/barry-reboot-required-notified}"

[ -f "$REBOOT_FLAG" ] || exit 0
[ -f "$NOTIFIED_MARKER" ] && exit 0

PACKAGES=""
if [ -f /var/run/reboot-required.pkgs ]; then
    PACKAGES=$(cat /var/run/reboot-required.pkgs | sort -u | tr '\n' ' ')
fi

TIMESTAMP=$(date -u '+%b %d, %Y %H:%M UTC')
if [ -n "$PACKAGES" ]; then
    MESSAGE="⚠️ Reboot required on bastobot (${TIMESTAMP}).
Packages: ${PACKAGES}
Run reboot at your next maintenance window."
else
    MESSAGE="⚠️ Reboot required on bastobot (${TIMESTAMP}).
Run reboot at your next maintenance window."
fi

send_telegram "$MESSAGE" || exit 1

touch "$NOTIFIED_MARKER"
exit 0
