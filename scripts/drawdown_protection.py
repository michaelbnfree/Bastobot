#!/usr/bin/env python3
"""
Drawdown Protection Circuit Breaker
Monitors equity and disables trading if drawdown exceeds threshold
Prevents catastrophic losses and protects capital
"""

import os
import sys
import json
import redis
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

sys.path.insert(0, '/root/bastobot')

load_dotenv('/root/bastobot/.env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
ACCOUNT_SIZE = float(os.getenv('ACCOUNT_SIZE_USD', '250000'))
MAX_DRAWDOWN_PCT = float(os.getenv('MAX_DRAWDOWN_PCT', '10.0'))  # 10% default

class DrawdownProtection:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )

    def calculate_current_equity(self):
        """Calculate current account equity"""
        try:
            trades_file = '/root/bastobot/autonomous_trades_v2.jsonl'
            if not os.path.exists(trades_file):
                return ACCOUNT_SIZE, 0

            trades = []
            with open(trades_file, 'r') as f:
                for line in f:
                    if line.strip():
                        trades.append(json.loads(line))

            # Calculate realized P&L from closed trades
            realized_pnl = 0
            for trade in trades:
                if trade.get('status') == 'CLOSED':
                    r_multiple = trade.get('r_multiple', 0)
                    risk_amount = trade.get('risk_amount_usd', 0)
                    realized_pnl += r_multiple * risk_amount

            # Calculate unrealized P&L from open trades (estimate)
            unrealized_pnl = 0
            for trade in trades:
                if trade.get('status') == 'OPEN':
                    current_price = trade.get('current_price', trade.get('entry_price'))
                    entry_price = trade.get('entry_price')
                    position_size = trade.get('position_size_usd', 0)
                    action = trade.get('action')

                    if action == 'LONG':
                        pnl = (current_price - entry_price) / entry_price * position_size
                    else:  # SHORT
                        pnl = (entry_price - current_price) / entry_price * position_size

                    unrealized_pnl += pnl

            current_equity = ACCOUNT_SIZE + realized_pnl + unrealized_pnl
            total_pnl = realized_pnl + unrealized_pnl

            return current_equity, total_pnl

        except Exception as e:
            logger.error(f'Error calculating equity: {e}')
            return ACCOUNT_SIZE, 0

    def check_circuit_breaker(self):
        """Check if drawdown exceeds threshold and trigger circuit breaker"""
        try:
            current_equity, total_pnl = self.calculate_current_equity()

            # Calculate drawdown
            drawdown = (ACCOUNT_SIZE - current_equity) / ACCOUNT_SIZE * 100
            drawdown_pct = max(0, drawdown)  # Only positive drawdowns count

            logger.info(f'Equity check: ${current_equity:,.0f} (Drawdown: {drawdown_pct:.1f}% / Max: {MAX_DRAWDOWN_PCT}%)')

            # Check if circuit breaker should trigger
            circuit_status = self.redis_client.get('trading_circuit_breaker')
            currently_broken = circuit_status == 'TRIGGERED'

            if drawdown_pct >= MAX_DRAWDOWN_PCT and not currently_broken:
                # TRIGGER circuit breaker
                logger.warning(f'⚠️ CIRCUIT BREAKER TRIGGERED: Drawdown {drawdown_pct:.1f}% exceeds max {MAX_DRAWDOWN_PCT}%')
                self._trigger_circuit_breaker(drawdown_pct, current_equity, total_pnl)
                return True

            elif drawdown_pct < (MAX_DRAWDOWN_PCT * 0.5) and currently_broken:
                # RECOVER circuit breaker (drawdown recovered to 50% of threshold)
                logger.info(f'✅ Circuit breaker recovered: Drawdown {drawdown_pct:.1f}% below recovery threshold')
                self._recover_circuit_breaker(drawdown_pct, current_equity, total_pnl)
                return False

            # Update equity stats in Redis
            self._update_equity_stats(current_equity, drawdown_pct, total_pnl)

            return currently_broken

        except Exception as e:
            logger.error(f'Error checking circuit breaker: {e}')
            return False

    def _trigger_circuit_breaker(self, drawdown_pct, equity, pnl):
        """Trigger the circuit breaker - disable trading"""
        try:
            alert = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'CIRCUIT_BREAKER_TRIGGERED',
                'severity': 'CRITICAL',
                'drawdown_pct': round(drawdown_pct, 2),
                'max_drawdown_pct': MAX_DRAWDOWN_PCT,
                'current_equity': round(equity, 2),
                'account_size': round(ACCOUNT_SIZE, 2),
                'realized_pnl': round(pnl, 2),
                'message': f'Trading DISABLED: Drawdown {drawdown_pct:.1f}% exceeds {MAX_DRAWDOWN_PCT}%',
                'action': 'DISABLE_AUTONOMOUS_TRADING'
            }

            # Store alert
            self.redis_client.set('circuit_breaker_alert', json.dumps(alert))
            self.redis_client.set('trading_circuit_breaker', 'TRIGGERED', ex=86400)  # 24 hours

            # Disable trading
            self.redis_client.set('ENABLE_AUTONOMOUS_TRADING', 'false')

            # Log to file
            with open('/root/bastobot/circuit_breaker_log.jsonl', 'a') as f:
                f.write(json.dumps(alert) + '\n')

            logger.critical(f'CIRCUIT BREAKER TRIGGERED: {alert["message"]}')

        except Exception as e:
            logger.error(f'Error triggering circuit breaker: {e}')

    def _recover_circuit_breaker(self, drawdown_pct, equity, pnl):
        """Recover from circuit breaker - re-enable trading"""
        try:
            alert = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'CIRCUIT_BREAKER_RECOVERED',
                'severity': 'INFO',
                'drawdown_pct': round(drawdown_pct, 2),
                'current_equity': round(equity, 2),
                'recovery_threshold': round(MAX_DRAWDOWN_PCT * 0.5, 2),
                'message': f'Trading RE-ENABLED: Drawdown recovered to {drawdown_pct:.1f}%',
                'action': 'ENABLE_AUTONOMOUS_TRADING'
            }

            # Update status
            self.redis_client.delete('trading_circuit_breaker')
            self.redis_client.set('ENABLE_AUTONOMOUS_TRADING', 'true')

            # Log recovery
            with open('/root/bastobot/circuit_breaker_log.jsonl', 'a') as f:
                f.write(json.dumps(alert) + '\n')

            logger.info(f'CIRCUIT BREAKER RECOVERED: {alert["message"]}')

        except Exception as e:
            logger.error(f'Error recovering circuit breaker: {e}')

    def _update_equity_stats(self, current_equity, drawdown_pct, pnl):
        """Update equity statistics in Redis"""
        try:
            stats = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'current_equity': round(current_equity, 2),
                'account_size': round(ACCOUNT_SIZE, 2),
                'drawdown_pct': round(drawdown_pct, 2),
                'max_drawdown_pct': MAX_DRAWDOWN_PCT,
                'total_pnl': round(pnl, 2),
                'circuit_breaker_status': self.redis_client.get('trading_circuit_breaker') or 'NORMAL'
            }

            self.redis_client.set('equity_stats', json.dumps(stats))

        except Exception as e:
            logger.debug(f'Error updating equity stats: {e}')

    def is_trading_enabled(self):
        """Check if trading is currently enabled"""
        circuit_status = self.redis_client.get('trading_circuit_breaker')
        return circuit_status != 'TRIGGERED'

    def run(self):
        """Run drawdown protection check"""
        logger.info('Running Drawdown Protection...')
        is_enabled = self.check_circuit_breaker()
        logger.info(f'Trading status: {"ENABLED ✅" if is_enabled else "DISABLED ⛔"}')

if __name__ == '__main__':
    protection = DrawdownProtection()
    protection.run()
