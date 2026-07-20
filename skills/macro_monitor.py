#!/usr/bin/env python3
"""
Macro Analysis Monitor
Tracks market regime, volatility, sentiment, and macro conditions
Stores analysis for LLMs and trading decisions
"""

import json
import redis
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class MacroMonitor:
    def __init__(self):
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        self.analysis_key = 'macro:analysis'
        self.history_key = 'macro:history'

    def get_market_regime(self, btc_price, eth_price, btc_rsi_1h, btc_rsi_4h):
        """Determine current market regime: Bull/Bear/Range"""
        if btc_rsi_1h > 60 and btc_rsi_4h > 55:
            return {'regime': 'BULL', 'strength': 'Strong', 'confidence': 0.85}
        elif btc_rsi_1h < 40 and btc_rsi_4h < 45:
            return {'regime': 'BEAR', 'strength': 'Strong', 'confidence': 0.85}
        else:
            return {'regime': 'RANGE', 'strength': 'Neutral', 'confidence': 0.70}

    def get_volatility_regime(self, bb_upper, bb_lower, bb_basis):
        """Assess volatility: High/Normal/Low"""
        bb_width = bb_upper - bb_lower
        bb_pct = (bb_width / bb_basis) * 100 if bb_basis > 0 else 0

        if bb_pct > 8:
            return {'regime': 'HIGH', 'volatility_pct': bb_pct, 'label': '🔴 High Vol'}
        elif bb_pct < 3:
            return {'regime': 'LOW', 'volatility_pct': bb_pct, 'label': '🟢 Low Vol'}
        else:
            return {'regime': 'NORMAL', 'volatility_pct': bb_pct, 'label': '🟡 Normal Vol'}

    def get_sentiment(self, btc_rsi_1h, eth_rsi_1h):
        """Gauge market sentiment: Greed/Neutral/Fear"""
        avg_rsi = (btc_rsi_1h + eth_rsi_1h) / 2

        if avg_rsi > 70:
            return {'sentiment': 'GREED', 'label': '😈 Extreme Greed', 'score': avg_rsi}
        elif avg_rsi > 60:
            return {'sentiment': 'OPTIMISTIC', 'label': '😊 Optimistic', 'score': avg_rsi}
        elif avg_rsi < 30:
            return {'sentiment': 'FEAR', 'label': '😱 Extreme Fear', 'score': avg_rsi}
        elif avg_rsi < 40:
            return {'sentiment': 'PESSIMISTIC', 'label': '😟 Pessimistic', 'score': avg_rsi}
        else:
            return {'sentiment': 'NEUTRAL', 'label': '😐 Neutral', 'score': avg_rsi}

    def analyze(self):
        """Run macro analysis and store results"""
        try:
            # Fetch current price data
            btc_cache = self.redis_client.get('scanner:cache:BTC')
            eth_cache = self.redis_client.get('scanner:cache:ETH')

            if not btc_cache or not eth_cache:
                logger.warning('Price data not available')
                return

            btc_data = json.loads(btc_cache)
            eth_data = json.loads(eth_cache)

            btc_price = btc_data['data']['binance']['price']
            eth_price = eth_data['data']['binance']['price']

            btc_rsi_1h = btc_data['data']['ta']['1h']['rsi']
            btc_rsi_4h = btc_data['data']['ta']['4h']['rsi']
            eth_rsi_1h = eth_data['data']['ta']['1h']['rsi']

            btc_bb_1d = btc_data['data']['ta']['1d']

            # Run analyses
            regime = self.get_market_regime(btc_price, eth_price, btc_rsi_1h, btc_rsi_4h)
            volatility = self.get_volatility_regime(
                btc_bb_1d['bb_upper'], btc_bb_1d['bb_lower'], btc_bb_1d['bb_basis']
            )
            sentiment = self.get_sentiment(btc_rsi_1h, eth_rsi_1h)

            # Build macro analysis
            analysis = {
                'timestamp': datetime.utcnow().isoformat(),
                'market_regime': regime,
                'volatility': volatility,
                'sentiment': sentiment,
                'prices': {
                    'BTC': btc_price,
                    'ETH': eth_price,
                },
                'rsi_levels': {
                    'BTC_1h': btc_rsi_1h,
                    'BTC_4h': btc_rsi_4h,
                    'ETH_1h': eth_rsi_1h,
                },
                'summary': f"{regime['regime']} market with {volatility['regime']} volatility. {sentiment['label']}"
            }

            # Store in Redis
            self.redis_client.set(self.analysis_key, json.dumps(analysis))

            # Keep history (last 24 analyses)
            history = json.loads(self.redis_client.get(self.history_key) or '[]')
            history.append(analysis)
            history = history[-24:]  # Keep last 24
            self.redis_client.set(self.history_key, json.dumps(history))

            logger.info(f'Macro analysis: {analysis["summary"]}')
            return analysis

        except Exception as e:
            logger.error(f'Macro analysis error: {e}')
            return None

    def get_latest(self):
        """Get latest macro analysis"""
        data = self.redis_client.get(self.analysis_key)
        return json.loads(data) if data else None

    def get_history(self):
        """Get macro analysis history"""
        data = self.redis_client.get(self.history_key)
        return json.loads(data) if data else []


if __name__ == '__main__':
    monitor = MacroMonitor()
    analysis = monitor.analyze()
    if analysis:
        print(json.dumps(analysis, indent=2))
