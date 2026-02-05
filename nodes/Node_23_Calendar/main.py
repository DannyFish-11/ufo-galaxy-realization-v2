"""
Node 23: Calendar - 日历服务节点
==================================
提供日历管理、事件创建、提醒功能
"""
import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 23 - Calendar", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 配置
CALENDAR_FILE = os.getenv("CALENDAR_FILE", "/tmp/calendar.json")

class Event(BaseModel):
    id: str
    title: str
    description: str = ""
    start_time: datetime
    end_time: datetime
    location: str = ""
    attendees: List[str] = []
    reminder_minutes: int = 15
    recurrence: Optional[str] = None  # daily, weekly, monthly
    color: str = "#3498db"
    created_at: datetime
    updated_at: datetime

class CreateEventRequest(BaseModel):
    title: str
    description: str = ""
    start_time: datetime
    end_time: datetime
    location: str = ""
    attendees: List[str] = []
    reminder_minutes: int = 15
    recurrence: Optional[str] = None
    color: str = "#3498db"

class CalendarManager:
    def __init__(self):
        self.events: Dict[str, Event] = {}
        self._load_events()

    def _load_events(self):
        """加载事件"""
        if os.path.exists(CALENDAR_FILE):
            try:
                with open(CALENDAR_FILE, 'r') as f:
                    data = json.load(f)
                    for event_data in data.get("events", []):
                        event = Event(**event_data)
                        self.events[event.id] = event
            except Exception as e:
                print(f"Failed to load events: {e}")

    def _save_events(self):
        """保存事件"""
        try:
            with open(CALENDAR_FILE, 'w') as f:
                json.dump({"events": [e.dict() for e in self.events.values()]}, f, default=str)
        except Exception as e:
            print(f"Failed to save events: {e}")

    def create_event(self, **kwargs) -> Event:
        """创建事件"""
        now = datetime.now()
        event = Event(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            **kwargs
        )
        self.events[event.id] = event
        self._save_events()
        return event

    def update_event(self, event_id: str, **kwargs) -> Optional[Event]:
        """更新事件"""
        if event_id not in self.events:
            return None

        event = self.events[event_id]
        for key, value in kwargs.items():
            if hasattr(event, key):
                setattr(event, key, value)
        event.updated_at = datetime.now()
        self._save_events()
        return event

    def delete_event(self, event_id: str) -> bool:
        """删除事件"""
        if event_id in self.events:
            del self.events[event_id]
            self._save_events()
            return True
        return False

    def get_event(self, event_id: str) -> Optional[Event]:
        """获取事件"""
        return self.events.get(event_id)

    def list_events(self, start: Optional[datetime] = None, 
                   end: Optional[datetime] = None) -> List[Event]:
        """列出事件"""
        events = list(self.events.values())

        if start:
            events = [e for e in events if e.end_time >= start]
        if end:
            events = [e for e in events if e.start_time <= end]

        return sorted(events, key=lambda x: x.start_time)

    def get_upcoming_events(self, days: int = 7) -> List[Event]:
        """获取即将发生的事件"""
        now = datetime.now()
        end = now + timedelta(days=days)
        return self.list_events(start=now, end=end)

    def get_events_for_day(self, date: datetime) -> List[Event]:
        """获取某天的事件"""
        start = date.replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=1)
        return self.list_events(start=start, end=end)

    def check_conflicts(self, start: datetime, end: datetime, 
                       exclude_id: Optional[str] = None) -> List[Event]:
        """检查时间冲突"""
        conflicts = []
        for event in self.events.values():
            if exclude_id and event.id == exclude_id:
                continue
            # 检查是否有重叠
            if start < event.end_time and end > event.start_time:
                conflicts.append(event)
        return conflicts

# 全局日历管理器
calendar_manager = CalendarManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "23",
        "name": "Calendar",
        "events_count": len(calendar_manager.events),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/events")
async def create_event(request: CreateEventRequest):
    """创建事件"""
    try:
        event = calendar_manager.create_event(**request.dict())
        return event
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events")
async def list_events(start: Optional[datetime] = None, end: Optional[datetime] = None):
    """列出事件"""
    try:
        events = calendar_manager.list_events(start=start, end=end)
        return {"events": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events/{event_id}")
async def get_event(event_id: str):
    """获取事件详情"""
    event = calendar_manager.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

@app.put("/events/{event_id}")
async def update_event(event_id: str, request: CreateEventRequest):
    """更新事件"""
    event = calendar_manager.update_event(event_id, **request.dict())
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

@app.delete("/events/{event_id}")
async def delete_event(event_id: str):
    """删除事件"""
    success = calendar_manager.delete_event(event_id)
    if not success:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True}

@app.get("/events/upcoming")
async def get_upcoming_events(days: int = 7):
    """获取即将发生的事件"""
    try:
        events = calendar_manager.get_upcoming_events(days)
        return {"events": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/conflicts")
async def check_conflicts(start: datetime, end: datetime, exclude_id: Optional[str] = None):
    """检查时间冲突"""
    try:
        conflicts = calendar_manager.check_conflicts(start, end, exclude_id)
        return {"conflicts": conflicts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8023)
