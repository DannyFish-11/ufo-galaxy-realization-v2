"""
Node 03: SecretVault - 密钥管理
=================================
提供安全的密钥存储、加密解密、密钥轮换功能
"""
import os
import json
import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

app = FastAPI(title="Node 03 - SecretVault", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 主密钥（从环境变量读取）
MASTER_KEY = os.getenv("SECRETVAULT_MASTER_KEY", Fernet.generate_key().decode())

class Secret(BaseModel):
    key: str
    value: str
    encrypted: bool = True
    created_at: datetime
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}

class SecretVault:
    def __init__(self):
        self._master_key = MASTER_KEY.encode() if isinstance(MASTER_KEY, str) else MASTER_KEY
        self._fernet = Fernet(self._master_key)
        self._secrets: Dict[str, Secret] = {}
        self._access_log: List[Dict] = []
        self._load_secrets()

    def _load_secrets(self):
        """加载持久化的密钥"""
        vault_file = os.getenv("SECRETVAULT_FILE", "/tmp/secretvault.json")
        if os.path.exists(vault_file):
            try:
                with open(vault_file, 'r') as f:
                    data = json.load(f)
                    for key, secret_data in data.get("secrets", {}).items():
                        self._secrets[key] = Secret(**secret_data)
            except Exception as e:
                print(f"Failed to load secrets: {e}")

    def _save_secrets(self):
        """保存密钥到文件"""
        vault_file = os.getenv("SECRETVAULT_FILE", "/tmp/secretvault.json")
        try:
            with open(vault_file, 'w') as f:
                json.dump({"secrets": {k: v.dict() for k, v in self._secrets.items()}}, f, default=str)
        except Exception as e:
            print(f"Failed to save secrets: {e}")

    def _log_access(self, action: str, key: str, success: bool):
        """记录访问日志"""
        self._access_log.append({
            "action": action,
            "key": key,
            "success": success,
            "timestamp": datetime.now().isoformat(),
            "ip": "internal"
        })
        # 只保留最近1000条日志
        self._access_log = self._access_log[-1000:]

    def encrypt(self, value: str) -> str:
        """加密值"""
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, encrypted_value: str) -> str:
        """解密值"""
        return self._fernet.decrypt(encrypted_value.encode()).decode()

    def set_secret(self, key: str, value: str, encrypted: bool = True, 
                   expires_in_days: Optional[int] = None,
                   metadata: Dict[str, Any] = None) -> Secret:
        """设置密钥"""
        if encrypted:
            value = self.encrypt(value)

        expires_at = None
        if expires_in_days:
            expires_at = datetime.now() + timedelta(days=expires_in_days)

        secret = Secret(
            key=key,
            value=value,
            encrypted=encrypted,
            created_at=datetime.now(),
            expires_at=expires_at,
            metadata=metadata or {}
        )
        self._secrets[key] = secret
        self._save_secrets()
        self._log_access("set", key, True)
        return secret

    def get_secret(self, key: str, decrypt: bool = True) -> Optional[str]:
        """获取密钥"""
        secret = self._secrets.get(key)
        if not secret:
            self._log_access("get", key, False)
            return None

        # 检查是否过期
        if secret.expires_at and datetime.now() > secret.expires_at:
            self._log_access("get", key, False)
            return None

        self._log_access("get", key, True)

        if secret.encrypted and decrypt:
            return self.decrypt(secret.value)
        return secret.value

    def delete_secret(self, key: str) -> bool:
        """删除密钥"""
        if key in self._secrets:
            del self._secrets[key]
            self._save_secrets()
            self._log_access("delete", key, True)
            return True
        self._log_access("delete", key, False)
        return False

    def list_secrets(self) -> List[str]:
        """列出所有密钥名称"""
        return list(self._secrets.keys())

    def rotate_key(self, key: str) -> bool:
        """轮换密钥（重新加密）"""
        secret = self._secrets.get(key)
        if not secret or not secret.encrypted:
            return False

        try:
            decrypted = self.decrypt(secret.value)
            secret.value = self.encrypt(decrypted)
            secret.created_at = datetime.now()
            self._save_secrets()
            self._log_access("rotate", key, True)
            return True
        except Exception:
            self._log_access("rotate", key, False)
            return False

    def generate_password(self, length: int = 32) -> str:
        """生成随机密码"""
        return secrets.token_urlsafe(length)

    def hash_value(self, value: str, algorithm: str = "sha256") -> str:
        """哈希值"""
        if algorithm == "sha256":
            return hashlib.sha256(value.encode()).hexdigest()
        elif algorithm == "sha512":
            return hashlib.sha512(value.encode()).hexdigest()
        elif algorithm == "md5":
            return hashlib.md5(value.encode()).hexdigest()
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

    def verify_hash(self, value: str, hash_value: str, algorithm: str = "sha256") -> bool:
        """验证哈希"""
        return self.hash_value(value, algorithm) == hash_value

# 全局密钥库
vault = SecretVault()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "03",
        "name": "SecretVault",
        "secrets_count": len(vault._secrets),
        "timestamp": datetime.now().isoformat()
    }

class SetSecretRequest(BaseModel):
    key: str
    value: str
    encrypted: bool = True
    expires_in_days: Optional[int] = None
    metadata: Dict[str, Any] = {}

@app.post("/secrets")
async def set_secret(request: SetSecretRequest):
    """设置密钥"""
    secret = vault.set_secret(
        key=request.key,
        value=request.value,
        encrypted=request.encrypted,
        expires_in_days=request.expires_in_days,
        metadata=request.metadata
    )
    return {"key": secret.key, "created_at": secret.created_at, "expires_at": secret.expires_at}

@app.get("/secrets/{key}")
async def get_secret(key: str, decrypt: bool = True):
    """获取密钥"""
    value = vault.get_secret(key, decrypt=decrypt)
    if value is None:
        raise HTTPException(status_code=404, detail="Secret not found or expired")
    return {"key": key, "value": value if decrypt else "***encrypted***"}

@app.delete("/secrets/{key}")
async def delete_secret(key: str):
    """删除密钥"""
    success = vault.delete_secret(key)
    if not success:
        raise HTTPException(status_code=404, detail="Secret not found")
    return {"success": True}

@app.get("/secrets")
async def list_secrets():
    """列出所有密钥"""
    return {"secrets": vault.list_secrets()}

@app.post("/secrets/{key}/rotate")
async def rotate_secret(key: str):
    """轮换密钥"""
    success = vault.rotate_key(key)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot rotate secret")
    return {"success": True}

class GeneratePasswordRequest(BaseModel):
    length: int = 32

@app.post("/generate-password")
async def generate_password(request: GeneratePasswordRequest):
    """生成随机密码"""
    return {"password": vault.generate_password(request.length)}

class HashRequest(BaseModel):
    value: str
    algorithm: str = "sha256"

@app.post("/hash")
async def hash_value(request: HashRequest):
    """哈希值"""
    return {"hash": vault.hash_value(request.value, request.algorithm)}

class VerifyHashRequest(BaseModel):
    value: str
    hash: str
    algorithm: str = "sha256"

@app.post("/verify-hash")
async def verify_hash(request: VerifyHashRequest):
    """验证哈希"""
    return {"valid": vault.verify_hash(request.value, request.hash, request.algorithm)}

@app.post("/encrypt")
async def encrypt_value(data: Dict[str, str]):
    """加密任意值"""
    value = data.get("value", "")
    return {"encrypted": vault.encrypt(value)}

@app.post("/decrypt")
async def decrypt_value(data: Dict[str, str]):
    """解密值"""
    encrypted = data.get("encrypted", "")
    return {"value": vault.decrypt(encrypted)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
