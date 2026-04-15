import os
import requests
from dotenv import load_dotenv
from skills.trading import get_btc_analysis

# Load the keys from your .env
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

OR_KEY = os.getenv("OPENROUTER_API_KEY")

def process_task(prompt):
    # STEP 1: Check if Bairry needs to look at the market
    market_context = ""
    if any(word in prompt.lower() for word in ["btc", "bitcoin", "price", "market", "trade"]):
        data = get_btc_analysis()
        market_context = f"\n[LIVE MARKET DATA]: {data}"

    # STEP 2: The "Super-Brain" Decision
    # We send the request to OpenRouter
    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OR_KEY}"},
        json={
            "model": "anthropic/claude-3.5-sonnet", # The "Ivy League" brain
            "messages": [
                {
                    "role": "system", 
                    "content": "You are Bairry, a sovereign AI agent. You have a background in CTO operations and crypto. Use the provided market data to give concise, sharp analysis."
                },
                {"role": "user", "content": f"{prompt} {market_context}"}
            ]
        }
    )
    
    try:
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Barry's brain stalled: {str(e)}"
