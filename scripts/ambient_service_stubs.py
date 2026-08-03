#!/usr/bin/env python3
"""ambient_service_stubs.py — 把"本机恰好装了某个服务"这件事变成可控开关。

为什么需要它
------------
本仓反复出过同一类缺陷:**一条测试的结论取决于机器上恰好有没有某个东西**,
而且失败信息从不提这一点。已确认的两起:

1. ``tests/test_mesh_worker_panel_toggle.py`` —— 断言"NATS 不可达",但
   ``core.nats_server`` 在连不上时会自动下载 nats-server 并拉起一个脱离进程
   长期存活的常驻服务。第一次跑就把前提亲手破坏掉,此后永久红且不自愈。
2. ``tests/test_pr52_desktop_native_ingress_backbone.py`` —— 用 _FakeRouter 控制
   路由后断言 route_type,但 ``_select_multimodal_route`` 会**先**问
   HardwareAwareMultimodalRouter,本机有 Ollama 就整个绕过那个 fake。
   而这个项目的安装文档**要求**装 Ollama —— 也就是说按文档配好环境的开发者
   一跑测试就看到 4 条与自己改动无关的红,失败信息只说 partial != native。

两起都是 CI 恒绿(runner 干净)、只砸本机开发者。靠人去想"会不会是环境"是不可靠的,
所以把它变成一个可以**主动制造**的条件:起这些桩,再跑一遍,谁翻红谁就是环境耦合。

这些桩是什么、不是什么
----------------------
* 是**真的 HTTP 服务**,监听真实端口,说真实协议的最小子集。被测代码走的是完整的
  探测/发现/连接链路,一步不少 —— 这是它能复现真实耦合的前提。
* **不是** mock:不 patch 任何东西,不进被测进程。
* 只实现"存在性探测"需要的那部分响应。它们的用途是回答"服务在不在",不是替
  真服务干活。

用法::

    python scripts/ambient_service_stubs.py            # 前台起全部桩,Ctrl-C 停
    python scripts/ambient_service_stubs.py --only ollama
    python scripts/ambient_service_stubs.py --check    # 只报告端口占用情况

CI 里由 .github/workflows/environment-coupling.yml 调用。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Ollama 桩
# ---------------------------------------------------------------------------
# 触发点:core.multi_llm_router._discover_providers() 与
# core.hardware_aware_multimodal_router —— 两者都靠 GET /api/tags 判断"本机有没有
# 本地模型"。只要这个端点答得出来,系统就认为本地模型可用,并据此改变路由与档位。
OLLAMA_PORT = 11434
_OLLAMA_MODEL = "ambient-stub:latest"


class _OllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *_a):  # 静音:桩的访问日志对判定没有价值
        pass

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/tags"):
            self._json({"models": [{"name": _OLLAMA_MODEL, "model": _OLLAMA_MODEL, "size": 1}]})
        else:
            self._json({"ok": True})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:  # noqa: BLE001
            payload = {}
        if self.path.startswith("/api/chat"):
            self._json(
                {
                    "model": payload.get("model", _OLLAMA_MODEL),
                    "message": {"role": "assistant", "content": "stub"},
                    "done": True,
                    "prompt_eval_count": 1,
                    "eval_count": 1,
                }
            )
        else:
            self._json({"response": "stub", "done": True})


_STUBS: Dict[str, Tuple[int, type]] = {
    "ollama": (OLLAMA_PORT, _OllamaHandler),
}


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def start(names: List[str]) -> List[HTTPServer]:
    """起指定的桩,返回 server 列表(调用方负责 shutdown)。

    端口已被占用时**不报错也不覆盖** —— 那说明本机真有那个服务,目的已经达到。
    """
    servers: List[HTTPServer] = []
    for name in names:
        port, handler = _STUBS[name]
        if port_in_use(port):
            print(f"  [{name}] :{port} 已被占用 —— 本机已有该服务,跳过起桩", flush=True)
            continue
        server = HTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        print(f"  [{name}] 桩已起 :{port}", flush=True)
    return servers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", choices=sorted(_STUBS), help="只起指定的桩(可重复)")
    parser.add_argument("--check", action="store_true", help="只报告端口占用,不起任何东西")
    args = parser.parse_args()

    names = args.only or sorted(_STUBS)

    if args.check:
        for name in names:
            port, _ = _STUBS[name]
            print(f"{name}: :{port} {'占用中' if port_in_use(port) else '空闲'}")
        return 0

    print("起环境桩(用于探测环境耦合的测试):", flush=True)
    servers = start(names)
    if not servers:
        print("没有起任何桩 —— 端口都已被占用。", flush=True)
    print("就绪。Ctrl-C 停止。", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
