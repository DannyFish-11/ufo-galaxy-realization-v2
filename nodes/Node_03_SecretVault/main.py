"""
Node 03: SecretVault - 密钥管理
=================================
提供安全的密钥存储、加密解密、密钥轮换功能
"""
import os
import json
from core.atomic_json import atomic_write_json
import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

logger = logging.getLogger("Node_03_SecretVault")

# 可选依赖：优雅降级
try:
    from fastapi import FastAPI, HTTPException, Header
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    logger.warning("fastapi/pydantic 未安装，HTTP API 不可用")

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except BaseException as e:
    HAS_CRYPTO = False
    Fernet = None
    logger.warning(f"cryptography 不可用: {e}，加密功能将降级")

try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    def get_cors_origins():
        return ["*"]

if HAS_FASTAPI:
    app = FastAPI(title="Node 03 - SecretVault", version="2.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
else:
    app = None

# 主密钥解析:严禁每次启动随机生成 —— 加密后的 secrets 会持久化,换了主密钥重启后
# 全部解密抛 InvalidToken,数据永久丢失。优先级:
#   1) 环境变量 SECRETVAULT_MASTER_KEY(生产推荐)
#   2) 持久化的密钥文件 SECRETVAULT_KEY_FILE(默认与 vault 同目录),存在则复用
#   3) 都没有才生成一次,并【落盘】到密钥文件(0600)供后续重启复用
def _is_usable_fernet_key(value: Optional[str]) -> bool:
    """这个值能不能真的构造出 Fernet。

    必须**用之前**验,不能等到 ``Fernet(key)`` 抛。真机踩到过:
    首次启动时 cryptography 还没装,走了 ``secrets.token_urlsafe(32)`` 那条降级分支,
    把一个 **43 字符**的串持久化进了密钥文件(合法的 Fernet key 是 44 字符);
    后来 cryptography 装上了,``Fernet(那个串)`` 直接在**模块导入**处抛
    ValueError,整个节点从此再也导不进来 —— 而报错只说
    "Fernet key must be 32 url-safe base64-encoded bytes",
    完全看不出问题出在哪个来源、也看不出是安装顺序造成的。
    """
    if not value or not (HAS_CRYPTO and Fernet):
        return False
    try:
        Fernet(value.encode())
        return True
    except Exception:  # noqa: BLE001
        return False


def _resolve_master_key() -> Optional[str]:
    """解析主密钥。**拿不到可用的就返回 None**,由调用方降级,不要在导入期崩。"""
    env_key = os.getenv("SECRETVAULT_MASTER_KEY")
    if env_key:
        if _is_usable_fernet_key(env_key):
            return env_key
        # 不静默换一把:运维明确指定了密钥,悄悄换掉会让之后写入的密文
        # 在"改对环境变量之后"反而解不开。报清楚,然后降级。
        logger.error(
            "SECRETVAULT_MASTER_KEY 不是合法的 Fernet 主密钥(需 44 字符 base64url,"
            "可用 python -c \"from cryptography.fernet import Fernet;"
            "print(Fernet.generate_key().decode())\" 生成);本次以**不加密**模式运行"
        )
        return None

    vault_file = os.getenv("SECRETVAULT_FILE", "/tmp/secretvault.json")
    key_file = os.getenv("SECRETVAULT_KEY_FILE", os.path.join(os.path.dirname(vault_file) or ".", ".secretvault.key"))
    try:
        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as f:
                persisted = f.read().strip()
            if persisted:
                if _is_usable_fernet_key(persisted):
                    return persisted
                # 同样不静默覆盖:万一那是一把**曾经合法、现在损坏**的密钥,
                # 覆盖掉就等于把已加密的 secrets 永久锁死。报清楚 + 给出下一步。
                logger.error(
                    "主密钥文件 %s 里的值不是合法 Fernet 主密钥(长度 %d,合法为 44)。"
                    "最常见的成因是**首次启动时 cryptography 未安装**,当时落盘的是"
                    "token_urlsafe 串。确认其中没有需要保留的密文后删除该文件即可自动重建;"
                    "本次以**不加密**模式运行",
                    key_file,
                    len(persisted),
                )
                return None
    except OSError as e:
        logger.warning(f"读取主密钥文件失败({key_file}): {e}")

    if not (HAS_CRYPTO and Fernet):
        # 关键:**不落盘**。以前这里会把 token_urlsafe(32) 写进密钥文件,
        # 于是给"以后装上 cryptography"埋了一颗必炸的雷(见 _is_usable_fernet_key)。
        # 没有加密能力就老老实实降级,不要留下一个看起来像密钥的文件。
        logger.warning("cryptography 未安装,SecretVault 以**不加密**模式运行(不生成也不持久化主密钥)")
        return None

    new_key = Fernet.generate_key().decode()
    try:
        os.makedirs(os.path.dirname(key_file) or ".", exist_ok=True)
        # 先建 0600 空文件再写,避免密钥以宽松权限短暂落盘
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_key)
        logger.warning(
            "SECRETVAULT_MASTER_KEY 未设置,已生成并持久化到 %s(请在生产用环境变量固定主密钥)",
            key_file,
        )
    except OSError as e:
        logger.error(f"主密钥持久化失败({key_file}): {e};本次启动的密钥不会跨重启保留")
    return new_key


MASTER_KEY = _resolve_master_key()

if HAS_FASTAPI:
    class Secret(BaseModel):
        key: str
        value: str
        encrypted: bool = True
        created_at: datetime
        expires_at: Optional[datetime] = None
        metadata: Dict[str, Any] = {}
else:
    Secret = None

class SecretVault:
    def __init__(self):
        self._master_key = MASTER_KEY.encode() if isinstance(MASTER_KEY, str) else MASTER_KEY
        # MASTER_KEY 为 None = 没拿到可用主密钥(原因已在 _resolve_master_key 里报过)。
        # 这里**不能**再直接 Fernet(...) —— 那正是以前在导入期崩掉整个节点的那一行。
        self._fernet = Fernet(self._master_key) if (HAS_CRYPTO and Fernet and self._master_key) else None
        self._secrets: Dict[str, Any] = {}
        self._access_log: List[Dict] = []
        self._load_secrets()
        if self._fernet is None:
            logger.warning("SecretVault 以降级模式运行（无加密支持）")

    def _load_secrets(self):
        """加载持久化的密钥"""
        vault_file = os.getenv("SECRETVAULT_FILE", "/tmp/secretvault.json")
        if os.path.exists(vault_file):
            try:
                with open(vault_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, secret_data in data.get("secrets", {}).items():
                        self._secrets[key] = Secret(**secret_data)
            except Exception as e:
                print(f"Failed to load secrets: {e}")

    def _save_secrets(self):
        """保存密钥到文件"""
        vault_file = os.getenv("SECRETVAULT_FILE", "/tmp/secretvault.json")
        try:
            # 原子写:这是密钥库。写到一半被打断会把整份密钥连同旧值一起废掉
            # (open(w) 先清空再写),而它恰恰是最不该丢的那份数据。
            atomic_write_json(
                vault_file,
                {"secrets": {k: v.dict() for k, v in self._secrets.items()}},
                indent=None,
                default=str,
            )
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
        """加密值(降级模式无 _fernet 时明确报错,避免 NoneType.encrypt 崩溃)"""
        if self._fernet is None:
            raise HTTPException(status_code=503, detail="加密不可用:cryptography 未安装(SecretVault 降级模式)")
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, encrypted_value: str) -> str:
        """解密值(降级模式无 _fernet 时明确报错)"""
        if self._fernet is None:
            raise HTTPException(status_code=503, detail="解密不可用:cryptography 未安装(SecretVault 降级模式)")
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

@app.get("/status")
async def node_status():
    """Node status endpoint."""
    return {
        "node_id": "03",
        "name": "SecretVault",
        "port": 8003,
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
