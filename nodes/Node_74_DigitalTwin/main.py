"""Node 74: DigitalTwin - 数字孪生"""
import os, json
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 74 - DigitalTwin", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 数字孪生状态存储
twins: Dict[str, Dict] = {}

class TwinCreateRequest(BaseModel):
    twin_id: str
    name: str
    type: str  # device, environment, process
    properties: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None

class TwinUpdateRequest(BaseModel):
    twin_id: str
    properties: Dict[str, Any]

class SimulateRequest(BaseModel):
    twin_id: str
    scenario: str
    parameters: Optional[Dict[str, Any]] = None

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "74", "name": "DigitalTwin", "twin_count": len(twins), "timestamp": datetime.now().isoformat()}

@app.post("/create")
async def create_twin(request: TwinCreateRequest):
    if request.twin_id in twins:
        raise HTTPException(status_code=400, detail="Twin already exists")
    twins[request.twin_id] = {
        "id": request.twin_id,
        "name": request.name,
        "type": request.type,
        "properties": request.properties,
        "metadata": request.metadata or {},
        "history": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    return {"success": True, "twin_id": request.twin_id}

@app.post("/update")
async def update_twin(request: TwinUpdateRequest):
    if request.twin_id not in twins:
        raise HTTPException(status_code=404, detail="Twin not found")
    
    twin = twins[request.twin_id]
    # 记录历史
    twin["history"].append({"properties": twin["properties"].copy(), "timestamp": twin["updated_at"]})
    if len(twin["history"]) > 100:
        twin["history"] = twin["history"][-100:]
    
    twin["properties"].update(request.properties)
    twin["updated_at"] = datetime.now().isoformat()
    return {"success": True, "twin_id": request.twin_id, "properties": twin["properties"]}

@app.get("/get/{twin_id}")
async def get_twin(twin_id: str):
    if twin_id not in twins:
        raise HTTPException(status_code=404, detail="Twin not found")
    return {"success": True, "twin": twins[twin_id]}

@app.get("/list")
async def list_twins():
    return {"success": True, "twins": [{"id": t["id"], "name": t["name"], "type": t["type"]} for t in twins.values()]}

@app.post("/simulate")
async def simulate(request: SimulateRequest):
    if request.twin_id not in twins:
        raise HTTPException(status_code=404, detail="Twin not found")
    
    twin = twins[request.twin_id]
    params = request.parameters or {}
    
    # 简单模拟逻辑
    result = {"scenario": request.scenario, "twin_id": request.twin_id, "initial_state": twin["properties"].copy()}
    
    if request.scenario == "temperature_change":
        delta = params.get("delta", 5)
        if "temperature" in twin["properties"]:
            result["predicted_temperature"] = twin["properties"]["temperature"] + delta
    elif request.scenario == "load_test":
        load = params.get("load", 100)
        result["predicted_response_time"] = load * 0.01
        result["predicted_success_rate"] = max(0, 100 - load * 0.1)
    else:
        result["message"] = f"Simulation for scenario '{request.scenario}' completed"
    
    result["timestamp"] = datetime.now().isoformat()
    return {"success": True, "result": result}

@app.delete("/delete/{twin_id}")
async def delete_twin(twin_id: str):
    if twin_id not in twins:
        raise HTTPException(status_code=404, detail="Twin not found")
    del twins[twin_id]
    return {"success": True, "twin_id": twin_id}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "create": return await create_twin(TwinCreateRequest(**params))
    elif tool == "update": return await update_twin(TwinUpdateRequest(**params))
    elif tool == "get": return await get_twin(params.get("twin_id"))
    elif tool == "list": return await list_twins()
    elif tool == "simulate": return await simulate(SimulateRequest(**params))
    elif tool == "delete": return await delete_twin(params.get("twin_id"))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8074)
