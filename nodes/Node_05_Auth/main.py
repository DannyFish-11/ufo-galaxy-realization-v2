"""
Node 05: Auth Guardian
======================
访问权限与身份校验服务。
支持 JWT、API Key、RBAC 等多种认证方式。

功能：
- JWT 令牌签发与验证
- API Key 管理
- 角色权限控制 (RBAC)
- 访问日志审计
"""

import os
import json
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass, field
from enum import Enum

import jwt
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

app = FastAPI(title="Node 05 - Auth Guardian", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

# =============================================================================
# Configuration
# =============================================================================

JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# =============================================================================
# Models
# =============================================================================

class Role(Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    SERVICE = "service"

class Permission(Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"

@dataclass
class User:
    """用户信息"""
    id: str
    username: str
    roles: Set[Role] = field(default_factory=set)
    api_keys: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_login: datetime = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class APIKey:
    """API Key"""
    key: str
    user_id: str
    name: str
    permissions: Set[Permission] = field(default_factory=set)
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = None
    last_used: datetime = None
    rate_limit: int = 1000  # requests per hour

@dataclass
class AccessLog:
    """访问日志"""
    timestamp: datetime
    user_id: str
    action: str
    resource: str
    result: str
    ip_address: str = None
    details: Dict[str, Any] = None

# =============================================================================
# RBAC Configuration
# =============================================================================

ROLE_PERMISSIONS = {
    Role.ADMIN: {Permission.READ, Permission.WRITE, Permission.EXECUTE, Permission.ADMIN},
    Role.OPERATOR: {Permission.READ, Permission.WRITE, Permission.EXECUTE},
    Role.VIEWER: {Permission.READ},
    Role.SERVICE: {Permission.READ, Permission.EXECUTE},
}

# 节点访问控制
NODE_ACCESS = {
    # Layer 0 节点需要 ADMIN 或 SERVICE 角色
    "00": {Role.ADMIN, Role.SERVICE},
    "01": {Role.ADMIN, Role.SERVICE, Role.OPERATOR},
    "02": {Role.ADMIN, Role.SERVICE, Role.OPERATOR},
    "03": {Role.ADMIN},  # 密钥库只有管理员可访问
    "04": {Role.ADMIN, Role.SERVICE},
    "05": {Role.ADMIN},
    
    # Layer 1 节点
    "50": {Role.ADMIN, Role.SERVICE, Role.OPERATOR},
    "58": {Role.ADMIN, Role.SERVICE, Role.OPERATOR},
    
    # Layer 2 工具节点 - 所有角色可访问
    "06": {Role.ADMIN, Role.SERVICE, Role.OPERATOR, Role.VIEWER},
    "07": {Role.ADMIN, Role.SERVICE, Role.OPERATOR, Role.VIEWER},
    
    # Layer 3 物理节点需要 OPERATOR 以上
    "33": {Role.ADMIN, Role.SERVICE, Role.OPERATOR},
    "49": {Role.ADMIN, Role.SERVICE, Role.OPERATOR},
}

# =============================================================================
# Auth Guardian Core
# =============================================================================

class AuthGuardian:
    """认证守卫"""
    
    def __init__(self):
        self.users: Dict[str, User] = {}
        self.api_keys: Dict[str, APIKey] = {}
        self.access_logs: List[AccessLog] = []
        self._init_default_users()
        
    def _init_default_users(self):
        """初始化默认用户"""
        # 系统管理员
        admin = User(
            id="admin",
            username="admin",
            roles={Role.ADMIN}
        )
        self.users["admin"] = admin
        
        # 服务账户
        service = User(
            id="service",
            username="service",
            roles={Role.SERVICE}
        )
        self.users["service"] = service
        
        # 创建默认 API Key
        default_key = os.getenv("DEFAULT_API_KEY", "ufo-galaxy-default-key")
        self.api_keys[default_key] = APIKey(
            key=default_key,
            user_id="service",
            name="Default Service Key",
            permissions={Permission.READ, Permission.EXECUTE}
        )
        
    def create_user(
        self,
        username: str,
        roles: List[str] = None,
        metadata: Dict[str, Any] = None
    ) -> User:
        """创建用户"""
        user_id = hashlib.sha256(username.encode()).hexdigest()[:16]
        
        user = User(
            id=user_id,
            username=username,
            roles={Role(r) for r in (roles or ["viewer"])},
            metadata=metadata or {}
        )
        
        self.users[user_id] = user
        return user
        
    def create_api_key(
        self,
        user_id: str,
        name: str,
        permissions: List[str] = None,
        expires_days: int = None
    ) -> APIKey:
        """创建 API Key"""
        if user_id not in self.users:
            raise ValueError(f"User not found: {user_id}")
            
        key = f"ufo_{secrets.token_urlsafe(32)}"
        
        api_key = APIKey(
            key=key,
            user_id=user_id,
            name=name,
            permissions={Permission(p) for p in (permissions or ["read"])},
            expires_at=datetime.now() + timedelta(days=expires_days) if expires_days else None
        )
        
        self.api_keys[key] = api_key
        self.users[user_id].api_keys.append(key)
        
        return api_key
        
    def generate_jwt(self, user_id: str) -> str:
        """生成 JWT 令牌"""
        user = self.users.get(user_id)
        if not user:
            raise ValueError(f"User not found: {user_id}")
            
        payload = {
            "sub": user_id,
            "username": user.username,
            "roles": [r.value for r in user.roles],
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
        }
        
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
        # 更新最后登录时间
        user.last_login = datetime.now()
        
        return token
        
    def verify_jwt(self, token: str) -> Dict[str, Any]:
        """验证 JWT 令牌"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return {
                "valid": True,
                "user_id": payload["sub"],
                "username": payload["username"],
                "roles": payload["roles"],
                "expires_at": datetime.fromtimestamp(payload["exp"]).isoformat()
            }
        except jwt.ExpiredSignatureError:
            return {"valid": False, "error": "Token expired"}
        except jwt.InvalidTokenError as e:
            return {"valid": False, "error": str(e)}
            
    def verify_api_key(self, key: str) -> Dict[str, Any]:
        """验证 API Key"""
        api_key = self.api_keys.get(key)
        if not api_key:
            return {"valid": False, "error": "Invalid API key"}
            
        # 检查过期
        if api_key.expires_at and datetime.now() > api_key.expires_at:
            return {"valid": False, "error": "API key expired"}
            
        # 更新最后使用时间
        api_key.last_used = datetime.now()
        
        return {
            "valid": True,
            "user_id": api_key.user_id,
            "name": api_key.name,
            "permissions": [p.value for p in api_key.permissions]
        }
        
    def check_permission(
        self,
        user_id: str,
        permission: Permission,
        resource: str = None
    ) -> bool:
        """检查权限"""
        user = self.users.get(user_id)
        if not user:
            return False
            
        # 检查角色权限
        for role in user.roles:
            if permission in ROLE_PERMISSIONS.get(role, set()):
                return True
                
        return False
        
    def check_node_access(self, user_id: str, node_id: str) -> bool:
        """检查节点访问权限"""
        user = self.users.get(user_id)
        if not user:
            return False
            
        allowed_roles = NODE_ACCESS.get(node_id, {Role.ADMIN, Role.SERVICE, Role.OPERATOR, Role.VIEWER})
        
        return bool(user.roles & allowed_roles)
        
    def log_access(
        self,
        user_id: str,
        action: str,
        resource: str,
        result: str,
        ip_address: str = None,
        details: Dict[str, Any] = None
    ):
        """记录访问日志"""
        log = AccessLog(
            timestamp=datetime.now(),
            user_id=user_id,
            action=action,
            resource=resource,
            result=result,
            ip_address=ip_address,
            details=details
        )
        self.access_logs.append(log)
        
        # 保留最近 10000 条
        if len(self.access_logs) > 10000:
            self.access_logs = self.access_logs[-10000:]
            
    def get_access_logs(
        self,
        user_id: str = None,
        action: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取访问日志"""
        logs = self.access_logs
        
        if user_id:
            logs = [l for l in logs if l.user_id == user_id]
        if action:
            logs = [l for l in logs if l.action == action]
            
        return [
            {
                "timestamp": l.timestamp.isoformat(),
                "user_id": l.user_id,
                "action": l.action,
                "resource": l.resource,
                "result": l.result,
                "ip_address": l.ip_address
            }
            for l in logs[-limit:]
        ]

# =============================================================================
# Global Instance
# =============================================================================

guardian = AuthGuardian()

# =============================================================================
# API Endpoints
# =============================================================================

class LoginRequest(BaseModel):
    username: str
    password: str = None  # 简化版，实际应该验证密码

class CreateUserRequest(BaseModel):
    username: str
    roles: List[str] = ["viewer"]
    metadata: Dict[str, Any] = None

class CreateAPIKeyRequest(BaseModel):
    user_id: str
    name: str
    permissions: List[str] = ["read"]
    expires_days: int = None

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "node_id": "05",
        "name": "Auth Guardian",
        "users": len(guardian.users),
        "api_keys": len(guardian.api_keys),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/login")
async def login(request: LoginRequest):
    """登录获取 JWT"""
    # 简化版：只检查用户是否存在
    user = None
    for u in guardian.users.values():
        if u.username == request.username:
            user = u
            break
            
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    token = guardian.generate_jwt(user.id)
    
    guardian.log_access(user.id, "login", "/login", "success")
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": JWT_EXPIRE_HOURS * 3600
    }

@app.post("/verify/jwt")
async def verify_jwt(authorization: str = Header(None)):
    """验证 JWT"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
        
    token = authorization[7:]
    result = guardian.verify_jwt(token)
    
    if not result["valid"]:
        raise HTTPException(status_code=401, detail=result["error"])
        
    return result

@app.post("/verify/apikey")
async def verify_apikey(x_api_key: str = Header(None)):
    """验证 API Key"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
        
    result = guardian.verify_api_key(x_api_key)
    
    if not result["valid"]:
        raise HTTPException(status_code=401, detail=result["error"])
        
    return result

@app.post("/users")
async def create_user(request: CreateUserRequest):
    """创建用户"""
    user = guardian.create_user(
        username=request.username,
        roles=request.roles,
        metadata=request.metadata
    )
    return {
        "user_id": user.id,
        "username": user.username,
        "roles": [r.value for r in user.roles]
    }

@app.get("/users")
async def list_users():
    """列出用户"""
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "roles": [r.value for r in u.roles],
                "created_at": u.created_at.isoformat()
            }
            for u in guardian.users.values()
        ]
    }

@app.post("/apikeys")
async def create_api_key(request: CreateAPIKeyRequest):
    """创建 API Key"""
    api_key = guardian.create_api_key(
        user_id=request.user_id,
        name=request.name,
        permissions=request.permissions,
        expires_days=request.expires_days
    )
    return {
        "key": api_key.key,
        "name": api_key.name,
        "permissions": [p.value for p in api_key.permissions],
        "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None
    }

@app.get("/check/permission")
async def check_permission(
    user_id: str,
    permission: str,
    resource: str = None
):
    """检查权限"""
    allowed = guardian.check_permission(
        user_id=user_id,
        permission=Permission(permission),
        resource=resource
    )
    return {"allowed": allowed}

@app.get("/check/node/{node_id}")
async def check_node_access(node_id: str, user_id: str):
    """检查节点访问权限"""
    allowed = guardian.check_node_access(user_id, node_id)
    return {"allowed": allowed, "node_id": node_id}

@app.get("/logs")
async def get_logs(
    user_id: str = None,
    action: str = None,
    limit: int = 100
):
    """获取访问日志"""
    return {
        "logs": guardian.get_access_logs(user_id, action, limit)
    }

# =============================================================================
# MCP Tool Interface
# =============================================================================

@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "verify_jwt":
        return guardian.verify_jwt(params.get("token", ""))
    elif tool == "verify_apikey":
        return guardian.verify_api_key(params.get("key", ""))
    elif tool == "check_permission":
        return {
            "allowed": guardian.check_permission(
                params.get("user_id", ""),
                Permission(params.get("permission", "read"))
            )
        }
    elif tool == "check_node_access":
        return {
            "allowed": guardian.check_node_access(
                params.get("user_id", ""),
                params.get("node_id", "")
            )
        }
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
