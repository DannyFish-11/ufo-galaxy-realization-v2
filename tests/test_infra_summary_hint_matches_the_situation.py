"""总结卡"降级"行里基础设施那一项的建议,要和它上面那一行说的是同一件事。

真机(Windows,Podman 已装、虚机没起):

    ⚠ 基础设施 · Podman   Podman 未就绪 — Podman 虚机未就绪 — 试 `podman machine start` 后重跑
    ...
    降级   基础设施 · Podman → 装 Docker/Podman 后重跑即恢复

总结卡叫一个已经装好 Podman 的人去装 Podman。
"""

from launcher import services as svc


def test_installed_but_not_running_gets_the_start_command_not_install():
    hint = svc.infra_summary_hint("已安装,但没在运行 — 虚机没起来,试 `podman machine start` 后重跑")
    assert hint is not None
    assert "podman machine start" in hint
    assert "装 Docker" not in hint


def test_docker_desktop_not_started():
    hint = svc.infra_summary_hint("已安装,但没在运行 — 手动启动 Docker Desktop 后重跑")
    assert hint == "手动启动 Docker Desktop 后重跑"


def test_not_installed_is_told_to_install():
    hint = svc.infra_summary_hint(
        "未安装 Docker/Podman — 依赖基础设施的节点将跳过（不影响桌面）",
        "启用全部节点：装 Docker 或 Podman 后重跑 — https://x",
    )
    assert "装 Docker 或 Podman" in hint


def test_api_socket_down_uses_the_socket_fix_from_the_note():
    hint = svc.infra_summary_hint("Podman 引擎在,但 compose 连不上它 — rc", "试 `podman machine start` 后重跑")
    assert hint == "试 `podman machine start` 后重跑"


def test_first_pull_is_not_told_to_install():
    hint = svc.infra_summary_hint(
        "首次镜像下载中（Podman 后台静默拉取）", "见 logs/docker.log；本轮先跳过依赖节点，下次启动即生效"
    )
    assert hint == "镜像在后台下载,下次启动即生效"


def test_unrecognised_failure_gets_no_made_up_advice():
    assert svc.infra_summary_hint("compose 失败:未能判定原因", "见 logs/docker.log") is None


def test_the_summary_line_is_wired_to_the_situational_hint():
    import inspect

    src = inspect.getsource(svc)
    assert 'hint="装 Docker/Podman 后重跑即恢复"' not in src
    assert "infra_summary_hint(d_value, d_note)" in src
