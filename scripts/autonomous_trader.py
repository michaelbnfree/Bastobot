#!/usr/bin/env python3
"""
Barry Autonomous Trading Agent
Makes intelligent trade decisions based on market context using MarketContextTool
Runs every 10 minutes alongside macro analysis
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

# Risk Parameters
POSITION_RISK_PCT = float(os.getenv('POSITION_RISK_PCT', '2.0'))  # Risk 2% per trade
MAX_OPEN_POSITIONS = int(os.getenv('MAX_OPEN_POSITIONS', '3'))
USE_HYPERLIQUID = os.getenv('USE_HYPERLIQUID', 'false').lower() == 'true'

class AutonomousTrader:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        from skills.openclaw_market_context import MarketContextTool
        self.market_context = MarketContextTool()

    def get_trade_signal(self) -> dict | None:
        """Evaluate market conditions and generate trade signal"""
        try:
            macro = json.loads(self.redis_client.get('macro:analysis') or '{}')
            trends = json.loads(self.redis_client.get('trend:analysis') or '{}')
            snapshots = self.get_latest_snapshots()

            if not macro or not trends:
                logger.warning('Insufficient market data for trading decision')
                return None

            logger.info('Evaluating market conditions for trade signal...')

            # Get market context
            context = self.market_context.get_market_context()

            # Evaluate if we should trade
            should_trade = self._evaluate_trade_opportunity(context, macro, trends, snapshots)

            if not should_trade:
                logger.info('Market conditions not favorable for trading')
                return None

            # Generate trade signal
            signal = self._generate_trade_signal(context, macro, trends, snapshots)
            logger.info(f'Trade signal generated: {signal.get("action")} (confidence: {signal.get("confidence")})')

            return signal

        except Exception as e:
            logger.error(f'Failed to get trade signal: {e}')
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
            for line in lines[-5:]:  # Last 5 snapshots
                try:
                    snapshots.append(json.loads(line))
                except:
                    pass

            return snapshots
        except Exception as e:
            logger.error(f'Failed to read snapshots: {e}')
            return []

    def get_market_summary(self, macro: dict, trends: dict) -> str:
        """Build human-readable market summary"""
        return f"""
MARKET ANALYSIS SUMMARY:
- Regime: {macro.get('market_regime', {}).get('regime')} (confidence: {macro.get('market_regime', {}).get('confidence'):.0%})
- Volatility: {macro.get('volatility', {}).get('regime')} at {macro.get('volatility', {}).get('volatility_pct'):.2f}%
- Sentiment: {macro.get('sentiment', {}).get('sentiment')} (score: {macro.get('sentiment', {}).get('score'):.1f}/100)
- Trend Alignment: {trends.get('alignment', {}).get('alignment')} (confidence: {trends.get('alignment', {}).get('confidence'):.0%})

TIMEFRAME TRENDS:
- 1h: {trends.get('trends', {}).get('1h', {}).get('direction')}
- 4h: {trends.get('trends', {}).get('4h', {}).get('direction')}
- 1d: {trends.get('trends', {}).get('1d', {}).get('direction')}

TRADING PARAMETERS:
- Max concurrent positions: {MAX_OPEN_POSITIONS}
- Risk per trade: {POSITION_RISK_PCT}%
- Live mode: {'Hyperliquid' if USE_HYPERLIQUID else 'Paper trading'}
"""

    def _evaluate_trade_opportunity(self, context: dict, macro: dict, trends: dict, snapshots: list) -> bool:
        """Evaluate if current market conditions are favorable for trading"""
        if not context:
            return False

        # Check market regime
        regime = context.get('regime')
        regime_confidence = context.get('regime_confidence', 0)

        # Only trade in BULL or BEAR regimes with decent confidence
        favorable_regimes = ['BULL', 'BEAR']
        if regime not in favorable_regimes:
            logger.info(f'Market regime {regime} not favorable for trading')
            return False

        if regime_confidence < 0.5:
            logger.info(f'Regime confidence {regime_confidence} too low')
            return False

        # Check trend alignment
        alignment = context.get('trend_alignment')
        alignment_conf = context.get('alignment_confidence', 0)

        # Only trade with aligned or mixed-favorable trends
        acceptable_alignments = ['BULLISH', 'BEARISH', 'MIXED_BULLISH', 'MIXED_BEARISH']
        if alignment not in acceptable_alignments:
            logger.info(f'Trend alignment {alignment} not favorable')
            return False

        if alignment_conf < 0.3:
            logger.info(f'Alignment confidence {alignment_conf} too low')
            return False

        # Check sentiment is not at extremes (too greedy or fearful)
        sentiment = context.get('sentiment')
        sentiment_score = context.get('sentiment_score', 50)

        if sentiment_score < 20 or sentiment_score > 80:
            logger.info(f'Sentiment at extreme ({sentiment}: {sentiment_score}) - too risky')
            return False

        logger.info(f'Market conditions favorable: {regime} (confidence: {regime_confidence}), Alignment: {alignment} ({alignment_conf})')
        return True

    def _generate_trade_signal(self, context: dict, macro: dict, trends: dict, snapshots: list) -> dict:
        """Generate specific trade signal based on market conditions"""
        regime = context.get('regime', 'RANGE')
        alignment = context.get('trend_alignment', 'CONFLICTED')

        action = 'LONG' if regime == 'BULL' else 'SHORT' if regime == 'BEAR' else 'SKIP'
        confidence = max(
            context.get('regime_confidence', 0.5),
            context.get('alignment_confidence', 0.3)
        )

        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': action,
            'regime': regime,
            'alignment': alignment,
            'confidence': confidence,
            'reasoning': f'{regime} market with {alignment} trends, confidence: {confidence:.2%}'
        }

    def execute_trade(self, decision: dict) -> bool:
        """Execute trade decision"""
        try:
            action = decision.get('action')
            if action == 'SKIP':
                logger.info('No trade action - market conditions not favorable')
                return False

            logger.info(f'Executing {action} trade...')

            if USE_HYPERLIQUID:
                return self._execute_hyperliquid_trade(decision)
            else:
                return self._log_paper_trade(decision)

        except Exception as e:
            logger.error(f'Trade execution failed: {e}')
            return False

    def _execute_hyperliquid_trade(self, decision: dict) -> bool:
        """Execute trade on Hyperliquid (when enabled)"""
        logger.info('Hyperliquid trading not yet configured')
        return False

    def _log_paper_trade(self, decision: dict) -> bool:
        """Log paper trade for backtesting and analysis"""
        try:
            trade_log = {
                'timestamp': decision.get('timestamp'),
                'action': decision.get('action'),
                'regime': decision.get('regime'),
                'alignment': decision.get('alignment'),
                'confidence': decision.get('confidence'),
                'reasoning': decision.get('reasoning'),
                'status': 'PAPER_TRADE'
            }

            # Log to file
            with open('/root/bastobot/autonomous_trades.jsonl', 'a') as f:
                f.write(json.dumps(trade_log) + '\n')

            # Store in Redis for dashboard
            self.redis_client.set(
                'last_trade_decision',
                json.dumps(trade_log),
                ex=3600
            )

            # Log to Notion for audit trail
            self._log_to_notion(trade_log)

            logger.info(f'Paper trade logged: {trade_log["action"]} (confidence: {trade_log["confidence"]:.0%})')
            return True

        except Exception as e:
            logger.error(f'Failed to log paper trade: {e}')
            return False

    def _log_to_notion(self, trade_log: dict) -> None:
        """Log autonomous trade decision to Notion"""
        try:
            import requests
            from datetime import datetime

            api_key = os.getenv('NOTION_API_KEY')
            db_id = os.getenv('NOTION_MACRO_DB_ID')

            if not api_key or not db_id:
                logger.debug('Notion credentials not configured for trade logging')
                return

            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'Notion-Version': '2022-06-28',
            }

            payload = {
                'parent': {'database_id': db_id},
                'properties': {
                    'Name': {
                        'title': [{
                            'text': {'content': f"Trade Signal - {trade_log.get('action')}"}
                        }]
                    },
                    'Timestamp': {
                        'date': {'start': datetime.fromisoformat(trade_log['timestamp']).date().isoformat()}
                    },
                    'Market Regime': {
                        'select': {'name': trade_log.get('regime', 'UNKNOWN')}
                    },
                    'Trend Alignment': {
                        'select': {'name': trade_log.get('alignment', 'UNKNOWN')}
                    },
                    'Sentiment': {
                        'select': {'name': 'NEUTRAL'}  # Placeholder
                    },
                    'Summary': {
                        'rich_text': [{
                            'text': {
                                'content': f"Action: {trade_log.get('action')}\nConfidence: {trade_log.get('confidence'):.0%}\nReasoning: {trade_log.get('reasoning')}"[:2000]
                            }
                        }]
                    }
                }
            }

            response = requests.post(
                'https://api.notion.com/v1/pages',
                headers=headers,
                json=payload,
                timeout=10
            )

            if response.status_code == 200:
                logger.debug('Trade decision logged to Notion')
            else:
                logger.warning(f'Failed to log to Notion: {response.status_code}')

        except Exception as e:
            logger.debug(f'Notion logging error (non-critical): {e}')

    def run(self):
        """Main autonomous trading loop"""
        logger.info('Starting Barry Autonomous Trader...')

        signal = self.get_trade_signal()
        if signal:
            self.execute_trade(signal)
            logger.info('Trade cycle complete')
        else:
            logger.info('No trade signal generated')

if __name__ == '__main__':
    trader = AutonomousTrader()
    trader.run()
