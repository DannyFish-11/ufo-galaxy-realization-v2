"""
Node 13: SQLite - SQLite数据库节点
=====================================
提供SQLite数据库连接、查询、事务管理功能
"""
import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 13 - SQLite", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# SQLite配置
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "/tmp/sqlite.db")

class QueryRequest(BaseModel):
    query: str
    params: List[Any] = []
    fetch: str = "all"  # one, all, none

class TransactionRequest(BaseModel):
    queries: List[Dict[str, Any]]

class SQLiteManager:
    def __init__(self):
        self.db_path = SQLITE_DB_PATH
        self._ensure_directory()

    def _ensure_directory(self):
        """确保数据库目录存在"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    @contextmanager
    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def execute(self, query: str, params: tuple = None, fetch: str = "all") -> Any:
        """执行查询"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or ())

            if fetch == "none":
                conn.commit()
                return {"affected_rows": cursor.rowcount}
            elif fetch == "one":
                row = cursor.fetchone()
                return dict(row) if row else None
            else:  # all
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def execute_transaction(self, queries: List[Dict[str, Any]]) -> List[Any]:
        """执行事务"""
        results = []
        with self._get_connection() as conn:
            try:
                conn.execute("BEGIN TRANSACTION")
                for q in queries:
                    query = q["query"]
                    params = tuple(q.get("params", []))
                    fetch = q.get("fetch", "none")

                    cursor = conn.cursor()
                    cursor.execute(query, params)

                    if fetch == "none":
                        results.append({"affected_rows": cursor.rowcount})
                    elif fetch == "one":
                        row = cursor.fetchone()
                        results.append(dict(row) if row else None)
                    else:
                        rows = cursor.fetchall()
                        results.append([dict(row) for row in rows])

                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
        return results

    def list_tables(self) -> List[str]:
        """列出所有表"""
        query = "SELECT name FROM sqlite_master WHERE type='table'"
        rows = self.execute(query)
        return [row["name"] for row in rows]

    def get_table_schema(self, table_name: str) -> List[Dict]:
        """获取表结构"""
        query = f"PRAGMA table_info({table_name})"
        rows = self.execute(query)
        return [{"name": r["name"], "type": r["type"], "notnull": r["notnull"], 
                 "default": r["dflt_value"], "pk": r["pk"]} for r in rows]

    def get_table_stats(self, table_name: str) -> Dict:
        """获取表统计信息"""
        query = f"SELECT COUNT(*) as count FROM {table_name}"
        result = self.execute(query, fetch="one")
        return {"table_name": table_name, "row_count": result["count"] if result else 0}

    def backup(self, backup_path: str) -> bool:
        """备份数据库"""
        with self._get_connection() as conn:
            backup_conn = sqlite3.connect(backup_path)
            conn.backup(backup_conn)
            backup_conn.close()
        return True

    def vacuum(self) -> bool:
        """优化数据库"""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
        return True

# 全局SQLite管理器
sqlite_manager = SQLiteManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "13",
        "name": "SQLite",
        "db_path": SQLITE_DB_PATH,
        "tables": sqlite_manager.list_tables(),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/query")
async def execute_query(request: QueryRequest):
    """执行SQL查询"""
    try:
        result = sqlite_manager.execute(request.query, tuple(request.params), request.fetch)
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transaction")
async def execute_transaction(request: TransactionRequest):
    """执行事务"""
    try:
        results = sqlite_manager.execute_transaction(request.queries)
        return {"success": True, "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tables")
async def list_tables():
    """列出所有表"""
    try:
        tables = sqlite_manager.list_tables()
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/schema/{table_name}")
async def get_table_schema(table_name: str):
    """获取表结构"""
    try:
        schema = sqlite_manager.get_table_schema(table_name)
        return {"table_name": table_name, "columns": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats/{table_name}")
async def get_table_stats(table_name: str):
    """获取表统计信息"""
    try:
        stats = sqlite_manager.get_table_stats(table_name)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backup")
async def backup_database(backup_path: str = "/tmp/sqlite_backup.db"):
    """备份数据库"""
    try:
        success = sqlite_manager.backup(backup_path)
        return {"success": success, "backup_path": backup_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/vacuum")
async def vacuum_database():
    """优化数据库"""
    try:
        success = sqlite_manager.vacuum()
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8013)
