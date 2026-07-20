#!/usr/bin/env python3
"""
Market Context API for LLM Integration
Provides macro analysis, trends, and setup context for decision-making
"""

import json
import redis
from flask import Flask, jsonify

app = Flask(__name__)
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

@app.route('/api/market-context', methods=['GET'])
def get_market_context():
    """Get complete market context for LLM decision-making"""
    try:
        # Fetch all relevant data
        macro = json.loads(redis_client.get('macro:analysis') or '{}')
        trends = json.loads(redis_client.get('trend:analysis') or '{}')
        trades = json.loads(redis_client.get('trade_monitor:list') or '[]')

        # Build context for LLM
        context = {
            'timestamp': macro.get('timestamp'),
            'market_regime': macro.get('market_regime'),
            'volatility': macro.get('volatility'),
            'sentiment': macro.get('sentiment'),
            'trends': trends.get('trends'),
            'alignment': trends.get('alignment'),
            'divergences': trends.get('divergences'),
            'active_trades': len(trades),
            'summary': {
                'macro': macro.get('summary'),
                'trends': trends.get('summary'),
            }
        }

        return jsonify(context)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/market-summary', methods=['GET'])
def get_market_summary():
    """Get brief market summary for quick LLM context"""
    try:
        macro = json.loads(redis_client.get('macro:analysis') or '{}')
        trends = json.loads(redis_client.get('trend:analysis') or '{}')

        summary = f"""
MARKET STATUS:
- Regime: {macro.get('market_regime', {}).get('regime')} ({macro.get('market_regime', {}).get('strength')})
- Volatility: {macro.get('volatility', {}).get('label')}
- Sentiment: {macro.get('sentiment', {}).get('label')}
- Trend Alignment: {trends.get('alignment', {}).get('alignment')} {trends.get('alignment', {}).get('emoji')}
- Timeframes: 1h {trends.get('trends', {}).get('1h', {}).get('emoji')} | 4h {trends.get('trends', {}).get('4h', {}).get('emoji')} | 1d {trends.get('trends', {}).get('1d', {}).get('emoji')}

RECOMMENDATION CONTEXT:
- Consider current market regime when evaluating setup
- Check for timeframe alignment before entry
- Monitor divergences for exit signals
- Respect volatility regime for position sizing
"""

        return jsonify({'summary': summary.strip()})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001)
