import re

from fastapi import FastAPI, Request
from redis import Redis
from rq import Queue
from api.routes import router as result_router

app = FastAPI(title="BastoBot Gateway")
app.include_router(result_router)

redis_conn = Redis(host='localhost', port=6379)
q = Queue('fast', connection=redis_conn)

EXPLICIT_FINANCIAL_PATTERNS = [
    # Direct bot/scanner/trade commands
    r"^(scan|watch|unwatch|hot trades|top trades|top setups|open trades|my trades|positions|pnl)\b",

    # Explicit trade-entry / management commands
    r"^(trade|enter trade|monitor|close trade)\b",

    # Common crypto tickers and stablecoins
    r"\b(btc|eth|sol|hype|xrp|bnb|doge|sui|near|avax|usdc|usdt)\b",

    # Crypto/trading-specific language
    r"\b(crypto|chart|long|short|leverage|funding|liquidation|perp|perps|futures|rsi|macd|support|resistance)\b",

    # Contextual market phrases only; avoid casual phrases like "farmers market"
    r"\b(crypto market|market structure|market update|market scan|market setup)\b",
]

def classify(msg: str) -> str:
    msg_lower = msg.strip().lower()

    if any(re.search(pattern, msg_lower) for pattern in EXPLICIT_FINANCIAL_PATTERNS):
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
