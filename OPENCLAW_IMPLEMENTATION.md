# OpenClaw Implementation Guide
## Integrating Market Intelligence into Autonomous Trading

This guide shows exactly how to wire up the market intelligence system into OpenClaw's autonomous trading flow.

---

## Quick Start

### 1. Load Tools into OpenClaw

In your OpenClaw agent configuration or skill loader:

```python
from tools.market_decision_tools import TOOLS, SYSTEM_PROMPT, make_trading_decision

# Option A: Direct tool registration
for tool in TOOLS:
    register_tool(tool)

# Option B: Use system prompt guidance
set_system_prompt(SYSTEM_PROMPT)
```

### 2. Call Tools During Trading Flow

When OpenClaw detects a setup:

```python
async def on_setup_detected(setup):
    """OpenClaw heartbeat handler when setup detected"""
    
    # Step 1: Evaluate setup in current market
    decision = await call_tool(
        "evaluate_setup",
        direction=setup.direction  # "LONG" or "SHORT"
    )
    
    if not decision['should_trade']:
        log(f"Skip: {decision['reason']}")
        return
    
    if decision['confidence'] < 0.5:
        log(f"Low confidence: {decision['confidence']:.0%}")
        return
    
    # Step 2: Calculate position size
    sizing = await call_tool(
        "calculate_position_size",
        base_size=setup.base_size,
        direction=setup.direction
    )
    
    # Step 3: Execute trade with market context
    trade = execute_trade(
        symbol=setup.symbol,
        direction=setup.direction,
        size=sizing['sized_position'],
        entry=setup.entry,
        sl=setup.sl_adjusted_for_vol(decision),
        tp1=setup.tp1,
        tp2=setup.tp2,
        adjustments=decision['adjustments']
    )
    
    log(f"Entered: {trade.symbol} {trade.direction} @ {trade.entry}")
    log(f"Size: {trade.size} | SL: {trade.sl} | TP1: {trade.tp1}")
    log(f"Risk: {sizing['risk_level']} | Confidence: {decision['confidence']:.0%}")
    
    # Step 4: Monitor with exit signals
    await monitor_trade(trade, decision)
```

### 3. Monitor Active Trades

```python
async def monitor_trade(trade, decision):
    """Monitor active trade for exit signals"""
    
    while trade.is_open():
        # Check for exit signals every heartbeat
        signals = await call_tool("check_exit_signals")
        
        if signals['exit_signals']['has_divergence']:
            log("⚠️ Divergence detected - consider partial exit")
            close_partial(trade, percent=0.5)
        
        if signals['exit_signals']['volatility_spike']:
            log("⚠️ Volatility spike - tighten stops")
            trade.update_sl(tighter=True)
        
        if signals['exit_signals']['sentiment_extreme']:
            log("⚠️ Extreme sentiment - prepare for reversal")
            if trade.pnl_pct > 3:  # Only close winners
                close_partial(trade, percent=0.5)
        
        # Check if trend reversed
        if signals['context']['trend_alignment'] != decision['market_context']['alignment']:
            log("📈 Trend alignment shifted - exit remaining")
            close_trade(trade)
            return
        
        await sleep(60)  # Check every minute
```

---

## Integration Points

### A. Skill-Based (Recommended)

If OpenClaw uses skill-based architecture:

```python
# openclaw_skills.py

class MarketIntelligenceSkill(BaseSkill):
    """Skill for market-aware trading decisions"""
    
    def __init__(self):
        self.context_tool = MarketContextTool()
    
    async def check_market_before_entry(self, setup):
        """Skill: Pre-trade market check"""
        decision = self.context_tool.should_trade_setup(setup.direction)
        return {
            'should_proceed': decision['should_trade'],
            'reasoning': decision['reason'],
            'confidence': decision['confidence']
        }
    
    async def size_position_by_risk(self, base_size, direction):
        """Skill: Risk-adjusted position sizing"""
        sizing = self.context_tool.get_position_sizing(base_size, direction)
        return sizing
    
    async def monitor_exit_signals(self, trade):
        """Skill: Active trade monitoring"""
        signals = self.context_tool.get_exit_signal_context()
        return signals
```

### B. Tool-Based (OpenClaw Native)

If using OpenClaw's native tool system:

```javascript
// In OpenClaw config or tools manifest

{
  "tools": [
    {
      "id": "market-context",
      "name": "Get Market Context",
      "description": "Fetch current market regime, volatility, sentiment",
      "handler": "python tools/market_decision_tools.py get_context"
    },
    {
      "id": "evaluate-setup",
      "name": "Evaluate Trading Setup",
      "description": "Check if setup should be traded in current market",
      "parameters": ["direction"],
      "handler": "python tools/market_decision_tools.py evaluate_setup"
    },
    {
      "id": "size-position",
      "name": "Calculate Position Size",
      "description": "Get risk-adjusted position size",
      "parameters": ["base_size", "direction"],
      "handler": "python tools/market_decision_tools.py size_position"
    },
    {
      "id": "exit-signals",
      "name": "Check Exit Signals",
      "description": "Monitor for active trade exit signals",
      "handler": "python tools/market_decision_tools.py exit_signals"
    }
  ]
}
```

### C. REST API (For Remote OpenClaw)

If OpenClaw runs remotely, expose via Flask:

```python
from flask import Flask, request, jsonify
from tools.market_decision_tools import make_trading_decision
from skills.openclaw_market_context import MarketContextTool

app = Flask(__name__)
tool = MarketContextTool()

@app.route('/trade/evaluate', methods=['POST'])
def evaluate_trade():
    data = request.json
    decision = make_trading_decision(
        data['symbol'],
        data['direction'],
        data['setup']
    )
    return jsonify(decision)

@app.route('/market/context', methods=['GET'])
def market_context():
    return jsonify(tool.get_market_context())

# Start: python market_api.py
# OpenClaw calls: curl -X POST http://localhost:5001/trade/evaluate
```

---

## Example: Full Trading Loop

Here's a complete example of OpenClaw making a trade decision:

### Setup Detection
```
Chart Analysis: BTC 1h - Bull flag forming, targeting 65500
Entry: 64700
SL: 64000  
TP1: 65500
TP2: 66500
```

### Step 1: Market Context
```
OpenClaw: "Let me check the market conditions"
  ↓
call_tool("get_market_context")
  ↓
Result:
{
  "regime": "BULL",
  "regime_confidence": 0.85,
  "volatility": "NORMAL",
  "sentiment": "OPTIMISTIC",
  "trend_alignment": "BULLISH",
  "alignment_confidence": 0.75
}

Reasoning: "BULL market with BULLISH trend alignment"
```

### Step 2: Setup Evaluation
```
OpenClaw: "Should I trade this LONG setup?"
  ↓
call_tool("evaluate_setup", direction="LONG")
  ↓
Result:
{
  "should_trade": true,
  "confidence": 0.95,
  "reason": "Perfect bullish alignment (BULL regime + BULLISH trends)",
  "adjustments": {
    "position_size_multiplier": 1.0,
    "take_profit_tighter": false,
    "stop_loss_wider": false
  }
}

Reasoning: "95% confidence, perfect alignment, proceed to sizing"
```

### Step 3: Position Sizing
```
OpenClaw: "What size should I take given these conditions?"
  ↓
call_tool("calculate_position_size", base_size=0.1, direction="LONG")
  ↓
Result:
{
  "sized_position": 0.1,
  "risk_level": "LOW_RISK",
  "reasoning": "Base: 0.1, Multiplier: 1.00x, Confidence: 95%"
}

Reasoning: "Low risk, take full size"
```

### Step 4: Execute Trade
```
OpenClaw: "Conditions are favorable, executing..."

TRADE EXECUTION:
- Symbol: BTC
- Direction: LONG
- Entry: 64700
- Size: 0.1 BTC
- SL: 64000 (no adjustment needed)
- TP1: 65500
- TP2: 66500
- Market Context: BULL, BULLISH, OPTIMISTIC
- Confidence: 95%
- Risk Level: LOW
- Conviction: HIGH ✓

Order sent to exchange.
```

### Step 5: Monitoring Begins
```
Heartbeat 1 (1 minute):
  call_tool("check_exit_signals")
  → No divergences, volatility stable, sentiment bullish
  → Continue holding

Heartbeat 5 (5 minutes):
  Price hits TP1 at 65500
  → Partial close 50% at TP1
  → Trail remaining to entry

Heartbeat 10 (10 minutes):
  Market macro analysis updates
  New trend alignment: MIXED_BULLISH (was BULLISH)
  → Exit remaining position, lock in gains
  
Total P&L: +2.5%
Trade closed ✓
```

---

## Testing Implementation

### 1. Dry Run a Decision
```bash
python3 tools/market_decision_tools.py
# Shows complete decision with market context
```

### 2. Test with Sample Setup
```python
from tools.market_decision_tools import make_trading_decision

setup = {
    'entry': 64700,
    'sl': 64000,
    'tp1': 65500,
    'tp2': 66500,
    'size': 0.1
}

decision = make_trading_decision('BTC', 'LONG', setup)
print(decision['action'])           # → TRADE or SKIP
print(decision['confidence'])       # → 0.95
print(decision['position_size'])    # → 0.1
print(decision['risk_level'])       # → LOW_RISK
```

### 3. Test Exit Monitoring
```python
from skills.openclaw_market_context import MarketContextTool

tool = MarketContextTool()
signals = tool.get_exit_signal_context()
print(signals['watch_for_reversal'])  # → True/False
print(signals['exit_signals'])        # → {has_divergence, volatility_spike, ...}
```

---

## Configuration

### Environment Variables
```bash
# .env or openclaw config
REDIS_HOST=localhost
REDIS_PORT=6379
MARKET_ANALYSIS_UPDATE=10  # minutes
CONFIDENCE_THRESHOLD=0.5    # Min confidence to trade
COUNTER_TREND_THRESHOLD=0.6 # Min for counter-trend trades
```

### Cron Job (ensure analyses run)
```bash
# Verify in crontab
*/10 * * * * python3 /root/bastobot/scripts/run_analyses.py >> /var/log/bastobot_analyses.log 2>&1
```

### Dashboard Monitoring
```bash
# Tailscale
http://100.100.241.127:3003

# Shows real-time Market Analysis cards with:
- Current regime/vol/sentiment
- Trend alignment
- Divergence warnings
```

---

## Decision Tree

Quick reference for decision-making:

```
Setup detected
  ↓
get_market_context()
  ├─ Regime = BULL, Alignment = BULLISH
  │  └─ LONG: High confidence (90%+)
  │  └─ SHORT: Low confidence (20%)
  │
  ├─ Regime = BULL, Alignment = MIXED_BULLISH
  │  └─ LONG: Moderate confidence (65%)
  │  └─ SHORT: Skip
  │
  ├─ Regime = BULL, Alignment = BEARISH
  │  └─ LONG: Skip (counter-trend)
  │  └─ SHORT: Skip (low probability)
  │
  ├─ Regime = RANGE, Alignment = MIXED
  │  └─ LONG or SHORT: Lower confidence (45-50%), reduce size
  │
  └─ Regime = BEAR (opposite logic)

If confidence > 0.5:
  → calculate_position_size()
  → execute_trade()
Else:
  → skip_setup()
```

---

## Common Issues & Solutions

### Issue: "No market data available"
```
Solution: Check Redis and analysis runs
$ tail -f /var/log/bastobot_analyses.log
$ redis-cli GET macro:analysis
```

### Issue: Low confidence signals not trading enough
```
Solution: Check counter-trend settings
- Counter-trend requires higher confidence (60%+)
- In ranging markets, mix of LONG/SHORT OK
- Consider adding indicators alongside macro analysis
```

### Issue: Trades exit too early
```
Solution: Adjust exit signal sensitivity
- Current: Exits on divergence
- Consider: Grade exit urgency (divergence = 30% close, not 100%)
- Add: Partial exit logic based on profit targets hit first
```

### Issue: Position sizing too small
```
Solution: Review volatility regime
- HIGH volatility: 0.8x (conservative)
- If wanting larger: Wait for NORMAL/LOW vol
- Check: Base size parameter, confidence multiplier
```

---

## Monitoring & Logs

### Check Analysis Runs
```bash
tail -f /var/log/bastobot_analyses.log
```

### Example Log Output
```
2026-07-20 10:10:15 - INFO - Running macro and trend analyses...
2026-07-20 10:10:15 - INFO - ✓ Macro: BULL market with NORMAL volatility. 😊 Optimistic
2026-07-20 10:10:15 - INFO - ✓ Trend: 🟡 MIXED_BULLISH - 1h 📈, 4h 📈, 1d ↔️
2026-07-20 10:10:15 - INFO - Analyses completed successfully
```

### View Redis Data
```bash
redis-cli
> GET macro:analysis | jq .
> GET trend:analysis | jq .
> GET macro:history | jq 'length'  # Should be 24 (last 24 runs)
```

---

## Success Metrics

Track these to verify integration is working:

1. **Decision Quality**
   - % of trades with confidence > 80%
   - Avg P&L of aligned vs counter-trend trades
   - Exit signal accuracy (% exited before reversal)

2. **System Health**
   - Analyses run on schedule (every 10 min)
   - Redis data freshness (< 5 min old)
   - Tool latency (< 100ms per call)

3. **Trading Performance**
   - Win rate aligned trades vs counter-trend
   - Avg holding time by regime
   - Drawdown reduction vs non-macro trades

---

## Next: Deploy to Production

1. **Start monitoring:** `tail -f /var/log/bastobot_analyses.log`
2. **Watch dashboard:** http://100.100.241.127:3003
3. **Track decisions:** Log all evaluate_setup() calls
4. **Measure results:** Compare with/without macro context
5. **Iterate:** Adjust thresholds based on live performance

Ready to go! 🚀
