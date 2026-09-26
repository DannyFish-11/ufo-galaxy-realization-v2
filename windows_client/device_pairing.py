"""windows_client/device_pairing.py — 这台电脑作为「相对主体」接入主脑:配对、凭据、续期、进网。

和手机/手表走同一条配对链(``core/routes/pairing.py``),不另起一套:

    主脑(智能体)          devices__invite kind=laptop → 一次性配对码 + 一条命令
    这台电脑              python windows_client/windows_aip_client.py --pair 123456 --gateway http://主脑地址:端口
                          ├─ POST /api/v1/pair/claim   → 能力令牌 + 按可达性排好的连接地址 + tailnet 钥匙
                          ├─ 有 tailscale 且没登录任何网 → 用那把钥匙自己进自建 tailnet(带出门也连得回来)
                          └─ 凭据存本机;之后直接 python windows_aip_client.py 就行
    每次连上              device_register 带上令牌 → 规范入口核验(令牌签给的就是本机 id)
    令牌快过期            POST /api/v1/pair/renew 凭旧令牌换新 —— 常驻设备不用每天重配

它不是第二个大脑:没有三态、没有模型,只是主脑的手和眼(执行都走
``WindowsExecutionArbiter``)。要不要做某件事,由主脑那边的权限门和确认决定。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("windows-aip-client.pairing")

#: 离过期还剩这么久就换新令牌。
RENEW_AHEAD_S = 6 * 3600.0
#: 向主脑申请的令牌有效期(与 /api/v1/pair/claim 的默认一致)。
TOKEN_TTL_S = 24 * 3600.0


class PairingError(Exception):
    """配对/续期失败。``how_to_fix`` 是给人看的下一步。"""

    def __init__(self, message: str, how_to_fix: str = ""):
        super().__init__(message)
        self.how_to_fix = how_to_fix


def state_path() -> str:
    """凭据文件位置。``GALAXY_DEVICE_STATE`` 可覆盖(测试、多开)。"""
    override = os.environ.get("GALAXY_DEVICE_STATE", "").strip()
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".galaxy")
    return os.path.join(base, "Galaxy", "device.json") if os.environ.get("APPDATA") else os.path.join(base, "device.json")


def load_state(path: Optional[str] = None) -> Dict[str, Any]:
    try:
        with open(path or state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: Dict[str, Any], path: Optional[str] = None) -> None:
    p = path or state_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)  # 令牌是这台电脑进主脑的凭证
    except OSError:
        pass


def stable_device_id(state: Dict[str, Any]) -> str:
    """这台电脑的设备 id:第一次生成后就固定下来。

    此前每次启动都拼一个随机后缀,重启一次设备列表里就多一台「新电脑」,
    而令牌签给的是旧 id,重启后必然被入口拒掉。
    """
    did = str(state.get("device_id") or "").strip()
    if not did:
        host = "".join(ch for ch in socket.gethostname().lower() if ch.isalnum() or ch == "-")[:24] or "pc"
        did = f"windows_{host}_{uuid.uuid4().hex[:6]}"
        state["device_id"] = did
    return did


def detect_device_type() -> str:
    """有电池的算笔记本。探不到就按台式机报(不会影响能力,只影响怎么称呼它)。"""
    try:
        import psutil  # type: ignore

        if psutil.sensors_battery() is not None:
            return "windows_laptop"
    except Exception:  # noqa: BLE001
        pass
    return "windows_desktop"


# ── HTTP ──────────────────────────────────────────────────────────────────────


def _post_json(url: str, body: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 地址由用户给出
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            data = {}
        data.setdefault("success", False)
        data.setdefault("error", f"HTTP {exc.code}")
        data["_status"] = exc.code
        return data
    except (urllib.error.URLError, OSError) as exc:
        raise PairingError(
            f"连不上主脑 {url}: {exc}",
            "确认 --gateway 写的是主脑电脑的地址和端口,两台机器在同一个网络里(或都在自建 tailnet 里)",
        ) from exc


def _base(gateway: str) -> str:
    g = (gateway or "").strip().rstrip("/")
    if not g:
        raise PairingError("没有主脑地址", "加上 --gateway http://主脑地址:端口")
    if "://" not in g:
        g = "http://" + g
    return g.replace("ws://", "http://", 1).replace("wss://", "https://", 1)


# ── 配对 / 续期 ────────────────────────────────────────────────────────────────


def pair(
    code: str,
    gateway: str,
    state: Dict[str, Any],
    *,
    name: str = "",
    device_type: str = "",
    capabilities: Optional[List[str]] = None,
    post: Callable[[str, Dict[str, Any]], Dict[str, Any]] = _post_json,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """凭主脑给的一次性配对码配对。成功后把凭据写进 *state* 并返回 claim 的响应。"""
    base = _base(gateway)
    did = stable_device_id(state)
    body = {
        "code": str(code).strip(),
        "device_id": did,
        "name": name or socket.gethostname(),
        "device_type": device_type or detect_device_type(),
        "capabilities": list(capabilities or []),
        "note": "windows_aip_client",
        "token_ttl_s": TOKEN_TTL_S,
    }
    resp = post(f"{base}/api/v1/pair/claim", body)
    if not resp.get("success"):
        raise PairingError(
            f"配对失败:{resp.get('error') or resp}",
            "让主脑重新给一个配对码(10 分钟内有效,只能用一次)",
        )
    token = resp.get("capability_token")
    if not token:
        raise PairingError(
            "配对成功但主脑没有签发令牌(这台设备可能被设成了拒绝)",
            "在主脑那边把这台设备的信任级别调高后重新配对",
        )
    t = float(now if now is not None else time.time())
    state.update(
        {
            "gateway": base,
            "token": token,
            "token_expires_at": t + TOKEN_TTL_S,
            "candidates": [c for c in (resp.get("candidates") or []) if isinstance(c, dict) and c.get("url")],
            "gateway_device_id": resp.get("gateway_device_id") or "",
            "name": body["name"],
            "device_type": body["device_type"],
            "paired_at": t,
        }
    )
    return resp


def renew_if_due(
    state: Dict[str, Any],
    *,
    post: Callable[[str, Dict[str, Any]], Dict[str, Any]] = _post_json,
    now: Optional[float] = None,
) -> bool:
    """令牌快过期就换新。换了返回 True。旧令牌已失效(过期/被移除)时抛 PairingError。"""
    t = float(now if now is not None else time.time())
    if not state.get("token") or t < float(state.get("token_expires_at") or 0) - RENEW_AHEAD_S:
        return False
    resp = post(
        f"{_base(state.get('gateway', ''))}/api/v1/pair/renew",
        {"device_id": state.get("device_id", ""), "token": state["token"], "token_ttl_s": TOKEN_TTL_S},
    )
    if not resp.get("success") or not resp.get("capability_token"):
        raise PairingError(
            f"令牌续期被拒:{resp.get('error') or resp}",
            "这台电脑需要重新配对:让主脑给一个新的配对码,再运行 --pair",
        )
    state["token"] = resp["capability_token"]
    state["token_expires_at"] = t + TOKEN_TTL_S
    return True


def connect_urls(state: Dict[str, Any], fallback_host: str, fallback_port: int, device_id: str) -> List[str]:
    """按可达性排好的连接地址:配对时主脑给的在前,命令行给的兜底。"""
    urls: List[str] = []
    for c in sorted(state.get("candidates") or [], key=lambda c: int(c.get("priority") or 99)):
        u = str(c.get("url") or "")
        # 名片里的地址按领取方 id 拼好的是网关自己的 id;统一换成本机 id
        if "/ws/device/" in u:
            u = u.split("/ws/device/", 1)[0] + f"/ws/device/{device_id}"
        if u and u not in urls:
            urls.append(u)
    gw = str(state.get("gateway") or "")
    if gw:
        u = gw.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + f"/ws/device/{device_id}"
        if u not in urls:
            urls.append(u)
    if fallback_host:
        u = f"ws://{fallback_host}:{fallback_port}/ws/device/{device_id}"
        if u not in urls:
            urls.append(u)
    return urls


# ── 进自建 tailnet ─────────────────────────────────────────────────────────────


def join_tailnet(
    grant: Optional[Dict[str, Any]],
    device_id: str,
    *,
    run: Callable[[List[str]], "subprocess.CompletedProcess[str]"] = None,  # type: ignore[assignment]
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Dict[str, Any]:
    """用配对拿到的钥匙把本机加入自建 tailnet。

    已经登录在某个 tailnet 上的不动它(可能是用户自己的网);没装 tailscale 就说去哪装;
    权限不够(Windows 上常见)就给一条可以直接粘贴执行的命令。
    """
    if not grant or not grant.get("auth_key") or not grant.get("control_url"):
        return {"state": "no_grant"}
    run = run or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=60))  # noqa: S603
    exe = which("tailscale")
    cmd_text = f"tailscale up --login-server={grant['control_url']} --authkey={grant['auth_key']} --hostname={device_id}"
    if not exe:
        return {
            "state": "no_tailscale",
            "how_to_fix": "装上 Tailscale(https://tailscale.com/download/windows)后再运行一次 --pair,或手动执行:"
            + cmd_text,
        }
    try:
        st = run([exe, "status", "--json"])
        backend = json.loads(st.stdout or "{}").get("BackendState", "") if st.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        backend = ""
    if backend == "Running":
        return {"state": "already_in_a_tailnet"}
    r = run([exe, "up", f"--login-server={grant['control_url']}", f"--authkey={grant['auth_key']}", f"--hostname={device_id}"])
    if r.returncode == 0:
        return {"state": "joined"}
    return {
        "state": "failed",
        "detail": (r.stderr or r.stdout or "").strip()[:300],
        "how_to_fix": "用管理员身份打开终端执行:" + cmd_text,
    }


def os_label() -> str:
    try:
        return f"{platform.system()} {platform.release()}"
    except Exception:  # noqa: BLE001
        return "unknown"
