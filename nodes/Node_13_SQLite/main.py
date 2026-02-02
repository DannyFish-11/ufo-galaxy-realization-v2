"""
Node 13: SQLite - 完整的 SQLite 数据库操作服务
支持多数据库连接、事务管理、备份恢复、查询优化等高级功能
"""
import os
import sqlite3
import json
import shutil
from datetime import datetime
from typing import Optional, List, Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 13 - SQLite", version="3.0.0", description="完整的 SQLite 数据库操作服务")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DB_PATH = os.getenv("SQLITE_DB_PATH", "/tmp/galaxy.db")
connections = {}

class QueryRequest(BaseModel):
    sql: str
    params: Optional[List[Any]] = None
    db_path: Optional[str] = None

class TableRequest(BaseModel):
    table_name: str
    columns: Dict[str, str]
    db_path: Optional[str] = None

class InsertRequest(BaseModel):
    table_name: str
    data: Dict[str, Any]
    db_path: Optional[str] = None

class UpdateRequest(BaseModel):
    table_name: str
    data: Dict[str, Any]
    where: str
    params: Optional[List[Any]] = None
    db_path: Optional[str] = None

class DeleteRequest(BaseModel):
    table_name: str
    where: str
    params: Optional[List[Any]] = None
    db_path: Optional[str] = None

class BackupRequest(BaseModel):
    source_db: Optional[str] = None
    target_path: str

class TransactionRequest(BaseModel):
    queries: List[QueryRequest]
    db_path: Optional[str] = None

def get_connection(db_path: str = None):
    """获取或创建数据库连接"""
    path = db_path or DB_PATH
    if path not in connections:
        # 确保目录存在
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        connections[path] = sqlite3.connect(path, check_same_thread=False)
        connections[path].row_factory = sqlite3.Row
        # 启用外键约束
        connections[path].execute("PRAGMA foreign_keys = ON")
    return connections[path]

def close_connection(db_path: str = None):
    """关闭数据库连接"""
    path = db_path or DB_PATH
    if path in connections:
        connections[path].close()
        del connections[path]

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "node_id": "13",
        "name": "SQLite",
        "version": "3.0.0",
        "default_db": DB_PATH,
        "active_connections": len(connections),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/query")
async def execute_query(request: QueryRequest):
    """执行 SQL 查询"""
    try:
        conn = get_connection(request.db_path)
        cursor = conn.cursor()
        
        if request.params:
            cursor.execute(request.sql, request.params)
        else:
            cursor.execute(request.sql)
        
        if request.sql.strip().upper().startswith("SELECT"):
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            results = [dict(zip(columns, row)) for row in rows]
            return {"success": True, "results": results, "count": len(results)}
        else:
            conn.commit()
            return {"success": True, "rowcount": cursor.rowcount, "lastrowid": cursor.lastrowid}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/transaction")
async def execute_transaction(request: TransactionRequest):
    """执行事务（多个查询作为一个原子操作）"""
    try:
        conn = get_connection(request.db_path)
        conn.execute("BEGIN TRANSACTION")
        
        results = []
        for query in request.queries:
            cursor = conn.cursor()
            if query.params:
                cursor.execute(query.sql, query.params)
            else:
                cursor.execute(query.sql)
            
            if query.sql.strip().upper().startswith("SELECT"):
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                results.append([dict(zip(columns, row)) for row in rows])
            else:
                results.append({"rowcount": cursor.rowcount, "lastrowid": cursor.lastrowid})
        
        conn.commit()
        return {"success": True, "results": results}
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}

@app.post("/create_table")
async def create_table(request: TableRequest):
    """创建表"""
    try:
        columns_sql = ", ".join([f"{name} {dtype}" for name, dtype in request.columns.items()])
        sql = f"CREATE TABLE IF NOT EXISTS {request.table_name} ({columns_sql})"
        return await execute_query(QueryRequest(sql=sql, db_path=request.db_path))
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/drop_table/{table_name}")
async def drop_table(table_name: str, db_path: Optional[str] = None):
    """删除表"""
    try:
        sql = f"DROP TABLE IF EXISTS {table_name}"
        return await execute_query(QueryRequest(sql=sql, db_path=db_path))
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/tables")
async def list_tables(db_path: Optional[str] = None):
    """列出所有表"""
    sql = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    result = await execute_query(QueryRequest(sql=sql, db_path=db_path))
    if result["success"]:
        return {"success": True, "tables": [r["name"] for r in result["results"]]}
    return result

@app.get("/schema/{table_name}")
async def get_schema(table_name: str, db_path: Optional[str] = None):
    """获取表结构"""
    sql = f"PRAGMA table_info({table_name})"
    result = await execute_query(QueryRequest(sql=sql, db_path=db_path))
    if result["success"]:
        return {"success": True, "table": table_name, "columns": result["results"]}
    return result

@app.post("/insert")
async def insert_data(request: InsertRequest):
    """插入数据"""
    try:
        columns = ", ".join(request.data.keys())
        placeholders = ", ".join(["?" for _ in request.data])
        sql = f"INSERT INTO {request.table_name} ({columns}) VALUES ({placeholders})"
        return await execute_query(QueryRequest(sql=sql, params=list(request.data.values()), db_path=request.db_path))
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/update")
async def update_data(request: UpdateRequest):
    """更新数据"""
    try:
        set_clause = ", ".join([f"{k} = ?" for k in request.data.keys()])
        sql = f"UPDATE {request.table_name} SET {set_clause} WHERE {request.where}"
        params = list(request.data.values()) + (request.params or [])
        return await execute_query(QueryRequest(sql=sql, params=params, db_path=request.db_path))
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/delete")
async def delete_data(request: DeleteRequest):
    """删除数据"""
    try:
        sql = f"DELETE FROM {request.table_name} WHERE {request.where}"
        return await execute_query(QueryRequest(sql=sql, params=request.params, db_path=request.db_path))
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/backup")
async def backup_database(request: BackupRequest):
    """备份数据库"""
    try:
        source = request.source_db or DB_PATH
        target = request.target_path
        
        # 确保目标目录存在
        os.makedirs(os.path.dirname(target) if os.path.dirname(target) else ".", exist_ok=True)
        
        # 使用 SQLite 的备份 API
        source_conn = get_connection(source)
        target_conn = sqlite3.connect(target)
        source_conn.backup(target_conn)
        target_conn.close()
        
        return {"success": True, "source": source, "target": target, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/restore")
async def restore_database(backup_path: str, target_db: Optional[str] = None):
    """从备份恢复数据库"""
    try:
        target = target_db or DB_PATH
        
        # 关闭现有连接
        close_connection(target)
        
        # 复制备份文件
        shutil.copy2(backup_path, target)
        
        return {"success": True, "backup": backup_path, "target": target, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/analyze/{table_name}")
async def analyze_table(table_name: str, db_path: Optional[str] = None):
    """分析表（更新统计信息以优化查询）"""
    try:
        sql = f"ANALYZE {table_name}"
        result = await execute_query(QueryRequest(sql=sql, db_path=db_path))
        if result["success"]:
            return {"success": True, "table": table_name, "message": "分析完成"}
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/vacuum")
async def vacuum_database(db_path: Optional[str] = None):
    """压缩数据库（清理碎片，减小文件大小）"""
    try:
        sql = "VACUUM"
        result = await execute_query(QueryRequest(sql=sql, db_path=db_path))
        if result["success"]:
            return {"success": True, "message": "数据库压缩完成"}
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/integrity_check")
async def integrity_check(db_path: Optional[str] = None):
    """检查数据库完整性"""
    try:
        sql = "PRAGMA integrity_check"
        result = await execute_query(QueryRequest(sql=sql, db_path=db_path))
        if result["success"]:
            return {"success": True, "check_results": result["results"]}
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "query":
        return await execute_query(QueryRequest(**params))
    elif tool == "transaction":
        return await execute_transaction(TransactionRequest(**params))
    elif tool == "create_table":
        return await create_table(TableRequest(**params))
    elif tool == "drop_table":
        return await drop_table(params.get("table_name", ""), params.get("db_path"))
    elif tool == "tables":
        return await list_tables(params.get("db_path"))
    elif tool == "schema":
        return await get_schema(params.get("table_name", ""), params.get("db_path"))
    elif tool == "insert":
        return await insert_data(InsertRequest(**params))
    elif tool == "update":
        return await update_data(UpdateRequest(**params))
    elif tool == "delete":
        return await delete_data(DeleteRequest(**params))
    elif tool == "backup":
        return await backup_database(BackupRequest(**params))
    elif tool == "restore":
        return await restore_database(params.get("backup_path", ""), params.get("target_db"))
    elif tool == "analyze":
        return await analyze_table(params.get("table_name", ""), params.get("db_path"))
    elif tool == "vacuum":
        return await vacuum_database(params.get("db_path"))
    elif tool == "integrity_check":
        return await integrity_check(params.get("db_path"))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8013)
