"""tests/test_deploy_surfaces_resolve.py — compose 文件指到的东西真的在，监控真的抓得到。

复测查出两件事，都是「文件写着、其实跑不起来」：

1. ``deploy/compose/`` 下的 compose 文件（``full.yml`` 是 ``python main.py --docker-full`` 用的，
   ``production.yml`` 是部署文档里的生产入口）把构建上下文写成 ``.``、挂载写成 ``./core`` 这类。
   Compose 按**文件所在目录**解析相对路径，于是它们指向 ``deploy/compose/``：
   构建找不到 Dockerfile，``./core`` 会拿一个空目录盖住容器里的代码，``env_file: .env`` 找不到。
2. ``config/prometheus.yml`` 抓 ``galaxy:8080`` / ``gateway:8000``，可哪份 compose 里的服务都在 9000；
   网关的 Prometheus 出口是 ``/gateway/metrics``，``/metrics`` 在网关上是 404。
   结果一个指标都没抓到过，``galaxy_legacy_dispatch_total`` 有计数器却没人看得见（路线图 C3）。

这里静态核对：路径按 Compose 的规则解析之后存在；抓取目标的端口是服务真正监听的端口；
告警规则引用的指标真的有代码在导出；规则文件真的挂进了 prometheus 读的目录。
"""

from __future__ import annotations

import fnmatch
import functools
import re
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = [
    "docker-compose.yml",
    *sorted(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "deploy/compose").glob("*.yml")),
]


@functools.lru_cache(maxsize=None)
def _load(rel: str) -> dict:
    return yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8")) or {}


def _services(rel: str) -> dict:
    return _load(rel).get("services") or {}


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _relative_refs(rel: str) -> Iterator[Tuple[str, str, str]]:
    """(服务, 种类, 相对路径)：构建上下文、env_file、绑定挂载源。"""
    for name, svc in _services(rel).items():
        build = svc.get("build")
        if isinstance(build, str):
            yield name, "context", build
        elif isinstance(build, dict) and build.get("context"):
            yield name, "context", build["context"]
        for env in _as_list(svc.get("env_file")):
            yield name, "env_file", env if isinstance(env, str) else env.get("path", "")
        for vol in _as_list(svc.get("volumes")):
            src = vol.split(":", 1)[0] if isinstance(vol, str) else (vol.get("source") or "")
            if src.startswith("."):
                yield name, "volume", src


@pytest.mark.parametrize("compose", COMPOSE_FILES)
def test_relative_paths_resolve_to_real_files(compose):
    base = (REPO_ROOT / compose).parent
    broken: List[str] = []
    for service, kind, ref in _relative_refs(compose):
        target = (base / ref).resolve()
        if kind == "env_file":
            # .env 由用户从 .env.example 生成，可以还不存在；但它必须指向仓库根那一份
            if target != (REPO_ROOT / ".env").resolve():
                broken.append(f"{service}: env_file {ref} → {target}（应指向仓库根的 .env）")
        elif not target.exists():
            broken.append(f"{service}: {kind} {ref} → {target} 不存在")
        elif kind == "context":
            build = _services(compose)[service]["build"]
            dockerfile = build.get("dockerfile", "Dockerfile") if isinstance(build, dict) else "Dockerfile"
            if not (target / dockerfile).is_file():
                broken.append(f"{service}: 构建上下文 {target} 里没有 {dockerfile}")
    assert not broken, f"{compose} 按 Compose 规则（相对本文件所在目录）解析后:\n" + "\n".join(sorted(set(broken))[:20])


def _listening_ports(svc: dict) -> set:
    ports = {str(p) for p in _as_list(svc.get("expose"))}
    for mapping in _as_list(svc.get("ports")):
        ports.add(str(mapping).split("/")[0].rsplit(":", 1)[-1])
    for arg in _as_list(svc.get("command")):
        if re.fullmatch(r"\d{2,5}", str(arg)):
            ports.add(str(arg))
    health = " ".join(map(str, _as_list((svc.get("healthcheck") or {}).get("test"))))
    ports.update(re.findall(r"localhost:(\d+)", health))
    return ports


def test_every_scrape_target_is_a_port_the_service_listens_on():
    prom = _load("config/prometheus.yml")
    services = _services("deploy/compose/production.yml")
    wrong = []
    for job in prom.get("scrape_configs", []):
        for static in job.get("static_configs", []):
            for target in static.get("targets", []):
                host, _, port = target.partition(":")
                if host in services and port not in _listening_ports(services[host]):
                    wrong.append(
                        f"{job['job_name']}: {target}（{host} 监听 {sorted(_listening_ports(services[host]))}）"
                    )
    assert not wrong, "prometheus 抓的端口不是服务在听的端口:\n" + "\n".join(wrong)


def test_the_gateway_is_scraped_where_it_exports_metrics():
    prom = _load("config/prometheus.yml")
    job = next(j for j in prom["scrape_configs"] if j["job_name"] == "galaxy-gateway")
    src = (REPO_ROOT / "galaxy_gateway/routes/health.py").read_text(encoding="utf-8")
    assert f'@router.get("{job["metrics_path"]}")' in src, f"网关没有 {job['metrics_path']} 这个出口"


def test_every_metric_an_alert_uses_is_exported_somewhere():
    rules = _load("config/prometheus_alerts.yml")
    exprs = [r["expr"] for g in rules["groups"] for r in g["rules"]]
    names = {m for e in exprs for m in re.findall(r"\b(galaxy_[a-z0-9_]+)\b", e)}
    assert names, "规则里没有引用任何 galaxy_* 指标 —— 判据自身失效"
    exported = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (REPO_ROOT / "galaxy_gateway").rglob("*.py")
    )
    exported += "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (REPO_ROOT / "core/routes").rglob("*.py")
    )
    missing = sorted(n for n in names if f'"{n}"' not in exported)
    assert not missing, f"告警引用了没人导出的指标（规则永远不会触发）: {missing}"


def test_the_rules_file_is_mounted_where_prometheus_reads_rules():
    globs = _load("config/prometheus.yml").get("rule_files") or []
    mounts = [
        v.split(":")[1]
        for v in _as_list(_services("deploy/compose/production.yml")["prometheus"].get("volumes"))
        if isinstance(v, str) and "prometheus_alerts.yml" in v
    ]
    assert mounts, "production.yml 的 prometheus 没挂告警规则文件"
    assert any(fnmatch.fnmatch(m, g) for m in mounts for g in globs), f"挂载点 {mounts} 不在 rule_files {globs} 里"
