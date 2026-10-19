"""基础设施容器此刻到底怎么样 —— 横幅上那句「已就绪」不能只凭 ``compose up -d`` 退出码是 0。

全面排查第 6 轮真跑（沙箱里第一次有了 Docker）：横幅写「nats / redis / qdrant / neo4j / mongodb 已就绪」，
而 neo4j 在反复重启（插件名写成了 ``gds``，它连起都起不来）、qdrant 永远 unhealthy（健康检查调 ``curl``，
镜像里没有）。``up -d`` 只说明「容器建好了、启动过了」，不说明里面的服务起没起来。

这里在 ``up -d`` 之后读一遍 ``compose ps``，最多等几秒让还在起来的落定：

- 全在跑且健康（或没有健康检查）→ 已就绪；
- 反复重启 / 退出了 / 健康检查不过 / 没建出来 → 照实点名，算降级；
- 到点还在起来（健康检查的启动期）→ 「还在起来」，与节点同一档，不算降级。

一次轮询里见过「坏」的就记成坏：起不来的容器在「重启中」与「刚起来」之间来回切，只看最后一眼会看漏。
读不到状态（compose 太旧、不认 ``--format json``）就只说「已拉起」，不替它说「已就绪」。
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

#: 本机的四个库：只给这台电脑上的后端与节点用（docker-compose.yml 里端口只绑 127.0.0.1）
LOCAL_STORES = ("redis", "qdrant", "neo4j", "mongodb")


def infra_services() -> List[str]:
    """``compose up -d`` 起哪几个基础设施容器。

    NATS 只在要总线时起 —— 与真正连总线的那一处同一判据（``core.system_mode.nats_wanted``）。全面排查第 7 轮：
    本地模式（这台电脑不加入设备网络）下照样起了一个 nats 容器，4222 对整个局域网开着、不带认证。
    """
    from core.system_mode import nats_wanted

    return (["nats"] if nats_wanted() else []) + list(LOCAL_STORES)


GOOD = "good"
STARTING = "starting"
BAD = "bad"

#: 坏在哪儿 → 横幅上那句话
_BAD_WORDS = {
    "restarting": "反复重启",
    "exited": "退出了",
    "dead": "退出了",
    "paused": "被暂停了",
    "missing": "没建出来",
    "unhealthy": "健康检查不过",
}


def parse_ps(text: str) -> Dict[str, Tuple[str, str]]:
    """``compose ps --format json`` 的输出 → ``{服务名: (State, Health)}``。

    新版 compose 一行一个对象，旧版是一个数组；两种都认。认不出返回 ``{}``（调用方据此不下结论）。
    """
    text = (text or "").strip()
    if not text:
        return {}
    rows: list = []
    try:
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
    except ValueError:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                return {}
    out: Dict[str, Tuple[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("Service") or row.get("Name")
        if name:
            out[str(name)] = (str(row.get("State") or "").lower(), str(row.get("Health") or "").lower())
    return out


def verdict(state: str, health: str) -> str:
    """一个容器此刻算好、还在起来、还是坏。"""
    if state == "running" and health in ("", "healthy"):
        return GOOD
    if state == "created" or (state == "running" and health == "starting"):
        return STARTING
    return BAD


def _why(state: str, health: str) -> str:
    if state == "running" and health == "unhealthy":
        return _BAD_WORDS["unhealthy"]
    return _BAD_WORDS.get(state, f"状态 {state or '未知'}")


def settle(
    read: Callable[[], Dict[str, Tuple[str, str]]],
    services: Sequence[str],
    *,
    wait_s: float = 8.0,
    every_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Optional[Dict[str, Tuple[str, str]]]:
    """轮询到没有「还在起来」的、或到点为止。返回 ``{服务: (判定, 坏在哪儿)}``；读不到状态返回 ``None``。"""
    deadline = clock() + wait_s
    seen_bad: Dict[str, str] = {}
    while True:
        states = read()
        if not states:
            return None
        result: Dict[str, Tuple[str, str]] = {}
        for svc in services:
            state, health = states.get(svc, ("missing", ""))
            kind = verdict(state, health)
            if kind == BAD:
                seen_bad.setdefault(svc, _why(state, health))
            result[svc] = (BAD, seen_bad[svc]) if svc in seen_bad else (kind, "")
        if all(kind != STARTING for kind, _ in result.values()) or clock() >= deadline:
            return result
        sleep(every_s)


def summarize(
    result: Optional[Dict[str, Tuple[str, str]]], services: Sequence[str], rt_name: str, logs_cmd: str
) -> tuple:
    """→ 与 ``GalaxyUnified.ensure_docker_infra`` 同形的 ``(status, value, note)``。"""
    every = " / ".join(services)
    if result is None:
        return ("ok", f"{every} 已拉起 · via {rt_name}（没读到各服务的状态）", "")
    good = [s for s in services if result[s][0] == GOOD]
    starting = [s for s in services if result[s][0] == STARTING]
    bad = [s for s in services if result[s][0] == BAD]
    if not starting and not bad:
        return ("ok", f"{every} 已就绪 · via {rt_name}", "")
    parts: List[str] = []
    if bad:
        parts.append(" · ".join(f"{s} {result[s][1]}" for s in bad))
    if starting:
        parts.append(f"{' / '.join(starting)} 还在起来")
    if good:
        parts.append(f"{' / '.join(good)} 已就绪")
    value = "，".join(parts) + f" · via {rt_name}"
    if bad:
        return ("warn", value, f"看原因：{logs_cmd} {' '.join(bad)}")
    return ("info", value, "")


def infra_summary(
    compose_cmd: Sequence[str],
    services: Sequence[str],
    rt_name: str,
    cwd: str,
    *,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    wait_s: float = 8.0,
) -> tuple:
    """``compose_cmd`` 是 ``[docker, compose, -f, 文件]`` 这一截。在工作线程里调（会轮询几秒）。"""

    def read() -> Dict[str, Tuple[str, str]]:
        try:
            done = run(
                list(compose_cmd) + ["ps", "--all", "--format", "json"] + list(services),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        return parse_ps(done.stdout) if done.returncode == 0 else {}

    # 给人抄的那条命令：``docker compose logs`` / ``docker-compose logs`` / ``podman compose logs`` …
    head = [str(compose_cmd[0]).replace("\\", "/").rsplit("/", 1)[-1]] if compose_cmd else ["docker", "compose"]
    if len(compose_cmd) > 1 and compose_cmd[1] == "compose":
        head.append("compose")
    return summarize(settle(read, services, wait_s=wait_s), services, rt_name, " ".join(head + ["logs"]))
