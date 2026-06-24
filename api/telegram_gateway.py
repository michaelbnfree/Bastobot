import telebot
import telebot.apihelper
import os
import sys
import signal
import subprocess
import requests
import threading
import time
import base64
import io
import redis
from PIL import Image

sys.path.insert(0, '/root/bastobot')

telebot.apihelper.READ_TIMEOUT = 90

_redis = redis.Redis(host='localhost', port=6379, db=0)


def _ack_message(category):
    """Return the right acknowledgment based on rolling average job time for this category."""
    try:
        from workers.tasks import get_avg_timing
        avg = get_avg_timing(category)
        if avg is not None and avg > 30:
            return f"⏳ Give me a couple minutes... ({category})"
        if avg is not None and avg > 8:
            return f"⏳ On it... (~{int(avg)}s, {category})"
    except Exception:
        pass
    return f"⏳ On it... ({category})"


TOKEN = "***REDACTED_TELEGRAM_TOKEN***"
AUTHORIZED_ID = 298886049
API_BASE = "http://127.0.0.1:18790"
bot = telebot.TeleBot(TOKEN)

print("Barry is awake and listening...")


def _send_long(chat_id, text, chunk_size=4000):
    """Send a message, splitting into chunks if it exceeds Telegram's 4096-char limit."""
    for i in range(0, len(text), chunk_size):
        bot.send_message(chat_id, text[i:i + chunk_size])


def poll_and_reply(job_id, chat_id):
    for _ in range(120):  # 10 min at 5s intervals
        time.sleep(5)
        try:
            res = requests.get(f"{API_BASE}/result/{job_id}", timeout=5)
            data = res.json()
            if data.get("status") == "complete":
                _send_long(chat_id, data["response"])
                return
            if data.get("status") in ("failed", "error"):
                bot.send_message(chat_id, f"❌ Job failed: {data.get('message', 'unknown error')}")
                return
        except Exception:
            pass
    bot.send_message(chat_id, "⏱ Request timed out.")


@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.from_user.id == AUTHORIZED_ID:
        bot.reply_to(message, "Online and ready. Reply to any message with /save to vault it.")


@bot.message_handler(commands=['save'])
def handle_save_command(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    if message.reply_to_message:
        content = message.reply_to_message.text or "Photo/Media"
        print(f"!!! SAVING TO VAULT: {content}")
        try:
            subprocess.Popen(["python3", "/root/bastobot/api/save_to_notion.py", str(content)])
            bot.reply_to(message, "🚀 Sent to the Vault!")
        except Exception as e:
            bot.reply_to(message, f"❌ Failed to save: {e}")
    else:
        bot.reply_to(message, "⚠️ Reply to a message with /save to vault it.")


@bot.message_handler(content_types=['document'])
def handle_document(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    try:
        doc = message.document
        if doc.mime_type != 'application/pdf':
            bot.reply_to(message, f"📄 Unsupported file type ({doc.mime_type}). Only PDFs for now.")
            return
        file_info = bot.get_file(doc.file_id)
        file_bytes = bot.download_file(file_info.file_path)
        filename = doc.file_name or "document.pdf"
        save_path = f"/root/.openclaw/workspace/{filename}"
        with open(save_path, 'wb') as f:
            f.write(file_bytes)
        size_kb = len(file_bytes) // 1024
        bot.reply_to(message, f"📄 Saved `{filename}` ({size_kb}KB) to workspace. Claude can read it now.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error handling document: {e}")


@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_bytes = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(file_bytes))
        img.thumbnail((1280, 1280), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        caption = message.caption or ""
        res = requests.post(
            f"{API_BASE}/query",
            json={"message": caption, "image_b64": image_b64, "mime_type": "image/jpeg"},
            timeout=15
        )
        data = res.json()
        bot.reply_to(message, _ack_message(data.get('category', 'vision')))
        threading.Thread(
            target=poll_and_reply,
            args=(data["job_id"], message.chat.id),
            daemon=True
        ).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=['kill'])
def handle_kill(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    from skills.active.hyperliquid import set_kill_switch
    bot.reply_to(message, set_kill_switch(True))


@bot.message_handler(commands=['resume'])
def handle_resume(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    from skills.active.hyperliquid import set_kill_switch
    bot.reply_to(message, set_kill_switch(False))


@bot.message_handler(commands=['approve'])
def handle_approve(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /approve <token>")
        return
    token = parts[1]
    key = f"hl:risk:pending:{token}"
    if _redis.exists(key):
        _redis.set(key, "approve")
        bot.reply_to(message, f"✅ Trade {token} approved — executing.")
    else:
        bot.reply_to(message, f"⚠️ No pending trade with token {token}.")


@bot.message_handler(commands=['reject'])
def handle_reject(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /reject <token>")
        return
    token = parts[1]
    key = f"hl:risk:pending:{token}"
    if _redis.exists(key):
        _redis.set(key, "reject")
        bot.reply_to(message, f"🚫 Trade {token} rejected.")
    else:
        bot.reply_to(message, f"⚠️ No pending trade with token {token}.")


@bot.message_handler(commands=['riskstatus'])
def handle_riskstatus(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    from skills.active.hyperliquid import get_risk_status
    s = get_risk_status()
    lines = [
        f"{'🛑' if s['kill_switch'] else '✅'} Kill switch: {'ON' if s['kill_switch'] else 'off'}",
        f"{'🔐' if s['manual_confirm'] else '🤖'} Manual confirm: {'ON' if s['manual_confirm'] else 'off'}",
        f"💰 Max trade: ${s['max_trade_usd']:,.0f}",
        f"📉 Daily loss limit: ${s['daily_loss_limit']:,.0f}",
        f"📊 Today's loss: ${s['today_loss_usd']:,.2f}" if s['today_loss_usd'] is not None else "📊 Today's loss: (no baseline yet)",
        f"🏦 Current equity: ${s['current_equity']:,.2f}" if s['current_equity'] is not None else "🏦 Current equity: unavailable",
    ]
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(func=lambda m: True)
def handle_message(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    try:
        res = requests.post(f"{API_BASE}/query", json={"message": message.text}, timeout=10)
        data = res.json()
        if data.get("category") == "simple":
            bot.reply_to(message, data["response"])
        else:
            bot.reply_to(message, _ack_message(data.get('category', 'queued')))
            threading.Thread(
                target=poll_and_reply,
                args=(data["job_id"], message.chat.id),
                daemon=True
            ).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


_last_telegram_ok = time.time()

def _watchdog():
    """Exit if Telegram has been unreachable for 10 minutes, triggering systemd restart."""
    global _last_telegram_ok
    while True:
        time.sleep(120)
        try:
            bot.get_me()
            _last_telegram_ok = time.time()
        except Exception as e:
            print(f"[WATCHDOG] get_me failed: {e}")
        if time.time() - _last_telegram_ok > 600:
            print("[WATCHDOG] No successful Telegram contact in 10min — forcing restart")
            os.kill(os.getpid(), signal.SIGTERM)

threading.Thread(target=_watchdog, daemon=True).start()

try:
    bot.delete_webhook()
    print("[STARTUP] Webhook cleared.")
except Exception as e:
    print(f"[STARTUP] delete_webhook failed: {e}")

while True:
    try:
        bot.polling(non_stop=False, timeout=20, long_polling_timeout=15)
    except telebot.apihelper.ApiTelegramException as e:
        if "409" in str(e):
            print(f"[POLLING] Webhook conflict detected — clearing and retrying")
            try:
                bot.send_message(AUTHORIZED_ID, "⚠️ Barry: webhook conflict detected, clearing webhook...")
                bot.delete_webhook()
            except Exception as inner:
                print(f"[POLLING] Failed to clear webhook: {inner}")
        else:
            print(f"[POLLING] Telegram error: {e} — retrying in 5s")
        time.sleep(5)
    except Exception as e:
        print(f"[POLLING] Crashed: {e} — retrying in 5s")
        time.sleep(5)
