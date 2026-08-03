"""
OAuth 2.0 FastAPI 路由
提供 Google/GitHub OAuth 登录和 Device Flow 端点

端点列表：
- GET  /auth/oauth/providers          — 列出支持的提供商
- GET  /auth/oauth/{provider}/authorize — 跳转 OAuth 授权页
- GET  /auth/oauth/callback            — OAuth 回调处理
- POST /auth/oauth/device/start        — 启动设备授权
- POST /auth/oauth/device/poll         — 轮询设备令牌
- GET  /auth/oauth/me                  — 获取当前 OAuth 用户信息
- POST /auth/oauth/refresh             — 刷新 Token
- POST /auth/oauth/logout              — 撤销 Token
"""

import hashlib
import os
import secrets
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger("Node_05_Auth.OAuthRoutes")

# 可选依赖：优雅降级
try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    logger.warning("httpx 未安装，OAuth 路由不可用")

try:
    import jwt

    HAS_JWT = True
except ImportError:
    HAS_JWT = False

try:
    from fastapi import FastAPI, HTTPException, Depends, Header, Request
    from fastapi.responses import RedirectResponse
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from pydantic import BaseModel

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    logger.warning("fastapi/pydantic 未安装，OAuth 路由不可用")

# 导入 OAuth 提供商和 Device Flow
from nodes.Node_05_Auth.oauth_providers import (
    get_oauth_provider,
    get_available_providers,
    GitHubOAuthProvider,
    PKCEHelper,
    OAuthError,
)
from nodes.Node_05_Auth.device_flow import (
    DeviceFlowManager,
    DeviceFlowError,
    AuthorizationPendingError,
    SlowDownError,
    ExpiredTokenError,
)

# JWT 配置（与 main.py 保持一致）
JWT_SECRET = os.getenv("AUTH_JWT_SECRET", secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.getenv("AUTH_JWT_EXPIRE_DAYS", "7"))
JWT_REFRESH_EXPIRE_DAYS = int(os.getenv("AUTH_JWT_REFRESH_EXPIRE_DAYS", "30"))

# 内存存储（生产环境建议用 Redis）
# key: state, value: {"provider": str, "code_verifier": str, "created_at": datetime}
_state_store: Dict[str, Dict[str, Any]] = {}

# Device Flow 会话存储
# key: device_code, value: {"provider": str, "created_at": datetime}
_device_sessions: Dict[str, Dict[str, Any]] = {}

# OAuth 刷新令牌存储
# key: refresh_token, value: {"oauth_user_id": str, "provider": str}
_oauth_refresh_tokens: Dict[str, Dict[str, Any]] = {}

# OAuth 用户信息缓存
# key: oauth_user_id, value: {"email": str, "name": str, "picture": str, "provider": str}
_oauth_users: Dict[str, Dict[str, Any]] = {}


# ============ Pydantic 请求模型 ============


class DeviceStartRequest(BaseModel):
    provider: str = "google"


class DevicePollRequest(BaseModel):
    provider: str
    device_code: str


class GoogleIdTokenRequest(BaseModel):
    """Android 原生 Google Sign-In 拿到的 ID Token。

    与 ``/auth/oauth/callback`` 那条**不是同一种凭证**:那边收的是授权码 + PKCE
    verifier(服务端重定向流),这里收的是客户端 SDK 直接产出的 ID Token。
    Android 用的是原生账号选择器,它给不出授权码 —— 详见下面路由的说明。
    """

    id_token: str


class GitHubCodeRequest(BaseModel):
    """Android 自己走完 GitHub 授权后拿到的授权码。

    ``redirect_uri`` 必须回传:GitHub 换取令牌时会校验它与授权时用的那个一致,
    而客户端用的是自己的回调地址,与服务端 ``OAUTH_REDIRECT_URI`` 不是同一个。
    不带上它,换取会以 redirect_uri_mismatch 失败。
    """

    code: str
    redirect_uri: Optional[str] = None


class OAuthRefreshRequest(BaseModel):
    refresh_token: str


class OAuthLogoutRequest(BaseModel):
    refresh_token: str


# ============ 辅助函数 ============

#: Google 的 JWKS 端点。**本地校验**用的公钥从这里取。
#:
#: 为什么不用 tokeninfo 端点:Google 自己的文档把 ``/tokeninfo`` 定位为调试用途,
#: 生产环境要求取公钥在本地验签 —— 每次登录都往 Google 打一次同步 HTTP,既加一跳
#: 延迟,也把登录的可用性绑在对方那个调试端点上。
_GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"

#: ``iss`` 的两种合法写法,Google 两种都会签发。
_GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

_jwks_client = None


def _google_jwks_client():
    """惰性构造并复用 JWKS 客户端。

    PyJWT 的 ``PyJWKClient`` 自带密钥集缓存与 ``lifespan`` 轮转(默认 300 秒),
    正好对上 Google "公钥会定期轮转、按 Cache-Control 决定何时重取" 的要求。
    用它而不是新引一个 ``google-auth`` 依赖:本仓有供应链哈希闸,加一个依赖要
    连带重算 requirements.hash.txt,而 pyjwt + cryptography 已经在依赖里,
    能力也完全够 —— 验签、aud、iss、exp 四项一个不少。
    """
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(_GOOGLE_JWKS_URI)
    return _jwks_client


def _google_audiences() -> set:
    """本后端认可的 Google 客户端 ID。

    Android 原生登录用的 client id 与 Web 的通常**不是同一个**,所以这里收一个
    逗号分隔的列表,而不是单个值 —— 只配一个的话,手机端登录会以 aud 不匹配被拒,
    而那个错误看起来像"token 无效",很难指向配置。
    """
    raw = ",".join(
        filter(
            None,
            (os.getenv("GOOGLE_CLIENT_ID", ""), os.getenv("GOOGLE_ANDROID_CLIENT_ID", "")),
        )
    )
    return {c.strip() for c in raw.split(",") if c.strip()}


def _verify_google_id_token(token: str) -> Dict[str, str]:
    """本地校验 Google ID Token,返回规范化的用户信息。

    四项校验缺一不可(Google 文档明列):
      1. 签名 —— 用 JWKS 里对应 kid 的公钥,并**锁定 RS256**(不锁算法会给
         alg=none / HS256 混淆攻击留口子);
      2. ``aud`` —— 必须是本后端自己的客户端 ID;
      3. ``iss`` —— accounts.google.com 或带 https 前缀那个;
      4. ``exp`` —— 由 PyJWT 默认校验。

    "客户端发来的就信"是这条链路最典型的死法:ID Token 是个任何人都能构造的
    JSON,不验签就等于让调用方自称是谁就是谁。
    """
    audiences = _google_audiences()
    if not audiences:
        # 没配就明说,而不是放行或含糊报 401 —— 后者会让人去查 token,
        # 而问题其实在部署配置上。
        raise HTTPException(
            status_code=503,
            detail="服务端未配置 GOOGLE_CLIENT_ID / GOOGLE_ANDROID_CLIENT_ID,无法校验 ID Token",
        )
    try:
        signing_key = _google_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=list(audiences),
            options={"require": ["exp", "aud", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("Google ID Token 校验失败: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail=f"ID Token 校验失败: {type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 — 取公钥可能因网络失败
        logger.error("取 Google 公钥失败: %s", exc)
        raise HTTPException(status_code=503, detail="无法获取 Google 公钥,稍后重试")

    # iss 单独判:PyJWT 的 issuer 参数只接受单个字符串,而 Google 两种写法都会签发。
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise HTTPException(status_code=401, detail=f"ID Token 的 iss 不是 Google: {claims.get('iss')!r}")

    if not claims.get("email"):
        raise HTTPException(status_code=400, detail="ID Token 里没有 email(登录需要 email scope)")

    return {
        "id": str(claims["sub"]),
        "email": claims["email"],
        "name": claims.get("name") or claims.get("email", ""),
        "picture": claims.get("picture", ""),
        "provider": "google",
    }


def _log_subject(oauth_user: Dict[str, str]) -> str:
    """把用户身份压成一个**可对账、但不可还原**的短标识,用于日志。

    为什么不直接打邮箱
    ------------------
    登录日志会被采集、转发、长期留存,而邮箱是直接可用的个人标识 —— 一条
    ``logger.info`` 就把它复制进了一条谁也说不清边界的管道。CodeQL 的
    ``py/clear-text-logging-sensitive-data`` 报的就是这个(它把凭证下游的值
    整体视作敏感,所以点名的是邮箱那一行)。

    但日志里完全不留标识也不行 —— 排查"这个用户反复登录失败"时需要能把几条
    日志串起来。折中是打 ``provider:sha256(provider:id)[:12]``:同一个人始终是
    同一个串(可对账),而从串反推不回邮箱或用户 ID(不可还原)。

    与本仓 ``scripts/verify_provider_apis.py`` 的规矩一致:那边是"绝不打印密钥值,
    连长度都不打",这里是"绝不打印可直接识别到人的字段"。
    """
    provider = str(oauth_user.get("provider") or "?")
    raw = f"{provider}:{oauth_user.get('id') or oauth_user.get('email') or ''}"
    return f"{provider}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _generate_jwt_token(oauth_user: Dict[str, str]) -> Dict[str, Any]:
    """为 OAuth 用户生成 JWT 令牌

    Args:
        oauth_user: {"id": str, "email": str, "name": str, "picture": str, "provider": str}

    Returns:
        {"access_token": str, "refresh_token": str, "token_type": "bearer", "expires_in": int}
    """
    now = datetime.utcnow()
    exp = now + timedelta(days=JWT_EXPIRE_DAYS)

    payload = {
        "sub": oauth_user["id"],
        "email": oauth_user["email"],
        "name": oauth_user["name"],
        "picture": oauth_user.get("picture", ""),
        "provider": oauth_user["provider"],
        "type": "oauth_access",
        "jti": secrets.token_urlsafe(16),  # JWT ID，确保每次生成的 token 唯一
        "iat": now,
        "exp": exp,
    }

    access_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    # 创建刷新令牌
    refresh_token = secrets.token_urlsafe(32)
    refresh_exp = now + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)
    _oauth_refresh_tokens[refresh_token] = {
        "oauth_user_id": oauth_user["id"],
        "provider": oauth_user["provider"],
        "exp": refresh_exp,
    }

    # 缓存用户信息
    _oauth_users[oauth_user["id"]] = {
        "id": oauth_user["id"],
        "email": oauth_user["email"],
        "name": oauth_user["name"],
        "picture": oauth_user.get("picture", ""),
        "provider": oauth_user["provider"],
    }

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": JWT_EXPIRE_DAYS * 86400,
        "user": {
            "id": oauth_user["id"],
            "email": oauth_user["email"],
            "name": oauth_user["name"],
            "picture": oauth_user.get("picture", ""),
            "provider": oauth_user["provider"],
        },
    }


def _verify_oauth_token(token: str) -> Optional[Dict[str, Any]]:
    """验证 OAuth JWT 令牌

    Args:
        token: JWT access_token

    Returns:
        解码后的 payload，验证失败返回 None
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "oauth_access":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _cleanup_expired_states():
    """清理过期的 state 记录（5分钟前创建的）"""
    now = datetime.utcnow()
    expired = [k for k, v in _state_store.items() if now - v.get("created_at", now) > timedelta(minutes=5)]
    for k in expired:
        del _state_store[k]


def _cleanup_expired_tokens():
    """清理过期的刷新令牌"""
    now = datetime.utcnow()
    expired = [k for k, v in _oauth_refresh_tokens.items() if v.get("exp", now) < now]
    for k in expired:
        del _oauth_refresh_tokens[k]


# ============ FastAPI 依赖 ============

security = HTTPBearer()


async def get_current_oauth_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """依赖：获取当前 OAuth 用户"""
    payload = _verify_oauth_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    user = _oauth_users.get(user_id)
    if not user:
        # 从 token payload 重建用户信息
        user = {
            "id": user_id,
            "email": payload.get("email", ""),
            "name": payload.get("name", ""),
            "picture": payload.get("picture", ""),
            "provider": payload.get("provider", ""),
        }
        _oauth_users[user_id] = user

    return user


# ============ 路由注册函数 ============


def register_oauth_routes(app: FastAPI):
    """注册 OAuth 路由到 FastAPI 应用

    Args:
        app: FastAPI 应用实例
    """
    if not HAS_FASTAPI:
        logger.warning("FastAPI 不可用，跳过 OAuth 路由注册")
        return
    if not HAS_HTTPX:
        logger.warning("httpx 不可用，跳过 OAuth 路由注册")
        return
    if not HAS_JWT:
        logger.warning("PyJWT 不可用，跳过 OAuth 路由注册")
        return

    device_flow_manager = DeviceFlowManager()

    # ---- 1. 列出支持的提供商 ----
    @app.get("/auth/oauth/providers")
    async def list_providers():
        """列出已配置的 OAuth 提供商"""
        providers = get_available_providers()
        return {
            "providers": providers,
            "device_flow_available": {
                "google": device_flow_manager.is_provider_configured("google"),
            },
        }

    # ---- 2. 跳转 OAuth 授权页 ----
    @app.get("/auth/oauth/{provider}/authorize")
    async def oauth_authorize(provider: str):
        """重定向用户到 OAuth 提供商的授权页面

        自动生成 PKCE 参数和 state 参数，参数存储在内存中供回调验证
        """
        provider = provider.lower()

        # 验证提供商
        try:
            oauth_provider = get_oauth_provider(provider)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

        # 生成 PKCE 参数
        code_verifier = PKCEHelper.generate_code_verifier()
        code_challenge = PKCEHelper.generate_code_challenge(code_verifier)
        state = PKCEHelper.generate_state()

        # 存储 state 与 code_verifier 的映射（用于回调验证）
        _cleanup_expired_states()
        _state_store[state] = {
            "provider": provider,
            "code_verifier": code_verifier,
            "created_at": datetime.utcnow(),
        }

        # 生成授权 URL
        authorize_url = oauth_provider.get_authorize_url(state, code_challenge)

        logger.debug(f"OAuth authorize: provider={provider}, state={state[:8]}...")
        return RedirectResponse(url=authorize_url)

    # ---- 3. OAuth 回调处理 ----
    @app.get("/auth/oauth/callback")
    async def oauth_callback(
        request: Request,
        code: str = "",
        state: str = "",
        error: str = "",
        error_description: str = "",
    ):
        """OAuth 回调处理

        流程：
        1. 验证 state 防止 CSRF 攻击
        2. 使用授权码 + code_verifier 换取 access_token
        3. 获取用户信息
        4. 生成 JWT Token 返回
        """
        # 处理 OAuth 错误
        if error:
            logger.error(f"OAuth callback error: {error} - {error_description}")
            raise HTTPException(
                status_code=400,
                detail=f"OAuth error: {error}: {error_description}",
            )

        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing code or state parameter")

        # 验证 state 防止 CSRF
        state_data = _state_store.pop(state, None)
        if not state_data:
            logger.warning(f"无效的 state 参数: {state[:8]}...")
            raise HTTPException(status_code=400, detail="Invalid or expired state parameter")

        provider = state_data["provider"]
        code_verifier = state_data["code_verifier"]

        try:
            oauth_provider = get_oauth_provider(provider)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

        try:
            # 用授权码换取 access_token
            token_response = await oauth_provider.exchange_code(code, code_verifier)
            access_token = token_response.get("access_token")
            if not access_token:
                raise HTTPException(status_code=400, detail="No access_token in response")

            # 获取用户信息
            user_info = await oauth_provider.get_user_info(access_token)
            if not user_info.get("email"):
                logger.warning(
                    "OAuth 用户未提供邮箱 subject=%s 拿到的字段=%s",
                    _log_subject({**user_info, "provider": provider}),
                    sorted(user_info.keys()),
                )
                raise HTTPException(status_code=400, detail="Email not provided by OAuth provider")

        except HTTPException:
            raise
        except OAuthError as e:
            logger.error(f"OAuth 令牌交换失败: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"OAuth 回调处理异常: {e}")
            raise HTTPException(status_code=500, detail="OAuth processing failed")

        # 生成 JWT Token
        token_data = _generate_jwt_token(user_info)
        logger.info("OAuth 登录成功(%s/callback): %s", provider, _log_subject({**user_info, "provider": provider}))

        return token_data

    # ---- 3b. 客户端已完成授权,把凭证交给后端换 JWT ----
    #
    # 这两条与上面的 authorize/callback 是**同一件事的两种做法**,都留着是有意的:
    #
    #   authorize + callback   服务端重定向流。浏览器把用户导去授权页,授权码回到
    #                          服务端的 callback,服务端换令牌。适合 Web。
    #   下面这两条              客户端交互流。App 用原生 SDK 完成授权,把结果交给后端。
    #
    # 为什么必须有后一种:Android 用的是原生 Google Sign-In(账号选择器),它产出的是
    # **ID Token 而不是授权码** —— 拿不到授权码,就走不了 PKCE 那条 callback 流。
    # 硬要统一成重定向流,等于把原生账号选择器换成跳浏览器,是体验倒退。
    #
    # 两条路径最终都汇到同一个 _generate_jwt_token(),所以"登录之后是什么"只有一份实现。

    @app.post("/auth/oauth/google")
    async def oauth_google_id_token(body: GoogleIdTokenRequest):
        """用 Android 原生登录拿到的 ID Token 换取本系统 JWT。

        校验是**本地**做的(JWKS 验签 + aud + iss + exp),不打 Google 的 tokeninfo。
        """
        oauth_user = _verify_google_id_token(body.id_token)
        token_data = _generate_jwt_token(oauth_user)
        logger.info("OAuth 登录成功(google/id_token): %s", _log_subject(oauth_user))
        return token_data

    @app.post("/auth/oauth/github")
    async def oauth_github_code(body: GitHubCodeRequest):
        """用客户端自己走完授权拿到的 GitHub 授权码换取本系统 JWT。"""
        if not body.code:
            raise HTTPException(status_code=400, detail="缺少 code")
        try:
            # 用调用方给的 redirect_uri 构造 provider:GitHub 换取令牌时会校验它与
            # 授权时用的一致,而客户端用的是它自己的回调地址,与服务端默认的那个不同。
            # 走 get_oauth_provider() 会拿到服务端默认值,换取必然 redirect_uri_mismatch。
            provider = GitHubOAuthProvider(redirect_uri=body.redirect_uri or None)
            # code_verifier 传空:客户端流没有 PKCE,而 exchange_code 里对空值是
            # "有就带上、没有就不带",不需要为此改动提供商实现。
            token_response = await provider.exchange_code(body.code, "")
            access_token = token_response.get("access_token")
            if not access_token:
                raise HTTPException(status_code=400, detail="GitHub 未返回 access_token")
            user_info = await provider.get_user_info(access_token)
        except HTTPException:
            raise
        except OAuthError as exc:
            logger.error("GitHub 令牌交换失败: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("GitHub 登录处理异常: %s", exc)
            raise HTTPException(status_code=500, detail="GitHub 登录处理失败")

        if not user_info.get("email"):
            raise HTTPException(status_code=400, detail="GitHub 未提供 email(需要 user:email scope)")

        token_data = _generate_jwt_token(user_info)
        logger.info("OAuth 登录成功(github/code): %s", _log_subject(user_info))
        return token_data

    # ---- 4. 启动设备授权 ----
    @app.post("/auth/oauth/device/start")
    async def device_start(request_data: DeviceStartRequest):
        """启动 OAuth 2.0 Device Flow

        适用于无浏览器设备（如智能手表）
        """
        provider = request_data.provider.lower()

        if not device_flow_manager.is_provider_configured(provider):
            raise HTTPException(
                status_code=400,
                detail=f"Device Flow for {provider} is not configured",
            )

        try:
            result = await device_flow_manager.start_device_auth(provider)
            # 存储 device_code 与 provider 的映射
            _device_sessions[result["device_code"]] = {
                "provider": provider,
                "created_at": datetime.utcnow(),
            }
            return result
        except DeviceFlowError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Device auth start failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to start device auth")

    # ---- 5. 轮询设备令牌 ----
    @app.post("/auth/oauth/device/poll")
    async def device_poll(request_data: DevicePollRequest):
        """轮询设备授权结果

        调用方需循环调用此端点直到成功或失败
        authorization_pending 错误码表示用户尚未完成授权
        """
        provider = request_data.provider.lower()
        device_code = request_data.device_code

        try:
            token_data = await device_flow_manager.poll_device_token(provider, device_code)
            access_token = token_data.get("access_token")

            # 获取用户信息
            if access_token:
                try:
                    oauth_provider = get_oauth_provider(provider)
                    user_info = await oauth_provider.get_user_info(access_token)

                    # 清理 device session
                    _device_sessions.pop(device_code, None)

                    # 生成 JWT Token
                    jwt_token = _generate_jwt_token(user_info)
                    return {
                        "status": "success",
                        **jwt_token,
                    }
                except Exception as e:
                    logger.warning(f"获取用户信息失败: {e}")
                    # 仍返回 token 让用户可以后续获取信息
                    return {
                        "status": "success",
                        **token_data,
                    }
            else:
                return {"status": "pending"}

        except AuthorizationPendingError:
            raise HTTPException(
                status_code=428,  # Precondition Required
                detail="authorization_pending",
            )
        except SlowDownError:
            raise HTTPException(
                status_code=429,  # Too Many Requests
                detail="slow_down",
                headers={"Retry-After": "10"},
            )
        except ExpiredTokenError:
            _device_sessions.pop(device_code, None)
            raise HTTPException(status_code=410, detail="expired_token")
        except DeviceFlowError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Device poll failed: {e}")
            raise HTTPException(status_code=500, detail="Token polling failed")

    # ---- 6. 获取当前 OAuth 用户信息 ----
    @app.get("/auth/oauth/me")
    async def oauth_me(current_user: Dict[str, Any] = Depends(get_current_oauth_user)):
        """获取当前 OAuth 用户信息（需要 Bearer Token）"""
        return {
            "id": current_user["id"],
            "email": current_user["email"],
            "name": current_user["name"],
            "picture": current_user.get("picture", ""),
            "provider": current_user.get("provider", ""),
        }

    # ---- 7. 刷新 Token ----
    @app.post("/auth/oauth/refresh")
    async def oauth_refresh(request_data: OAuthRefreshRequest):
        """刷新 OAuth JWT Token"""
        refresh_token = request_data.refresh_token

        token_data = _oauth_refresh_tokens.get(refresh_token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        # 检查是否过期
        if token_data.get("exp") and token_data["exp"] < datetime.utcnow():
            del _oauth_refresh_tokens[refresh_token]
            raise HTTPException(status_code=401, detail="Refresh token expired")

        oauth_user_id = token_data.get("oauth_user_id")
        user = _oauth_users.get(oauth_user_id)

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # 删除旧刷新令牌
        del _oauth_refresh_tokens[refresh_token]

        # 生成新令牌
        new_tokens = _generate_jwt_token(user)
        return new_tokens

    # ---- 8. 撤销 Token ----
    @app.post("/auth/oauth/logout")
    async def oauth_logout(request_data: OAuthLogoutRequest):
        """撤销 OAuth 刷新令牌"""
        refresh_token = request_data.refresh_token

        _cleanup_expired_tokens()

        if refresh_token in _oauth_refresh_tokens:
            del _oauth_refresh_tokens[refresh_token]
            return {"success": True}

        return {"success": False, "detail": "Token not found"}

    # ---- 9. 健康检查扩展 ----
    @app.get("/auth/oauth/health")
    async def oauth_health():
        """OAuth 子系统健康检查"""
        providers = get_available_providers()
        return {
            "status": "healthy" if providers else "no_providers_configured",
            "providers_configured": [p["id"] for p in providers],
            "device_flow_available": {
                "google": device_flow_manager.is_provider_configured("google"),
            },
        }

    logger.info("OAuth 路由已注册")
