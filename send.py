# -*- coding: utf-8 -*-
import json
import requests
import uuid
import os
import time
from dotenv import load_dotenv
from google.genai import Client
from google.genai import types

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

def ask_ai(data, trip_or_not="trip"):
    """
    使用 Google Gemini 模型生成行程規劃。
    """
    if trip_or_not == "notrip":
        prompt = data
        
    elif trip_or_not == "trip":   
        # 定義非常完整的 Prompt
        prompt = f"""
        你是一個專業的行程規劃師，負責根據輸入的活動資料和天數來設計行程。
        請根據以下的活動資料，規劃出一個清晰、有條理的行程，並以以下格式回答：

        ### 回答格式(幫我用成json)：
        請根據行程資料生成 JSON 格式的行程表，格式如下：
        {{
            "1": [
                {{
                    "title": "活動名稱",
                    "time": "活動時間",
                    "location": "活動地點(詳細地址)",
                    "tags": "活動標籤"
                }}          
            ],
            "2": [
                {{
                    "title": "第二天活動名稱",
                    "time": "第二天活動時間",
                    "location": "第二天活動地點(詳細地址)",
                    "tags": "第二天活動標籤"
                }}
            ]
            ...
        }}

        請確保輸出的 JSON 格式正確，並且活動按照天數分組。
        
        ### 輸入資料：
        {data}

        ### 注意事項：
        1. 如果輸入的活動資料不足以填滿所有天數，請合理分配活動並在行程中加入適合的休息時間。
        2. 每一天的行程最多包含 3 個活動 + 1 個住住，活動之間請合理安排時間。
        3. 如果活動有重疊，請根據地點和時間進行優化分配，避免衝突。
        4. 請確保行程既充實又不過於緊湊，適合一般旅遊者。
        5. 請用繁體中文回答。
        6. 每一個行程成都要是從資料裡面找到的，不要寫XXX附近的飯店等不清楚的東西，一定也寫清楚飯店、景點、餐飲的名稱
        7. 請嚴格依照行程天數來排行程！！！
        """
    else:
        return "抱歉，我現在無法回答問題。"
    
    try:
        # 呼叫 Gemini API
        response = CLIENT.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        save_log(f"Google AI response: {response.text}")
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
    """
    根據 UID 刪除使用者設定檔。

    Args:
        uid (str): 要刪除的使用者的唯一識別碼。

    Returns:
        bool: 如果成功刪除則返回 True，否則返回 False (例如找不到使用者)。
    """
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
    更新或建立使用者資料，包含家車站資訊。
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
            # 更新家車站資訊 (只有在提供時才更新)
            if home_station_code and home_station_name:
                target_user["homeStationCode"] = home_station_code
                target_user["homeStationName"] = home_station_name
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
                "line_account": None,
                "homeStationCode": home_station_code,
                "homeStationName": home_station_name
            }
            if login_type and user_id:
                key = f"{login_type}_account"
                if login_type == "google":
                    new_user[key] = {
                        "userId": user_id,
                        "display_name": display_name,
                        "email": email
                    }
                else:
                    new_user[key] = {
                        "userId": user_id,
                        "display_name": display_name
                    }
            users.append(new_user)
            save_log(f"Created new user {uid} via {login_type}")

        # 寫回檔案
        f.seek(0)
        json.dump(users, f, ensure_ascii=False, indent=4)
        f.truncate()

    return uid

def find_user_by_identity(login_type, provider_id=None, email=None):
    """
    根據登入類型 (line/google) 和其唯一識別碼 (provider_id/email) 查找使用者。
    - login_type: 'line' 或 'google'
    - provider_id: LINE 的 user ID
    - email: Google 的 email
    返回：找到的使用者資料 (dict) 或 None
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
