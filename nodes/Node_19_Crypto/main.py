"""
Node 19: Crypto - 加密服务节点
================================
提供加密解密、哈希计算、数字签名功能
"""
import os
import base64
import hashlib
import hmac
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 尝试导入cryptography
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, padding, ec
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

app = FastAPI(title="Node 19 - Crypto", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class HashRequest(BaseModel):
    data: str
    algorithm: str = "sha256"  # md5, sha1, sha256, sha512

class HMACRequest(BaseModel):
    data: str
    key: str
    algorithm: str = "sha256"

class EncryptRequest(BaseModel):
    data: str
    key: Optional[str] = None

class SignRequest(BaseModel):
    data: str
    private_key: Optional[str] = None

class VerifyRequest(BaseModel):
    data: str
    signature: str
    public_key: Optional[str] = None

class CryptoManager:
    def __init__(self):
        self._keys = {}

    def hash(self, data: str, algorithm: str = "sha256") -> str:
        """计算哈希"""
        algorithms = {
            "md5": hashlib.md5,
            "sha1": hashlib.sha1,
            "sha256": hashlib.sha256,
            "sha512": hashlib.sha512,
            "sha3_256": hashlib.sha3_256,
            "blake2b": hashlib.blake2b
        }

        if algorithm not in algorithms:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        return algorithms[algorithm](data.encode()).hexdigest()

    def hmac_sign(self, data: str, key: str, algorithm: str = "sha256") -> str:
        """HMAC签名"""
        algorithms = {
            "sha256": hashes.SHA256(),
            "sha512": hashes.SHA512(),
            "sha1": hashes.SHA1()
        }

        if algorithm not in algorithms:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        h = hmac.new(key.encode(), data.encode(), getattr(hashlib, algorithm))
        return h.hexdigest()

    def hmac_verify(self, data: str, signature: str, key: str, algorithm: str = "sha256") -> bool:
        """验证HMAC签名"""
        expected = self.hmac_sign(data, key, algorithm)
        return hmac.compare_digest(expected, signature)

    def generate_key(self) -> str:
        """生成Fernet密钥"""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography not installed")
        return Fernet.generate_key().decode()

    def encrypt(self, data: str, key: Optional[str] = None) -> str:
        """加密数据"""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography not installed")

        key = key or self.generate_key()
        f = Fernet(key.encode())
        encrypted = f.encrypt(data.encode())
        return base64.b64encode(encrypted).decode()

    def decrypt(self, encrypted_data: str, key: str) -> str:
        """解密数据"""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography not installed")

        f = Fernet(key.encode())
        decrypted = f.decrypt(base64.b64decode(encrypted_data))
        return decrypted.decode()

    def generate_rsa_keypair(self) -> Dict[str, str]:
        """生成RSA密钥对"""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography not installed")

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return {
            "private_key": private_pem.decode(),
            "public_key": public_pem.decode()
        }

    def rsa_sign(self, data: str, private_key_pem: str) -> str:
        """RSA签名"""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography not installed")

        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        signature = private_key.sign(
            data.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode()

    def rsa_verify(self, data: str, signature: str, public_key_pem: str) -> bool:
        """验证RSA签名"""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography not installed")

        try:
            public_key = serialization.load_pem_public_key(public_key_pem.encode())
            public_key.verify(
                base64.b64decode(signature),
                data.encode(),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256()
            )
            return True
        except Exception:
            return False

# 全局加密管理器
crypto_manager = CryptoManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "19",
        "name": "Crypto",
        "cryptography_available": CRYPTO_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/hash")
async def hash_data(request: HashRequest):
    """计算哈希"""
    try:
        result = crypto_manager.hash(request.data, request.algorithm)
        return {"hash": result, "algorithm": request.algorithm}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/hmac/sign")
async def hmac_sign(request: HMACRequest):
    """HMAC签名"""
    try:
        result = crypto_manager.hmac_sign(request.data, request.key, request.algorithm)
        return {"signature": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/hmac/verify")
async def hmac_verify(request: VerifyRequest, key: str, algorithm: str = "sha256"):
    """验证HMAC签名"""
    try:
        valid = crypto_manager.hmac_verify(request.data, request.signature, key, algorithm)
        return {"valid": valid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/encrypt")
async def encrypt(request: EncryptRequest):
    """加密数据"""
    try:
        encrypted = crypto_manager.encrypt(request.data, request.key)
        return {"encrypted": encrypted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/decrypt")
async def decrypt(encrypted_data: str, key: str):
    """解密数据"""
    try:
        decrypted = crypto_manager.decrypt(encrypted_data, key)
        return {"decrypted": decrypted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rsa/generate")
async def generate_rsa_keypair():
    """生成RSA密钥对"""
    try:
        keys = crypto_manager.generate_rsa_keypair()
        return keys
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rsa/sign")
async def rsa_sign(request: SignRequest):
    """RSA签名"""
    try:
        signature = crypto_manager.rsa_sign(request.data, request.private_key)
        return {"signature": signature}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rsa/verify")
async def rsa_verify(request: VerifyRequest):
    """验证RSA签名"""
    try:
        valid = crypto_manager.rsa_verify(request.data, request.signature, request.public_key)
        return {"valid": valid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8019)
