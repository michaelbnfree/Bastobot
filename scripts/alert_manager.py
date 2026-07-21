#!/usr/bin/env python3
"""
Alert Manager
Sends real-time alerts via Telegram/Slack for trading events
"""

import os
import sys
import json
import redis
import logging
import requests
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

# Alert destinations
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

class AlertManager:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )

    def send_telegram_alert(self, title: str, message: str, alert_type: str = 'INFO'):
        """Send alert via Telegram"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return False

        try:
            # Emoji based on alert type
            emoji_map = {
                'TRADE_SIGNAL': '🚀',
                'TRADE_CLOSED': '✅',
                'LOSS': '❌',
                'REGIME_CHANGE': '⚠️',
                'CIRCUIT_BREAKER': '⛔',
                'ERROR': '🔴',
                'INFO': 'ℹ️'
            }
            emoji = emoji_map.get(alert_type, 'ℹ️')

            text = f"{emoji} *{title}*\n\n{message}"

            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': text,
                'parse_mode': 'Markdown'
            }

            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.debug(f'Telegram alert sent: {title}')
                return True
            else:
                logger.warning(f'Telegram failed: {response.status_code}')
                return False

        except Exception as e:
            logger.error(f'Telegram alert error: {e}')
            return False

    def send_slack_alert(self, title: str, message: str, alert_type: str = 'INFO'):
        """Send alert via Slack"""
        if not SLACK_WEBHOOK_URL:
            return False

        try:
            # Color based on alert type
            color_map = {
                'TRADE_SIGNAL': '#36a64f',  # Green
                'TRADE_CLOSED': '#0099ff',  # Blue
                'LOSS': '#ff0000',          # Red
                'REGIME_CHANGE': '#ffaa00', # Orange
                'CIRCUIT_BREAKER': '#ff0000', # Red
                'ERROR': '#ff0000',         # Red
                'INFO': '#0099ff'           # Blue
            }
            color = color_map.get(alert_type, '#0099ff')

            payload = {
                'attachments': [
                    {
                        'color': color,
                        'title': title,
                        'text': message,
                        'ts': int(datetime.now(timezone.utc).timestamp())
                    }
                ]
            }

            response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
            if response.status_code == 200:
                logger.debug(f'Slack alert sent: {title}')
                return True
            else:
                logger.warning(f'Slack failed: {response.status_code}')
                return False

        except Exception as e:
            logger.error(f'Slack alert error: {e}')
            return False

    def send_all_alerts(self, title: str, message: str, alert_type: str = 'INFO'):
        """Send alert to all configured channels"""
        self.send_telegram_alert(title, message, alert_type)
        self.send_slack_alert(title, message, alert_type)

    def alert_on_trade_signal(self, signal: dict):
        """Alert when new trade signal generated"""
        try:
            action = signal.get('action')
            asset = signal.get('asset', 'BTC')
            entry = signal.get('entry_price')
            sl = signal.get('stop_loss')
            tp = signal.get('take_profit')
            confidence = signal.get('confidence', 0)
            risk_reward = signal.get('risk_reward_ratio', 0)
            position_size = signal.get('position_size_usd', 0)

            title = f"New Trade Signal: {action} {asset}"
            message = f"""
Entry: ${entry:,.2f}
SL: ${sl:,.2f}
TP: ${tp:,.2f}
R:R: {risk_reward:.1f}:1
Position: ${position_size:,.0f}
Confidence: {confidence:.0%}
            """.strip()

            self.send_all_alerts(title, message, 'TRADE_SIGNAL')

            # Store alert in Redis
            alert = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'TRADE_SIGNAL',
                'signal': signal
            }
            self.redis_client.lpush('alerts', json.dumps(alert))
            self.redis_client.ltrim('alerts', 0, 99)  # Keep last 100

        except Exception as e:
            logger.error(f'Error alerting on trade signal: {e}')

    def alert_on_trade_close(self, trade: dict):
        """Alert when trade closes (WIN or LOSS)"""
        try:
            outcome = trade.get('outcome')
            asset = trade.get('asset', 'BTC')
            action = trade.get('action')
            entry = trade.get('entry_price')
            exit_price = trade.get('exit_price')
            r_multiple = trade.get('r_multiple', 0)
            pnl = r_multiple * trade.get('risk_amount_usd', 0)

            alert_type = 'TRADE_CLOSED' if outcome == 'WIN' else 'LOSS'
            emoji = '✅' if outcome == 'WIN' else '❌'

            title = f"{emoji} Trade Closed: {asset} {action} ({outcome})"
            message = f"""
Entry: ${entry:,.2f}
Exit: ${exit_price:,.2f}
Return: {r_multiple:.2f}R
P&L: ${pnl:,.0f}
            """.strip()

            self.send_all_alerts(title, message, alert_type)

            # Store alert
            alert = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': alert_type,
                'trade': trade
            }
            self.redis_client.lpush('alerts', json.dumps(alert))
            self.redis_client.ltrim('alerts', 0, 99)

        except Exception as e:
            logger.error(f'Error alerting on trade close: {e}')

    def alert_on_regime_change(self, old_regime: str, new_regime: str, confidence: float):
        """Alert when market regime changes"""
        try:
            title = f"⚠️ Market Regime Change"
            message = f"""
Previous: {old_regime}
New: {new_regime}
Confidence: {confidence:.0%}
            """.strip()

            self.send_all_alerts(title, message, 'REGIME_CHANGE')

            # Store alert
            alert = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'REGIME_CHANGE',
                'old_regime': old_regime,
                'new_regime': new_regime,
                'confidence': confidence
            }
            self.redis_client.lpush('alerts', json.dumps(alert))
            self.redis_client.ltrim('alerts', 0, 99)

        except Exception as e:
            logger.error(f'Error alerting on regime change: {e}')

    def alert_on_circuit_breaker(self, drawdown: float, max_drawdown: float):
        """Alert when circuit breaker triggers"""
        try:
            title = "⛔ Circuit Breaker Triggered"
            message = f"""
Drawdown: {drawdown:.1f}%
Max Allowed: {max_drawdown:.1f}%
Status: Trading DISABLED for protection
            """.strip()

            self.send_all_alerts(title, message, 'CIRCUIT_BREAKER')

            # Store alert
            alert = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'CIRCUIT_BREAKER',
                'drawdown': drawdown,
                'max_drawdown': max_drawdown
            }
            self.redis_client.lpush('alerts', json.dumps(alert))
            self.redis_client.ltrim('alerts', 0, 99)

        except Exception as e:
            logger.error(f'Error alerting on circuit breaker: {e}')

    def get_recent_alerts(self, count: int = 10) -> list:
        """Get recent alerts from Redis"""
        try:
            alerts = []
            alert_data = self.redis_client.lrange('alerts', 0, count - 1)
            for alert_json in alert_data:
                alerts.append(json.loads(alert_json))
            return alerts
        except Exception as e:
            logger.error(f'Error getting recent alerts: {e}')
            return []

if __name__ == '__main__':
    manager = AlertManager()

    # Test alerts
    print("Testing alert system...")

    # Test signal alert
    test_signal = {
        'action': 'LONG',
        'asset': 'BTC',
        'entry_price': 64100,
        'stop_loss': 63500,
        'take_profit': 65300,
        'risk_reward_ratio': 2.0,
        'position_size_usd': 5000,
        'confidence': 0.68
    }
    manager.alert_on_trade_signal(test_signal)

    # Test trade close alert
    test_trade = {
        'asset': 'BTC',
        'action': 'LONG',
        'entry_price': 64100,
        'exit_price': 65300,
        'r_multiple': 2.0,
        'risk_amount_usd': 5000,
        'outcome': 'WIN'
    }
    manager.alert_on_trade_close(test_trade)

    print("✅ Test alerts sent")
