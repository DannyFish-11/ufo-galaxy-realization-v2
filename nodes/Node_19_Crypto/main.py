"""
Node 19: Crypto - 加密和哈希工具
"""
import os, hashlib, hmac, base64, secrets
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

app = FastAPI(title="Node 19 - Crypto", version="3.0.0", description="Cryptography and Hashing Utilities")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class HashRequest(BaseModel):
    data: str
    algorithm: str = "sha256"

class EncryptRequest(BaseModel):
    data: str
    key: Optional[str] = None
    algorithm: str = "fernet"

class HMACRequest(BaseModel):
    data: str
    key: str
    algorithm: str = "sha256"

HASH_ALGORITHMS = ["md5", "sha1", "sha256", "sha384", "sha512", "blake2b", "blake2s"]

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "19",
        "name": "Crypto",
        "supported_hash_algorithms": len(HASH_ALGORITHMS),
        "supported_encryption": ["fernet", "aes256"]
    }

@app.post("/hash")
async def compute_hash(request: HashRequest):
    """计算哈希值"""
    if request.algorithm not in HASH_ALGORITHMS:
        raise HTTPException(status_code=400, detail=f"Unsupported algorithm: {request.algorithm}")
    
    try:
        hash_func = hashlib.new(request.algorithm)
        hash_func.update(request.data.encode())
        return {
            "success": True,
            "algorithm": request.algorithm,
            "hash": hash_func.hexdigest()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/hmac")
async def compute_hmac(request: HMACRequest):
    """计算 HMAC"""
    try:
        h = hmac.new(request.key.encode(), request.data.encode(), request.algorithm)
        return {
            "success": True,
            "algorithm": request.algorithm,
            "hmac": h.hexdigest()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/encrypt")
async def encrypt_data(request: EncryptRequest):
    """加密数据"""
    try:
        if request.algorithm == "fernet":
            key = request.key.encode() if request.key else Fernet.generate_key()
            f = Fernet(key)
            encrypted = f.encrypt(request.data.encode())
            return {
                "success": True,
                "algorithm": "fernet",
                "encrypted": encrypted.decode(),
                "key": key.decode() if not request.key else None
            }
        elif request.algorithm == "aes256":
            key = request.key.encode()[:32] if request.key else secrets.token_bytes(32)
            iv = secrets.token_bytes(16)
            cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
            encryptor = cipher.encryptor()
            encrypted = encryptor.update(request.data.encode()) + encryptor.finalize()
            return {
                "success": True,
                "algorithm": "aes256",
                "encrypted": base64.b64encode(encrypted).decode(),
                "iv": base64.b64encode(iv).decode(),
                "key": base64.b64encode(key).decode() if not request.key else None
            }
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported algorithm: {request.algorithm}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/decrypt")
async def decrypt_data(encrypted: str, key: str, algorithm: str = "fernet", iv: Optional[str] = None):
    """解密数据"""
    try:
        if algorithm == "fernet":
            f = Fernet(key.encode())
            decrypted = f.decrypt(encrypted.encode())
            return {"success": True, "decrypted": decrypted.decode()}
        elif algorithm == "aes256":
            if not iv:
                raise HTTPException(status_code=400, detail="IV required for AES256")
            key_bytes = base64.b64decode(key)
            iv_bytes = base64.b64decode(iv)
            encrypted_bytes = base64.b64decode(encrypted)
            cipher = Cipher(algorithms.AES(key_bytes), modes.CFB(iv_bytes), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted_bytes) + decryptor.finalize()
            return {"success": True, "decrypted": decrypted.decode()}
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported algorithm: {algorithm}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/generate_key")
async def generate_key(algorithm: str = "fernet"):
    """生成加密密钥"""
    if algorithm == "fernet":
        key = Fernet.generate_key()
        return {"success": True, "algorithm": "fernet", "key": key.decode()}
    elif algorithm == "aes256":
        key = secrets.token_bytes(32)
        return {"success": True, "algorithm": "aes256", "key": base64.b64encode(key).decode()}
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported algorithm: {algorithm}")

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "hash": return await compute_hash(HashRequest(**params))
    elif tool == "hmac": return await compute_hmac(HMACRequest(**params))
    elif tool == "encrypt": return await encrypt_data(EncryptRequest(**params))
    elif tool == "decrypt": return await decrypt_data(**params)
    elif tool == "generate_key": return await generate_key(params.get("algorithm", "fernet"))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8019)
