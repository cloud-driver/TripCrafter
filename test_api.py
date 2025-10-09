import requests
import json

url = "http://127.0.0.1:10000/api/search-station"

payload = {
    "home_station_code": "6180",
    "home_station_name": "鳳林",
    "departure_datetime": "2025-10-16T08:44:00",
    "destination_address": "嘉義市忠孝路275號"
}

headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, data=json.dumps(payload), headers=headers)

if response.status_code == 200:
    print(json.dumps(response.json(), indent=4, ensure_ascii=False))
else:
    print(f"code: {response.status_code}")
    print(response.text)
