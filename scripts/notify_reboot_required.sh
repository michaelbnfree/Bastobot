#!/bin/bash
# Checks for a pending kernel/system reboot and alerts via Telegram.
# Notifies once per pending reboot; the marker lives in /var/run/ so it
# clears automatically after the reboot happens.

TOKEN="8282849330:AAEAnJpa0lcp7FoFlnHUCcwyPoXJ7uh3I-U"
CHAT_ID="298886049"

REBOOT_FLAG="/var/run/reboot-required"
NOTIFIED_MARKER="/var/run/barry-reboot-required-notified"

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

curl -s --max-time 10 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MESSAGE}" \
    > /dev/null 2>&1

touch "$NOTIFIED_MARKER"
exit 0
