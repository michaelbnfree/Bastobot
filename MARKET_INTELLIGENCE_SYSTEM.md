# Barry Market Intelligence System
## Complete Macro Analysis → OpenClaw Integration

A fully integrated market intelligence pipeline that feeds real-time macro analysis, trend monitoring, and decision support directly into OpenClaw's autonomous trading logic.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  MARKET DATA SOURCES                                            │
│  - Binance prices (updated every 5 minutes)                     │
│  - RSI, Bollinger Bands, MACD (Technical Indicators)            │
│  - Historical snapshots (Trade setups + conviction)             │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  ANALYSIS LAYER (Updates every 10 minutes)                      │
├─────────────────────────────────────────────────────────────────┤
│  📊 Macro Monitor                                                │
│  - Market Regime: BULL/BEAR/RANGE                               │
│  - Volatility: HIGH/NORMAL/LOW (Bollinger Band width)           │
│  - Sentiment: GREED to FEAR (RSI-based)                         │
│                                                                 │
│  📈 Trend Monitor                                                │
│  - Timeframe Analysis: 1h/4h/1d trends                          │
│  - Alignment: BULLISH/BEARISH/MIXED status                      │
│  - Divergence Detection: Momentum misalignments                 │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  REDIS CACHE (Real-time data store)                             │
├─────────────────────────────────────────────────────────────────┤
│  - macro:analysis          → Latest macro context               │
│  - trend:analysis          → Latest trend analysis              │
│  - macro:history           → Last 24 macro snapshots            │
│  - scanner:cache:*         → Live price data                    │
│  - trade_monitor:*         → Active trades                      │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  DECISION ENGINE (OpenClaw Integration)                         │
├─────────────────────────────────────────────────────────────────┤
│  🎯 Market Context Tool                                          │
│  - get_market_context() → Full regime/vol/sentiment             │
│                                                                 │
│  ✅ Setup Evaluation Tool                                        │
│  - evaluate_setup("LONG"|"SHORT") → confidence + adjustments    │
│                                                                 │
│  📊 Position Sizing Tool                                         │
│  - calculate_position_size(base, direction) → risk-adjusted     │
│                                                                 │
│  🚪 Exit Signal Tool                                             │
│  - check_exit_signals() → divergences, reversals, warnings      │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  OPENCLAW AUTONOMOUS AGENT                                      │
├─────────────────────────────────────────────────────────────────┤
│  1. Setup detected (chart analysis)                             │
│  2. Call evaluate_setup(direction)                              │
│  3. Only proceed if confidence > 0.5                            │
│  4. Size position with calculate_position_size()                │
│  5. Execute trade with context-aware adjustments                │
│  6. Monitor with check_exit_signals() on every heartbeat        │
│  7. Exit based on macro signals + technical TP                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Data Collection
**Location:** `/root/bastobot/skills/`

- **macro_monitor.py** — Analyzes market regime, volatility, sentiment
- **trend_monitor.py** — Analyzes timeframe trends, alignment, divergences
- **run_analyses.py** — Orchestrates scheduled analysis runs

**Automated via cron:**
```bash
*/10 * * * * python3 scripts/run_analyses.py >> /var/log/bastobot_analyses.log 2>&1
```

### 2. Decision Tools
**Location:** `/root/bastobot/tools/`

- **market_decision_tools.py** — Callable decision functions for OpenClaw
  - `make_trading_decision()` — Full decision flow
  - `TOOLS` — Tool definitions for OpenClaw
  - `SYSTEM_PROMPT` — Guidance for autonomous trading

**Base Tool:** `openclaw_market_context.py` provides:
- `get_market_context()` — Market analysis snapshot
- `should_trade_setup()` — Confidence evaluation
- `get_position_sizing()` — Risk-adjusted sizing
- `get_exit_signal_context()` — Exit monitoring

### 3. Display & Monitoring
**Location:** `/root/mission-control/`

- **API endpoints:**
  - `/api/macro` — Fetch macro + trend data
  
- **Components:**
  - `MacroAnalysis.tsx` — Dashboard display (Macro + Trends)
  - Renders in **Market Analysis** section

**Access:** http://100.100.241.127:3003 (Tailscale)

### 4. Integration Points

**For OpenClaw:**
- Load tools from `market_decision_tools.TOOLS`
- Use system prompt from `market_decision_tools.SYSTEM_PROMPT`
- Call tools during decision-making:
  - Before entry: `evaluate_setup(direction)`
  - Before sizing: `calculate_position_size(base, direction)`
  - During monitoring: `check_exit_signals()`

**For Barry/Skills:**
- Import and use `make_trading_decision()` in trade entry logic
- Access tool directly via `MarketContextTool` class

---

## Decision Logic

### Entry Decision Flow

```python
# Step 1: Get Context
context = get_market_context()
# → {regime: 'BULL', volatility: 'HIGH', sentiment: 'GREED', alignment: 'MIXED_BULLISH'}

# Step 2: Evaluate Setup
eval = should_trade_setup('LONG')
# → {should_trade: True, confidence: 0.95, reason: "...", adjustments: {...}}

# Step 3: Size Position
sizing = calculate_position_size(0.1, 'LONG')
# → {sized_position: 0.076, risk_level: 'LOW_RISK', adjustments: {...}}

# Step 4: Execute
if eval['should_trade'] and eval['confidence'] > 0.5:
    enter_trade(
        size=sizing['sized_position'],
        sl_wider=sizing['adjustments'].get('stop_loss_wider'),
        tp_tighter=sizing['adjustments'].get('take_profit_tighter')
    )
```

### Confidence Calculation

**Base confidence by regime + alignment:**

| Regime | BULLISH | MIXED_BULLISH | BEARISH | MIXED_BEARISH | CONFLICTED |
|--------|---------|---------------|---------|---------------|------------|
| BULL   | 0.90    | 0.65          | 0.20    | 0.20          | 0.20       |
| BEAR   | 0.20    | 0.20          | 0.90    | 0.65          | 0.20       |
| RANGE  | 0.50    | 0.45          | 0.50    | 0.45          | 0.40       |

**Adjustments applied:**
- Sentiment: ±5% for aligned, -20% for counter-trend
- Volatility: ×0.8 if HIGH, ×1.2 if LOW
- Divergence: ×0.85 if active
- Confidence floor: 0.4 (won't trade below)

---

## Usage Examples

### Example 1: OpenClaw Entry Decision

```
Setup detected: BTC 1h bull flag, potential breakout to 65500

Agent reasoning:
1. Call get_market_context()
   → BULL regime (85%), HIGH volatility, GREED sentiment, MIXED_BULLISH
   
2. Call evaluate_setup("LONG")
   → Confidence: 95%, "Perfect bullish alignment"
   → Adjustments: 0.8x size (high vol), wider SL
   
3. Call calculate_position_size(0.1, "LONG")
   → Size: 0.076 BTC, Risk: LOW_RISK
   
Decision: ENTER at 64700 with 0.076 BTC
- SL: 64000 (wider due to HIGH volatility)
- TP1: 65500 (normal tightness)
- TP2: 66500
- Risk: LOW, Confidence: 95%
```

### Example 2: Exit Signal During Trade

```
Trade active: Long 0.076 BTC @ 64700

Heartbeat check: check_exit_signals()
→ {
    volatility_spike: true,
    sentiment_extreme: true,  ← Shifted to extreme GREED
    has_divergence: false,
    watch_for_reversal: true
}

Agent reasoning:
- Extreme GREED usually precedes pullback
- HIGH volatility spike = increased risk
- Action: Partial exit at TP1 (65500), trail TP2 or exit remaining
```

### Example 3: Skip Counter-Trend Setup

```
Setup detected: ETH potential long on 4h despite BEAR market

Agent reasoning:
1. get_market_context()
   → BEAR regime (85%), NORMAL vol, PESSIMISTIC, BEARISH alignment

2. evaluate_setup("LONG")
   → Confidence: 20%, "Counter-trend setup (BEAR regime)"
   
Decision: SKIP
Reasoning: Counter-trend in strong bear market has low probability
Could reconsider if confidence was >50%, but currently not favorable
```

---

## Monitoring & Maintenance

### Check Current Analysis
```bash
# Via command line
redis-cli
> GET macro:analysis
> GET trend:analysis

# Via Python
python3 skills/macro_monitor.py
python3 skills/trend_monitor.py
```

### View Logs
```bash
tail -f /var/log/bastobot_analyses.log
```

### Test Decision Engine
```bash
python3 tools/market_decision_tools.py
```

### Dashboard Access
- **Tailscale:** http://100.100.241.127:3003
- **Market Analysis section:** Shows latest macro + trend data
- **Updates:** Every 10 seconds for dashboard, every 10 minutes for analysis

---

## Data Freshness

| Data Source | Update Frequency | Store | Freshness Indicator |
|-------------|------------------|-------|----------------------|
| Price data | 5 minutes | Redis scanner:cache:* | Age in seconds |
| RSI/Bollinger | 5 minutes | Redis scanner:cache:* | Included with price |
| Macro analysis | 10 minutes | Redis macro:analysis | Timestamp |
| Trend analysis | 10 minutes | Redis trend:analysis | Timestamp |
| History | 10 minutes | Redis macro:history | Rolling 24 snapshots |

---

## Future Enhancements

- [ ] VIX integration for correlation analysis
- [ ] Multi-asset regime detection (BTC→altcoins)
- [ ] Volume profile & VWAP integration
- [ ] Support/resistance level extraction
- [ ] Funding rate monitoring (perps)
- [ ] Liquidation cascade detection
- [ ] Correlation shifts between assets
- [ ] Micro regime changes (<10min analysis)
- [ ] Historical macro trending dashboard

---

## Quick Reference

### Entry Rules
- ✅ Trade with trend when confidence > 70%
- ✅ Trade mixed alignment if confidence > 50%
- ❌ Skip counter-trend unless confidence > 60%
- ❌ Reduce size in HIGH volatility
- ❌ Skip when divergences detected

### Position Sizing
- Base sizing: 1.0x
- HIGH volatility: 0.8x
- LOW volatility: 1.2x
- Low confidence: Further reduced by confidence %
- Counter-trend: Already reduced by evaluation

### Exit Signals
- Divergence detected: Exit 30-50%
- Trend reversal (alignment shift): Exit 30-50%
- Sentiment extreme + volatility spike: Protect TP2
- Market regime shift: Exit remainder

---

## Files Reference

```
/root/bastobot/
├── skills/
│   ├── macro_monitor.py              ← Macro analysis
│   ├── trend_monitor.py              ← Trend analysis
│   ├── openclaw_market_context.py    ← OpenClaw tool base
│   └── run_analyses.py               ← Scheduler
├── tools/
│   └── market_decision_tools.py      ← OpenClaw tool wrappers
├── api/
│   └── market_context.py             ← Flask endpoints (optional)
├── MACRO_ANALYSIS_GUIDE.md           ← Setup guide
└── OPENCLAW_INTEGRATION.md           ← OpenClaw usage guide

/root/mission-control/
├── pages/api/macro.ts                ← Dashboard API endpoint
└── components/MacroAnalysis.tsx      ← Dashboard display
```

---

## Support

Questions about:
- **Macro analysis:** See `MACRO_ANALYSIS_GUIDE.md`
- **OpenClaw integration:** See `OPENCLAW_INTEGRATION.md`
- **Dashboard:** Check Mission Control at http://100.100.241.127:3003
- **Decision logic:** Review `tools/market_decision_tools.py`
- **Logs:** `tail -f /var/log/bastobot_analyses.log`
