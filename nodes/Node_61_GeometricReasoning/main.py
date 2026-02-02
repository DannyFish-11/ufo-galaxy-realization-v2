"""
Node 61: GeometricReasoning - 几何推理
"""
import os, math
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 61 - GeometricReasoning", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class Point(BaseModel):
    x: float
    y: float
    z: float = 0

class LineRequest(BaseModel):
    p1: Point
    p2: Point

class TriangleRequest(BaseModel):
    a: Point
    b: Point
    c: Point

class CircleRequest(BaseModel):
    center: Point
    radius: float

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "61", "name": "GeometricReasoning", "timestamp": datetime.now().isoformat()}

def distance(p1: Point, p2: Point) -> float:
    return math.sqrt((p2.x - p1.x)**2 + (p2.y - p1.y)**2 + (p2.z - p1.z)**2)

def cross_product_2d(o: Point, a: Point, b: Point) -> float:
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)

@app.post("/distance")
async def calc_distance(request: LineRequest):
    """计算两点间距离"""
    d = distance(request.p1, request.p2)
    return {"success": True, "distance": round(d, 6)}

@app.post("/midpoint")
async def calc_midpoint(request: LineRequest):
    """计算中点"""
    mid = Point(x=(request.p1.x + request.p2.x) / 2, y=(request.p1.y + request.p2.y) / 2, z=(request.p1.z + request.p2.z) / 2)
    return {"success": True, "midpoint": {"x": mid.x, "y": mid.y, "z": mid.z}}

@app.post("/triangle/area")
async def triangle_area(request: TriangleRequest):
    """计算三角形面积 (海伦公式)"""
    a = distance(request.b, request.c)
    b = distance(request.a, request.c)
    c = distance(request.a, request.b)
    s = (a + b + c) / 2
    area = math.sqrt(s * (s - a) * (s - b) * (s - c))
    return {"success": True, "area": round(area, 6), "sides": {"a": round(a, 4), "b": round(b, 4), "c": round(c, 4)}}

@app.post("/triangle/centroid")
async def triangle_centroid(request: TriangleRequest):
    """计算三角形重心"""
    cx = (request.a.x + request.b.x + request.c.x) / 3
    cy = (request.a.y + request.b.y + request.c.y) / 3
    return {"success": True, "centroid": {"x": round(cx, 4), "y": round(cy, 4)}}

@app.post("/triangle/type")
async def triangle_type(request: TriangleRequest):
    """判断三角形类型"""
    a = distance(request.b, request.c)
    b = distance(request.a, request.c)
    c = distance(request.a, request.b)
    sides = sorted([a, b, c])
    
    # 按边分类
    if abs(sides[0] - sides[1]) < 1e-6 and abs(sides[1] - sides[2]) < 1e-6:
        side_type = "equilateral"
    elif abs(sides[0] - sides[1]) < 1e-6 or abs(sides[1] - sides[2]) < 1e-6:
        side_type = "isosceles"
    else:
        side_type = "scalene"
    
    # 按角分类
    a2, b2, c2 = sides[0]**2, sides[1]**2, sides[2]**2
    if abs(a2 + b2 - c2) < 1e-6:
        angle_type = "right"
    elif a2 + b2 < c2:
        angle_type = "obtuse"
    else:
        angle_type = "acute"
    
    return {"success": True, "side_type": side_type, "angle_type": angle_type}

@app.post("/circle/area")
async def circle_area(request: CircleRequest):
    """计算圆面积"""
    area = math.pi * request.radius ** 2
    circumference = 2 * math.pi * request.radius
    return {"success": True, "area": round(area, 6), "circumference": round(circumference, 6)}

@app.post("/point_in_triangle")
async def point_in_triangle(point: Point, triangle: TriangleRequest):
    """判断点是否在三角形内"""
    d1 = cross_product_2d(point, triangle.a, triangle.b)
    d2 = cross_product_2d(point, triangle.b, triangle.c)
    d3 = cross_product_2d(point, triangle.c, triangle.a)
    
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    
    inside = not (has_neg and has_pos)
    return {"success": True, "inside": inside}

@app.post("/convex_hull")
async def convex_hull(points: List[Point]):
    """计算凸包 (Graham Scan)"""
    if len(points) < 3:
        return {"success": True, "hull": [{"x": p.x, "y": p.y} for p in points]}
    
    pts = sorted([(p.x, p.y) for p in points])
    
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    
    hull = lower[:-1] + upper[:-1]
    return {"success": True, "hull": [{"x": p[0], "y": p[1]} for p in hull]}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "distance": return await calc_distance(LineRequest(**params))
    elif tool == "midpoint": return await calc_midpoint(LineRequest(**params))
    elif tool == "triangle_area": return await triangle_area(TriangleRequest(**params))
    elif tool == "triangle_centroid": return await triangle_centroid(TriangleRequest(**params))
    elif tool == "triangle_type": return await triangle_type(TriangleRequest(**params))
    elif tool == "circle_area": return await circle_area(CircleRequest(**params))
    elif tool == "point_in_triangle": return await point_in_triangle(Point(**params.get("point", {})), TriangleRequest(**params.get("triangle", {})))
    elif tool == "convex_hull": return await convex_hull([Point(**p) for p in params.get("points", [])])
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8061)
