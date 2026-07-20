#!/usr/bin/env python3
"""
Trend Monitor
Tracks multi-timeframe trends, divergences, momentum, and support/resistance
"""

import json
import redis
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TrendMonitor:
    def __init__(self):
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        self.trends_key = 'trend:analysis'

    def analyze_trend(self, rsi_1h, rsi_4h, rsi_1d, bb_basis_1h, bb_basis_4h):
        """Analyze trend across timeframes"""
        trends = {}

        # 1H Trend
        if rsi_1h > 60:
            trends['1h'] = {'direction': 'UP', 'strength': 'Strong' if rsi_1h > 70 else 'Moderate', 'emoji': '📈'}
        elif rsi_1h < 40:
            trends['1h'] = {'direction': 'DOWN', 'strength': 'Strong' if rsi_1h < 30 else 'Moderate', 'emoji': '📉'}
        else:
            trends['1h'] = {'direction': 'CONSOLIDATING', 'strength': 'Weak', 'emoji': '↔️'}

        # 4H Trend
        if rsi_4h > 60:
            trends['4h'] = {'direction': 'UP', 'strength': 'Strong' if rsi_4h > 70 else 'Moderate', 'emoji': '📈'}
        elif rsi_4h < 40:
            trends['4h'] = {'direction': 'DOWN', 'strength': 'Strong' if rsi_4h < 30 else 'Moderate', 'emoji': '📉'}
        else:
            trends['4h'] = {'direction': 'CONSOLIDATING', 'strength': 'Weak', 'emoji': '↔️'}

        # 1D Trend
        if rsi_1d > 60:
            trends['1d'] = {'direction': 'UP', 'strength': 'Strong' if rsi_1d > 70 else 'Moderate', 'emoji': '📈'}
        elif rsi_1d < 40:
            trends['1d'] = {'direction': 'DOWN', 'strength': 'Strong' if rsi_1d < 30 else 'Moderate', 'emoji': '📉'}
        else:
            trends['1d'] = {'direction': 'CONSOLIDATING', 'strength': 'Weak', 'emoji': '↔️'}

        return trends

    def check_alignment(self, trends):
        """Check if trends are aligned across timeframes"""
        directions = [t['direction'] for t in trends.values()]

        if all(d == 'UP' for d in directions):
            return {'aligned': True, 'alignment': 'BULLISH', 'emoji': '🟢', 'confidence': 0.9}
        elif all(d == 'DOWN' for d in directions):
            return {'aligned': True, 'alignment': 'BEARISH', 'emoji': '🔴', 'confidence': 0.9}
        elif directions.count('UP') > directions.count('DOWN'):
            return {'aligned': False, 'alignment': 'MIXED_BULLISH', 'emoji': '🟡', 'confidence': 0.6}
        elif directions.count('DOWN') > directions.count('UP'):
            return {'aligned': False, 'alignment': 'MIXED_BEARISH', 'emoji': '🟡', 'confidence': 0.6}
        else:
            return {'aligned': False, 'alignment': 'CONFLICTED', 'emoji': '⚠️', 'confidence': 0.3}

    def check_divergence(self, rsi_1h, rsi_4h, rsi_1d):
        """Check for momentum divergences"""
        divergences = []

        # 1H vs 4H divergence
        if (rsi_1h > 60 and rsi_4h < 40):
            divergences.append({'type': 'Bullish Divergence', 'tf': '1h vs 4h', 'risk': 'High'})
        elif (rsi_1h < 40 and rsi_4h > 60):
            divergences.append({'type': 'Bearish Divergence', 'tf': '1h vs 4h', 'risk': 'High'})

        # 4H vs 1D divergence
        if (rsi_4h > 60 and rsi_1d < 40):
            divergences.append({'type': 'Bullish Divergence', 'tf': '4h vs 1d', 'risk': 'Medium'})
        elif (rsi_4h < 40 and rsi_1d > 60):
            divergences.append({'type': 'Bearish Divergence', 'tf': '4h vs 1d', 'risk': 'Medium'})

        return divergences if divergences else [{'type': 'None', 'risk': 'None'}]

    def analyze(self):
        """Run trend analysis and store results"""
        try:
            # Fetch current data
            btc_cache = self.redis_client.get('scanner:cache:BTC')
            if not btc_cache:
                logger.warning('BTC data not available')
                return

            btc_data = json.loads(btc_cache)
            ta = btc_data['data']['ta']

            rsi_1h = ta['1h']['rsi']
            rsi_4h = ta['4h']['rsi']
            rsi_1d = ta['1d']['rsi']
            bb_basis_1h = ta['1h']['bb_basis']
            bb_basis_4h = ta['4h']['bb_basis']

            # Analyze trends
            trends = self.analyze_trend(rsi_1h, rsi_4h, rsi_1d, bb_basis_1h, bb_basis_4h)
            alignment = self.check_alignment(trends)
            divergences = self.check_divergence(rsi_1h, rsi_4h, rsi_1d)

            # Build analysis
            analysis = {
                'timestamp': datetime.utcnow().isoformat(),
                'trends': trends,
                'alignment': alignment,
                'divergences': divergences,
                'summary': f"{alignment['emoji']} {alignment['alignment']} - 1h {trends['1h']['emoji']}, 4h {trends['4h']['emoji']}, 1d {trends['1d']['emoji']}"
            }

            # Store in Redis
            self.redis_client.set(self.trends_key, json.dumps(analysis))

            logger.info(f'Trend analysis: {analysis["summary"]}')
            return analysis

        except Exception as e:
            logger.error(f'Trend analysis error: {e}')
            return None

    def get_latest(self):
        """Get latest trend analysis"""
        data = self.redis_client.get(self.trends_key)
        return json.loads(data) if data else None


if __name__ == '__main__':
    monitor = TrendMonitor()
    analysis = monitor.analyze()
    if analysis:
        print(json.dumps(analysis, indent=2))
