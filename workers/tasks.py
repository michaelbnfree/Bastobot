import ollama
from redis import Redis
from rq import get_current_job
import os

redis_client = Redis(host='localhost', port=6379)

# 1. This handles your TEXT messages
def process_task(message: str):
    # Determine which model to use (Triage)
    model_name = "0xroyce/plutus" if any(word in message.lower() for word in ["btc", "bitcoin", "market"]) else "llama3"
    
    response = ollama.generate(model=model_name, prompt=message)
    
    job = get_current_job()
    redis_client.setex(f"result:{job.id}", 3600, response['response'])

# 2. This handles your PHOTOS
def process_vision_task(image_path: str, prompt: str):
    with open(image_path, 'rb') as img:
        response = ollama.generate(
            model='moondream',
            prompt=prompt,
            images=[img.read()]
        )
    
    job = get_current_job()
    redis_client.setex(f"result:{job.id}", 3600, response['response'])
    
    # Clean up the image from the VPS
    if os.path.exists(image_path):
        os.remove(image_path)

