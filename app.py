import os
import requests
import secrets
import jwt as pyjwt
import json
import uuid
from flask import Flask, request, redirect, jsonify, session, send_from_directory, Response, render_template, url_for, flash
from send import Keep, update_user_profile, get_user_data, save_log, send_push_message, replay_msg, find_user_by_identity, delete_user_profile
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

@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

@csrf.exempt
@app.route("/")
def home():
    uid = session.get('uid')
    if not uid:
        return render_template('index.html')
    else:
        return redirect(url_for('account_management', uid=uid))
    
@csrf.exempt
@app.route("/logout")
def logout():
    uid = session.pop('uid', None)
    if uid:
        userdata = get_user_data(uid)
        username = userdata.get("username", "使用者") if userdata else "使用者"
        flash(f"{username} 已成功登出。")
    else:
        flash("您已登出。")
    return redirect(url_for('home'))

@app.route('/delete_account/<uid>')
@limiter.limit("3 per hour")
def delete_account(uid):
    logged_in_uid = session.get('uid')
    if not logged_in_uid or logged_in_uid != uid:
        flash("權限不足，無法刪除此帳號。", "error")
        return redirect(url_for('home'))

    success = delete_user_profile(uid)

    if success:
        session.clear()
        flash("您的帳號已成功刪除。", "success")
        return redirect(url_for('home'))
    else:
        flash("刪除帳號失敗，請稍後再試。", "error")
        return redirect(url_for('account_management', uid=uid))

# LINE 登入
@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/line")
def login_line():
    uid = request.args.get("uid")
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
        return redirect(url_for('home'))

    token_url = "https://api.line.me/oauth2/v2.1/token"
    payload = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_response = requests.post(token_url, data=payload, headers=headers)

    if token_response.status_code != 200:
        flash("無法從 LINE 獲取 Access Token", "error")
        return redirect(url_for('home'))

    token_data = token_response.json()
    id_token_jwt = token_data.get("id_token")
    
    if not id_token_jwt:
        flash("無法從 LINE 獲取 ID Token", "error")
        return redirect(url_for('home'))

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
            return redirect(url_for('account_management', uid=final_uid))
        
        elif flow == 'login':
            # 登入流程
            found_user = find_user_by_identity(login_type='line', provider_id=user_id)
            if found_user:
                save_log(f"{user_id} (Line) logged in with existing uid {found_user['uid']}")
                flash("登入成功！", "success")
                session['uid'] = found_user['uid']
                return redirect(url_for('account_management', uid=found_user['uid']))
            else:
                save_log(f"Login failed: Line user {user_id} not found. Asking to register.")
                flash("此 LINE 帳號尚未註冊，請先註冊。", "error")
                return redirect(url_for('home'))
        else:
            save_log(f"Unknown flow type: {flow}")
            flash("發生未知錯誤，請重試。", "error")
            return redirect(url_for('home'))

    except pyjwt.InvalidTokenError as e:
        save_log(f"ID Token驗證失敗：{e}")
        flash(f"ID Token驗證失敗：{e}", "error")
        return redirect(url_for('home'))

@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/google")
def login_google():
    uid = request.args.get("uid")
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
        return redirect(url_for('home'))
    
    if not code:
        flash("授權失敗：未收到授權碼。", "error")
        return redirect(url_for('home'))

    token_data = {
        "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
    }
    response = requests.post(GOOGLE_TOKEN_URL, data=token_data)
    token_info = response.json()

    if "error" in token_info:
        flash(f"獲取Token失敗：{token_info.get('error_description', token_info.get('error'))}", "error")
        return redirect(url_for('home'))

    id_token_jwt = token_info.get("id_token")
    if not id_token_jwt:
        flash("獲取ID Token失敗。", "error")
        return redirect(url_for('home'))

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
            return redirect(url_for('account_management', uid=final_uid))

        elif flow == 'login':
            # 登入流程
            found_user = find_user_by_identity(login_type='google', email=email)
            if found_user:
                save_log(f"{user_id} (Google) logged in with existing uid {found_user['uid']}")
                flash("登入成功！", "success")
                session['uid'] = found_user['uid']
                return redirect(url_for('account_management', uid=found_user['uid']))
            else:
                save_log(f"Login failed: Google user {email} not found. Asking to register.")
                flash("此 Google 帳號尚未註冊，請先註冊。", "error")
                return redirect(url_for('home'))
        else:
            save_log(f"Unknown flow type: {flow}")
            flash("發生未知錯誤，請重試。", "error")
            return redirect(url_for('home'))

    except ValueError as e:
        save_log(f"ID Token驗證失敗：{e}")
        flash(f"ID Token驗證失敗：{e}", "error")
        return redirect(url_for('home'))

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

@csrf.exempt
@app.route("/account_management", methods=["GET", "POST"])
def account_management():
    # POST 請求處理邏輯
    if request.method == "POST":
        uid = request.form.get("uid")
        username = request.form.get("username")

        if not uid or not username:
            flash("UID 和使用者名稱不能為空。", "error")
            if uid:
                return redirect(url_for('account_management', uid=uid))
            else:
                return redirect(url_for('home'))

        update_user_profile(uid=uid, username=username)
        flash("使用者名稱已更新。", "success")
        return redirect(url_for('account_management', uid=uid))

    # GET 請求處理邏輯
    uid = request.args.get("uid")
    if not uid:
        flash("請提供有效的 UID 以管理帳戶。", "error")
        return redirect(url_for('home'))

    user_data = get_user_data(uid)
    if not user_data:
        flash("找不到該使用者的資料。", "error")
        return redirect(url_for('home'))

    return render_template('account_management.html', user_data=user_data)

@app.route('/update_username', methods=['POST'])
@csrf.exempt
def update_username_route():
    """
    從 form 拿到 uid 與新的 username，呼叫 update_user_profile 更新，
    然後重新導回 /account_management?uid=…
    """
    uid = request.values.get('uid') or session.get('uid_id')
    new_name = request.form.get('username', '').strip()

    if not uid or not new_name:
        flash('更新失敗：參數不足', 'error')
        return redirect(url_for('account_management', uid=uid))

    update_user_profile(uid, username=new_name)

    flash('使用者名稱更新成功', 'success')
    return redirect(url_for('account_management', uid=uid))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))