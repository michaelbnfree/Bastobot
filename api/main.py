from fastapi import FastAPI, Request
import ollama
from redis import Redis
from rq import Queue
from api.routes import router as result_router

app = FastAPI(title="BastoBot Gateway")
# This is the bridge Barry needed:
app.include_router(result_router)

redis_conn = Redis(host='localhost', port=6379)
q = Queue('bastobot_tasks', connection=redis_conn)
SYS_P = "Classify: simple, medium, financial. Financial=BTC, prices, SoyBoy. Reply ONLY with category."

def classify(msg: str):
    try:
        res = ollama.chat(model='smollm2:135m', messages=[{'role': 'system', 'content': SYS_P},{'role': 'user', 'content': msg}])
        cat = res['message']['content'].strip().lower()
        if any(w in msg.lower() for w in ['btc', 'soyboy', 'price', 'trade']): return 'financial'
        return cat if cat in ['simple', 'medium', 'financial'] else 'medium'
    except: return 'medium'

@app.post("/query")
async def handle_query(req: Request):
    body = await req.json()
    msg = body.get("message", "")
    cat = classify(msg)
    if cat == "simple":
        res = ollama.chat(model='smollm2:135m', messages=[{'role': 'user', 'content': msg}])
        return {"category": "simple", "response": res['message']['content']}
    job = q.enqueue('workers.tasks.process_task', msg, cat, job_timeout=600)
    return {"category": cat, "job_id": job.id, "status": "queued"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18790)
