#!/bin/bash
# Sends a Telegram alert when Barry restarts.
# - Intentional (manual) restarts: silent.
# - Kernel upgrade reboots: informational (✅).
# - Unexpected crashes: warning (⚠️).

TOKEN="***REDACTED_TELEGRAM_TOKEN***"
CHAT_ID="298886049"

INTENTIONAL=$(redis-cli get barry:restart:intentional 2>/dev/null)
if [ "$INTENTIONAL" = "1" ]; then
    redis-cli del barry:restart:intentional > /dev/null 2>&1
    exit 0
fi

KERNEL_NOW=$(uname -r)
KERNEL_LAST=$(redis-cli get barry:last_kernel 2>/dev/null)
TIMESTAMP=$(date -u '+%b %d, %Y %H:%M UTC')

if [ -n "$KERNEL_LAST" ] && [ "$KERNEL_NOW" != "$KERNEL_LAST" ]; then
    MESSAGE="✅ Barry back online at ${TIMESTAMP} — kernel upgraded (${KERNEL_LAST} → ${KERNEL_NOW})"
    redis-cli del barry:last_kernel > /dev/null 2>&1
else
    MESSAGE="⚠️ Barry restarted at ${TIMESTAMP} — if unexpected, check for missed messages. (VPS snapshot or crash)"
fi

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MESSAGE}" \
    > /dev/null 2>&1

exit 0
