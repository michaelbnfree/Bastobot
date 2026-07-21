#!/usr/bin/env python3
"""
Trade Performance Tracker
Updates autonomous trades with exit prices and calculates win/loss metrics
Runs periodically to close trades and track performance
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

class TradePerformanceTracker:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )

    def get_indicators(self):
        """Get current market indicators for exit price"""
        try:
            indicators = json.loads(self.redis_client.get('indicators:data') or '{}')
            return indicators
        except:
            return {}

    def close_trades_at_tp_or_sl(self):
        """Close trades that hit take profit or stop loss"""
        try:
            trades_file = '/root/bastobot/autonomous_trades_v2.jsonl'
            if not os.path.exists(trades_file):
                return

            indicators = self.get_indicators()
            updated_trades = []
            closed_count = 0

            with open(trades_file, 'r') as f:
                lines = f.readlines()

            for line in lines:
                try:
                    trade = json.loads(line)

                    # Only process open trades
                    if trade.get('status') != 'OPEN':
                        updated_trades.append(trade)
                        continue

                    asset = trade.get('asset', 'BTC')
                    current_price = indicators.get(asset, {}).get('price', None)

                    if not current_price:
                        updated_trades.append(trade)
                        continue

                    entry_price = trade.get('entry_price')
                    stop_loss = trade.get('stop_loss')
                    take_profit = trade.get('take_profit')
                    action = trade.get('action')

                    # Check if trade hit SL or TP
                    hit_sl = (action == 'LONG' and current_price <= stop_loss) or \
                             (action == 'SHORT' and current_price >= stop_loss)
                    hit_tp = (action == 'LONG' and current_price >= take_profit) or \
                             (action == 'SHORT' and current_price <= take_profit)

                    if hit_sl or hit_tp:
                        # Close the trade
                        trade['exit_price'] = current_price
                        trade['status'] = 'CLOSED'
                        trade['closed_at'] = datetime.now(timezone.utc).isoformat()

                        # Calculate outcome
                        if hit_tp:
                            trade['outcome'] = 'WIN'
                        else:
                            trade['outcome'] = 'LOSS'

                        # Calculate R multiple
                        risk_pips = abs(entry_price - stop_loss)
                        if action == 'LONG':
                            result_pips = current_price - entry_price
                        else:
                            result_pips = entry_price - current_price

                        r_multiple = result_pips / risk_pips if risk_pips > 0 else 0
                        trade['r_multiple'] = round(r_multiple, 2)

                        logger.info(
                            f"Closed {trade['outcome']}: {asset} {action} @ {entry_price} "
                            f"→ {current_price} (R: {r_multiple:.2f})"
                        )
                        closed_count += 1

                    updated_trades.append(trade)

                except Exception as e:
                    logger.error(f'Error processing trade: {e}')
                    updated_trades.append(trade)

            # Write updated trades back
            with open(trades_file, 'w') as f:
                for trade in updated_trades:
                    f.write(json.dumps(trade) + '\n')

            logger.info(f'Closed {closed_count} trades this cycle')
            return closed_count

        except Exception as e:
            logger.error(f'Error closing trades: {e}')
            return 0

    def calculate_performance_stats(self):
        """Calculate overall performance metrics"""
        try:
            trades_file = '/root/bastobot/autonomous_trades_v2.jsonl'
            if not os.path.exists(trades_file):
                return {}

            stats = {
                'total_trades': 0,
                'open_trades': 0,
                'closed_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'avg_r_multiple': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'consecutive_wins': 0,
                'max_consecutive_wins': 0,
                'consecutive_losses': 0,
                'max_consecutive_losses': 0,
                'avg_confidence': 0.0,
                'total_risk_usd': 0.0,
                'realized_pnl_usd': 0.0,
                'equity_curve': []
            }

            trades = []
            with open(trades_file, 'r') as f:
                for line in f:
                    if line.strip():
                        trades.append(json.loads(line))

            stats['total_trades'] = len(trades)

            closed_trades = [t for t in trades if t.get('status') == 'CLOSED']
            open_trades = [t for t in trades if t.get('status') == 'OPEN']

            stats['open_trades'] = len(open_trades)
            stats['closed_trades'] = len(closed_trades)

            if not closed_trades:
                return stats

            # Calculate metrics from closed trades
            winning_trades = [t for t in closed_trades if t.get('outcome') == 'WIN']
            losing_trades = [t for t in closed_trades if t.get('outcome') == 'LOSS']

            stats['winning_trades'] = len(winning_trades)
            stats['losing_trades'] = len(losing_trades)

            # Win rate
            if closed_trades:
                stats['win_rate'] = len(winning_trades) / len(closed_trades)

            # R multiples
            r_multiples = [t.get('r_multiple', 0) for t in closed_trades if t.get('r_multiple')]
            if r_multiples:
                stats['avg_r_multiple'] = sum(r_multiples) / len(r_multiples)
                stats['best_trade'] = max(r_multiples)
                stats['worst_trade'] = min(r_multiples)

            # Profit factor (gross profits / gross losses)
            winning_r = sum([t.get('r_multiple', 0) for t in winning_trades if t.get('r_multiple', 0) > 0])
            losing_r = sum([abs(t.get('r_multiple', 0)) for t in losing_trades if t.get('r_multiple', 0) < 0])
            stats['profit_factor'] = winning_r / losing_r if losing_r > 0 else 0

            # Consecutive wins/losses
            current_win_streak = 0
            current_loss_streak = 0
            for trade in closed_trades:
                if trade.get('outcome') == 'WIN':
                    current_win_streak += 1
                    current_loss_streak = 0
                    stats['max_consecutive_wins'] = max(stats['max_consecutive_wins'], current_win_streak)
                else:
                    current_loss_streak += 1
                    current_win_streak = 0
                    stats['max_consecutive_losses'] = max(stats['max_consecutive_losses'], current_loss_streak)

            # Average confidence
            confidences = [t.get('confidence', 0.5) for t in closed_trades]
            stats['avg_confidence'] = sum(confidences) / len(confidences) if confidences else 0

            # Risk/PnL
            stats['total_risk_usd'] = sum([t.get('risk_amount_usd', 0) for t in closed_trades])

            # Realized P&L (sum of R multiples * risk per trade)
            pnl = sum([
                t.get('r_multiple', 0) * t.get('risk_amount_usd', 0)
                for t in closed_trades
            ])
            stats['realized_pnl_usd'] = round(pnl, 2)

            # Equity curve (running P&L)
            equity = 0
            for trade in closed_trades:
                equity += trade.get('r_multiple', 0) * trade.get('risk_amount_usd', 0)
                stats['equity_curve'].append({
                    'timestamp': trade.get('timestamp'),
                    'equity': round(equity, 2)
                })

            logger.info(f'Performance Stats: {stats["win_rate"]:.0%} WR, {stats["profit_factor"]:.2f} PF, {stats["avg_r_multiple"]:.2f}R avg')
            return stats

        except Exception as e:
            logger.error(f'Error calculating stats: {e}')
            return {}

    def store_stats_in_redis(self):
        """Store performance stats in Redis for dashboard access"""
        try:
            stats = self.calculate_performance_stats()
            self.redis_client.set(
                'trade_performance_stats',
                json.dumps(stats),
                ex=3600
            )
            logger.info('Performance stats stored in Redis')
            return stats
        except Exception as e:
            logger.error(f'Error storing stats: {e}')
            return {}

    def run(self):
        """Run tracker cycle"""
        logger.info('Running Trade Performance Tracker...')
        self.close_trades_at_tp_or_sl()
        stats = self.store_stats_in_redis()
        logger.info(f'Tracker cycle complete: {stats.get("closed_trades", 0)} closed trades, {stats.get("win_rate", 0):.0%} win rate')

if __name__ == '__main__':
    tracker = TradePerformanceTracker()
    tracker.run()
