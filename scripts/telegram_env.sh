# Sourced by the notify_*.sh scripts and health_check.sh.
# Reads only TELEGRAM_BOT_TOKEN from .env (the file is never sourced) and checks
# Telegram's answer, so a bad token fails the unit instead of looking like success.
# A scrubbed placeholder ("***REDACTED_TELEGRAM_TOKEN***") was once committed in
# each script; every alert got a 404 while the scripts exited 0.

BASTOBOT_ENV="${BASTOBOT_ENV:-/root/bastobot/.env}"
CHAT_ID="${TELEGRAM_CHAT_ID:-298886049}"

load_telegram_token() {
    TOKEN=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' "$BASTOBOT_ENV" 2>/dev/null | cut -d= -f2- | tr -d "\"' \r")
    if ! [[ "$TOKEN" =~ ^[0-9]{6,}:[A-Za-z0-9_-]{30,}$ ]]; then
        echo "FATAL: TELEGRAM_BOT_TOKEN missing or not a bot token in $BASTOBOT_ENV" >&2
        return 1
    fi
}

# send_telegram "text": succeeds only if Telegram answered HTTP 200.
send_telegram() {
    local code
    code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' -X POST \
        "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${CHAT_ID}" \
        --data-urlencode "text=$1")
    if [ "$code" != "200" ]; then
        echo "Telegram send failed: HTTP ${code:-none}" >&2
        return 1
    fi
}
