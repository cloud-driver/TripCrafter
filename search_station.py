# -*- coding: utf-8 -*-
import json
import requests
import asyncio
import aiohttp
from geopy.distance import geodesic
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from send import save_log

# --- 環境設定 ---
if os.path.exists(".env"): load_dotenv()

# API Keys
API_TOKEN = os.getenv('TRAIN_API_TOKEN')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- 常數與設定 ---
if not os.path.exists("json"):
    os.makedirs("json")
    
ALL_STATIONS_CACHE_FILE = "json/all_stations_data.json"

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

def get_coordinates(address):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={GOOGLE_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data['status'] == 'OK': return data['results'][0]['geometry']['location']
        else: save_log(f"Geocoding API 狀態錯誤 for '{address}': {data['status']}")
    except requests.exceptions.RequestException as e:
        save_log(f"Geocoding API 請求失敗 for '{address}': {e}")
    return None

def initialize_all_stations_data():
    if os.path.exists(ALL_STATIONS_CACHE_FILE):
        try:
            with open(ALL_STATIONS_CACHE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            save_log(f"⚠️ 從快取檔案 {ALL_STATIONS_CACHE_FILE} 讀取失敗: {e}。將重新從 API 獲取。")
    save_log("--- 快取檔案不存在，正在從 API 初始化所有車站的資料 (此過程只會執行一次) ---")
    all_stations = {}
    headers = {"Content-Type": "application/json", "token": API_TOKEN}
    for city_name, city_code in city_code_map.items():
        payload = {"city_code": [city_code]}
        try:
            response = requests.post("https://superiorapis-creator.cteam.com.tw/manager/feature/proxy/8e150c9487e6/pub_8e15166c84d3", json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            stations_in_city = response.json().get(city_code, {})
            for code, name in stations_in_city.items():
                if code not in all_stations: all_stations[code] = {"name": name, "city": city_name}
        except Exception as e: save_log(f"查詢城市 {city_name} 車站列表時發生錯誤: {e}")
    save_log(f"--- 正在獲取 {len(all_stations)} 個車站的座標 ---")
    for code, data in all_stations.items():
        coords = get_coordinates(f"{data['name']}車站")
        data['coords'] = coords if coords else None
    try:
        with open(ALL_STATIONS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_stations, f, ensure_ascii=False, indent=4)
        save_log(f"--- 所有車站資料已成功快取至 {ALL_STATIONS_CACHE_FILE} ---\n")
    except IOError as e: save_log(f"❌ 儲存車站快取失敗: {e}\n")
    return all_stations

async def get_train_schedule_async(session, start_station, end_station, departure_time):
    headers = {"Content-Type": "application/json", "token": API_TOKEN}
    payload = {"start_station": start_station, "end_station": end_station, "datetime": departure_time}
    url = "https://superiorapis-creator.cteam.com.tw/manager/feature/proxy/8e150c9487e6/pub_8e150e53827d"
    try:
        async with session.post(url, json=payload, headers=headers, timeout=30) as response:
            response.raise_for_status()
            result = await response.json()
            return result if isinstance(result, list) and len(result) > 0 else []
    except Exception as e:
        save_log(f"查詢時刻表時發生錯誤 ({start_station} -> {end_station}): {e}")
        return []

def find_closest_station(target_coords, stations_data):
    closest_station_info, min_distance = None, float('inf')
    for station_code, station_info in stations_data.items():
        station_coords = station_info.get('coords')
        if station_coords:
            distance = geodesic((target_coords['lat'], target_coords['lng']),(station_coords['lat'], station_coords['lng'])).km
            if distance < min_distance:
                min_distance = distance
                closest_station_info = (station_code, station_info['name'], distance)
    return closest_station_info

def get_station_region(station_code, all_stations_data):
    for region, codes in station_regions.items():
        if station_code in codes: return region
    station_info = all_stations_data.get(station_code)
    if not station_info or not station_info.get('coords'): return None
    station_coords = (station_info['coords']['lat'], station_info['coords']['lng'])
    closest_hub_code, min_distance = None, float('inf')
    for hub_code in big_station_map.values():
        hub_info = all_stations_data.get(hub_code)
        if hub_info and hub_info.get('coords'):
            hub_coords = (hub_info['coords']['lat'], hub_info['coords']['lng'])
            distance = geodesic(station_coords, hub_coords).km
            if distance < min_distance: min_distance, closest_hub_code = distance, hub_code
    if closest_hub_code:
        for region, codes in station_regions.items():
            if closest_hub_code in codes: return region
    return None

def find_closest_big_station(station_code, all_stations_data):
    station_info = all_stations_data.get(station_code)
    if not station_info or not station_info.get('coords'): return None
    target_coords = (station_info['coords']['lat'], station_info['coords']['lng'])
    closest_hub_code, min_distance = None, float('inf')
    for hub_code in big_station_map.values():
        if hub_code == station_code: continue
        hub_info = all_stations_data.get(hub_code)
        if hub_info and hub_info.get('coords'):
            hub_coords = (hub_info['coords']['lat'], hub_info['coords']['lng'])
            distance = geodesic(target_coords, hub_coords).km
            if distance < min_distance: min_distance, closest_hub_code = distance, hub_code
    return closest_hub_code

async def search_station_async(home_station_code, home_station_name, departure_datetime_str, destination_address, all_stations_data):
    departure_datetime = datetime.fromisoformat(departure_datetime_str)
    destination_coords = get_coordinates(destination_address)
    if not destination_coords:
        save_log("無法獲取目的地座標。"); return None

    destination_city = destination_address[0:3]
    city_stations = {code: data for code, data in all_stations_data.items() if data['city'] in destination_city}
    closest_station_info = find_closest_station(destination_coords, city_stations if city_stations else all_stations_data)
    if not closest_station_info:
        save_log("找不到離目的地最近的火車站。"); return None
    
    dest_station_code, dest_station_name, _ = closest_station_info
    all_found_routes = []
    
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
    
        tasks = []
        tasks.append(get_train_schedule_async(session, home_station_code, dest_station_code, departure_datetime_str))
        
        start_region = get_station_region(home_station_code, all_stations_data)
        dest_region = get_station_region(dest_station_code, all_stations_data)
        key_hubs = {}
        if start_region and dest_region and start_region != dest_region:
            junction_key = frozenset([start_region, dest_region])
            if junction_key in junction_hubs:
                hub_codes = junction_hubs[junction_key]
                key_hubs = {code: all_stations_data.get(code, {}).get("name", f"車站{code}") for code in hub_codes}

        transfer_leg1_tasks = {}
        for hub_code in key_hubs.keys():
            if hub_code in [home_station_code, dest_station_code]: continue
            task = get_train_schedule_async(session, home_station_code, hub_code, departure_datetime_str)
            transfer_leg1_tasks[hub_code] = task
        
        save_log("--- 正在平行查詢 直達 & 轉乘第一段 路線 ---")
        direct_trains_result = await tasks[0]
        transfer_leg1_results = await asyncio.gather(*transfer_leg1_tasks.values())

        if direct_trains_result:
            train = direct_trains_result[0]
            arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{train['arrival_time']}:00")
            if arrival_dt < departure_datetime: arrival_dt += timedelta(days=1)
            all_found_routes.append({
                "type": "直達", "duration": arrival_dt - departure_datetime,
                "legs_info": [f"直達: {home_station_name} -> {dest_station_name}"], "details": [train]
            })

        transfer_leg2_tasks = {}
        hub_codes_with_results = list(transfer_leg1_tasks.keys())
        for i, leg1_trains in enumerate(transfer_leg1_results):
            if leg1_trains:
                hub_code = hub_codes_with_results[i]
                leg1 = leg1_trains[0]
                leg1_arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['arrival_time']}:00")
                if leg1_arrival_dt < datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['departure_time']}:00"):
                    leg1_arrival_dt += timedelta(days=1)
                task = get_train_schedule_async(session, hub_code, dest_station_code, leg1_arrival_dt.isoformat())
                transfer_leg2_tasks[task] = {"leg1_details": leg1, "hub_code": hub_code}

        if transfer_leg2_tasks:
            save_log("--- 正在平行查詢 轉乘第二段 路線 ---")
            transfer_leg2_task_list = list(transfer_leg2_tasks.keys())
            transfer_leg2_results = await asyncio.gather(*transfer_leg2_task_list)
            for i, leg2_trains in enumerate(transfer_leg2_results):
                if leg2_trains:
                    original_task = transfer_leg2_task_list[i]
                    leg1_info = transfer_leg2_tasks[original_task]
                    leg1, hub_code, hub_name = leg1_info["leg1_details"], leg1_info["hub_code"], key_hubs[leg1_info["hub_code"]]
                    leg2 = leg2_trains[0]
                    leg1_arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['arrival_time']}:00")
                    if leg1_arrival_dt < datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['departure_time']}:00"): leg1_arrival_dt += timedelta(days=1)
                    leg2_arrival_dt = datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['arrival_time']}:00")
                    if leg2_arrival_dt < datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['departure_time']}:00"): leg2_arrival_dt += timedelta(days=1)
                    all_found_routes.append({
                        "type": f"轉乘一次 ({hub_name})", "duration": leg2_arrival_dt - departure_datetime,
                        "legs_info": [f"第一段: {home_station_name} -> {hub_name}", f"第二段: {hub_name} -> {dest_station_name}"],
                        "details": [leg1, leg2]
                    })
        
        if not all_found_routes:
            save_log("--- 直達與單次轉乘無結果，嘗試備用方案：搜尋兩次轉乘 ---")
            start_hub = find_closest_big_station(home_station_code, all_stations_data)
            dest_hub = find_closest_big_station(dest_station_code, all_stations_data)
            if start_hub and dest_hub and start_hub != dest_hub:
                leg1_trains = await get_train_schedule_async(session, home_station_code, start_hub, departure_datetime_str)
                if leg1_trains:
                    leg1 = leg1_trains[0]
                    leg1_arrival_dt = datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['arrival_time']}:00")
                    if leg1_arrival_dt < datetime.fromisoformat(f"{departure_datetime.date()}T{leg1['departure_time']}:00"): leg1_arrival_dt += timedelta(days=1)
                    leg2_trains = await get_train_schedule_async(session, start_hub, dest_hub, leg1_arrival_dt.isoformat())
                    if leg2_trains:
                        leg2 = leg2_trains[0]
                        leg2_arrival_dt = datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['arrival_time']}:00")
                        if leg2_arrival_dt < datetime.fromisoformat(f"{leg1_arrival_dt.date()}T{leg2['departure_time']}:00"): leg2_arrival_dt += timedelta(days=1)
                        leg3_trains = await get_train_schedule_async(session, dest_hub, dest_station_code, leg2_arrival_dt.isoformat())
                        if leg3_trains:
                            leg3 = leg3_trains[0]
                            leg3_arrival_dt = datetime.fromisoformat(f"{leg2_arrival_dt.date()}T{leg3['arrival_time']}:00")
                            if leg3_arrival_dt < datetime.fromisoformat(f"{leg2_arrival_dt.date()}T{leg3['departure_time']}:00"): leg3_arrival_dt += timedelta(days=1)
                            start_hub_name = all_stations_data.get(start_hub, {}).get("name", f"車站{start_hub}")
                            dest_hub_name = all_stations_data.get(dest_hub, {}).get("name", f"車站{dest_hub}")
                            all_found_routes.append({
                                "type": f"轉乘兩次 ({start_hub_name} -> {dest_hub_name})", "duration": leg3_arrival_dt - departure_datetime,
                                "legs_info": [f"第一段: {home_station_name} -> {start_hub_name}", f"第二段: {start_hub_name} -> {dest_hub_name}", f"第三段: {dest_hub_name} -> {dest_station_name}"],
                                "details": [leg1, leg2, leg3]
                            })
    
    if not all_found_routes: return None
    best_route = sorted(all_found_routes, key=lambda x: x['duration'])[0]
    best_route['duration'] = int(best_route['duration'].total_seconds())
    best_route['from'] = {"code": home_station_code, "name": home_station_name}
    best_route['to'] = {"code": dest_station_code, "name": dest_station_name}
    return best_route

def search_station(home_station_code, home_station_name, departure_datetime_str, destination_address):
    all_stations_data = initialize_all_stations_data()
    result = asyncio.run(search_station_async(
        home_station_code, home_station_name, departure_datetime_str, destination_address, all_stations_data
    ))
    return result

if __name__ == '__main__':
    home_station_code = "0980"
    home_station_name = "南港"
    departure_datetime_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    destination_address = "花蓮縣花蓮市達固湖彎大路23號" # 臺南車站

    print(f"從 {home_station_name} 到 {destination_address}")
    print(f"出發時間: {departure_datetime_str}")
    print("-" * 30)
    
    import time
    start_time = time.time()
    best_route = search_station(home_station_code, home_station_name, departure_datetime_str, destination_address)
    end_time = time.time()
    
    if best_route:
        print(json.dumps(best_route, indent=4, ensure_ascii=False))
    else:
        print("找不到合適的路線。")
        
    print("-" * 30)
    print(f"總執行時間: {end_time - start_time:.2f} 秒")