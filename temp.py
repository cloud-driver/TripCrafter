# -*- coding: utf-8 -*-
from gevent import monkey
monkey.patch_all()

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
from api_routes import api_bp
from gevent.pywsgi import WSGIServer

if os.path.exists(".env"): load_dotenv()

app = Flask(__name__, static_folder='assets', static_url_path='/assets')
app.config['JSON_AS_ASCII'] = False
app.secret_key = secrets.token_hex(24)
app.config['SECRET_PAGE_PASSWORD'] = os.getenv('SECRET_PAGE_PASSWORD')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['WTF_CSRF_EXEMPT_LIST'] = ['api.api_search_station']
app.permanent_session_lifetime = timedelta(days=1)
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])

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
            save_log(f"解密錯誤：{e}")
            return None
    else:
        return None

# LINE 登入
@limiter.limit("5 per minute")
@app.route("/login/line")
def login_line():
    uid = decrypt_token(request.args.get("token"))
    username = request.args.get("username")
    # 從 request 取得車站資訊
    home_station_code = request.args.get("homeStationCode")
    home_station_name = request.args.get("homeStationName")
    state = secrets.token_hex(16)

    # 根據參數判斷流程
    if username:
        session['flow'] = 'register'
        session['username'] = username
        # 將車站資訊存入 session，以便 callback 流程使用
        session['home_station_code'] = home_station_code
        session['home_station_name'] = home_station_name
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
        # 從 session 取出車站資訊
        home_station_code = session.pop("home_station_code", None)
        home_station_name = session.pop("home_station_name", None)
        
        # 登入/註冊成功後要導向的網址
        next_url = session.pop('next_url', None)

        if flow in ['register', 'link']:
            # 註冊 或 連結流程
            final_uid = update_user_profile(
                uid=uid, login_type='line', user_id=user_id, 
                display_name=display_name, email=email, username=username,
                home_station_code=home_station_code, home_station_name=home_station_name
            )
            
            # --- START: 註冊流程修改 ---
            if flow == 'register':
                save_log(f"{user_id} (Line) registered with uid {final_uid}")
                flash("註冊成功！", "success")
                session['token'] = encrypt_token(final_uid) # 註冊成功後直接設定 token
                
                # 註冊成功後，順便將車站資訊存入 session
                if home_station_code and home_station_name:
                    session['homeStationCode'] = home_station_code
                    session['homeStationName'] = home_station_name
                
                # 導向邏輯
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect(url_for('account_management', token=session['token']))
            # --- END: 註冊流程修改 ---
            
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
                # 登入成功時，將使用者資料中的車站資訊寫入 session
                if found_user.get("homeStationCode") and found_user.get("homeStationName"):
                    session['homeStationCode'] = found_user["homeStationCode"]
                    session['homeStationName'] = found_user["homeStationName"]
                
                # 導向邏輯
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect(url_for('account_management', token=session['token']))
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

@limiter.limit("5 per minute")
@app.route("/login/google")
def login_google():
    uid = decrypt_token(request.args.get("token"))
    username = request.args.get("username")
    # 從 request 取得車站資訊
    home_station_code = request.args.get("homeStationCode")
    home_station_name = request.args.get("homeStationName")
    state = secrets.token_hex(16)

    # 根據參數判斷流程
    if username:
        session['flow'] = 'register'
        session['username'] = username
        # 將車站資訊存入 session，以便 callback 流程使用
        session['home_station_code'] = home_station_code
        session['home_station_name'] = home_station_name
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
        # 從 session 取出車站資訊
        home_station_code = session.pop("home_station_code", None)
        home_station_name = session.pop("home_station_name", None)
        
        # 登入/註冊成功後要導向的網址
        next_url = session.pop('next_url', None)

        if flow in ['register', 'link']:
            # 註冊 或 連結流程
            final_uid = update_user_profile(
                uid=uid, login_type='google', user_id=user_id, 
                display_name=display_name, email=email, username=username,
                home_station_code=home_station_code, home_station_name=home_station_name
            )
            
            # --- START: 註冊流程修改 ---
            if flow == 'register':
                save_log(f"{user_id} (Google) registered with uid {final_uid}")
                flash("註冊成功！", "success")
                session['token'] = encrypt_token(final_uid) # 註冊成功後直接設定 token

                # 註冊成功後，順便將車站資訊存入 session
                if home_station_code and home_station_name:
                    session['homeStationCode'] = home_station_code
                    session['homeStationName'] = home_station_name
                
                # 導向邏輯
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect(url_for('account_management', token=session['token']))
            # --- END: 註冊流程修改 ---

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
                # 登入成功時，將使用者資料中的車站資訊寫入 session
                if found_user.get("homeStationCode") and found_user.get("homeStationName"):
                    session['homeStationCode'] = found_user["homeStationCode"]
                    session['homeStationName'] = found_user["homeStationName"]
                
                # 導向邏輯
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect(url_for('account_management', token=session['token']))
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