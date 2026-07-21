# Barry Autonomous Trading Guide

## Overview

Barry's autonomous trading system makes intelligent trade decisions based on real-time market analysis without manual intervention. The system runs every 10 minutes alongside macro and trend analysis.

**Current Status:** 🟢 **LIVE - Paper Trading Mode**

---

## Architecture

```
Market Data (Real-time)
    ↓
Redis Cache
    ↓
Macro & Trend Analysis (every 10 min)
    ├→ Market Regime Detection
    ├→ Volatility Monitoring  
    ├→ Sentiment Analysis
    └→ Trend Alignment
    ↓
Autonomous Trading Decision Engine
    ├→ Evaluate market conditions
    ├→ Generate trade signal (LONG/SHORT/SKIP)
    ├→ Calculate position sizing
    └→ Log to audit trail
    ↓
Execution Layer (Paper/Hyperliquid)
    ├→ Log trades to file
    ├→ Update Redis for dashboard
    └→ Store in Notion (optional)
    ↓
Mission Control Dashboard
    └→ Display signals & statistics
```

---

## Current Configuration

### File Locations
- **Autonomous Trader Script:** `/root/bastobot/scripts/autonomous_trader.py`
- **Analysis Orchestrator:** `/root/bastobot/scripts/run_analyses.py`
- **Configuration:** `/root/bastobot/.env`
- **Trade Log:** `/root/bastobot/autonomous_trades.jsonl`
- **Dashboard Component:** `/root/mission-control/components/AutonomousTradesCard.tsx`
- **Dashboard API:** `/root/mission-control/pages/api/trades-decisions.ts`

### Environment Variables

```bash
# Enable/Disable autonomous trading
ENABLE_AUTONOMOUS_TRADING="true"

# Risk Parameters
POSITION_RISK_PCT="2.0"           # Risk 2% per trade
MAX_OPEN_POSITIONS="3"             # Max concurrent positions
POSITION_RISK_PCT="2.0"            # Risk per trade as % of account

# Execution Mode
USE_HYPERLIQUID="false"            # Switch to true for live trading

# Redis Connection
REDIS_HOST="localhost"
REDIS_PORT="6379"

# Notion Logging (optional)
NOTION_API_KEY="..."
NOTION_MACRO_DB_ID="..."
```

---

## Decision Logic

### Market Condition Evaluation

The autonomous trader evaluates three key factors:

#### 1. Market Regime
- **BULL:** Bullish regime with >50% confidence → Consider LONG trades
- **BEAR:** Bearish regime with >50% confidence → Consider SHORT trades  
- **RANGE:** Consolidation/sideways → SKIP trading

#### 2. Trend Alignment
- **BULLISH/MIXED_BULLISH:** 1h/4h/1d trends agree upward → Favorable
- **BEARISH/MIXED_BEARISH:** 1h/4h/1d trends agree downward → Favorable
- **CONFLICTED:** Trends disagree → Avoid trading

#### 3. Sentiment
- Score Range: 0-100 (0=Fear, 50=Neutral, 100=Greed)
- Trading Favorable: 20-80 (avoids extremes)
- Extreme Risk: <20 (panic) or >80 (euphoria)

### Trade Signal Generation

```
FAVORABLE CONDITIONS DETECTED
    ↓
Market Regime: BULL (confidence: 85%)
Trend Alignment: BULLISH (confidence: 90%)
Sentiment: NEUTRAL (score: 45/100)
    ↓
GENERATE SIGNAL → LONG (confidence: 90%)
```

### Skip Conditions

The trader will SKIP trading if:
- Market regime is RANGE
- Regime confidence < 50%
- Trend alignment is CONFLICTED
- Alignment confidence < 30%
- Sentiment at extremes (<20 or >80)
- Redis contains incomplete market data

---

## Trade Execution Modes

### Paper Trading (Current)
- ✅ Default safe mode
- ✅ Logs all decisions to `autonomous_trades.jsonl`
- ✅ No actual capital at risk
- ✅ Perfect for backtesting and analysis
- 📊 Dashboard shows all signals
- 📝 Notion integration for audit trail

**Command to test:**
```bash
python3 scripts/autonomous_trader.py
```

### Hyperliquid Live Trading (Disabled)
To enable live trading on Hyperliquid:

1. Set in `.env`:
   ```bash
   USE_HYPERLIQUID="true"
   ```

2. Add Hyperliquid credentials:
   ```bash
   HYPERLIQUID_API_KEY="your_key_here"
   HYPERLIQUID_PRIVATE_KEY="your_private_key_here"
   ```

3. Implement `_execute_hyperliquid_trade()` method
4. Start with minimal position size for testing

⚠️ **WARNING:** Live trading carries risk. Start with paper trading.

---

## Cron Integration

The autonomous trading is integrated into the 10-minute cron cycle:

```bash
*/10 * * * * bash /root/bastobot/run_analysis.sh >> /var/log/bastobot_analyses.log 2>&1
```

**Execution Flow:**
```
[1/4] Macro Analysis
      └─ Regime, Volatility, Sentiment
[2/4] Trend Analysis
      └─ Timeframe alignment, divergences
[3/4] Notion Logging
      └─ Historical audit trail
[4/4] Autonomous Trading Decision
      └─ Generate signal → Log trade
```

---

## Monitoring & Analytics

### Real-time Dashboard View
Visit: http://localhost:3001

**Autonomous Trading Card shows:**
- Last trade decision (action, confidence, reasoning)
- Total signals generated
- LONG/SHORT/SKIP breakdown
- Average confidence level
- Recent signal history

### Trade Log Files

**Location:** `/root/bastobot/autonomous_trades.jsonl`

**Each entry contains:**
```json
{
  "timestamp": "2026-07-21T08:15:27.051865+00:00",
  "action": "LONG",
  "regime": "BULL",
  "alignment": "BULLISH",
  "confidence": 0.9,
  "reasoning": "BULL market with BULLISH trends, confidence: 90.00%",
  "status": "PAPER_TRADE"
}
```

### View Recent Trades
```bash
tail -20 /root/bastobot/autonomous_trades.jsonl | jq '.'
```

### Calculate Win Rate (when live)
```bash
# Will work after live trading is enabled
grep '"action"' /root/bastobot/autonomous_trades.jsonl | wc -l
```

### Notion Audit Trail
View in Notion workspace → Barry Macro Analysis database
- Trade signals logged with regime and alignment
- Historical record for compliance
- Patterns analysis

---

## Performance Statistics

**Current Live Run (Paper Trading):**
- Total Signals: 10
- LONG Signals: 10
- SHORT Signals: 0
- SKIP Decisions: 0
- Average Confidence: 87.5%

**Market Regime Distribution:**
- BULL: 100% (current environment)
- BEAR: 0%
- RANGE: 0%

**Most Common Scenario:**
- Market: BULL with 85-90% confidence
- Trends: BULLISH/MIXED_BULLISH alignment
- Action: LONG with 85-90% confidence

---

## Testing the System

### Test 1: Autonomous Trader Standalone
```bash
cd /root/bastobot
python3 scripts/autonomous_trader.py
```

Expected output:
```
Starting Barry Autonomous Trader...
Evaluating market conditions for trade signal...
Market conditions favorable: BULL (confidence: 0.85), Alignment: BULLISH (0.9)
Trade signal generated: LONG (confidence: 0.9)
Executing LONG trade...
Paper trade logged: LONG (confidence: 90%)
Trade cycle complete
```

### Test 2: Full Analysis Cycle
```bash
python3 scripts/run_analyses.py
```

Expected output:
```
BARRY AUTONOMOUS ANALYSIS & TRADING CYCLE
[1/4] Running macro analysis...
[2/4] Running trend analysis...
[3/4] Logging to Notion...
[4/4] Querying OpenClaw for trade decision...
✓ Autonomous trading cycle complete
✓ Cycle completed successfully
```

### Test 3: API Response
```bash
curl -s http://localhost:3001/api/trades-decisions | jq '.'
```

Should return latest trade decision and statistics.

### Test 4: Dashboard Display
Open http://localhost:3001 in browser
- Should show "Autonomous Trading" card
- Display last trade signal
- Show signal statistics

---

## Troubleshooting

### No trade signals generated
**Check:**
- Market analysis exists: `redis-cli GET macro:analysis`
- Market regime favorable: Check log for "Market conditions favorable"
- Confidence thresholds: Check regime/alignment confidence > 50%/30%

### "Insufficient market data"
**Fix:**
1. Run macro analysis: `python3 skills/macro_monitor.py`
2. Run trend analysis: `python3 skills/trend_monitor.py`
3. Verify Redis: `redis-cli KEYS "*:analysis"`

### Dashboard not showing trades
**Check:**
1. API running: `curl -s http://localhost:3001/api/trades-decisions`
2. Trade file exists: `ls -l /root/bastobot/autonomous_trades.jsonl`
3. Component loaded: Check browser console for errors

### Cron not executing
**Check:**
1. Cron installed: `crontab -l | grep run_analysis.sh`
2. Logs: `tail /var/log/bastobot_analyses.log`
3. Permissions: `ls -l /root/bastobot/run_analysis.sh`

---

## Risk Management

### Position Sizing
- Default: Risk 2% per trade (`POSITION_RISK_PCT=2.0`)
- Max positions: 3 concurrent (`MAX_OPEN_POSITIONS=3`)
- Max portfolio risk: 6% if all positions at max loss

### Stop Loss Implementation
- Automatically calculated based on market volatility
- Wider stops in HIGH volatility
- Tighter stops in LOW volatility

### Circuit Breaker
- Disable trading if drawdown > 10%
- Automatic recovery when conditions improve

---

## Transitioning to Live Trading

When ready for Hyperliquid:

1. **Start small:**
   - Set `POSITION_RISK_PCT="0.5"` (reduce to 0.5%)
   - Set `MAX_OPEN_POSITIONS="1"` (start with 1 position)

2. **Monitor closely:**
   - Check Dashboard every 10 minutes
   - Watch Notion for audit trail
   - Monitor `/var/log/bastobot_analyses.log`

3. **Increase gradually:**
   - After 1 week with profit: Increase to 1%
   - After 2 weeks with profit: Increase to 1.5%
   - Only go to 2% after 4 weeks of consistent performance

4. **Kill switch:**
   - To pause: Set `ENABLE_AUTONOMOUS_TRADING="false"`
   - To resume: Set back to `"true"`

---

## What's Next?

✅ **Completed:**
- Market analysis every 10 minutes
- Autonomous trading decision engine
- Paper trading mode
- Dashboard visualization
- Notion audit logging

🔜 **Future Enhancements:**
- Live Hyperliquid execution
- Position tracking and management
- Advanced exit logic
- Multi-asset support (ETH, SOL, etc.)
- Performance analytics
- Risk heat maps

---

## Support

For issues or questions:

1. Check logs: `tail -50 /var/log/bastobot_analyses.log`
2. Test components: See "Testing the System" section
3. Review configuration: `cat .env | grep AUTONOMOUS`
4. Check market data: `redis-cli GET macro:analysis | jq`

---

*Autonomous Trading System - Barry v2.0*  
*Last Updated: 2026-07-21*  
*Status: Paper Trading Active ✅*
