import requests
import json
import time
start_time = time.time()

url = "http://127.0.0.1:10000/api/closest-station"

payload = {
    "address": "嘉義市忠孝路275號"
}

headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, data=json.dumps(payload), headers=headers)
end_time = time.time()
if response.status_code == 200:
    print(json.dumps(response.json(), indent=4, ensure_ascii=False))
    print(f"總執行時間: {end_time - start_time:.2f} 秒")
else:
    print(f"code: {response.status_code}")
    print(response.text)
