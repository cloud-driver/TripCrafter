import os
import requests
import secrets
import jwt as pyjwt
import json
from flask import Flask, request, redirect, jsonify, session, send_from_directory, Response, render_template, url_for, flash
from send import Keep, update_user_profile, get_user_data, save_log, send_push_message, replay_msg, ask_ai
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect, generate_csrf
from datetime import timedelta
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

if os.path.exists(".env"): load_dotenv()

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = secrets.token_hex(24)
app.config['SECRET_PAGE_PASSWORD'] = os.getenv('SECRET_PAGE_PASSWORD')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.permanent_session_lifetime = timedelta(minutes=10)
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

@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

@csrf.exempt
@app.route("/")
def home():
    return render_template('index.html')

# LINE 登入
@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/line")
def login_line():
    uid = request.args.get("uid")
    username = request.args.get("username")
    state = secrets.token_hex(16)

    session['oauth_state_line'] = state
    session['uid_id'] = uid
    if username:
        session['username'] = username

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
    uid = session.pop("uid_id", None)
    username = session.pop("username", None)

    if not state or state != session.pop("oauth_state_line", None):
        save_log("fail by state")
        return "驗證失敗，state 不一致", 400

    token_url = "https://api.line.me/oauth2/v2.1/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_response = requests.post(token_url, data=payload, headers=headers)

    if token_response.status_code != 200:
        return "無法獲取 Access Token", 400

    token_data = token_response.json()
    id_token_jwt = token_data.get("id_token")
    
    if not id_token_jwt:
        return "無法獲取 ID Token", 400

    try:
        decoded = pyjwt.decode(id_token_jwt, CLIENT_SECRET, audience=str(CLIENT_ID), algorithms=["HS256"])
        user_id = decoded.get("sub")
        display_name = decoded.get("name", "未知")
        email = decoded.get("email")

        save_log(f"{user_id} (Line) login with uidID in {uid}")
        update_user_profile(uid=uid, login_type='line', user_id=user_id, display_name=display_name, email=email, username=username)
        return redirect(url_for('account_management', uid=uid))
    except pyjwt.InvalidTokenError as e:
        save_log(f"ID Token驗證失敗：{e}")
        return f"ID Token驗證失敗：{e}", 400

# Google 登入
@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/google")
def login_google():
    uid = request.args.get("uid")
    username = request.args.get("username")
    state = secrets.token_hex(16)

    session['oauth_state_google'] = state
    session['uid_id'] = uid
    if username:
        session['username'] = username

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
    uid = session.pop("uid_id", None)
    username = session.pop("username", None)

    if not state or state != session.pop("oauth_state_google", None):
        save_log("Google login fail by state")
        return "驗證失敗，state 不一致", 400
    
    if not code:
        return "授權失敗：未收到授權碼。", 400

    token_data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    response = requests.post(GOOGLE_TOKEN_URL, data=token_data)
    token_info = response.json()

    if "error" in token_info:
        return f"獲取Token失敗：{token_info.get('error_description', token_info.get('error'))}", 400

    id_token_jwt = token_info.get("id_token")

    if not id_token_jwt:
        return "獲取ID Token失敗。", 400

    try:
        idinfo = id_token.verify_oauth2_token(id_token_jwt, google_requests.Request(), GOOGLE_CLIENT_ID)
        user_id = idinfo['sub']
        display_name = idinfo.get('name', '未知')
        email = idinfo.get('email')

        save_log(f"{user_id} (Google) login with uidID in {uid} via Google")
        update_user_profile(uid=uid, login_type='google', user_id=user_id, display_name=display_name, email=email, username=username)
        return redirect(url_for('account_management', uid=uid))
    except ValueError as e:
        save_log(f"ID Token驗證失敗：{e}")
        return f"ID Token驗證失敗：{e}", 400

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

# 整合後的帳戶管理頁面路由 (GET 和 POST)
@csrf.exempt
@app.route("/account_management", methods=["GET", "POST"])
def account_management():
    if request.method == "POST":
        uid = request.form.get("uid")
        username = request.form.get("username")

        if not uid or not username:
            flash("UID 和使用者名稱不能為空。", "error")
            # 如果 uid 存在，即使 username 為空也重新導向，讓使用者看到錯誤訊息
            if uid:
                return redirect(url_for('account_management', uid=uid))
            else: # 如果連 uid 都沒有，只能導回首頁
                return redirect(url_for('home'))

        update_user_profile(uid=uid, username=username)
        flash("使用者名稱已更新。", "success")
        return redirect(url_for('account_management', uid=uid))

    # 以下為 GET 請求的處理邏輯
    uid = request.args.get("uid")
    if not uid:
        flash("請提供有效的 UID 以管理帳戶。", "error")
        return redirect(url_for('home'))

    user_data = get_user_data(uid)
    if not user_data:
        user_data = {"uid": uid, "username": "未設定"}
        update_user_profile(uid=uid)

    return render_template('account_management.html', user_data=user_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
