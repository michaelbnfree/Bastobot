#!/bin/bash
# Barry health check — run after boot (barry-health-check.service) or manually.
# Sends a Telegram summary and prints to stdout.

TOKEN="8282849330:AAEAnJpa0lcp7FoFlnHUCcwyPoXJ7uh3I-U"
CHAT_ID="298886049"

TIMESTAMP=$(date -u '+%b %d, %Y %H:%M UTC')
ALL_OK=true
BODY=""

# --- Systemd services ---
SERVICES=(bastobot-api bastobot-tg bastobot-worker bastobot-tasks-worker bastobot-scanner)
for svc in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc"; then
        BODY+="  ✅ $svc\n"
    else
        STATE=$(systemctl is-active "$svc")
        BODY+="  ❌ $svc ($STATE)\n"
        ALL_OK=false
    fi
done

# --- Redis ---
BODY+="\n"
if redis-cli ping 2>/dev/null | grep -q PONG; then
    BODY+="Redis: ✅\n"
else
    BODY+="Redis: ❌ not responding\n"
    ALL_OK=false
fi

# --- RQ workers ---
WORKER_COUNT=$(redis-cli keys "rq:worker:*" 2>/dev/null | wc -l | tr -d ' ')
if [ "$WORKER_COUNT" -ge 2 ]; then
    BODY+="Workers: ✅ $WORKER_COUNT registered\n"
else
    BODY+="Workers: ⚠️ only $WORKER_COUNT of 2 registered\n"
    ALL_OK=false
fi

# --- API ---
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:18790/docs 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    BODY+="API: ✅ $HTTP_CODE\n"
else
    BODY+="API: ❌ got $HTTP_CODE\n"
    ALL_OK=false
fi

# --- Compose ---
if $ALL_OK; then
    HEADER="✅ Barry fully operational — ${TIMESTAMP}"
else
    HEADER="⚠️ Barry health check — ${TIMESTAMP} — issues detected"
fi

MESSAGE=$(printf "%s\n\n%b" "$HEADER" "$BODY")

printf "%s\n" "$MESSAGE"

curl -s --max-time 10 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MESSAGE}" \
    > /dev/null 2>&1

exit 0
