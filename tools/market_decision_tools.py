#!/usr/bin/env python3
"""
OpenClaw Tools - Market Decision Tools
Callable tools for OpenClaw autonomous agent to use in trading decisions
"""

import sys
sys.path.insert(0, '/root/bastobot')

from skills.openclaw_market_context import MarketContextTool
import json

tool = MarketContextTool()

# Tool definitions for OpenClaw
TOOLS = [
    {
        "name": "get_market_context",
        "description": "Get current market regime, volatility, sentiment, and trend alignment. Use this to understand market conditions before making trading decisions.",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "handler": lambda **kwargs: tool.get_market_context()
    },
    {
        "name": "evaluate_setup",
        "description": "Evaluate if a trading setup should be executed based on current market conditions. Returns confidence level and position sizing recommendations.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["LONG", "SHORT"],
                    "description": "Direction of the proposed trade"
                }
            },
            "required": ["direction"]
        },
        "handler": lambda direction: tool.should_trade_setup(direction)
    },
    {
        "name": "calculate_position_size",
        "description": "Calculate optimal position size based on market conditions, risk, and setup confidence.",
        "parameters": {
            "type": "object",
            "properties": {
                "base_size": {
                    "type": "number",
                    "description": "Base position size in the asset (e.g., 0.1 for BTC)"
                },
                "direction": {
                    "type": "string",
                    "enum": ["LONG", "SHORT"],
                    "description": "Trade direction"
                }
            },
            "required": ["base_size", "direction"]
        },
        "handler": lambda base_size, direction: tool.get_position_sizing(base_size, direction)
    },
    {
        "name": "check_exit_signals",
        "description": "Check for exit signals and risk factors. Use this to monitor active trades.",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "handler": lambda **kwargs: tool.get_exit_signal_context()
    }
]

# Example prompts for OpenClaw
SYSTEM_PROMPT = """You are an autonomous trading agent with access to real-time market analysis.

Before entering ANY trade:
1. Always call get_market_context to understand current market conditions
2. Call evaluate_setup with the proposed direction
3. Only enter if confidence is > 0.5
4. Use calculate_position_size to determine proper risk-adjusted position

For LONG trades:
- Prefer when regime is BULL and alignment is BULLISH or MIXED_BULLISH
- Be cautious in BEAR or CONFLICTED markets
- Adjust size down in HIGH volatility

For SHORT trades:
- Prefer when regime is BEAR and alignment is BEARISH or MIXED_BEARISH
- Be cautious in BULL or CONFLICTED markets
- Adjust size down in HIGH volatility

For EXITS:
- Call check_exit_signals on every heartbeat to monitor active trades
- Exit immediately if divergences appear
- Tighten TP in extreme sentiment (GREED/FEAR)
- Respect RANGE regime for taking partial profits

Always provide reasoning for your decisions based on market context."""

# Example decision flow
def make_trading_decision(setup_symbol: str, setup_direction: str, setup_data: dict) -> dict:
    """
    Full decision flow for a trading setup.

    Args:
        setup_symbol: Asset symbol (BTC, ETH, etc)
        setup_direction: LONG or SHORT
        setup_data: Dict with entry, sl, tp1, tp2

    Returns:
        Decision object with action and reasoning
    """
    # Step 1: Get market context
    context = tool.get_market_context()

    # Step 2: Evaluate setup
    evaluation = tool.should_trade_setup(setup_direction)

    # Step 3: Size position
    sizing = tool.get_position_sizing(setup_data.get('size', 0.1), setup_direction)

    # Step 4: Build decision
    decision = {
        'symbol': setup_symbol,
        'direction': setup_direction,
        'action': 'TRADE' if evaluation['should_trade'] else 'SKIP',
        'confidence': evaluation['confidence'],
        'reason': evaluation['reason'],
        'position_size': sizing['sized_position'],
        'risk_level': sizing['risk_level'],
        'adjustments': evaluation['adjustments'],
        'setup_data': setup_data,
        'market_context': evaluation['market_context'],
        'reasoning': f"""
Market: {context['regime']} regime ({context['regime_confidence']:.0%} conf)
Volatility: {context['volatility']}
Sentiment: {context['sentiment']} ({context['sentiment_score']:.0f})
Trend Alignment: {context['trend_alignment']} ({context['alignment_confidence']:.0%} conf)

Setup Evaluation:
- {evaluation['reason']}
- Confidence: {evaluation['confidence']:.0%}
- Position Size: {sizing['sized_position']} (Risk: {sizing['risk_level']})
- Adjustments: {json.dumps(evaluation['adjustments'], indent=2)}
"""
    }

    return decision


if __name__ == '__main__':
    print("=== Testing Trading Decision ===\n")

    setup = {
        'entry': 64700,
        'sl': 64000,
        'tp1': 65500,
        'tp2': 66500,
        'size': 0.1
    }

    decision = make_trading_decision('BTC', 'LONG', setup)
    print(json.dumps(decision, indent=2))
