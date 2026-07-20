#!/usr/bin/env python3
"""
OpenClaw Market Context Tool
Provides intelligent market analysis for autonomous trading decisions
"""

import json
import redis
import logging

logger = logging.getLogger(__name__)

class MarketContextTool:
    def __init__(self):
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

    def get_market_context(self) -> dict:
        """Get complete market analysis for decision-making"""
        try:
            macro = json.loads(self.redis_client.get('macro:analysis') or '{}')
            trends = json.loads(self.redis_client.get('trend:analysis') or '{}')

            return {
                'regime': macro.get('market_regime', {}).get('regime'),
                'regime_confidence': macro.get('market_regime', {}).get('confidence'),
                'volatility': macro.get('volatility', {}).get('regime'),
                'sentiment': macro.get('sentiment', {}).get('sentiment'),
                'sentiment_score': macro.get('sentiment', {}).get('score'),
                'trend_alignment': trends.get('alignment', {}).get('alignment'),
                'alignment_confidence': trends.get('alignment', {}).get('confidence'),
                'timeframes': trends.get('trends', {}),
                'divergences': trends.get('divergences', []),
            }
        except Exception as e:
            logger.error(f'Failed to get market context: {e}')
            return {}

    def should_trade_setup(self, setup_direction: str = 'LONG') -> dict:
        """
        Evaluate if a setup should be traded based on market conditions.

        Args:
            setup_direction: 'LONG', 'SHORT', or 'NEUTRAL'

        Returns:
            {
                'should_trade': bool,
                'confidence': float (0-1),
                'reason': str,
                'adjustments': dict
            }
        """
        context = self.get_market_context()

        if not context:
            return {
                'should_trade': False,
                'confidence': 0,
                'reason': 'No market data available',
                'adjustments': {}
            }

        regime = context.get('regime')
        alignment = context.get('trend_alignment')
        volatility = context.get('volatility')
        sentiment = context.get('sentiment')
        divergences = context.get('divergences', [])

        # Check for active divergences (warning sign)
        has_divergence = any(d.get('type') != 'None' for d in divergences)

        # Trading logic
        should_trade = False
        confidence = 0
        reason = ""
        adjustments = {'position_size_multiplier': 1.0, 'take_profit_tighter': False}

        # LONG Setup Logic
        if setup_direction == 'LONG':
            if regime == 'BULL' and 'BULLISH' in alignment:
                # Perfect alignment
                should_trade = True
                confidence = 0.9
                reason = 'Perfect bullish alignment (BULL regime + BULLISH trends)'

                # Adjust for sentiment
                if sentiment in ['GREED', 'OPTIMISTIC']:
                    confidence = min(0.95, confidence + 0.05)
                elif sentiment in ['FEAR', 'PESSIMISTIC']:
                    confidence = max(0.7, confidence - 0.2)

            elif regime == 'BULL' and 'MIXED_BULLISH' in alignment:
                # Partial alignment
                should_trade = True
                confidence = 0.65
                reason = 'Mixed bullish alignment (BULL regime but mixed trends)'
                adjustments['position_size_multiplier'] = 0.75

            elif regime == 'RANGE' and 'MIXED_BULLISH' in alignment:
                # Weak alignment
                should_trade = True
                confidence = 0.45
                reason = 'Weak bullish alignment (RANGE regime + mixed trends)'
                adjustments['position_size_multiplier'] = 0.5
                adjustments['take_profit_tighter'] = True

            elif regime == 'BEAR' or 'BEARISH' in alignment:
                # Counter-trend trade
                should_trade = False
                confidence = 0.2
                reason = 'Counter-trend setup (BEAR regime, low probability)'

        # SHORT Setup Logic
        elif setup_direction == 'SHORT':
            if regime == 'BEAR' and 'BEARISH' in alignment:
                # Perfect alignment
                should_trade = True
                confidence = 0.9
                reason = 'Perfect bearish alignment (BEAR regime + BEARISH trends)'

                if sentiment in ['FEAR', 'PESSIMISTIC']:
                    confidence = min(0.95, confidence + 0.05)
                elif sentiment in ['GREED', 'OPTIMISTIC']:
                    confidence = max(0.7, confidence - 0.2)

            elif regime == 'BEAR' and 'MIXED_BEARISH' in alignment:
                # Partial alignment
                should_trade = True
                confidence = 0.65
                reason = 'Mixed bearish alignment (BEAR regime but mixed trends)'
                adjustments['position_size_multiplier'] = 0.75

            elif regime == 'RANGE' and 'MIXED_BEARISH' in alignment:
                # Weak alignment
                should_trade = True
                confidence = 0.45
                reason = 'Weak bearish alignment (RANGE regime + mixed trends)'
                adjustments['position_size_multiplier'] = 0.5
                adjustments['take_profit_tighter'] = True

            elif regime == 'BULL' or 'BULLISH' in alignment:
                # Counter-trend trade
                should_trade = False
                confidence = 0.2
                reason = 'Counter-trend setup (BULL regime, low probability)'

        # Volatility adjustments
        if volatility == 'HIGH':
            adjustments['position_size_multiplier'] *= 0.8  # Reduce size in high vol
            adjustments['stop_loss_wider'] = True
        elif volatility == 'LOW':
            adjustments['position_size_multiplier'] *= 1.2  # Slightly larger in low vol

        # Divergence warning
        if has_divergence and should_trade:
            confidence *= 0.85  # Reduce confidence if divergence detected
            adjustments['watch_for_early_exit'] = True

        return {
            'should_trade': should_trade and confidence > 0.4,
            'confidence': min(1.0, confidence),
            'reason': reason,
            'adjustments': adjustments,
            'market_context': {
                'regime': regime,
                'alignment': alignment,
                'volatility': volatility,
                'sentiment': sentiment,
            }
        }

    def get_position_sizing(self, base_size: float, setup_direction: str = 'LONG') -> dict:
        """
        Calculate position size based on market conditions.

        Args:
            base_size: Base position size (e.g., 0.1 BTC)
            setup_direction: 'LONG' or 'SHORT'

        Returns:
            {
                'sized_position': float,
                'reasoning': str,
                'risk_level': str
            }
        """
        decision = self.should_trade_setup(setup_direction)

        if not decision['should_trade']:
            return {
                'sized_position': 0,
                'reasoning': 'Setup should not be traded',
                'risk_level': 'SKIP'
            }

        multiplier = decision['adjustments'].get('position_size_multiplier', 1.0)
        sized = base_size * multiplier * decision['confidence']

        # Risk level assessment
        if decision['confidence'] > 0.85:
            risk_level = 'LOW_RISK'
        elif decision['confidence'] > 0.65:
            risk_level = 'MODERATE_RISK'
        else:
            risk_level = 'HIGH_RISK'

        return {
            'sized_position': round(sized, 6),
            'reasoning': f"Base: {base_size}, Multiplier: {multiplier:.2f}x, Confidence: {decision['confidence']:.0%}",
            'risk_level': risk_level,
            'adjustments': decision['adjustments']
        }

    def get_exit_signal_context(self) -> dict:
        """
        Provide context for exit decision-making.
        """
        context = self.get_market_context()
        divergences = context.get('divergences', [])

        exit_signals = {
            'has_divergence': any(d.get('type') != 'None' for d in divergences),
            'divergences': [d for d in divergences if d.get('type') != 'None'],
            'trend_reversal': False,
            'volatility_spike': context.get('volatility') == 'HIGH',
            'sentiment_extreme': context.get('sentiment') in ['GREED', 'FEAR']
        }

        return {
            'exit_signals': exit_signals,
            'watch_for_reversal': any(exit_signals.values()),
            'context': context
        }


# Standalone usage for OpenClaw integration
if __name__ == '__main__':
    tool = MarketContextTool()

    print("\n=== Market Context ===")
    context = tool.get_market_context()
    print(json.dumps(context, indent=2))

    print("\n=== Long Setup Evaluation ===")
    long_eval = tool.should_trade_setup('LONG')
    print(json.dumps(long_eval, indent=2))

    print("\n=== Position Sizing (0.1 BTC Long) ===")
    sizing = tool.get_position_sizing(0.1, 'LONG')
    print(json.dumps(sizing, indent=2))

    print("\n=== Exit Signal Context ===")
    exit_context = tool.get_exit_signal_context()
    print(json.dumps(exit_context, indent=2))
