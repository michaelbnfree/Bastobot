#!/bin/bash
# Pre-reboot notification — fired by barry-notify-reboot.service during shutdown.
# Stores the current kernel in Redis so notify_restart.sh can detect a kernel upgrade.

TOKEN="8282849330:AAEAnJpa0lcp7FoFlnHUCcwyPoXJ7uh3I-U"
CHAT_ID="298886049"

KERNEL=$(uname -r)
redis-cli set barry:last_kernel "$KERNEL" > /dev/null 2>&1

TIMESTAMP=$(date -u '+%b %d, %Y %H:%M UTC')
MESSAGE="🔄 Barry going down at ${TIMESTAMP} for kernel upgrade (${KERNEL}). Back in ~60s."

curl -s --max-time 10 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MESSAGE}" \
    > /dev/null 2>&1

exit 0
