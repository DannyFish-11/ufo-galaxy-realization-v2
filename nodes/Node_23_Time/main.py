"""
Node 23: Time - 时间服务节点
==============================
提供时间查询、时区转换、定时器功能
"""
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pytz

app = FastAPI(title="Node 23 - Time", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 常用时区
COMMON_TIMEZONES = [
    "UTC", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul",
    "Europe/London", "Europe/Paris", "Europe/Berlin",
    "America/New_York", "America/Los_Angeles", "America/Chicago"
]

class TimezoneConvertRequest(BaseModel):
    datetime_str: str
    from_tz: str
    to_tz: str
    format: str = "%Y-%m-%d %H:%M:%S"

class TimerRequest(BaseModel):
    duration_seconds: int
    name: str = "timer"

class TimeManager:
    def __init__(self):
        self.timers: Dict[str, Dict] = {}

    def get_current_time(self, timezone: str = "UTC") -> Dict:
        """获取当前时间"""
        try:
            tz = pytz.timezone(timezone)
            now = datetime.now(tz)
            return {
                "datetime": now.isoformat(),
                "timestamp": now.timestamp(),
                "timezone": timezone,
                "formatted": now.strftime("%Y-%m-%d %H:%M:%S %Z")
            }
        except pytz.UnknownTimeZoneError:
            raise ValueError(f"Unknown timezone: {timezone}")

    def convert_timezone(self, datetime_str: str, from_tz: str, to_tz: str, 
                        format: str = "%Y-%m-%d %H:%M:%S") -> Dict:
        """转换时区"""
        try:
            from_timezone = pytz.timezone(from_tz)
            to_timezone = pytz.timezone(to_tz)

            # 解析时间
            dt = datetime.strptime(datetime_str, format)
            dt = from_timezone.localize(dt)

            # 转换时区
            converted = dt.astimezone(to_timezone)

            return {
                "original": datetime_str,
                "from_tz": from_tz,
                "to_tz": to_tz,
                "converted": converted.strftime(format),
                "converted_iso": converted.isoformat()
            }
        except pytz.UnknownTimeZoneError as e:
            raise ValueError(f"Unknown timezone: {e}")

    def list_timezones(self) -> List[str]:
        """列出所有时区"""
        return pytz.all_timezones

    def get_common_timezones(self) -> List[str]:
        """获取常用时区"""
        return COMMON_TIMEZONES

    def get_time_difference(self, tz1: str, tz2: str) -> Dict:
        """获取时区差异"""
        try:
            timezone1 = pytz.timezone(tz1)
            timezone2 = pytz.timezone(tz2)

            now = datetime.now(pytz.UTC)
            offset1 = timezone1.utcoffset(now)
            offset2 = timezone2.utcoffset(now)

            diff = offset2 - offset1
            diff_hours = diff.total_seconds() / 3600

            return {
                "timezone1": tz1,
                "timezone2": tz2,
                "difference_hours": diff_hours,
                "difference_formatted": f"{diff_hours:+.1f}h"
            }
        except pytz.UnknownTimeZoneError as e:
            raise ValueError(f"Unknown timezone: {e}")

    def create_timer(self, name: str, duration_seconds: int) -> Dict:
        """创建定时器"""
        end_time = datetime.now() + timedelta(seconds=duration_seconds)
        self.timers[name] = {
            "name": name,
            "duration": duration_seconds,
            "created_at": datetime.now().isoformat(),
            "end_time": end_time.isoformat(),
            "remaining": duration_seconds
        }
        return self.timers[name]

    def get_timer(self, name: str) -> Optional[Dict]:
        """获取定时器状态"""
        if name not in self.timers:
            return None

        timer = self.timers[name]
        end_time = datetime.fromisoformat(timer["end_time"])
        remaining = (end_time - datetime.now()).total_seconds()

        timer["remaining"] = max(0, int(remaining))
        timer["finished"] = remaining <= 0

        return timer

    def delete_timer(self, name: str) -> bool:
        """删除定时器"""
        if name in self.timers:
            del self.timers[name]
            return True
        return False

# 全局时间管理器
time_manager = TimeManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "23",
        "name": "Time",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/now")
async def get_current_time(timezone: str = "UTC"):
    """获取当前时间"""
    try:
        return time_manager.get_current_time(timezone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/convert")
async def convert_timezone(request: TimezoneConvertRequest):
    """转换时区"""
    try:
        return time_manager.convert_timezone(
            request.datetime_str,
            request.from_tz,
            request.to_tz,
            request.format
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/timezones")
async def list_timezones(all: bool = False):
    """列出时区"""
    if all:
        return {"timezones": time_manager.list_timezones()}
    return {"timezones": time_manager.get_common_timezones()}

@app.get("/difference")
async def get_time_difference(tz1: str, tz2: str):
    """获取时区差异"""
    try:
        return time_manager.get_time_difference(tz1, tz2)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/timers")
async def create_timer(request: TimerRequest):
    """创建定时器"""
    return time_manager.create_timer(request.name, request.duration_seconds)

@app.get("/timers/{name}")
async def get_timer(name: str):
    """获取定时器状态"""
    timer = time_manager.get_timer(name)
    if not timer:
        raise HTTPException(status_code=404, detail="Timer not found")
    return timer

@app.delete("/timers/{name}")
async def delete_timer(name: str):
    """删除定时器"""
    success = time_manager.delete_timer(name)
    if not success:
        raise HTTPException(status_code=404, detail="Timer not found")
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8123)
