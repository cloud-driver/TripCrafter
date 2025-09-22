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

def ask_ai(question):
    """呼叫 Google AI 並返回結果"""
    try:
        response = CLIENT.generate_content(question)
        return response.text
    except Exception as e:
        save_log(f"Error calling Google AI: {e}")
        return "抱歉，我現在無法回答問題。"

def replay_msg(user_message):
    """處理使用者訊息並回傳答覆"""
    # 在這裡你可以加入更多判斷邏輯，例如關鍵字回覆
    # 現在預設是將所有訊息都交給 AI 處理
    reply = ask_ai(user_message)
    return reply

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

def update_user_profile(uid,
                        login_type=None,
                        user_id=None,
                        display_name=None,
                        email=None,
                        username=None):
    """
    - Google 登入：若有 email，先試試用 email 找現有帳號來合併；
      找不到就用傳入的 uid 建新帳號。
    - LINE 登入：一律透過 uid 來建／更新 line_account。
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

        # 1. Google + email → 嘗試用 email 合併
        if login_type == "google" and email:
            for user in users:
                ga = user.get("google_account")
                if ga and ga.get("email") == email:
                    target_user = user
                    uid = user["uid"]
                    break

        # 2. 若還沒找到，統一使用 uid 去找
        if not target_user:
            for user in users:
                if user.get("uid") == uid:
                    target_user = user
                    break

        # 3. 更新或建立
        if target_user:
            # 更新使用者名稱
            if username:
                target_user["username"] = username
            # 更新對應的登入方式
            if login_type and user_id:
                key = f"{login_type}_account"
                target_user[key] = {
                    "userId": user_id,
                    "display_name": display_name,
                    # LINE 這邊的 email 可能是 None → 不影響
                    "email": email
                }
            save_log(f"Updated user {uid} via {login_type}")
        else:
            # 全新使用者
            new_user = {
                "uid": uid,
                "username": username or display_name or "新使用者",
                "google_account": None,
                "line_account": None
            }
            if login_type and user_id:
                key = f"{login_type}_account"
                new_user[key] = {
                    "userId": user_id,
                    "display_name": display_name,
                    "email": email
                }
            users.append(new_user)
            save_log(f"Created new user {uid} via {login_type}")

        # 寫回檔案
        f.seek(0)
        json.dump(users, f, ensure_ascii=False, indent=4)
        f.truncate()

    return uid
