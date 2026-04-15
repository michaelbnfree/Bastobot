from tradingview_ta import TA_Handler, Interval

def get_btc_analysis():
    # Barry's eyes on the Binance BTC/USDT 1-hour chart
    handler = TA_Handler(
        symbol="BTCUSDT",
        screener="crypto",
        exchange="BINANCE",
        interval=Interval.INTERVAL_1_HOUR
    )
    
    try:
        analysis = handler.get_analysis()
        # We strip the complex data down to the essentials Barry needs to think
        return {
            "summary": analysis.summary, # Overall: BUY, SELL, NEUTRAL
            "rsi": analysis.indicators["RSI"],
            "macd": analysis.indicators["MACD.macd"],
            "adx": analysis.indicators["ADX"]
        }
    except Exception as e:
        return f"Market Data Error: {str(e)}"
