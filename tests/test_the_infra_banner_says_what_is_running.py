"""基础设施那一行横幅照实说；compose 里的服务真起得来。

全面排查第 6 轮真跑（沙箱里第一次有了 Docker）：横幅写「nats / redis / qdrant / neo4j / mongodb 已就绪」，实际

- neo4j 在反复重启 —— ``NEO4J_PLUGINS=["apoc", "gds"]``，5.x 认的名字是 ``graph-data-science``，``gds`` 一写它连起都起不来；
- qdrant 永远 unhealthy —— 健康检查调 ``curl``，qdrant 镜像里没有 curl 也没有 wget（只有 bash）；
- 横幅只看 ``compose up -d`` 的退出码，容器里的服务起没起来它不看。

这里钉住三件事：横幅按各服务此刻的状态说话（``launcher/compose_health.py``）；compose 文件里 neo4j 的插件名
是它认的名字、内存设置用 5.x 的名字；qdrant 的健康检查不调镜像里没有的工具。
"""

from __future__ import annotations

import functools
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from launcher import compose_health as ch

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = [
    "docker-compose.yml",
    *sorted(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "deploy/compose").glob("*.yml")),
]
INFRA = ["nats", "redis", "qdrant", "neo4j", "mongodb"]

#: neo4j 5.x 镜像的入口脚本认的插件名（插件名写错它直接退出，报的就是这张表）
NEO4J_PLUGINS = {"apoc", "apoc-extended", "bloom", "graph-algorithms", "graph-data-science", "graphql", "n10s"}


@functools.lru_cache(maxsize=None)
def _services(rel: str) -> dict:
    return (yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8")) or {}).get("services") or {}


def _env(svc: dict) -> dict:
    env = svc.get("environment") or {}
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    return dict(str(e).split("=", 1) for e in env if "=" in str(e))


def _ps(*rows) -> str:
    """新版 compose 的输出：一行一个对象。"""
    return "\n".join(json.dumps({"Service": s, "State": st, "Health": h}) for s, st, h in rows)


# ── 横幅照实说 ────────────────────────────────────────────────────────────────


def test_both_ps_formats_are_read():
    lines = _ps(("nats", "running", "healthy"), ("neo4j", "restarting", ""))
    array = json.dumps([{"Service": "nats", "State": "running", "Health": "healthy"}])
    assert ch.parse_ps(lines) == {"nats": ("running", "healthy"), "neo4j": ("restarting", "")}
    assert ch.parse_ps(array) == {"nats": ("running", "healthy")}
    assert ch.parse_ps("") == {} and ch.parse_ps("not json") == {}


def test_all_up_and_healthy_is_ready():
    out = ch.summarize(
        ch.settle(lambda: ch.parse_ps(_ps(*[(s, "running", "healthy") for s in INFRA])), INFRA),
        INFRA,
        "Docker",
        "docker compose logs",
    )
    assert out == ("ok", "nats / redis / qdrant / neo4j / mongodb 已就绪 · via Docker", "")


def test_the_round_6_scene_is_said_as_it_is():
    """neo4j 反复重启、qdrant 健康检查不过：点名、算降级，告诉人去哪看。"""
    rows = [(s, "running", "healthy") for s in ("nats", "redis", "mongodb")]
    rows += [("qdrant", "running", "unhealthy"), ("neo4j", "restarting", "")]
    status, value, note = ch.summarize(
        ch.settle(lambda: ch.parse_ps(_ps(*rows)), INFRA), INFRA, "Docker", "docker compose logs"
    )
    assert status == "warn"
    assert "neo4j 反复重启" in value and "qdrant 健康检查不过" in value
    assert "已就绪" not in value.split("，")[0], "坏的要排在最前面说"
    assert note == "看原因：docker compose logs qdrant neo4j"


def test_a_crash_loop_seen_once_is_remembered():
    """起不来的容器在「重启中」和「刚起来」之间来回切：只看最后一眼会看漏。"""
    frames = iter(
        [
            _ps(("neo4j", "running", "starting")),
            _ps(("neo4j", "restarting", "")),
            _ps(("neo4j", "running", "starting")),
        ]
    )
    t = [0.0]
    result = ch.settle(
        lambda: ch.parse_ps(next(frames)),
        ["neo4j"],
        wait_s=2.0,
        every_s=1.0,
        sleep=lambda s: t.__setitem__(0, t[0] + s),
        clock=lambda: t[0],
    )
    assert result == {"neo4j": (ch.BAD, "反复重启")}


def test_still_starting_at_the_deadline_is_not_a_degradation():
    t = [0.0]
    result = ch.settle(
        lambda: ch.parse_ps(_ps(("neo4j", "running", "starting"), ("nats", "running", ""))),
        ["nats", "neo4j"],
        wait_s=3.0,
        sleep=lambda s: t.__setitem__(0, t[0] + s),
        clock=lambda: t[0],
    )
    status, value, _ = ch.summarize(result, ["nats", "neo4j"], "Docker", "docker compose logs")
    assert status == "info" and value == "neo4j 还在起来，nats 已就绪 · via Docker"


def test_a_service_that_was_never_created_is_named():
    result = ch.settle(lambda: ch.parse_ps(_ps(("nats", "running", ""))), ["nats", "neo4j"])
    assert result["neo4j"] == (ch.BAD, "没建出来")


def test_unreadable_states_do_not_claim_ready():
    """compose 太旧、不认 --format json：只说「已拉起」，不替它说「已就绪」。"""

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unknown flag: --format")

    status, value, _ = ch.infra_summary(["docker", "compose", "-f", "x.yml"], INFRA, "Docker", ".", run=run)
    assert status == "ok" and "已拉起" in value and "已就绪" not in value


def test_the_logs_hint_matches_the_compose_flavour():
    def run(cmd, **kw):
        assert cmd[-6:] == ["ps", "--all", "--format", "json", "nats", "neo4j"], cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=_ps(("nats", "running", ""), ("neo4j", "exited", "")))

    _, _, note = ch.infra_summary(
        ["/usr/bin/docker", "compose", "-f", "x.yml"], ["nats", "neo4j"], "Docker", ".", run=run, wait_s=0
    )
    assert note == "看原因：docker compose logs neo4j"
    _, _, note = ch.infra_summary(
        ["/usr/local/bin/podman-compose", "-f", "x.yml"], ["nats", "neo4j"], "Podman", ".", run=run, wait_s=0
    )
    assert note == "看原因：podman-compose logs neo4j"


def test_the_launcher_asks_compose_health_before_saying_ready():
    src = (REPO_ROOT / "launcher" / "services.py").read_text(encoding="utf-8")
    assert "infra_summary" in src
    assert "已就绪 · via {rt_name}" not in src, "横幅又只凭 up -d 的退出码说「已就绪」了"


# ── compose 里的服务真起得来 ──────────────────────────────────────────────────


@pytest.mark.parametrize("rel", COMPOSE_FILES)
def test_neo4j_plugins_are_names_neo4j_knows(rel):
    svc = _services(rel).get("neo4j")
    if not svc:
        pytest.skip(f"{rel} 里没有 neo4j")
    raw = _env(svc).get("NEO4J_PLUGINS")
    if raw is None:
        return
    names = set(json.loads(raw))
    assert names <= NEO4J_PLUGINS, f"{rel}: neo4j 不认 {sorted(names - NEO4J_PLUGINS)} —— 写错一个它就起不来"


@pytest.mark.parametrize("rel", COMPOSE_FILES)
def test_neo4j_memory_settings_use_the_5x_names(rel):
    svc = _services(rel).get("neo4j")
    if not svc:
        pytest.skip(f"{rel} 里没有 neo4j")
    old = [k for k in _env(svc) if k.startswith("NEO4J_dbms_memory_")]
    assert not old, f"{rel}: {old} 是 4.x 的名字，5.x 每次启动都报弃用（改成 NEO4J_server_memory_*）"


@pytest.mark.parametrize("rel", COMPOSE_FILES)
def test_qdrant_healthcheck_uses_only_what_its_image_has(rel):
    """qdrant 镜像里没有 curl / wget / nc，只有 bash —— 调别的，健康检查永远不过。"""
    svc = _services(rel).get("qdrant")
    if not svc or not svc.get("healthcheck"):
        pytest.skip(f"{rel} 里没有 qdrant 的健康检查")
    test = svc["healthcheck"]["test"]
    probe = " ".join(test) if isinstance(test, list) else str(test)
    for tool in ("curl", "wget", " nc "):
        assert tool not in f" {probe} ", f"{rel}: qdrant 的健康检查调了镜像里没有的 {tool.strip()}"
    assert "/dev/tcp/" in probe and "/readyz" in probe
