import telebot
import requests
import time
import os

TOKEN = "***REDACTED_TELEGRAM_TOKEN***"
AUTHORIZED_ID = 298886049
API_URL = "http://127.0.0.1:18790"
IMG_DIR = "/root/bastobot/temp_images"
os.makedirs(IMG_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(content_types=['photo'], func=lambda m: m.from_user.id == AUTHORIZED_ID)
def handle_photo(m):
    status_msg = bot.reply_to(m, "📥 👁️ Barry is looking...")
    try:
        file_info = bot.get_file(m.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        img_path = os.path.join(IMG_DIR, f"{m.message_id}.jpg")
        with open(img_path, 'wb') as f:
            f.write(downloaded_file)
        
        r = requests.post(f"{API_URL}/query", json={"message": m.caption or "What is this?", "image_path": img_path})
        jid = r.json().get("job_id")
        
        start_time = time.time()
        while True:
            time.sleep(2)
            res = requests.get(f"{API_URL}/result/{jid}").json()
            if res.get("status") == "complete":
                bot.edit_message_text(f"✅ Vision:\n\n{res.get('response')}", m.chat.id, status_msg.message_id)
                break
            if time.time() - start_time > 120:
                bot.edit_message_text("❌ Timeout", m.chat.id, status_msg.message_id)
                break
    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")

@bot.message_handler(func=lambda m: m.from_user.id == AUTHORIZED_ID)
def handle_text(m):
    status_msg = bot.reply_to(m, "🤖 Thinking...")
    try:
        r = requests.post(f"{API_URL}/query", json={"message": m.text})
        jid = r.json().get("job_id")
        
        start_time = time.time()
        while True:
            time.sleep(2)
            res = requests.get(f"{API_URL}/result/{jid}").json()
            if res.get("status") == "complete":
                bot.edit_message_text(f"✅ Response:\n\n{res.get('response')}", m.chat.id, status_msg.message_id)
                break
            if time.time() - start_time > 60:
                bot.edit_message_text("❌ Timeout", m.chat.id, status_msg.message_id)
                break
    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")

bot.infinity_polling()
