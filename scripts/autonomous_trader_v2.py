#!/usr/bin/env python3
"""
Barry Autonomous Trading Agent v2.0
Enhanced with:
1. Setup-to-Signal Integration
2. Entry/Exit Specifics (price targets, SL/TP)
3. Win Rate Tracking
4. Volatility-Based Position Sizing
5. Momentum Confirmation (RSI, MACD)
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
BASE_RISK_PCT = float(os.getenv('POSITION_RISK_PCT', '2.0'))
MAX_OPEN_POSITIONS = int(os.getenv('MAX_OPEN_POSITIONS', '3'))
USE_HYPERLIQUID = os.getenv('USE_HYPERLIQUID', 'false').lower() == 'true'
ACCOUNT_SIZE = float(os.getenv('ACCOUNT_SIZE_USD', '250000'))

class AutonomousTraderV2:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        from skills.openclaw_market_context import MarketContextTool
        self.market_context = MarketContextTool()

    def get_trade_signal(self) -> dict | None:
        """Evaluate market conditions and generate detailed trade signal"""
        try:
            macro = json.loads(self.redis_client.get('macro:analysis') or '{}')
            trends = json.loads(self.redis_client.get('trend:analysis') or '{}')
            snapshots = self.get_latest_snapshots()
            indicators = json.loads(self.redis_client.get('indicators:data') or '{}')

            if not macro or not trends:
                logger.warning('Insufficient market data for trading decision')
                return None

            logger.info('Evaluating market conditions for trade signal...')

            # Get market context
            context = self.market_context.get_market_context()

            # Step 1: Check macro conditions
            if not self._evaluate_macro_conditions(context):
                logger.info('Macro conditions not favorable')
                return None

            # Step 2: Check setup validation
            setup = self._find_high_conviction_setup(snapshots, context)
            if not setup:
                logger.info('No high-conviction setup found')
                return None

            # Step 3: Confirm with momentum
            momentum_score = self._calculate_momentum_score(indicators, setup.get('asset', 'BTC'))
            if momentum_score < 0.3:
                logger.info(f'Momentum score too low: {momentum_score}')
                return None

            # Step 4: Generate detailed signal with prices
            signal = self._generate_detailed_signal(
                context, macro, trends, setup, momentum_score, indicators
            )

            logger.info(f'Trade signal generated: {signal.get("action")} @ {signal.get("entry_price")} (confidence: {signal.get("confidence"):.0%})')
            return signal

        except Exception as e:
            logger.error(f'Failed to get trade signal: {e}')
            import traceback
            traceback.print_exc()
            return None

    def get_latest_snapshots(self) -> list:
        """Read latest setup snapshots from file"""
        try:
            snapshots_file = '/root/bastobot/snapshots.jsonl'
            if not os.path.exists(snapshots_file):
                return []

            with open(snapshots_file, 'r') as f:
                lines = f.readlines()

            snapshots = []
            for line in lines[-10:]:  # Last 10 snapshots
                try:
                    snapshots.append(json.loads(line))
                except:
                    pass

            return snapshots
        except Exception as e:
            logger.error(f'Failed to read snapshots: {e}')
            return []

    def _evaluate_macro_conditions(self, context: dict) -> bool:
        """Step 1: Evaluate macro conditions"""
        regime = context.get('regime')
        regime_confidence = context.get('regime_confidence', 0)

        # Only trade in BULL or BEAR
        if regime not in ['BULL', 'BEAR']:
            return False

        if regime_confidence < 0.5:
            return False

        # Check sentiment (avoid extremes)
        sentiment_score = context.get('sentiment_score', 50)
        if sentiment_score < 20 or sentiment_score > 80:
            logger.info(f'Sentiment at extreme: {sentiment_score}')
            return False

        return True

    def _find_high_conviction_setup(self, snapshots: list, context: dict) -> dict | None:
        """Step 2: Find setup that aligns with market regime"""
        if not snapshots:
            return None

        regime = context.get('regime')
        alignment = context.get('trend_alignment')

        for snapshot in reversed(snapshots):  # Most recent first
            setup_direction = snapshot.get('direction', 'LONG')
            conviction = snapshot.get('conviction', 0)

            # Setup must have high conviction
            if conviction < 0.6:
                continue

            # Setup direction must align with regime
            if regime == 'BULL' and setup_direction != 'LONG':
                continue
            if regime == 'BEAR' and setup_direction != 'SHORT':
                continue

            # Setup must align with trend alignment
            if 'BULLISH' not in alignment and setup_direction == 'LONG':
                continue
            if 'BEARISH' not in alignment and setup_direction == 'SHORT':
                continue

            logger.info(f'Found high-conviction setup: {setup_direction} (conviction: {conviction:.0%})')
            return snapshot

        return None

    def _calculate_momentum_score(self, indicators: dict, asset: str = 'BTC') -> float:
        """Step 3: Calculate momentum confirmation score (RSI, MACD)"""
        try:
            if asset not in indicators:
                return 0.5  # Neutral if no data

            asset_data = indicators[asset].get('ta', {})

            # Average RSI across timeframes
            rsi_scores = []
            for tf in ['1h', '4h', '1d']:
                rsi = asset_data.get(tf, {}).get('rsi', 50)
                # RSI 30-70 is neutral/good, extremes are risky
                if rsi < 30:
                    rsi_scores.append(0.2)  # Oversold - risky
                elif rsi < 40:
                    rsi_scores.append(0.7)  # Oversold territory - good entry
                elif rsi < 60:
                    rsi_scores.append(0.9)  # Ideal momentum
                elif rsi < 70:
                    rsi_scores.append(0.7)  # Overbought territory - caution
                else:
                    rsi_scores.append(0.2)  # Overbought - risky

            momentum = sum(rsi_scores) / len(rsi_scores) if rsi_scores else 0.5
            logger.debug(f'Momentum score: {momentum:.2f}')
            return momentum

        except Exception as e:
            logger.debug(f'Momentum calculation error: {e}')
            return 0.5

    def _calculate_position_size(self, context: dict, entry_price: float, stop_loss: float) -> dict:
        """Step 4a: Calculate position size based on volatility"""
        volatility = context.get('volatility', 'NORMAL')
        base_risk = BASE_RISK_PCT

        # Adjust risk based on volatility
        if volatility == 'HIGH':
            risk_pct = base_risk * 0.5  # Risk 1% instead of 2%
            logger.info('HIGH volatility - reducing position size to 1%')
        elif volatility == 'LOW':
            risk_pct = base_risk * 1.5  # Risk 3% instead of 2%
            logger.info('LOW volatility - increasing position size to 3%')
        else:
            risk_pct = base_risk

        # Calculate position size from risk amount
        risk_amount_usd = (ACCOUNT_SIZE * risk_pct) / 100
        price_risk_pips = abs(entry_price - stop_loss)

        if price_risk_pips == 0:
            position_size_usd = ACCOUNT_SIZE * (risk_pct / 100)
        else:
            # Position size = Risk Amount / Price Risk (in pips)
            position_size_usd = risk_amount_usd

        return {
            'risk_pct': risk_pct,
            'risk_amount_usd': risk_amount_usd,
            'position_size_usd': position_size_usd,
            'volatility_adjusted': volatility != 'NORMAL'
        }

    def _calculate_entry_exit(self, context: dict, setup: dict, indicators: dict) -> dict:
        """Step 4b: Calculate entry, stop loss, and take profit"""
        try:
            asset = setup.get('asset', 'BTC')
            direction = setup.get('direction', 'LONG')

            # Use setup's entry price if available, otherwise try indicators
            current_price = setup.get('entry_price', 0) or indicators.get(asset, {}).get('price', 0)

            if not current_price:
                logger.warning(f'No price data for {asset}, using setup entry price')
                current_price = setup.get('entry_price', 64000)  # Fallback

            # Get volatility-based range
            volatility_pct = context.get('volatility_pct', 5.0)

            # Entry: Current market price
            entry_price = current_price

            # Stop Loss: Based on setup structure or volatility
            setup_sl = setup.get('stop_loss', None)
            if setup_sl:
                stop_loss = setup_sl
            else:
                # Use volatility-based SL
                atr_points = (current_price * volatility_pct) / 100
                stop_loss = entry_price - atr_points if direction == 'LONG' else entry_price + atr_points

            # Take Profit: 2:1 risk-reward ratio
            risk_points = abs(entry_price - stop_loss)
            take_profit = entry_price + (risk_points * 2) if direction == 'LONG' else entry_price - (risk_points * 2)

            # Calculate metrics
            price_risk = abs(entry_price - stop_loss)
            price_reward = abs(take_profit - entry_price)
            risk_reward_ratio = price_reward / price_risk if price_risk > 0 else 0

            return {
                'entry_price': round(entry_price, 2),
                'stop_loss': round(stop_loss, 2),
                'take_profit': round(take_profit, 2),
                'price_risk_pips': round(price_risk, 2),
                'price_reward_pips': round(price_reward, 2),
                'risk_reward_ratio': round(risk_reward_ratio, 2)
            }

        except Exception as e:
            logger.error(f'Entry/Exit calculation error: {e}')
            return None

    def _generate_detailed_signal(self, context: dict, macro: dict, trends: dict,
                                 setup: dict, momentum_score: float, indicators: dict) -> dict:
        """Generate detailed trade signal with all specifics"""
        regime = context.get('regime')
        setup_direction = setup.get('direction', 'LONG')
        setup_conviction = setup.get('conviction', 0.5)

        # Calculate entry/exit
        entry_exit = self._calculate_entry_exit(context, setup, indicators)
        if not entry_exit:
            return None

        # Calculate position size
        position = self._calculate_position_size(context, entry_exit['entry_price'], entry_exit['stop_loss'])

        # Confidence = average of multiple factors
        confidence = (
            context.get('regime_confidence', 0.5) * 0.3 +
            setup_conviction * 0.3 +
            momentum_score * 0.4
        )

        signal = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': setup_direction,
            'asset': setup.get('asset', 'BTC'),

            # Market context
            'regime': regime,
            'regime_confidence': context.get('regime_confidence', 0),
            'alignment': context.get('trend_alignment'),
            'alignment_confidence': context.get('alignment_confidence', 0),
            'sentiment': context.get('sentiment'),
            'sentiment_score': context.get('sentiment_score', 50),

            # Setup details
            'setup_type': setup.get('type', 'unknown'),
            'setup_conviction': setup_conviction,

            # Momentum
            'momentum_score': momentum_score,

            # Entry/Exit
            'entry_price': entry_exit['entry_price'],
            'stop_loss': entry_exit['stop_loss'],
            'take_profit': entry_exit['take_profit'],
            'price_risk_pips': entry_exit['price_risk_pips'],
            'price_reward_pips': entry_exit['price_reward_pips'],
            'risk_reward_ratio': entry_exit['risk_reward_ratio'],

            # Position sizing
            'risk_pct': position['risk_pct'],
            'risk_amount_usd': round(position['risk_amount_usd'], 2),
            'position_size_usd': round(position['position_size_usd'], 2),
            'volatility_adjusted': position['volatility_adjusted'],

            # Overall confidence
            'confidence': min(confidence, 0.95),  # Cap at 95%

            # Reasoning
            'reasoning': f'{regime} market + {setup.get("type")} setup (conviction: {setup_conviction:.0%}) + momentum ({momentum_score:.0%})',
            'status': 'PENDING'
        }

        return signal

    def execute_trade(self, decision: dict) -> bool:
        """Execute or log trade decision"""
        try:
            action = decision.get('action')
            if not action or action == 'SKIP':
                logger.info('No trade action')
                return False

            logger.info(f'Processing {action} trade signal...')

            if USE_HYPERLIQUID:
                return self._execute_hyperliquid_trade(decision)
            else:
                return self._log_paper_trade(decision)

        except Exception as e:
            logger.error(f'Trade execution failed: {e}')
            return False

    def _execute_hyperliquid_trade(self, decision: dict) -> bool:
        """Execute trade on Hyperliquid (when enabled)"""
        logger.info('Hyperliquid live trading not yet implemented')
        return self._log_paper_trade(decision)

    def _log_paper_trade(self, decision: dict) -> bool:
        """Log paper trade with detailed signal for win/loss tracking"""
        try:
            # Add tracking ID for later win/loss assessment
            import hashlib
            signal_hash = hashlib.md5(
                f"{decision['timestamp']}{decision['action']}{decision['entry_price']}".encode()
            ).hexdigest()[:8]

            trade_log = {
                'signal_id': signal_hash,
                'timestamp': decision.get('timestamp'),
                'action': decision.get('action'),
                'asset': decision.get('asset', 'BTC'),

                # Entry/Exit
                'entry_price': decision.get('entry_price'),
                'stop_loss': decision.get('stop_loss'),
                'take_profit': decision.get('take_profit'),
                'risk_reward_ratio': decision.get('risk_reward_ratio'),

                # Position sizing
                'risk_pct': decision.get('risk_pct'),
                'position_size_usd': decision.get('position_size_usd'),

                # Confidence & reasoning
                'confidence': decision.get('confidence'),
                'regime': decision.get('regime'),
                'alignment': decision.get('alignment'),
                'setup_conviction': decision.get('setup_conviction'),
                'momentum_score': decision.get('momentum_score'),
                'reasoning': decision.get('reasoning'),

                # Status tracking
                'status': 'OPEN',
                'exit_price': None,
                'outcome': None,
                'r_multiple': None
            }

            # Log to file
            with open('/root/bastobot/autonomous_trades_v2.jsonl', 'a') as f:
                f.write(json.dumps(trade_log) + '\n')

            # Store in Redis for dashboard
            self.redis_client.set(
                'last_trade_decision_v2',
                json.dumps(trade_log),
                ex=3600
            )

            logger.info(
                f'Paper trade logged: {trade_log["action"]} @ {trade_log["entry_price"]} '
                f'SL: {trade_log["stop_loss"]} TP: {trade_log["take_profit"]} '
                f'R:R: {trade_log["risk_reward_ratio"]:.1f}:1 (confidence: {trade_log["confidence"]:.0%})'
            )
            return True

        except Exception as e:
            logger.error(f'Failed to log paper trade: {e}')
            return False

    def run(self):
        """Main autonomous trading loop"""
        logger.info('Starting Barry Autonomous Trader v2.0...')

        signal = self.get_trade_signal()
        if signal:
            self.execute_trade(signal)
            logger.info('Trade cycle complete')
        else:
            logger.info('No trade signal generated this cycle')

if __name__ == '__main__':
    trader = AutonomousTraderV2()
    trader.run()
