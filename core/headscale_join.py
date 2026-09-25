"""core/headscale_join.py — 配对时给手表发一把"一次性进 tailnet 的钥匙"。

为什么手表需要这个
==================
手表装不了 Tailscale:Wear OS 把 VPN 授权做成了桩,任何 VpnService 类 App 都拿不到
授权(见 deploy/headscale/README.md 第 4 节)。所以手表 App 里嵌了一个用户态的
tailnet 进程(galaxy-wearos 仓的 ``tailnet/``),它自己以一台独立设备的身份加入
tailnet,出门在外也能**直连**这台电脑。

它第一次加入时需要一把 headscale 的预授权密钥(preauth key)。让人去电脑上敲
``headscale preauthkeys create`` 再把一长串字符手输进手表,这件事在小屏上不现实。
而配对这一刻,手表正好在和电脑说话 —— 就在这里把钥匙交过去。

这把钥匙的形状
==============
* **一次性**(reusable=false):用过即废。配对响应要是被截走,最多只能被用一次,
  而那一次正常情况下就是手表自己;
* **短命**(默认 10 分钟):配对完手表立刻就用,用不着更久;
* **非临时节点**(ephemeral=false):手表离线一阵子不该被 headscale 清掉,
  否则每次回来都要重新配对。节点身份存在手表本地,之后重连不再需要钥匙。

失败不连坐
==========
签不出钥匙(没配 headscale、密钥错、headscale 不在线)**不影响配对本身**:
手表照样拿到令牌与候选路径,在家的局域网直连不受影响。只是响应里明确写出
"为什么没有钥匙、怎么修",而不是静默少一个字段 —— 那会表现成"出门连不上",
而没人知道原因在这里。

配置
====
* ``GALAXY_HEADSCALE_URL``      headscale 地址(与电脑自己 ``tailscale up --login-server``
                                 用的是同一个;手表也向它登记)
* ``GALAXY_HEADSCALE_API_KEY``  headscale 的 API 密钥(``headscale apikeys create``)
* ``GALAXY_HEADSCALE_USER``     手表登记到哪个 headscale 用户下,默认 ``galaxy``
                                 (与 deploy/headscale/init.sh 建的一致)
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

#: 钥匙的默认有效期。配对完手表马上就用,不需要更久。
DEFAULT_KEY_TTL_S = 600.0

#: 对 headscale 的单次请求超时。配对请求本身在等这一步,不能拖。
HTTP_TIMEOUT_S = 8.0

HttpJson = Callable[[str, str, Dict[str, str], Optional[Dict[str, Any]]], Dict[str, Any]]


@dataclass(frozen=True)
class JoinGrant:
    """交给手表的那一份:往哪儿登记、凭什么登记、什么时候作废。"""

    control_url: str
    auth_key: str
    expires_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {"control_url": self.control_url, "auth_key": self.auth_key, "expires_at": self.expires_at}


class JoinUnavailable(Exception):
    """签不出钥匙。``reason`` 是稳定的机器码,``how_to_fix`` 是给人看的下一步。"""

    def __init__(self, reason: str, how_to_fix: str):
        super().__init__(reason)
        self.reason = reason
        self.how_to_fix = how_to_fix

    def to_dict(self) -> Dict[str, str]:
        return {"reason": self.reason, "how_to_fix": self.how_to_fix}


def _settings() -> Dict[str, str]:
    return {
        "url": os.getenv("GALAXY_HEADSCALE_URL", "").strip().rstrip("/"),
        "api_key": os.getenv("GALAXY_HEADSCALE_API_KEY", "").strip(),
        "user": os.getenv("GALAXY_HEADSCALE_USER", "").strip() or "galaxy",
    }


def join_status() -> Dict[str, Any]:
    """不发任何请求,只看配置齐不齐 —— 给路径状态盘用。"""
    s = _settings()
    if not s["url"]:
        return {
            "configured": False,
            "reason": "no_headscale_url",
            "how_to_fix": "设 GALAXY_HEADSCALE_URL 为你自建的 headscale 地址(手表出门直连要靠它)",
        }
    if not s["api_key"]:
        return {
            "configured": False,
            "reason": "no_api_key",
            "how_to_fix": "在 headscale 上执行 `headscale apikeys create`,把结果填进 GALAXY_HEADSCALE_API_KEY",
        }
    return {"configured": True, "reason": "", "how_to_fix": "", "control_url": s["url"], "user": s["user"]}


def _default_http_json(
    method: str, url: str, headers: Dict[str, str], body: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 — 地址来自本机配置
        return json.loads(resp.read().decode("utf-8") or "{}")


def _pick(d: Dict[str, Any], *names: str) -> Any:
    """headscale 的 REST 网关不同版本用 camelCase 或 snake_case —— 两种都认。"""
    for n in names:
        if n in d:
            return d[n]
    return None


def issue_join_key(ttl_s: float = DEFAULT_KEY_TTL_S, *, http_json: Optional[HttpJson] = None) -> JoinGrant:
    """向 headscale 要一把一次性、短命的预授权密钥。

    失败一律抛 :class:`JoinUnavailable`,带上可行动的修法。
    """
    status = join_status()
    if not status["configured"]:
        raise JoinUnavailable(status["reason"], status["how_to_fix"])
    s = _settings()
    call = http_json or _default_http_json
    headers = {"Authorization": f"Bearer {s['api_key']}", "Content-Type": "application/json"}

    try:
        users = call("GET", f"{s['url']}/api/v1/user?{urllib.parse.urlencode({'name': s['user']})}", headers, None)
        match = [u for u in (_pick(users, "users") or []) if str(u.get("name")) == s["user"]]
        if not match:
            raise JoinUnavailable(
                "no_such_user",
                f"headscale 上没有用户 {s['user']!r}:执行 `headscale users create {s['user']}`,"
                "或把 GALAXY_HEADSCALE_USER 改成已有的用户",
            )
        # 新版 headscale 按数字 id 指定用户;JSON 里 uint64 以字符串形式出现。
        user_id = str(match[0].get("id", ""))

        expiration = datetime.fromtimestamp(time.time() + ttl_s, tz=timezone.utc)
        created = call(
            "POST",
            f"{s['url']}/api/v1/preauthkey",
            headers,
            {
                "user": user_id,
                "reusable": False,
                "ephemeral": False,
                "expiration": expiration.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
    except JoinUnavailable:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise JoinUnavailable(
                "api_key_rejected",
                "headscale 拒绝了 GALAXY_HEADSCALE_API_KEY(过期或填错):重新 `headscale apikeys create`",
            ) from exc
        raise JoinUnavailable("headscale_error", f"headscale 返回 HTTP {exc.code},看 headscale 日志") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise JoinUnavailable(
            "headscale_unreachable",
            f"连不上 {s['url']}:确认 headscale 在运行、这台电脑能访问它",
        ) from exc
    except (ValueError, TypeError) as exc:
        raise JoinUnavailable("bad_response", "headscale 的返回看不懂,可能版本不兼容") from exc

    key_obj = _pick(created, "preAuthKey", "pre_auth_key") or {}
    key = str(key_obj.get("key", "")).strip()
    if not key:
        raise JoinUnavailable("bad_response", "headscale 回了成功却没有给出密钥,可能版本不兼容")
    return JoinGrant(control_url=s["url"], auth_key=key, expires_at=expiration.timestamp())
