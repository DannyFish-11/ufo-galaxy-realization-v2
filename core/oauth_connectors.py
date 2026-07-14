"""
core/oauth_connectors.py — 自建 OAuth 连接器(阶段2b,A 方案)
=================================================================

面板节点名单台上「连接 Gmail / GitHub / Notion…」的后端。**全本地、不依赖第三方**:
你在各服务自建一次 OAuth App(拿到 client_id/secret 填进来),之后用户点「连接」
就是标准一键授权,token 存本机(runtime/oauth_connectors.json,已 gitignore)。

覆盖审计出的连接器节点:
  github  → Node_11 GitHub, Node_106 GitHubFlow
  google  → Node_16 Gmail, Node_123 Calendar(同一 Google OAuth,合并 scope)
  slack   → Node_10 Slack
  notion  → Node_21 Notion
  discord → Node_26 Discord

流程:
  1. 首次:POST /credentials 存该服务的 client_id/secret(你自建 App 得到)。
  2. 授权:GET /authorize → 302 跳到服务授权页(带 redirect_uri + state)。
  3. 回调:GET /callback?code=... → 用 code 换 access_token,存本机。
  4. 断开:POST /disconnect 删 token。

redirect_uri 固定为 http://localhost:{port}/api/v1/connectors/{service}/callback —
你在创建 OAuth App 时把它登记为回调地址即可。全程容错。
"""

from __future__ import annotations

import json
import logging
import os
import secrets as _secrets
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.OAuthConnectors")

_ROOT = Path(__file__).resolve().parent.parent
_STORE = _ROOT / "runtime" / "oauth_connectors.json"

# 每个服务的 OAuth 端点 + scope + 自建 App 的文档链接(前端首次没配时提示用)。
CONNECTORS: Dict[str, Dict[str, Any]] = {
    "github": {
        "label": "GitHub",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scope": "repo read:user user:email",
        "create_app_url": "https://github.com/settings/developers",
        "create_hint": "New OAuth App;Authorization callback URL 填下方 redirect_uri",
    },
    "google": {
        "label": "Google (Gmail / Calendar)",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/calendar",
        "extra_authorize": {"access_type": "offline", "prompt": "consent"},
        "create_app_url": "https://console.cloud.google.com/apis/credentials",
        "create_hint": "创建 OAuth client ID(Web);已获授权重定向 URI 填下方 redirect_uri",
    },
    "slack": {
        "label": "Slack",
        "authorize_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scope": "chat:write channels:read users:read",
        "create_app_url": "https://api.slack.com/apps",
        "create_hint": "Create New App → OAuth & Permissions;Redirect URLs 填下方 redirect_uri",
    },
    "notion": {
        "label": "Notion",
        "authorize_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scope": "",
        "extra_authorize": {"owner": "user"},
        "create_app_url": "https://www.notion.so/my-integrations",
        "create_hint": "New integration(Public);Redirect URI 填下方 redirect_uri",
        # Notion 的 token 端点跟其余四家不一样:不接受 body 里带 client_id/secret,
        # 要求 HTTP Basic(client_id:client_secret)+ JSON body。按标准 OAuth2
        # form-encoded 发会被判无效凭证,换 token 必然失败——见 handle_callback()。
        "token_auth": "basic_json",
    },
    "discord": {
        "label": "Discord",
        "authorize_url": "https://discord.com/oauth2/authorize",
        "token_url": "https://discord.com/api/oauth2/token",
        "scope": "identify guilds",
        "create_app_url": "https://discord.com/developers/applications",
        "create_hint": "New Application → OAuth2;Redirects 填下方 redirect_uri",
    },
}

# 服务 → 用户信息接口(拿真实账号名用于面板展示;为空表示账号名直接从 token
# 响应本身取,见 _extract_account())。github/discord 的 token 响应里不含
# 用户信息，需要额外一次 Bearer 请求。
_USERINFO_URL: Dict[str, str] = {
    "github": "https://api.github.com/user",
    "google": "https://www.googleapis.com/oauth2/v3/userinfo",
    "discord": "https://discord.com/api/users/@me",
}


def _extract_account(service: str, tok: Dict[str, Any], userinfo: Optional[Dict[str, Any]]) -> Optional[str]:
    """从 token 响应本身或额外的 userinfo 请求里提取一个人类可读账号名。

    每家 OAuth 服务的字段形状都不一样(核实过官方文档/真实响应体):
      - github:  token 响应无用户信息 → userinfo 是 /user，取 login
      - google:  token 响应无用户信息 → userinfo 是 /userinfo，取 email
      - slack:   token 响应自带 team.name(+ authed_user.id)，无需额外请求
      - notion:  token 响应自带 workspace_name，无需额外请求
      - discord: token 响应无用户信息 → userinfo 是 /users/@me，取 global_name/username
    取不到就返回 None(不影响连接成功——账号名只是展示用)。
    """
    try:
        if service == "github" and userinfo:
            return userinfo.get("login")
        if service == "google" and userinfo:
            return userinfo.get("email")
        if service == "slack":
            team = tok.get("team") or {}
            return team.get("name") or (tok.get("authed_user") or {}).get("id")
        if service == "notion":
            return tok.get("workspace_name")
        if service == "discord" and userinfo:
            name = userinfo.get("global_name") or userinfo.get("username")
            discrim = userinfo.get("discriminator")
            if name and discrim and discrim != "0":
                return f"{name}#{discrim}"
            return name
    except Exception:  # noqa: BLE001
        pass
    return None


# 节点编号 → 连接器服务(供前端在节点卡上显示「连接」)。
NODE_TO_SERVICE: Dict[int, str] = {
    11: "github",
    106: "github",
    16: "google",
    123: "google",
    10: "slack",
    21: "notion",
    26: "discord",
}


def _load() -> Dict[str, Any]:
    try:
        if _STORE.exists():
            return json.loads(_STORE.read_text("utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save(data: Dict[str, Any]) -> None:
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("写 oauth_connectors.json 失败: %s", exc)


def _base_url() -> str:
    port = os.environ.get("GATEWAY_PORT") or os.environ.get("PORT") or "9000"
    return f"http://localhost:{port}"


def redirect_uri(service: str) -> str:
    return f"{_base_url()}/api/v1/connectors/{service}/callback"


def set_credentials(service: str, client_id: str, client_secret: str) -> Dict[str, Any]:
    if service not in CONNECTORS:
        return {"ok": False, "error": f"未知连接器: {service}"}
    data = _load()
    entry = data.get(service, {})
    entry["client_id"] = (client_id or "").strip()
    entry["client_secret"] = (client_secret or "").strip()
    data[service] = entry
    _save(data)
    return {"ok": True, "service": service}


def _status(service: str, entry: Dict[str, Any]) -> str:
    if not entry.get("client_id") or not entry.get("client_secret"):
        return "needs_config"
    if entry.get("access_token"):
        return "connected"
    return "disconnected"


def list_connectors() -> Dict[str, Any]:
    data = _load()
    out: List[Dict[str, Any]] = []
    for svc, meta in CONNECTORS.items():
        entry = data.get(svc, {})
        out.append(
            {
                "service": svc,
                "label": meta["label"],
                "status": _status(svc, entry),
                "account": entry.get("account"),
                "redirect_uri": redirect_uri(svc),
                "create_app_url": meta.get("create_app_url"),
                "create_hint": meta.get("create_hint"),
                "has_client_id": bool(entry.get("client_id")),
            }
        )
    return {"connectors": out, "node_to_service": NODE_TO_SERVICE}


def build_authorize_url(service: str) -> Tuple[Optional[str], Optional[str]]:
    """返回 (authorize_url, error)。生成带 state 的授权链接并暂存 state 防 CSRF。"""
    meta = CONNECTORS.get(service)
    if not meta:
        return None, f"未知连接器: {service}"
    data = _load()
    entry = data.get(service, {})
    if not entry.get("client_id"):
        return None, "needs_config"
    state = _secrets.token_urlsafe(24)
    entry["_state"] = state
    data[service] = entry
    _save(data)
    from urllib.parse import urlencode

    params = {
        "client_id": entry["client_id"],
        "redirect_uri": redirect_uri(service),
        "response_type": "code",
        "state": state,
    }
    if meta.get("scope"):
        params["scope"] = meta["scope"]
    params.update(meta.get("extra_authorize", {}))
    return f"{meta['authorize_url']}?{urlencode(params)}", None


async def handle_callback(service: str, code: str, state: str) -> Dict[str, Any]:
    """用 code 换 token 并存本机。校验 state。"""
    meta = CONNECTORS.get(service)
    if not meta:
        return {"ok": False, "error": f"未知连接器: {service}"}
    data = _load()
    entry = data.get(service, {})
    if not code:
        return {"ok": False, "error": "缺少 code"}
    if state and entry.get("_state") and state != entry["_state"]:
        return {"ok": False, "error": "state 校验失败(可能是过期或 CSRF)"}
    try:
        import httpx

        headers = {"Accept": "application/json"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            if meta.get("token_auth") == "basic_json":
                # Notion: 凭证走 HTTP Basic,body 是 JSON(不是 form)——见 CONNECTORS 里的注释。
                r = await client.post(
                    meta["token_url"],
                    json={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri(service),
                    },
                    headers=headers,
                    auth=httpx.BasicAuth(entry.get("client_id", ""), entry.get("client_secret", "")),
                )
            else:
                payload = {
                    "client_id": entry.get("client_id"),
                    "client_secret": entry.get("client_secret"),
                    "code": code,
                    "redirect_uri": redirect_uri(service),
                    "grant_type": "authorization_code",
                }
                r = await client.post(meta["token_url"], data=payload, headers=headers)
            tok = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

            access = tok.get("access_token")
            if not access:
                return {"ok": False, "error": f"换取 token 失败: {tok.get('error') or r.text[:120]}"}
            entry["access_token"] = access
            if tok.get("refresh_token"):
                entry["refresh_token"] = tok["refresh_token"]
            entry.pop("_state", None)

            # 拿真实账号名(不同服务字段不同,见 _extract_account 的文档注释)。
            userinfo: Optional[Dict[str, Any]] = None
            userinfo_url = _USERINFO_URL.get(service)
            if userinfo_url:
                try:
                    ur = await client.get(
                        userinfo_url,
                        headers={
                            "Authorization": f"Bearer {access}",
                            "Accept": "application/json",
                            # GitHub 要求带 User-Agent，否则部分端点拒绝匿名 UA。
                            "User-Agent": "Galaxy-OAuth-Connector",
                        },
                    )
                    if ur.status_code == 200:
                        userinfo = ur.json()
                    else:
                        logger.debug("获取 %s 用户信息失败(status=%s)——不影响连接本身", service, ur.status_code)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("获取 %s 用户信息异常(非致命): %s", service, exc)
            entry["account"] = _extract_account(service, tok, userinfo)

        data[service] = entry
        _save(data)
        logger.info("OAuth 连接成功: %s (账号=%s)", service, entry.get("account") or "未知")
        return {"ok": True, "service": service, "account": entry.get("account")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def disconnect(service: str) -> Dict[str, Any]:
    data = _load()
    if service in data:
        for k in ("access_token", "refresh_token", "account", "_state"):
            data[service].pop(k, None)
        _save(data)
    return {"ok": True, "service": service}
