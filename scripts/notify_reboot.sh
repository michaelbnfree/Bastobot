#!/bin/bash
# Pre-reboot notification — fired by barry-notify-reboot.service during shutdown.
# Stores the current kernel in Redis so notify_restart.sh can detect a kernel upgrade.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/telegram_env.sh"
load_telegram_token || exit 1

KERNEL=$(uname -r)
redis-cli set barry:last_kernel "$KERNEL" > /dev/null 2>&1

TIMESTAMP=$(date -u '+%b %d, %Y %H:%M UTC')
MESSAGE="🔄 Barry going down at ${TIMESTAMP} for kernel upgrade (${KERNEL}). Back in ~60s."

send_telegram "$MESSAGE" || exit 1

exit 0
