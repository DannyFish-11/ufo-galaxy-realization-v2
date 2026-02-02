"""
Node 56: Planning - 任务规划和调度
"""
import os, heapq
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 56 - Planning", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class Task(BaseModel):
    id: str
    name: str
    duration: int  # minutes
    dependencies: List[str] = []
    priority: int = 5  # 1-10
    deadline: Optional[str] = None

class PlanRequest(BaseModel):
    tasks: List[Task]
    available_time: int = 480  # minutes per day

class PathRequest(BaseModel):
    graph: Dict[str, Dict[str, int]]
    start: str
    end: str

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "56", "name": "Planning", "timestamp": datetime.now().isoformat()}

@app.post("/topological_sort")
async def topological_sort(request: PlanRequest):
    """拓扑排序任务"""
    tasks = {t.id: t for t in request.tasks}
    in_degree = {t.id: 0 for t in request.tasks}
    adj = {t.id: [] for t in request.tasks}
    
    for task in request.tasks:
        for dep in task.dependencies:
            if dep in adj:
                adj[dep].append(task.id)
                in_degree[task.id] += 1
    
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    result = []
    
    while queue:
        queue.sort(key=lambda x: -tasks[x].priority)
        current = queue.pop(0)
        result.append({"id": current, "name": tasks[current].name, "duration": tasks[current].duration})
        
        for neighbor in adj[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    if len(result) != len(request.tasks):
        return {"success": False, "error": "Circular dependency detected"}
    
    return {"success": True, "order": result, "total_duration": sum(t["duration"] for t in result)}

@app.post("/schedule")
async def schedule_tasks(request: PlanRequest):
    """调度任务到多天"""
    sorted_result = await topological_sort(request)
    if not sorted_result["success"]:
        return sorted_result
    
    tasks = sorted_result["order"]
    days = []
    current_day = {"day": 1, "tasks": [], "total_time": 0}
    
    for task in tasks:
        if current_day["total_time"] + task["duration"] <= request.available_time:
            current_day["tasks"].append(task)
            current_day["total_time"] += task["duration"]
        else:
            days.append(current_day)
            current_day = {"day": len(days) + 1, "tasks": [task], "total_time": task["duration"]}
    
    if current_day["tasks"]:
        days.append(current_day)
    
    return {"success": True, "schedule": days, "total_days": len(days)}

@app.post("/shortest_path")
async def dijkstra(request: PathRequest):
    """Dijkstra 最短路径"""
    graph = request.graph
    start = request.start
    end = request.end
    
    if start not in graph:
        raise HTTPException(status_code=400, detail=f"Start node {start} not in graph")
    
    distances = {node: float('inf') for node in graph}
    distances[start] = 0
    previous = {node: None for node in graph}
    pq = [(0, start)]
    
    while pq:
        current_dist, current = heapq.heappop(pq)
        
        if current == end:
            break
        
        if current_dist > distances[current]:
            continue
        
        for neighbor, weight in graph.get(current, {}).items():
            distance = current_dist + weight
            if distance < distances.get(neighbor, float('inf')):
                distances[neighbor] = distance
                previous[neighbor] = current
                heapq.heappush(pq, (distance, neighbor))
    
    path = []
    current = end
    while current:
        path.append(current)
        current = previous.get(current)
    path.reverse()
    
    if distances.get(end, float('inf')) == float('inf'):
        return {"success": False, "error": f"No path from {start} to {end}"}
    
    return {"success": True, "path": path, "distance": distances[end]}

@app.post("/critical_path")
async def critical_path(request: PlanRequest):
    """关键路径分析"""
    tasks = {t.id: t for t in request.tasks}
    
    earliest_start = {}
    earliest_finish = {}
    
    def calc_earliest(tid):
        if tid in earliest_start:
            return earliest_finish[tid]
        task = tasks[tid]
        if not task.dependencies:
            earliest_start[tid] = 0
        else:
            earliest_start[tid] = max(calc_earliest(dep) for dep in task.dependencies)
        earliest_finish[tid] = earliest_start[tid] + task.duration
        return earliest_finish[tid]
    
    for tid in tasks:
        calc_earliest(tid)
    
    project_duration = max(earliest_finish.values())
    
    latest_finish = {}
    latest_start = {}
    
    for tid in tasks:
        latest_finish[tid] = project_duration
        latest_start[tid] = project_duration - tasks[tid].duration
    
    critical = [tid for tid in tasks if earliest_start[tid] == latest_start[tid]]
    
    return {"success": True, "project_duration": project_duration, "critical_path": critical, "earliest_start": earliest_start, "earliest_finish": earliest_finish}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "topological_sort": return await topological_sort(PlanRequest(**params))
    elif tool == "schedule": return await schedule_tasks(PlanRequest(**params))
    elif tool == "shortest_path": return await dijkstra(PathRequest(**params))
    elif tool == "critical_path": return await critical_path(PlanRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8056)
