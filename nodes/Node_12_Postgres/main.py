"""Node 12: Postgres - 数据库操作"""
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 12 - Postgres", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

psycopg2 = None
try:
    import psycopg2 as _psycopg2
    from psycopg2.extras import RealDictCursor
    psycopg2 = _psycopg2
except ImportError:
    pass

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB", "postgres")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASS", "")

class QueryRequest(BaseModel):
    sql: str
    params: Optional[List[Any]] = None

@app.get("/health")
async def health():
    return {"status": "healthy" if psycopg2 else "degraded", "node_id": "12", "name": "Postgres", "psycopg2_available": psycopg2 is not None, "timestamp": datetime.now().isoformat()}

def get_conn():
    if not psycopg2:
        raise HTTPException(status_code=503, detail="psycopg2 not installed. Run: pip install psycopg2-binary")
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS)

@app.post("/query")
async def query(request: QueryRequest):
    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(request.sql, request.params)
        if request.sql.strip().upper().startswith("SELECT"):
            rows = cur.fetchall()
            result = {"success": True, "rows": [dict(row) for row in rows], "rowcount": len(rows)}
        else:
            conn.commit()
            result = {"success": True, "rowcount": cur.rowcount}
        cur.close()
        conn.close()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "query": return await query(QueryRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8012)
