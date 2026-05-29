#!/bin/bash
# Sends a Telegram alert when Barry restarts unexpectedly.
# Skipped if barry:restart:intentional is set in Redis (manual restart).

TOKEN="8282849330:AAEAnJpa0lcp7FoFlnHUCcwyPoXJ7uh3I-U"
CHAT_ID="298886049"

INTENTIONAL=$(redis-cli get barry:restart:intentional 2>/dev/null)
if [ "$INTENTIONAL" = "1" ]; then
    redis-cli del barry:restart:intentional > /dev/null 2>&1
    exit 0
fi

TIMESTAMP=$(date -u '+%b %d, %Y %H:%M UTC')
MESSAGE="⚠️ Barry restarted at ${TIMESTAMP} — if unexpected, check for missed messages. (VPS snapshot or crash)"

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MESSAGE}" \
    > /dev/null 2>&1

exit 0
