# -*- coding: utf-8 -*-
import os
import requests
import secrets
import jwt as pyjwt
import json
import uuid
from flask import Flask, request, redirect, jsonify, session, send_from_directory, Response, render_template, url_for, flash, abort
from send import Keep, update_user_profile, get_user_data, save_log, send_push_message, replay_msg, find_user_by_identity, delete_user_profile, ask_ai
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect, generate_csrf
from datetime import timedelta
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import csv
import re
import html
import math
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad as _pad, unpad as _unpad
import time
import sqlite3
from datetime import datetime
import random

COUNTY_MAP = {
    "Lienchiang": "連江縣",
    "Taipei":    "臺北市",
    "NewTaipei": "新北市",
    "Taoyuan":   "桃園市",
    "Taichung":  "臺中市",
    "Tainan":    "臺南市",
    "Kaohsiung": "高雄市",
    "Keelung":   "基隆市",
    "HsinchuCity":   "新竹市",
    "Hsinchu": "新竹縣",
    "Miaoli":    "苗栗縣",
    "Changhua":  "彰化縣",
    "Nantou":    "南投縣",
    "Yunlin":    "雲林縣",
    "ChiayiCity":    "嘉義市",
    "Chiayi":"嘉義縣",
    "Pingtung":  "屏東縣",
    "Yilan":     "宜蘭縣",
    "Hualien":   "花蓮縣",
    "Taitung":   "臺東縣",
    "Penghu":    "澎湖縣",
    "Kinmen":    "金門縣",
    "Matsu":     "連江縣"
}

if os.path.exists(".env"): load_dotenv()

app = Flask(__name__, static_folder='assets', static_url_path='/assets')
app.config['JSON_AS_ASCII'] = False
app.secret_key = secrets.token_hex(24)
app.config['SECRET_PAGE_PASSWORD'] = os.getenv('SECRET_PAGE_PASSWORD')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.permanent_session_lifetime = timedelta(days=1)
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])
csrf = CSRFProtect(app)


# LINE 配置
CLIENT_ID = int(os.getenv('LINE_LOGIN_CHANNEL_ID'))
CLIENT_SECRET = str(os.getenv('LINE_LOGIN_CHANNEL_SECRET'))
REDIRECT_URI = f"{str(os.getenv('URL'))}/callback/line"

# Google 配置
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = f"{str(os.getenv('URL'))}/callback/google"

# Google OAuth 2.0 授權終端點
GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

AES_KEY = os.getenv('TOKEN_AES_KEY', '')
if len(AES_KEY.encode()) not in (16, 24, 32):
    raise RuntimeError("AES_KEY error")

#打開活動.csv
EVENTS = {}
with open('datas/活動.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        eid = row['唯一識別碼']
        EVENTS[eid] = row

ATTRACTIONS = {}
with open('datas/景點.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        eid = row['縣市名稱']
        ATTRACTIONS[eid] = row

HOTEL = {}
with open('datas/景點.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        eid = row['縣市名稱']
        HOTEL[eid] = row

RESTAURANT = {}
with open('datas/餐飲.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        eid = row['縣市名稱']
        RESTAURANT[eid] = row


# 根據城市名稱查找對應的資料
def find(DATA, city_name):
    """
    根據城市名稱查找對應的資料。
    如果找到的景點超過50個，則隨機選取50個。
    回傳一個包含所有景點完整內容的純文字字串。
    """
    found = {}
    for value in DATA.values():
        if value['縣市名稱'] == city_name:
            found[value['唯一識別碼']] = value

    result_dict = {}
    if len(found) > 50:
        random_keys = random.sample(list(found.keys()), 50)
        result_dict = {key: found[key] for key in random_keys}
    else:
        result_dict = found
    
    attraction_strings = []
    for attraction_data in result_dict.values():
        single_attraction_parts = []
        for key, value in attraction_data.items():
            single_attraction_parts.append(f"{key}: {value}")
        attraction_strings.append("\n".join(single_attraction_parts))
    
    return "\n\n---\n\n".join(attraction_strings)

#實作 pad / unpad
BS = AES.block_size

# 加密函式
def encrypt_token(uid: str) -> str:
    # 加入時間戳記（秒）
    timestamp = str(int(time.time()))  # 獲取當前時間戳
    data = f"{uid}:{timestamp}"  # 將 uid 和時間戳記組合
    iv = secrets.token_bytes(BS)  # 隨機生成 IV
    cipher = AES.new(AES_KEY.encode(), AES.MODE_CBC, iv)  # 建立 AES 加密器
    ct = cipher.encrypt(_pad(data.encode('utf-8'), BS))  # 加密並填充
    return base64.urlsafe_b64encode(iv + ct).decode('utf-8')  # 返回加密後的 Token

# 解密函式
def decrypt_token(token: str) -> tuple:
    if token:
        try:
            data = base64.urlsafe_b64decode(token.encode('utf-8'))  # 解碼 Base64
            iv, ct = data[:BS], data[BS:]  # 分離 IV 和密文
            cipher = AES.new(AES_KEY.encode(), AES.MODE_CBC, iv)  # 建立 AES 解密器
            pt = _unpad(cipher.decrypt(ct), BS).decode('utf-8')  # 解密並去填充
            uid, timestamp = pt.split(":")  # 分解 uid 和時間戳記
            
            # 驗證時間戳記是否過期
            current_time = int(time.time())
            token_time = int(timestamp)
            if current_time - token_time > 3600:
                raise ValueError("Token 已過期")
            
            return uid
        except Exception as e:
            print(f"解密錯誤：{e}")
            return None
    else:
        return None

# 初始化資料庫
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            trip_id TEXT NOT NULL,
            schedule TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()  # 呼叫初始化（只在應用啟動時執行一次）

@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

@csrf.exempt
@app.route("/")
def home():
    session['token'] = encrypt_token("123123123321123123123") # 測試用，預設登入
    session['home'] = "10001" # 測試用，預設家
    return render_template('index.html')

@csrf.exempt
@app.route("/login")
def login():
    token = session.get('token')
    if not token:
        return render_template('login.html')
    else:
        return redirect(url_for('account_management', token=token))
    
@csrf.exempt
@app.route("/logout")
def logout():
    token = session.pop('token', None)
    if token:
        try:
            uid = decrypt_token(token)
            username = get_user_data(uid).get("username", "使用者")
            flash(f"{username} 已成功登出。")
        except:
            pass
    else:
        flash("您已登出。")
    return redirect(url_for('login'))

@app.route('/delete_account')
def delete_account():
    token = request.args.get('token')
    logged_in_token = session.get('token')
    if not logged_in_token or logged_in_token != token:
        flash("權限不足，無法刪除此帳號。", "error")
        return redirect(url_for('login'))

    success = delete_user_profile(decrypt_token(token))

    if success:
        session.clear()
        flash("您的帳號已成功刪除。", "success")
        return redirect(url_for('login'))
    else:
        flash("刪除帳號失敗，請稍後再試。", "error")
        return redirect(url_for('account_management', token=token))

# LINE 登入
@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/line")
def login_line():
    uid = decrypt_token(request.args.get("token"))
    username = request.args.get("username")
    state = secrets.token_hex(16)

    # 根據參數判斷流程
    if username:
        session['flow'] = 'register'
        session['username'] = username
        # 註冊流程，若無uid則產生新的
        if not uid: uid = str(uuid.uuid4())
    elif uid:
        session['flow'] = 'link' # 從帳號管理頁來，有uid但無username
    else:
        session['flow'] = 'login' # 從首頁登入來，無uid也無username
        uid = str(uuid.uuid4()) # 為登入流程產生一個暫時的uid

    session['oauth_state_line'] = state
    session['uid_id'] = uid  # 將 uid 存入 session

    login_url = (
        f"https://access.line.me/oauth2/v2.1/authorize"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=openid%20profile%20email"
        f"&state={state}"
    )
    return redirect(login_url)

@csrf.exempt
@limiter.limit("10 per minute")
@app.route("/callback/line")
def callback_line():
    code = request.args.get("code")
    state = request.args.get("state")
    
    if not state or state != session.pop("oauth_state_line", None):
        save_log("fail by state")
        flash("驗證失敗，請重試。", "error")
        return redirect(url_for('login'))

    token_url = "https://api.line.me/oauth2/v2.1/token"
    payload = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_response = requests.post(token_url, data=payload, headers=headers)

    if token_response.status_code != 200:
        flash("無法從 LINE 獲取 Access Token", "error")
        return redirect(url_for('login'))

    token_data = token_response.json()
    id_token_jwt = token_data.get("id_token")
    
    if not id_token_jwt:
        flash("無法從 LINE 獲取 ID Token", "error")
        return redirect(url_for('login'))

    try:
        decoded = pyjwt.decode(id_token_jwt, CLIENT_SECRET, audience=str(CLIENT_ID), algorithms=["HS256"])
        user_id = decoded.get("sub")
        display_name = decoded.get("name", "未知")
        email = decoded.get("email")

        flow = session.pop("flow", None)
        uid = session.pop("uid_id", None)
        username = session.pop("username", None)

        if flow in ['register', 'link']:
            # 註冊 或 連結流程
            final_uid = update_user_profile(uid=uid, login_type='line', user_id=user_id, display_name=display_name, email=email, username=username)
            if flow == 'register':
                save_log(f"{user_id} (Line) registered with uid {final_uid}")
                flash("註冊成功！", "success")
            else: # link
                save_log(f"Linked Line account {user_id} to uid {final_uid}")
                flash("LINE 帳號連結成功！", "success")
            return redirect(url_for('account_management', token=encrypt_token(final_uid)))
        
        elif flow == 'login':
            # 登入流程
            found_user = find_user_by_identity(login_type='line', provider_id=user_id)
            if found_user:
                save_log(f"{user_id} (Line) logged in with existing uid {found_user['uid']}")
                flash("登入成功！", "success")
                session['token'] = encrypt_token(found_user['uid'])
                return redirect(url_for('account_management', token=encrypt_token(found_user['uid'])))
            else:
                save_log(f"Login failed: Line user {user_id} not found. Asking to register.")
                flash("此 LINE 帳號尚未註冊，請先註冊。", "error")
                return redirect(url_for('login'))
        else:
            save_log(f"Unknown flow type: {flow}")
            flash("發生未知錯誤，請重試。", "error")
            return redirect(url_for('login'))

    except pyjwt.InvalidTokenError as e:
        save_log(f"ID Token驗證失敗：{e}")
        flash(f"ID Token驗證失敗：{e}", "error")
        return redirect(url_for('login'))

@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/google")
def login_google():
    uid = decrypt_token(request.args.get("token"))
    username = request.args.get("username")
    state = secrets.token_hex(16)

    # 根據參數判斷流程
    if username:
        session['flow'] = 'register'
        session['username'] = username
        if not uid: uid = str(uuid.uuid4())
    elif uid:
        session['flow'] = 'link'
    else:
        session['flow'] = 'login'
        uid = str(uuid.uuid4())

    session['oauth_state_google'] = state
    session['uid_id'] = uid

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state
    }
    auth_url = f"{GOOGLE_AUTHORIZATION_URL}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
    return redirect(auth_url)

@csrf.exempt
@limiter.limit("10 per minute")
@app.route("/callback/google")
def callback_google():
    code = request.args.get('code')
    state = request.args.get('state')

    if not state or state != session.pop("oauth_state_google", None):
        save_log("Google login fail by state")
        flash("驗證失敗，請重試。", "error")
        return redirect(url_for('login'))
    
    if not code:
        flash("授權失敗：未收到授權碼。", "error")
        return redirect(url_for('login'))

    token_data = {
        "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
    }
    response = requests.post(GOOGLE_TOKEN_URL, data=token_data)
    token_info = response.json()

    if "error" in token_info:
        flash(f"獲取Token失敗：{token_info.get('error_description', token_info.get('error'))}", "error")
        return redirect(url_for('login'))

    id_token_jwt = token_info.get("id_token")
    if not id_token_jwt:
        flash("獲取ID Token失敗。", "error")
        return redirect(url_for('login'))

    try:
        idinfo = id_token.verify_oauth2_token(id_token_jwt, google_requests.Request(), GOOGLE_CLIENT_ID)
        user_id = idinfo['sub']
        display_name = idinfo.get('name', '未知')
        email = idinfo.get('email')

        flow = session.pop("flow", None)
        uid = session.pop("uid_id", None)
        username = session.pop("username", None)

        if flow in ['register', 'link']:
            # 註冊 或 連結流程
            final_uid = update_user_profile(uid=uid, login_type='google', user_id=user_id, display_name=display_name, email=email, username=username)
            if flow == 'register':
                save_log(f"{user_id} (Google) registered with uid {final_uid}")
                flash("註冊成功！", "success")
            else: # link
                save_log(f"Linked Google account {email} to uid {final_uid}")
                flash("Google 帳號連結成功！", "success")
            return redirect(url_for('account_management', token=encrypt_token(final_uid)))

        elif flow == 'login':
            # 登入流程
            found_user = find_user_by_identity(login_type='google', email=email)
            if found_user:
                save_log(f"{user_id} (Google) logged in with existing uid {found_user['uid']}")
                flash("登入成功！", "success")
                session['token'] = encrypt_token(found_user['uid'])
                return redirect(url_for('account_management', token=encrypt_token(found_user['uid'])))
            else:
                save_log(f"Login failed: Google user {email} not found. Asking to register.")
                flash("此 Google 帳號尚未註冊，請先註冊。", "error")
                return redirect(url_for('login'))
        else:
            save_log(f"Unknown flow type: {flow}")
            flash("發生未知錯誤，請重試。", "error")
            return redirect(url_for('login'))

    except ValueError as e:
        save_log(f"ID Token驗證失敗：{e}")
        flash(f"ID Token驗證失敗：{e}", "error")
        return redirect(url_for('login'))

@csrf.exempt
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@csrf.exempt
@app.route('/log')
def log_page():
    return render_template('log.html')

@csrf.exempt
@app.route('/log/data')
def log_data():
    data = Keep.logs()
    response = Response(
        json.dumps(data, ensure_ascii=False),
        content_type='application/json; charset=utf-8'
    )
    return response

@csrf.exempt
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json()
    events = body.get("events", [])

    for event in events:
        if event.get("type") == "message" and event["message"]["type"] == "text":
            user_id = event["source"]["userId"]
            user_message = event["message"]["text"]
            reply_text = replay_msg(user_message)

            send_push_message(user_id, [{"type": "text", "text": reply_text}])

    return jsonify({"status": "ok"})

@csrf.exempt
@app.route("/healthz")
def health():
    return "ok", 200

@csrf.exempt
@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad Request"}), 400

@app.errorhandler(401)
def unauthorized(error):
    return jsonify({"error": "Unauthorized"}), 401

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal Server Error"}), 500

@csrf.exempt
@app.route("/account_management", methods=["GET", "POST"])
def account_management():
    # 先從 query 讀 token
    token = request.args.get("token")
    if not token:
        flash("缺少 token，請重新登入。", "error")
        return redirect(url_for('login'))
    try:
        uid = decrypt_token(token)
    except Exception:
        flash("無效的 token，請重新登入。", "error")
        return redirect(url_for('login'))

    # POST：更新 username（和原本 uid 相同）
    if request.method == "POST":
        new_name = request.form.get("username", "").strip()
        if not new_name:
            flash("使用者名稱不能為空。", "error")
        else:
            update_user_profile(uid=uid, username=new_name)
            flash("使用者名稱已更新。", "success")
        # 更新完後仍留在同一頁，token 不變
        return redirect(url_for('account_management', token=token))

    # GET：顯示帳號資訊
    user_data = get_user_data(uid)
    if not user_data:
        flash("找不到使用者資料，請重新登入。", "error")
        return redirect(url_for('login'))
    return render_template('account_management.html',
                           user_data=user_data,
                           token=token)

@csrf.exempt
@app.route('/update_username', methods=['POST'])
def update_username_route():
    token = request.form.get('token') or request.args.get('token')
    if not token:
        flash("缺少 token，更新失敗。", "error")
        return redirect(url_for('login'))
    try:
        uid = decrypt_token(token)
    except Exception:
        flash("無效的 token，更新失敗。", "error")
        return redirect(url_for('login'))

    new_name = request.form.get('username', '').strip()
    if not new_name:
        flash('更新失敗：使用者名稱不能為空', 'error')
    else:
        update_user_profile(uid=uid, username=new_name)
        flash('使用者名稱更新成功', 'success')
    return redirect(url_for('account_management', token=token))

@csrf.exempt
@app.route("/active/<county_en>")
def active(county_en):
    # 1. 參數合法性檢查（與您原本相同）
    if county_en != 'all':
        county_zh = COUNTY_MAP.get(county_en)
        if not county_zh:
            return render_template("active.html",
                                   county=county_en,
                                   events=[],
                                   error="找不到對應的縣市"), 404
    else:
        county_zh = None

    # 2. 讀 CSV，蒐集所有符合縣市／all 的 events
    events = []
    with open("datas/活動.csv", newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            if county_en!='all' and row["縣市名稱"]!=county_zh:
                continue

            # 清洗描述、組地址…（沿用您原本的邏輯）
            raw_desc = row.get("文字描述","").strip()
            m = re.match(r'(?i)^\s*<p>(.*)</p>\s*$', raw_desc, flags=re.S)
            desc = m.group(1).strip() if m else raw_desc
            desc = re.sub(r'<[^>]+>','', desc)
            desc = html.unescape(desc).strip()

            parts = [row.get("行政區","").strip(), row.get("街道名稱","").strip()]
            address = " ".join(p for p in parts if p) or row.get("資料提供單位","").strip()

            events.append({
              "name":    row.get("資料名稱","").strip(),
              "desc":    desc,
              "contact": row.get("聯絡電話","").strip(),
              "time":    row.get("活動場次時間","").strip(),
              "address": address,
              "county":  row.get("縣市名稱","").strip(),
              "id":      row.get("唯一識別碼","").strip()
            })

    # 3. all 模式：依 order_map 排序
    if county_en=='all':
        ordered = list(COUNTY_MAP.values())
        order_map = {c:i for i,c in enumerate(ordered)}
        events.sort(key=lambda e: order_map.get(e["county"], float("inf")))
        display_county = "所有縣市"
    else:
        display_county = county_zh

    # 4. 讀取分頁參數
    try:
        per_page = int(request.args.get("per_page", 10))
    except ValueError:
        per_page = 10
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    total = len(events)
    total_pages = math.ceil(total / per_page) or 1
    page = max(1, min(page, total_pages))

    # 5. 切片分頁
    start = (page - 1) * per_page
    events_page = events[start : start + per_page]

    # 6. render
    return render_template("active.html",
        county=display_county,
        events=events_page,
        error=None,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages
    )

@csrf.exempt
@app.route("/search/<keyword>")
def search(keyword):
    # --- 1. 解析分頁參數 ---
    try:
        per_page = int(request.args.get("per_page", 10))
    except ValueError:
        per_page = 10

    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    # --- 2. 關鍵字分詞（全轉小寫） ---
    words = [w.strip().lower() for w in keyword.split() if w.strip()]

    # --- 3. 讀 CSV 並過濾 ---
    matched = []
    with open("datas/活動.csv", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            # 先整理描述
            raw = row.get("文字描述", "").strip()
            m = re.match(r'(?i)^\s*<p>(.*)</p>\s*$', raw, flags=re.S)
            desc = m.group(1).strip() if m else raw
            desc = re.sub(r'<[^>]+>', '', desc)
            desc = html.unescape(desc).strip()

            # 組地址
            addr_parts = [row.get("行政區","").strip(), row.get("街道名稱","").strip()]
            address = " ".join(p for p in addr_parts if p)
            if not address:
                address = row.get("資料提供單位","").strip()

            # 建立單筆 event
            event = {
                "name":    row.get("資料名稱","").strip(),
                "desc":    desc,
                "time":    row.get("活動場次時間","").strip(),
                "address": address,
                "county":  row.get("縣市名稱","").strip(),
                "id":      row.get("唯一識別碼","").strip()
            }

            # 做關鍵字全包含檢查
            text = " ".join([event["name"], event["desc"], event["address"]]).lower()
            if all(w in text for w in words):
                matched.append(event)

    # --- 4. 分頁計算 ---
    total = len(matched)
    total_pages = math.ceil(total / per_page) or 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    events_page = matched[start : start + per_page]

    # --- 5. 回傳 render_template ---
    # 這裡我們用 active.html，並把 county 欄位傳成「搜尋『keyword'』」
    return render_template(
        "active.html",
        county=f"{'、'.join(list(keyword.split()))}相關",
        events=events_page,
        error=None,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages
    )

@app.route('/info')
def info():
    eid = request.args.get('id')
    if not eid or eid not in EVENTS:
        abort(404)
    event = EVENTS[eid]
    m = re.match(r'(?i)^\s*<p>(.*)</p>\s*$', event["文字描述"], flags=re.S)
    desc = m.group(1).strip() if m else event["文字描述"]
    desc = re.sub(r'<[^>]+>', '', desc)
    desc = html.unescape(desc).strip()
    event["文字描述"] = desc
    return render_template('info.html', event=event)

@csrf.exempt
@app.route("/trip/<days>/<active>")
def trip(days, active):
    token = session.get('token') or ''
    home_station = session.get('home') or '1000' # 預設北車

    # 驗證天數是否正確
    if days not in ['one-day', 'two-day', 'three-day']:
        abort(404)

    # 確認唯一識別碼是否存在於 EVENTS
    if active not in EVENTS:
        abort(404, description="No events found with the specified unique identifier.")

    # 取得符合唯一識別碼的資料
    event_data = EVENTS[active]

    # 整合資料為字串格式
    def package_data(event):
        return f"##{event['唯一識別碼']}:{event['資料名稱']}({event['縣市名稱']}{event['行政區(鄉鎮區)名稱']}) \n 景點資料：\n{find(ATTRACTIONS, event['縣市名稱'])}\n\n 餐廳資料：\n{find(RESTAURANT, event['縣市名稱'])}\n\n 住宿資料：\n{find(HOTEL, event['縣市名稱'])}\n\n 活動資料：\n名稱: {event['資料名稱']}\n地點: {event['行政區(鄉鎮區)名稱']} {event['街道名稱']}\n描述: {event['文字描述']}\n聯絡方式: {event['聯絡電話']}#{event['分機']}\n"

    packaged_data = package_data(event_data)

    # 根據天數生成行程格式
    days_map = {
        'one-day': 1,
        'two-day': 2,
        'three-day': 3
    }
    total_days = days_map[days]
    trip_data = f"# {total_days} Days\n{packaged_data}"

    # 呼叫 AI 排行程
    ai_response = ask_ai(trip_data)
    #ai_response = "```json\n{\n    \"1\": [\n        {\n            \"title\": \"2024新北觀光工廠｜青春造一夏(板橋區)\",\n            \"time\": \"10:00 - 16:00\",\n            \"location\": \"板橋區\",\n            \"tags\": \"文化, 觀光, 體驗\"\n        },\n        {\n            \"title\": \"午餐與休息\",\n            \"time\": \"12:00 - 13:30\",\n            \"location\": \"板橋區附近餐廳\",\n            \"tags\": \"餐飲, 休息\"\n        },\n        {\n            \"title\": \"自由活動或周邊景點\",\n            \"time\": \"16:00 - 18:00\",\n            \"location\": \"板橋區\",\n            \"tags\": \"自由, 探索\"\n        }\n    ],\n    \"2\": [\n        {\n            \"title\": \"早晨漫步與早餐\",\n            \"time\": \"08:00 - 09:30\",\n            \"location\": \"住宿地點附近\",\n            \"tags\": \"休息, 餐飲\"\n        },\n        {\n            \"title\": \"參觀板橋林家花園\",\n            \"time\": \"09:30 - 12:00\",\n            \"location\": \"板橋區\",\n            \"tags\": \"歷史, 建築, 園林\"\n        },\n        {\n            \"title\": \"午餐\",\n            \"time\": \"12:00 - 13:30\",\n            \"location\": \"板橋區\",\n            \"tags\": \"餐飲\"\n        }\n    ],\n    \"3\": [\n        {\n            \"title\": \"在地市場體驗 (如湳雅夜市)\",\n            \"time\": \"09:00 - 11:00\",\n            \"location\": \"板橋區\",\n            \"tags\": \"在地, 文化, 體驗\"\n        },\n        {\n            \"title\": \"午餐與購物\",\n            \"time\": \"11:00 - 13:00\",\n            \"location\": \"板橋區\",\n            \"tags\": \"餐飲, 購物\"\n        },\n        {\n            \"title\": \"整理行李與離開\",\n            \"time\": \"13:00 onwards\",\n            \"location\": \"住宿地點\",\n            \"tags\": \"休息, 離開\"\n        }\n    ]\n}\n```"

    def fix_json_format_with_markers(json_string):
        # 移除頭尾的 ```json 和 ```
        if json_string.startswith("```json"):
            json_string = json_string[7:]  # 移除開頭的 ```json
        if json_string.endswith("```"):
            json_string = json_string[:-3]  # 移除結尾的 ```

        # 清理多餘的換行符號與空格
        cleaned_string = json_string.replace("\\n", "").replace("    ", "").strip()

        try:
            # 將清理後的字串解析為 JSON
            parsed_json = json.loads(cleaned_string)
            return parsed_json
        except json.JSONDecodeError as e:
            print(f"JSON 解析錯誤：{e}")
            return None
        
    ai_response=fix_json_format_with_markers(ai_response)

    print(ai_response)

    # 將結果渲染到模板
    return render_template('trip.html', days=days, active=active, ai_response=ai_response, event=event_data, token=token)

@app.route('/save_data/<flow>', methods=['POST'])
@csrf.exempt
def save_data(flow):
    """未完成"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    
    token = data.get('token')
    schedule = data.get('schedule')
    
    if not token:
        return jsonify({"error": "Missing token"}), 400
    if not schedule or not isinstance(schedule, dict) or not schedule:
        return jsonify({"error": "Missing or invalid schedule"}), 400
    
    # 驗證 token（示例：檢查是否匹配 session 或資料庫）
    if token != session.get('token'):  # 假設使用 session 驗證
        return jsonify({"error": "Invalid token"}), 401
    
    if flow not in ['new', 'update']:
        return jsonify({"error": "Invalid flow type"}), 400
    
    # 繼續儲存邏輯...
    if flow == 'new':
        trip_id = str(uuid.uuid4())
    else:  # flow == 'update'
        trip_id = data.get('trip_id')
        if not trip_id:
            return jsonify({"error": "Missing trip_id for update flow"}), 400
        
    try:
        uid = decrypt_token(token)
        if not uid:
            return jsonify({"error": "無效的 token"}), 401

        # 將 schedule 轉成 JSON 字串
        schedule_json = json.dumps(schedule, ensure_ascii=False)

        # 儲存到資料庫
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        current_time = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO schedules (uid, trip_id, schedule, created_at) VALUES (?, ?, ?, ?)",
            (uid, trip_id, schedule_json, current_time)
        )
        conn.commit()
        conn.close()

        # 可選：記錄日誌
        save_log(f"User {uid} saved schedule to database")

        return jsonify({"message": "行程儲存成功"}), 200
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=True)