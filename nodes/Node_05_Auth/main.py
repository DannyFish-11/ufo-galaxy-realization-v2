"""
Node 05: Auth - 认证服务
=========================
提供用户认证、JWT令牌管理、权限控制功能
"""
import os
import jwt
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

app = FastAPI(title="Node 05 - Auth", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# JWT配置
JWT_SECRET = os.getenv("AUTH_JWT_SECRET", secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.getenv("AUTH_JWT_EXPIRE_DAYS", "7"))

security = HTTPBearer()

class User(BaseModel):
    username: str
    password_hash: str
    email: Optional[str] = None
    role: str = "user"
    created_at: datetime
    last_login: Optional[datetime] = None
    is_active: bool = True
    permissions: List[str] = []

class TokenData(BaseModel):
    username: str
    role: str
    permissions: List[str]
    exp: datetime

class AuthManager:
    def __init__(self):
        self._users: Dict[str, User] = {}
        self._refresh_tokens: Dict[str, str] = {}  # token -> username
        self._failed_attempts: Dict[str, List[datetime]] = {}
        self._load_users()

    def _load_users(self):
        """加载用户数据"""
        users_file = os.getenv("AUTH_USERS_FILE", "/tmp/auth_users.json")
        if os.path.exists(users_file):
            try:
                with open(users_file, 'r') as f:
                    data = json.load(f)
                    for username, user_data in data.get("users", {}).items():
                        self._users[username] = User(**user_data)
            except Exception as e:
                print(f"Failed to load users: {e}")
        # 创建默认管理员
        if "admin" not in self._users:
            self.create_user("admin", "admin123", email="admin@localhost", role="admin", permissions=["*"])

    def _save_users(self):
        """保存用户数据"""
        users_file = os.getenv("AUTH_USERS_FILE", "/tmp/auth_users.json")
        try:
            with open(users_file, 'w') as f:
                json.dump({"users": {k: v.dict() for k, v in self._users.items()}}, f, default=str)
        except Exception as e:
            print(f"Failed to save users: {e}")

    def _hash_password(self, password: str) -> str:
        """哈希密码"""
        salt = secrets.token_hex(16)
        pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return salt + pwdhash.hex()

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """验证密码"""
        salt = password_hash[:32]
        pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return password_hash == salt + pwdhash.hex()

    def _check_rate_limit(self, username: str) -> bool:
        """检查登录频率限制"""
        now = datetime.now()
        attempts = self._failed_attempts.get(username, [])
        # 保留最近5分钟内的失败记录
        attempts = [a for a in attempts if now - a < timedelta(minutes=5)]
        self._failed_attempts[username] = attempts
        # 5分钟内超过5次失败则锁定
        return len(attempts) < 5

    def _record_failed_attempt(self, username: str):
        """记录失败登录"""
        if username not in self._failed_attempts:
            self._failed_attempts[username] = []
        self._failed_attempts[username].append(datetime.now())

    def create_user(self, username: str, password: str, email: Optional[str] = None,
                   role: str = "user", permissions: List[str] = None) -> User:
        """创建用户"""
        if username in self._users:
            raise ValueError(f"User {username} already exists")

        user = User(
            username=username,
            password_hash=self._hash_password(password),
            email=email,
            role=role,
            created_at=datetime.now(),
            permissions=permissions or []
        )
        self._users[username] = user
        self._save_users()
        return user

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """认证用户"""
        if not self._check_rate_limit(username):
            raise HTTPException(status_code=429, detail="Too many failed attempts, please try again later")

        user = self._users.get(username)
        if not user or not user.is_active:
            self._record_failed_attempt(username)
            return None

        if not self._verify_password(password, user.password_hash):
            self._record_failed_attempt(username)
            return None

        user.last_login = datetime.now()
        self._save_users()
        return user

    def create_token(self, user: User) -> Dict[str, str]:
        """创建JWT令牌"""
        exp = datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)
        payload = {
            "username": user.username,
            "role": user.role,
            "permissions": user.permissions,
            "exp": exp
        }
        access_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        # 创建刷新令牌
        refresh_token = secrets.token_urlsafe(32)
        self._refresh_tokens[refresh_token] = user.username

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": JWT_EXPIRE_DAYS * 86400
        }

    def verify_token(self, token: str) -> Optional[TokenData]:
        """验证JWT令牌"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return TokenData(
                username=payload["username"],
                role=payload["role"],
                permissions=payload.get("permissions", []),
                exp=datetime.fromtimestamp(payload["exp"])
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    def refresh_access_token(self, refresh_token: str) -> Optional[Dict[str, str]]:
        """刷新访问令牌"""
        username = self._refresh_tokens.get(refresh_token)
        if not username:
            return None

        user = self._users.get(username)
        if not user or not user.is_active:
            return None

        # 删除旧刷新令牌
        del self._refresh_tokens[refresh_token]

        return self.create_token(user)

    def revoke_token(self, refresh_token: str) -> bool:
        """撤销令牌"""
        if refresh_token in self._refresh_tokens:
            del self._refresh_tokens[refresh_token]
            return True
        return False

    def has_permission(self, token_data: TokenData, permission: str) -> bool:
        """检查权限"""
        if "*" in token_data.permissions:
            return True
        return permission in token_data.permissions

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """修改密码"""
        user = self._users.get(username)
        if not user:
            return False

        if not self._verify_password(old_password, user.password_hash):
            return False

        user.password_hash = self._hash_password(new_password)
        self._save_users()
        return True

    def delete_user(self, username: str) -> bool:
        """删除用户"""
        if username in self._users:
            del self._users[username]
            self._save_users()
            return True
        return False

# 全局认证管理器
auth_manager = AuthManager()

# 依赖：获取当前用户
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> TokenData:
    return auth_manager.verify_token(credentials.credentials)

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "05",
        "name": "Auth",
        "users_count": len(auth_manager._users),
        "timestamp": datetime.now().isoformat()
    }

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/login")
async def login(request: LoginRequest):
    """用户登录"""
    user = auth_manager.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return auth_manager.create_token(user)

class RefreshRequest(BaseModel):
    refresh_token: str

@app.post("/refresh")
async def refresh(request: RefreshRequest):
    """刷新令牌"""
    tokens = auth_manager.refresh_access_token(request.refresh_token)
    if not tokens:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return tokens

@app.post("/logout")
async def logout(request: RefreshRequest):
    """用户登出"""
    success = auth_manager.revoke_token(request.refresh_token)
    return {"success": success}

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

@app.post("/register")
async def register(request: RegisterRequest):
    """用户注册"""
    try:
        user = auth_manager.create_user(
            username=request.username,
            password=request.password,
            email=request.email
        )
        return {"username": user.username, "created_at": user.created_at}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/me")
async def get_me(current_user: TokenData = Depends(get_current_user)):
    """获取当前用户信息"""
    user = auth_manager._users.get(current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "permissions": user.permissions,
        "created_at": user.created_at,
        "last_login": user.last_login
    }

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

@app.post("/change-password")
async def change_password(request: ChangePasswordRequest, current_user: TokenData = Depends(get_current_user)):
    """修改密码"""
    success = auth_manager.change_password(current_user.username, request.old_password, request.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to change password")
    return {"success": True}

@app.get("/verify")
async def verify_token_endpoint(current_user: TokenData = Depends(get_current_user)):
    """验证令牌"""
    return {"valid": True, "username": current_user.username, "role": current_user.role}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
