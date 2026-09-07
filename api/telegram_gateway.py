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
from dotenv import load_dotenv

sys.path.insert(0, '/root/bastobot')
load_dotenv('/root/bastobot/.env')

telebot.apihelper.READ_TIMEOUT = 90

_redis = redis.Redis(host='localhost', port=6379, db=0)


def _ack_message(prompt, category):
    """Return acknowledgment based on category and prompt content.

    Three tiers:
    1. Snapshots/trade setups → explicit "give me a few minutes" warning
    2. Financial API calls → rolling average time estimate (warn if > 30s)
    3. Non-financial quick queries → no message (typing dots only)
    """
    slow_keywords = ["snapshot", "breakdown", "overview", "trade idea", "trade update", "trade setup"]

    try:
        # Tier 1: Snapshots/trade setups (explicit warning)
        if category == "financial" and any(w in prompt.lower() for w in slow_keywords):
            return "⏳ Give me a few minutes (financial - verified snapshot)..."

        # Tier 2: Financial API calls (show rolling average, warn if slow)
        if category == "financial":
            from workers.tasks import get_avg_timing
            avg = get_avg_timing(category)
            if avg is not None:
                if avg > 30:  # If averaging > 30s, warn
                    return f"⏳ Give me a few minutes (financial)..."
                elif avg > 5:  # If 5-30s, show estimate
                    return f"⏳ On it... (~{int(avg)}s, financial)"
            return None  # No message for very fast financial queries

        # Tier 3: Non-financial (no message, typing indicator is enough)
        return None

    except Exception:
        return None  # Default to no message on error


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not set in environment")
    sys.exit(1)

AUTHORIZED_ID = 298886049
API_BASE = "http://127.0.0.1:18790"
bot = telebot.TeleBot(TOKEN)

print("Barry is awake and listening...")


def _send_long(chat_id, text, chunk_size=4000):
    """Send a message, splitting into chunks if it exceeds Telegram's 4096-char limit."""
    for i in range(0, len(text), chunk_size):
        bot.send_message(chat_id, text[i:i + chunk_size])


def keep_typing(chat_id, stop_event):
    """Send typing action immediately and every 4 seconds until stop_event is set."""
    try:
        result = bot.send_chat_action(chat_id, "typing")
        print(f"[TYPING] Sent initial typing indicator for {chat_id}, result={result}")
    except Exception as e:
        print(f"[TYPING] Failed to send initial: {e}")

    while not stop_event.is_set():
        # Wait 4 seconds or wake up early if stop_event is triggered
        if stop_event.wait(timeout=4.0):
            break
        try:
            result = bot.send_chat_action(chat_id, "typing")
            print(f"[TYPING] Refreshed typing indicator for {chat_id}, result={result}")
        except Exception as e:
            print(f"[TYPING] Failed to refresh: {e}")


def poll_and_reply(job_id, chat_id):
    stop_typing_event = threading.Event()

    # Start typing indicator in background
    typing_thread = threading.Thread(
        target=keep_typing,
        args=(chat_id, stop_typing_event),
        daemon=True
    )
    typing_thread.start()
    print(f"[POLL] Started typing thread for job {job_id} in chat {chat_id}")

    try:
        for _ in range(120):  # 10 min at 5s intervals
            time.sleep(5)
            try:
                res = requests.get(f"{API_BASE}/result/{job_id}", timeout=5)
                data = res.json()
                if data.get("status") == "complete":
                    stop_typing_event.set()
                    typing_thread.join(timeout=1)
                    _send_long(chat_id, data["response"])
                    return
                if data.get("status") in ("failed", "error"):
                    stop_typing_event.set()
                    typing_thread.join(timeout=1)
                    bot.send_message(chat_id, f"❌ Job failed: {data.get('message', 'unknown error')}")
                    return
            except Exception:
                pass

        # Timeout reached
        stop_typing_event.set()
        typing_thread.join(timeout=1)
        bot.send_message(chat_id, "⏱ Request timed out.")
    finally:
        stop_typing_event.set()
        typing_thread.join(timeout=1)


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
        ack = _ack_message(message.caption or "", data.get('category', 'vision'))
        if ack:
            bot.reply_to(message, ack)
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
    bot.reply_to(
        message,
        "Exchange kill-switch control is handled by the canonical Barry engine, not BastoBot."
    )


@bot.message_handler(commands=['resume'])
def handle_resume(message):
    if message.from_user.id != AUTHORIZED_ID:
        return
    bot.reply_to(
        message,
        "Exchange resume control is handled by the canonical Barry engine, not BastoBot."
    )


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
    bot.reply_to(
        message,
        "Risk status is owned by the canonical Barry engine. BastoBot is limited to UI, research, and proposal emission."
    )


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
            # Start typing indicator immediately, then send ack
            threading.Thread(
                target=poll_and_reply,
                args=(data["job_id"], message.chat.id),
                daemon=True
            ).start()
            time.sleep(0.5)  # Give typing thread a moment to start
            ack = _ack_message(message.text, data.get('category', 'queued'))
            if ack:
                bot.reply_to(message, ack)
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
    import time
    time.sleep(1)  # Wait for webhook to be deleted
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
