from fastapi import APIRouter
from redis import Redis
from rq.job import Job

router = APIRouter()
redis_conn = Redis(host='localhost', port=6379)

@router.get("/result/{job_id}")
async def get_result(job_id: str):
    # 1. Try to get the finished result from Redis
    result = redis_conn.get(f"result:{job_id}")
    if result:
        return {"status": "complete", "response": result.decode('utf-8')}
    
    # 2. If not in result keys, check the queue status
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        return {"status": job.get_status()}
    except:
        return {"status": "error", "message": "Job not found"}
