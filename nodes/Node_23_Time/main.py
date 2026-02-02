"""
Node 23: Time - 时间和时区处理
"""
import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 23 - Time", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

pytz = None
try:
    import pytz as _pytz
    pytz = _pytz
except ImportError:
    pass

class FormatRequest(BaseModel):
    timestamp: Optional[float] = None
    format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"

class ParseRequest(BaseModel):
    datetime_str: str
    format: str = "%Y-%m-%d %H:%M:%S"
    timezone: str = "UTC"

class ConvertRequest(BaseModel):
    timestamp: float
    from_tz: str = "UTC"
    to_tz: str = "UTC"

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "23", "name": "Time", "pytz_available": pytz is not None, "timestamp": datetime.now().isoformat()}

@app.get("/now")
async def get_now(timezone: str = "UTC", format: str = "%Y-%m-%d %H:%M:%S"):
    now = datetime.utcnow()
    if pytz and timezone != "UTC":
        try:
            tz = pytz.timezone(timezone)
            now = datetime.now(tz)
        except:
            pass
    return {"success": True, "timestamp": now.timestamp(), "formatted": now.strftime(format), "timezone": timezone, "iso": now.isoformat()}

@app.post("/format")
async def format_time(request: FormatRequest):
    ts = request.timestamp or datetime.utcnow().timestamp()
    dt = datetime.fromtimestamp(ts)
    
    if pytz and request.timezone != "UTC":
        try:
            tz = pytz.timezone(request.timezone)
            dt = datetime.fromtimestamp(ts, tz)
        except:
            pass
    
    return {"success": True, "formatted": dt.strftime(request.format), "timestamp": ts}

@app.post("/parse")
async def parse_time(request: ParseRequest):
    try:
        dt = datetime.strptime(request.datetime_str, request.format)
        
        if pytz and request.timezone != "UTC":
            try:
                tz = pytz.timezone(request.timezone)
                dt = tz.localize(dt)
            except:
                pass
        
        return {"success": True, "timestamp": dt.timestamp(), "iso": dt.isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/convert")
async def convert_timezone(request: ConvertRequest):
    if not pytz:
        return {"success": False, "error": "pytz not installed"}
    
    try:
        from_tz = pytz.timezone(request.from_tz)
        to_tz = pytz.timezone(request.to_tz)
        
        dt = datetime.fromtimestamp(request.timestamp, from_tz)
        converted = dt.astimezone(to_tz)
        
        return {"success": True, "original": dt.isoformat(), "converted": converted.isoformat(), "timestamp": converted.timestamp()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/timezones")
async def list_timezones():
    if pytz:
        return {"success": True, "timezones": list(pytz.all_timezones)[:100], "total": len(pytz.all_timezones)}
    return {"success": True, "timezones": ["UTC", "US/Eastern", "US/Pacific", "Europe/London", "Asia/Shanghai", "Asia/Tokyo"]}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "now": return await get_now(params.get("timezone", "UTC"), params.get("format", "%Y-%m-%d %H:%M:%S"))
    elif tool == "format": return await format_time(FormatRequest(**params))
    elif tool == "parse": return await parse_time(ParseRequest(**params))
    elif tool == "convert": return await convert_timezone(ConvertRequest(**params))
    elif tool == "timezones": return await list_timezones()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8023)
