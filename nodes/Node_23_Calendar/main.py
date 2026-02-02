"""
Node 23: Calendar - 日历和日程管理
"""
import os, json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 23 - Calendar", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

events = {}

class Event(BaseModel):
    title: str
    start: str  # ISO format
    end: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    reminder: Optional[int] = None  # minutes before

class EventQuery(BaseModel):
    start_date: str
    end_date: Optional[str] = None

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "23", "name": "Calendar", "events_count": len(events), "timestamp": datetime.now().isoformat()}

@app.post("/events")
async def create_event(event: Event):
    event_id = f"evt_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    events[event_id] = event.dict()
    events[event_id]["id"] = event_id
    events[event_id]["created_at"] = datetime.now().isoformat()
    return {"success": True, "event_id": event_id, "event": events[event_id]}

@app.get("/events")
async def list_events(start_date: Optional[str] = None, end_date: Optional[str] = None):
    result = []
    for eid, evt in events.items():
        if start_date and evt["start"] < start_date:
            continue
        if end_date and evt["start"] > end_date:
            continue
        result.append(evt)
    result.sort(key=lambda x: x["start"])
    return {"success": True, "events": result, "count": len(result)}

@app.get("/events/{event_id}")
async def get_event(event_id: str):
    if event_id not in events:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True, "event": events[event_id]}

@app.put("/events/{event_id}")
async def update_event(event_id: str, event: Event):
    if event_id not in events:
        raise HTTPException(status_code=404, detail="Event not found")
    events[event_id].update(event.dict())
    events[event_id]["updated_at"] = datetime.now().isoformat()
    return {"success": True, "event": events[event_id]}

@app.delete("/events/{event_id}")
async def delete_event(event_id: str):
    if event_id not in events:
        raise HTTPException(status_code=404, detail="Event not found")
    del events[event_id]
    return {"success": True, "deleted": event_id}

@app.get("/today")
async def today_events():
    today = datetime.now().strftime("%Y-%m-%d")
    result = [evt for evt in events.values() if evt["start"].startswith(today)]
    return {"success": True, "date": today, "events": result, "count": len(result)}

@app.get("/upcoming")
async def upcoming_events(days: int = 7):
    now = datetime.now()
    end = now + timedelta(days=days)
    result = [evt for evt in events.values() if now.isoformat() <= evt["start"] <= end.isoformat()]
    result.sort(key=lambda x: x["start"])
    return {"success": True, "events": result, "count": len(result)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "create": return await create_event(Event(**params))
    elif tool == "list": return await list_events(params.get("start_date"), params.get("end_date"))
    elif tool == "get": return await get_event(params.get("event_id", ""))
    elif tool == "update": return await update_event(params.get("event_id", ""), Event(**params.get("event", {})))
    elif tool == "delete": return await delete_event(params.get("event_id", ""))
    elif tool == "today": return await today_events()
    elif tool == "upcoming": return await upcoming_events(params.get("days", 7))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8023)
