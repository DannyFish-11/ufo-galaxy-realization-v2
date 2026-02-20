"""
Node 12: PostgreSQL - PostgreSQL数据库节点
===========================================
提供PostgreSQL数据库连接、查询、事务管理功能
"""
import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 尝试导入asyncpg
try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

app = FastAPI(title="Node 12 - PostgreSQL", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# PostgreSQL配置
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
PG_DATABASE = os.getenv("POSTGRES_DATABASE", "postgres")
PG_POOL_SIZE = int(os.getenv("POSTGRES_POOL_SIZE", "10"))

class QueryRequest(BaseModel):
    query: str
    params: List[Any] = []
    fetch: str = "all"  # one, all, none

class TransactionRequest(BaseModel):
    queries: List[Dict[str, Any]]  # [{"query": "...", "params": []}]

class PostgresManager:
    def __init__(self):
        self.pool = None
        self._connected = False

    async def connect(self):
        """创建连接池"""
        if not ASYNCPG_AVAILABLE:
            raise RuntimeError("asyncpg not installed. Install with: pip install asyncpg")

        if not self.pool:
            self.pool = await asyncpg.create_pool(
                host=PG_HOST,
                port=PG_PORT,
                user=PG_USER,
                password=PG_PASSWORD,
                database=PG_DATABASE,
                min_size=1,
                max_size=PG_POOL_SIZE
            )
            self._connected = True

    async def disconnect(self):
        """关闭连接池"""
        if self.pool:
            await self.pool.close()
            self.pool = None
            self._connected = False

    async def execute(self, query: str, params: List[Any] = None, fetch: str = "all") -> Any:
        """执行查询"""
        if not self._connected:
            await self.connect()

        async with self.pool.acquire() as conn:
            if fetch == "none":
                result = await conn.execute(query, *(params or []))
                return {"affected_rows": int(result.split()[-1]) if result.split() else 0}
            elif fetch == "one":
                row = await conn.fetchrow(query, *(params or []))
                return dict(row) if row else None
            else:  # all
                rows = await conn.fetch(query, *(params or []))
                return [dict(row) for row in rows]

    async def execute_transaction(self, queries: List[Dict[str, Any]]) -> List[Any]:
        """执行事务"""
        if not self._connected:
            await self.connect()

        results = []
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for q in queries:
                    query = q["query"]
                    params = q.get("params", [])
                    fetch = q.get("fetch", "none")

                    if fetch == "none":
                        result = await conn.execute(query, *params)
                        results.append({"affected_rows": int(result.split()[-1]) if result.split() else 0})
                    elif fetch == "one":
                        row = await conn.fetchrow(query, *params)
                        results.append(dict(row) if row else None)
                    else:
                        rows = await conn.fetch(query, *params)
                        results.append([dict(row) for row in rows])
        return results

    async def list_tables(self) -> List[str]:
        """列出所有表"""
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """
        rows = await self.execute(query)
        return [row["table_name"] for row in rows]

    async def get_table_schema(self, table_name: str) -> List[Dict]:
        """获取表结构"""
        query = """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = $1 AND table_schema = 'public'
        """
        return await self.execute(query, [table_name])

    async def get_table_stats(self, table_name: str) -> Dict:
        """获取表统计信息"""
        query = f"SELECT COUNT(*) as count FROM {table_name}"
        result = await self.execute(query, fetch="one")
        return {"table_name": table_name, "row_count": result["count"] if result else 0}

# 全局PostgreSQL管理器
pg_manager = PostgresManager()

@app.on_event("startup")
async def startup():
    if ASYNCPG_AVAILABLE:
        await pg_manager.connect()

@app.on_event("shutdown")
async def shutdown():
    if ASYNCPG_AVAILABLE:
        await pg_manager.disconnect()

# ============ API 端点 ============

@app.get("/health")
async def health():
    status = "healthy" if pg_manager._connected else "unavailable"
    return {
        "status": status,
        "node_id": "12",
        "name": "PostgreSQL",
        "host": PG_HOST,
        "port": PG_PORT,
        "database": PG_DATABASE,
        "asyncpg_available": ASYNCPG_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/query")
async def execute_query(request: QueryRequest):
    """执行SQL查询"""
    if not ASYNCPG_AVAILABLE:
        raise HTTPException(status_code=503, detail="asyncpg not installed")

    try:
        result = await pg_manager.execute(request.query, request.params, request.fetch)
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transaction")
async def execute_transaction(request: TransactionRequest):
    """执行事务"""
    if not ASYNCPG_AVAILABLE:
        raise HTTPException(status_code=503, detail="asyncpg not installed")

    try:
        results = await pg_manager.execute_transaction(request.queries)
        return {"success": True, "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tables")
async def list_tables():
    """列出所有表"""
    if not ASYNCPG_AVAILABLE:
        raise HTTPException(status_code=503, detail="asyncpg not installed")

    try:
        tables = await pg_manager.list_tables()
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/schema/{table_name}")
async def get_table_schema(table_name: str):
    """获取表结构"""
    if not ASYNCPG_AVAILABLE:
        raise HTTPException(status_code=503, detail="asyncpg not installed")

    try:
        schema = await pg_manager.get_table_schema(table_name)
        return {"table_name": table_name, "columns": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats/{table_name}")
async def get_table_stats(table_name: str):
    """获取表统计信息"""
    if not ASYNCPG_AVAILABLE:
        raise HTTPException(status_code=503, detail="asyncpg not installed")

    try:
        stats = await pg_manager.get_table_stats(table_name)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8012)
