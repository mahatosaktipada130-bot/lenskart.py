#!/usr/bin/env python3
"""
Lenskart "Run For Frame" - TELEGRAM BOT VERSION
Cloud/Render friendly: Telegram se phone & OTP input leta hai.
"""

import os
import json
import random
import time
import uuid
import hashlib
import base64
import requests
from datetime import datetime

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# Render Environment Variable se bot token uthayega
TELEGRAM_BOT_TOKEN = os.getenv("8544323418:AAEP2BJACBmCYan6tdnnMnQqtd0nvIsQQ7o", "8544323418:AAEP2BJACBmCYan6tdnnMnQqtd0nvIsQQ7o")

BASE = "https://api-gateway.juno.lenskart.com"

BRANDS = ["xiaomi", "realme", "samsung", "oneplus", "oppo", "vivo"]
MODELS = {
    "xiaomi": ["Mi 11X", "Redmi Note 10", "Mi 10", "Poco X3"],
    "realme": ["RMX3031", "RMX3370", "RMX3360", "RMX3263"],
    "samsung": ["SM-G998B", "SM-G991B", "SM-A526B", "SM-M515F"],
    "oneplus": ["LE2115", "LE2125", "KB2001", "IN2015"],
    "oppo": ["CPH2207", "CPH2249", "CPH2217"],
    "vivo": ["V2024", "V2036", "V2041", "V2115"]
}
ANDROID_VERSIONS = ["13", "14"]

WAITING_PHONE, WAITING_OTP = range(2)

class LenskartFakeDevice:
    def __init__(self, phone: str, phone_code: str = "+91"):
        self.phone = phone
        self.phone_code = phone_code
        self.brand = random.choice(BRANDS)
        self.model = random.choice(MODELS.get(self.brand, ["RMX3031"]))
        self.android_version = random.choice(ANDROID_VERSIONS)
        self.udid = uuid.uuid4().hex[:16]
        self.advertising_id = str(uuid.uuid4())
        self.build_version = f"TP1A.220905.00{random.randint(1,9)}"
        self.session_token = None
        self.auth_token = None
        self.user_id = None
        self.customer_type = "EXISTING"
        self.s = requests.Session()
        self.x_assertion = self.generate_x_assertion()
        
    def generate_x_assertion(self):
        device_data = f"{self.udid}:{self.advertising_id}:{self.brand}:{self.model}:{self.phone}"
        hash_obj = hashlib.sha256(device_data.encode())
        assertion = base64.b64encode(hash_obj.digest()).decode('utf-8')
        assertion = assertion.replace('+', '-').replace('/', '_')
        while len(assertion) < 100:
            assertion += random.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        return assertion[:100]
        
    def base_headers(self) -> dict:
        h = {
            "Content-Type": "application/json; charset=UTF-8",
            "api_key": "valyoo123",
            "x-api-client": "android",
            "x-app-version": "5.8.2 (260713001)",
            "appversion": "5.8.2 (260713001)",
            "X-Build-Version": "260713001",
            "x-country-code": "IN",
            "x-accept-language": "en",
            "x-customer-type": self.customer_type,
            "udid": self.udid,
            "uniqueId": self.advertising_id[:16],
            "brand": self.brand,
            "model": self.model,
            "x-b3-traceid": str(int(time.time() * 1000)),
            "User-Agent": f"Dalvik/2.1.0 (Linux; U; Android {self.android_version}; {self.model} Build/{self.build_version})",
        }
        if self.phone:
            h["x-customer-phone"] = self.phone
            h["x-customer-phone-code"] = self.phone_code.replace("+", "")
        if self.session_token:
            h["x-session-token"] = self.session_token
        if self.x_assertion:
            h["x-assertion"] = self.x_assertion
        return h

    def post(self, path, body=None, params=None):
        url = f"{BASE}{path}"
        if params:
            url += "?" + "&".join([f"{k}={v}" for k, v in params.items()])
        return self.s.post(url, headers=self.base_headers(), json=body, timeout=30)

    def create_session(self):
        r = self.post("/v2/sessions", {})
        if r.status_code == 200:
            self.session_token = r.json().get("result", {}).get("id")
            return True
        return False

    def send_otp(self):
        if not self.session_token:
            return False
        body = {"phoneCode": self.phone_code, "telephone": self.phone}
        r = self.post("/v3/customers/sendOtp", body)
        if r.status_code == 200:
            res = r.json().get("result") or {}
            self.customer_type = "NEW" if res.get("isNewUser") else "EXISTING"
            return True
        return False

    def verify_otp(self, code: str):
        body = {"code": code, "phoneCode": self.phone_code, "telephone": self.phone}
        r = self.post("/v2/customers/authenticate/mobile", body)
        if r.status_code == 200:
            res = r.json().get("result") or {}
            self.auth_token = res.get("token")
            self.user_id = res.get("user_id")
            if self.auth_token:
                self.session_token = self.auth_token
                return True
        return False

    def claim_reward(self, steps: int = 30000):
        DAY_MS = 86400000
        now_utc_ms = int(time.time() * 1000)
        now_ist_ms = now_utc_ms + (5.5 * 3600 * 1000)
        today_midnight_utc = ((now_ist_ms // DAY_MS) * DAY_MS) - (5.5 * 3600 * 1000)
        
        payload = [{"distance": 0.0, "steps": 0, "timestamp": int(today_midnight_utc - i * DAY_MS)} for i in range(6, 0, -1)]
        payload.append({"distance": 0.0, "steps": steps, "timestamp": int(today_midnight_utc)})
        
        r = self.post("/v2/customers/bff/campaign/eligibility", payload, {"campaignName": "run-for-frame"})
        if r.status_code == 200:
            return r.json().get("result") or {}
        return None

# Telegram Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Apna **10-digit mobile number** enter karein:")
    return WAITING_PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.isdigit() or len(phone) != 10:
        await update.message.reply_text("❌ Sahi 10-digit number dalein.")
        return WAITING_PHONE

    await update.message.reply_text(f"🔄 Session & Fake Device Generate ho raha hai...\n📱 Phone: `{phone}`", parse_mode="Markdown")
    
    device = LenskartFakeDevice(phone)
    if not device.create_session() or not device.send_otp():
        await update.message.reply_text("❌ Error aaya. Phir se `/start` karein.")
        return ConversationHandler.END

    context.user_data["device"] = device
    await update.message.reply_text("🔑 Mobile par aaya **OTP enter karein**:")
    return WAITING_OTP

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp = update.message.text.strip()
    device: LenskartFakeDevice = context.user_data.get("device")

    if not device or not device.verify_otp(otp):
        await update.message.reply_text("❌ Verification Failed! `/start` karke try karein.", parse_mode="Markdown")
        return ConversationHandler.END

    await update.message.reply_text("✅ Login successful! Steps submit ho rahe hain...")
    reward = device.claim_reward(steps=30000)
    
    if reward and reward.get("giftVoucher"):
        msg = (
            "🎉 **REWARD UNLOCKED!** 🎉\n\n"
            f"📱 Phone: `{device.phone}`\n"
            f"🏆 Tier: {reward.get('tier')}\n"
            f"🎫 Voucher: `{reward.get('giftVoucher')}`\n"
            f"📱 Device Fake: {device.brand} ({device.model})"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        err = reward.get("message") if reward else "Claim nahi hua"
        await update.message.reply_text(f"⚠️ Status: {err}")

    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Process canceled.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            WAITING_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()

