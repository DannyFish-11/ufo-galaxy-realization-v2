#!/usr/bin/env python3
"""behavior_smoke.py — 真跑一遍,并断言"内部确实动了"。

它和 scripts/smoke_test.py 有什么不同
------------------------------------
``smoke_test.py`` 问的是"端点在不在、答不答得出 200"。这个脚本问的是**另一个问题**:

    请求确实进来了 —— 那条链路到底有没有干活?

差别不是程度问题。本轮排查里连着找到五处缺陷,全都是 **200 OK + 内部什么都没发生**:

  * 设备维协商读的是 UDM,而 UDM 在运行时是空的(272 个设备 vs 0)。
    协商照常返回,只是永远按"无设备信息"走。
  * ``audio_out`` 这一档在真实设备数据里根本没有任何设备声明过 ——
    73 个被卡住的设备里 0 个是真阳性。闸照常生效,只是全在误杀。
  * 焦点栈的标题被 ``[Multimodal context: …]`` 这类机器注解污染,
    栈照常记,只是记下来的是噪声。
  * 三态心跳任务因为漏了一行 ``_tick_running = True`` 而从不推进 ——
    ``_tick_task`` 存在、字段仍显示 ``liminal``、**全部既有测试照常绿**。
  * 实时会话链路上下文没补齐,每一轮都是无记忆的。

这五处的共同点:**没有任何断言会红**。单测证明的是函数对不对,端点探活证明的是
进程活没活着,两者都不覆盖"这个能力在真实请求里到底生效了没有"。这个脚本就是补
那一层 —— 它只断言**计数器动了**,不断言业务结果,因为业务结果依赖模型输出而
计数器不依赖。

怎么跑
------
1. 起 Ollama 桩(复用 ``ambient_service_stubs.py``),让本地模型探测有东西可探;
2. 按 ``unified_launcher.py`` 的方式组装权威 API 层(``core.api_routes``);
3. 打真实 HTTP:同一会话连着几轮,构成"话题延续";
4. 回头读观测端点,断言 ACI / 焦点栈 / 在场 / 设备模态**各自的计数或快照确实变了**。

用法::

    python scripts/behavior_smoke.py
    python scripts/behavior_smoke.py --port 8799 --keep-going
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

SESSION_ID = "behavior-smoke-session"

#: ACI 的静默期(``_DEFAULT_SETTLE_DELAY_S`` = 1.2s):一轮结束后要静置这么久才真的去预取,
#: 期间只要有新请求进来或又落了一轮就放弃。所以轮次间隔**必须大于**它,收尾也必须多等一拍。
#:
#: 第一版这里两处都踩空了:轮次间隔 1.0s < 1.2s,于是每一次预取都被下一轮作废
#: (skipped_busy=3);最后一次预取还在静默期里我就去读了统计。结果是
#: prefetch_entries_cached 恒为 0,而当时的断言只查 "scheduled >= 1" —— **它照样绿**。
#: 一条在被测链路一次都没跑通的情况下仍然通过的断言,正是这个脚本存在的理由本身。
ACI_SETTLE_S = 1.2
TURN_GAP_S = ACI_SETTLE_S + 1.3
DRAIN_S = ACI_SETTLE_S + 1.8

#: 连着问同一个话题。ACI 的预判、焦点栈的"同一焦点"判定都依赖轮次之间的词面接近,
#: 单轮什么都触发不了 —— 这也是为什么这个脚本不能只打一次请求就收工。
TURNS = [
    "帮我梳理一下分布式调度里的任务分片策略",
    "任务分片的粒度一般怎么定",
    "那分片之后失败重试怎么处理",
]


class Report:
    """把每条检查连同"它挡住的是哪种静默失效"一起记下来。"""

    def __init__(self) -> None:
        self.rows: List[Tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return ok

    @property
    def failed(self) -> List[Tuple[str, bool, str]]:
        return [r for r in self.rows if not r[1]]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _request(url: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 60.0) -> Tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 固定打本机
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        return 0, str(exc)


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ---------------------------------------------------------------------------
# 组装被测应用
# ---------------------------------------------------------------------------
#: 这份 harness 必须和 unified_launcher.py 的步骤 3 保持一致:建一个 FastAPI 应用,
#: 把 core.api_routes.create_api_routes() 挂上去。
#:
#: 为什么不直接跑 unified_launcher —— 它还会拉起进程监管、心跳、节点编排等一整套,
#: 在 CI 里既慢又不稳,而本脚本要验的缺陷全都在**请求处理**里,不在进程监管里。
#: 为什么不用 galaxy_gateway.app —— 实测它只暴露 59 条路由,observability / modality /
#: operator 都不在其中;拿它当被测对象会得到一个恒绿但什么都没测到的脚本。
_APP_HARNESS = '''
import os, sys
sys.path.insert(0, {repo!r})
os.environ.setdefault("GALAXY_NATS_ENABLED", "false")
from fastapi import FastAPI
import uvicorn
from core.api_routes import create_api_routes

app = FastAPI(title="behavior-smoke")
app.include_router(create_api_routes(service_manager=None, config=None))
uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
'''


def boot_app(port: int, log_path: Path) -> subprocess.Popen:
    log = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-c", _APP_HARNESS.format(repo=str(REPO_ROOT), port=port)],
        cwd=REPO_ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "GALAXY_NATS_ENABLED": "false", "PYTHONUNBUFFERED": "1"},
    )


def wait_ready(base: str, proc: subprocess.Popen, timeout: float = 180.0) -> bool:
    """轮询到应用能答话为止。

    用 ``/openapi.json`` 而不是某个健康端点:健康端点自己也可能没挂上,
    而 openapi 只要 FastAPI 起来了就一定有 —— 这里要判的是"进程活了没有",
    不该和"某个路由存在不存在"耦合。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        status, _ = _request(f"{base}/openapi.json", timeout=5)
        if status == 200:
            return True
        time.sleep(1.0)
    return False


# ---------------------------------------------------------------------------
# 检查
# ---------------------------------------------------------------------------
def check_routes_present(base: str, rep: Report) -> Dict[str, Any]:
    """先确认被测端点真的挂上了。

    这一条必须排在最前面:如果观测端点压根不存在,后面每一条检查都会因为拿不到数据
    而"没发现问题",于是整个脚本变成恒绿。**探针自己失效必须表现为失败,不是通过。**
    """
    status, spec = _request(f"{base}/openapi.json", timeout=30)
    paths = set((spec or {}).get("paths", {})) if isinstance(spec, dict) else set()
    for path in (
        "/api/v1/chat",
        "/api/v1/observability/context-layer",
        "/api/v1/modality/matrix",
        "/api/v1/operator/presence/ambient",
    ):
        rep.check(f"路由已挂载 {path}", path in paths, f"共 {len(paths)} 条路由")
    return {"paths": paths}


def drive_turns(base: str, rep: Report) -> None:
    ok_turns = 0
    for i, text in enumerate(TURNS, 1):
        status, body = _request(
            f"{base}/api/v1/chat",
            {"message": text, "session_id": SESSION_ID},
            timeout=120,
        )
        # 200 就算数:上游可能没配 key 而走降级回答,那不影响本脚本要验的东西 ——
        # ACI 预取、焦点栈记账都发生在**取到模型回答之前**。
        if status == 200:
            ok_turns += 1
        else:
            print(f"    (第 {i} 轮 HTTP {status}: {str(body)[:160]})")
        time.sleep(TURN_GAP_S)
    rep.check(f"驱动 {len(TURNS)} 轮真实对话", ok_turns == len(TURNS), f"成功 {ok_turns}/{len(TURNS)}")
    # 等最后一次预取走完静默期。不等就去读统计,读到的是"还没来得及跑",
    # 而那和"跑了但什么都没做"在数字上长得一模一样。
    print(f"    等 {DRAIN_S:.1f}s 让最后一次预取落地…")
    time.sleep(DRAIN_S)

    # 再打一轮**与上一轮逐字相同**的问题,把闭环补上。
    # 预判的第一条就是"话题延续 = 上一句用户问的"(kind=topic_continuity),
    # 所以这一轮理应命中刚才预取进缓存的那条。
    #
    # 为什么非要有这一轮:cached >= 1 只证明"存进去了",不证明"取得出来"。
    # 存和取是两条独立的路径,任何一条断了,另一条的计数器都照涨不误 ——
    # 缓存写满而命中恒为 0,恰恰是这个系统里最典型的那种"看起来在工作"。
    status, _ = _request(f"{base}/api/v1/chat", {"message": TURNS[-1], "session_id": SESSION_ID}, timeout=120)
    rep.check("复述上一轮以触发命中", status == 200, f"HTTP {status}")


def check_context_layer(base: str, rep: Report) -> None:
    status, body = _request(f"{base}/api/v1/observability/context-layer?session_id={SESSION_ID}", timeout=30)
    if status != 200 or not isinstance(body, dict):
        rep.check("观测端点可读", False, f"HTTP {status}")
        return
    rep.check("观测端点可读", True)

    aci = body.get("aci") or {}
    # 挡的是:ACI 整条链路一次都没被调用(而不是"猜错了")。区别很重要 ——
    # 猜错是效果问题,一次都没跑是**接线问题**,后者才是这个脚本要抓的。
    attempts = int(aci.get("prefetch_runs_scheduled") or 0)
    cached = int(aci.get("prefetch_entries_cached") or 0)
    rep.check("ACI 预取被安排过", attempts >= 1, f"prefetch_runs_scheduled={attempts}")
    # 关键的是这一条,不是上一条。"安排过"只证明入口接上了;预取可以次次
    # 被静默期作废、或者组装出空上下文,而计数器照样一路上涨。真正说明这条链路
    # 通了的是**有东西被存进缓存**。
    rep.check(
        "ACI 预取真的落了缓存",
        cached >= 1,
        f"cached={cached} skipped_busy={aci.get('prefetch_skipped_busy')} "
        f"failed={aci.get('prefetch_failed')} stats={json.dumps(aci, ensure_ascii=False)[:220]}",
    )

    hits = sum(int(aci.get(k) or 0) for k in ("hit_exact", "hit_lexical", "hit_continuation"))
    # 闭环:存进去的东西真的被取出来用了。这一条断了而上一条没断,意味着
    # 预取在白干 —— 每轮都算一遍、存一遍,然后没有任何一次被读到。
    rep.check(
        "缓存真的被命中(存-取闭环)",
        hits >= 1,
        f"hit_exact={aci.get('hit_exact')} hit_lexical={aci.get('hit_lexical')} "
        f"hit_continuation={aci.get('hit_continuation')} miss={aci.get('miss')}",
    )

    focus = body.get("focus_stack") or {}
    if focus.get("error"):
        rep.check("焦点栈快照可用", False, str(focus))
        return
    rep.check("焦点栈快照可用", True)
    depth = int(focus.get("depth") or 0) or (1 if focus.get("current") else 0)
    # 挡的是:焦点栈从没记下任何东西(接线断了),不是"分层不对"。
    rep.check("焦点栈至少记下了一个焦点", depth >= 1, f"depth={depth}")

    title = ((focus.get("current") or {}) if isinstance(focus.get("current"), dict) else {}).get("title") or ""
    # 挡的是:标题被 [Multimodal context: …] 这类机器注解污染 —— 实测发生过,
    # 栈照常记,只是记下来的是噪声,从任何单测里都看不出来。
    if title:
        polluted = "Multimodal context" in title or title.strip().startswith("]")
        rep.check("焦点标题没有被机器注解污染", not polluted, f"title={title!r}")


def check_modality_matrix(base: str, rep: Report) -> None:
    # 注意端点分工:/matrix 是**档位**矩阵(模型声明 × 服务现实),
    # 设备这一维在 /devices。第一版这里打错了端点,于是拿档位矩阵去数设备,
    # 数出 0 来 —— 探针自己读错来源,报出来的却像是被测对象坏了。
    status, body = _request(f"{base}/api/v1/modality/matrix", timeout=30)
    tiers = (body or {}).get("tiers") if isinstance(body, dict) else None
    rep.check(
        "档位矩阵可读且非空",
        status == 200 and isinstance(tiers, list) and len(tiers) >= 1,
        f"HTTP {status} tiers={len(tiers) if isinstance(tiers, list) else 'n/a'}",
    )

    status, body = _request(f"{base}/api/v1/modality/devices", timeout=60)
    if status != 200 or not isinstance(body, dict):
        rep.check("设备模态矩阵可读", False, f"HTTP {status}")
        return
    rep.check("设备模态矩阵可读", True)

    devices = body.get("devices") or []
    count = len(devices) if isinstance(devices, list) else 0
    # 挡的正是那次实测:设备维读的是 UDM,而 UDM 在运行时是空的 —— 端点照常 200,
    # 只是永远返回 0 个设备。修法是改读 core/routes/devices.py 那份合并来源。
    rep.check(
        "矩阵里真的有设备(不是空 UDM)",
        count >= 1,
        f"设备数={count};为 0 通常意味着又读回了运行时为空的那份来源",
    )
    if count < 1:
        return

    gated = sum(1 for d in devices if isinstance(d, dict) and (d.get("gate") or {}).get("gating_active"))
    device_limited = sum(
        1
        for d in devices
        if isinstance(d, dict)
        for v in (d.get("plan") or {}).values()
        if isinstance(v, dict) and v.get("limited_by") == "device"
    )
    # 这两条才是"第三维真的在起作用"。只数设备数不够 —— 设备全在、但没有一个
    # 申报过能力时,门控存在而从不生效,表现与没接线完全一样。
    rep.check("有设备申报了模态能力(门控真的激活)", gated >= 1, f"gating_active={gated}/{count}")
    rep.check(
        "确实有模态因**设备**而受限(第三维在生产里生效)",
        device_limited >= 1,
        f"limited_by=device 的条目数={device_limited}",
    )


def check_presence(base: str, rep: Report) -> None:
    status, body = _request(f"{base}/api/v1/operator/presence/ambient", timeout=30)
    if status != 200 or not isinstance(body, dict):
        rep.check("在场快照可读", False, f"HTTP {status}")
        return
    rep.check("在场快照可读", True)
    # 只断言字段成形,不断言"此刻有环境在场" —— 冒烟里没有双工会话,
    # 要求它非空会变成一条必然红的假断言。
    rep.check(
        "在场快照字段成形",
        isinstance(body.get("ambient_presence", body.get("entries", [])), (list, dict)),
        json.dumps(body, ensure_ascii=False)[:200],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--keep-going", action="store_true", help="有失败也以 0 退出(告警形态)")
    parser.add_argument("--boot-timeout", type=float, default=180.0)
    args = parser.parse_args()

    port = _free_port(args.port)
    base = f"http://127.0.0.1:{port}"
    rep = Report()
    # 落在 logs/ 下:.gitignore 已经忽略了它,不会把工作树弄脏 ——
    # 本仓有过"测试改写 git 跟踪文件"的教训,冒烟脚本不该再犯一次。
    log_dir = REPO_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "behavior_smoke_app.log"

    from ambient_service_stubs import OLLAMA_PORT, port_in_use, start as start_stubs  # noqa: PLC0415

    print("── 起环境桩 ──")
    stub_handles = start_stubs(["ollama"]) if not port_in_use(OLLAMA_PORT) else []
    print(f"  Ollama 桩: {'已就绪' if port_in_use(OLLAMA_PORT) else '未起来(继续,本地模型探测会落空)'}")

    print(f"\n── 起应用(:{port})──")
    proc = boot_app(port, log_path)
    try:
        if not wait_ready(base, proc, args.boot_timeout):
            print(f"应用没起来。日志尾部({log_path}):", file=sys.stderr)
            if log_path.is_file():
                print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]))
            return 2

        print("\n── 检查:被测端点是否存在 ──")
        check_routes_present(base, rep)

        print("\n── 驱动真实对话 ──")
        drive_turns(base, rep)

        print("\n── 检查:上下文层(ACI / 焦点栈)──")
        check_context_layer(base, rep)

        print("\n── 检查:设备模态第三维 ──")
        check_modality_matrix(base, rep)

        print("\n── 检查:在场 ──")
        check_presence(base, rep)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        for handle in stub_handles:
            try:
                handle.shutdown()
            except Exception:  # noqa: BLE001 — 收桩失败不该盖掉真正的结论
                pass

    print("\n" + "=" * 72)
    print(f"{len(rep.rows) - len(rep.failed)} 通过 / {len(rep.failed)} 失败")
    print("=" * 72)
    if rep.failed:
        print("\n失败项:")
        for name, _, detail in rep.failed:
            print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))
        print(
            "\n  这些都不是『端点挂了』—— 端点很可能照常 200。它们说的是**那条链路没干活**。\n"
            f"  应用日志在 {log_path}。"
        )
        if not args.keep_going:
            return 1
        print("\n  以 --keep-going 运行,不判失败。")
    else:
        print("\n✅ 每条链路的计数/快照都确实动了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
