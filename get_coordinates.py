import requests
import json

def get_coordinates(address):
    """
    將地址轉換為經緯度座標。

    Args:
        address: 您想要查詢的地址字串。

    Returns:
        一個包含 'lat' (緯度) 和 'lng' (經度) 的字典，
        如果找不到地址則返回 None。
    """
    # 從您的 HTML 檔案中提取的 API 金鑰
    api_key = "AIzaSyBupx_s-VMi7f5AgVZ8_vJ5xIMWgh0XHHI"
    
    # Google Geocoding API 的 URL
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}"
    
    try:
        # 發送 GET 請求
        response = requests.get(url)
        # 將回傳的 JSON 字串轉換成 Python 字典
        data = response.json()
        
        # 檢查 API 回應的狀態
        if data['status'] == 'OK':
            # 提取經緯度資訊
            location = data['results'][0]['geometry']['location']
            return location
        else:
            print(f"無法找到地址，錯誤訊息：{data['status']}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"請求發生錯誤：{e}")
        return None

# --- 主程式 ---
if __name__ == "__main__":
    # 讓使用者輸入地址
    input_address = input("請輸入您想查詢的地址：")
    
    # 呼叫函式取得座標
    coordinates = get_coordinates(input_address)
    
    # 輸出結果
    if coordinates:
        print("---")
        print(f"查詢地址：{input_address}")
        print(f"緯度 (lat): {coordinates['lat']}")
        print(f"經度 (lng): {coordinates['lng']}")
