"""
OAuth 2.0 Device Flow (RFC 8628) 实现
用于无浏览器或输入受限设备（如智能手表）的认证
"""

import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("Node_05_Auth.DeviceFlow")

# 可选依赖：优雅降级
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    logger.warning("httpx 未安装，Device Flow 不可用")


# Google Device Flow 端点
GOOGLE_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DEVICE_SCOPE = "openid email profile"


class DeviceFlowError(Exception):
    """Device Flow 错误基类"""

    def __init__(self, message: str, error_code: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code


class AuthorizationPendingError(DeviceFlowError):
    """用户尚未完成授权，需要继续轮询"""
    pass


class SlowDownError(DeviceFlowError):
    """轮询过快，需要增加间隔"""
    pass


class ExpiredTokenError(DeviceFlowError):
    """device_code 已过期"""
    pass


class DeviceFlowManager:
    """OAuth 2.0 Device Flow 管理器

    RFC 8628 实现流程：
    1. 设备向授权服务器请求 device_code 和 user_code
    2. 设备显示 user_code 和验证 URL 给用户
    3. 用户在另一设备（如手机）上打开验证 URL 并输入 user_code
    4. 设备轮询令牌端点直到用户完成授权
    """

    def __init__(self):
        self._google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        self._google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    async def start_device_auth(self, provider: str) -> Dict[str, Any]:
        """启动设备授权流程

        Args:
            provider: 提供商名称，目前支持 "google"

        Returns:
            {
                "device_code": "设备代码",
                "user_code": "用户输入代码（如 ABCD-EFGH）",
                "verification_uri": "验证 URL",
                "expires_in": 1800,
                "interval": 5
            }
        """
        if not HAS_HTTPX:
            raise RuntimeError("httpx 未安装，无法执行 HTTP 请求")

        provider = provider.lower()
        if provider == "google":
            return await self._start_google_device_auth()
        else:
            raise ValueError(f"Device Flow 不支持的提供商: {provider}")

    async def _start_google_device_auth(self) -> Dict[str, Any]:
        """启动 Google 设备授权"""
        if not self._google_client_id:
            raise DeviceFlowError("Google Device Flow 需要 GOOGLE_CLIENT_ID 环境变量")

        data = {
            "client_id": self._google_client_id,
            "scope": GOOGLE_DEVICE_SCOPE,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(GOOGLE_DEVICE_CODE_URL, data=data)

        if resp.status_code != 200:
            logger.error(f"Google device code 请求失败: {resp.status_code} {resp.text}")
            raise DeviceFlowError(f"Device code request failed: {resp.status_code}")

        result = resp.json()

        # 如果响应中包含 error，说明请求本身失败
        if "error" in result:
            raise DeviceFlowError(
                f"Device code error: {result.get('error_description', result['error'])}"
            )

        logger.debug(f"Device auth started: user_code={result.get('user_code')}")
        return {
            "device_code": result.get("device_code"),
            "user_code": result.get("user_code"),
            "verification_uri": result.get("verification_uri"),
            "verification_uri_complete": result.get("verification_uri_complete"),
            "expires_in": result.get("expires_in", 1800),
            "interval": result.get("interval", 5),
        }

    async def poll_device_token(
        self, provider: str, device_code: str
    ) -> Dict[str, Any]:
        """轮询设备授权结果

        Args:
            provider: 提供商名称
            device_code: start_device_auth 返回的 device_code

        Returns:
            {
                "access_token": "...",
                "refresh_token": "...",
                "id_token": "...",
                "token_type": "Bearer",
                "expires_in": 3600
            }

        Raises:
            AuthorizationPendingError: 用户尚未完成授权，调用方应等待后继续轮询
            SlowDownError: 轮询过快，调用方应增加等待间隔
            ExpiredTokenError: device_code 已过期，需重新启动流程
            DeviceFlowError: 其他错误
        """
        if not HAS_HTTPX:
            raise RuntimeError("httpx 未安装，无法执行 HTTP 请求")

        provider = provider.lower()
        if provider == "google":
            return await self._poll_google_device_token(device_code)
        else:
            raise ValueError(f"Device Flow 不支持的提供商: {provider}")

    async def _poll_google_device_token(self, device_code: str) -> Dict[str, Any]:
        """轮询 Google 设备授权结果"""
        if not self._google_client_id or not self._google_client_secret:
            raise DeviceFlowError(
                "Google Device Flow 需要 GOOGLE_CLIENT_ID 和 GOOGLE_CLIENT_SECRET 环境变量"
            )

        data = {
            "client_id": self._google_client_id,
            "client_secret": self._google_client_secret,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=data)

        result = resp.json()

        # 检查错误响应
        if "error" in result:
            error = result["error"]
            error_description = result.get("error_description", error)

            if error == "authorization_pending":
                # 用户尚未完成授权，继续轮询
                raise AuthorizationPendingError(error_description, error)
            elif error == "slow_down":
                # 轮询过快，需要增加间隔
                raise SlowDownError(error_description, error)
            elif error == "expired_token":
                # device_code 已过期
                raise ExpiredTokenError(error_description, error)
            elif error == "access_denied":
                raise DeviceFlowError("用户拒绝了授权", error)
            else:
                raise DeviceFlowError(f"Token polling error: {error_description}", error)

        logger.debug("Device token 获取成功")
        return {
            "access_token": result.get("access_token"),
            "refresh_token": result.get("refresh_token"),
            "id_token": result.get("id_token"),
            "token_type": result.get("token_type", "Bearer"),
            "expires_in": result.get("expires_in", 3600),
        }

    async def get_user_info(
        self, provider: str, access_token: str
    ) -> Dict[str, str]:
        """通过 access_token 获取用户信息

        Args:
            provider: 提供商名称
            access_token: Device Flow 获取到的 access_token

        Returns:
            统一格式的用户信息字典
        """
        # 复用 oauth_providers 中的实现
        from nodes.Node_05_Auth.oauth_providers import get_oauth_provider, OAuthError

        oauth_provider = get_oauth_provider(provider)
        try:
            user_info = await oauth_provider.get_user_info(access_token)
            return user_info
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            raise DeviceFlowError(f"获取用户信息失败: {e}")

    def is_provider_configured(self, provider: str) -> bool:
        """检查指定提供商是否已配置 Device Flow"""
        provider = provider.lower()
        if provider == "google":
            return bool(self._google_client_id and self._google_client_secret)
        return False
