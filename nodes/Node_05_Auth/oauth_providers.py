"""
OAuth 2.0 提供商实现
支持 Google 和 GitHub OAuth 2.0 Authorization Code Flow
包含 PKCE、state 参数等安全机制
"""

import os
import base64
import hashlib
import secrets
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from urllib.parse import urlencode

logger = logging.getLogger("Node_05_Auth.OAuthProviders")

# 可选依赖：优雅降级
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    logger.warning("httpx 未安装，OAuth 功能不可用")


class OAuthProvider(ABC):
    """OAuth 提供商抽象基类"""

    @abstractmethod
    def get_authorize_url(self, state: str, code_challenge: str) -> str:
        """生成授权 URL"""
        pass

    @abstractmethod
    async def exchange_code(self, code: str, code_verifier: str) -> Dict[str, Any]:
        """用授权码换取 access_token"""
        pass

    @abstractmethod
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """获取用户信息"""
        pass


class PKCEHelper:
    """PKCE (Proof Key for Code Exchange) 辅助类
    
    RFC 7636 实现，防止授权码拦截攻击
    """

    @staticmethod
    def generate_code_verifier() -> str:
        """生成 code_verifier：43-128 字节的随机字符串"""
        verifier = base64.urlsafe_b64encode(
            secrets.token_bytes(64)
        ).decode("ascii").rstrip("=")
        return verifier

    @staticmethod
    def generate_code_challenge(verifier: str) -> str:
        """生成 code_challenge：S256(code_verifier)"""
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return challenge

    @staticmethod
    def generate_state() -> str:
        """生成防 CSRF 的 state 参数"""
        return secrets.token_urlsafe(32)


class GoogleOAuthProvider(OAuthProvider):
    """Google OAuth 2.0 提供商

    支持 OpenID Connect，scope 包含 openid email profile
    """

    # Google OAuth 2.0 端点
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    SCOPE = "openid email profile"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get(
            "GOOGLE_CLIENT_SECRET", ""
        )
        self.redirect_uri = redirect_uri or os.environ.get(
            "OAUTH_REDIRECT_URI", "http://localhost:8765/auth/callback"
        )

        if not self.client_id or not self.client_secret:
            logger.warning("Google OAuth 客户端凭据未配置")

    def get_authorize_url(self, state: str, code_challenge: str) -> str:
        """生成 Google 授权 URL

        Args:
            state: 防 CSRF 的随机字符串
            code_challenge: PKCE code_challenge

        Returns:
            完整的授权 URL，用户需重定向到此地址
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",  # 请求 refresh_token
            "prompt": "consent",  # 确保每次都返回 refresh_token
        }
        param_str = urlencode(params)
        return f"{self.AUTH_URL}?{param_str}"

    async def exchange_code(self, code: str, code_verifier: str) -> Dict[str, Any]:
        """用授权码换取 access_token

        Args:
            code: 授权回调中收到的授权码
            code_verifier: PKCE code_verifier

        Returns:
            令牌响应字典，包含 access_token, refresh_token, id_token, expires_in
        """
        if not HAS_HTTPX:
            raise RuntimeError("httpx 未安装，无法执行 HTTP 请求")

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.TOKEN_URL, data=data)

        if resp.status_code != 200:
            logger.error(f"Google token 交换失败: {resp.status_code} {resp.text}")
            raise OAuthError(f"Token exchange failed: {resp.status_code}")

        token_data = resp.json()
        logger.debug("Google token 交换成功")
        return token_data

    async def get_user_info(self, access_token: str) -> Dict[str, str]:
        """获取 Google 用户信息

        Args:
            access_token: OAuth access_token

        Returns:
            统一格式的用户信息字典:
            {
                "id": "google_用户ID",
                "email": "用户邮箱",
                "name": "用户姓名",
                "picture": "头像URL",
                "provider": "google"
            }
        """
        if not HAS_HTTPX:
            raise RuntimeError("httpx 未安装，无法执行 HTTP 请求")

        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(self.USERINFO_URL, headers=headers)

        if resp.status_code != 200:
            logger.error(f"Google userinfo 获取失败: {resp.status_code}")
            raise OAuthError(f"Failed to get user info: {resp.status_code}")

        data = resp.json()
        return {
            "id": f"google_{data.get('id', '')}",
            "email": data.get("email", ""),
            "name": data.get("name", ""),
            "picture": data.get("picture", ""),
            "provider": "google",
        }


class GitHubOAuthProvider(OAuthProvider):
    """GitHub OAuth 2.0 提供商

    scope 包含 read:user user:email
    """

    # GitHub OAuth 2.0 端点
    AUTH_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    USER_URL = "https://api.github.com/user"
    EMAILS_URL = "https://api.github.com/user/emails"
    SCOPE = "read:user user:email"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("GITHUB_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get(
            "GITHUB_CLIENT_SECRET", ""
        )
        self.redirect_uri = redirect_uri or os.environ.get(
            "OAUTH_REDIRECT_URI", "http://localhost:8765/auth/callback"
        )

        if not self.client_id or not self.client_secret:
            logger.warning("GitHub OAuth 客户端凭据未配置")

    def get_authorize_url(self, state: str, code_challenge: str) -> str:
        """生成 GitHub 授权 URL

        GitHub 目前不支持标准 PKCE S256，但仍传递 code_challenge 以确保兼容性
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.SCOPE,
            "state": state,
        }
        # GitHub 可选支持 PKCE
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        param_str = urlencode(params)
        return f"{self.AUTH_URL}?{param_str}"

    async def exchange_code(self, code: str, code_verifier: str) -> Dict[str, Any]:
        """用授权码换取 access_token

        GitHub 要求 Accept: application/json 来获取 JSON 响应
        """
        if not HAS_HTTPX:
            raise RuntimeError("httpx 未安装，无法执行 HTTP 请求")

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        # 如果 GitHub 应用配置了 PKCE
        if code_verifier:
            data["code_verifier"] = code_verifier

        headers = {"Accept": "application/json"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.TOKEN_URL, data=data, headers=headers)

        if resp.status_code != 200:
            logger.error(f"GitHub token 交换失败: {resp.status_code} {resp.text}")
            raise OAuthError(f"Token exchange failed: {resp.status_code}")

        token_data = resp.json()
        # GitHub 错误响应中可能包含 error 字段
        if "error" in token_data:
            raise OAuthError(f"GitHub error: {token_data['error']}")

        logger.debug("GitHub token 交换成功")
        return token_data

    async def get_user_info(self, access_token: str) -> Dict[str, str]:
        """获取 GitHub 用户信息

        需要额外调用 /user/emails 获取邮箱（因为主端点可能不返回 email）

        Returns:
            统一格式的用户信息字典:
            {
                "id": "github_用户ID",
                "email": "用户邮箱",
                "name": "用户姓名",
                "picture": "头像URL",
                "provider": "github"
            }
        """
        if not HAS_HTTPX:
            raise RuntimeError("httpx 未安装，无法执行 HTTP 请求")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 获取用户基本信息
            resp = await client.get(self.USER_URL, headers=headers)
            if resp.status_code != 200:
                logger.error(f"GitHub user 获取失败: {resp.status_code}")
                raise OAuthError(f"Failed to get user info: {resp.status_code}")
            user_data = resp.json()

            # 获取邮箱列表（GitHub 可能不在主端点返回 email）
            email = user_data.get("email") or ""
            if not email:
                try:
                    resp_emails = await client.get(self.EMAILS_URL, headers=headers)
                    if resp_emails.status_code == 200:
                        emails = resp_emails.json()
                        # 优先取主邮箱、已验证的邮箱
                        for e in emails:
                            if e.get("primary") and e.get("verified"):
                                email = e.get("email", "")
                                break
                        if not email:
                            for e in emails:
                                if e.get("verified"):
                                    email = e.get("email", "")
                                    break
                except Exception as e:
                    logger.warning(f"获取 GitHub 邮箱失败: {e}")

        return {
            "id": f"github_{user_data.get('id', '')}",
            "email": email,
            "name": user_data.get("name") or user_data.get("login", ""),
            "picture": user_data.get("avatar_url", ""),
            "provider": "github",
        }


class OAuthError(Exception):
    """OAuth 操作错误"""
    pass


# 提供商工厂
def get_oauth_provider(provider: str) -> OAuthProvider:
    """获取 OAuth 提供商实例

    Args:
        provider: 提供商名称，支持 "google" 和 "github"

    Returns:
        OAuthProvider 实例

    Raises:
        ValueError: 不支持的提供商
    """
    provider = provider.lower()
    if provider == "google":
        return GoogleOAuthProvider()
    elif provider == "github":
        return GitHubOAuthProvider()
    else:
        raise ValueError(f"不支持的 OAuth 提供商: {provider}")


def get_available_providers() -> list:
    """获取已配置的 OAuth 提供商列表"""
    providers = []

    if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
        providers.append(
            {
                "id": "google",
                "name": "Google",
                "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            }
        )

    if os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET"):
        providers.append(
            {
                "id": "github",
                "name": "GitHub",
                "auth_url": "https://github.com/login/oauth/authorize",
            }
        )

    return providers
