import os
import urllib.parse
import base64
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Flask app initialization
app = Flask(__name__)

# Configs
TOKEN = os.getenv("TELEGRAM_TOKEN", "8772577579:AAGwh5SabsaB26fgMGm9vO9FBnFtCwn37KQ")
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")

# Telegram Application Setup
tg_app = Application.builder().token(TOKEN).build()

# Helper: URL Decode Logic
def decode_url(full_url: str) -> str:
    parsed_url = urllib.parse.urlparse(full_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    
    if 's' not in query_params:
        return "⚠️ Link me '?s=' parameter nahi mila."
    
    encoded_string = query_params['s'][0]
    try:
        decoded_bytes = base64.b64decode(encoded_string)
        return decoded_bytes.decode('utf-8')
    except Exception as e:
        return f"❌ Decode error: {str(e)}"

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot active hai! Base64 parameter wala URL bhejein.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.strip()
    if user_text.startswith("http"):
        result = decode_url(user_text)
        await update.message.reply_text(f"**Decoded Result:**\n`{result}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("Kripya ek valid URL bhejein.")

# Register Handlers
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Variable to track initialization state
is_initialized = False

async def main_init():
    global is_initialized
    if not is_initialized:
        await tg_app.initialize()
        if WEBHOOK_URL:
            webhook_endpoint = f"{WEBHOOK_URL}/{TOKEN}"
            await tg_app.bot.set_webhook(url=webhook_endpoint)
            print(f"Webhook successfully set to: {webhook_endpoint}")
        is_initialized = True

# Flask Routes (Synchronous for Flask stability)
@app.route("/")
def home():
    return "Bot is running on Render with Flask!"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """Telegram webhook handler without Flask-level async conflicts"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Initialize bot if not done yet
    if not is_initialized:
        loop.run_until_complete(main_init())
        
    update = Update.de_json(request.get_json(force=True), tg_app.bot)
    loop.run_until_complete(tg_app.process_update(update))
    loop.close()
    
    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
