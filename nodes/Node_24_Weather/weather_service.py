"""
UFO Galaxy - Node_24 Weather Service
=====================================

真实的天气服务实现，支持多个天气 API

支持的 API:
1. OpenWeatherMap (免费)
2. WeatherAPI (免费)
3. 和风天气 (中国)
"""

import os
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WeatherProvider(str, Enum):
    """天气 API 提供商"""
    OPENWEATHERMAP = "openweathermap"
    WEATHERAPI = "weatherapi"
    QWEATHER = "qweather"  # 和风天气


@dataclass
class WeatherData:
    """天气数据"""
    location: str = ""
    country: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    
    # 当前天气
    temperature: float = 0.0  # 摄氏度
    feels_like: float = 0.0
    humidity: int = 0  # 百分比
    pressure: int = 0  # hPa
    wind_speed: float = 0.0  # m/s
    wind_direction: int = 0  # 度
    visibility: int = 0  # 米
    clouds: int = 0  # 百分比
    
    # 天气描述
    condition: str = ""
    description: str = ""
    icon: str = ""
    
    # 时间
    timestamp: datetime = field(default_factory=datetime.now)
    sunrise: Optional[datetime] = None
    sunset: Optional[datetime] = None
    
    # 其他
    uv_index: float = 0.0
    aqi: int = 0  # 空气质量指数


@dataclass
class ForecastData:
    """天气预报数据"""
    date: datetime
    temp_min: float
    temp_max: float
    condition: str
    description: str
    humidity: int
    wind_speed: float
    precipitation_probability: int = 0


class BaseWeatherClient:
    """天气客户端基类"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    async def get_current_weather(self, location: str) -> WeatherData:
        """获取当前天气"""
        raise NotImplementedError
    
    async def get_forecast(self, location: str, days: int = 5) -> List[ForecastData]:
        """获取天气预报"""
        raise NotImplementedError


class OpenWeatherMapClient(BaseWeatherClient):
    """OpenWeatherMap 客户端"""
    
    BASE_URL = "https://api.openweathermap.org/data/2.5"
    
    async def get_current_weather(self, location: str) -> WeatherData:
        """获取当前天气"""
        async with httpx.AsyncClient(timeout=30) as client:
            # 尝试按城市名查询
            response = await client.get(
                f"{self.BASE_URL}/weather",
                params={
                    "q": location,
                    "appid": self.api_key,
                    "units": "metric",
                    "lang": "zh_cn"
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code} - {response.text}")
            
            data = response.json()
            
            return WeatherData(
                location=data.get("name", location),
                country=data.get("sys", {}).get("country", ""),
                latitude=data.get("coord", {}).get("lat", 0),
                longitude=data.get("coord", {}).get("lon", 0),
                temperature=data.get("main", {}).get("temp", 0),
                feels_like=data.get("main", {}).get("feels_like", 0),
                humidity=data.get("main", {}).get("humidity", 0),
                pressure=data.get("main", {}).get("pressure", 0),
                wind_speed=data.get("wind", {}).get("speed", 0),
                wind_direction=data.get("wind", {}).get("deg", 0),
                visibility=data.get("visibility", 0),
                clouds=data.get("clouds", {}).get("all", 0),
                condition=data.get("weather", [{}])[0].get("main", ""),
                description=data.get("weather", [{}])[0].get("description", ""),
                icon=data.get("weather", [{}])[0].get("icon", ""),
                timestamp=datetime.fromtimestamp(data.get("dt", 0)),
                sunrise=datetime.fromtimestamp(data.get("sys", {}).get("sunrise", 0)) if data.get("sys", {}).get("sunrise") else None,
                sunset=datetime.fromtimestamp(data.get("sys", {}).get("sunset", 0)) if data.get("sys", {}).get("sunset") else None
            )
    
    async def get_forecast(self, location: str, days: int = 5) -> List[ForecastData]:
        """获取天气预报"""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.BASE_URL}/forecast",
                params={
                    "q": location,
                    "appid": self.api_key,
                    "units": "metric",
                    "lang": "zh_cn",
                    "cnt": days * 8  # 每3小时一个数据点
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            
            data = response.json()
            forecasts = []
            
            # 按天聚合
            daily_data = {}
            for item in data.get("list", []):
                date = datetime.fromtimestamp(item["dt"]).date()
                if date not in daily_data:
                    daily_data[date] = {
                        "temps": [],
                        "conditions": [],
                        "descriptions": [],
                        "humidity": [],
                        "wind_speed": []
                    }
                
                daily_data[date]["temps"].append(item["main"]["temp"])
                daily_data[date]["conditions"].append(item["weather"][0]["main"])
                daily_data[date]["descriptions"].append(item["weather"][0]["description"])
                daily_data[date]["humidity"].append(item["main"]["humidity"])
                daily_data[date]["wind_speed"].append(item["wind"]["speed"])
            
            for date, values in sorted(daily_data.items())[:days]:
                forecasts.append(ForecastData(
                    date=datetime.combine(date, datetime.min.time()),
                    temp_min=min(values["temps"]),
                    temp_max=max(values["temps"]),
                    condition=max(set(values["conditions"]), key=values["conditions"].count),
                    description=max(set(values["descriptions"]), key=values["descriptions"].count),
                    humidity=int(sum(values["humidity"]) / len(values["humidity"])),
                    wind_speed=sum(values["wind_speed"]) / len(values["wind_speed"])
                ))
            
            return forecasts


class WeatherAPIClient(BaseWeatherClient):
    """WeatherAPI 客户端"""
    
    BASE_URL = "https://api.weatherapi.com/v1"
    
    async def get_current_weather(self, location: str) -> WeatherData:
        """获取当前天气"""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.BASE_URL}/current.json",
                params={
                    "key": self.api_key,
                    "q": location,
                    "aqi": "yes"
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            
            data = response.json()
            loc = data.get("location", {})
            current = data.get("current", {})
            
            return WeatherData(
                location=loc.get("name", location),
                country=loc.get("country", ""),
                latitude=loc.get("lat", 0),
                longitude=loc.get("lon", 0),
                temperature=current.get("temp_c", 0),
                feels_like=current.get("feelslike_c", 0),
                humidity=current.get("humidity", 0),
                pressure=current.get("pressure_mb", 0),
                wind_speed=current.get("wind_kph", 0) / 3.6,  # 转换为 m/s
                wind_direction=current.get("wind_degree", 0),
                visibility=int(current.get("vis_km", 0) * 1000),
                clouds=current.get("cloud", 0),
                condition=current.get("condition", {}).get("text", ""),
                description=current.get("condition", {}).get("text", ""),
                icon=current.get("condition", {}).get("icon", ""),
                uv_index=current.get("uv", 0),
                aqi=current.get("air_quality", {}).get("us-epa-index", 0)
            )
    
    async def get_forecast(self, location: str, days: int = 5) -> List[ForecastData]:
        """获取天气预报"""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.BASE_URL}/forecast.json",
                params={
                    "key": self.api_key,
                    "q": location,
                    "days": days
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            
            data = response.json()
            forecasts = []
            
            for day in data.get("forecast", {}).get("forecastday", []):
                day_data = day.get("day", {})
                forecasts.append(ForecastData(
                    date=datetime.strptime(day["date"], "%Y-%m-%d"),
                    temp_min=day_data.get("mintemp_c", 0),
                    temp_max=day_data.get("maxtemp_c", 0),
                    condition=day_data.get("condition", {}).get("text", ""),
                    description=day_data.get("condition", {}).get("text", ""),
                    humidity=day_data.get("avghumidity", 0),
                    wind_speed=day_data.get("maxwind_kph", 0) / 3.6,
                    precipitation_probability=day_data.get("daily_chance_of_rain", 0)
                ))
            
            return forecasts


class QWeatherClient(BaseWeatherClient):
    """和风天气客户端"""
    
    BASE_URL = "https://devapi.qweather.com/v7"
    
    async def _get_location_id(self, location: str) -> str:
        """获取位置 ID"""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://geoapi.qweather.com/v2/city/lookup",
                params={
                    "key": self.api_key,
                    "location": location
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            
            data = response.json()
            if data.get("code") != "200" or not data.get("location"):
                raise Exception(f"Location not found: {location}")
            
            return data["location"][0]["id"]
    
    async def get_current_weather(self, location: str) -> WeatherData:
        """获取当前天气"""
        location_id = await self._get_location_id(location)
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.BASE_URL}/weather/now",
                params={
                    "key": self.api_key,
                    "location": location_id
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            
            data = response.json()
            now = data.get("now", {})
            
            return WeatherData(
                location=location,
                temperature=float(now.get("temp", 0)),
                feels_like=float(now.get("feelsLike", 0)),
                humidity=int(now.get("humidity", 0)),
                pressure=int(now.get("pressure", 0)),
                wind_speed=float(now.get("windSpeed", 0)) / 3.6,
                wind_direction=int(now.get("wind360", 0)),
                visibility=int(now.get("vis", 0)) * 1000,
                clouds=int(now.get("cloud", 0)),
                condition=now.get("text", ""),
                description=now.get("text", "")
            )
    
    async def get_forecast(self, location: str, days: int = 5) -> List[ForecastData]:
        """获取天气预报"""
        location_id = await self._get_location_id(location)
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.BASE_URL}/weather/{days}d",
                params={
                    "key": self.api_key,
                    "location": location_id
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            
            data = response.json()
            forecasts = []
            
            for day in data.get("daily", []):
                forecasts.append(ForecastData(
                    date=datetime.strptime(day["fxDate"], "%Y-%m-%d"),
                    temp_min=float(day.get("tempMin", 0)),
                    temp_max=float(day.get("tempMax", 0)),
                    condition=day.get("textDay", ""),
                    description=day.get("textDay", ""),
                    humidity=int(day.get("humidity", 0)),
                    wind_speed=float(day.get("windSpeedDay", 0)) / 3.6
                ))
            
            return forecasts


class WeatherService:
    """天气服务 - 统一接口"""
    
    def __init__(
        self,
        provider: WeatherProvider = WeatherProvider.OPENWEATHERMAP,
        api_key: Optional[str] = None
    ):
        self.provider = provider
        self.api_key = api_key or self._get_api_key_from_env()
        self.client = self._create_client()
    
    def _get_api_key_from_env(self) -> str:
        """从环境变量获取 API Key"""
        if self.provider == WeatherProvider.OPENWEATHERMAP:
            return os.getenv("OPENWEATHERMAP_API_KEY", "")
        elif self.provider == WeatherProvider.WEATHERAPI:
            return os.getenv("WEATHERAPI_KEY", "")
        elif self.provider == WeatherProvider.QWEATHER:
            return os.getenv("QWEATHER_API_KEY", "")
        return ""
    
    def _create_client(self) -> BaseWeatherClient:
        """创建客户端"""
        if self.provider == WeatherProvider.OPENWEATHERMAP:
            return OpenWeatherMapClient(self.api_key)
        elif self.provider == WeatherProvider.WEATHERAPI:
            return WeatherAPIClient(self.api_key)
        elif self.provider == WeatherProvider.QWEATHER:
            return QWeatherClient(self.api_key)
        else:
            raise ValueError(f"Unknown provider: {self.provider}")
    
    async def get_weather(self, location: str) -> WeatherData:
        """获取当前天气"""
        return await self.client.get_current_weather(location)
    
    async def get_forecast(self, location: str, days: int = 5) -> List[ForecastData]:
        """获取天气预报"""
        return await self.client.get_forecast(location, days)
    
    def format_weather(self, weather: WeatherData) -> str:
        """格式化天气信息"""
        return f"""
📍 {weather.location}, {weather.country}
🌡️ 温度: {weather.temperature}°C (体感 {weather.feels_like}°C)
☁️ 天气: {weather.description}
💧 湿度: {weather.humidity}%
💨 风速: {weather.wind_speed:.1f} m/s
👁️ 能见度: {weather.visibility / 1000:.1f} km
"""
    
    def format_forecast(self, forecasts: List[ForecastData]) -> str:
        """格式化天气预报"""
        lines = ["📅 天气预报:"]
        for f in forecasts:
            lines.append(f"  {f.date.strftime('%m-%d')}: {f.condition}, {f.temp_min:.0f}~{f.temp_max:.0f}°C")
        return "\n".join(lines)


# 测试代码
async def test_weather_service():
    """测试天气服务"""
    print("=== 测试天气服务 ===")
    
    # 检查 API Key
    api_key = os.getenv("OPENWEATHERMAP_API_KEY", "")
    
    if api_key:
        print(f"Using OpenWeatherMap API")
        service = WeatherService(
            provider=WeatherProvider.OPENWEATHERMAP,
            api_key=api_key
        )
        
        try:
            weather = await service.get_weather("Beijing")
            print(service.format_weather(weather))
            
            forecasts = await service.get_forecast("Beijing", 3)
            print(service.format_forecast(forecasts))
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("No API key found. Set OPENWEATHERMAP_API_KEY environment variable.")
        print("Creating mock weather data for testing...")
        
        # 模拟数据
        weather = WeatherData(
            location="Beijing",
            country="CN",
            temperature=15.5,
            feels_like=14.0,
            humidity=65,
            pressure=1013,
            wind_speed=3.5,
            visibility=10000,
            condition="Cloudy",
            description="多云"
        )
        
        service = WeatherService()
        print(service.format_weather(weather))
    
    print("\n✅ 天气服务测试完成")


if __name__ == "__main__":
    asyncio.run(test_weather_service())
