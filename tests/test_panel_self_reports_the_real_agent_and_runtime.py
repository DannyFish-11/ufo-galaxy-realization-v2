"""面板左下「接上了什么」里本体与容器那两行:写**实际的那个东西**,不写形容词。

所有者的原话:「容器就显示实际，是 docker 就显示 docker，是 podman 就显示 podman」、
「本体那块儿也是显示后端实际的 Agent …… 那就显示他的这个名字就好」。

两条事实的出处都是 ``GET /api/v1/panel/self``:

* ``agent`` —— 正在答话的那个 Agent 实例的类名(OpenClawd)。只**读**模块里的单例,
  不调 ``get_openclawd()``:为了报个名字把整个智能体建出来,是这一行最不该有的副作用。
* ``container_runtime`` —— ``core.container_runtime.current_runtime()``,与启动器同一个先后
  (环境 > 选过且装着 > 只装了一个),但**只读**:不写选择记录、不弹交互、不跑 ``docker info``。
"""

from __future__ import annotations

import pytest


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes.panel import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


@pytest.fixture
def no_agent(monkeypatch):
    import core.openclawd as oc

    monkeypatch.setattr(oc, "_openclawd_instance", None)
    return oc


def _only(monkeypatch, installed, env="", saved=""):
    """假装这台机器上装了 ``installed`` 里的运行时;选择记录一旦被写就当场失败。"""
    import core.container_runtime as cr

    monkeypatch.setattr(cr.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None)
    monkeypatch.setattr(cr, "load_choice", lambda: saved)
    if env:
        monkeypatch.setenv("GALAXY_CONTAINER_RUNTIME", env)
    else:
        monkeypatch.delenv("GALAXY_CONTAINER_RUNTIME", raising=False)

    def _no_write(*_a, **_k):
        raise AssertionError("只读探测把选择记录写了 —— 面板每打开一次就改一次启动器的选择")

    monkeypatch.setattr(cr, "save_choice", _no_write)
    return cr


def test_the_agent_row_names_the_class_without_building_the_agent(no_agent, monkeypatch):
    def _no_build():
        raise AssertionError("为了报个名字把智能体建出来了")

    monkeypatch.setattr(no_agent, "get_openclawd", _no_build)
    _only(monkeypatch, {"podman"})
    body = _client().get("/api/v1/panel/self").json()
    assert body["agent"] == "OpenClawd"
    assert body["agent_running"] is False
    assert no_agent._openclawd_instance is None


def test_the_agent_row_names_the_instance_that_is_actually_running(no_agent, monkeypatch):
    class Kimi:  # 换一个 Agent 跑,名字就跟着换 —— 不是写死的字符串
        pass

    monkeypatch.setattr(no_agent, "_openclawd_instance", Kimi())
    _only(monkeypatch, set())
    body = _client().get("/api/v1/panel/self").json()
    assert body["agent"] == "Kimi" and body["agent_running"] is True


@pytest.mark.parametrize(
    ("installed", "env", "saved", "expected"),
    [
        ({"docker"}, "", "", "docker"),
        ({"podman"}, "", "", "podman"),
        ({"docker", "podman"}, "", "podman", "podman"),
        ({"docker", "podman"}, "docker", "podman", "docker"),
        # 两个都装、谁也没选过:启动器非交互时拒绝静默挑一个,这里也不替它挑
        ({"docker", "podman"}, "", "", ""),
        # 选过的那个已经卸了:只剩一个就是它
        ({"docker"}, "", "podman", "docker"),
        (set(), "", "", ""),
    ],
)
def test_the_container_row_names_the_runtime_actually_in_use(monkeypatch, installed, env, saved, expected):
    cr = _only(monkeypatch, installed, env=env, saved=saved)
    assert cr.current_runtime() == expected


def test_the_endpoint_says_docker_or_podman_and_empty_when_there_is_none(no_agent, monkeypatch):
    _only(monkeypatch, {"podman"})
    assert _client().get("/api/v1/panel/self").json()["container_runtime"] == "podman"
    _only(monkeypatch, set())
    assert _client().get("/api/v1/panel/self").json()["container_runtime"] == ""


def test_a_failing_probe_is_none_not_a_500(no_agent, monkeypatch):
    import core.container_runtime as cr

    def _boom():
        raise OSError("which 炸了")

    monkeypatch.setattr(cr, "current_runtime", _boom)
    resp = _client().get("/api/v1/panel/self")
    assert resp.status_code == 200 and resp.json()["container_runtime"] == ""
