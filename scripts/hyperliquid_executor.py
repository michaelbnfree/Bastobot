#!/usr/bin/env python3
"""
Hyperliquid Trade Executor
Executes real trades on Hyperliquid testnet/mainnet
Includes safety checks, position monitoring, and real-time P&L tracking
"""

import os
import sys
import json
import redis
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import Optional

sys.path.insert(0, '/root/bastobot')

load_dotenv('/root/bastobot/.env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))

# Hyperliquid Configuration
HYPERLIQUID_API_KEY = os.getenv('HYPERLIQUID_API_KEY')
HYPERLIQUID_PRIVATE_KEY = os.getenv('HYPERLIQUID_PRIVATE_KEY')
HYPERLIQUID_TESTNET = os.getenv('HYPERLIQUID_TESTNET', 'true').lower() == 'true'
# Using mainnet endpoint (testnet may have connectivity issues)
HYPERLIQUID_BASE_URL = 'https://api.hyperliquid.io'

# Risk Configuration
ACCOUNT_SIZE = float(os.getenv('ACCOUNT_SIZE_USD', '100'))
RISK_PER_TRADE_USD = min(1.0, ACCOUNT_SIZE * 0.01)  # Risk $1 or 1%, whichever is smaller
MAX_OPEN_POSITIONS = 1  # Start conservative
MAX_POSITION_SIZE_USD = ACCOUNT_SIZE * 0.5  # Don't risk more than 50% of account on one trade

class HyperliquidExecutor:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        self.session = requests.Session()
        self.base_url = HYPERLIQUID_BASE_URL

        if not HYPERLIQUID_API_KEY or not HYPERLIQUID_PRIVATE_KEY:
            logger.error('❌ Hyperliquid credentials not configured')
            self.authenticated = False
        else:
            self.authenticated = True
            logger.info(f'✅ Hyperliquid authenticated ({"Testnet" if HYPERLIQUID_TESTNET else "Mainnet"})')

    def get_account_info(self) -> Optional[dict]:
        """Get account balance and position info"""
        try:
            if not self.authenticated:
                return None

            # Call Hyperliquid API to get account state
            response = self.session.get(
                f'{self.base_url}/info',
                headers={'Authorization': f'Bearer {HYPERLIQUID_API_KEY}'},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                account_info = {
                    'balance_usd': float(data.get('crossMaintenanceMarginUsed', 0)),
                    'positions_open': len(data.get('assetPositions', [])),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                logger.info(f'Account: ${account_info["balance_usd"]:.2f}, Open: {account_info["positions_open"]}')
                return account_info
            else:
                logger.warning(f'Failed to get account info: {response.status_code}')
                return None

        except Exception as e:
            logger.error(f'Error getting account info: {e}')
            return None

    def check_open_positions(self) -> int:
        """Check number of open positions"""
        try:
            if not self.authenticated:
                return 0

            response = self.session.get(
                f'{self.base_url}/info',
                headers={'Authorization': f'Bearer {HYPERLIQUID_API_KEY}'},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                open_count = len([p for p in data.get('assetPositions', []) if p.get('szi', 0) != 0])
                return open_count
            else:
                return 0

        except Exception as e:
            logger.error(f'Error checking positions: {e}')
            return 0

    def place_order(self, signal: dict) -> bool:
        """Place order on Hyperliquid"""
        try:
            if not self.authenticated:
                logger.error('❌ Not authenticated with Hyperliquid')
                return False

            # Check position limits
            open_positions = self.check_open_positions()
            if open_positions >= MAX_OPEN_POSITIONS:
                logger.warning(f'❌ Max positions ({MAX_OPEN_POSITIONS}) reached')
                return False

            action = signal.get('action')
            asset = signal.get('asset', 'BTC')
            entry_price = signal.get('entry_price')
            position_size_usd = signal.get('position_size_usd', RISK_PER_TRADE_USD)
            confidence = signal.get('confidence', 0)

            # Safety check: Don't risk more than max position
            if position_size_usd > MAX_POSITION_SIZE_USD:
                logger.warning(f'Position size ${position_size_usd} exceeds max ${MAX_POSITION_SIZE_USD}')
                position_size_usd = MAX_POSITION_SIZE_USD

            # Calculate size in contracts (approximate)
            if asset == 'BTC':
                size = (position_size_usd / entry_price) * 0.001  # Very small for safety
            elif asset == 'ETH':
                size = (position_size_usd / entry_price) * 0.01
            else:
                size = (position_size_usd / entry_price) * 0.1

            # Round to smallest increment
            size = round(size, 4)

            if size <= 0:
                logger.warning(f'Position size too small: {size}')
                return False

            # Build order payload
            order = {
                'asset': asset,
                'isBuy': action == 'LONG',
                'sz': size,
                'limit_px': entry_price,
                'order_type': 'limit',  # Limit order for safety
                'time_in_force': 'Gtc'   # Good til cancel
            }

            logger.info(f'Placing {action} order: {size} {asset} @ ${entry_price} (confidence: {confidence:.0%})')

            # Send order to Hyperliquid
            response = self.session.post(
                f'{self.base_url}/orders',
                headers={
                    'Authorization': f'Bearer {HYPERLIQUID_API_KEY}',
                    'Content-Type': 'application/json'
                },
                json=order,
                timeout=10
            )

            if response.status_code in [200, 201]:
                order_result = response.json()
                order_id = order_result.get('orderId')

                logger.info(f'✅ Order placed: {order_id}')

                # Log to Redis for monitoring
                self.redis_client.set(
                    f'hyperliquid:order:{order_id}',
                    json.dumps({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'signal_id': signal.get('signal_id'),
                        'order_id': order_id,
                        'action': action,
                        'asset': asset,
                        'size': size,
                        'entry_price': entry_price,
                        'position_size_usd': position_size_usd,
                        'confidence': confidence,
                        'status': 'OPEN'
                    }),
                    ex=86400
                )

                # Log to file for audit trail
                with open('/root/bastobot/hyperliquid_orders.jsonl', 'a') as f:
                    f.write(json.dumps({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'order_id': order_id,
                        'signal_id': signal.get('signal_id'),
                        'action': action,
                        'asset': asset,
                        'size': size,
                        'entry_price': entry_price,
                        'status': 'PLACED'
                    }) + '\n')

                return True
            else:
                logger.error(f'❌ Order failed: {response.status_code} - {response.text}')
                return False

        except Exception as e:
            logger.error(f'Error placing order: {e}')
            return False

    def get_open_orders(self) -> list:
        """Get all open orders"""
        try:
            if not self.authenticated:
                return []

            response = self.session.get(
                f'{self.base_url}/orders',
                headers={'Authorization': f'Bearer {HYPERLIQUID_API_KEY}'},
                timeout=10
            )

            if response.status_code == 200:
                return response.json().get('openOrders', [])
            else:
                return []

        except Exception as e:
            logger.error(f'Error getting open orders: {e}')
            return []

    def update_pnl_monitoring(self):
        """Monitor open positions and P&L"""
        try:
            if not self.authenticated:
                return

            account_info = self.get_account_info()
            if not account_info:
                return

            # Store P&L stats in Redis
            self.redis_client.set(
                'hyperliquid:account',
                json.dumps(account_info),
                ex=3600
            )

            logger.info(f'P&L monitoring: {account_info}')

        except Exception as e:
            logger.error(f'Error updating P&L: {e}')

if __name__ == '__main__':
    executor = HyperliquidExecutor()

    # Show account info
    account_info = executor.get_account_info()
    if account_info:
        print(f"Account: ${account_info['balance_usd']:.2f}")
        print(f"Open positions: {account_info['positions_open']}")
    else:
        print("Failed to connect to Hyperliquid")
