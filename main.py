import os
import urllib.parse
import base64
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Flask app initialization
app = Flask(__name__)

# Configs
TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render automatically ye URL provide karta hai

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

# Flask Routes
@app.route("/")
def home():
    return "Bot is running on Render with Flask!"

@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    """Telegram se aane wale updates ko handle karne ke liye route"""
    update = Update.de_json(request.get_json(force=True), tg_app.bot)
    await tg_app.process_update(update)
    return "ok", 200

if __name__ == "__main__":
    import asyncio
    
    # Render port dynamic deta hai
    port = int(os.environ.get("PORT", 5000))
    
    # Webhook setup function
    async def setup_webhook():
        await tg_app.initialize()
        if WEBHOOK_URL:
            webhook_endpoint = f"{WEBHOOK_URL}/{TOKEN}"
            await tg_app.bot.set_webhook(url=webhook_endpoint)
            print(f"Webhook set to: {webhook_endpoint}")

    asyncio.run(setup_webhook())
    app.run(host="0.0.0.0", port=port)

