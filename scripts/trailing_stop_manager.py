#!/usr/bin/env python3
"""
Trailing Stop Manager
Automatically trails stops to lock in profits and let winners run
Runs every 5-10 minutes to update open trades
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

class TrailingStopManager:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )

    def get_current_prices(self):
        """Get current market prices for all assets"""
        try:
            indicators = json.loads(self.redis_client.get('indicators:data') or '{}')
            prices = {}
            for asset in ['BTC', 'ETH', 'SOL']:
                prices[asset] = indicators.get(asset, {}).get('price', None)
            return prices
        except:
            return {}

    def update_trailing_stops(self):
        """Update trailing stops for all open trades"""
        try:
            trades_file = '/root/bastobot/autonomous_trades_v2.jsonl'
            if not os.path.exists(trades_file):
                return 0

            prices = self.get_current_prices()
            updated_count = 0
            trailing_count = 0

            # Read all trades
            trades = []
            with open(trades_file, 'r') as f:
                for line in f:
                    if line.strip():
                        trades.append(json.loads(line))

            # Update open trades with trailing stops
            updated_trades = []
            for trade in trades:
                if trade.get('status') != 'OPEN':
                    updated_trades.append(trade)
                    continue

                asset = trade.get('asset', 'BTC')
                current_price = prices.get(asset)

                if not current_price:
                    updated_trades.append(trade)
                    continue

                entry_price = trade.get('entry_price')
                original_sl = trade.get('stop_loss')
                current_sl = trade.get('current_stop_loss', original_sl)
                take_profit = trade.get('take_profit')
                action = trade.get('action')

                # Calculate profit level
                if action == 'LONG':
                    profit_pips = current_price - entry_price
                    total_target = take_profit - entry_price
                    profit_pct = (profit_pips / total_target) if total_target > 0 else 0
                else:  # SHORT
                    profit_pips = entry_price - current_price
                    total_target = entry_price - take_profit
                    profit_pct = (profit_pips / total_target) if total_target > 0 else 0

                # Trailing stop logic
                new_sl = current_sl
                trailing_activated = trade.get('trailing_activated', False)

                if profit_pct >= 0.5 and not trailing_activated:
                    # Hit 50% of target: Move SL to breakeven
                    new_sl = entry_price
                    trade['trailing_activated'] = True
                    trade['breakeven_at'] = datetime.now(timezone.utc).isoformat()
                    logger.info(f"🎯 {asset} {action}: Hit 50% profit, SL moved to breakeven ({entry_price})")
                    trailing_count += 1
                    updated_count += 1

                elif profit_pct >= 0.75 and trailing_activated:
                    # Hit 75% of target: Trail SL at 90% of highest price
                    if action == 'LONG':
                        trail_distance = (current_price - entry_price) * 0.1  # 10% of gains
                        new_sl = current_price - trail_distance
                    else:  # SHORT
                        trail_distance = (entry_price - current_price) * 0.1
                        new_sl = current_price + trail_distance

                    # Only move SL up, never down
                    if action == 'LONG':
                        new_sl = max(new_sl, current_sl)
                    else:
                        new_sl = min(new_sl, current_sl)

                    if new_sl != current_sl:
                        logger.info(f"📈 {asset} {action}: Hit 75% profit, trailing SL to {new_sl:.2f}")
                        updated_count += 1

                elif profit_pct >= 1.0 and trailing_activated:
                    # Hit 100% of target: Trail very tight (5% of current price)
                    trail_pct = 0.05
                    if action == 'LONG':
                        new_sl = current_price * (1 - trail_pct)
                    else:
                        new_sl = current_price * (1 + trail_pct)

                    # Only tighten SL, never loosen
                    if action == 'LONG':
                        new_sl = max(new_sl, current_sl)
                    else:
                        new_sl = min(new_sl, current_sl)

                    if new_sl != current_sl:
                        logger.info(f"🚀 {asset} {action}: Hit 100% profit, tight trail to {new_sl:.2f}")
                        updated_count += 1

                # Update trade with new SL
                if new_sl != current_sl:
                    trade['current_stop_loss'] = new_sl
                    trade['sl_updated_at'] = datetime.now(timezone.utc).isoformat()
                    trade['sl_update_price'] = current_price
                    trade['profit_pct'] = profit_pct

                updated_trades.append(trade)

            # Write updated trades back
            with open(trades_file, 'w') as f:
                for trade in updated_trades:
                    f.write(json.dumps(trade) + '\n')

            if updated_count > 0:
                logger.info(f'Updated {updated_count} trailing stops ({trailing_count} breakeven activations)')

            return updated_count

        except Exception as e:
            logger.error(f'Error updating trailing stops: {e}')
            return 0

    def get_trailing_stop_stats(self):
        """Get statistics on trailing stops"""
        try:
            trades_file = '/root/bastobot/autonomous_trades_v2.jsonl'
            if not os.path.exists(trades_file):
                return {}

            trades = []
            with open(trades_file, 'r') as f:
                for line in f:
                    if line.strip():
                        trades.append(json.loads(line))

            open_trades = [t for t in trades if t.get('status') == 'OPEN']
            closed_trades = [t for t in trades if t.get('status') == 'CLOSED']

            # Trades with trailing stops activated
            trailing_active = [t for t in open_trades if t.get('trailing_activated')]
            breakeven_trades = [t for t in trailing_active if t.get('breakeven_at')]

            # Profit distribution
            profits_locked = sum([
                (t.get('take_profit', 0) - t.get('entry_price', 0)) if t.get('action') == 'LONG' else
                (t.get('entry_price', 0) - t.get('take_profit', 0))
                for t in breakeven_trades
            ])

            stats = {
                'open_trades': len(open_trades),
                'with_trailing_stops': len(trailing_active),
                'at_breakeven': len(breakeven_trades),
                'potential_profit_locked': round(profits_locked, 2),
                'avg_profit_pct': sum([t.get('profit_pct', 0) for t in open_trades]) / len(open_trades) if open_trades else 0
            }

            return stats

        except Exception as e:
            logger.error(f'Error calculating trailing stop stats: {e}')
            return {}

    def run(self):
        """Run trailing stop manager"""
        logger.info('Running Trailing Stop Manager...')
        self.update_trailing_stops()
        stats = self.get_trailing_stop_stats()
        logger.info(f'Trailing stop stats: {stats}')

if __name__ == '__main__':
    manager = TrailingStopManager()
    manager.run()
