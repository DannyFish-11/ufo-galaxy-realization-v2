"""core/tailnet_self_join.py — 这台电脑自己加入 tailnet,不用人去敲 ``tailscale up``。

为什么默认自动加入
==================
智能体和网关都跑在这台电脑上,它是整个 tailnet 的中心:手表出门直连连的就是它的
100.x 地址。配好了 headscale 却忘了让电脑自己加入,结果是"钥匙发了、手表进网了、
却找不到电脑"—— 而这一步本来就不需要人做任何判断。

所以:配了 headscale(``GALAXY_HEADSCALE_URL`` + ``GALAXY_HEADSCALE_API_KEY``)、
这台机器装了 Tailscale 客户端、又还没加入时,网关启动时给自己签一把一次性钥匙,
执行 ``tailscale up --login-server=<headscale> --authkey=<钥匙>``。
``GALAXY_HEADSCALE_AUTOJOIN=0`` 可以关掉。

不替你做的事
============
* **已经登录到别的控制服务器**(比如官方 Tailscale)时不动它 —— 那是你自己的选择,
  改掉它会把这台机器从另一个网里拿出来。如实报 ``joined_elsewhere``。
* **没装 Tailscale 客户端**时不去装 —— 装软件要管理员权限、各平台方式不同。
  报 ``no_tailscale`` 并给出安装地址。
* **权限不够**(Linux 上 ``tailscale up`` 通常要 root)时不提权,给出一条可以直接
  复制去执行的命令(钥匙 10 分钟内有效)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import socket
import subprocess
from typing import Any, Callable, Dict, List, Optional

from core.headscale_join import JoinUnavailable, issue_join_key, join_status

logger = logging.getLogger("Galaxy.TailnetSelfJoin")

Runner = Callable[[List[str]], "subprocess.CompletedProcess[str]"]

#: ``tailscale up`` 最多等多久。加入本身几秒;超过这个时间多半是卡在交互式登录上。
UP_TIMEOUT_S = 60


def autojoin_enabled() -> bool:
    return os.getenv("GALAXY_HEADSCALE_AUTOJOIN", "1").strip().lower() not in ("0", "false", "no", "off")


def _run(cmd: List[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=UP_TIMEOUT_S
    )


def this_hostname() -> str:
    """这台电脑在 tailnet 里的名字。"""
    raw = re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().lower()).strip("-")[:40]
    return f"galaxy-{raw}" if raw else "galaxy-gateway"


def _norm(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def current_state(run: Runner = _run) -> Dict[str, Any]:
    """这台电脑此刻在不在 tailnet 里、在谁的 tailnet 里。不改任何东西。"""
    if shutil.which("tailscale") is None:
        return {"state": "no_tailscale"}
    try:
        st = json.loads(run(["tailscale", "status", "--json"]).stdout or "{}")
    except (ValueError, OSError, subprocess.SubprocessError):
        return {"state": "unknown"}
    backend = str(st.get("BackendState", ""))
    ips = list((st.get("Self") or {}).get("TailscaleIPs") or [])
    control = ""
    try:
        prefs = json.loads(run(["tailscale", "debug", "prefs"]).stdout or "{}")
        control = str(prefs.get("ControlURL", ""))
    except (ValueError, OSError, subprocess.SubprocessError):
        pass
    return {"state": "running" if backend == "Running" else "logged_out", "ips": ips, "control_url": control}


def ensure_joined(*, run: Runner = _run, issue: Callable[..., Any] = issue_join_key) -> Dict[str, Any]:
    """确保这台电脑在自建的 tailnet 里。返回 ``{state, detail, how_to_fix, ...}``。"""
    status = join_status()
    if not status["configured"]:
        return {"state": "not_configured", "detail": "没配 headscale", "how_to_fix": status["how_to_fix"]}
    url = status["control_url"]

    cur = current_state(run)
    if cur["state"] == "no_tailscale":
        return {
            "state": "no_tailscale",
            "detail": "这台电脑没装 Tailscale 客户端",
            "how_to_fix": "安装 Tailscale 客户端:https://tailscale.com/download(装完重启网关即可自动加入)",
        }
    if cur["state"] == "running":
        if _norm(cur.get("control_url", "")) in ("", _norm(url)):
            return {"state": "joined", "detail": "已在自建 tailnet 里", "ips": cur.get("ips", []), "how_to_fix": ""}
        return {
            "state": "joined_elsewhere",
            "detail": f"这台电脑已登录到另一个控制服务器({cur.get('control_url')}),不去动它",
            "how_to_fix": f"确实要换到自建的:tailscale logout 后重启网关,或手动 tailscale up --login-server={url}",
            "ips": cur.get("ips", []),
        }

    try:
        grant = issue()
    except JoinUnavailable as exc:
        return {"state": "failed", "detail": f"签不出加入钥匙:{exc.reason}", "how_to_fix": exc.how_to_fix}

    cmd = [
        "tailscale",
        "up",
        f"--login-server={url}",
        f"--authkey={grant.auth_key}",
        f"--hostname={this_hostname()}",
    ]
    try:
        res = run(cmd)
    except subprocess.TimeoutExpired:
        return {
            "state": "failed",
            "detail": f"tailscale up 超过 {UP_TIMEOUT_S} 秒没有完成",
            "how_to_fix": f"确认这台电脑能访问 {url}",
        }
    if res.returncode == 0:
        after = current_state(run)
        logger.info("这台电脑已加入自建 tailnet:%s", after.get("ips"))
        return {"state": "joined", "detail": "已自动加入自建 tailnet", "ips": after.get("ips", []), "how_to_fix": ""}

    err = (res.stderr or res.stdout or "").strip()
    manual = " ".join(cmd)
    if re.search(r"permission|access denied|operation not permitted|must be root|sudo|elevat", err, re.I):
        return {
            "state": "needs_admin",
            "detail": "tailscale up 需要管理员权限",
            "how_to_fix": f"用管理员身份执行(钥匙 10 分钟内有效,一次性):sudo {manual}",
        }
    return {"state": "failed", "detail": f"tailscale up 失败:{err[:300]}", "how_to_fix": f"手动执行:{manual}"}


async def autojoin_at_startup(
    *, run: Runner = _run, issue: Callable[..., Any] = issue_join_key
) -> Optional[Dict[str, Any]]:
    """启动时让这台电脑自己入网。网关 lifespan 与桌面启动器共用这一处。

    为什么要两个入口都调
    ====================
    桌面版由启动器自己建 FastAPI 应用并挂上 ``/ws/device/{id}``,**不跑**网关的 lifespan
    —— 只写在 lifespan 里的自动入网,桌面版永远等不到。结果是「钥匙发了、手表进网了、
    电脑不在网里」。

    返回 ``ensure_joined`` 的结果;开关关着(``GALAXY_HEADSCALE_AUTOJOIN=0``)返回 ``None``。
    没入成不抛异常、不挡启动,只留一条带处置的告警。
    """
    if not autojoin_enabled():
        return None
    result = await asyncio.to_thread(ensure_joined, run=run, issue=issue)
    if result["state"] not in ("joined", "not_configured"):
        logger.warning("这台电脑没能加入自建 tailnet:%s 处置:%s", result["detail"], result["how_to_fix"])
    return result


def desktop_gate(*, run: Runner = _run) -> Optional[Dict[str, str]]:
    """配对要给设备发 tailnet 钥匙之前:这台电脑自己在不在那张网里。

    在 → 返回 ``None``(放行)。不在 → 返回 ``{reason, how_to_fix}``,形状与
    ``JoinUnavailable.to_dict()`` 相同,配对响应原样放进 ``tailnet_join_unavailable``。

    为什么要拦
    ==========
    钥匙只管「进网」。电脑自己不在网里时,手表拿着钥匙进了一张**空网**:headscale 里多了一个
    节点,手表却出门连不上中心 —— 而配对界面还显示成功。不发钥匙、直接说清「电脑还没入网」,
    比发一把没用的钥匙诚实,也少留一个没人用却能进网的凭证。

    查不出来(``tailscale status`` 没给出可解析的结果)时**放行**:拿不准就不替人拒绝,
    钥匙是一次性、10 分钟内有效的。
    """
    cur = current_state(run)
    state = cur["state"]
    if state == "unknown":
        return None
    url = join_status().get("control_url", "")
    if state == "running":
        if _norm(cur.get("control_url", "")) in ("", _norm(url)):
            return None
        why = f"这台电脑登录在另一个控制服务器({cur.get('control_url')}),不是手表要加入的那张网"
        fix = f"在电脑上换到自建的:tailscale logout 后重启网关,或 tailscale up --login-server={url}"
    elif state == "no_tailscale":
        why = "这台电脑没装 Tailscale 客户端"
        fix = "安装 Tailscale 客户端:https://tailscale.com/download ,装完重启网关即可自动加入"
    else:
        why = "这台电脑还没登录到自建 tailnet"
        fix = "网关启动时会自动加入(GALAXY_HEADSCALE_AUTOJOIN=1);现在可调 POST /api/v1/tailnet/join-this-computer 立刻加入"
    return {"reason": "desktop_not_on_tailnet", "how_to_fix": f"{why}。{fix}"}


def join_command_for(device_kind: str, grant: Any) -> Dict[str, str]:
    """给要加入的另一台设备的说明:能直接执行的命令,或者在 App 里怎么填。"""
    url = grant.control_url
    key = grant.auth_key
    if device_kind in ("android", "ios", "phone"):
        return {
            "how": "app",
            "steps": (
                "打开 Tailscale App → 右上角账户 → 使用自定义控制服务器/Use an alternate server → "
                f"填 {url} → 选择用 auth key 登录 → 粘贴下面的钥匙"
            ),
            "control_url": url,
            "auth_key": key,
        }
    cmd = f"tailscale up --login-server={url} --authkey={key}"
    return {"how": "command", "command": cmd if device_kind == "windows" else f"sudo {cmd}"}
