"""
UFO Galaxy - Credential Vault Routes
=======================================

Routes:
  POST   /api/v1/vault/credentials              - 写入凭证
  GET    /api/v1/vault/credentials              - 列出凭证键名
  DELETE /api/v1/vault/credentials/{key_name}  - 删除凭证
  POST   /api/v1/vault/tokens                   - 颁发 token
  POST   /api/v1/vault/fetch                    - 用 token 拉取凭证
  GET    /api/v1/vault/audit                    - 审计日志
  POST   /api/v1/vault/cleanup                  - 清理过期 token
  GET    /api/v1/vault/health                   - Vault 健康状态
  GET    /api/v1/vault/tokens/{token}/info      - Token 元信息
  POST   /api/v1/vault/tokens/validate          - 验证 token
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("UFO-Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create credential vault routes router."""
    router = APIRouter()

    # Rate limiters for sensitive endpoints (in-memory token bucket per client IP)
    try:
        from core.security_middleware import RateLimiter as _RateLimiter
        _vault_fetch_limiter = _RateLimiter(requests_per_minute=30, burst_size=10)
    except Exception:
        _vault_fetch_limiter = None

    @router.post("/api/v1/vault/credentials")
    async def vault_set_credential(request: Request):
        """管理端写入/更新凭证"""
        body = await request.json()
        key_name = body.get("key_name", "")
        value = body.get("value", "")
        if not key_name or not value:
            raise HTTPException(status_code=400, detail="key_name and value are required")
        try:
            from core.credential_vault import get_vault
            get_vault().set_credential(key_name, value)
            return JSONResponse({"success": True, "key_name": key_name})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/vault/credentials")
    async def vault_list_credentials():
        """列出所有凭证键名（不返回值）"""
        try:
            from core.credential_vault import get_vault
            return JSONResponse({"keys": get_vault().list_credential_keys()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/api/v1/vault/credentials/{key_name}")
    async def vault_delete_credential(key_name: str):
        """删除 Vault 内的凭证"""
        try:
            from core.credential_vault import get_vault
            deleted = get_vault().delete_credential(key_name)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Credential '{key_name}' not found")
            return JSONResponse({"success": True, "key_name": key_name})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vault/tokens")
    async def vault_issue_token(request: Request):
        """为 Worker/Device 颁发短期 token"""
        body = await request.json()
        device_id = body.get("device_id", "")
        ttl = int(body.get("ttl", 300))
        scopes = body.get("scopes")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id is required")
        try:
            from core.credential_vault import get_vault
            token = get_vault().issue_token(device_id, ttl=ttl, scopes=scopes)
            return JSONResponse({"success": True, "token": token, "ttl": ttl})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vault/fetch")
    async def vault_fetch_by_token(request: Request):
        """Worker 用 token 拉取凭证"""
        if _vault_fetch_limiter is not None:
            client_ip = request.client.host if request.client else "unknown"
            if not _vault_fetch_limiter.is_allowed(client_ip):
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
        body = await request.json()
        token = body.get("token", "")
        key_name = body.get("key_name", "")
        if not token or not key_name:
            raise HTTPException(status_code=400, detail="token and key_name are required")
        try:
            from core.credential_vault import get_vault
            value = get_vault().get_credential_by_token(token, key_name)
            if value is None:
                raise HTTPException(status_code=403, detail="Invalid token or insufficient scope")
            return JSONResponse({"success": True, "key_name": key_name, "value": value})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/vault/audit")
    async def vault_audit_log(limit: int = 100):
        """获取最近 N 条凭证访问审计记录"""
        try:
            from core.credential_vault import get_vault
            return JSONResponse({"records": get_vault().get_audit_log(limit=limit)})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vault/cleanup")
    async def vault_cleanup_tokens():
        """清理过期 token，返回清理数量"""
        try:
            from core.credential_vault import get_vault
            count = get_vault().cleanup_expired_tokens()
            return JSONResponse({"success": True, "cleaned_up": count})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/vault/health")
    async def vault_health():
        """Vault 健康状态：token 数量、凭证键数量、审计条目数"""
        try:
            from core.credential_vault import get_vault
            return JSONResponse(get_vault().get_health_metrics())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/vault/tokens/{token}/info")
    async def vault_token_info(token: str):
        """获取 token 元信息（device_id、过期时间、scopes 等，不含凭证值）"""
        try:
            from core.credential_vault import get_vault
            info = get_vault().get_token_info(token)
            if info is None:
                raise HTTPException(status_code=404, detail="Token not found or expired")
            return JSONResponse(info)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/vault/tokens/validate")
    async def vault_validate_token(request: Request):
        """验证 token 有效性，返回 valid 和 device_id"""
        body = await request.json()
        token = body.get("token", "")
        if not token:
            raise HTTPException(status_code=400, detail="token is required")
        try:
            from core.credential_vault import get_vault
            valid, device_id = get_vault().validate_token(token)
            return JSONResponse({"valid": valid, "device_id": device_id})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router
