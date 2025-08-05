# --- START OF FINAL, COMPLETE, AND UNIFIED backend/main.py FILE ---

import uvicorn
import json
import hmac
import hashlib
from urllib.parse import parse_qsl, unquote
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import logging
import os
import asyncio
import random
import re
import sys
import signal

import telegram
from telegram.ext import Application
from telegram.request import HTTPXRequest
from telegram.constants import ParseMode
from telegram.error import Forbidden

import pytz
from datetime import datetime
import colorlog
from dotenv import load_dotenv

# --- CONFIGURATION & SETUP ---

# Load environment variables from a .env file if it exists (for local development)
load_dotenv()

# Securely load secrets from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_OWNER_ID = os.getenv("BOT_OWNER_ID")

# Validate that secrets are loaded, otherwise the app cannot run.
if not BOT_TOKEN or not BOT_OWNER_ID:
    raise ValueError("FATAL: BOT_TOKEN and BOT_OWNER_ID must be set in the environment.")
try:
    BOT_OWNER_ID = int(BOT_OWNER_ID)
except (ValueError, TypeError):
    raise ValueError("FATAL: BOT_OWNER_ID must be a valid integer.")

# Colored Logging Setup
log = logging.getLogger()
log.setLevel(logging.INFO)
if not log.handlers:
    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        '%(log_color)s%(levelname)-8s%(reset)s %(blue)s%(asctime)s%(reset)s - %(name)s - %(message)s',
        log_colors={'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow', 'ERROR': 'red', 'CRITICAL': 'red,bg_white'}
    ))
    log.addHandler(handler)
logger = logging.getLogger(__name__)

# Constants
USER_DATA_DIR = "user_data11_refactored"
PROFILE_FILE, FRIENDS_FILE, MESSAGE_HISTORY_FILE, UID_TO_TID_MAP_FILE = "profile.json", "friends.json", "message_history.json", "uid_to_tid.json"
ist = pytz.timezone('Asia/Kolkata')
os.makedirs(USER_DATA_DIR, exist_ok=True)

# In-memory data caches that will be populated on startup
uid_to_tid_map_cache, tid_to_profile_cache, tid_to_friends_cache, tid_to_history_cache = {}, {}, {}, {}


# --- DATA LOGIC (Ported from original bot and integrated) ---

#<editor-fold desc="File I/O and Data Loading">
def get_user_data_path(telegram_id, filename=""):
    folder = os.path.join(USER_DATA_DIR, str(telegram_id))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename) if filename else folder

def _load_json_data_from_file(file_path, default_data=None):
    if default_data is None: default_data = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f: return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSONDecodeError in {file_path}: {e}")
            return default_data
    return default_data

def _save_json_data_to_file(file_path, data):
    try:
        with open(file_path, "w") as f: json.dump(data, f, indent=4)
        return True
    except IOError as e:
        logger.error(f"IOError saving to {file_path}: {e}")
        return False

def save_all_data_to_disk(source="periodic"):
    logger.info(f"Saving all data to disk (source: {source})...")
    _save_json_data_to_file(os.path.join(USER_DATA_DIR, UID_TO_TID_MAP_FILE), uid_to_tid_map_cache)
    for tid, profile in tid_to_profile_cache.items():
        _save_json_data_to_file(get_user_data_path(tid, PROFILE_FILE), profile)
    for tid, friends in tid_to_friends_cache.items():
        _save_json_data_to_file(get_user_data_path(tid, FRIENDS_FILE), friends)
    for tid, history in tid_to_history_cache.items():
        _save_json_data_to_file(get_user_data_path(tid, MESSAGE_HISTORY_FILE), history)
    logger.info("All data saved.")

def load_all_data_into_memory():
    global uid_to_tid_map_cache, tid_to_profile_cache, tid_to_friends_cache, tid_to_history_cache
    logger.info("Loading all user data into memory cache...")
    uid_to_tid_map_cache = _load_json_data_from_file(os.path.join(USER_DATA_DIR, UID_TO_TID_MAP_FILE), {})
    if not os.path.exists(USER_DATA_DIR): return
    for item in os.listdir(USER_DATA_DIR):
        if not item.isdigit(): continue
        tid = int(item)
        user_folder = os.path.join(USER_DATA_DIR, item)
        profile_data = _load_json_data_from_file(os.path.join(user_folder, PROFILE_FILE), {})
        profile_data.setdefault("sent_requests", [])
        profile_data.setdefault("received_requests", [])
        profile_data.setdefault("bio", "") # Ensure bio field exists for older users
        tid_to_profile_cache[tid] = profile_data
        tid_to_friends_cache[tid] = _load_json_data_from_file(os.path.join(user_folder, FRIENDS_FILE), [])
        tid_to_history_cache[tid] = _load_json_data_from_file(os.path.join(user_folder, MESSAGE_HISTORY_FILE), {})
    logger.info(f"Loaded data for {len(tid_to_profile_cache)} users.")
#</editor-fold>

#<editor-fold desc="Helper and Data Access Functions">
def get_current_ist_time_str(): return datetime.now(ist).strftime("%Y-%m-%d %I:%M:%S %p")
def get_relative_time_string(dt_past_str: str) -> str:
    if not dt_past_str: return "never"
    try: dt_past_aware = ist.localize(datetime.strptime(dt_past_str, "%Y-%m-%d %I:%M:%S %p"))
    except (ValueError, TypeError): return "a while ago"
    seconds = int((datetime.now(ist) - dt_past_aware).total_seconds())
    if seconds < 30: return "online"
    elif seconds < 120: return "1m ago"
    elif seconds < 3600: return f"{seconds // 60}m ago"
    elif seconds < 86400: return f"{seconds // 3600}h ago"
    else: return f"{seconds // 86400}d ago"

def get_unique_id_by_tid(telegram_id): return tid_to_profile_cache.get(int(telegram_id), {}).get("unique_id")
def get_telegram_id_by_uid(unique_id): return int(tid) if (tid := uid_to_tid_map_cache.get(str(unique_id))) else None
def get_user_profile_by_tid(telegram_id): return tid_to_profile_cache.get(int(telegram_id))
def get_user_profile_by_uid(unique_id): return tid_to_profile_cache.get(tid) if (tid := get_telegram_id_by_uid(unique_id)) else None
def get_username_by_uid(unique_id): return (p.get("username", "Unknown") if (p:=get_user_profile_by_uid(unique_id)) else "Unknown")
def get_friends_by_uid(user_uid): return tid_to_friends_cache.get(user_tid, []) if (user_tid := get_telegram_id_by_uid(user_uid)) else []
def get_blocked_users_by_tid(telegram_id): return tid_to_profile_cache.get(int(telegram_id), {}).get("blocked_users", [])
def is_friend(user_uid, target_uid): return str(target_uid) in get_friends_by_uid(user_uid)
def has_sent_request(sender_uid, receiver_uid): return (p and str(receiver_uid) in p.get("sent_requests", [])) if (p:=get_user_profile_by_uid(sender_uid)) else False
def has_received_request(receiver_uid, sender_uid): return (p and str(sender_uid) in p.get("received_requests", [])) if (p:=get_user_profile_by_uid(receiver_uid)) else False
#</editor-fold>

#<editor-fold desc="User and Data Modification Functions">
async def update_user_activity(telegram_id):
    if not telegram_id: return
    if profile_data := tid_to_profile_cache.get(int(telegram_id)):
        profile_data["last_active_timestamp"] = get_current_ist_time_str()

def ensure_user_profile_from_web(user: dict):
    telegram_id = int(user.get("id"))
    if profile := tid_to_profile_cache.get(telegram_id): return profile.get("unique_id")
    
    username = user.get("username") or user.get("first_name", f"User_{telegram_id}")
    unique_id = str(random.randint(10000000, 99999999))
    while unique_id in uid_to_tid_map_cache: unique_id = str(random.randint(10000000, 99999999))
    
    new_user_data = {
        "unique_id": unique_id, "telegram_id": telegram_id, "username": username,
        "joined_date": get_current_ist_time_str(), "last_active_timestamp": get_current_ist_time_str(),
        "blocked_users": [], "sent_requests": [], "received_requests": [], "bio": ""
    }
    tid_to_profile_cache[telegram_id] = new_user_data
    uid_to_tid_map_cache[unique_id] = telegram_id
    tid_to_friends_cache.setdefault(telegram_id, [])
    tid_to_history_cache.setdefault(telegram_id, {})
    logger.info(f"New user registered from Mini App: TID {telegram_id}, UID {unique_id}, Username {username}")
    return unique_id

def add_friend_by_uid(user_uid, friend_uid):
    user_tid = get_telegram_id_by_uid(user_uid)
    if not user_tid: return False
    friends_list = tid_to_friends_cache.get(user_tid, [])
    if str(friend_uid) not in friends_list:
        friends_list.append(str(friend_uid))
        return True
    return False

def remove_friend_by_uid(user_uid, friend_to_remove_uid):
    if (user_tid := get_telegram_id_by_uid(user_uid)) and str(friend_to_remove_uid) in tid_to_friends_cache.get(user_tid, []):
        tid_to_friends_cache[user_tid].remove(str(friend_to_remove_uid))
    if (friend_tid := get_telegram_id_by_uid(friend_to_remove_uid)) and str(user_uid) in tid_to_friends_cache.get(friend_tid, []):
        tid_to_friends_cache[friend_tid].remove(str(user_uid))

def remove_pending_request(sender_uid, receiver_uid):
    if (s_profile := get_user_profile_by_uid(sender_uid)) and str(receiver_uid) in s_profile.get("sent_requests", []):
        s_profile["sent_requests"].remove(str(receiver_uid))
    if (r_profile := get_user_profile_by_uid(receiver_uid)) and str(sender_uid) in r_profile.get("received_requests", []):
        r_profile["received_requests"].remove(str(sender_uid))

def block_user_by_tid(telegram_id, uid_to_block):
    if profile := tid_to_profile_cache.get(telegram_id):
        if str(uid_to_block) not in profile.setdefault("blocked_users", []):
            profile["blocked_users"].append(str(uid_to_block))

def unblock_user_by_tid(telegram_id, uid_to_unblock):
    if profile := tid_to_profile_cache.get(telegram_id):
        if str(uid_to_unblock) in profile.get("blocked_users", []):
            profile["blocked_users"].remove(str(uid_to_unblock))

def store_message(sender_tid, receiver_tid, message_text):
    sender_uid, receiver_uid = get_unique_id_by_tid(sender_tid), get_unique_id_by_tid(receiver_tid)
    if not sender_uid or not receiver_uid: return
    message_data = {
        "sender_uid": sender_uid, "receiver_uid": receiver_uid, "text": message_text,
        "timestamp": get_current_ist_time_str(), "reactions": [], "unread": True
    }
    tid_to_history_cache.setdefault(sender_tid, {}).setdefault(str(receiver_uid), []).append({**message_data, "unread": False})
    tid_to_history_cache.setdefault(receiver_tid, {}).setdefault(str(sender_uid), []).append(message_data)

async def send_push_notification(bot: telegram.Bot, receiver_tid: int, text: str):
    try:
        await bot.send_message(chat_id=receiver_tid, text=text, parse_mode=ParseMode.MARKDOWN_V2)
        return True
    except Forbidden:
        logger.warning(f"Push notification failed to TID {receiver_tid}: Bot blocked.")
        return False
    except Exception as e:
        logger.error(f"Push notification failed to TID {receiver_tid}: {e}")
        return False
#</editor-fold>

# --- FASTAPI APPLICATION ---

app = FastAPI()
ptb_app = Application.builder().token(BOT_TOKEN).build()

# CORS Middleware
origins = [
    "https://dreamy-banoffee-9c18ac.netlify.app", 

    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

#<editor-fold desc="Pydantic Models & Security">
class MessagePayload(BaseModel): text: str = Field(..., min_length=1, max_length=4096)
class BioPayload(BaseModel): bio: str = Field("", max_length=150)
class ValidatedUser(BaseModel): id: int; first_name: str; last_name: str | None = None; username: str | None = None

def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    try:
        parsed_data = dict(parse_qsl(unquote(init_data)))
        received_hash = parsed_data.pop("hash", "")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new("WebAppData".encode(), bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash == received_hash:
            return json.loads(parsed_data.get("user", "{}"))
        return None
    except Exception as e:
        logger.error(f"InitData validation error: {e}")
        return None

async def get_current_user(request: Request) -> ValidatedUser:
    init_data = request.headers.get("X-Telegram-Init-Data")
    if not init_data: raise HTTPException(status_code=401, detail="X-Telegram-Init-Data header is missing")

    parsed_init_data = dict(parse_qsl(unquote(init_data)))
    if parsed_init_data.get("query_id") == "MOCK_FOR_LOCAL_DEV":
        logger.warning("Auth bypassed: Using MOCK initData for local development.")
        user_data = json.loads(parsed_init_data.get("user", "{}"))
    else:
        user_data = validate_init_data(init_data, BOT_TOKEN)
        if user_data is None: raise HTTPException(status_code=403, detail="Invalid Telegram InitData")
    
    ensure_user_profile_from_web(user_data)
    await update_user_activity(user_data.get("id"))
    return ValidatedUser(**user_data)
#</editor-fold>

#<editor-fold desc="Lifecycle Events">
@app.on_event("startup")
async def on_startup():
    load_all_data_into_memory()
    logger.info("FastAPI server started, data loaded.")

@app.on_event("shutdown")
def on_shutdown():
    save_all_data_to_disk("shutdown")
    logger.info("FastAPI server shutting down, data saved.")
#</editor-fold>

#<editor-fold desc="API Endpoints">
@app.get("/api/me")
async def get_my_profile(current_user: ValidatedUser = Depends(get_current_user)):
    profile = get_user_profile_by_tid(current_user.id)
    if not profile: raise HTTPException(status_code=404, detail="User profile not found.")
    return JSONResponse(content=profile)

@app.get("/api/profile/{target_uid}")
async def get_user_profile(target_uid: str, current_user: ValidatedUser = Depends(get_current_user)):
    my_uid = get_unique_id_by_tid(current_user.id)
    target_profile = get_user_profile_by_uid(target_uid)
    if not target_profile: raise HTTPException(status_code=404, detail="Target user not found.")

    target_profile["relation"] = {
        "is_me": my_uid == target_uid, "is_friend": is_friend(my_uid, target_uid),
        "is_blocked": target_uid in get_blocked_users_by_tid(current_user.id),
        "sent_request": has_sent_request(my_uid, target_uid),
        "received_request": has_received_request(my_uid, target_uid),
    }
    target_profile["status"] = get_relative_time_string(target_profile.get('last_active_timestamp'))
    return JSONResponse(content=target_profile)

@app.put("/api/me/bio")
async def update_my_bio(payload: BioPayload, current_user: ValidatedUser = Depends(get_current_user)):
    profile = get_user_profile_by_tid(current_user.id)
    if not profile: raise HTTPException(status_code=404, detail="Your user profile could not be found.")
    profile["bio"] = payload.bio
    return JSONResponse(content={"status": "Bio updated successfully."})

@app.get("/api/chats")
async def get_chat_list(current_user: ValidatedUser = Depends(get_current_user)):
    user_history = tid_to_history_cache.get(current_user.id, {})
    previews = [{
        "partner_uid": p_uid, "partner_username": get_username_by_uid(p_uid),
        "last_message_text": msgs[-1].get("text", "") if msgs else "",
        "timestamp_raw": msgs[-1].get("timestamp") if msgs else "1970-01-01 00:00:00 AM",
        "unread_count": sum(1 for m in msgs if m.get("unread")),
    } for p_uid, msgs in user_history.items()]
    sorted_chats = sorted(previews, key=lambda x: datetime.strptime(x['timestamp_raw'], "%Y-%m-%d %I:%M:%S %p"), reverse=True)
    return JSONResponse(content=sorted_chats)

@app.get("/api/chat/{partner_uid}")
async def get_full_chat(partner_uid: str, current_user: ValidatedUser = Depends(get_current_user)):
    messages = tid_to_history_cache.get(current_user.id, {}).get(partner_uid, [])
    for msg in messages:
        if msg.get("unread"): msg["unread"] = False
    return JSONResponse(content={"messages": messages})

@app.delete("/api/chat/{partner_uid}")
async def delete_chat_history(partner_uid: str, current_user: ValidatedUser = Depends(get_current_user)):
    if (history := tid_to_history_cache.get(current_user.id)) and partner_uid in history:
        del history[partner_uid]
        return JSONResponse(content={"status": "Chat history deleted."})
    raise HTTPException(status_code=404, detail="Chat history not found.")

@app.post("/api/message/{partner_uid}")
async def send_message(partner_uid: str, payload: MessagePayload, current_user: ValidatedUser = Depends(get_current_user)):
    my_uid = get_unique_id_by_tid(current_user.id)
    if my_uid == partner_uid: raise HTTPException(status_code=400, detail="You cannot message yourself.")
    receiver_tid = get_telegram_id_by_uid(partner_uid)
    if not receiver_tid: raise HTTPException(status_code=404, detail="Recipient not found.")
    if str(my_uid) in get_blocked_users_by_tid(receiver_tid): raise HTTPException(status_code=403, detail="You have been blocked by this user.")
    if str(partner_uid) in get_blocked_users_by_tid(current_user.id): raise HTTPException(status_code=403, detail="You must unblock this user first.")

    store_message(current_user.id, receiver_tid, payload.text)
    sender_username = get_username_by_uid(my_uid)
    await send_push_notification(ptb_app.bot, receiver_tid, f"📩 You have a new message from *{telegram.helpers.escape_markdown(sender_username, version=2)}*\\!")
    return JSONResponse(content={"status": "Message sent"})

@app.get("/api/friends")
async def get_friends_list(current_user: ValidatedUser = Depends(get_current_user)):
    friends_uids = get_friends_by_uid(get_unique_id_by_tid(current_user.id))
    return JSONResponse(content=[get_user_profile_by_uid(uid) for uid in friends_uids if get_user_profile_by_uid(uid)])

@app.get("/api/requests")
async def get_requests_list(current_user: ValidatedUser = Depends(get_current_user)):
    profile = get_user_profile_by_tid(current_user.id)
    if not profile: raise HTTPException(status_code=404, detail="Profile not found.")
    return JSONResponse(content={
        "received": [get_user_profile_by_uid(uid) for uid in profile.get("received_requests", []) if get_user_profile_by_uid(uid)],
        "sent": [get_user_profile_by_uid(uid) for uid in profile.get("sent_requests", []) if get_user_profile_by_uid(uid)]
    })

@app.post("/api/action/{action}/{target_uid}")
async def handle_user_action(action: str, target_uid: str, current_user: ValidatedUser = Depends(get_current_user)):
    my_tid, my_uid = current_user.id, get_unique_id_by_tid(current_user.id)
    target_tid = get_telegram_id_by_uid(target_uid)

    if action == "add_friend":
        s_profile, r_profile = get_user_profile_by_uid(my_uid), get_user_profile_by_uid(target_uid)
        if not s_profile or not r_profile: raise HTTPException(status_code=404, detail="User not found.")
        if is_friend(my_uid, target_uid) or has_sent_request(my_uid, target_uid): raise HTTPException(status_code=400, detail="Request already sent or already friends.")
        s_profile.setdefault("sent_requests", []).append(target_uid)
        r_profile.setdefault("received_requests", []).append(my_uid)
        if target_tid: await send_push_notification(ptb_app.bot, target_tid, f"🤝 You have a friend request from *{telegram.helpers.escape_markdown(current_user.first_name, version=2)}*\\!")
    elif action == "accept_friend":
        add_friend_by_uid(my_uid, target_uid); add_friend_by_uid(target_uid, my_uid)
        remove_pending_request(target_uid, my_uid)
        if target_tid: await send_push_notification(ptb_app.bot, target_tid, f"🎉 *{telegram.helpers.escape_markdown(current_user.first_name, version=2)}* accepted your friend request\\!")
    elif action == "decline_friend": remove_pending_request(target_uid, my_uid)
    elif action == "cancel_request": remove_pending_request(my_uid, target_uid)
    elif action == "unfriend": remove_friend_by_uid(my_uid, target_uid)
    elif action == "block":
        block_user_by_tid(my_tid, target_uid)
        remove_friend_by_uid(my_uid, target_uid)
        remove_pending_request(my_uid, target_uid); remove_pending_request(target_uid, my_uid)
    elif action == "unblock": unblock_user_by_tid(my_tid, target_uid)
    else: raise HTTPException(status_code=400, detail="Invalid action.")
    return JSONResponse(content={"status": "Action successful."})

@app.post("/api/react/{partner_uid}/{emoji}")
async def react_to_last_message(partner_uid: str, emoji: str, current_user: ValidatedUser = Depends(get_current_user)):
    my_tid, my_uid = current_user.id, get_unique_id_by_tid(current_user.id)
    partner_tid = get_telegram_id_by_uid(partner_uid)
    history = tid_to_history_cache.get(my_tid, {}).get(partner_uid, [])
    if not history: raise HTTPException(status_code=404, detail="Chat history not found.")

    msg_to_react = history[-1]
    reactions = msg_to_react.setdefault('reactions', [])
    user_reaction = next((r for r in reactions if r['reactor_uid'] == my_uid), None)
    if user_reaction: user_reaction['emoji'] = emoji
    else: reactions.append({'reactor_uid': my_uid, 'emoji': emoji})
    
    if partner_tid and (p_history := tid_to_history_cache.get(partner_tid, {}).get(my_uid, [])):
        p_msg = next((m for m in reversed(p_history) if m.get("timestamp") == msg_to_react.get("timestamp")), None)
        if p_msg: p_msg['reactions'] = reactions

    return JSONResponse(content={"status": "Reaction added."})
#</editor-fold>

# --- Run Server ---
if __name__ == "__main__":
    # For local development: uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    # The start command on Render should be: uvicorn main:app --host 0.0.0.0 --port 10000
<<<<<<< HEAD
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
=======
    
>>>>>>> origin/main

# --- END OF UNIFIED backend/main.py FILE ---
