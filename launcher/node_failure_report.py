"""节点启动结果的汇总 —— 「起来了 / 还在起 / 真起不来(以及为什么)」三件事分开说。

## 被修的问题（Windows 真机日志）

CPU 吃紧的机器上，13 个节点并行拉起（外加语音模型下载、本地大模型在占 CPU），最重的那几个
（状态机、编排器、上下文、自愈）5 秒内过不了健康检查。此前汇总里：

* 进程明明还活着、只是慢，也被写成「N 个节点启动失败（详情见日志 DEBUG）」—— 而且之后没有人再去看它们，
  它们起来了也不会被登记，系统就一直「9/13 就绪」；
* 真起不来的，失败原因只写进 DEBUG 日志，屏幕上只有一个「详情见日志 DEBUG」，用户拿不到一句能照着做的话；
* 端口被占用 / 被 Windows 保留（Hyper-V、WSL、Docker 会保留一段端口，``netsh int ipv4 show excludedportrange``
  能看到）这种最常见的真原因，被归进「其他」。

现在：慢的 → 后台继续等、起来了自动登记；真失败的 → 屏幕上带一句原因（取 stderr 最后一行有信息的）；端口问题单独说，
并给出看哪里。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy")

#: 慢启动的节点后台最多再等多久（秒）。不做成配置项：两分钟还没起来的，不是「慢」，是卡住了。
SLOW_START_WAIT_S = 120.0

#: stderr 里出现这些，就是端口绑不上（占用 / 被系统保留 / 无权限）。
PORT_SIGNALS = (
    "winerror 10013",
    "winerror 10048",
    "errno 10013",
    "errno 10048",
    "errno 98",
    "errno 48",
    "address already in use",
    "only one usage of each socket address",
    "forbidden by its access permissions",
)


def is_port_failure(stderr_text: str) -> bool:
    low = (stderr_text or "").lower()
    return any(s in low for s in PORT_SIGNALS)


def last_informative_line(stderr_text: str, limit: int = 140) -> str:
    """stderr 里最后一行有信息的 —— 通常就是异常那一行。"""
    for line in reversed((stderr_text or "").splitlines()):
        text = line.strip()
        if text and not set(text) <= set("^~ -"):
            return text[:limit]
    return ""


def read_node_output(service: Any, limit: int = 4096) -> str:
    """节点进程输出的最后 ``limit`` 字节：优先读它的日志文件，没有就退回管道（旧路径 / 测试替身）。

    永不抛异常；读不到返回空串。
    """
    path = getattr(service, "log_path", None)
    if path:
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - limit))
                return f.read().decode(errors="replace")
        except OSError:
            pass
    proc = getattr(service, "process", None)
    stream = getattr(proc, "stderr", None)
    if stream is None:
        return ""
    try:
        return ((stream.read() or b"")[-limit:]).decode(errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def report_node_failures(
    results: Dict[str, bool],
    reasons: Dict[str, str],
    details: Dict[str, str],
    print_status: Callable[..., None],
) -> List[str]:
    """把启动结果按原因分桶打印，返回「还在慢慢起」的节点名（调用方据此派后台等待）。"""
    ok = [n for n, v in results.items() if v]
    failed = [n for n, v in results.items() if not v]

    def of(kind: str) -> List[str]:
        return [n for n in failed if reasons.get(n) == kind]

    slow, infra, imports, port = of("slow_start"), of("infra"), of("import"), of("port")
    other = [n for n in failed if reasons.get(n) not in ("slow_start", "infra", "import", "port")]

    if infra:
        print_status(
            f"{len(infra)} 个节点因缺少基础设施跳过（单机模式属正常；如需启用：docker compose up -d）: {infra}",
            "warning",
        )
    if imports:
        print_status(
            f"{len(imports)} 个节点因缺 Python 依赖未启动（pip install -r requirements.txt 可修）: {imports}", "warning"
        )
    if port:
        print_status(
            f"{len(port)} 个节点的端口绑不上（被别的程序占用，或被系统保留 —— Windows 上管理员 PowerShell 运行 "
            f"`netsh int ipv4 show excludedportrange protocol=tcp` 看哪一段被保留）: {port}",
            "warning",
        )
    if slow:
        print_status(
            f"{len(slow)} 个节点还在启动（进程在跑、只是这台机器忙，起来后会自动接上，不用管）: {slow}", "info"
        )
    if other:
        why = "；".join(f"{n}: {details[n]}" for n in other if details.get(n))
        print_status(
            f"{len(other)} 个节点启动失败: {other}" + (f" —— {why}" if why else "（原因没捕获到，见日志 DEBUG）"),
            "warning" if not ok else "info",
        )
    if not failed:
        print_status(f"全部 {len(ok)} 个节点就绪", "success")
    return slow


async def adopt_slow_nodes(launcher: Any, nodes: List[str], wait_s: Optional[float] = None) -> Dict[str, bool]:
    """进程还活着、只是健康检查没赶上的节点：继续等，起来了就登记；进程死了就如实记下原因。

    返回 ``{节点名: 最终是否起来}``。永不抛异常（后台任务，出错只记日志）。
    """
    import aiohttp

    if wait_s is None:
        wait_s = SLOW_START_WAIT_S
    outcome: Dict[str, bool] = {}
    pending = {n for n in nodes}
    deadline = asyncio.get_running_loop().time() + wait_s
    try:
        while pending and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(2)
            for name in sorted(pending):
                svc = launcher.service_manager.services.get(name)
                proc = svc.process if svc else None
                cfg = launcher.node_configs.get(name, {})
                port = cfg.get("port") if isinstance(cfg, dict) else None
                if proc is not None and proc.poll() is not None:  # 进程自己退了：不是慢，是死了
                    pending.discard(name)
                    outcome[name] = False
                    detail = last_informative_line(read_node_output(svc))
                    logger.warning("节点 %s 等到一半进程退出了%s", name, f"：{detail}" if detail else "")
                    continue
                if port is None:
                    continue
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
                        async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                            healthy = resp.status < 400
                except Exception:  # noqa: BLE001
                    healthy = False
                if healthy:
                    pending.discard(name)
                    outcome[name] = True
                    await launcher._register_node_with_runtime_registry(name, port)
                    logger.info("节点 %s 慢启动完成，已登记（端口 %s）", name, port)
        for name in pending:
            outcome[name] = False
            logger.warning("节点 %s 等了 %.0f 秒仍没通过健康检查（进程还在，可能卡住了）", name, wait_s)
    except Exception as exc:  # noqa: BLE001 — 后台任务，失败只记日志
        logger.warning("慢启动节点的后台等待出错: %s", exc)
    return outcome
