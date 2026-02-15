"""
Node 24: Weather - 天气查询节点
=================================
提供天气查询、天气预报、空气质量功能
"""
import os
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 24 - Weather", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 配置
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5"

class WeatherManager:
    def __init__(self):
        self.api_key = OPENWEATHER_API_KEY
        self.base_url = OPENWEATHER_URL

    def get_current_weather(self, city: str, units: str = "metric", lang: str = "zh_cn") -> Dict:
        """获取当前天气"""
        if not self.api_key:
            # 返回模拟数据
            return {
                "city": city,
                "temperature": 22,
                "feels_like": 21,
                "humidity": 65,
                "pressure": 1013,
                "description": "多云",
                "wind_speed": 3.5,
                "visibility": 10000,
                "clouds": 40,
                "timestamp": datetime.now().isoformat(),
                "note": "Using mock data (API key not configured)"
            }

        params = {
            "q": city,
            "appid": self.api_key,
            "units": units,
            "lang": lang
        }

        response = requests.get(f"{self.base_url}/weather", params=params, timeout=10)

        if response.status_code != 200:
            raise RuntimeError(f"Weather API error: {response.text}")

        data = response.json()

        return {
            "city": data["name"],
            "country": data["sys"]["country"],
            "temperature": data["main"]["temp"],
            "feels_like": data["main"]["feels_like"],
            "temp_min": data["main"]["temp_min"],
            "temp_max": data["main"]["temp_max"],
            "humidity": data["main"]["humidity"],
            "pressure": data["main"]["pressure"],
            "description": data["weather"][0]["description"],
            "weather_main": data["weather"][0]["main"],
            "weather_icon": data["weather"][0]["icon"],
            "wind_speed": data["wind"]["speed"],
            "wind_deg": data["wind"].get("deg"),
            "visibility": data.get("visibility"),
            "clouds": data["clouds"]["all"],
            "sunrise": datetime.fromtimestamp(data["sys"]["sunrise"]).isoformat(),
            "sunset": datetime.fromtimestamp(data["sys"]["sunset"]).isoformat(),
            "timestamp": datetime.now().isoformat()
        }

    def get_forecast(self, city: str, units: str = "metric", lang: str = "zh_cn", days: int = 5) -> Dict:
        """获取天气预报"""
        if not self.api_key:
            return {
                "city": city,
                "forecast": [
                    {
                        "date": (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d"),
                        "temperature": 20 + i,
                        "description": "晴",
                        "humidity": 60
                    }
                    for i in range(days)
                ],
                "note": "Using mock data (API key not configured)"
            }

        params = {
            "q": city,
            "appid": self.api_key,
            "units": units,
            "lang": lang,
            "cnt": days * 8  # 每3小时一个数据点
        }

        response = requests.get(f"{self.base_url}/forecast", params=params, timeout=10)

        if response.status_code != 200:
            raise RuntimeError(f"Weather API error: {response.text}")

        data = response.json()

        forecast_list = []
        for item in data.get("list", []):
            forecast_list.append({
                "datetime": item["dt_txt"],
                "temperature": item["main"]["temp"],
                "feels_like": item["main"]["feels_like"],
                "humidity": item["main"]["humidity"],
                "description": item["weather"][0]["description"],
                "weather_icon": item["weather"][0]["icon"],
                "wind_speed": item["wind"]["speed"],
                "probability": item.get("pop", 0)  # 降水概率
            })

        return {
            "city": data["city"]["name"],
            "country": data["city"]["country"],
            "forecast": forecast_list
        }

    def get_air_quality(self, lat: float, lon: float) -> Dict:
        """获取空气质量"""
        if not self.api_key:
            return {
                "aqi": 2,
                "quality": "良",
                "components": {
                    "co": 220.5,
                    "no": 0.5,
                    "no2": 12.3,
                    "o3": 68.2,
                    "pm2_5": 8.4,
                    "pm10": 15.2
                },
                "note": "Using mock data (API key not configured)"
            }

        params = {
            "lat": lat,
            "lon": lon,
            "appid": self.api_key
        }

        response = requests.get("http://api.openweathermap.org/data/2.5/air_pollution", params=params, timeout=10)

        if response.status_code != 200:
            raise RuntimeError(f"Air quality API error: {response.text}")

        data = response.json()
        aqi = data["list"][0]["main"]["aqi"]
        components = data["list"][0]["components"]

        aqi_labels = {1: "优", 2: "良", 3: "轻度污染", 4: "中度污染", 5: "重度污染"}

        return {
            "aqi": aqi,
            "quality": aqi_labels.get(aqi, "未知"),
            "components": components
        }

    def get_weather_by_coords(self, lat: float, lon: float, units: str = "metric", lang: str = "zh_cn") -> Dict:
        """根据坐标获取天气"""
        if not self.api_key:
            return {"error": "API key not configured"}

        params = {
            "lat": lat,
            "lon": lon,
            "appid": self.api_key,
            "units": units,
            "lang": lang
        }

        response = requests.get(f"{self.base_url}/weather", params=params, timeout=10)

        if response.status_code != 200:
            raise RuntimeError(f"Weather API error: {response.text}")

        data = response.json()

        return {
            "city": data["name"],
            "temperature": data["main"]["temp"],
            "description": data["weather"][0]["description"],
            "humidity": data["main"]["humidity"],
            "wind_speed": data["wind"]["speed"],
            "timestamp": datetime.now().isoformat()
        }

# 全局天气管理器
weather_manager = WeatherManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "24",
        "name": "Weather",
        "api_configured": bool(OPENWEATHER_API_KEY),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/current")
async def get_current_weather(city: str, units: str = "metric", lang: str = "zh_cn"):
    """获取当前天气"""
    try:
        return weather_manager.get_current_weather(city, units, lang)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/forecast")
async def get_forecast(city: str, units: str = "metric", lang: str = "zh_cn", days: int = 5):
    """获取天气预报"""
    try:
        return weather_manager.get_forecast(city, units, lang, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/air-quality")
async def get_air_quality(lat: float, lon: float):
    """获取空气质量"""
    try:
        return weather_manager.get_air_quality(lat, lon)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/coords")
async def get_weather_by_coords(lat: float, lon: float, units: str = "metric", lang: str = "zh_cn"):
    """根据坐标获取天气"""
    try:
        return weather_manager.get_weather_by_coords(lat, lon, units, lang)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8024)
