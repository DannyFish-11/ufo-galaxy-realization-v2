"""
Node 53: GraphLogic - 图论和逻辑推理
"""
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from collections import deque
import heapq

app = FastAPI(title="Node 53 - GraphLogic", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class Graph(BaseModel):
    nodes: List[str]
    edges: List[Dict[str, Any]]
    directed: bool = False

class PathRequest(BaseModel):
    graph: Graph
    start: str
    end: str
    algorithm: str = "dijkstra"

class LogicRequest(BaseModel):
    premises: List[str]
    query: str

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "53", "name": "GraphLogic", "timestamp": datetime.now().isoformat()}

def build_adjacency(graph: Graph) -> Dict[str, Dict[str, float]]:
    adj = {node: {} for node in graph.nodes}
    for edge in graph.edges:
        src, dst = edge["source"], edge["target"]
        weight = edge.get("weight", 1)
        adj[src][dst] = weight
        if not graph.directed:
            adj[dst][src] = weight
    return adj

@app.post("/shortest_path")
async def shortest_path(request: PathRequest):
    adj = build_adjacency(request.graph)
    
    if request.algorithm == "dijkstra":
        distances = {node: float('inf') for node in request.graph.nodes}
        distances[request.start] = 0
        previous = {}
        pq = [(0, request.start)]
        
        while pq:
            dist, current = heapq.heappop(pq)
            if current == request.end:
                break
            if dist > distances[current]:
                continue
            for neighbor, weight in adj.get(current, {}).items():
                new_dist = dist + weight
                if new_dist < distances.get(neighbor, float('inf')):
                    distances[neighbor] = new_dist
                    previous[neighbor] = current
                    heapq.heappush(pq, (new_dist, neighbor))
        
        path = []
        current = request.end
        while current in previous:
            path.append(current)
            current = previous[current]
        path.append(request.start)
        path.reverse()
        
        if distances[request.end] == float('inf'):
            return {"success": False, "error": "No path found"}
        
        return {"success": True, "path": path, "distance": distances[request.end], "algorithm": "dijkstra"}
    
    elif request.algorithm == "bfs":
        visited = {request.start}
        queue = deque([(request.start, [request.start])])
        
        while queue:
            current, path = queue.popleft()
            if current == request.end:
                return {"success": True, "path": path, "distance": len(path) - 1, "algorithm": "bfs"}
            
            for neighbor in adj.get(current, {}):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        
        return {"success": False, "error": "No path found"}
    
    return {"success": False, "error": f"Unknown algorithm: {request.algorithm}"}

@app.post("/connected_components")
async def connected_components(graph: Graph):
    adj = build_adjacency(graph)
    visited = set()
    components = []
    
    def dfs(node: str, component: List[str]):
        visited.add(node)
        component.append(node)
        for neighbor in adj.get(node, {}):
            if neighbor not in visited:
                dfs(neighbor, component)
    
    for node in graph.nodes:
        if node not in visited:
            component = []
            dfs(node, component)
            components.append(component)
    
    return {"success": True, "components": components, "count": len(components)}

@app.post("/topological_sort")
async def topological_sort(graph: Graph):
    if not graph.directed:
        return {"success": False, "error": "Topological sort requires directed graph"}
    
    adj = build_adjacency(graph)
    in_degree = {node: 0 for node in graph.nodes}
    
    for edge in graph.edges:
        in_degree[edge["target"]] += 1
    
    queue = deque([node for node, deg in in_degree.items() if deg == 0])
    result = []
    
    while queue:
        current = queue.popleft()
        result.append(current)
        for neighbor in adj.get(current, {}):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    if len(result) != len(graph.nodes):
        return {"success": False, "error": "Graph has cycle"}
    
    return {"success": True, "order": result}

@app.post("/cycle_detection")
async def detect_cycle(graph: Graph):
    adj = build_adjacency(graph)
    
    if graph.directed:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node: WHITE for node in graph.nodes}
        
        def dfs(node):
            color[node] = GRAY
            for neighbor in adj.get(node, {}):
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE and dfs(neighbor):
                    return True
            color[node] = BLACK
            return False
        
        for node in graph.nodes:
            if color[node] == WHITE and dfs(node):
                return {"success": True, "has_cycle": True}
        return {"success": True, "has_cycle": False}
    else:
        visited = set()
        
        def dfs(node, parent):
            visited.add(node)
            for neighbor in adj.get(node, {}):
                if neighbor not in visited:
                    if dfs(neighbor, node):
                        return True
                elif neighbor != parent:
                    return True
            return False
        
        for node in graph.nodes:
            if node not in visited:
                if dfs(node, None):
                    return {"success": True, "has_cycle": True}
        return {"success": True, "has_cycle": False}

@app.post("/mst")
async def minimum_spanning_tree(graph: Graph):
    if graph.directed:
        return {"success": False, "error": "MST requires undirected graph"}
    
    edges = [(e.get("weight", 1), e["source"], e["target"]) for e in graph.edges]
    edges.sort()
    
    parent = {node: node for node in graph.nodes}
    rank = {node: 0 for node in graph.nodes}
    
    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    
    def union(x, y):
        px, py = find(x), find(y)
        if px == py:
            return False
        if rank[px] < rank[py]:
            px, py = py, px
        parent[py] = px
        if rank[px] == rank[py]:
            rank[px] += 1
        return True
    
    mst_edges = []
    total_weight = 0
    
    for weight, src, dst in edges:
        if union(src, dst):
            mst_edges.append({"source": src, "target": dst, "weight": weight})
            total_weight += weight
    
    return {"success": True, "edges": mst_edges, "total_weight": total_weight}

@app.post("/logic/evaluate")
async def evaluate_logic(request: LogicRequest):
    facts = set()
    rules = []
    
    for premise in request.premises:
        if "->" in premise:
            parts = premise.split("->")
            antecedent = parts[0].strip()
            consequent = parts[1].strip()
            rules.append((antecedent, consequent))
        else:
            facts.add(premise.strip())
    
    changed = True
    while changed:
        changed = False
        for antecedent, consequent in rules:
            if antecedent in facts and consequent not in facts:
                facts.add(consequent)
                changed = True
    
    result = request.query in facts
    return {"success": True, "query": request.query, "result": result, "derived_facts": list(facts)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "shortest_path": return await shortest_path(PathRequest(**params))
    elif tool == "connected_components": return await connected_components(Graph(**params.get("graph", {})))
    elif tool == "topological_sort": return await topological_sort(Graph(**params.get("graph", {})))
    elif tool == "cycle_detection": return await detect_cycle(Graph(**params.get("graph", {})))
    elif tool == "mst": return await minimum_spanning_tree(Graph(**params.get("graph", {})))
    elif tool == "logic_evaluate": return await evaluate_logic(LogicRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8053)
