# -*- coding: utf-8 -*-
import json
import requests
import uuid
import os
import time
from dotenv import load_dotenv
from google.genai import Client

if os.path.exists(".env"): load_dotenv()

USER_FILE = r"json/users.json"
LOG_FILE = r"json/log.json"
SECRET_TOKEN = os.getenv('SECRET_TOKEN')
CLIENT = Client(api_key=os.getenv('API_KEY'))

class Keep():
    """讀取各json中的資訊"""
    @staticmethod
    def logs():
        # 確保日誌檔案存在
        if not os.path.exists(LOG_FILE):
            return []
        with open(LOG_FILE, "r", encoding="utf8") as a:
            try:
                data = json.load(a)
            except json.JSONDecodeError:
                data = []
            return data

def save_log(message):
    """將日誌訊息儲存到 log.json"""
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    }
    logs = Keep.logs()
    logs.append(log_entry)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=4)


def send_push_message(user_id, messages):
    """發送打包好的訊息給指定使用者"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {str(os.getenv('MESSAGING_API_ACCESS_TOKEN'))}",
        "X-Line-Retry-Key": str(uuid.uuid4())
    }
    payload = {
        "to": user_id,
        "messages": messages
    }
    save_log(f"Have allready send {messages} to {user_id}")
    response = requests.post(url, headers=headers, json=payload)
    return response.status_code, response.text

def send_grip_data(uid, grip_value):
    """根據uid 發送握力訊息給對應 userLineId"""
    user_data = get_user_data(uid)
    if not user_data or "line_account" not in user_data:
        error_msg = f"找不到對應的uid: {uid} 或未綁定 Line 帳戶"
        save_log({"error": error_msg})
        return {"error": error_msg}, 404

    target_user_id = user_data["line_account"]["userId"]
    message = {"type": "text", "text": f"今日握力紀錄：{grip_value} kg"}
    status, response_text = send_push_message(target_user_id, [message])
    log_msg = f"已發送給 {target_user_id}：{status}, {response_text}"
    save_log({"message": log_msg})
    return {"message": log_msg}, 200

def get_uid():
    """把users.json中所有的uid讀出來"""
    uid_list = []
    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r", encoding="utf-8") as f:
            try:
                users = json.load(f)
                for user_entry in users:
                    if 'uid' in user_entry:
                        uid_list.append(user_entry['uid'])
            except json.JSONDecodeError:
                pass
    return uid_list

def get_user_data(uid):
    """根據 uid 獲取單一使用者資料"""
    if not os.path.exists(USER_FILE):
        return None
    with open(USER_FILE, "r", encoding="utf-8") as f:
        try:
            users = json.load(f)
            for user in users:
                if user.get("uid") == uid:
                    return user
        except json.JSONDecodeError:
            return None
    return None

def update_user_profile(uid, login_type=None, user_id=None, display_name=None, email=None, username=None):
    """
    新增或更新使用者資料。
    - 如果提供了 email，會優先嘗試根據 email 合併帳戶。
    - 否則，會根據 uid 更新或新增使用者。
    - 返回最終確定的 uid。
    """
    os.makedirs(os.path.dirname(USER_FILE), exist_ok=True)
    if not os.path.exists(USER_FILE):
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    with open(USER_FILE, "r+", encoding="utf-8") as f:
        try:
            users = json.load(f)
        except json.JSONDecodeError:
            users = []

        target_user = None
        
        # 1. 優先透過 email 尋找並合併帳戶
        if email:
            for user in users:
                if ('google_account' in user and user.get('google_account') and user['google_account'].get('email') == email) or \
                   ('line_account' in user and user.get('line_account') and user['line_account'].get('email') == email):
                    target_user = user
                    uid = target_user['uid']  # 使用現有帳戶的 uid
                    break
        
        # 2. 如果 email 沒找到，則透過傳入的 uid 尋找
        if not target_user:
            for user in users:
                if user.get("uid") == uid:
                    target_user = user
                    break

        # 3. 處理找到的或新的使用者
        if target_user:
            # 更新現有使用者
            if username is not None and username.strip() != '':
                target_user["username"] = username
            if login_type and user_id:
                account_key = f"{login_type}_account"
                target_user[account_key] = {
                    "userId": user_id,
                    "display_name": display_name,
                    "email": email
                }
            save_log(f"Updated user profile for UID: {uid}")
        else:
            # 建立新使用者
            new_user = {
                "uid": uid,
                "username": username or display_name or "新使用者",
                "google_account": None,
                "line_account": None
            }
            if login_type and user_id:
                account_key = f"{login_type}_account"
                new_user[account_key] = {
                    "userId": user_id,
                    "display_name": display_name,
                    "email": email
                }
            users.append(new_user)
            save_log(f"Created new user profile with UID: {uid}")

        # 將更新後的資料寫回檔案
        f.seek(0)
        json.dump(users, f, ensure_ascii=False, indent=4)
        f.truncate()
        
        return uid # 返回最終的 uid