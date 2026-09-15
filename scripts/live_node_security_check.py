#!/usr/bin/env python3
"""真实环境里验节点 HTTP 面的三道门 —— 不是 TestClient,是真起进程、走真实 TCP。

## 为什么需要这个

TestClient 走进程内 ASGI transport:不经过真实 socket、不跑 uvicorn 的 HTTP 解析、
不跑 lifespan。中间件在两种方式下都会执行,但"容器起来之后到底行不行"只有真跑才算数。

这个脚本做的事:用 uvicorn 把节点起在真实端口上,用真实 HTTP 客户端打它,
逐条核对契约(见 docs/NODE_HTTP_SECURITY_CONTRACT.md)。

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("nodes", nargs="*", help="节点目录名,如 Node_06_Filesystem;留空=默认那批")
    args = ap.parse_args()

    for dep in ("uvicorn", "httpx"):
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
    for module, path, method, body in targets:
        fails = check(module, path, method, body)
        name = module.split(".")[1]
        print(f"  {'❌' if fails else '✅'} {name:<26} {method} {path}")
        for f in fails:
            print(f"       {f}")
        all_fails += fails

    print()
    if all_fails:
        print(f"—— {len(all_fails)} 项不符合契约 ——")
        return 1
    print(f"—— {len(targets)} 个节点在真实 HTTP 上全部符合契约 ——")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
