# --- START OF backend/data_logic.py FILE ---

import os
import json
import asyncio
import random
import re
import sys
import signal
import telegram
from telegram import Update, User
from telegram.ext import Application
from telegram.constants import ParseMode
from telegram.error import Forbidden
import traceback
import logging
import pytz
from datetime import datetime
import colorlog

# --- Colored Logging Setup ---
log = logging.getLogger()
log.setLevel(logging.INFO)
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(levelname)-8s%(reset)s %(blue)s%(asctime)s%(reset)s - %(name)s - %(message)s',
    log_colors={'DEBUG':'cyan','INFO':'green','WARNING':'yellow','ERROR':'red','CRITICAL':'red,bg_white'}
))
if not log.handlers: log.addHandler(handler)
logger = logging.getLogger(__name__)

# --- Constants ---
# BOT_TOKEN and BOT_OWNER_ID will be moved to main.py
USER_DATA_DIR = "user_data11_refactored"
PROFILE_FILE, FRIENDS_FILE, MESSAGE_HISTORY_FILE, UID_TO_TID_MAP_FILE = "profile.json", "friends.json", "message_history.json", "uid_to_tid.json"

uid_to_tid_map_cache, tid_to_profile_cache, tid_to_friends_cache, tid_to_history_cache = {}, {}, {}, {}
ist = pytz.timezone('Asia/Kolkata')
os.makedirs(USER_DATA_DIR, exist_ok=True)

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
    if profile := tid_to_profile_cache.get(telegram_id):
        return profile.get("unique_id")
    
    # User doesn't exist, create them
    username = user.get("username") or user.get("first_name", f"User_{telegram_id}")
    unique_id = str(random.randint(10000000, 99999999))
    while unique_id in uid_to_tid_map_cache: unique_id = str(random.randint(10000000, 99999999))
    
    new_user_data = {"unique_id": unique_id, "telegram_id": telegram_id, "username": username, "joined_date": get_current_ist_time_str(), "last_active_timestamp": get_current_ist_time_str(), "blocked_users": [], "sent_requests": [], "received_requests": []}
    
    tid_to_profile_cache[telegram_id] = new_user_data
    uid_to_tid_map_cache[unique_id] = telegram_id
    tid_to_friends_cache.setdefault(telegram_id, [])
    tid_to_history_cache.setdefault(telegram_id, {})
    
    _save_json_data_to_file(get_user_data_path(telegram_id, PROFILE_FILE), new_user_data)
    _save_json_data_to_file(os.path.join(USER_DATA_DIR, UID_TO_TID_MAP_FILE), uid_to_tid_map_cache)
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
    actions_taken = 0
    if (user_tid := get_telegram_id_by_uid(user_uid)) and str(friend_to_remove_uid) in tid_to_friends_cache.get(user_tid, []):
        tid_to_friends_cache[user_tid].remove(str(friend_to_remove_uid)); actions_taken += 1
    if (friend_to_remove_tid := get_telegram_id_by_uid(friend_to_remove_uid)) and str(user_uid) in tid_to_friends_cache.get(friend_to_remove_tid, []):
        tid_to_friends_cache[friend_to_remove_tid].remove(str(user_uid)); actions_taken += 1
    return actions_taken > 0

def remove_pending_request(sender_uid, receiver_uid):
    if (s_profile := get_user_profile_by_uid(sender_uid)) and str(receiver_uid) in s_profile.get("sent_requests", []):
        s_profile["sent_requests"].remove(str(receiver_uid))
    if (r_profile := get_user_profile_by_uid(receiver_uid)) and str(sender_uid) in r_profile.get("received_requests", []):
        r_profile["received_requests"].remove(str(sender_uid))

def block_user_by_tid(telegram_id, uid_to_block):
    if profile_data := tid_to_profile_cache.get(telegram_id):
        if str(uid_to_block) not in profile_data.get("blocked_users", []):
            profile_data.setdefault("blocked_users", []).append(str(uid_to_block))
            return True
    return False

def unblock_user_by_tid(telegram_id, uid_to_unblock):
    if profile_data := tid_to_profile_cache.get(telegram_id):
        if str(uid_to_unblock) in profile_data.get("blocked_users", []):
            profile_data["blocked_users"].remove(str(uid_to_unblock))
            return True
    return False

def store_message(sender_tid, receiver_tid, message_text, reaction=None):
    sender_uid, receiver_uid = get_unique_id_by_tid(sender_tid), get_unique_id_by_tid(receiver_tid)
    if not sender_uid or not receiver_uid: return None
    message_data = { "sender_uid": sender_uid, "receiver_uid": receiver_uid, "text": message_text, "timestamp": get_current_ist_time_str(), "reaction": reaction or "", "unread": True }
    sender_history = tid_to_history_cache.setdefault(sender_tid, {})
    sender_history.setdefault(str(receiver_uid), []).append({**message_data, "unread": False})
    receiver_history = tid_to_history_cache.setdefault(receiver_tid, {})
    receiver_history.setdefault(str(sender_uid), []).append(message_data)
    return message_data

async def send_push_notification(bot: telegram.Bot, receiver_tid: int, text: str):
    """Sends a simple push notification to a user."""
    try:
        await bot.send_message(chat_id=receiver_tid, text=text, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"Sent push notification to TID {receiver_tid}")
        return True
    except Forbidden:
        logger.warning(f"Could not send push notification to {receiver_tid}, bot might be blocked.")
        return False
    except Exception as e:
        logger.error(f"Failed to send push notification to {receiver_tid}: {e}")
        return False

#</editor-fold>

# --- END OF backend/data_logic.py FILE ---
