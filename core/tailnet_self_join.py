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

import json
import logging
import os
import re
import shutil
import socket
import subprocess
from typing import Any, Callable, Dict, List

from core.headscale_join import JoinUnavailable, issue_join_key, join_status

logger = logging.getLogger("Galaxy.TailnetSelfJoin")

Runner = Callable[[List[str]], "subprocess.CompletedProcess[str]"]

#: ``tailscale up`` 最多等多久。加入本身几秒;超过这个时间多半是卡在交互式登录上。
UP_TIMEOUT_S = 60


def autojoin_enabled() -> bool:
    return os.getenv("GALAXY_HEADSCALE_AUTOJOIN", "1").strip().lower() not in ("0", "false", "no", "off")


def _run(cmd: List[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(cmd, capture_output=True, text=True, timeout=UP_TIMEOUT_S)  # noqa: S603


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
