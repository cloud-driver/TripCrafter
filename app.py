# -*- coding: utf-8 -*-
from gevent import monkey
monkey.patch_all()

import os
import requests
import secrets
import jwt as pyjwt
import json
import uuid
from flask import Flask, request, redirect, jsonify, session, send_from_directory, Response, render_template, url_for, flash, abort, send_file
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
from werkzeug.utils import secure_filename
import threading
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from math import radians, cos, sin, asin, sqrt

COUNTY_MAP = {
    "Lienchiang": "連江縣",
    "Taipei":     "臺北市",
    "NewTaipei":  "新北市",
    "Taoyuan":    "桃園市",
    "Taichung":   "臺中市",
    "Tainan":     "臺南市",
    "Kaohsiung":  "高雄市",
    "Keelung":    "基隆市",
    "HsinchuCity":"新竹市",
    "Hsinchu":    "新竹縣",
    "Miaoli":     "苗栗縣",
    "Changhua":   "彰化縣",
    "Nantou":     "南投縣",
    "Yunlin":     "雲林縣",
    "ChiayiCity": "嘉義市",
    "Chiayi":     "嘉義縣",
    "Pingtung":   "屏東縣",
    "Yilan":      "宜蘭縣",
    "Hualien":    "花蓮縣",
    "Taitung":    "臺東縣",
    "Penghu":     "澎湖縣",
    "Kinmen":     "金門縣",
    "Matsu":      "連江縣"
}

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
csrf = CSRFProtect(app)

UPLOAD_FOLDER = 'assets/uploads/memoirs'
VIDEO_FOLDER = 'assets/videos'
BGM_FOLDER = 'assets/bgm'
FONT_PATH = 'assets/fonts/NotoSansTC-Bold.ttf' # 請確保有中文字型

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['VIDEO_FOLDER'] = VIDEO_FOLDER
app.config['BGM_FOLDER'] = BGM_FOLDER

os.makedirs(os.path.join(app.root_path, UPLOAD_FOLDER), exist_ok=True)
os.makedirs(os.path.join(app.root_path, VIDEO_FOLDER), exist_ok=True)
os.makedirs(os.path.join(app.root_path, BGM_FOLDER), exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app.register_blueprint(api_bp, url_prefix='/api')

csrf.exempt(api_bp)

CLIENT_ID = int(os.getenv('LINE_LOGIN_CHANNEL_ID'))
CLIENT_SECRET = str(os.getenv('LINE_LOGIN_CHANNEL_SECRET'))
REDIRECT_URI = f"{str(os.getenv('URL'))}/callback/line"

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = f"{str(os.getenv('URL'))}/callback/google"

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

AES_KEY = os.getenv('TOKEN_AES_KEY', '')
if len(AES_KEY.encode()) not in (16, 24, 32):
    raise RuntimeError("AES_KEY error")

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
        eid = row['唯一識別碼']
        ATTRACTIONS[eid] = row

HOTEL = {}
with open('datas/景點.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        eid = row['唯一識別碼']
        HOTEL[eid] = row

RESTAURANT = {}
with open('datas/餐飲.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        eid = row['唯一識別碼']
        RESTAURANT[eid] = row

ALL_STATIONS_DATA = {}
try:
    with open('json/all_stations_data.json', encoding='utf-8') as f:
        ALL_STATIONS_DATA = json.load(f)
except Exception as e:
    save_log(f"Failed to load all_stations_data.json: {e}")

def link_callback(uri, rel):
    """
    將 HTML 中的相對路徑轉換為系統絕對路徑
    """
    # 如果是 /assets 開頭的資源 (字型、圖片、CSS)
    if uri.startswith('/assets'):
        # 去掉開頭的 /
        uri_path = uri.lstrip('/')
        # 組合專案根目錄與檔案路徑
        path = os.path.join(app.root_path, uri_path)
        # 確保路徑是絕對路徑
        abs_path = os.path.abspath(path)
        return abs_path
    return uri

def haversine(lon1, lat1, lon2, lat2):
    """
    計算兩點經緯度之間的距離 (公里)
    """
    try:
        lon1, lat1, lon2, lat2 = map(float, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1 
        dlat = lat2 - lat1 
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a)) 
        r = 6371 # 地球半徑 (km)
        return c * r
    except:
        return 99999 # 若座標無效，回傳極大值

def find(DATA, city_name):
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

BS = AES.block_size

def encrypt_token(uid: str) -> str:
    timestamp = str(int(time.time()))
    data = f"{uid}:{timestamp}"
    iv = secrets.token_bytes(BS)
    cipher = AES.new(AES_KEY.encode(), AES.MODE_CBC, iv)
    ct = cipher.encrypt(_pad(data.encode('utf-8'), BS))
    return base64.urlsafe_b64encode(iv + ct).decode('utf-8')

def decrypt_token(token: str) -> tuple:
    if token:
        try:
            data = base64.urlsafe_b64decode(token.encode('utf-8'))
            iv, ct = data[:BS], data[BS:]
            cipher = AES.new(AES_KEY.encode(), AES.MODE_CBC, iv)
            pt = _unpad(cipher.decrypt(ct), BS).decode('utf-8')
            uid, timestamp = pt.split(":")
            
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

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS memoirs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            image_path TEXT,
            user_text TEXT,
            ai_content TEXT,
            created_at TEXT NOT NULL
        )
    ''')
    
    try:
        cursor.execute("SELECT days FROM schedules LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE schedules ADD COLUMN days TEXT")

    try:
        cursor.execute("SELECT active FROM schedules LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE schedules ADD COLUMN active TEXT")
        
    try:
        cursor.execute("SELECT trip_name FROM schedules LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE schedules ADD COLUMN trip_name TEXT")

    try:
        cursor.execute("SELECT layout_type FROM memoirs LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE memoirs ADD COLUMN layout_type TEXT DEFAULT '1'")

    try:
        cursor.execute("SELECT share_token FROM memoirs LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE memoirs ADD COLUMN share_token TEXT")

    try:
        cursor.execute("SELECT video_path FROM memoirs LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE memoirs ADD COLUMN video_path TEXT")

    conn.commit()
    conn.close()

init_db()

# === 背景生成影片與通知 ===
def generate_video_task(memoir_id, uid, images_list, text_content, date_str):
    try:
        with app.app_context():
            # 1. 準備 BGM
            if not os.path.exists(app.config['BGM_FOLDER']):
                save_log(f"BGM folder missing for {memoir_id}")
                return
            bgm_files = [f for f in os.listdir(app.config['BGM_FOLDER']) if f.endswith('.mp3')]
            if not bgm_files:
                save_log(f"No BGM files found for {memoir_id}")
                return
            selected_bgm = random.choice(bgm_files)
            bgm_path = os.path.join(app.config['BGM_FOLDER'], selected_bgm)

            # 2. 處理圖片與文字
            clips = []
            try:
                font = ImageFont.truetype(FONT_PATH, 40)
            except:
                font = ImageFont.load_default()

            for index, img_name in enumerate(images_list):
                img_path = os.path.join(app.config['UPLOAD_FOLDER'], img_name)
                pil_img = Image.open(img_path).convert("RGB")
                
                target_size = (1280, 720)
                pil_img.thumbnail(target_size, Image.Resampling.LANCZOS)
                
                background = Image.new('RGB', target_size, (0, 0, 0))
                offset = ((target_size[0] - pil_img.width) // 2, (target_size[1] - pil_img.height) // 2)
                background.paste(pil_img, offset)
                
                draw = ImageDraw.Draw(background)
                
                if index == 0:
                    display_text = f"旅行回憶 - {date_str}"
                else:
                    sentences = text_content.split('，')
                    txt_idx = (index - 1) % len(sentences)
                    display_text = sentences[txt_idx]
                    if len(display_text) > 20: display_text = display_text[:20] + "..."

                text_bbox = draw.textbbox((0, 0), display_text, font=font)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]
                x = (target_size[0] - text_width) / 2
                y = target_size[1] - text_height - 50 

                draw.text((x+2, y+2), display_text, font=font, fill=(0, 0, 0))
                draw.text((x, y), display_text, font=font, fill=(255, 255, 255))

                img_array = np.array(background)
                clip = ImageClip(img_array).set_duration(4).crossfadein(1)
                clips.append(clip)

            # 3. 合成影片
            video = concatenate_videoclips(clips, method="compose")
            audio = AudioFileClip(bgm_path)
            if audio.duration > video.duration:
                final_audio = audio.subclip(0, video.duration)
            else:
                final_audio = audio.loop(duration=video.duration)
            
            video = video.set_audio(final_audio).audio_fadeout(2)
            
            output_filename = f"memoir_{memoir_id}_{uuid.uuid4().hex[:8]}.mp4"
            output_path = os.path.join(app.config['VIDEO_FOLDER'], output_filename)
            
            video.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', preset='medium', threads=4)

            # 4. 更新資料庫
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE memoirs SET video_path = ? WHERE id = ?", (output_filename, memoir_id))
            conn.commit()
            conn.close()
            
            # 5. 發送通知 (使用 send.py 的 get_user_data 讀取 JSON)
            user_data = get_user_data(uid)
            target_line_id = None
            
            if user_data:
                # 優先嘗試讀取 line_account 中的 userId
                line_acc = user_data.get('line_account')
                if line_acc and isinstance(line_acc, dict):
                    target_line_id = line_acc.get('userId')
            
            if target_line_id:
                video_url = f"{str(os.getenv('URL'))}/memoir/{memoir_id}"
                notify_msg = f"🎥 您的回憶錄影片已生成完畢！\n點擊觀看：{video_url}"
                send_push_message(target_line_id, [{"type": "text", "text": notify_msg}])
                save_log(f"Video notification sent to {target_line_id}")
            else:
                save_log(f"Video created but no LINE ID found for uid {uid} in users.json")

    except Exception as e:
        save_log(f"Background video generation failed: {e}")

@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

@csrf.exempt
@app.route("/test")
def test():
    session.clear()
    session['token'] = encrypt_token("7b9fca25-b071-43a9-952f-eafc5730cb10")
    session['home_station_code'] = "1000"
    session['home_station_name'] = "臺北"
    return render_template('test-search-station.html')

@csrf.exempt
@app.route("/")
def home():
    return render_template('index.html')

@csrf.exempt
@app.route("/index")
def index():
    return redirect(url_for('home'))

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        send_push_message("U19f5c7ea1eb5591d7d374a4a62374f0f", f"收到聯絡表單: {name}, {email}, {subject}, {message}")
        
        flash('您的訊息已成功送出！我們會盡快聯絡您。', 'success')
        return redirect(url_for('contact'))
        
    return render_template('contact.html')

@csrf.exempt
@app.route("/login")
def login():
    token = session.get('token')
    code_to_name = {code: data['name'] for code, data in ALL_STATIONS_DATA.items()}
    name_to_code = {data['name']: code for code, data in ALL_STATIONS_DATA.items()}
    
    if token:
        uid = decrypt_token(token)
        if uid:
            next_url = session.pop('next_url', None)
            if next_url:
                return redirect(next_url)
            else:
                return redirect(url_for('account_management', token=token))
        else:
            session.pop('token', None)
            session.pop('homeStationCode', None)
            session.pop('homeStationName', None)
            flash("登入已過期，請重新登入。", "error")
    
    return render_template('login.html', code_to_name=code_to_name, name_to_code=name_to_code)
    
@csrf.exempt
@app.route("/logout")
def logout():
    token = session.pop('token', None)
    session.pop('homeStationCode', None)
    session.pop('homeStationName', None)
    session.pop('next_url', None)
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

@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/line")
def login_line():
    uid = decrypt_token(request.args.get("token"))
    username = request.args.get("username")
    home_station_code = request.args.get("homeStationCode")
    home_station_name = request.args.get("homeStationName")
    state = secrets.token_hex(16)

    if username:
        session['flow'] = 'register'
        session['username'] = username
        session['home_station_code'] = home_station_code
        session['home_station_name'] = home_station_name
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
        f"&bot_prompt=aggressive"
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
        home_station_code = session.pop("home_station_code", None)
        home_station_name = session.pop("home_station_name", None)
        
        next_url = session.pop('next_url', None)

        if flow in ['register', 'link']:
            final_uid = update_user_profile(
                uid=uid, login_type='line', user_id=user_id, 
                display_name=display_name, email=email, username=username,
                home_station_code=home_station_code, home_station_name=home_station_name
            )
            
            if flow == 'register':
                save_log(f"{user_id} (Line) registered with uid {final_uid}")
                flash("註冊成功！", "success")
                session['token'] = encrypt_token(final_uid)
                
                if home_station_code and home_station_name:
                    session['homeStationCode'] = home_station_code
                    session['homeStationName'] = home_station_name
                
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect(url_for('account_management', token=session['token']))
            
            else:
                save_log(f"Linked Line account {user_id} to uid {final_uid}")
                flash("LINE 帳號連結成功！", "success")
                return redirect(url_for('account_management', token=encrypt_token(final_uid)))
        
        elif flow == 'login':
            found_user = find_user_by_identity(login_type='line', provider_id=user_id)
            if found_user:
                save_log(f"{user_id} (Line) logged in with existing uid {found_user['uid']}")
                flash("登入成功！", "success")
                session['token'] = encrypt_token(found_user['uid'])
                if found_user.get("homeStationCode") and found_user.get("homeStationName"):
                    session['homeStationCode'] = found_user["homeStationCode"]
                    session['homeStationName'] = found_user["homeStationName"]
                
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

@csrf.exempt
@limiter.limit("5 per minute")
@app.route("/login/google")
def login_google():
    uid = decrypt_token(request.args.get("token"))
    username = request.args.get("username")
    home_station_code = request.args.get("homeStationCode")
    home_station_name = request.args.get("homeStationName")
    state = secrets.token_hex(16)

    if username:
        session['flow'] = 'register'
        session['username'] = username
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
        home_station_code = session.pop("home_station_code", None)
        home_station_name = session.pop("home_station_name", None)
        
        next_url = session.pop('next_url', None)

        if flow in ['register', 'link']:
            final_uid = update_user_profile(
                uid=uid, login_type='google', user_id=user_id, 
                display_name=display_name, email=email, username=username,
                home_station_code=home_station_code, home_station_name=home_station_name
            )
            
            if flow == 'register':
                save_log(f"{user_id} (Google) registered with uid {final_uid}")
                flash("註冊成功！", "success")
                session['token'] = encrypt_token(final_uid)

                if home_station_code and home_station_name:
                    session['homeStationCode'] = home_station_code
                    session['homeStationName'] = home_station_name
                
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect(url_for('account_management', token=session['token']))

            else:
                save_log(f"Linked Google account {email} to uid {final_uid}")
                flash("Google 帳號連結成功！", "success")
                return redirect(url_for('account_management', token=encrypt_token(final_uid)))

        elif flow == 'login':
            found_user = find_user_by_identity(login_type='google', email=email)
            if found_user:
                save_log(f"{user_id} (Google) logged in with existing uid {found_user['uid']}")
                flash("登入成功！", "success")
                session['token'] = encrypt_token(found_user['uid'])
                if found_user.get("homeStationCode") and found_user.get("homeStationName"):
                    session['homeStationCode'] = found_user["homeStationCode"]
                    session['homeStationName'] = found_user["homeStationName"]
                
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
    token = request.args.get("token")
    if not token:
        flash("缺少 token，請重新登入。", "error")
        return redirect(url_for('login'))
    try:
        uid = decrypt_token(token)
        if not uid:
             flash("無效的 token，請重新登入。", "error")
             return redirect(url_for('login'))
    except Exception:
        flash("無效的 token，請重新登入。", "error")
        return redirect(url_for('login'))

    user_data = get_user_data(uid)
    
    if not user_data:
        flash("查無此帳號，請重新登入。", "error")
        session.pop('token', None) 
        session.pop('homeStationCode', None)
        session.pop('homeStationName', None)
        session.clear()
        return redirect(url_for('login'))
    
    if request.method == "POST":
        new_name = request.form.get("username", "").strip()
        if not new_name:
            flash("使用者名稱不能為空。", "error")
        else:
            update_user_profile(uid=uid, username=new_name)
            flash("使用者名稱已更新。", "success")
        return redirect(url_for('account_management', token=token))

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
@app.route('/update_home_station', methods=['POST'])
def update_home_station_route():
    token = request.form.get('token') or request.args.get('token')
    if not token:
        flash("缺少 token，更新失敗。", "error")
        return redirect(url_for('login'))
    try:
        uid = decrypt_token(token)
    except Exception:
        flash("無效的 token，更新失敗。", "error")
        return redirect(url_for('login'))

    new_station_name = request.form.get('homeStationName', '').strip()
    new_station_code = request.form.get('homeStationCode', '').strip()
    
    if not new_station_name:
        flash('更新失敗：車站名稱不能為空', 'error')
    else:
        update_user_profile(
            uid=uid, 
            home_station_name=new_station_name, 
            home_station_code=new_station_code
        )
        
        if session.get('token') == token:
            session['homeStationCode'] = new_station_code
            session['homeStationName'] = new_station_name
            save_log(f"Session home station updated for uid {uid}: {new_station_name} ({new_station_code})")

        flash('常用車站更新成功', 'success')
        
    return redirect(url_for('account_management', token=token))

@csrf.exempt
@app.route("/active/<county_en>")
def active(county_en):
    if county_en != 'all':
        county_zh = COUNTY_MAP.get(county_en)
        if not county_zh:
            return render_template("active.html",
                                   county=county_en,
                                   events=[],
                                   error="找不到對應的縣市"), 404
    else:
        county_zh = None

    events = []
    with open("datas/活動.csv", newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            if county_en!='all' and row["縣市名稱"]!=county_zh:
                continue

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

    if county_en=='all':
        ordered = list(COUNTY_MAP.values())
        order_map = {c:i for i,c in enumerate(ordered)}
        events.sort(key=lambda e: order_map.get(e["county"], float("inf")))
        display_county = "所有縣市"
    else:
        display_county = county_zh

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

    start = (page - 1) * per_page
    events_page = events[start : start + per_page]

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
@app.route('/api/recommendations')
def get_recommendations():
    """
    API: 取得推薦行程 (支援行政區優先排序與無限捲動)
    """
    category = request.args.get('category', 'all')
    target_county = request.args.get('county', '')  # 例如：臺北市
    target_district = request.args.get('district', '') # 例如：信義區
    keyword = request.args.get('keyword', '').strip().lower()
    page = int(request.args.get('page', 1))
    per_page = 20

    # 1. 整合資料來源
    sources = []
    if category in ['all', 'attraction']:
        sources.extend(list(ATTRACTIONS.values()))
    if category in ['all', 'food']:
        sources.extend(list(RESTAURANT.values()))
    if category in ['all', 'hotel']:
        sources.extend(list(HOTEL.values()))

    # 2. 篩選與評分 (Score)
    # Score 規則: 關鍵字匹配(100) > 同行政區(10) > 同縣市(5) > 其他(0)
    results = []
    
    for item in sources:
        # 欄位正規化
        name = item.get('Name', item.get('名稱', item.get('資料名稱', '')))
        addr = item.get('Add', item.get('地址', item.get('街道名稱', '')))
        desc = item.get('Description', item.get('說明', item.get('文字描述', '')))
        region = item.get('Region', item.get('行政區', item.get('鄉鎮市區', '')))
        town = item.get('Town', item.get('縣市', item.get('縣市名稱', '')))
        
        # 圖片處理 (不同資料源欄位不同)
        image = item.get('Picture1', item.get('照片連結1', ''))
        
        if not name: continue

        score = 0
        
        # 關鍵字篩選 (最高優先級)
        if keyword:
            content_str = f"{name} {addr} {desc}".lower()
            if keyword in content_str:
                score += 100
            else:
                continue # 有關鍵字但沒對上，直接跳過

        # 地區優先級排序
        # 判斷行政區 (例如: 信義區)
        if target_district and (target_district in addr or target_district == region):
            score += 10
        
        # 判斷縣市 (例如: 臺北市)
        if target_county and (target_county in addr or target_county == town):
            score += 5
            
        # 如果沒有關鍵字搜尋，且完全不同縣市，則過濾掉 (避免顯示屏東的資料給在台北的人)
        # 但如果是搜尋模式，則全台皆可搜
        if not keyword and target_county and score < 5:
            continue

        # 整理回傳格式
        tag_cat = "景點"
        if item in list(RESTAURANT.values()): tag_cat = "美食"
        elif item in list(HOTEL.values()): tag_cat = "住宿"

        results.append({
            "id": item.get('Id', item.get('唯一識別碼', uuid.uuid4().hex)),
            "title": name,
            "address": addr,
            "category": tag_cat,
            "image": image,
            "tel": item.get('Tel', item.get('電話', '')),
            "score": score
        })

    # 3. 排序：分數高者優先，若分數相同則隨機 (讓每次稍微不同)
    # Python 的 sort 是穩定的，先 shuffle 可以增加多樣性
    random.shuffle(results) 
    results.sort(key=lambda x: x['score'], reverse=True)

    # 4. 分頁處理
    total = len(results)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_data = results[start:end]

    return jsonify({
        "data": paginated_data,
        "has_next": end < total
    })

@csrf.exempt
@app.route("/search/<keyword>")
def search(keyword):
    try:
        per_page = int(request.args.get("per_page", 10))
    except ValueError:
        per_page = 10

    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    words = [w.strip().lower() for w in keyword.split() if w.strip()]

    if "test" in words:
        return redirect(url_for('test'))

    matched = []
    with open("datas/活動.csv", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            raw = row.get("文字描述", "").strip()
            m = re.match(r'(?i)^\s*<p>(.*)</p>\s*$', raw, flags=re.S)
            desc = m.group(1).strip() if m else raw
            desc = re.sub(r'<[^>]+>', '', desc)
            desc = html.unescape(desc).strip()

            addr_parts = [row.get("行政區","").strip(), row.get("街道名稱","").strip()]
            address = " ".join(p for p in addr_parts if p)
            if not address:
                address = row.get("資料提供單位","").strip()

            event = {
                "name":    row.get("資料名稱","").strip(),
                "desc":    desc,
                "time":    row.get("活動場次時間","").strip(),
                "address": address,
                "county":  row.get("縣市名稱","").strip(),
                "id":      row.get("唯一識別碼","").strip()
            }

            text = " ".join([event["name"], event["desc"], event["address"]]).lower()
            if all(w in text for w in words):
                matched.append(event)

    total = len(matched)
    total_pages = math.ceil(total / per_page) or 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    events_page = matched[start : start + per_page]

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
@app.route("/trip/<days>/<active>", defaults={'trip_id': None})
@app.route("/trip/<days>/<active>/<trip_id>")
def trip(days, active, trip_id):
    token = session.get('token') or ''
    
    if not token:
        session['next_url'] = request.url
        flash("請先登入以使用行程規劃功能。", "error")
        return redirect(url_for('login'))
    
    uid = decrypt_token(token)
    if not uid:
        flash("登入憑證無效，請重新登入。", "error")
        return redirect(url_for('login'))

    if 'homeStationCode' not in session:
        session['homeStationCode'] = '1000'
    if 'homeStationName' not in session:
        session['homeStationName'] = '臺北'

    if days not in ['one-day', 'two-day', 'three-day']:
        abort(404)

    if active not in EVENTS:
        abort(404, description="找不到指定的活動。")

    event_data = EVENTS[active]
    ai_response = None
    
    if trip_id:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT schedule FROM schedules WHERE trip_id = ? AND uid = ?", (trip_id, uid))
        result = cursor.fetchone()
        conn.close()
        if result:
            ai_response = json.loads(result[0])
            session['current_trip_id'] = trip_id
        else:
            flash("找不到指定的行程，或您沒有權限存取。", "error")
            return redirect(url_for('my_trips'))
    
    if request.args.get('regenerate') == 'true' or not ai_response:
        def package_data(event):
            return f"##{event['唯一識別碼']}:{event['資料名稱']}({event['縣市名稱']}{event['行政區(鄉鎮區)名稱']}) \n 景點資料：\n{find(ATTRACTIONS, event['縣市名稱'])}\n\n 餐廳資料：\n{find(RESTAURANT, event['縣市名稱'])}\n\n 住宿資料：\n{find(HOTEL, event['縣市名稱'])}\n\n 活動資料：\n名稱: {event['資料名稱']}\n地點: {event['行政區(鄉鎮區)名稱']} {event['街道名稱']}\n描述: {event['文字描述']}\n聯絡方式: {event['聯絡電話']}#{event['分機']}\n"
        
        packaged_data = package_data(event_data)
        days_map = {'one-day': 1, 'two-day': 2, 'three-day': 3}
        total_days = days_map[days]
        trip_data = f"# {total_days} Days\n{packaged_data}"
        
        raw_ai_response = ask_ai(trip_data)

        print("Raw AI Response:", raw_ai_response)

        def fix_json_format_with_markers(json_string):
            if json_string.startswith("```json"):
                json_string = json_string[7:]
            if json_string.endswith("```"):
                json_string = json_string[:-3]
            cleaned_string = json_string.replace("\\n", "").replace("    ", "").strip()
            try:
                return json.loads(cleaned_string)
            except json.JSONDecodeError:
                return None
        
        ai_response = fix_json_format_with_markers(raw_ai_response)
        if ai_response is None:
            flash("AI 行程規劃失敗或回傳格式錯誤，請重試。", "error")
            ai_response = {}

    if request.args.get('regenerate') == 'true':
        session.pop('current_trip_id', None)

    total_days = len(ai_response.keys())
    # 避免 ai_response 為空或結構錯誤
    try:
        raw_start = ai_response.get('1', [{}])[0].get('location', '臺北')
        raw_end = ai_response.get(str(total_days), [{}])[-1].get('location', '臺北')
    except:
        raw_start = '臺北'
        raw_end = '臺北'

    def clean_addr(addr: str) -> str:
        cleaned = addr.split('(')[0].strip()
        return cleaned.replace('\n', '').replace('\r', '').strip()

    start_location = clean_addr(raw_start)
    end_location = clean_addr(raw_end)

    print(ai_response)

    return render_template('trip.html', days=days, active=active, ai_response=ai_response, event=event_data, token=token, start_location=start_location, end_location=end_location, trip_id=trip_id)

# === 在 app.py 中新增或替換以下路由 ===

@app.route('/trip/send_line/<trip_id>', methods=['POST'])
@csrf.exempt
def send_trip_to_line(trip_id):
    token = session.get('token')
    if not token:
        return jsonify({"error": "請先登入"}), 401
        
    uid = decrypt_token(token)
    if not uid:
        return jsonify({"error": "無效的憑證"}), 401
        
    # 1. 檢查使用者是否有綁定 LINE
    user_data = get_user_data(uid) # 使用 send.py 的函式
    line_user_id = None
    if user_data and 'line_account' in user_data and user_data['line_account']:
        line_user_id = user_data['line_account'].get('userId')
        
    if not line_user_id:
        return jsonify({"error": "您尚未綁定 LINE 帳號，無法傳送行程。請先至「帳號管理」綁定 LINE。"}), 400

    # 2. 取得行程資料
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schedules WHERE trip_id = ? AND uid = ?", (trip_id, uid))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "找不到行程"}), 404
        
    schedule = json.loads(row['schedule'])
    trip_name = row['trip_name'] if row['trip_name'] else "我的行程"
    
    # 3. 格式化訊息內容
    msg_lines = [f"📅 {trip_name}", ""] # 標題
    
    for day, activities in schedule.items():
        msg_lines.append(f"【第 {day} 天】")
        for act in activities:
            time_str = act.get('time', '')
            title = act.get('title', '未命名活動')
            location = act.get('location', '').split(' ')[0] # 簡化地址
            
            # 組合單行行程: 09:00 台北101 (信義區...)
            if time_str:
                msg_lines.append(f"🕒 {time_str} | {title}")
            else:
                msg_lines.append(f"📍 {title}")
            
            if location:
                msg_lines.append(f"   ↳ {location}")
        msg_lines.append("") # 每天之間空一行
        
    msg_lines.append("---")
    msg_lines.append("此行程由 TripCrafter 規劃")
    
    final_text = "\n".join(msg_lines)
    
    # 4. 發送 LINE 訊息
    try:
        # 呼叫 send.py 的函式
        send_push_message(line_user_id, [{"type": "text", "text": final_text}])
        return jsonify({"message": "行程已成功傳送到您的 LINE！"}), 200
    except Exception as e:
        save_log(f"Send Line Error: {e}")
        return jsonify({"error": "發送失敗，請稍後再試"}), 500

@app.route('/my_trips')
@csrf.exempt
def my_trips():
    token = session.get('token')
    if not token:
        flash("請先登入。", "error")
        return redirect(url_for('login'))

    uid = decrypt_token(token)
    if not uid:
        flash("登入無效，請重新登入。", "error")
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT trip_id, schedule, created_at, days, active, trip_name FROM schedules WHERE uid = ? ORDER BY created_at DESC", (uid,))
    trips_data = cursor.fetchall()
    conn.close()

    trips = []
    for row in trips_data:
        if row['trip_name']:
            trip_name = row['trip_name']
        else:
            schedule_data = json.loads(row['schedule'])
            first_day_activities = schedule_data.get('1', [])
            trip_name = first_day_activities[0]['title'] if first_day_activities else "未命名行程"
        
        trips.append({
            'trip_id': row['trip_id'],
            'name': trip_name,
            'created_at': row['created_at'],
            'days': row['days'],
            'active': row['active']
        })

    return render_template('my_trips.html', trips=trips, token=token)

@app.route('/save_data/new', methods=['POST'])
def save_data_new():
    data = request.get_json()
    token = data.get('token')
    schedule = data.get('schedule')
    days = data.get('days')
    active = data.get('active')
    trip_name = data.get('trip_name')

    if not all([token, schedule, days, active]):
        return jsonify({"error": "缺少必要參數"}), 400

    uid = decrypt_token(token)
    if not uid:
        return jsonify({"error": "無效的 token"}), 401

    trip_id = str(uuid.uuid4())
    schedule_json = json.dumps(schedule, ensure_ascii=False)
    current_time = datetime.now().isoformat()

    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO schedules (uid, trip_id, schedule, created_at, days, active, trip_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, trip_id, schedule_json, current_time, days, active, trip_name)
        )
        conn.commit()
        conn.close()
        session['current_trip_id'] = trip_id
        return jsonify({"message": "行程已另存新檔！", "trip_id": trip_id}), 200
    except Exception as e:
        return jsonify({"error": f"伺服器錯誤: {str(e)}"}), 500

@app.route('/save_data/update', methods=['POST'])
def save_data_update():
    data = request.get_json()
    token = data.get('token')
    schedule = data.get('schedule')
    trip_id = data.get('trip_id')
    trip_name = data.get('trip_name')

    if not all([token, schedule, trip_id]):
        return jsonify({"error": "缺少必要參數"}), 400
    
    uid = decrypt_token(token)
    if not uid:
        return jsonify({"error": "無效的 token"}), 401
        
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM schedules WHERE trip_id = ? AND uid = ?", (trip_id, uid))
        exists = cursor.fetchone()

        if not exists:
            conn.close()
            return jsonify({"error": "未找到該行程ID！"}), 404
        
        schedule_json = json.dumps(schedule, ensure_ascii=False)
        # 同步更新名稱 (如果有的話)
        if trip_name:
            cursor.execute("UPDATE schedules SET schedule = ?, trip_name = ? WHERE trip_id = ?", (schedule_json, trip_name, trip_id))
        else:
            cursor.execute("UPDATE schedules SET schedule = ? WHERE trip_id = ?", (schedule_json, trip_id))
            
        conn.commit()
        conn.close()
        return jsonify({"message": "行程更新成功"}), 200
    except Exception as e:
        return jsonify({"error": f"伺服器錯誤: {str(e)}"}), 500
    
@app.route('/rename_trip', methods=['POST'])
@csrf.exempt
def rename_trip():
    data = request.get_json()
    token = data.get('token')
    trip_id = data.get('trip_id')
    new_name = data.get('new_name', '').strip()

    if not all([token, trip_id, new_name]):
        return jsonify({"error": "缺少必要參數"}), 400

    uid = decrypt_token(token)
    if not uid:
        return jsonify({"error": "無效的 token"}), 401

    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM schedules WHERE trip_id = ? AND uid = ?", (trip_id, uid))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "找不到行程或權限不足"}), 404
        
        cursor.execute("UPDATE schedules SET trip_name = ? WHERE trip_id = ?", (new_name, trip_id))
        conn.commit()
        conn.close()
        return jsonify({"message": "行程名稱已更新"}), 200
    except Exception as e:
        return jsonify({"error": f"伺服器錯誤: {str(e)}"}), 500

@app.route('/delete_trip', methods=['POST'])
@csrf.exempt
def delete_trip():
    data = request.get_json()
    token = data.get('token')
    trip_id = data.get('trip_id')

    if not all([token, trip_id]):
        return jsonify({"error": "缺少必要參數"}), 400

    uid = decrypt_token(token)
    if not uid:
        return jsonify({"error": "無效的 token"}), 401

    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM schedules WHERE trip_id = ? AND uid = ?", (trip_id, uid))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "找不到行程或權限不足"}), 404
            
        cursor.execute("DELETE FROM schedules WHERE trip_id = ? AND uid = ?", (trip_id, uid))
        conn.commit()
        conn.close()
        return jsonify({"message": "行程已刪除"}), 200
    except Exception as e:
        return jsonify({"error": f"伺服器錯誤: {str(e)}"}), 500
    
@csrf.exempt
@app.route("/memoir/create", methods=["GET", "POST"])
def create_memoir():
    token = session.get('token')
    if not token:
        flash("請先登入以製作回憶錄。", "error")
        return redirect(url_for('login'))
    
    uid = decrypt_token(token)
    if not uid:
        return redirect(url_for('login'))

    if request.method == "POST":
        user_text = request.form.get("user_text")
        layout_type = request.form.get("layout_type", "1")
        files = request.files.getlist("photos")
        
        saved_filenames = []
        if files:
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
                    file.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename))
                    saved_filenames.append(filename)
        
        image_path_json = json.dumps(saved_filenames)
        
        ai_article = ask_ai(user_text, trip_or_not="memoir")
        
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memoirs (uid, image_path, user_text, ai_content, created_at, layout_type) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, image_path_json, user_text, ai_article, datetime.now().isoformat(), layout_type)
        )
        conn.commit()
        memoir_id = cursor.lastrowid
        conn.close()
        
        return redirect(url_for('view_memoir', memoir_id=memoir_id))

    return render_template("create_memoir.html")

@csrf.exempt
@app.route("/memoir/edit/<int:memoir_id>", methods=["GET", "POST"])
def edit_memoir(memoir_id):
    token = session.get('token')
    if not token:
        flash("請先登入。", "error")
        return redirect(url_for('login'))
        
    uid = decrypt_token(token)
    if not uid:
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM memoirs WHERE id = ? AND uid = ?", (memoir_id, uid))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        flash("找不到該回憶錄或無權限編輯。", "error")
        return redirect(url_for('my_memoirs'))
    
    memoir = dict(row)

    if request.method == "POST":
        action = request.form.get("action")
        new_layout_type = request.form.get("layout_type")

        if action == "regenerate":
            new_user_text = request.form.get("user_text")
            ai_article = ask_ai(new_user_text, trip_or_not="memoir")
            
            cursor.execute(
                "UPDATE memoirs SET user_text = ?, ai_content = ?, layout_type = ? WHERE id = ?",
                (new_user_text, ai_article, new_layout_type, memoir_id)
            )
            flash("文章已根據新的關鍵字重新生成！", "success")

        elif action == "save_manual":
            manual_content = request.form.get("content_text")
            cursor.execute(
                "UPDATE memoirs SET ai_content = ?, layout_type = ? WHERE id = ?",
                (manual_content, new_layout_type, memoir_id)
            )
            flash("文章修改已儲存！", "success")

        conn.commit()
        conn.close()
        return redirect(url_for('view_memoir', memoir_id=memoir_id))

    conn.close()
    return render_template("edit_memoir.html", memoir=memoir)

@csrf.exempt
@app.route("/memoir/share/create/<int:memoir_id>", methods=["POST"])
def create_share_link(memoir_id):
    token = session.get('token')
    if not token:
        return jsonify({"error": "請先登入"}), 401
    
    uid = decrypt_token(token)
    if not uid:
        return jsonify({"error": "無效的憑證"}), 401

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT share_token FROM memoirs WHERE id = ? AND uid = ?", (memoir_id, uid))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"error": "找不到回憶錄或無權限"}), 404

    share_token = row[0]
    if not share_token:
        share_token = uuid.uuid4().hex
        cursor.execute("UPDATE memoirs SET share_token = ? WHERE id = ?", (share_token, memoir_id))
        conn.commit()
    
    conn.close()
    
    share_url = url_for('view_shared_memoir', token=share_token, _external=True)
    return jsonify({"share_url": share_url}), 200

@csrf.exempt
@app.route("/share/<token>")
def view_shared_memoir(token):
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM memoirs WHERE share_token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return render_template('404.html'), 404
    
    memoir = dict(row)
    try:
        images = json.loads(memoir['image_path'])
        if not isinstance(images, list):
            images = [memoir['image_path']] if memoir['image_path'] else []
    except:
        images = [memoir['image_path']] if memoir['image_path'] else []
        
    memoir['images_list'] = images
    if not memoir.get('layout_type'):
        memoir['layout_type'] = '1'

    return render_template("view_memoir.html", memoir=memoir, is_public=True)

@csrf.exempt
@app.route("/memoir/<int:memoir_id>")
def view_memoir(memoir_id):
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM memoirs WHERE id = ?", (memoir_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        abort(404)
    
    memoir = dict(row)
    
    try:
        images = json.loads(memoir['image_path'])
        if not isinstance(images, list):
            images = [memoir['image_path']] if memoir['image_path'] else []
    except:
        images = [memoir['image_path']] if memoir['image_path'] else []
        
    memoir['images_list'] = images
    
    if not memoir.get('layout_type'):
        memoir['layout_type'] = '1'
    
    is_owner = False
    token = session.get('token')
    if token:
        uid = decrypt_token(token)
        if uid and uid == memoir['uid']:
            is_owner = True
        
    return render_template("view_memoir.html", memoir=memoir, is_owner=is_owner)

@csrf.exempt
@app.route("/my_memoirs")
def my_memoirs():
    token = session.get('token')
    if not token: return redirect(url_for('login'))
    uid = decrypt_token(token)
    
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM memoirs WHERE uid = ? ORDER BY created_at DESC", (uid,))
    rows = cursor.fetchall()
    conn.close()
    
    memoirs = []
    for row in rows:
        m = dict(row)
        try:
            images = json.loads(m['image_path'])
            if isinstance(images, list) and len(images) > 0:
                m['cover_image'] = images[0]
            else:
                m['cover_image'] = m['image_path']
        except:
            m['cover_image'] = m['image_path']
            
        memoirs.append(m)
    
    return render_template("my_memoirs.html", memoirs=memoirs)

@csrf.exempt
@app.route("/memoir/delete/<int:memoir_id>", methods=["POST"])
def delete_memoir(memoir_id):
    token = session.get('token')
    if not token:
        flash("請先登入。", "error")
        return redirect(url_for('login'))
        
    uid = decrypt_token(token)
    if not uid:
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 先查詢要刪除的回憶錄資料，以獲取檔案名稱
    cursor.execute("SELECT * FROM memoirs WHERE id = ? AND uid = ?", (memoir_id, uid))
    memoir = cursor.fetchone()
    
    if not memoir:
        conn.close()
        flash("找不到該回憶錄或無權限刪除。", "error")
        return redirect(url_for('my_memoirs'))
    
    # === 新增：刪除實體圖片檔案 ===
    try:
        if memoir['image_path']:
            images = json.loads(memoir['image_path'])
            # 確保是列表
            if isinstance(images, list):
                for img_file in images:
                    file_path = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], img_file)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"Deleted image: {file_path}")
            # 相容舊格式 (如果是單一字串)
            elif isinstance(images, str):
                file_path = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], images)
                if os.path.exists(file_path):
                    os.remove(file_path)
    except Exception as e:
        save_log(f"Error deleting images for memoir {memoir_id}: {e}")

    # === 新增：刪除實體影片檔案 (如果有) ===
    try:
        if memoir['video_path']:
            video_file = memoir['video_path']
            video_full_path = os.path.join(app.root_path, app.config['VIDEO_FOLDER'], video_file)
            if os.path.exists(video_full_path):
                os.remove(video_full_path)
                print(f"Deleted video: {video_full_path}")
    except Exception as e:
        save_log(f"Error deleting video for memoir {memoir_id}: {e}")

    # 2. 最後再刪除資料庫紀錄
    cursor.execute("DELETE FROM memoirs WHERE id = ?", (memoir_id,))
    conn.commit()
    conn.close()
    
    flash("回憶錄與相關檔案已刪除。", "success")
    return redirect(url_for('my_memoirs'))

@csrf.exempt
@app.route("/memoir/video/create/<int:memoir_id>", methods=["POST"])
def create_memoir_video(memoir_id):
    token = session.get('token')
    if not token: return jsonify({"error": "請先登入"}), 401
    
    uid = decrypt_token(token)
    if not uid: return jsonify({"error": "無效憑證"}), 401

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM memoirs WHERE id = ? AND uid = ?", (memoir_id, uid))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "找不到回憶錄"}), 404
    
    memoir = dict(row)
    
    if memoir.get('video_path'):
        return jsonify({"video_url": f"/assets/videos/{memoir['video_path']}", "status": "completed"}), 200

    try:
        images_list = json.loads(memoir['image_path'])
    except:
        return jsonify({"error": "沒有圖片"}), 400

    if not images_list:
        return jsonify({"error": "圖片列表為空"}), 400

    thread = threading.Thread(target=generate_video_task, args=(
        memoir_id, 
        uid, 
        images_list, 
        memoir.get('user_text', ''), 
        memoir.get('created_at', '')[:10]
    ))
    thread.daemon = True 
    thread.start()

    return jsonify({
        "message": "影片生成請求已接收！系統將在背景製作，完成後會透過 LINE 通知您。",
        "status": "processing"
    }), 202
    
with app.app_context():
    links = []
    for rule in app.url_map.iter_rules():
        if "static" not in rule.endpoint:
            links.append(f"Endpoint: {rule.endpoint}, Methods: {','.join(rule.methods)}, URL: {rule}")
    for link in sorted(links):
        print(link)
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting gevent WSGIServer on 0.0.0.0:{port}...")
    print(f"Access the app at http://localhost:{port}/")
    
    http_server = WSGIServer(('0.0.0.0', port), app)
    
    http_server.serve_forever()