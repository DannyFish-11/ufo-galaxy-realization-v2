"""
Node 111 - ContextManager (上下文管理节点)
提供会话上下文、状态管理和上下文切换能力
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 111 - ContextManager", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class ContextType(str, Enum):
    """上下文类型"""
    SESSION = "session"         # 会话上下文
    TASK = "task"               # 任务上下文
    USER = "user"               # 用户上下文
    SYSTEM = "system"           # 系统上下文
    CONVERSATION = "conversation"  # 对话上下文
    WORKFLOW = "workflow"       # 工作流上下文


class ContextScope(str, Enum):
    """上下文范围"""
    GLOBAL = "global"           # 全局
    LOCAL = "local"             # 局部
    TEMPORARY = "temporary"     # 临时


@dataclass
class ContextEntry:
    """上下文条目"""
    key: str
    value: Any
    context_type: ContextType
    scope: ContextScope
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: int = 1


@dataclass
class Context:
    """上下文"""
    context_id: str
    context_type: ContextType
    name: str
    entries: Dict[str, ContextEntry] = field(default_factory=dict)
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextSnapshot:
    """上下文快照"""
    snapshot_id: str
    context_id: str
    entries: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.now)
    description: str = ""


class ContextManager:
    """上下文管理器"""
    
    def __init__(self):
        self.contexts: Dict[str, Context] = {}
        self.snapshots: Dict[str, ContextSnapshot] = {}
        self.active_context_id: Optional[str] = None
        self._context_stack: List[str] = []
        self._initialize_system_context()
    
    def _initialize_system_context(self):
        """初始化系统上下文"""
        system_context = Context(
            context_id="system",
            context_type=ContextType.SYSTEM,
            name="System Context"
        )
        self.contexts["system"] = system_context
        
        # 添加系统级变量
        self.set("system", "startup_time", datetime.now().isoformat(), ContextScope.GLOBAL)
        self.set("system", "version", "2.0.0", ContextScope.GLOBAL)
    
    def create_context(self, context_type: ContextType, name: str, 
                       parent_id: Optional[str] = None, metadata: Dict = None) -> str:
        """创建新上下文"""
        context_id = str(uuid.uuid4())
        
        context = Context(
            context_id=context_id,
            context_type=context_type,
            name=name,
            parent_id=parent_id,
            metadata=metadata or {}
        )
        
        self.contexts[context_id] = context
        
        # 更新父上下文
        if parent_id and parent_id in self.contexts:
            self.contexts[parent_id].children_ids.append(context_id)
        
        logger.info(f"Created context: {context_id} ({name})")
        return context_id
    
    def delete_context(self, context_id: str, recursive: bool = False) -> bool:
        """删除上下文"""
        if context_id not in self.contexts:
            return False
        
        context = self.contexts[context_id]
        
        # 递归删除子上下文
        if recursive:
            for child_id in context.children_ids[:]:
                self.delete_context(child_id, recursive=True)
        
        # 从父上下文中移除
        if context.parent_id and context.parent_id in self.contexts:
            parent = self.contexts[context.parent_id]
            if context_id in parent.children_ids:
                parent.children_ids.remove(context_id)
        
        del self.contexts[context_id]
        logger.info(f"Deleted context: {context_id}")
        return True
    
    def set(self, context_id: str, key: str, value: Any, 
            scope: ContextScope = ContextScope.LOCAL,
            ttl: Optional[int] = None) -> bool:
        """设置上下文值"""
        if context_id not in self.contexts:
            return False
        
        context = self.contexts[context_id]
        
        expires_at = None
        if ttl:
            expires_at = datetime.now() + timedelta(seconds=ttl)
        
        if key in context.entries:
            entry = context.entries[key]
            entry.value = value
            entry.updated_at = datetime.now()
            entry.expires_at = expires_at
            entry.version += 1
        else:
            entry = ContextEntry(
                key=key,
                value=value,
                context_type=context.context_type,
                scope=scope,
                expires_at=expires_at
            )
            context.entries[key] = entry
        
        context.last_accessed = datetime.now()
        return True
    
    def get(self, context_id: str, key: str, default: Any = None, 
            inherit: bool = True) -> Any:
        """获取上下文值"""
        if context_id not in self.contexts:
            return default
        
        context = self.contexts[context_id]
        context.last_accessed = datetime.now()
        
        # 检查当前上下文
        if key in context.entries:
            entry = context.entries[key]
            
            # 检查是否过期
            if entry.expires_at and datetime.now() > entry.expires_at:
                del context.entries[key]
            else:
                return entry.value
        
        # 继承父上下文
        if inherit and context.parent_id:
            return self.get(context.parent_id, key, default, inherit=True)
        
        return default
    
    def delete_key(self, context_id: str, key: str) -> bool:
        """删除上下文键"""
        if context_id not in self.contexts:
            return False
        
        context = self.contexts[context_id]
        if key in context.entries:
            del context.entries[key]
            return True
        return False
    
    def get_all(self, context_id: str, include_inherited: bool = False) -> Dict[str, Any]:
        """获取上下文所有值"""
        if context_id not in self.contexts:
            return {}
        
        context = self.contexts[context_id]
        context.last_accessed = datetime.now()
        
        result = {}
        
        # 先获取继承的值
        if include_inherited and context.parent_id:
            result = self.get_all(context.parent_id, include_inherited=True)
        
        # 当前上下文的值覆盖继承的值
        for key, entry in context.entries.items():
            if entry.expires_at and datetime.now() > entry.expires_at:
                continue
            result[key] = entry.value
        
        return result
    
    def switch_context(self, context_id: str) -> bool:
        """切换当前上下文"""
        if context_id not in self.contexts:
            return False
        
        if self.active_context_id:
            self._context_stack.append(self.active_context_id)
        
        self.active_context_id = context_id
        self.contexts[context_id].is_active = True
        self.contexts[context_id].last_accessed = datetime.now()
        
        logger.info(f"Switched to context: {context_id}")
        return True
    
    def pop_context(self) -> Optional[str]:
        """弹出上下文栈"""
        if not self._context_stack:
            return None
        
        if self.active_context_id:
            self.contexts[self.active_context_id].is_active = False
        
        previous_id = self._context_stack.pop()
        self.active_context_id = previous_id
        
        if previous_id in self.contexts:
            self.contexts[previous_id].is_active = True
        
        return previous_id
    
    def create_snapshot(self, context_id: str, description: str = "") -> Optional[str]:
        """创建上下文快照"""
        if context_id not in self.contexts:
            return None
        
        context = self.contexts[context_id]
        
        entries = {}
        for key, entry in context.entries.items():
            if entry.expires_at and datetime.now() > entry.expires_at:
                continue
            entries[key] = entry.value
        
        snapshot = ContextSnapshot(
            snapshot_id=str(uuid.uuid4()),
            context_id=context_id,
            entries=entries,
            description=description
        )
        
        self.snapshots[snapshot.snapshot_id] = snapshot
        logger.info(f"Created snapshot: {snapshot.snapshot_id} for context {context_id}")
        return snapshot.snapshot_id
    
    def restore_snapshot(self, snapshot_id: str) -> bool:
        """恢复上下文快照"""
        if snapshot_id not in self.snapshots:
            return False
        
        snapshot = self.snapshots[snapshot_id]
        context_id = snapshot.context_id
        
        if context_id not in self.contexts:
            return False
        
        context = self.contexts[context_id]
        
        # 清除现有条目
        context.entries.clear()
        
        # 恢复快照条目
        for key, value in snapshot.entries.items():
            self.set(context_id, key, value)
        
        logger.info(f"Restored snapshot: {snapshot_id} to context {context_id}")
        return True
    
    def merge_contexts(self, source_id: str, target_id: str, 
                       overwrite: bool = False) -> bool:
        """合并上下文"""
        if source_id not in self.contexts or target_id not in self.contexts:
            return False
        
        source = self.contexts[source_id]
        
        for key, entry in source.entries.items():
            if entry.expires_at and datetime.now() > entry.expires_at:
                continue
            
            if overwrite or key not in self.contexts[target_id].entries:
                self.set(target_id, key, entry.value, entry.scope)
        
        logger.info(f"Merged context {source_id} into {target_id}")
        return True
    
    def cleanup_expired(self) -> int:
        """清理过期条目"""
        cleaned = 0
        now = datetime.now()
        
        for context in self.contexts.values():
            expired_keys = []
            for key, entry in context.entries.items():
                if entry.expires_at and now > entry.expires_at:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del context.entries[key]
                cleaned += 1
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired entries")
        return cleaned
    
    def get_context_info(self, context_id: str) -> Optional[Dict[str, Any]]:
        """获取上下文信息"""
        if context_id not in self.contexts:
            return None
        
        context = self.contexts[context_id]
        return {
            "context_id": context.context_id,
            "context_type": context.context_type.value,
            "name": context.name,
            "entry_count": len(context.entries),
            "parent_id": context.parent_id,
            "children_count": len(context.children_ids),
            "is_active": context.is_active,
            "created_at": context.created_at.isoformat(),
            "last_accessed": context.last_accessed.isoformat(),
            "metadata": context.metadata
        }
    
    def list_contexts(self, context_type: Optional[ContextType] = None) -> List[Dict[str, Any]]:
        """列出上下文"""
        result = []
        for context in self.contexts.values():
            if context_type and context.context_type != context_type:
                continue
            result.append(self.get_context_info(context.context_id))
        return result
    
    def get_status(self) -> Dict[str, Any]:
        """获取管理器状态"""
        return {
            "total_contexts": len(self.contexts),
            "active_context": self.active_context_id,
            "context_stack_depth": len(self._context_stack),
            "total_snapshots": len(self.snapshots),
            "contexts_by_type": {
                ct.value: sum(1 for c in self.contexts.values() if c.context_type == ct)
                for ct in ContextType
            }
        }


# 全局实例
context_manager = ContextManager()


# API 模型
class CreateContextRequest(BaseModel):
    context_type: str
    name: str
    parent_id: Optional[str] = None
    metadata: Dict[str, Any] = {}

class SetValueRequest(BaseModel):
    key: str
    value: Any
    scope: str = "local"
    ttl: Optional[int] = None

class MergeContextRequest(BaseModel):
    source_id: str
    target_id: str
    overwrite: bool = False


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_111_ContextManager"}

@app.get("/status")
async def get_status():
    return context_manager.get_status()

@app.post("/contexts")
async def create_context(request: CreateContextRequest):
    context_id = context_manager.create_context(
        ContextType(request.context_type),
        request.name,
        request.parent_id,
        request.metadata
    )
    return {"context_id": context_id}

@app.get("/contexts")
async def list_contexts(context_type: Optional[str] = None):
    ct = ContextType(context_type) if context_type else None
    return context_manager.list_contexts(ct)

@app.get("/contexts/{context_id}")
async def get_context(context_id: str):
    info = context_manager.get_context_info(context_id)
    if not info:
        raise HTTPException(status_code=404, detail="Context not found")
    return info

@app.delete("/contexts/{context_id}")
async def delete_context(context_id: str, recursive: bool = False):
    success = context_manager.delete_context(context_id, recursive)
    return {"success": success}

@app.post("/contexts/{context_id}/values")
async def set_value(context_id: str, request: SetValueRequest):
    success = context_manager.set(
        context_id,
        request.key,
        request.value,
        ContextScope(request.scope),
        request.ttl
    )
    return {"success": success}

@app.get("/contexts/{context_id}/values")
async def get_all_values(context_id: str, include_inherited: bool = False):
    values = context_manager.get_all(context_id, include_inherited)
    return values

@app.get("/contexts/{context_id}/values/{key}")
async def get_value(context_id: str, key: str, inherit: bool = True):
    value = context_manager.get(context_id, key, inherit=inherit)
    if value is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"key": key, "value": value}

@app.delete("/contexts/{context_id}/values/{key}")
async def delete_value(context_id: str, key: str):
    success = context_manager.delete_key(context_id, key)
    return {"success": success}

@app.post("/contexts/{context_id}/switch")
async def switch_context(context_id: str):
    success = context_manager.switch_context(context_id)
    return {"success": success}

@app.post("/contexts/pop")
async def pop_context():
    previous_id = context_manager.pop_context()
    return {"previous_context_id": previous_id}

@app.post("/contexts/{context_id}/snapshot")
async def create_snapshot(context_id: str, description: str = ""):
    snapshot_id = context_manager.create_snapshot(context_id, description)
    if not snapshot_id:
        raise HTTPException(status_code=404, detail="Context not found")
    return {"snapshot_id": snapshot_id}

@app.post("/snapshots/{snapshot_id}/restore")
async def restore_snapshot(snapshot_id: str):
    success = context_manager.restore_snapshot(snapshot_id)
    return {"success": success}

@app.get("/snapshots")
async def list_snapshots():
    return [asdict(s) for s in context_manager.snapshots.values()]

@app.post("/contexts/merge")
async def merge_contexts(request: MergeContextRequest):
    success = context_manager.merge_contexts(
        request.source_id,
        request.target_id,
        request.overwrite
    )
    return {"success": success}

@app.post("/cleanup")
async def cleanup_expired():
    cleaned = context_manager.cleanup_expired()
    return {"cleaned_entries": cleaned}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8111)
