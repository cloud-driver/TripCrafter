from flask import Blueprint, jsonify, request
from send import save_log
from search_station import search_station, get_coordinates, initialize_all_stations_data, find_closest_station
import json
import traceback

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route("/search-station", methods=["POST", "OPTIONS"])
def api_search_station():
    """
    提供火車路線查詢的 API
    """

    save_log("DEBUG: api_search_station function was CALLED!") 

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "請提供有效的 JSON 資料"}), 400
        
        log_params = {
            "home_station_code": data.get("home_station_code"),
            "home_station_name": data.get("home_station_name"),
            "departure_datetime": data.get("departure_datetime"),
            "destination_address": data.get("destination_address")
        }
        save_log(f"API_PARAMS_RECEIVED: {json.dumps(log_params, ensure_ascii=False)}")
        

        home_station_code = data.get("home_station_code")
        home_station_name = data.get("home_station_name")
        departure_datetime = data.get("departure_datetime")
        destination_address = data.get("destination_address")

        if departure_datetime and len(departure_datetime) == 16:
            departure_datetime += ":00"
            save_log(f"Formatted departure_datetime to: {departure_datetime}")

        if not all([home_station_code, home_station_name, departure_datetime, destination_address]):
            return jsonify({"error": "缺少必要的參數"}), 400

        result = search_station(
            home_station_code=home_station_code,
            home_station_name=home_station_name,
            departure_datetime_str=departure_datetime,
            destination_address=destination_address,
        )

        if not result:
            return jsonify({"error": "找不到適合的火車路線"}), 404

        return jsonify(result), 200

    except Exception as e:
        save_log(f"API search-station error: {str(e)}")
        save_log(traceback.format_exc())
        return jsonify({"error": f"伺服器錯誤: {str(e)}"}), 500
    
@api_bp.route("/closest-station", methods=["POST", "OPTIONS"])
def api_closest_station():
    """
    用地址找離該地址最近的火車站
    """
    if request.method == "OPTIONS":
        return "", 204

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "請提供有效的 JSON 資料"}), 400

        address = data.get("address")
        if not address:
            save_log("API_PARAMS_MISSING: address is missing")
            return jsonify({"error": "缺少必要的參數 'address'"}), 400
        
        log_params = {"address": address}
        save_log(f"API_PARAMS_RECEIVED: {json.dumps(log_params, ensure_ascii=False)}")

        coordinates = get_coordinates(address)
        if not coordinates:
            return jsonify({"error": "無法取得地址的經緯度，請檢查地址是否正確或 Google API Key 是否有效"}), 400
        
        all_stations_data = initialize_all_stations_data()
        if not all_stations_data:
            return jsonify({"error": "無法初始化車站資料"}), 500
        
        closest_station_info = find_closest_station(coordinates, all_stations_data)

        if not closest_station_info:
            return jsonify({"error": "找不到最近的車站"}), 404

        station_code, station_name, distance = closest_station_info
        result = {
            "closest_station": {
                "code": station_code,
                "name": station_name,
                "distance_km": round(distance, 2)
            }
        }

        return jsonify(result), 200

    except Exception as e:
        # 在伺服器紀錄詳細的錯誤，但回傳給使用者的訊息可以簡潔一些
        save_log(f"API /closest-station Unhandled Error: {str(e)}")
        save_log(traceback.format_exc())
        return jsonify({"error": "伺服器內部發生未預期的錯誤"}), 500