"""Node 73: Learning - 自主学习系统"""
import os, json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 73 - Learning", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 学习数据存储
learning_data = {
    "feedback": [],
    "patterns": {},
    "preferences": {},
    "stats": {"total_interactions": 0, "positive_feedback": 0, "negative_feedback": 0}
}

DATA_FILE = "/tmp/learning_data.json"

def load_data():
    global learning_data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            learning_data = json.load(f)

def save_data():
    with open(DATA_FILE, 'w') as f:
        json.dump(learning_data, f)

load_data()

class FeedbackRequest(BaseModel):
    action: str
    result: str
    rating: int  # 1-5
    context: Optional[Dict[str, Any]] = None

class PatternRequest(BaseModel):
    pattern_name: str
    trigger: str
    response: str

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "73", "name": "Learning", "total_feedback": len(learning_data["feedback"]), "timestamp": datetime.now().isoformat()}

@app.post("/feedback")
async def record_feedback(request: FeedbackRequest):
    feedback_entry = {
        "action": request.action,
        "result": request.result,
        "rating": request.rating,
        "context": request.context,
        "timestamp": datetime.now().isoformat()
    }
    learning_data["feedback"].append(feedback_entry)
    learning_data["stats"]["total_interactions"] += 1
    if request.rating >= 4:
        learning_data["stats"]["positive_feedback"] += 1
    elif request.rating <= 2:
        learning_data["stats"]["negative_feedback"] += 1
    save_data()
    return {"success": True, "feedback_id": len(learning_data["feedback"]) - 1}

@app.post("/pattern")
async def add_pattern(request: PatternRequest):
    learning_data["patterns"][request.pattern_name] = {"trigger": request.trigger, "response": request.response, "created_at": datetime.now().isoformat()}
    save_data()
    return {"success": True, "pattern_name": request.pattern_name}

@app.get("/stats")
async def get_stats():
    return {"success": True, "stats": learning_data["stats"], "pattern_count": len(learning_data["patterns"]), "feedback_count": len(learning_data["feedback"])}

@app.get("/patterns")
async def get_patterns():
    return {"success": True, "patterns": learning_data["patterns"]}

@app.post("/preference")
async def set_preference(key: str, value: Any):
    learning_data["preferences"][key] = value
    save_data()
    return {"success": True, "key": key, "value": value}

@app.get("/preference/{key}")
async def get_preference(key: str):
    if key in learning_data["preferences"]:
        return {"success": True, "key": key, "value": learning_data["preferences"][key]}
    raise HTTPException(status_code=404, detail="Preference not found")

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "feedback": return await record_feedback(FeedbackRequest(**params))
    elif tool == "pattern": return await add_pattern(PatternRequest(**params))
    elif tool == "stats": return await get_stats()
    elif tool == "patterns": return await get_patterns()
    elif tool == "set_preference": return await set_preference(params.get("key"), params.get("value"))
    elif tool == "get_preference": return await get_preference(params.get("key"))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8073)
