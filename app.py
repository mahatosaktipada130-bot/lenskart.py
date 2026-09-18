import os
import asyncio
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from google import genai

# Load Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("8376027265:AAFuOeCcDrQ7Ws4WGDkDy3vmpfgJa8iaGCE")
GEMINI_API_KEY = os.getenv("AQ.Ab8RN6IU_a-8qJE50zw0XKTbZnim-0cKC7C2HHlLOXOzv7-6UQ")

# Initialize Flask App & Gemini Client
app = Flask(__name__)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Initialize Telegram Bot Application
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# Command Handler: /start
async def start_command(update: Update, context):
    await update.message.reply_text("Hello! I am your AI assistant powered by Gemini. Ask me anything!")

# Message Handler: Generate AI Response
async def handle_message(update: Update, context):
    user_text = update.message.text
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_text,
        )
        reply = response.text if response.text else "Sorry, I couldn't process that request."
    except Exception as e:
        reply = f"Error generating response: {str(e)}"
    
    await update.message.reply_text(reply)

# Register Handlers
telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Webhook Endpoint for Telegram Updates
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.method == "POST":
        asyncio.run(telegram_app.initialize())
        update = Update.de_json(request.get_json(force=True), telegram_app.bot)
        asyncio.run(telegram_app.process_update(update))
        return jsonify({"status": "ok"}), 200
    return jsonify({"status": "method not allowed"}), 405

@app.route("/")
def home():
    return "Telegram Gemini Bot Server is Running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
