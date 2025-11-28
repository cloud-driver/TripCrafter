import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

url = "https://superiorapis-creator.cteam.com.tw/manager/feature/proxy/8e150c9487e6/pub_8e150e53827d"

headers = {
    "Content-Type": "application/json",
    "token": os.getenv('TRAIN_API_TOKEN') 
}

# === 診斷測試 ===
# 根據推測，這是最能「通過驗證」但會「觸發錯誤」的組合
# 1. 使用底線 (因為連字號會直接被擋 405)
# 2. 使用 'T' 的時間格式 (因為空格會被擋 405)
# 3. 補上 'train_type' (官方文件有寫，也許後端沒收到這欄位就報錯？)
payload = {
    "start_station": "臺北",
    "end_station": "花蓮",
    "datetime": "2025-12-01T12:00:00", 
    "train_type": 0  
}

print("--- 深度診斷測試 ---")
print(f"發送 payload: {json.dumps(payload, ensure_ascii=False)}")

try:
    response = requests.post(url, json=payload, headers=headers)
    print(f"HTTP 狀態碼: {response.status_code}")
    
    print("詳細回應內容 (請截圖或複製這段):")
    try:
        # 嘗試排版 JSON
        print(json.dumps(response.json(), indent=4, ensure_ascii=False))
    except:
        # 如果不是 JSON，直接印出原始文字
        print(response.text)

except Exception as e:
    print(f"發生錯誤: {e}")