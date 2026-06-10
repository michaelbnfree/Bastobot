from fastapi import FastAPI, Request
from redis import Redis
from rq import Queue
from api.routes import router as result_router

app = FastAPI(title="BastoBot Gateway")
app.include_router(result_router)

redis_conn = Redis(host='localhost', port=6379)
q = Queue('fast', connection=redis_conn)

FINANCIAL_KEYWORDS = [
    'btc', 'eth', 'xion', 'soyboy', 'crypto', 'coin', 'token',
    'price', 'trade', 'trading', 'chart', 'candle', 'market',
    'stock', 'forex', 'futures', 'perpetual', 'long', 'short',
    'rsi', 'macd', 'support', 'resistance', 'breakout', 'bullish', 'bearish',
    'usdt', 'usd', 'leverage', 'liquidat', 'position', 'entry', 'target', 'stop',
    'limit', 'order', 'buy', 'sell', 'signal', 'trend', 'pump', 'dump',
    'wick', 'level', 'setup', 'tp', 'sl', 'pnl', 'profit', 'loss',
    # Scanner / watchlist / trade monitor commands
    'watch', 'unwatch', 'watchlist', 'hot trades', 'top trades', 'top setups',
    'my trades', 'open trades', 'conviction', 'monitor', 'scan',
]

def classify(msg: str) -> str:
    if any(w in msg.lower() for w in FINANCIAL_KEYWORDS):
        return 'financial'
    return 'medium'

@app.post("/query")
async def handle_query(req: Request):
    body = await req.json()
    msg = body.get("message") or ""
    image_b64 = body.get("image_b64")
    mime_type = body.get("mime_type", "image/jpeg")
    cat = "vision" if image_b64 and not msg.strip() else classify(msg)
    job = q.enqueue(
        'workers.tasks.process_task', msg, cat,
        image_b64=image_b64, mime_type=mime_type,
        job_timeout=600,
        result_ttl=3600,
    )
    return {"category": cat, "job_id": job.id, "status": "queued"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18790)
