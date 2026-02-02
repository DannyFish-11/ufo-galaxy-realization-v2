"""
Node 28: Reserved
==================
预留节点 - 待未来扩展

此节点为占位符，可根据需要实现具体功能。
"""

import os
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Node 28 - Reserved", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

NODE_ID = os.getenv("NODE_ID", "26")
NODE_NAME = os.getenv("NODE_NAME", "Reserved")

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "reserved",
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "message": "This node is reserved for future expansion",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/")
async def root():
    """根路径"""
    return {
        "node": f"Node {NODE_ID}",
        "name": NODE_NAME,
        "status": "reserved",
        "description": "预留节点 - 待未来扩展"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(f"80{NODE_ID}"))
