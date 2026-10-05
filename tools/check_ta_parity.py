"""Compare the local TradingView-style rating with live TradingView, per indicator vote.

Usage:  python3 tools/check_ta_parity.py [SYMBOL ...]        (default: BTCUSDT ETHUSDT)

For each symbol and timeframe it fetches Binance candles and TradingView's analysis back to
back, overwrites the forming candle with TradingView's own OHLCV so both sides see the same
bar, and prints which indicator values and votes disagree. TradingView rate-limits (HTTP 429),
so calls are spaced out; run it sparingly."""
import sys
import time

import requests
from tradingview_ta import Interval, TA_Handler

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
from skills import ta_local  # noqa: E402

INTERVALS = {"1h": Interval.INTERVAL_1_HOUR, "4h": Interval.INTERVAL_4_HOURS, "1d": Interval.INTERVAL_1_DAY}
VALUE_MAP = {"rsi": "RSI", "stoch_k": "Stoch.K", "cci": "CCI20", "adx": "ADX", "ao": "AO", "mom": "Mom",
             "macd": "MACD.macd", "wr": "W.R", "uo": "UO", "ema200": "EMA200", "sma50": "SMA50"}


def main(symbols):
    agree = total = 0
    for symbol in symbols:
        for name, interval in INTERVALS.items():
            tv = TA_Handler(symbol=symbol, screener="crypto", exchange="BINANCE", interval=interval).get_analysis()
            rows = requests.get("https://api.binance.com/api/v3/klines",
                                params={"symbol": symbol, "interval": name, "limit": 1000}, timeout=15).json()
            candles = [[float(x) for x in r[:6]] for r in rows]
            ind = tv.indicators
            if abs(candles[-1][1] - ind["open"]) > 1e-6 * ind["open"]:
                print(f"{symbol} {name}: candle rolled between calls, skipped")
                continue
            candles[-1][2:6] = [ind["high"], ind["low"], ind["close"], ind["volume"]]
            ta = ta_local.compute_ta(candles)
            votes = {**ta["oscillators"]["COMPUTE"], **ta["moving_averages"]["COMPUTE"]}
            truth = {**tv.oscillators["COMPUTE"], **tv.moving_averages["COMPUTE"]}
            diffs = [f"{k}: local {votes[k]} / TV {truth[k]}" for k in truth if votes.get(k) != truth[k]]
            agree += len(truth) - len(diffs)
            total += len(truth)
            print(f"{symbol} {name}: summary local {ta['summary']['RECOMMENDATION']} {ta['summary']['BUY']}/"
                  f"{ta['summary']['NEUTRAL']}/{ta['summary']['SELL']}  TV {tv.summary['RECOMMENDATION']} "
                  f"{tv.summary['BUY']}/{tv.summary['NEUTRAL']}/{tv.summary['SELL']}  | vote mismatches: {diffs or 'none'}")
            time.sleep(20)
    if total:
        print(f"\nvote agreement: {agree}/{total} = {100 * agree / total:.1f}%")


if __name__ == "__main__":
    main(sys.argv[1:] or ["BTCUSDT", "ETHUSDT"])
