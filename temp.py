# -*- coding: utf-8 -*-
import json
import requests
from geopy.distance import geodesic
from datetime import datetime, timedelta

home_station_code = "7130"  # 蘇澳新
departure_datetime_str = "2025-10-16T08:44:00" # 出發時間

# API Keys
API_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJjZXJ0IjoiMmIyYzU5YjE3MWMyY2RiMDExZDk4ZjYxN2NkYWEyZTgyNDk1YWY4YyIsImlhdCI6MTc1OTU5Njc0NX0.iyxRW1MLztK2VV2xGgLYdKzV7pE9pHYvIrz6MfdejYw"
GOOGLE_API_KEY = "AIzaSyBupx_s-VMi7f5AgVZ8_vJ5xIMWgh0XHHI"

city_code_map = {
    "臺北市": "A", "台北市": "A", "臺中市": "B", "台中市": "B", "基隆市": "C", 
    "臺南市": "D", "高雄市": "E", "新北市": "F", "宜蘭縣": "G", "桃園市": "H", 
    "嘉義市": "I", "新竹縣": "J", "苗栗縣": "K", "南投縣": "M", "彰化縣": "N", 
    "新竹市": "O", "雲林縣": "P", "嘉義縣": "Q", "屏東縣": "T", "花蓮縣": "U", 
    "臺東縣": "V", "台東縣": "V", 
}

big_station_map = {
    "基隆": "0900", "七堵": "0930", "南港": "0980", "松山": "0990", "臺北": "1000", 
    "板橋": "1020", "樹林": "1040", "桃園": "1080", "中壢": "1100", "新竹": "1210", 
    "竹南": "1250", "苗栗": "3160", "豐原": "3230", "臺中": "3300", "彰化": "3360", 
    "員林": "3390", "斗六": "3470", "嘉義": "4080", "新營": "4120", "臺南": "4220", 
    "新左營": "4340", "高雄": "4400", "屏東": "5000", "潮州": "5050", "宜蘭": "7190", 
    "蘇澳新": "7130", "花蓮": "7000", "玉里": "6110", "臺東": "6000"
}
big_station_name_map = {v: k for k, v in big_station_map.items()}

ai_response = '''
{
    "1": [
        {
            "title": "奮起湖老街",
            "time": "上午",
            "location": "嘉義縣竹崎鄉中和村奮起湖",
            "tags": "景點, 老街, 懷舊"
        }
    ]
}
'''

station_coords_cache = {}
station_name_cache = {}

def get_coordinates(address):
    """將地址轉換為經緯度座標，並加入快取"""
    if address in station_coords_cache:
        return station_coords_cache[address]
    
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={GOOGLE_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            station_coords_cache[address] = location
            return location
        return None
    except requests.exceptions.RequestException:
        return None

def get_station_name(station_code):
    """根據車站代碼獲取車站名稱，並加入快取"""
    if station_code in station_name_cache:
        return station_name_cache[station_code]
    
    if station_code in big_station_name_map:
        station_name_cache[station_code] = big_station_name_map[station_code]
        return big_station_name_map[station_code]

    print(f"警告: 無法從快取或大站列表中找到代碼 {station_code} 的名稱。")
    return f"車站{station_code}"

def find_closest_station(target_coords, stations):
    """從車站列表中找出距離目標座標最近的車站"""
    closest_station_info = None
    min_distance = float('inf')
    for station_code, station_name in stations:
        station_coords = get_coordinates(f"{station_name}車站")
        if station_coords:
            distance = geodesic((target_coords['lat'], target_coords['lng']), (station_coords['lat'], station_coords['lng'])).km
            if distance < min_distance:
                min_distance = distance
                closest_station_info = (station_code, station_name, distance)
    return closest_station_info

def find_closest_big_station(target_station_code, big_station_coords):
    """從所有大站中，找到離目標車站最近的一個"""
    target_station_name = get_station_name(target_station_code)
    target_coords = get_coordinates(f"{target_station_name}車站")
    if not target_coords:
        return None

    closest_hub_code = None
    min_distance = float('inf')
    for hub_code, hub_coords in big_station_coords.items():
        if hub_code == target_station_code:
            continue
        distance = geodesic((target_coords['lat'], target_coords['lng']), (hub_coords['lat'], hub_coords['lng'])).km
        if distance < min_distance:
            min_distance = distance
            closest_hub_code = hub_code
    return closest_hub_code

def get_train_schedule(start_station, end_station, departure_time):
    """查詢火車時刻表"""
    headers = {"Content-Type": "application/json", "token": API_TOKEN}
    payload = {"start_station": start_station, "end_station": end_station, "datetime": departure_time}
    try:
        response = requests.post(
            "https://superiorapis-creator.cteam.com.tw/manager/feature/proxy/8e150c9487e6/pub_8e150e53827d",
            json=payload, headers=headers, timeout=30
        )
        response.raise_for_status()
        result = response.json()
        return result if isinstance(result, list) and len(result) > 0 else []
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        print(f"查詢時刻表時發生錯誤 ({start_station} -> {end_station}): {e}")
        return []
    
def get_station_list_by_city(destination_city):
    """根據城市名稱獲取該城市的所有車站列表"""
    city_prefix = city_code_map.get(destination_city)
    if not city_prefix:
        return []

    headers = {"Content-Type": "application/json", "token": API_TOKEN}
    payload = {"city_code": [city_prefix]}
    try:
        response = requests.post(
            "https://superiorapis-creator.cteam.com.tw/manager/feature/proxy/8e150c9487e6/pub_8e15166c84d3",
            params={}, json=payload, headers=headers, timeout=30
        )
        response.raise_for_status()
        stations = response.json()
        print(f"查詢到城市 {destination_city} 的車站列表: {stations}")
        return [(num, name) for num, name in stations[city_prefix].items()]
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        print(f"查詢城市 {destination_city} 車站列表時發生錯誤: {e}")
        return []

def main():
    """主執行函式"""
    all_found_routes = []
    departure_datetime = datetime.fromisoformat(departure_datetime_str)

    for code, name in big_station_name_map.items():
        station_name_cache[code] = name
    station_name_cache[home_station_code] = "蘇澳新"

    try:
        travel_data = json.loads(ai_response)
        destination_address = travel_data["1"][0]["location"]
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"解析行程 JSON 時出錯: {e}"); return

    destination_coords = get_coordinates(destination_address)
    if not destination_coords: print("無法獲取目的地座標。"); return

    destination_city = destination_address[0:3]
    station_list = get_station_list_by_city(destination_city)
    if not station_list: print(f"找不到城市 '{destination_city}' 的車站列表。"); return
    
    closest_station_info = find_closest_station(destination_coords, station_list)
    if not closest_station_info: print("找不到離目的地最近的火車站。"); return
    
    dest_station_code, dest_station_name, _ = closest_station_info
    station_name_cache[dest_station_code] = dest_station_name
    print(f"出發站: {get_station_name(home_station_code)} ({home_station_code})")
    print(f"目的地: {dest_station_name} ({dest_station_code})\n")

    # 策略一：搜尋直達車
    print("--- 1. 正在搜尋直達路線 ---")
    direct_trains = get_train_schedule(home_station_code, dest_station_code, departure_datetime_str)
    if direct_trains:
        print("✅ 找到直達車次！")
        train = direct_trains[0]
        arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{train['arrival_time']}:00")
        if arrival_dt < departure_datetime: arrival_dt += timedelta(days=1)
        duration = arrival_dt - departure_datetime
        all_found_routes.append({
            "type": "直達", "duration": duration,
            "legs_info": [f"直達: {get_station_name(home_station_code)} -> {dest_station_name}"],
            "details": [train]
        })
    else:
        print("⚠️ 未找到直達車次。")
    print("--- 直達搜尋完畢 ---\n")

    # 策略二：搜尋單次轉乘 (經由關鍵樞紐站)
    print("--- 2. 正在搜尋單次轉乘路線 ---")
    
    # *** 修改點：縮小轉乘站範圍，只搜尋最可能的北部轉乘樞紐 ***
    key_hubs = {
        "七堵": "0930", "南港": "0980", "松山": "0990", "臺北": "1000", "板橋": "1020"
    }

    for hub_name, hub_code in key_hubs.items():
        if hub_code in [home_station_code, dest_station_code]: continue
        
        # 接下來的邏輯完全一樣，但因為查詢次數減少，會快很多且不會報錯
        leg1_trains = get_train_schedule(home_station_code, hub_code, departure_datetime_str)
        if leg1_trains:
            leg1 = leg1_trains[0]
            leg1_arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['arrival_time']}:00")
            if leg1_arrival_dt < datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['departure_time']}:00"):
                leg1_arrival_dt += timedelta(days=1)
            
            leg2_trains = get_train_schedule(hub_code, dest_station_code, leg1_arrival_dt.isoformat())
            if leg2_trains:
                leg2 = leg2_trains[0]
                leg2_arrival_dt = datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['arrival_time']}:00")
                if leg2_arrival_dt < datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['departure_time']}:00"):
                    leg2_arrival_dt += timedelta(days=1)
                
                duration = leg2_arrival_dt - departure_datetime
                print(f"✅ 找到經由【{hub_name}】的單次轉乘路線！")
                all_found_routes.append({
                    "type": f"轉乘一次 ({hub_name})", "duration": duration,
                    "legs_info": [f"第一段: {get_station_name(home_station_code)} -> {hub_name}", f"第二段: {hub_name} -> {dest_station_name}"],
                    "details": [leg1, leg2]
                })
    print("--- 單次轉乘搜尋完畢 ---\n")

    # 策略三：搜尋兩次轉乘
    print("--- 3. 正在搜尋兩次轉乘路線 ---")
    big_station_coords = {code: get_coordinates(f"{name}車站") for name, code in big_station_map.items()}
    big_station_coords = {k: v for k, v in big_station_coords.items() if v}
    start_hub = find_closest_big_station(home_station_code, big_station_coords)
    dest_hub = find_closest_big_station(dest_station_code, big_station_coords)

    if start_hub and dest_hub and start_hub != dest_hub:
        start_hub_name = get_station_name(start_hub)
        dest_hub_name = get_station_name(dest_hub)
        print(f"規劃路線: {get_station_name(home_station_code)} -> {start_hub_name} -> {dest_hub_name} -> {dest_station_name}")

        leg1_trains = get_train_schedule(home_station_code, start_hub, departure_datetime_str)
        if leg1_trains:
            leg1 = leg1_trains[0]
            leg1_arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['arrival_time']}:00")
            if leg1_arrival_dt < datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['departure_time']}:00"):
                leg1_arrival_dt += timedelta(days=1)
            
            leg2_trains = get_train_schedule(start_hub, dest_hub, leg1_arrival_dt.isoformat())
            if leg2_trains:
                leg2 = leg2_trains[0]
                leg2_arrival_dt = datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['arrival_time']}:00")
                if leg2_arrival_dt < datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['departure_time']}:00"):
                    leg2_arrival_dt += timedelta(days=1)

                leg3_trains = get_train_schedule(dest_hub, dest_station_code, leg2_arrival_dt.isoformat())
                if leg3_trains:
                    leg3 = leg3_trains[0]
                    leg3_arrival_dt = datetime.fromisoformat(f"{leg2_arrival_dt.date()}T{leg3['arrival_time']}:00")
                    if leg3_arrival_dt < datetime.fromisoformat(f"{leg2_arrival_dt.date()}T{leg3['departure_time']}:00"):
                        leg3_arrival_dt += timedelta(days=1)

                    duration = leg3_arrival_dt - departure_datetime
                    print("✅ 找到兩次轉乘的完整路線！")
                    all_found_routes.append({
                        "type": f"轉乘兩次 ({start_hub_name} -> {dest_hub_name})", "duration": duration,
                        "legs_info": [f"第一段: {get_station_name(home_station_code)} -> {start_hub_name}", f"第二段: {start_hub_name} -> {dest_hub_name}", f"第三段: {dest_hub_name} -> {dest_station_name}"],
                        "details": [leg1, leg2, leg3]
                    })
    print("--- 兩次轉乘搜尋完畢 ---\n")

    # --- 4. 比較所有路線並找出最佳解 ---
    print("="*40)
    if not all_found_routes:
        print("❌ 搜尋結束，未找到任何可行的火車路線。")
        return

    best_route = sorted(all_found_routes, key=lambda x: x['duration'])[0]

    print("🎉 找到最快路線！ 🎉")
    print(f"路線類型: {best_route['type']}")
    print(f"總耗時: {best_route['duration']}")
    print("\n--- 詳細行程 ---")
    
    for i, leg_detail in enumerate(best_route['details']):
        print(f"\n{best_route['legs_info'][i]}")
        print(json.dumps(leg_detail, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
