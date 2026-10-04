#!/bin/bash
# Sends a Telegram alert when Barry restarts.
# - Intentional (manual) restarts: silent.
# - Kernel upgrade reboots: informational (✅).
# - Unexpected crashes: warning (⚠️).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/telegram_env.sh"
load_telegram_token || exit 1

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
    KERNEL_UPGRADED=1
else
    MESSAGE="⚠️ Barry restarted at ${TIMESTAMP} — if unexpected, check for missed messages. (VPS snapshot or crash)"
fi

send_telegram "$MESSAGE" || exit 1

[ -n "$KERNEL_UPGRADED" ] && redis-cli del barry:last_kernel > /dev/null 2>&1

exit 0
