"""
Node 24: Weather
====================
天气查询 (OpenWeather API)

依赖库: requests
工具: get_weather, forecast
"""

import os
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Node 24 - Weather", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Configuration
# =============================================================================

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5"

# =============================================================================
# Tool Implementation
# =============================================================================

class WeatherTools:
    """
    Weather 工具实现 (OpenWeather API)
    """
    
    def __init__(self):
        self.api_key = OPENWEATHER_API_KEY
        self.base_url = OPENWEATHER_BASE_URL
        self.initialized = bool(self.api_key)
        
        if not self.initialized:
            print("Warning: OPENWEATHER_API_KEY not set")
        
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表"""
        return [
            {
                "name": "get_weather",
                "description": "获取指定城市的当前天气",
                "parameters": {
                    "city": "城市名称 (例如: Beijing, Shanghai, New York)",
                    "units": "温度单位 (metric=摄氏度, imperial=华氏度, 默认: metric)"
                }
            },
            {
                "name": "forecast",
                "description": "获取指定城市的未来天气预报 (5天，每3小时)",
                "parameters": {
                    "city": "城市名称 (例如: Beijing, Shanghai, New York)",
                    "units": "温度单位 (metric=摄氏度, imperial=华氏度, 默认: metric)",
                    "days": "预报天数 (1-5, 默认: 3)"
                }
            }
        ]
        
    async def call_tool(self, tool: str, params: Dict[str, Any]) -> Any:
        """调用工具"""
        if not self.initialized:
            raise RuntimeError("Weather API not initialized (missing API key)")
            
        handler = getattr(self, f"_tool_{tool}", None)
        if not handler:
            raise ValueError(f"Unknown tool: {tool}")
            
        return await handler(params)
        
    async def _tool_get_weather(self, params: dict) -> dict:
        """获取当前天气"""
        city = params.get("city", "")
        units = params.get("units", "metric")
        
        if not city:
            return {"error": "城市名称不能为空"}
        
        try:
            url = f"{self.base_url}/weather"
            response = requests.get(url, params={
                "q": city,
                "appid": self.api_key,
                "units": units,
                "lang": "zh_cn"
            }, timeout=10)
            
            response.raise_for_status()
            data = response.json()
            
            # 解析天气数据
            result = {
                "city": data["name"],
                "country": data["sys"]["country"],
                "temperature": data["main"]["temp"],
                "feels_like": data["main"]["feels_like"],
                "humidity": data["main"]["humidity"],
                "pressure": data["main"]["pressure"],
                "weather": data["weather"][0]["description"],
                "weather_icon": data["weather"][0]["icon"],
                "wind_speed": data["wind"]["speed"],
                "wind_deg": data["wind"].get("deg", 0),
                "clouds": data["clouds"]["all"],
                "visibility": data.get("visibility", 0) / 1000,  # 转换为公里
                "sunrise": datetime.fromtimestamp(data["sys"]["sunrise"]).strftime("%H:%M:%S"),
                "sunset": datetime.fromtimestamp(data["sys"]["sunset"]).strftime("%H:%M:%S"),
                "timestamp": datetime.fromtimestamp(data["dt"]).strftime("%Y-%m-%d %H:%M:%S"),
                "units": units
            }
            
            return result
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return {"error": f"未找到城市: {city}"}
            else:
                return {"error": f"API 错误: {e.response.status_code}"}
        except Exception as e:
            return {"error": f"获取天气失败: {str(e)}"}

    async def _tool_forecast(self, params: dict) -> dict:
        """获取天气预报"""
        city = params.get("city", "")
        units = params.get("units", "metric")
        days = min(int(params.get("days", 3)), 5)  # 最多5天
        
        if not city:
            return {"error": "城市名称不能为空"}
        
        try:
            url = f"{self.base_url}/forecast"
            response = requests.get(url, params={
                "q": city,
                "appid": self.api_key,
                "units": units,
                "lang": "zh_cn"
            }, timeout=10)
            
            response.raise_for_status()
            data = response.json()
            
            # 解析预报数据 (每3小时一个数据点，取每天的中午12点数据)
            forecasts = []
            seen_dates = set()
            
            for item in data["list"]:
                dt = datetime.fromtimestamp(item["dt"])
                date_str = dt.strftime("%Y-%m-%d")
                
                # 只取每天的中午12点数据
                if dt.hour == 12 and date_str not in seen_dates:
                    forecasts.append({
                        "date": date_str,
                        "day_of_week": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()],
                        "temperature": item["main"]["temp"],
                        "temp_min": item["main"]["temp_min"],
                        "temp_max": item["main"]["temp_max"],
                        "humidity": item["main"]["humidity"],
                        "weather": item["weather"][0]["description"],
                        "weather_icon": item["weather"][0]["icon"],
                        "wind_speed": item["wind"]["speed"],
                        "clouds": item["clouds"]["all"],
                        "pop": item.get("pop", 0) * 100  # 降水概率 (%)
                    })
                    seen_dates.add(date_str)
                    
                if len(forecasts) >= days:
                    break
            
            result = {
                "city": data["city"]["name"],
                "country": data["city"]["country"],
                "forecasts": forecasts,
                "units": units
            }
            
            return result
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return {"error": f"未找到城市: {city}"}
            else:
                return {"error": f"API 错误: {e.response.status_code}"}
        except Exception as e:
            return {"error": f"获取预报失败: {str(e)}"}


# =============================================================================
# Global Instance
# =============================================================================

tools = WeatherTools()

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy" if tools.initialized else "degraded",
        "node_id": "24",
        "name": "Weather",
        "initialized": tools.initialized,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/tools")
async def list_tools():
    """列出可用工具"""
    return {"tools": tools.get_tools()}

@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    try:
        result = await tools.call_tool(tool, params)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8024)
