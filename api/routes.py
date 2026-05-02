from fastapi import APIRouter
from redis import Redis
from rq.job import Job

router = APIRouter()
redis_conn = Redis(host='localhost', port=6379)


@router.get("/result/{job_id}")
async def get_result(job_id: str):
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        if job.is_finished:
            return {"status": "complete", "response": job.result}
        if job.is_failed:
            return {"status": "failed", "message": str(job.exc_info)}
        return {"status": str(job.get_status())}
    except Exception:
        return {"status": "error", "message": "Job not found"}
