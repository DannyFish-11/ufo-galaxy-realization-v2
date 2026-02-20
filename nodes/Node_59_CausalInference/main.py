"""
Node 59: CausalInference - 因果推理
"""
import os, random, math
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 59 - CausalInference", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class CausalGraphRequest(BaseModel):
    nodes: List[str]
    edges: List[List[str]]

class ATERequest(BaseModel):
    treatment: List[int]
    outcome: List[float]
    confounders: Optional[List[List[float]]] = None

class DoCalculusRequest(BaseModel):
    graph: Dict[str, List[str]]
    intervention: str
    outcome: str

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "59", "name": "CausalInference", "timestamp": datetime.now().isoformat()}

@app.post("/build_graph")
async def build_causal_graph(request: CausalGraphRequest):
    """构建因果图"""
    graph = {node: [] for node in request.nodes}
    for edge in request.edges:
        if len(edge) == 2:
            cause, effect = edge
            if cause in graph:
                graph[cause].append(effect)
    
    # 检测环
    def has_cycle(node, visited, rec_stack):
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if has_cycle(neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                return True
        rec_stack.remove(node)
        return False
    
    visited = set()
    is_dag = not any(has_cycle(n, visited, set()) for n in request.nodes if n not in visited)
    
    return {"success": True, "graph": graph, "is_dag": is_dag, "nodes": len(request.nodes), "edges": len(request.edges)}

@app.post("/ate")
async def average_treatment_effect(request: ATERequest):
    """计算平均处理效应 (ATE)"""
    if len(request.treatment) != len(request.outcome):
        raise HTTPException(status_code=400, detail="Treatment and outcome must have same length")
    
    treated = [o for t, o in zip(request.treatment, request.outcome) if t == 1]
    control = [o for t, o in zip(request.treatment, request.outcome) if t == 0]
    
    if not treated or not control:
        raise HTTPException(status_code=400, detail="Need both treated and control groups")
    
    ate = sum(treated) / len(treated) - sum(control) / len(control)
    
    # Bootstrap 置信区间
    bootstrap_ates = []
    for _ in range(1000):
        t_sample = random.choices(treated, k=len(treated))
        c_sample = random.choices(control, k=len(control))
        bootstrap_ates.append(sum(t_sample) / len(t_sample) - sum(c_sample) / len(c_sample))
    
    bootstrap_ates.sort()
    ci_lower = bootstrap_ates[25]
    ci_upper = bootstrap_ates[975]
    
    return {"success": True, "ate": round(ate, 4), "ci_95": [round(ci_lower, 4), round(ci_upper, 4)], "n_treated": len(treated), "n_control": len(control)}

@app.post("/do_calculus")
async def do_calculus(request: DoCalculusRequest):
    """Do-calculus 干预分析"""
    graph = request.graph
    intervention = request.intervention
    outcome = request.outcome
    
    # 找到所有从 intervention 到 outcome 的路径
    def find_paths(start, end, path=[]):
        path = path + [start]
        if start == end:
            return [path]
        if start not in graph:
            return []
        paths = []
        for node in graph[start]:
            if node not in path:
                new_paths = find_paths(node, end, path)
                paths.extend(new_paths)
        return paths
    
    paths = find_paths(intervention, outcome)
    
    # 找到后门路径 (需要调整的混杂因素)
    backdoor_vars = set()
    for node, children in graph.items():
        if intervention in children and outcome in children:
            backdoor_vars.add(node)
    
    return {
        "success": True,
        "intervention": f"do({intervention})",
        "outcome": outcome,
        "causal_paths": paths,
        "backdoor_variables": list(backdoor_vars),
        "adjustment_needed": len(backdoor_vars) > 0
    }

@app.post("/counterfactual")
async def counterfactual_analysis(factual_outcome: float, treatment_effect: float, was_treated: bool):
    """反事实分析"""
    if was_treated:
        counterfactual = factual_outcome - treatment_effect
        return {"success": True, "factual": f"Treated, outcome={factual_outcome}", "counterfactual": f"If not treated, outcome would be {round(counterfactual, 2)}"}
    else:
        counterfactual = factual_outcome + treatment_effect
        return {"success": True, "factual": f"Not treated, outcome={factual_outcome}", "counterfactual": f"If treated, outcome would be {round(counterfactual, 2)}"}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "build_graph": return await build_causal_graph(CausalGraphRequest(**params))
    elif tool == "ate": return await average_treatment_effect(ATERequest(**params))
    elif tool == "do_calculus": return await do_calculus(DoCalculusRequest(**params))
    elif tool == "counterfactual": return await counterfactual_analysis(params.get("factual_outcome", 0), params.get("treatment_effect", 0), params.get("was_treated", True))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8059)
