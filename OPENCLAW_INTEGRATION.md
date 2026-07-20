# OpenClaw Integration with Market Analysis

OpenClaw (Regis) now has intelligent market-aware trading decision tools.

## Overview

OpenClaw can now:
1. **Check market conditions** before entering trades
2. **Evaluate setup confidence** based on regime, volatility, sentiment, alignment
3. **Auto-size positions** based on risk and market conditions
4. **Monitor exit signals** during active trades

## Available Tools for OpenClaw

### 1. `get_market_context()`
Get current market analysis snapshot.

**Returns:**
```json
{
  "regime": "BULL|BEAR|RANGE",
  "regime_confidence": 0.85,
  "volatility": "HIGH|NORMAL|LOW",
  "sentiment": "GREED|OPTIMISTIC|NEUTRAL|PESSIMISTIC|FEAR",
  "sentiment_score": 77.03,
  "trend_alignment": "BULLISH|BEARISH|MIXED_BULLISH|MIXED_BEARISH|CONFLICTED",
  "alignment_confidence": 0.6,
  "timeframes": {
    "1h": {"direction": "UP|DOWN|CONSOLIDATING", "strength": "..."},
    "4h": {...},
    "1d": {...}
  },
  "divergences": []
}
```

**Use:** Get baseline market conditions before evaluating any setup.

### 2. `evaluate_setup(direction: 'LONG'|'SHORT')`
Evaluate if a setup should be traded.

**Parameters:**
- `direction`: "LONG" or "SHORT"

**Returns:**
```json
{
  "should_trade": true,
  "confidence": 0.95,
  "reason": "Perfect bullish alignment (BULL regime + BULLISH trends)",
  "adjustments": {
    "position_size_multiplier": 0.8,
    "take_profit_tighter": false,
    "stop_loss_wider": true
  },
  "market_context": {...}
}
```

**Logic:**
- LONG trades: BULL regime + BULLISH alignment = highest confidence
- SHORT trades: BEAR regime + BEARISH alignment = highest confidence
- Counter-trend: Much lower confidence, trade only if conviction is very high

### 3. `calculate_position_size(base_size: float, direction: 'LONG'|'SHORT')`
Calculate risk-adjusted position size.

**Parameters:**
- `base_size`: Base size in asset (e.g., 0.1 BTC)
- `direction`: "LONG" or "SHORT"

**Returns:**
```json
{
  "sized_position": 0.076,
  "reasoning": "Base: 0.1, Multiplier: 0.80x, Confidence: 95%",
  "risk_level": "LOW_RISK|MODERATE_RISK|HIGH_RISK",
  "adjustments": {...}
}
```

**Multiplier Logic:**
- HIGH volatility: 0.8x (reduce risk)
- LOW volatility: 1.2x (can take slightly more)
- Low confidence: Further reduced by confidence level

### 4. `check_exit_signals()`
Monitor active trades for exit signals.

**Returns:**
```json
{
  "exit_signals": {
    "has_divergence": false,
    "divergences": [],
    "trend_reversal": false,
    "volatility_spike": true,
    "sentiment_extreme": true
  },
  "watch_for_reversal": true
}
```

**Signals:**
- Divergence detected: Medium urgency exit
- Trend reversal: Check alignment shift
- Volatility spike + Extreme sentiment: Be prepared to exit

## Integration in OpenClaw

### System Prompt
Use this system prompt to guide OpenClaw's trading decisions:

```
You are an autonomous trading agent with access to real-time market analysis.

Before entering ANY trade:
1. Call get_market_context to understand current market conditions
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

Always provide reasoning for your decisions based on market context.
```

### Example Flow

1. **Setup Detection** → Setup is found on charts
2. **Call get_market_context()** → Market is BULL with MIXED_BULLISH alignment
3. **Call evaluate_setup("LONG")** → Returns 0.95 confidence
4. **Call calculate_position_size(0.1, "LONG")** → Returns 0.076 with LOW_RISK
5. **Enter Trade** → Place 0.076 BTC long with wider SL (HIGH volatility)
6. **Heartbeat Loop** → Call check_exit_signals() every minute
7. **Signal Alert** → Sentiment shifts to FEAR, exit TP1

## Python Integration

### For Barry/BastoBot Skills

```python
from tools.market_decision_tools import make_trading_decision

# Evaluate a setup
setup = {
    'entry': 64700,
    'sl': 64000,
    'tp1': 65500,
    'tp2': 66500,
    'size': 0.1
}

decision = make_trading_decision('BTC', 'LONG', setup)

if decision['action'] == 'TRADE':
    print(f"Enter {decision['position_size']} BTC at {setup['entry']}")
    print(f"SL: {setup['sl']}")
    print(f"TP1: {setup['tp1']} (tighten: {decision['adjustments']['take_profit_tighter']})")
else:
    print(f"Skip setup: {decision['reason']}")
```

### Direct Tool Access

```python
from skills.openclaw_market_context import MarketContextTool

tool = MarketContextTool()

# Get context
context = tool.get_market_context()
print(f"Market regime: {context['regime']}")

# Evaluate
eval = tool.should_trade_setup('LONG')
print(f"Trade confidence: {eval['confidence']:.0%}")

# Size position
sizing = tool.get_position_sizing(0.1, 'LONG')
print(f"Position: {sizing['sized_position']}")
```

## Expected Behavior

### Market Regimes

**BULL Market:**
- LONG trades: 90%+ confidence if aligned
- SHORT trades: 30-50% confidence (counter-trend)
- Position sizing: Standard to reduced

**BEAR Market:**
- SHORT trades: 90%+ confidence if aligned
- LONG trades: 30-50% confidence (counter-trend)
- Position sizing: Standard to reduced

**RANGE Market:**
- Both LONG/SHORT: 45-65% confidence (mixed)
- Position sizing: 50-75% of base

### Volatility Impact

- HIGH volatility: 0.8x position size, wider stops
- NORMAL volatility: 1.0x position size
- LOW volatility: 1.2x position size, tighter stops

### Sentiment Adjustment

- GREED: +5% confidence bonus for LONG, -20% for SHORT
- FEAR: +5% confidence bonus for SHORT, -20% for LONG
- NEUTRAL: No adjustment

## Testing

Run test:
```bash
cd /root/bastobot
python3 tools/market_decision_tools.py
```

Real-time decision:
```bash
python3 skills/openclaw_market_context.py
```

## Monitoring

Check analysis logs:
```bash
tail -f /var/log/bastobot_analyses.log
```

Redis data:
```bash
redis-cli
> GET macro:analysis
> GET trend:analysis
```

## Next Steps

1. Add to OpenClaw as callable tools
2. Update OpenClaw's trade entry skill to use evaluate_setup()
3. Create exit monitoring skill using check_exit_signals()
4. Wire up position sizing to actual trade execution
5. Add decision logging to audit trail
