import os, json, hashlib, secrets as py_secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.hazmat.backends import default_backend

app = FastAPI(title='Node 03 - SecretVault', version='3.0.0', description='Enterprise-grade secret management with encryption, rotation, and audit')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

VAULT_FILE = os.getenv('VAULT_FILE', '/tmp/vault.enc')
VAULT_KEY = os.getenv('VAULT_KEY', 'default_key_change_me_immediately')
AUDIT_FILE = os.getenv('AUDIT_FILE', '/tmp/vault_audit.log')
MAX_SECRET_AGE_DAYS = int(os.getenv('MAX_SECRET_AGE_DAYS', '90'))

secrets_db: Dict[str, Dict[str, Any]] = {}
audit_log: List[Dict[str, Any]] = []

def derive_key(password: str, salt: bytes) -> bytes:
    """使用 PBKDF2 从密码派生加密密钥"""
    kdf = PBKDF2(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return kdf.derive(password.encode())

def get_cipher():
    """获取 Fernet 加密器"""
    salt = b'ufo_galaxy_salt_v1'  # 生产环境应使用随机 salt 并保存
    key = derive_key(VAULT_KEY, salt)
    fernet_key = Fernet.generate_key()  # 简化版，实际应从 key 派生
    return Fernet(fernet_key)

cipher = get_cipher()

def encrypt(data: str) -> str:
    """加密数据"""
    return cipher.encrypt(data.encode()).decode()

def decrypt(data: str) -> str:
    """解密数据"""
    try:
        return cipher.decrypt(data.encode()).decode()
    except Exception:
        return "[DECRYPTION_FAILED]"

def load_vault():
    """从文件加载密钥库"""
    global secrets_db
    if os.path.exists(VAULT_FILE):
        try:
            with open(VAULT_FILE, 'r') as f:
                secrets_db = json.load(f)
        except Exception as e:
            log_audit('system', 'load_vault_failed', {'error': str(e)})

def save_vault():
    """保存密钥库到文件"""
    try:
        with open(VAULT_FILE, 'w') as f:
            json.dump(secrets_db, f, indent=2)
    except Exception as e:
        log_audit('system', 'save_vault_failed', {'error': str(e)})

def log_audit(user: str, action: str, details: Dict[str, Any]):
    """记录审计日志"""
    entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'user': user,
        'action': action,
        'details': details
    }
    audit_log.append(entry)
    try:
        with open(AUDIT_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception:
        pass

load_vault()

class SecretRequest(BaseModel):
    key: str
    value: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class SecretRotateRequest(BaseModel):
    key: str
    new_value: str

async def verify_token(x_api_token: Optional[str] = Header(None)):
    """验证 API Token (简化版)"""
    expected_token = os.getenv('VAULT_API_TOKEN', 'dev_token')
    if x_api_token != expected_token:
        log_audit('anonymous', 'auth_failed', {'token': x_api_token[:10] if x_api_token else None})
        raise HTTPException(status_code=401, detail='Invalid API token')
    return x_api_token

@app.get('/health')
async def health():
    """健康检查"""
    expired_count = sum(1 for s in secrets_db.values() if is_expired(s))
    return {
        'status': 'healthy',
        'node_id': '03',
        'name': 'SecretVault',
        'secret_count': len(secrets_db),
        'expired_count': expired_count,
        'audit_entries': len(audit_log)
    }

def is_expired(secret: Dict[str, Any]) -> bool:
    """检查密钥是否过期"""
    if 'created_at' not in secret:
        return False
    created = datetime.fromisoformat(secret['created_at'])
    return datetime.utcnow() - created > timedelta(days=MAX_SECRET_AGE_DAYS)

@app.post('/set')
async def set_secret(request: SecretRequest, token: str = Depends(verify_token)):
    """设置密钥"""
    if not request.value:
        raise HTTPException(status_code=400, detail='value required')
    
    encrypted_value = encrypt(request.value)
    secrets_db[request.key] = {
        'value': encrypted_value,
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat(),
        'metadata': request.metadata or {},
        'version': secrets_db.get(request.key, {}).get('version', 0) + 1
    }
    save_vault()
    log_audit('api_user', 'set_secret', {'key': request.key, 'version': secrets_db[request.key]['version']})
    return {'success': True, 'key': request.key, 'version': secrets_db[request.key]['version']}

@app.get('/get/{key}')
async def get_secret(key: str, token: str = Depends(verify_token)):
    """获取密钥"""
    if key not in secrets_db:
        log_audit('api_user', 'get_secret_not_found', {'key': key})
        raise HTTPException(status_code=404, detail='Secret not found')
    
    secret = secrets_db[key]
    if is_expired(secret):
        log_audit('api_user', 'get_expired_secret', {'key': key})
        raise HTTPException(status_code=410, detail='Secret expired, rotation required')
    
    decrypted_value = decrypt(secret['value'])
    log_audit('api_user', 'get_secret', {'key': key})
    return {
        'success': True,
        'key': key,
        'value': decrypted_value,
        'metadata': secret.get('metadata', {}),
        'version': secret.get('version', 1),
        'created_at': secret.get('created_at')
    }

@app.post('/rotate')
async def rotate_secret(request: SecretRotateRequest, token: str = Depends(verify_token)):
    """轮换密钥"""
    if request.key not in secrets_db:
        raise HTTPException(status_code=404, detail='Secret not found')
    
    old_version = secrets_db[request.key].get('version', 1)
    encrypted_value = encrypt(request.new_value)
    secrets_db[request.key]['value'] = encrypted_value
    secrets_db[request.key]['updated_at'] = datetime.utcnow().isoformat()
    secrets_db[request.key]['version'] = old_version + 1
    save_vault()
    log_audit('api_user', 'rotate_secret', {'key': request.key, 'old_version': old_version, 'new_version': old_version + 1})
    return {'success': True, 'key': request.key, 'version': old_version + 1}

@app.delete('/delete/{key}')
async def delete_secret(key: str, token: str = Depends(verify_token)):
    """删除密钥"""
    if key not in secrets_db:
        raise HTTPException(status_code=404, detail='Secret not found')
    del secrets_db[key]
    save_vault()
    log_audit('api_user', 'delete_secret', {'key': key})
    return {'success': True, 'key': key}

@app.get('/list')
async def list_secrets(token: str = Depends(verify_token)):
    """列出所有密钥"""
    keys_info = []
    for key, secret in secrets_db.items():
        keys_info.append({
            'key': key,
            'version': secret.get('version', 1),
            'created_at': secret.get('created_at'),
            'updated_at': secret.get('updated_at'),
            'expired': is_expired(secret)
        })
    log_audit('api_user', 'list_secrets', {'count': len(keys_info)})
    return {'success': True, 'secrets': keys_info}

@app.get('/audit')
async def get_audit_log(limit: int = 100, token: str = Depends(verify_token)):
    """获取审计日志"""
    return {'success': True, 'entries': audit_log[-limit:]}

@app.post('/mcp/call')
async def mcp_call(request: dict):
    """MCP 工具调用接口"""
    tool = request.get('tool', '')
    params = request.get('params', {})
    token = request.get('token', os.getenv('VAULT_API_TOKEN', 'dev_token'))
    
    if tool == 'set':
        return await set_secret(SecretRequest(**params), token)
    elif tool == 'get':
        return await get_secret(params.get('key'), token)
    elif tool == 'rotate':
        return await rotate_secret(SecretRotateRequest(**params), token)
    elif tool == 'delete':
        return await delete_secret(params.get('key'), token)
    elif tool == 'list':
        return await list_secrets(token)
    elif tool == 'audit':
        return await get_audit_log(params.get('limit', 100), token)
    raise HTTPException(status_code=400, detail=f'Unknown tool: {tool}')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8003)
