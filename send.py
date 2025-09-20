# -*- coding: utf-8 -*-
from google.genai import Client
from google.genai import types
import json
import requests
import uuid
import os
import time
from dotenv import load_dotenv

if os.path.exists(".env"): load_dotenv()

USER_FILE = r"json/users.json"
LOG_FILE = r"json/log.json"
SECRET_TOKEN = os.getenv('SECRET_TOKEN')
CLIENT = Client(api_key=os.getenv('API_KEY'))

class Keep():
    """讀取各json中的資訊"""
    @staticmethod
    def logs():
        with open(LOG_FILE, "r", encoding="utf8") as a:
            data = json.load(a)
            return data

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
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            try:
                users = json.load(f)
            except json.JSONDecodeError:
                save_log({"error": "使用者資料格式錯誤（可能為空檔）"})
                return {"error": "使用者資料格式錯誤（可能為空檔）"}, 500
    except FileNotFoundError:
        save_log({"error": "找不到使用者資料"})
        return {"error": "找不到使用者資料"}, 500

    # 尋找對應 uid 的 Line userId
    target_user_id = None
    for user_entry in users:
        if user_entry.get("uid") == uid and "line_account" in user_entry:
            target_user_id = user_entry["line_account"]["userId"]
            break

    if not target_user_id:
        save_log({"error": f"找不到對應的uid: {uid} 或未綁定 Line 帳戶"})
        return {"error": f"找不到對應的uid: {uid} 或未綁定 Line 帳戶"}, 404

    message = {
        "type": "text",
        "text": f"今日握力紀錄：{grip_value} kg"
    }
    status, response = send_push_message(target_user_id, [message])
    save_log({"message": f"已發送給 {target_user_id}：{status}, {response}"})
    return {"message": f"已發送給 {target_user_id}：{status}, {response}"}, 200

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
                pass # 檔案為空或格式錯誤時，回傳空列表
    return uid_list

def update_user_profile(uid, login_type=None, user_id=None, display_name=None, email=None, username=None):
    """
    新增或更新使用者資料，包括綁定帳戶資訊和使用者名稱。
    uid: 系統內部唯一識別碼
    login_type: 'line' 或 'google'
    user_id: 來自 Line 或 Google 的使用者 ID
    display_name: 來自 Line 或 Google 的顯示名稱
    email: 來自 Line 或 Google 的 Email
    username: 使用者自行設定的名稱
    """
    # 確保目錄存在
    os.makedirs(os.path.dirname(USER_FILE), exist_ok=True)
    
    if not os.path.exists(USER_FILE):
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    with open(USER_FILE, "r", encoding="utf-8") as f:
        try:
            users = json.load(f)
        except json.JSONDecodeError:
            users = []

    user_found = False
    for user_entry in users:
        if user_entry.get("uid") == uid:
            user_found = True
            if username is not None:
                user_entry["username"] = username
            if login_type and user_id:
                account_key = f"{login_type}_account"
                user_entry[account_key] = {
                    "userId": user_id,
                    "display_name": display_name,
                    "email": email
                }
            break

    if not user_found:
        new_user_entry = {"uid": uid}
        if username is not None:
            new_user_entry["username"] = username
        if login_type and user_id:
            account_key = f"{login_type}_account"
            new_user_entry[account_key] = {
                "userId": user_id,
                "display_name": display_name,
                "email": email
            }
        users.append(new_user_entry)

    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

    return "success", 200

def get_user_data(uid):
    """根據 uid 獲取完整的用戶資料"""
    if not os.path.exists(USER_FILE):
        return None
    with open(USER_FILE, "r", encoding="utf-8") as f:
        try:
            users = json.load(f)
            for user_entry in users:
                if user_entry.get("uid") == uid:
                    return user_entry
        except json.JSONDecodeError:
            return None
    return None

def get_user_by_email(email):
    """根據 email 獲取用戶資料"""
    if not os.path.exists(USER_FILE):
        return None
    with open(USER_FILE, "r", encoding="utf-8") as f:
        try:
            users = json.load(f)
            for user_entry in users:
                # 檢查 Google 帳戶
                if "google_account" in user_entry and user_entry["google_account"].get("email") == email:
                    return user_entry
                # 檢查 Line 帳戶
                if "line_account" in user_entry and user_entry["line_account"].get("email") == email:
                    return user_entry
        except json.JSONDecodeError:
            return None
    return None

def get_user_emails():
    """獲取所有用戶的 email 列表，用於群發郵件"""
    emails = []
    if not os.path.exists(USER_FILE):
        return emails
    
    with open(USER_FILE, "r", encoding="utf-8") as f:
        try:
            users = json.load(f)
            for user_entry in users:
                # 優先使用 Google 帳戶的 email
                if "google_account" in user_entry and user_entry["google_account"].get("email"):
                    emails.append({
                        "uid": user_entry.get("uid"),
                        "username": user_entry.get("username", "未設定"),
                        "email": user_entry["google_account"]["email"]
                    })
                    continue
                
                # 如果沒有 Google 帳戶，則使用 Line 帳戶的 email
                if "line_account" in user_entry and user_entry["line_account"].get("email"):
                    emails.append({
                        "uid": user_entry.get("uid"),
                        "username": user_entry.get("username", "未設定"),
                        "email": user_entry["line_account"]["email"]
                    })
        except json.JSONDecodeError:
            return emails
    
    return emails

def save_log(text):
    # 確保目錄存在
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf8") as f:
            json.dump([], f)

    with open(LOG_FILE, "r", encoding="utf8") as f:
        try:
            logs = json.load(f)
        except json.JSONDecodeError:
            logs = []

    logs.append({"time": time.ctime(time.time()), "log": text})

    with open(LOG_FILE, "w", encoding="utf8") as f:
        json.dump(logs, f, indent=4, ensure_ascii=False)
        
def replay_msg(user_msg):
    """Line自動回覆訊息"""
    return ask_ai(f"XXX")

def ask_ai(question):
    """問gemini問題"""
    response = CLIENT.models.generate_content(
        model="gemini-2.5-flash", contents=question, config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=0))
    )
    return response.text

def clean_users():
    """清除使用者資料"""
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=4)

if __name__ == "__main__":
    print("這裡是自建函式庫，你點錯了，請使用 app.py")
