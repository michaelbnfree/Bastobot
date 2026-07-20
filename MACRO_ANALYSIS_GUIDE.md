# Macro Analysis & Trend Monitoring System

Barry now has a complete macro analysis and trend monitoring system for intelligent trading decisions.

## Components

### 1. Macro Monitor (`skills/macro_monitor.py`)
Tracks market conditions and updates every 10 minutes via cron.

**Analyzes:**
- **Market Regime**: BULL / BEAR / RANGE
- **Volatility**: HIGH / NORMAL / LOW (via Bollinger Band width)
- **Sentiment**: GREED / OPTIMISTIC / NEUTRAL / PESSIMISTIC / FEAR

**Data Stored in Redis:**
- `macro:analysis` — Current macro analysis
- `macro:history` — Last 24 analyses

**Example Output:**
```json
{
  "timestamp": "2026-07-19T03:20:21",
  "market_regime": {"regime": "BULL", "strength": "Strong", "confidence": 0.85},
  "volatility": {"regime": "HIGH", "label": "🔴 High Vol", "volatility_pct": 10.0},
  "sentiment": {"sentiment": "GREED", "label": "😈 Extreme Greed", "score": 77.03},
  "summary": "BULL market with HIGH volatility. 😈 Extreme Greed"
}
```

### 2. Trend Monitor (`skills/trend_monitor.py`)
Analyzes multi-timeframe trends and detects divergences.

**Tracks:**
- **Timeframe Trends**: 1h/4h/1d (UP/DOWN/CONSOLIDATING)
- **Alignment**: BULLISH / BEARISH / MIXED_BULLISH / MIXED_BEARISH / CONFLICTED
- **Divergences**: Detects misalignment between timeframes

**Data Stored in Redis:**
- `trend:analysis` — Current trend analysis

**Example Output:**
```json
{
  "timestamp": "2026-07-19T03:20:54",
  "trends": {
    "1h": {"direction": "UP", "strength": "Strong", "emoji": "📈"},
    "4h": {"direction": "CONSOLIDATING", "strength": "Weak", "emoji": "↔️"},
    "1d": {"direction": "CONSOLIDATING", "strength": "Weak", "emoji": "↔️"}
  },
  "alignment": {"alignment": "MIXED_BULLISH", "emoji": "🟡", "confidence": 0.6},
  "divergences": []
}
```

### 3. Automated Execution
Runs every 10 minutes via cron:
```bash
*/10 * * * * python3 scripts/run_analyses.py >> /var/log/bastobot_analyses.log 2>&1
```

## Dashboard Integration

Mission Control displays:
1. **Market Analysis Card**
   - Market regime with confidence
   - Volatility status
   - Sentiment gauge

2. **Trend Alignment Card**
   - Overall alignment status
   - Per-timeframe trends with emoji
   - Active divergences

Access at: `http://100.100.241.127:3001` (Tailscale)

## LLM Integration

### For OpenClaw and Barry:

Get complete market context:
```bash
curl http://127.0.0.1:5001/api/market-context
```

Get quick summary:
```bash
curl http://127.0.0.1:5001/api/market-summary
```

### Example Context Format:
```
MARKET STATUS:
- Regime: BULL (Strong)
- Volatility: 🔴 High Vol
- Sentiment: 😈 Extreme Greed
- Trend Alignment: 🟡 MIXED_BULLISH
- Timeframes: 1h 📈 | 4h ↔️ | 1d ↔️

RECOMMENDATION CONTEXT:
- Consider current market regime when evaluating setup
- Check for timeframe alignment before entry
- Monitor divergences for exit signals
- Respect volatility regime for position sizing
```

## Using in Trading Logic

Example for Barry to check before entering a trade:

```python
import requests

def should_trade_setup():
    # Get market context
    context = requests.get('http://127.0.0.1:5001/api/market-context').json()
    
    # Check regime
    regime = context['market_regime']['regime']
    
    # Check alignment
    alignment = context['alignment']['alignment']
    
    # Trade conditions
    if regime == 'BULL' and 'BULLISH' in alignment:
        return True  # Market supports the trade
    
    if regime == 'BEAR' and 'BEARISH' in alignment:
        return True  # Market supports the trade
    
    # Mixed or no alignment - use smaller size
    return 'PROCEED_CAUTIOUS'
```

## Data Freshness

- Macro/Trend analysis: Updated every 10 minutes
- Price data: Updated every 5 minutes (from scanner)
- Dashboard refresh: Every 10 seconds

## Monitoring

Check logs:
```bash
tail -f /var/log/bastobot_analyses.log
```

Check Redis data:
```bash
redis-cli
> GET macro:analysis
> GET trend:analysis
```

## Future Enhancements

- [ ] VIX integration for volatility regime
- [ ] Multi-asset correlation tracking
- [ ] Support/resistance level extraction
- [ ] Volume profile analysis
- [ ] Funding rate monitoring
- [ ] Historical macro trending
