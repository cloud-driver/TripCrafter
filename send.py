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

    target = next((u for u in users if u.get("uid") == uid), None)
    if not target:
        save_log({"error": f"找不到對應的uid: {uid}"})
        return {"error": f"找不到對應的uid: {uid}"}, 404

    user_id = target["userId"]
    # goal = float(target["target"]) # 這裡的 target 似乎沒有在 users.json 中定義，如果需要請自行添加
    message = {
        "type": "text",
        "text": f"今日握力紀錄：{grip_value} kg"
    }
    status, response = send_push_message(user_id, [message])
    save_log({"message": f"已發送給 {user_id}：{status}, {response}"})
    return {"message": f"已發送給 {user_id}：{status}, {response}"}, 200

def get_uid():
    """把users.json中所有的uid讀出來"""
    uid = []
    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
    else:
        users = []

    for i in users:
        if 'uid' in i:
            uid.append(i['uid'])
        
    return uid

def save_user_uid(user_id, uid, login_type='line'):
    """新增或更新userid及其對應的uid，並記錄登入類型"""
    if not os.path.exists(USER_FILE):
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    
    with open(USER_FILE, "r", encoding="utf-8") as f:
        try:
            users = json.load(f)
        except json.JSONDecodeError:
            users = []

    found = False
    for user in users:
        if user.get("userId") == user_id:
            user["uid"] = uid
            user["login_type"] = login_type
            found = True
            break
    
    if not found:
        users.append({"userId": user_id, 
                      "uid": uid,
                      "login_type": login_type})

    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

    return "success", 200
    
def save_log(text):
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