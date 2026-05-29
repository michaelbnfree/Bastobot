#!/bin/bash
# Intentional restart — suppresses the Telegram alert.
# Usage: ./scripts/restart_barry.sh [tg|worker|all]

TARGET=${1:-all}

redis-cli set barry:restart:intentional 1 ex 60 > /dev/null

case "$TARGET" in
    tg)
        systemctl restart bastobot-tg.service
        echo "bastobot-tg restarted (silent)"
        ;;
    worker)
        systemctl restart bastobot-worker.service
        echo "bastobot-worker restarted (silent)"
        ;;
    all|*)
        systemctl restart bastobot-tg.service bastobot-worker.service
        echo "bastobot-tg + bastobot-worker restarted (silent)"
        ;;
esac
