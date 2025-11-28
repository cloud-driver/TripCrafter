# -*- coding: utf-8 -*-
import json
import requests
import uuid
import os
import time
from dotenv import load_dotenv
from google.genai import Client
from google.genai import types
import google.generativeai as genai

if os.path.exists(".env"): load_dotenv()

USER_FILE = r"json/users.json"
LOG_FILE = r"json/log.json"
SECRET_TOKEN = os.getenv('SECRET_TOKEN')
genai.configure(api_key=os.getenv('API_KEY'))

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

def ask_ai(data, trip_or_not="trip"):
    """
    使用 Google Gemini 模型生成行程規劃或回憶錄。
    """
    if trip_or_not == "notrip":
        prompt = data
        
    elif trip_or_not == "trip":   
        prompt = f"""
        你是一個專業且嚴謹的台灣旅遊行程規劃師。你的任務是根據輸入資料中的【指定天數】和【可用資料庫】來規劃行程。

        ### 核心規則 (違反將導致系統錯誤)：
        1. **嚴格遵守天數**：輸入資料的第一行會標註天數（例如 "# 1 Days"）。你產生的 JSON **必須**只包含該天數的鍵值（例如只包含 "1"）。絕對**不可以**自己增加額外的天數。
        2. **禁止幻覺**：你安排的所有景點、餐廳、住宿，**必須**完全來自下方的【可用資料庫】。絕對不可以自己編造地點，也不可以使用資料庫以外的知名地點。
        3. **資料引用**：在行程中提及地點時，請使用資料庫中的完整名稱。
        4. **若資料不足**：不要硬塞不存在的店。
        5. **JSON 格式**：必須輸出合法的 JSON 字串，不要包含 Markdown (```json) 標記。
        6. **使用繁體中文**。

        ### 回答格式範例 (JSON)：
        {{
            "1": [
                {{
                    "title": "活動或第一個行程的名稱 (必須來自資料庫)",
                    "time": "HH:MM - HH:MM",
                    "location": "完整地址 (來自資料庫)",
                    "tags": "標籤 (如: 景點, 美食)"
                }}
                // ... 更多活動
            ]
            // 注意：只有在要求 2 天以上時，才會有 "2" 這個鍵
        }}
        
        ### 輸入資料：
        {data}

        ### 規劃要求：
        1. 每天最多 3 個主要活動 + 1 個住宿 + 1 個午餐 + 1 個晚餐。
        2. **時間先後要合理優先**
        3. 路線要順暢。
        """
    elif trip_or_not == "memoir":
        # 新增回憶錄功能的 Prompt
        prompt = f"""
        你是一個感性的旅遊作家。使用者會提供一段他在旅途中的簡短想法或關鍵字。
        請你根據這些內容，擴寫成一篇溫暖、動人且文筆優美的「旅行回憶錄」。
        
        ### 使用者提供的內容：
        {data}

        ### 寫作要求：
        1. 文章標題要吸引人。
        2. 使用繁體中文。
        3. 字數約 300-500 字。
        4. 分段清晰，帶有情感共鳴。
        5. 回傳格式請使用 HTML (包含 <h3>標題</h3> 和 <p>內文</p>)，不要包含 ```html 標記。
        """
    else:
        return "抱歉，我現在無法回答問題。"
    
    try:
        # 呼叫 Gemini API
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        text_response = response.text
        
        # 簡單的清理，確保 JSON 解析順利 (針對 trip 模式)
        if trip_or_not == "trip":
            if text_response.startswith("```json"):
                text_response = text_response[7:]
            if text_response.endswith("```"):
                text_response = text_response[:-3]
            text_response = text_response.strip()

        save_log(f"Google AI response ({trip_or_not}): {text_response}")
        return text_response
    except Exception as e:
        save_log(f"Error calling Google AI: {e}")
        return "抱歉，AI 目前忙碌中，請稍後再試。"

def replay_msg(user_message):
    """處理使用者訊息並回傳答覆"""
    # === 修正：這裡必須指定 'notrip'，否則一般聊天會被當成行程規劃 ===
    reply = ask_ai(user_message, trip_or_not="notrip")
    return reply

def send_push_message(user_id, messages):
    """發送打包好的訊息給指定使用者 (user_id, messages)"""
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
    # 修正 log 記錄方式，避免直接把物件轉字串造成的格式混亂
    save_log(f"Pushing message to {user_id}")
    response = requests.post(url, headers=headers, json=payload)
    return response.status_code, response.text

def send_grip_data(uid, grip_value):
    """根據uid 發送握力訊息給對應 userLineId"""
    user_data = get_user_data(uid)
    if not user_data or "line_account" not in user_data or not user_data["line_account"]:
        error_msg = f"找不到對應的uid: {uid} 或未綁定 Line 帳戶"
        save_log(error_msg)
        return {"error": error_msg}, 404

    target_user_id = user_data["line_account"].get("userId")
    if not target_user_id:
        return {"error": "Line userId not found"}, 404

    message = {"type": "text", "text": f"今日握力紀錄：{grip_value} kg"}
    status, response_text = send_push_message(target_user_id, [message])
    log_msg = f"已發送給 {target_user_id}：{status}, {response_text}"
    save_log(log_msg)
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

def get_all_users():
    """讀取並返回所有使用者的資料列表"""
    if not os.path.exists(USER_FILE):
        return []
    if os.path.getsize(USER_FILE) == 0:
        return []
    with open(USER_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_all_users(users):
    """將使用者資料列表寫回 users.json"""
    os.makedirs(os.path.dirname(USER_FILE), exist_ok=True)
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def delete_user_profile(uid):
    """根據 UID 刪除使用者設定檔"""
    users = get_all_users()
    user_found = any(user.get('uid') == uid for user in users)
    if not user_found:
        save_log(f"Attempted to delete UID {uid}, but user was not found.")
        return False
    updated_users = [user for user in users if user.get('uid') != uid]
    save_all_users(updated_users)
    save_log(f"Successfully deleted user profile for UID: {uid}")
    return True

def update_user_profile(uid,
                        login_type=None,
                        user_id=None,
                        display_name=None,
                        email=None,
                        username=None,
                        home_station_code=None,
                        home_station_name=None):
    """
    更新或建立使用者資料
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
            if username:
                target_user["username"] = username
            if home_station_code and home_station_name:
                target_user["homeStationCode"] = home_station_code
                target_user["homeStationName"] = home_station_name
            if login_type and user_id:
                key = f"{login_type}_account"
                target_user[key] = {
                    "userId": user_id,
                    "display_name": display_name,
                    "email": email
                }
            save_log(f"Updated user {uid} via {login_type}")
        else:
            # 全新使用者
            new_user = {
                "uid": uid,
                "username": username or display_name or "新使用者",
                "google_account": None,
                "line_account": None,
                "homeStationCode": home_station_code,
                "homeStationName": home_station_name
            }
            if login_type and user_id:
                key = f"{login_type}_account"
                account_data = {"userId": user_id, "display_name": display_name}
                if login_type == "google":
                    account_data["email"] = email
                new_user[key] = account_data
            
            users.append(new_user)
            save_log(f"Created new user {uid} via {login_type}")

        # 寫回檔案
        f.seek(0)
        json.dump(users, f, ensure_ascii=False, indent=4)
        f.truncate()

    return uid

def find_user_by_identity(login_type, provider_id=None, email=None):
    """
    根據登入類型查找使用者
    """
    if not os.path.exists(USER_FILE):
        return None
    with open(USER_FILE, "r", encoding="utf-8") as f:
        try:
            users = json.load(f)
        except json.JSONDecodeError:
            return None

    for user in users:
        if login_type == 'google' and email:
            account = user.get('google_account')
            if account and account.get('email') == email:
                return user
        elif login_type == 'line' and provider_id:
            account = user.get('line_account')
            if account and account.get('userId') == provider_id:
                return user
    return None