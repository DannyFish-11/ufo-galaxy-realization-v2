#!/usr/bin/env python3
"""真实环境里验节点 HTTP 面的三道门 —— 不是 TestClient,是真起进程、走真实 TCP。

## 为什么需要这个

TestClient 走进程内 ASGI transport:不经过真实 socket、不跑 uvicorn 的 HTTP 解析、
不跑 lifespan。中间件在两种方式下都会执行,但"容器起来之后到底行不行"只有真跑才算数。

这个脚本做的事:用 uvicorn 把节点起在真实端口上,用真实 HTTP 客户端打它,
逐条核对契约(见 docs/NODE_HTTP_SECURITY_CONTRACT.md)。

## WebSocket 面也在核对之内

HTTP 中间件看不见 WS 握手(scope 类型不同),所以 WS 是**另一层**、要单独验。
仓里唯一带 WS 端点的节点是 ``Node_95_WebRTC_Receiver``,而它 import 就要 aiortc ——
这台机器上装不上时,脚本会明确打出"未验",**不会算成通过**。

不管 Node_95 能不能起,``--ws`` 这一段都会用同一个 ``install_node_auth`` 起一个
最小 app 验一遍机制本身:没有它,"WS 这层到底有没有生效"在缺依赖的机器上就无人回答。

## 用法

    python3 scripts/live_node_security_check.py                  # 默认那几个敏感节点
    python3 scripts/live_node_security_check.py Node_06_Filesystem

依赖 uvicorn 与 httpx。缺了会直接说,而不是假装跳过。
"""

from __future__ import annotations

import argparse
import importlib
import os
import socket
import subprocess
import sys
import tempfile
import time
from typing import List, Tuple

TOKEN = "live-check-token"

#: (节点模块, 一条会动手的路由, 方法, 请求体)
DEFAULT_TARGETS: List[Tuple[str, str, str, dict]] = [
    ("nodes.Node_03_SecretVault.main", "/status", "GET", {}),
    ("nodes.Node_92_AutoControl.main", "/click", "POST", {"x": 1, "y": 1}),
    ("nodes.Node_45_DesktopAuto.main", "/click", "POST", {"x": 1, "y": 1}),
    ("nodes.Node_122_Shell.main", "/execute", "POST", {"command": "echo hi"}),
    ("nodes.Node_00_StateMachine.main", "/status", "GET", {}),
]

_SERVE = """
import importlib, sys, uvicorn
m = importlib.import_module(sys.argv[1])
app = getattr(m, "app", None) or getattr(m, "_health_app", None)
if app is None:
    sys.exit(2)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
"""


#: 带 WS 端点的节点。值是握手路径(已填好占位符)。
WS_TARGETS: List[Tuple[str, str]] = [
    ("nodes.Node_95_WebRTC_Receiver.main", "/signaling/live-check-device"),
]

#: 机制自检用的最小 app —— 除 install_node_auth 外什么都没装。
_SERVE_WS_PROBE = """
import sys, uvicorn
sys.path.insert(0, %r)
from fastapi import FastAPI, WebSocket
from nodes.common.node_auth import install_node_auth
app = FastAPI()
install_node_auth(app, "LiveCheckProbe")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.websocket("/signaling/{device_id}")
async def signaling(websocket: WebSocket, device_id: str):
    await websocket.accept()
    await websocket.send_text("accepted-" + device_id)
    await websocket.close()

uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
"""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait(client, url: str, timeout: float = 45.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            client.get(url, timeout=2)
            return True
        except Exception:  # noqa: BLE001 — 还没起来
            time.sleep(0.5)
    return False


def check(module: str, path: str, method: str, body: dict) -> List[str]:
    """把一个节点真起起来,逐条核对。返回失败项(空=全过)。"""
    import httpx

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, GALAXY_API_TOKEN=TOKEN, PYTHONPATH=os.getcwd())
    env.pop("GALAXY_NODE_AUTH", None)
    proc = subprocess.Popen(
        [sys.executable, "-c", _SERVE, module, str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    fails: List[str] = []
    try:
        with httpx.Client() as c:
            if not _wait(c, f"{base}/health"):
                err = (proc.stderr.read() or b"").decode()[-400:] if proc.stderr else ""
                return [f"{module}: 起不来 / {err}"]

            # 1) 存活探针必须免认证 —— compose 的 healthcheck 是裸 curl
            if c.get(f"{base}/health").status_code != 200:
                fails.append(f"{module}: /health 不该要认证(容器会反复重启)")

            call = lambda h: c.request(method, f"{base}{path}", json=body or None, headers=h, timeout=25)
            # 2) 无令牌必须 401
            if call({}).status_code != 401:
                fails.append(f"{module}: {path} 无令牌没被拒")
            # 3) 错令牌必须 401
            if call({"Authorization": "Bearer wrong"}).status_code != 401:
                fails.append(f"{module}: {path} 错令牌没被拒")
            # 4) 对令牌必须放行(不断言 200:节点在本机可能缺 pyautogui/adb,
            #    真正执行会失败 —— 断言的是**没被门禁拦下**)
            if call({"Authorization": f"Bearer {TOKEN}"}).status_code in (401, 403):
                fails.append(f"{module}: {path} 对令牌被拦(门禁把正常调用挡了)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return fails


def _ws_attempt(url: str, headers: dict) -> Tuple[bool, str]:
    """真发一次握手。返回 (连上了吗, 说明)。"""
    import asyncio

    import websockets

    async def _go():
        kwargs = {}
        if headers:
            import inspect

            params = inspect.signature(websockets.connect).parameters
            name = "additional_headers" if "additional_headers" in params else "extra_headers"
            kwargs[name] = headers
        async with websockets.connect(url, open_timeout=8, **kwargs) as ws:
            # 判据是**握手成不成**,不是"有没有收到消息"。鉴权拦的就是握手;
            # 而多数信令端点 accept 之后是等对方先说话的(Node_95 正是如此),
            # 拿"收到第一条消息"当判据,会把一条已经建立的连接判成"没连上"。
            try:
                return f"已握手;首条消息 {(await asyncio.wait_for(ws.recv(), timeout=2))!r}"
            except (asyncio.TimeoutError, TimeoutError):
                return "已握手(端点在等对方先开口)"

    try:
        return True, str(asyncio.run(_go()))
    except Exception as exc:  # noqa: BLE001 — 被拒也走这里
        return False, f"{type(exc).__name__}: {exc}"


def check_ws(label: str, argv: List[str], ws_path: str) -> List[str]:
    """把一个带 WS 端点的 app 起起来,核对握手阶段的身份判定。"""
    import httpx

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, GALAXY_API_TOKEN=TOKEN, PYTHONPATH=os.getcwd())
    env.pop("GALAXY_NODE_AUTH", None)
    proc = subprocess.Popen(
        [sys.executable, *argv, str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    fails: List[str] = []
    try:
        with httpx.Client() as c:
            if not _wait(c, f"{base}/health", timeout=25.0):
                err = (proc.stderr.read() or b"").decode()[-400:] if proc.stderr else ""
                return [f"{label}: 起不来 / {err}"]

        ws_url = f"ws://127.0.0.1:{port}{ws_path}"
        ok_bare, why_bare = _ws_attempt(ws_url, {})
        if ok_bare:
            fails.append(f"{label}: {ws_path} 无令牌就握上手了(收到 {why_bare!r})")
        ok_wrong, _ = _ws_attempt(ws_url, {"Authorization": "Bearer wrong"})
        if ok_wrong:
            fails.append(f"{label}: {ws_path} 错令牌就握上手了")
        # 差分的另一半:只验"连不上"的话,把整条路堵死也会全绿。
        ok_good, why_good = _ws_attempt(ws_url, {"Authorization": f"Bearer {TOKEN}"})
        if not ok_good:
            fails.append(f"{label}: {ws_path} 带对令牌反而连不上 —— {why_good}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return fails


def _run_ws_section() -> Tuple[List[str], List[str]]:
    """返回 (失败项, 未能验证的说明)。"""
    fails: List[str] = []
    unverified: List[str] = []

    probe_src = _SERVE_WS_PROBE % (os.getcwd(),)
    probe_fails = check_ws("机制自检(最小 app)", ["-c", probe_src], "/signaling/live-check-device")
    print(f"  {'❌' if probe_fails else '✅'} {'机制自检(最小 app)':<26} WS /signaling/{{id}}")
    for f in probe_fails:
        print(f"       {f}")
    fails += probe_fails

    for module, ws_path in WS_TARGETS:
        name = module.split(".")[1]
        # 在子进程里探能不能导 —— 和真起服务同一个环境(PYTHONPATH=cwd),
        # 也免得把一个重依赖的节点模块拉进本进程。
        probe = subprocess.run(
            [sys.executable, "-c", f"import importlib; importlib.import_module({module!r})"],
            env=dict(os.environ, PYTHONPATH=os.getcwd()),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if probe.returncode != 0:
            why = (probe.stderr.strip().splitlines() or ["(无输出)"])[-1]
            print(f"  ⚠️  {name:<26} 未验 —— 本机导不进来: {why}")
            unverified.append(f"{name}: {why}")
            continue
        node_fails = check_ws(name, ["-c", _SERVE, module], ws_path)
        print(f"  {'❌' if node_fails else '✅'} {name:<26} WS {ws_path}")
        for f in node_fails:
            print(f"       {f}")
        fails += node_fails

    return fails, unverified


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("nodes", nargs="*", help="节点目录名,如 Node_06_Filesystem;留空=默认那批")
    ap.add_argument("--ws", action="store_true", help="只验 WebSocket 面")
    ap.add_argument("--no-ws", action="store_true", help="跳过 WebSocket 面")
    args = ap.parse_args()

    for dep in ("uvicorn", "httpx", "websockets"):
        try:
            importlib.import_module(dep)
        except ImportError:
            print(f"缺 {dep} —— 这个脚本要真起服务,装上再跑: pip install {dep}")
            return 2

    targets = DEFAULT_TARGETS
    if args.nodes:
        targets = [(f"nodes.{n}.main", "/status", "GET", {}) for n in args.nodes]

    os.makedirs(tempfile.gettempdir(), exist_ok=True)
    all_fails: List[str] = []
    checked = 0
    if not args.ws:
        for module, path, method, body in targets:
            fails = check(module, path, method, body)
            name = module.split(".")[1]
            print(f"  {'❌' if fails else '✅'} {name:<26} {method} {path}")
            for f in fails:
                print(f"       {f}")
            all_fails += fails
            checked += 1

    unverified: List[str] = []
    if not args.no_ws:
        ws_fails, unverified = _run_ws_section()
        all_fails += ws_fails

    print()
    for note in unverified:
        print(f"未能验证:{note}")
    if all_fails:
        print(f"—— {len(all_fails)} 项不符合契约 ——")
        return 1
    tail = f",另有 {len(unverified)} 项未能在本机验证" if unverified else ""
    print(f"—— 真实 HTTP/WS 上已核对的部分全部符合契约({checked} 个节点 + WS 面){tail} ——")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
