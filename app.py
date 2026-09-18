import os
import json
import time
import uuid
import random
import asyncio
import sqlite3
import threading
import aiohttp
import requests
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8772577579:AAGP6OKPBcY6OIwb48OS4nAWM00LVIM9imE")
DB_FILE = "shopsy_sessions.db"
GAMES_LIST = ["ludo", "match-3", "city-builder", "goods-triple", "runner-3d", "nazaria"]

USER_STATES = {}
app = Flask(__name__)

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            mobile TEXT PRIMARY KEY,
            account_id TEXT,
            tokens TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def load_sessions():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT mobile, account_id, tokens FROM sessions")
    rows = cursor.fetchall()
    conn.close()
    sessions = {}
    for row in rows:
        sessions[row[0]] = {"account_id": row[1], "tokens": json.loads(row[2])}
    return sessions

def save_session(mobile, account_id, tokens):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO sessions (mobile, account_id, tokens) VALUES (?, ?, ?)",
        (mobile, account_id, json.dumps(tokens))
    )
    conn.commit()
    conn.close()

# --- ASYNC SHOPSY BLAST ENGINE ---
async def prepare_and_wait(session, games_url, game_id, account_id, headers, fire_trigger):
    start_payload = {
        "requestMethod": "POST",
        "routeUri": "game/game-started",
        "payload": {"userId": account_id, "gameId": game_id}
    }
    try:
        async with session.post(games_url, headers=headers, json=start_payload) as start_req:
            if start_req.status != 200: return 0
            start_res = await start_req.json()
            
            # Fix: extract gameSessionId safely
            data = start_res.get("data", {})
            game_session_id = data.get("sessionId") or data.get("gameSessionId")
            if not game_session_id: return 0

        gems_count = random.randint(1500, 5000)
        play_time = random.randint(85, 110)
        
        end_payload = {
            "requestMethod": "POST",
            "routeUri": "game/game-ended",
            "payload": {
                "userId": account_id,
                "gameId": game_id,
                "sessionId": game_session_id,
                "gemsEarned": gems_count,
                "playTimeInSec": play_time
            }
        }
        await fire_trigger.wait()
        async with session.post(games_url, headers=headers, json=end_payload) as end_req:
            if end_req.status == 200:
                end_res = await end_req.json()
                res_data = end_res.get("data", {})
                return res_data.get("coinsEarnedForGame", 0) or res_data.get("coinsClaimed", 0) or res_data.get("rewardCoins", 0)
    except Exception:
        pass
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

# --- UI KEYBOARD BUILDERS ---
def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Login New Mobile", callback_data="btn_login"), InlineKeyboardButton("💥 Blast Engine", callback_data="btn_blast_menu")],
        [InlineKeyboardButton("📱 Saved Accounts", callback_data="view_accounts"), InlineKeyboardButton("⚡ Help", callback_data="view_help")]
    ])

def get_cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Operation", callback_data="main_menu")]])

# --- TELEGRAM COMMAND & CALLBACK HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USER_STATES.pop(user_id, None)
    
    msg = (
        "✨ *WELCOME TO SHOPSY ULTRA BLASTER* ✨\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 *Automated Multi-Account Engine*\n\n"
        "Neeche diye gaye buttons dwara bot ko operate karein:"
    )
    
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())
    elif update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "main_menu":
        USER_STATES.pop(user_id, None)
        await start_command(update, context)

    elif query.data == "btn_login":
        USER_STATES[user_id] = {"step": "AWAITING_MOBILE"}
        await query.edit_message_text(
            "📲 *LOGIN PROCESS*\n\nKripya apna 10-digit Shopsy Mobile Number send karein:\n\n_Example: 9876543210_",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard()
        )

    elif query.data == "btn_blast_menu":
        sessions = load_sessions()
        if not sessions:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Account Now", callback_data="btn_login")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
            ])
            await query.edit_message_text("❌ *Koi saved account nahi mila!*\nPehle login karke account add karein.", parse_mode="Markdown", reply_markup=keyboard)
            return

        keyboard = []
        for mobile in sessions.keys():
            keyboard.append([InlineKeyboardButton(f"💥 Blast: {mobile}", callback_data=f"exec_blast_{mobile}")])
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])

        await query.edit_message_text(
            "🚀 *SELECT ACCOUNT TO BLAST*\n\nNeeche diye gaye accounts me se select karein:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("exec_blast_"):
        mobile_number = query.data.replace("exec_blast_", "")
        await run_blast_process(query.message, mobile_number, is_callback=True)

    elif query.data == "view_accounts":
        sessions = load_sessions()
        if not sessions:
            msg = "📂 *NO SAVED ACCOUNTS FOUND*"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Account", callback_data="btn_login")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
            ])
        else:
            accs = "\n".join([f"• `{m}`" for m in sessions.keys()])
            msg = f"📑 *SAVED SESSIONS:*\n\n{accs}"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]])

        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)

    elif query.data == "view_help":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]])
        help_msg = (
            "🛠 *GUIDE*\n\n"
            "1️⃣ *Login Button* click karke number enter karein aur OTP verification karein.\n"
            "2️⃣ *Blast Engine* select karke target account par automatic claim script run karein."
        )
        await query.edit_message_text(help_msg, parse_mode="Markdown", reply_markup=keyboard)

# --- SHOPSY AUTH FUNCTIONS ---
def send_otp_request(mobile_number):
    device_id = uuid.uuid4().hex
    auth_url = "https://1.rome.api.flipkart.net/1/action/view"
    
    headers = {
        "FK-TENANT-ID": "SHOPSY",
        "business": "reseller",
        "X-PARTNER-CONTEXT": '{"source":"reseller"}',
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "okhttp/4.9.2",
        "X-Layout-Version": '{"appVersion":"910000","frameworkVersion":"1.0"}',
        "X-User-Agent": f"Mozilla/5.0 (Linux; Android 16; CPH2585 Build/TP1A.220905.001) FKUA/Retail/2291175/Android/Mobile (OnePlus/CPH2585/{device_id})"
    }

    payload_1 = {
        "actionRequestContext": {
            "type": "LOGIN_IDENTITY_VERIFY_SHOPSY2",
            "loginId": mobile_number,
            "loginIdPrefix": "+91",
            "phoneNumberFormat": "E164",
            "addAppHash": True,
            "loginType": "MOBILE",
            "verificationType": "OTP",
            "sourceContext": "Account"
        }
    }

    res = requests.post(auth_url, headers=headers, json=payload_1)
    res_json = res.json()
    action_context = res_json.get('RESPONSE', {}).get('actionResponseContext', {})
    
    req_id = action_context.get('requestId')
    sess = res_json.get("SESSION", {})
    
    if "at" in sess: headers["at"] = sess["at"]
    if "sn" in sess: headers["sn"] = sess["sn"]

    return req_id, headers, device_id

def verify_otp_request(mobile, otp_code, req_id, saved_headers):
    auth_url = "https://1.rome.api.flipkart.net/1/action/view"

    payload_2 = {
        "actionRequestContext": {
            "type": "LOGIN_SHOPSY2",
            "loginId": mobile,
            "loginIdPrefix": "+91",
            "otp": str(otp_code),
            "otpRequestId": req_id,
            "phoneNumberFormat": "E164",
            "loginType": "MOBILE",
            "verificationType": "OTP",
            "sourceContext": "Account"
        }
    }

    res = requests.post(auth_url, headers=saved_headers, json=payload_2)
    res_data = res.json()
    
    session_data = res_data.get("SESSION", {})
    account_id = session_data.get("accountId") or res_data.get("RESPONSE", {}).get("actionResponseContext", {}).get("accountId")
    access_token = session_data.get("at")

    if account_id and access_token:
        tokens = {
            "at": access_token,
            "sn": session_data.get("sn", saved_headers.get("sn")),
            "secureToken": session_data.get("secureToken", saved_headers.get("secureToken")),
            "vid": session_data.get("vid", saved_headers.get("X-Visit-Id"))
        }
        return True, account_id, tokens
    return False, None, None

# --- TEXT INPUT INTERCEPTOR ---
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in USER_STATES:
        return

    current_state = USER_STATES[user_id]
    step = current_state.get("step")

    if step == "AWAITING_MOBILE":
        mobile_number = text
        try:
            req_id, headers, device_id = send_otp_request(mobile_number)
            if not req_id:
                await update.message.reply_text("⛔ *Failed to send OTP!* Number check karein ya rate limit hit hui hai.", parse_mode="Markdown", reply_markup=get_cancel_keyboard())
                return

            USER_STATES[user_id] = {
                "step": "AWAITING_OTP",
                "mobile": mobile_number,
                "req_id": req_id,
                "headers": headers,
                "device_id": device_id
            }
            await update.message.reply_text(
                f"📲 *OTP Sent to `{mobile_number}`*\n\nAb WhatsApp / SMS par aaya hua **OTP code enter karein**:",
                parse_mode="Markdown",
                reply_markup=get_cancel_keyboard()
            )
        except Exception:
            await update.message.reply_text("❌ Connection error while requesting OTP.", reply_markup=get_cancel_keyboard())

    elif step == "AWAITING_OTP":
        otp_code = text
        state = USER_STATES[user_id]

        success, account_id, tokens = verify_otp_request(state["mobile"], otp_code, state["req_id"], state["headers"])

        if success:
            save_session(state["mobile"], account_id, tokens)
            del USER_STATES[user_id]
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💥 Execute Blast Now", callback_data=f"exec_blast_{state['mobile']}")],
                [InlineKeyboardButton("🏠 Main Dashboard", callback_data="main_menu")]
            ])
            await update.message.reply_text(
                f"🎉 *Login Successful!*\nAccount `{state['mobile']}` successfully saved.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text("❌ *Login Failed!* Incorrect OTP ya expired session. Dobara OTP enter karein:", parse_mode="Markdown", reply_markup=get_cancel_keyboard())

# --- RUN BLAST WITH AUTH TOKENS FIX ---
async def run_blast_process(target_msg, mobile_number, is_callback=False):
    sessions = load_sessions()
    if mobile_number not in sessions:
        err_txt = "❌ *Account not found!* Pehle account login karein."
        if is_callback:
            await target_msg.edit_text(err_txt, parse_mode="Markdown", reply_markup=get_main_keyboard())
        else:
            await target_msg.reply_text(err_txt, parse_mode="Markdown", reply_markup=get_main_keyboard())
        return

    status_text = "🚀 *Executing High-Speed Claim Engine...*"
    if is_callback:
        await target_msg.edit_text(status_text, parse_mode="Markdown")
        status_msg = target_msg
    else:
        status_msg = await target_msg.reply_text(status_text, parse_mode="Markdown")

    data = sessions[mobile_number]
    account_id = data["account_id"]
    tokens = data.get("tokens", {})

    games_url = "https://1.rome.api.flipkart.net/1/shopsy/games"
    device_id = uuid.uuid4().hex
    
    # Authenticated headers set karein
    games_headers = {
        "FK-TENANT-ID": "SHOPSY",
        "business": "reseller",
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "okhttp/4.9.2",
        "x-user-agent": f"Mozilla/5.0 (Linux; Android 16; CPH2585 Build/TP1A.220905.001) FKUA/Retail/2291175/Android/Mobile (OnePlus/CPH2585/{device_id})",
        "at": tokens.get("at", ""),
        "sn": tokens.get("sn", "")
    }

    try:
        requests.post(games_url, headers=games_headers, json={"requestMethod": "GET", "routeUri": "user/get-user", "payload": {"userId": account_id, "userName": "User"}})
        requests.post(games_url, headers=games_headers, json={"requestMethod": "POST", "routeUri": "gullak/claim-gullak", "payload": {"userId": account_id}})
    except Exception:
        pass

    queued_tasks = list(GAMES_LIST)
    total_coins = await execute_async_blast(games_url, account_id, games_headers, queued_tasks, max_threads=800)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💥 Blast Another Account", callback_data="btn_blast_menu")],
        [InlineKeyboardButton("🏠 Main Dashboard", callback_data="main_menu")]
    ])
    await status_msg.edit_text(
        f"💎 *BLAST COMPLETED*\n\n📱 Mobile: `{mobile_number}`\n🪙 Coins Claimed: `+{total_coins}`",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# --- COMMAND COMPATIBILITY ENGINE ---
async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USER_STATES[user_id] = {"step": "AWAITING_MOBILE"}
    await update.message.reply_text("📲 Kripya 10-digit Shopsy Mobile Number send karein:", parse_mode="Markdown", reply_markup=get_cancel_keyboard())

async def otp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in USER_STATES or USER_STATES[user_id].get("step") != "AWAITING_OTP":
        await update.message.reply_text("❌ Run `/login` or click Login Button first.", parse_mode="Markdown")
        return
    if context.args:
        update.message.text = context.args[0]
        await handle_text_input(update, context)

async def blast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/blast <mobile>`", parse_mode="Markdown")
        return
    mobile_number = context.args[0].strip()
    await run_blast_process(update.message, mobile_number, is_callback=False)

async def accounts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions = load_sessions()
    if not sessions:
        msg = "📂 *NO SAVED ACCOUNTS FOUND*"
    else:
        accs = "\n".join([f"• `{m}`" for m in sessions.keys()])
        msg = f"📑 *SAVED SESSIONS:*\n\n{accs}"

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)

# --- FLASK SERVER FOR RENDER (BACKGROUND THREAD) ---
@app.route("/")
def home():
    return "Shopsy Bot Service Active & Healthy!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# --- TELEGRAM BOT (MAIN THREAD) ---
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("login", login_command))
    bot_app.add_handler(CommandHandler("otp", otp_command))
    bot_app.add_handler(CommandHandler("blast", blast_command))
    bot_app.add_handler(CommandHandler("accounts", accounts_command))
    
    bot_app.add_handler(CallbackQueryHandler(callback_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook?drop_pending_updates=true")
    except Exception:
        pass

    print("Bot Main Thread par Polling start kar raha hai...")
    bot_app.run_polling(drop_pending_updates=True)

