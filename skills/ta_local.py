"""TradingView-style technical rating computed locally from OHLCV candles.

Replaces the stub that `_get_local_indicators` used to return (RSI and Bollinger bands
only, with MACD/ADX/EMAs hard-coded to 0 and the summary fixed at NEUTRAL 0/0/0), which
made every regime and every snapshot read "neutral" from 2026-07-20 on.

The rating follows TradingView's Technical Ratings: 11 oscillators and 15 moving averages
each vote BUY / SELL / NEUTRAL, and the summary is built from those 26 votes. Indicator
formulas follow Pine Script (Wilder RMA for RSI/ADX, EMA seeded with the SMA of the first n values, ...).
Parity with TradingView is checked in tests/test_ta_local.py against captured TradingView
output (values and per-indicator votes) and can be re-checked live with
tools/check_ta_parity.py.

Pure Python, no dependencies. Candles are rows of [open_time, open, high, low, close, volume];
the last row may be the still-forming candle, as on TradingView.
"""

from math import floor, sqrt

# ── series helpers ───────────────────────────────────────────────────────────


def _split(values):
    """(offset of first non-None value, the clean tail)."""
    first = next((i for i, v in enumerate(values) if v is not None), len(values))
    return first, values[first:]


def sma(values, n):
    first, v = _split(values)
    out = [None] * (len(v))
    window_sum = 0.0
    for i, x in enumerate(v):
        window_sum += x
        if i >= n:
            window_sum -= v[i - n]
        if i >= n - 1:
            out[i] = window_sum / n
    return [None] * first + out


def ema(values, n):
    """Pine ta.ema: alpha = 2/(n+1), seeded with the SMA of the first n values."""
    first, v = _split(values)
    out = [None] * len(v)
    if len(v) >= n:
        alpha = 2.0 / (n + 1)
        prev = sum(v[:n]) / n
        out[n - 1] = prev
        for i in range(n, len(v)):
            prev = alpha * v[i] + (1 - alpha) * prev
            out[i] = prev
    return [None] * first + out


def rma(values, n):
    """Pine ta.rma (Wilder): alpha = 1/n, seeded with the SMA of the first n values."""
    first, v = _split(values)
    out = [None] * len(v)
    if len(v) >= n:
        prev = sum(v[:n]) / n
        out[n - 1] = prev
        for i in range(n, len(v)):
            prev = (v[i] + (n - 1) * prev) / n
            out[i] = prev
    return [None] * first + out


def wma(values, n):
    first, v = _split(values)
    out = [None] * len(v)
    denom = n * (n + 1) / 2.0
    for i in range(n - 1, len(v)):
        out[i] = sum(v[i - n + 1 + j] * (j + 1) for j in range(n)) / denom
    return [None] * first + out


def _highest(values, n):
    return [None if i < n - 1 else max(values[i - n + 1:i + 1]) for i in range(len(values))]


def _lowest(values, n):
    return [None if i < n - 1 else min(values[i - n + 1:i + 1]) for i in range(len(values))]


def _sub(a, b):
    return [None if x is None or y is None else x - y for x, y in zip(a, b)]


def _last(series, back=0):
    i = len(series) - 1 - back
    return series[i] if i >= 0 else None


# ── indicators (each returns a full series) ──────────────────────────────────


def rsi(closes, n=14):
    gains, losses = [None], [None]
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain, avg_loss = rma(gains, n), rma(losses, n)
    out = []
    for g, l in zip(avg_gain, avg_loss):
        if g is None or l is None:
            out.append(None)
        elif l == 0:
            out.append(100.0)
        else:
            out.append(100.0 - 100.0 / (1.0 + g / l))
    return out


def stoch(highs, lows, closes, k_len=14, k_smooth=3, d_smooth=3):
    hh, ll = _highest(highs, k_len), _lowest(lows, k_len)
    raw = [None if h is None else (0.0 if h == l else 100.0 * (c - l) / (h - l))
           for h, l, c in zip(hh, ll, closes)]
    k = sma(raw, k_smooth)
    return k, sma(k, d_smooth)


def cci(highs, lows, closes, n=20):
    tp = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    mean = sma(tp, n)
    out = [None] * len(tp)
    for i in range(n - 1, len(tp)):
        dev = sum(abs(tp[j] - mean[i]) for j in range(i - n + 1, i + 1)) / n
        out[i] = 0.0 if dev == 0 else (tp[i] - mean[i]) / (0.015 * dev)
    return out


def dmi(highs, lows, closes, n=14):
    """Returns (+DI, -DI, ADX) series, Wilder smoothing as in Pine ta.dmi."""
    plus_dm, minus_dm, tr = [None], [None], [None]
    for i in range(1, len(closes)):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr, p, m = rma(tr, n), rma(plus_dm, n), rma(minus_dm, n)
    plus_di = [None if a in (None, 0) or x is None else 100.0 * x / a for a, x in zip(atr, p)]
    minus_di = [None if a in (None, 0) or x is None else 100.0 * x / a for a, x in zip(atr, m)]
    dx = [None if pl is None or mi is None else (0.0 if pl + mi == 0 else 100.0 * abs(pl - mi) / (pl + mi))
          for pl, mi in zip(plus_di, minus_di)]
    return plus_di, minus_di, rma(dx, n)


def awesome_oscillator(highs, lows):
    hl2 = [(h + l) / 2.0 for h, l in zip(highs, lows)]
    return _sub(sma(hl2, 5), sma(hl2, 34))


def momentum(closes, n=10):
    return [None if i < n else closes[i] - closes[i - n] for i in range(len(closes))]


def macd(closes, fast=12, slow=26, signal=9):
    line = _sub(ema(closes, fast), ema(closes, slow))
    return line, ema(line, signal)


def stoch_rsi(closes, rsi_len=14, stoch_len=14, k_smooth=3, d_smooth=3):
    r = rsi(closes, rsi_len)
    hh, ll = _highest_opt(r, stoch_len), _lowest_opt(r, stoch_len)
    raw = [None if h is None else (0.0 if h == l else 100.0 * (x - l) / (h - l))
           for h, l, x in zip(hh, ll, r)]
    k = sma(raw, k_smooth)
    return k, sma(k, d_smooth)


def _highest_opt(values, n):
    out = []
    for i in range(len(values)):
        w = values[max(0, i - n + 1):i + 1]
        out.append(max(w) if i >= n - 1 and all(x is not None for x in w) else None)
    return out


def _lowest_opt(values, n):
    out = []
    for i in range(len(values)):
        w = values[max(0, i - n + 1):i + 1]
        out.append(min(w) if i >= n - 1 and all(x is not None for x in w) else None)
    return out


def williams_r(highs, lows, closes, n=14):
    hh, ll = _highest(highs, n), _lowest(lows, n)
    return [None if h is None else (0.0 if h == l else -100.0 * (h - c) / (h - l))
            for h, l, c in zip(hh, ll, closes)]


def bull_bear_power(highs, lows, closes, n=13):
    e = ema(closes, n)
    return [None if x is None else h + l - 2 * x for h, l, x in zip(highs, lows, e)]


def ultimate_oscillator(highs, lows, closes, fast=7, mid=14, slow=28):
    bp, tr = [None], [None]
    for i in range(1, len(closes)):
        low = min(lows[i], closes[i - 1])
        bp.append(closes[i] - low)
        tr.append(max(highs[i], closes[i - 1]) - low)

    def avg(n):
        out = [None] * len(closes)
        for i in range(n, len(closes)):
            t = sum(tr[i - n + 1:i + 1])
            out[i] = sum(bp[i - n + 1:i + 1]) / t if t else 0.0
        return out

    a, b, c = avg(fast), avg(mid), avg(slow)
    return [None if x is None or y is None or z is None else 100.0 * (4 * x + 2 * y + z) / 7.0
            for x, y, z in zip(a, b, c)]


def vwma(closes, volumes, n=20):
    num = sma([c * v for c, v in zip(closes, volumes)], n)
    den = sma(volumes, n)
    return [None if a is None or not b else a / b for a, b in zip(num, den)]


def hull_ma(closes, n=9):
    half, full = wma(closes, max(1, floor(n / 2))), wma(closes, n)
    raw = [None if a is None or b is None else 2 * a - b for a, b in zip(half, full)]
    return wma(raw, max(1, round(sqrt(n))))


def ichimoku(highs, lows, conversion=9, base=26, span_b=52, displacement=26):
    """Returns (conversion line, base line, leading span A, leading span B) as plotted on
    the current bar, i.e. spans shifted forward by `displacement` bars."""
    def mid(n):
        return [None if h is None else (h + l) / 2.0 for h, l in zip(_highest(highs, n), _lowest(lows, n))]

    conv, bline, lead_b_raw = mid(conversion), mid(base), mid(span_b)
    lead_a_raw = [None if c is None or b is None else (c + b) / 2.0 for c, b in zip(conv, bline)]

    def shift(series):
        return [None] * displacement + series[:-displacement] if displacement else series

    return conv, bline, shift(lead_a_raw), shift(lead_b_raw)


# ── votes ────────────────────────────────────────────────────────────────────

BUY, SELL, NEUTRAL = "BUY", "SELL", "NEUTRAL"


def _vote(buy, sell):
    return BUY if buy else SELL if sell else NEUTRAL


def _recommendation(score):
    if score is None:
        return NEUTRAL
    if score < -0.5:
        return "STRONG_SELL"
    if score < -0.1:
        return "SELL"
    if score <= 0.1:
        return NEUTRAL
    if score <= 0.5:
        return BUY
    return "STRONG_BUY"


def _tally(votes):
    counts = {BUY: 0, SELL: 0, NEUTRAL: 0}
    for v in votes.values():
        counts[v] += 1
    total = len(votes)
    score = (counts[BUY] - counts[SELL]) / total if total else None
    return {"RECOMMENDATION": _recommendation(score), "BUY": counts[BUY], "SELL": counts[SELL],
            "NEUTRAL": counts[NEUTRAL]}, score


_EPS = 1e-9   # K == D at the 0/100 rails must not flip on float noise (TradingView votes NEUTRAL there)


def _gt(a, b):
    return a > b + _EPS


def _lt(a, b):
    return a < b - _EPS


def oscillator_votes(v):
    """v: dict of last/previous indicator values (see compute_values).

    Rules were fitted against TradingView's own per-indicator votes (tools/check_ta_parity.py,
    tests/fixtures/ta_tv_votes.json; 127 coin/timeframe samples when this was written):
      reproduced with no false alarms: RSI, CCI, ADX, AO, Mom, MACD, W%R, UO, Stochastic and
        all 14 price-vs-average rules
      Stoch RSI: only the SELL side is modelled (K > 80 and K < D reproduced 13/13); TradingView
        voted BUY on 2 of 127 samples whose pattern no simple rule explained, so BUY is not voted.
      BBP: only the BUY side is modelled (bear power < 0 and rising matched every TradingView BUY);
        TradingView's SELL votes (7 of 127) depend on something not recoverable from its output.
      Ichimoku (see moving_average_votes): TradingView voted NEUTRAL on every sample.
    """
    return {
        "RSI": _vote(v["rsi"] < 30 and v["rsi"] > v["rsi1"], v["rsi"] > 70 and v["rsi"] < v["rsi1"]),
        # the crossover on the previous bar is part of TradingView's rule (it voted NEUTRAL when
        # K was already above D, e.g. ZEC 1d)
        "STOCH.K": _vote(
            _lt(v["stoch_k"], 20) and _lt(v["stoch_d"], 20) and _gt(v["stoch_k"], v["stoch_d"]) and v["stoch_k1"] < v["stoch_d1"],
            _gt(v["stoch_k"], 80) and _gt(v["stoch_d"], 80) and _lt(v["stoch_k"], v["stoch_d"]) and v["stoch_k1"] > v["stoch_d1"]),
        "CCI": _vote(v["cci"] < -100 and v["cci"] > v["cci1"], v["cci"] > 100 and v["cci"] < v["cci1"]),
        "ADX": _vote(v["adx"] > 20 and v["plus_di1"] < v["minus_di1"] and v["plus_di"] > v["minus_di"],
                     v["adx"] > 20 and v["plus_di1"] > v["minus_di1"] and v["plus_di"] < v["minus_di"]),
        "AO": _vote((v["ao"] > 0 and v["ao1"] < 0) or (v["ao"] > 0 and v["ao1"] > 0 and v["ao"] > v["ao1"] and v["ao2"] > v["ao1"]),
                    (v["ao"] < 0 and v["ao1"] > 0) or (v["ao"] < 0 and v["ao1"] < 0 and v["ao"] < v["ao1"] and v["ao2"] < v["ao1"])),
        "Mom": _vote(v["mom"] > v["mom1"], v["mom"] < v["mom1"]),
        "MACD": _vote(v["macd"] > v["macd_signal"], v["macd"] < v["macd_signal"]),
        "Stoch.RSI": _vote(False, _gt(v["stoch_rsi_k"], 80) and _lt(v["stoch_rsi_k"], v["stoch_rsi_d"])),
        "W%R": _vote(v["wr"] < -80 and v["wr"] > v["wr1"], v["wr"] > -20 and v["wr"] < v["wr1"]),
        "BBP": _vote(v["bear"] < 0 and _gt(v["bear"], v["bear1"]), False),
        "UO": _vote(v["uo"] > 70, v["uo"] < 30),
    }


def moving_average_votes(v):
    close = v["close"]
    votes = {}
    for n in (10, 20, 30, 50, 100, 200):
        votes[f"EMA{n}"] = _vote(close > v[f"ema{n}"], close < v[f"ema{n}"])
        votes[f"SMA{n}"] = _vote(close > v[f"sma{n}"], close < v[f"sma{n}"])
    # TradingView voted NEUTRAL on all 127 captured samples, while the usual four-condition rule
    # (conversion > base, close > base, span A > span B, close > span A) voted BUY on 46 of them. The
    # indicator values are still computed (ichi_*); add the rule once a non-neutral vote can be fitted.
    votes["Ichimoku"] = NEUTRAL
    votes["VWMA"] = _vote(close > v["vwma"], close < v["vwma"])
    votes["HullMA"] = _vote(close > v["hma"], close < v["hma"])
    return votes


# ── entry point ──────────────────────────────────────────────────────────────

MIN_CANDLES = 250  # EMA/SMA 200 plus warm-up


def compute_values(candles):
    """Last and previous values of every indicator the rating needs."""
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]

    k, d = stoch(highs, lows, closes)
    sr_k, sr_d = stoch_rsi(closes)
    plus_di, minus_di, adx = dmi(highs, lows, closes)
    macd_line, macd_sig = macd(closes)
    conv, base, lead_a, lead_b = ichimoku(highs, lows)
    series = {
        "rsi": rsi(closes), "stoch_k": k, "stoch_d": d, "cci": cci(highs, lows, closes),
        "plus_di": plus_di, "minus_di": minus_di, "adx": adx,
        "ao": awesome_oscillator(highs, lows), "mom": momentum(closes),
        "macd": macd_line, "macd_signal": macd_sig, "stoch_rsi_k": sr_k, "stoch_rsi_d": sr_d,
        "wr": williams_r(highs, lows, closes), "bbp": bull_bear_power(highs, lows, closes),
        "uo": ultimate_oscillator(highs, lows, closes), "vwma": vwma(closes, volumes),
        "hma": hull_ma(closes), "ichi_conv": conv, "ichi_base": base,
        "ichi_lead_a": lead_a, "ichi_lead_b": lead_b,
    }
    for n in (5, 10, 20, 30, 50, 100, 200):
        series[f"ema{n}"], series[f"sma{n}"] = ema(closes, n), sma(closes, n)
    ema13 = ema(closes, 13)
    values = {name: _last(s) for name, s in series.items()}
    values["bear"] = None if ema13[-1] is None else lows[-1] - ema13[-1]
    values["bear1"] = None if ema13[-2] is None else lows[-2] - ema13[-2]
    for name in ("rsi", "stoch_k", "stoch_d", "cci", "plus_di", "minus_di", "ao", "mom", "wr", "bbp"):
        values[name + "1"] = _last(series[name], 1)
    values["ao2"] = _last(series["ao"], 2)
    values["close"] = closes[-1]
    return values


def compute_ta(candles):
    """Full rating for one timeframe, shaped like tradingview_ta's output plus the legacy
    keys the scanner and snapshots read (rsi, macd, adx, ema_20/50/200, bb_*).

    Returns None when there are too few candles for a trustworthy rating."""
    if not candles or len(candles) < MIN_CANDLES:
        return None
    v = compute_values(candles)
    if any(x is None for x in v.values()):
        return None
    osc, ma = oscillator_votes(v), moving_average_votes(v)
    summary, _ = _tally({**osc, **ma})
    osc_summary, _ = _tally(osc)
    ma_summary, _ = _tally(ma)

    closes = [float(c[4]) for c in candles]
    window = closes[-20:]
    basis = sum(window) / 20
    std = sqrt(sum((x - basis) ** 2 for x in window) / 20)   # population stdev, as TradingView
    return {
        "summary": summary,
        "oscillators": {**osc_summary, "COMPUTE": osc},
        "moving_averages": {**ma_summary, "COMPUTE": ma},
        "rsi": round(v["rsi"], 2),
        "macd": round(v["macd"], 4),
        "macd_signal": round(v["macd_signal"], 4),
        "adx": round(v["adx"], 2),
        "ema_20": round(v["ema20"], 2),
        "ema_50": round(v["ema50"], 2),
        "ema_200": round(v["ema200"], 2),
        "bb_upper": round(basis + 2 * std, 2),
        "bb_lower": round(basis - 2 * std, 2),
        "bb_basis": round(basis, 2),
        "source": "local",
    }
