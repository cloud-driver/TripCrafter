import os
import requests
import secrets
import jwt as pyjwt
import json
import uuid
from flask import Flask, request, redirect, jsonify, session, send_from_directory, Response, render_template, url_for, flash, abort
from send import Keep, update_user_profile, get_user_data, save_log, send_push_message, replay_msg, find_user_by_identity, delete_user_profile
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
import time

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

BS = AES.block_size

def _pad(s: bytes) -> bytes:
    padding = BS - len(s) % BS
    return s + bytes([padding] * padding)

def _unpad(s: bytes) -> bytes:
    return s[:-s[-1]]

def encrypt_token(uid: str) -> str:
    """
    1. payload = {"uid": uid, "iat": timestamp, "ip": requester IP}
    2. pad + AES-CBC 加密
    3. base64.urlsafe_b64encode(iv + ct)
    """
    iv = secrets.token_bytes(BS)
    cipher = AES.new(AES_KEY.encode(), AES.MODE_CBC, iv)

    payload = {
        "uid": uid,
        "iat": int(time.time()),
        "ip": request.remote_addr
    }
    raw = json.dumps(payload).encode("utf-8")
    ct = cipher.encrypt(_pad(raw))
    return base64.urlsafe_b64encode(iv + ct).decode("utf-8")

def decrypt_token(token: str, check_ip=False) -> dict:
    """
    解密 token，預設不檢查 IP
    """
    if not token:
        raise ValueError("Missing token")

    try:
        data = base64.urlsafe_b64decode(token.encode("utf-8"))
        iv, ct = data[:BS], data[BS:]
        cipher = AES.new(AES_KEY.encode(), AES.MODE_CBC, iv)
        pt = cipher.decrypt(ct)
        payload = json.loads(_unpad(pt).decode("utf-8"))
    except Exception:
        raise ValueError("無效的 token")

    now = int(time.time())
    # 驗證 1 小時過期
    if now - payload.get("iat", 0) > 3600:
        raise ValueError("Token 已過期，請重新登入")

    # 可選的 IP 驗證（預設關閉）
    if check_ip and payload.get("ip") != request.remote_addr:
        raise ValueError("IP 錯誤，請重新登入")

    return payload

def require_login(f):
    """登入驗證裝飾器"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 優先從 URL 獲取 token，其次從 session
        token = request.args.get('token') or session.get('token')
        
        if not token:
            flash("請先登入。", "error")
            return redirect(url_for('login'))
        
        try:
            payload = decrypt_token(token, check_ip=False)
            # 將解密後的資訊存入 g 供後續使用
            from flask import g
            g.current_user_uid = payload['uid']
            g.current_token = token
            
            # 確保 session 中有有效的 token
            session['token'] = token
            session.permanent = True
            
        except Exception as e:
            session.pop('token', None)
            flash("登入已過期，請重新登入。", "error")
            return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    
    return decorated_function

@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

@csrf.exempt
@app.route("/")
def home():
    return render_template('index.html')

@csrf.exempt
@app.route("/login")
def login():
    # 檢查 session 中的 token
    token = session.get('token')
    if token:
        try:
            decrypt_token(token, check_ip=False)
            return redirect(url_for('account_management'))
        except:
            session.pop('token', None)
    
    return render_template('login.html')

@csrf.exempt
@app.route("/logout")
def logout():
    token = session.pop('token', None)
    if token:
        try:
            info = decrypt_token(token, check_ip=False)
            uid = info["uid"]
            username = get_user_data(uid).get("username", "使用者")
            flash(f"{username} 已成功登出。", "success")
        except:
            pass
    else:
        flash("您已登出。", "info")
    return redirect(url_for('login'))

@require_login
@app.route('/delete_account')
def delete_account():
    from flask import g
    uid = g.current_user_uid
    
    success = delete_user_profile(uid)
    
    if success:
        session.clear()
        flash("您的帳號已成功刪除。", "success")
        return redirect(url_for('login'))
    else:
        flash("刪除帳號失敗，請稍後再試。", "error")
        return redirect(url_for('account_management'))

@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/line")
def login_line():
    uid = None
    # 優先從 URL 獲取，其次從 session
    token = request.args.get("token") or session.get('token')
    
    if token:
        try:
            info = decrypt_token(token, check_ip=False)
            uid = info.get("uid")
        except Exception:
            flash("無效的 token，請重新登入。", "error")
            return redirect(url_for("login"))
        
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

    session['oauth_state_line'] = state
    session['uid_id'] = uid

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
            final_uid = update_user_profile(uid=uid, login_type='line', user_id=user_id, display_name=display_name, email=email, username=username)
            if flow == 'register':
                save_log(f"{user_id} (Line) registered with uid {final_uid}")
                return handle_login_success(final_uid, "註冊成功！")
            else: # link
                save_log(f"Linked Line account {user_id} to uid {final_uid}")
                return handle_login_success(final_uid, "LINE 帳號連結成功！")
        
        elif flow == 'login':
            found_user = find_user_by_identity(login_type='line', provider_id=user_id)
            if found_user:
                save_log(f"{user_id} (Line) logged in with existing uid {found_user['uid']}")
                return handle_login_success(found_user['uid'])
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
    uid = None
    # 優先從 URL 獲取，其次從 session
    token = request.args.get("token") or session.get('token')
    
    if token:
        try:
            info = decrypt_token(token, check_ip=False)
            uid = info.get("uid")
        except Exception:
            flash("無效的 token，請重新登入。", "error")
            return redirect(url_for("login"))

    username = request.args.get("username")
    state = secrets.token_hex(16)

    if username:
        session['flow'] = 'register'
        session['username'] = username
        if not uid:
            uid = str(uuid.uuid4())
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
    auth_url = f"{GOOGLE_AUTHORIZATION_URL}?{'&'.join([f'{k}={v}' for k,v in params.items()])}"
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
            final_uid = update_user_profile(uid=uid, login_type='google', user_id=user_id, display_name=display_name, email=email, username=username)
            if flow == 'register':
                save_log(f"{user_id} (Google) registered with uid {final_uid}")
                return handle_login_success(final_uid, "註冊成功！")
            else: # link
                save_log(f"Linked Google account {email} to uid {final_uid}")
                return handle_login_success(final_uid, "Google 帳號連結成功！")

        elif flow == 'login':
            found_user = find_user_by_identity(login_type='google', email=email)
            if found_user:
                save_log(f"{user_id} (Google) logged in with existing uid {found_user['uid']}")
                return handle_login_success(found_user['uid'])
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

@require_login
@app.route("/account_management", methods=["GET", "POST"])
def account_management():
    from flask import g
    uid = g.current_user_uid
    token = g.current_token

    if request.method == "POST":
        new_name = request.form.get("username", "").strip()
        if not new_name:
            flash("使用者名稱不能為空。", "error")
        else:
            update_user_profile(uid=uid, username=new_name)
            flash("使用者名稱已更新。", "success")
        
        # POST 後重新導向，不帶任何參數
        return redirect(url_for('account_management'))

    # GET：顯示帳號資訊
    user_data = get_user_data(uid)
    if not user_data:
        flash("找不到使用者資料，請重新登入。", "error")
        return redirect(url_for('login'))
    
    return render_template('account_management.html',
                           user_data=user_data,
                           token=token)

@require_login
@csrf.exempt
@app.route('/update_username', methods=['POST'])
def update_username_route():
    from flask import g
    uid = g.current_user_uid

    new_name = request.form.get('username', '').strip()
    if not new_name:
        flash('更新失敗：使用者名稱不能為空', 'error')
    else:
        update_user_profile(uid=uid, username=new_name)
        flash('使用者名稱更新成功', 'success')
    
    return redirect(url_for('account_management'))

# 修改登入成功後的處理
def handle_login_success(uid, message="登入成功！"):
    """統一處理登入成功的邏輯"""
    token = encrypt_token(uid)
    session['token'] = token
    session.permanent = True
    flash(message, "success")
    return redirect(url_for('account_management'))

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
    return render_template('info.html', event=event)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))