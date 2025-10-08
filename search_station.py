# -*- coding: utf-8 -*-
import json
import requests
from geopy.distance import geodesic
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from send import save_log

if os.path.exists(".env"): load_dotenv()

# API Keys
API_TOKEN = os.getenv('TRAIN_API_TOKEN')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

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

station_regions = {
    'EAST': ["7190", "7130", "7000", "6110", "6000"],
    'WEST_NORTH': ["0900", "0930", "0980", "0990", "1000", "1020", "1040", "1080", "1100"],
    'WEST_CENTRAL': ["1210", "1250", "3160", "3230", "3300", "3360", "3390"],
    'WEST_SOUTH': ["3470", "4080", "4120", "4220", "4340", "4400"],
    'PINGTUNG': ["5000", "5050"]
}

junction_hubs = {
    frozenset(['EAST', 'WEST_NORTH']): ["0930", "0980", "0990", "1000", "1020"],
    frozenset(['EAST', 'WEST_CENTRAL']): ["0930", "0980", "0990", "1000", "1020"],
    frozenset(['EAST', 'WEST_SOUTH']): ["5000", "5050"],
    frozenset(['EAST', 'PINGTUNG']): ["5000", "5050"],
}

station_coords_cache = {}
station_name_cache = {}

def get_coordinates(address):
    if address in station_coords_cache:
        return station_coords_cache[address]
    
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={GOOGLE_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status() # 建議加上這行，方便檢查 HTTP 錯誤
        data = response.json()
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            station_coords_cache[address] = location
            return location
        else:
            save_log(f"Geocoding API 狀態錯誤 for '{address}': {data['status']}") # 加上錯誤訊息
        return None
    except requests.exceptions.RequestException as e:
        save_log(f"Geocoding API 請求失敗 for '{address}': {e}") # 加上錯誤訊息
        return None

def get_station_name(station_code):
    if station_code in station_name_cache: return station_name_cache[station_code]
    if station_code in big_station_name_map:
        station_name_cache[station_code] = big_station_name_map[station_code]
        return big_station_name_map[station_code]
    return f"車站{station_code}"

def find_closest_station(target_coords, stations):
    closest_station_info, min_distance = None, float('inf')
    for station_code, station_name in stations:
        station_coords = get_coordinates(f"{station_name}車站")
        if station_coords:
            distance = geodesic((target_coords['lat'], target_coords['lng']), (station_coords['lat'], station_coords['lng'])).km
            if distance < min_distance:
                min_distance, closest_station_info = distance, (station_code, station_name, distance)
    return closest_station_info

def find_closest_big_station(target_station_code, big_station_coords):
    target_station_name = get_station_name(target_station_code)
    target_coords = get_coordinates(f"{target_station_name}車站")
    if not target_coords: return None
    closest_hub_code, min_distance = None, float('inf')
    for hub_code, hub_coords in big_station_coords.items():
        if hub_code == target_station_code: continue
        distance = geodesic((target_coords['lat'], target_coords['lng']), (hub_coords['lat'], hub_coords['lng'])).km
        if distance < min_distance:
            min_distance, closest_hub_code = distance, hub_code
    return closest_hub_code

def get_train_schedule(start_station, end_station, departure_time):
    headers, payload = {"Content-Type": "application/json", "token": API_TOKEN}, {"start_station": start_station, "end_station": end_station, "datetime": departure_time}
    try:
        response = requests.post("https://superiorapis-creator.cteam.com.tw/manager/feature/proxy/8e150c9487e6/pub_8e150e53827d", json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result if isinstance(result, list) and len(result) > 0 else []
    except Exception as e:
        save_log(f"查詢時刻表時發生錯誤 ({start_station} -> {end_station}): {e}")
        return []

def get_station_list_by_city(destination_city):
    city_prefix = city_code_map.get(destination_city)
    if not city_prefix: return []
    headers, payload = {"Content-Type": "application/json", "token": API_TOKEN}, {"city_code": [city_prefix]}
    try:
        response = requests.post("https://superiorapis-creator.cteam.com.tw/manager/feature/proxy/8e150c9487e6/pub_8e15166c84d3", json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        stations = response.json()
        return [(num, name) for num, name in stations[city_prefix].items()]
    except Exception as e:
        save_log(f"查詢城市 {destination_city} 車站列表時發生錯誤: {e}")
        return []

# *** 新增：輔助函式，用來獲取車站所屬區域 ***
def get_station_region(station_code, big_station_coords):
    """
    獲取車站所屬的區域。
    如果車站本身就是大站，直接返回其區域。
    如果不是，則找到離它最近的大站，並返回該大站的區域。
    """
    # 1. 先嘗試直接從 station_regions 查找 (如果該站本身就是定義好的大站)
    for region, codes in station_regions.items():
        if station_code in codes:
            return region

    # 2. 如果找不到，表示這是一個小站。我們需要找到離它最近的大站。
    #    我們使用現有的 find_closest_big_station 函式來完成這件事。
    closest_big_station_code = find_closest_big_station(station_code, big_station_coords)

    if closest_big_station_code:
        # 3. 找到最近的大站後，再次查找這個大站所屬的區域。
        for region, codes in station_regions.items():
            if closest_big_station_code in codes:
                return region
    
    # 4. 如果連最近的大站都找不到，才返回 None
    return None

def search_station(home_station_code, home_station_name, departure_datetime_str, destination_address):
    """ 
    # 主搜尋程式邏輯 
    ## 範例參數:
        home_station_code = "0980"
        home_station_name = "南港"
        departure_datetime_str = "2025-10-16T08:44:00"
        destination_address = "臺北市信義區松仁路100號"
    ## 以上參數可直接帶入函式呼叫
    """
    all_found_routes = []
    departure_datetime = datetime.fromisoformat(departure_datetime_str)

    for code, name in big_station_name_map.items(): station_name_cache[code] = name
    station_name_cache[home_station_code] = home_station_name

    # --- START: 全新的大站座標初始化邏輯 ---
    
    BIG_STATION_CACHE_FILE = "json/big_station_coords.json"
    big_station_coords = {}

    # 步驟 1: 嘗試從快取檔案載入座標
    if os.path.exists(BIG_STATION_CACHE_FILE):
        try:
            with open(BIG_STATION_CACHE_FILE, 'r', encoding='utf-8') as f:
                big_station_coords = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            save_log(f"⚠️ 從快取檔案讀取失敗: {e}。將重新從 API 獲取資料。")
            big_station_coords = {} # 如果檔案損毀或讀取失敗，就清空字典以便重新抓取

    # 步驟 2: 如果快取不存在或載入失敗，則從 API 獲取並儲存
    if not big_station_coords:
        save_log("--- 快取不存在或已失效，正在從 API 初始化大站座標資料 ---")
        
        # 原本的 API 呼叫邏輯
        big_station_coords_raw = {code: get_coordinates(f"{name}車站") for name, code in big_station_map.items()}
        # 過濾掉查詢失敗的項目
        big_station_coords = {k: v for k, v in big_station_coords_raw.items() if v}
        
        save_log(f"--- 正在將新座標儲存至 {BIG_STATION_CACHE_FILE} ---")
        try:
            with open(BIG_STATION_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(big_station_coords, f, ensure_ascii=False, indent=4)
            save_log("--- 座標儲存完成 ---\n")
        except IOError as e:
            save_log(f"❌ 儲存座標快取失敗: {e}\n")

    # --- END: 全新的大站座標初始化邏輯 ---

    destination_coords = get_coordinates(destination_address)
    if not destination_coords: save_log("無法獲取目的地座標。"); return

    destination_city = destination_address[0:3]
    station_list = get_station_list_by_city(destination_city)
    if not station_list: save_log(f"找不到城市 '{destination_city}' 的車站列表。"); return
    
    closest_station_info = find_closest_station(destination_coords, station_list)
    if not closest_station_info: save_log("找不到離目的地最近的火車站。"); return
    
    dest_station_code, dest_station_name, _ = closest_station_info
    station_name_cache[dest_station_code] = dest_station_name
    # 策略一：搜尋直達車
    save_log("--- 1. 正在搜尋直達路線 ---")
    direct_trains = get_train_schedule(home_station_code, dest_station_code, departure_datetime_str)
    if direct_trains:
        train = direct_trains[0]
        arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{train['arrival_time']}:00")
        if arrival_dt < departure_datetime: arrival_dt += timedelta(days=1)
        duration = arrival_dt - departure_datetime
        all_found_routes.append({
            "type": "直達", "duration": duration,
            "legs_info": [f"直達: {get_station_name(home_station_code)} -> {dest_station_name}"],
            "details": [train]
        })

    # 策略二：搜尋單次轉乘 (經由關鍵樞紐站)
    key_hubs = {}
    start_region = get_station_region(home_station_code, big_station_coords)
    dest_region = get_station_region(dest_station_code, big_station_coords)
    if start_region and dest_region and start_region != dest_region:
        junction_key = frozenset([start_region, dest_region])
        if junction_key in junction_hubs:
            hub_codes = junction_hubs[junction_key]
            key_hubs = {get_station_name(code): code for code in hub_codes}

    for hub_name, hub_code in key_hubs.items():
        if hub_code in [home_station_code, dest_station_code]: continue
        leg1_trains = get_train_schedule(home_station_code, hub_code, departure_datetime_str)
        if leg1_trains:
            leg1 = leg1_trains[0]
            leg1_arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['arrival_time']}:00")
            if leg1_arrival_dt < datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['departure_time']}:00"): leg1_arrival_dt += timedelta(days=1)
            
            leg2_trains = get_train_schedule(hub_code, dest_station_code, leg1_arrival_dt.isoformat())
            if leg2_trains:
                leg2 = leg2_trains[0]
                leg2_arrival_dt = datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['arrival_time']}:00")
                if leg2_arrival_dt < datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['departure_time']}:00"): leg2_arrival_dt += timedelta(days=1)
                
                duration = leg2_arrival_dt - departure_datetime
                all_found_routes.append({
                    "type": f"轉乘一次 ({hub_name})", "duration": duration,
                    "legs_info": [f"第一段: {get_station_name(home_station_code)} -> {hub_name}", f"第二段: {hub_name} -> {dest_station_name}"],
                    "details": [leg1, leg2]
                })

    
    # 策略三：搜尋兩次轉乘
    start_hub = find_closest_big_station(home_station_code, big_station_coords)
    dest_hub = find_closest_big_station(dest_station_code, big_station_coords)

    if start_hub and dest_hub and start_hub != dest_hub:
        start_hub_name = get_station_name(start_hub)
        dest_hub_name = get_station_name(dest_hub)
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
                    all_found_routes.append({
                        "type": f"轉乘兩次 ({start_hub_name} -> {dest_hub_name})", "duration": duration,
                        "legs_info": [f"第一段: {get_station_name(home_station_code)} -> {start_hub_name}", f"第二段: {start_hub_name} -> {dest_hub_name}", f"第三段: {dest_hub_name} -> {dest_station_name}"],
                        "details": [leg1, leg2, leg3]
                    })

    # --- 4. 比較所有路線並找出最佳解 ---
    if not all_found_routes:
        return None

    best_route = sorted(all_found_routes, key=lambda x: x['duration'])[0]

    best_route['duration'] = int(best_route['duration'].total_seconds())

    best_route['from'] = {"code": home_station_code, "name": home_station_name}
    best_route['to'] = {"code": dest_station_code, "name": dest_station_name}

    return best_route
