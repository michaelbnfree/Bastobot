#!/bin/bash
# Barry health check — run after boot (barry-health-check.service) or manually.
# Sends a Telegram summary and prints to stdout.

TOKEN="8282849330:AAEAnJpa0lcp7FoFlnHUCcwyPoXJ7uh3I-U"
CHAT_ID="298886049"

TIMESTAMP=$(date -u '+%b %d, %Y %H:%M UTC')
ALL_OK=true
BODY=""

# --- Systemd services ---
SERVICES=(bastobot-api bastobot-tg bastobot-worker bastobot-tasks-worker bastobot-scanner cloudflared)
for svc in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc"; then
        BODY+="  ✅ $svc\n"
    else
        STATE=$(systemctl is-active "$svc")
        BODY+="  ❌ $svc ($STATE)\n"
        ALL_OK=false
    fi
done

BODY+="\n"

# --- Redis ---
if redis-cli ping 2>/dev/null | grep -q PONG; then
    REDIS_MEM=$(redis-cli info memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '\r ')
    BODY+="Redis: ✅ (${REDIS_MEM})\n"
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

# --- Queue backlog ---
Q_FAST=$(redis-cli llen rq:queue:fast 2>/dev/null)
Q_TASKS=$(redis-cli llen rq:queue:bastobot_tasks 2>/dev/null)
if [ "${Q_FAST:-0}" -le 5 ] && [ "${Q_TASKS:-0}" -le 5 ]; then
    BODY+="Queues: ✅ fast=${Q_FAST} tasks=${Q_TASKS}\n"
else
    BODY+="Queues: ⚠️ backlog fast=${Q_FAST} tasks=${Q_TASKS}\n"
    ALL_OK=false
fi

# --- Scanner freshness ---
LAST_SCAN=$(redis-cli get scanner:last_scan 2>/dev/null)
if [ -z "$LAST_SCAN" ]; then
    BODY+="Scanner: ❌ no scan recorded\n"
    ALL_OK=false
else
    SCAN_EPOCH=$(date -d "$LAST_SCAN" +%s 2>/dev/null)
    NOW_EPOCH=$(date +%s)
    AGE=$(( NOW_EPOCH - SCAN_EPOCH ))
    AGE_MIN=$(( AGE / 60 ))
    if [ "$AGE" -lt 600 ]; then
        BODY+="Scanner: ✅ last scan ${AGE_MIN}m ago\n"
    else
        BODY+="Scanner: ⚠️ last scan ${AGE_MIN}m ago (stale)\n"
        ALL_OK=false
    fi
fi

# --- API ---
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:18790/docs 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    BODY+="API: ✅ $HTTP_CODE\n"
else
    BODY+="API: ❌ got $HTTP_CODE\n"
    ALL_OK=false
fi

# --- Disk ---
DISK_PCT=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
if [ "${DISK_PCT:-0}" -lt 80 ]; then
    BODY+="Disk: ✅ ${DISK_PCT}% used\n"
else
    BODY+="Disk: ⚠️ ${DISK_PCT}% used\n"
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
