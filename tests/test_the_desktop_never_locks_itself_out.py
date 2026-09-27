"""全新克隆第一次启动,桌面应用不能把自己锁在门外。

真机日志(Windows,第一次 `python main.py`):

    21:30:42 没有配置共享 API token … 没配对的会被 401
    21:32:00 [安全] IP 自动封禁 300s: 127.0.0.1 (50 次失败请求/60s)
    21:32:32 [安全] 已拦截被封禁 IP: 127.0.0.1   ← 此后几百行,直到 Ctrl+C

链条是三个 bug 叠在一起:

1. 本机自签令牌只在 galaxy_gateway 的**完整** lifespan 里签;真实启动路径
   (main.py → launcher)只跑那个 lifespan 的一半,令牌**从来没签出来过**;
2. 鉴权默认开着,桌面壳找不到令牌 → 每个请求 401;
3. IP 封禁不豁免本机(旁边的限速、输入校验都豁免了),一分钟 50 次 401 就把
   127.0.0.1 自己封了,面板与后端之间的全部通讯 403。

第二次启动"看起来干净",只是因为第一次顺手从 .env.example 复制出的 .env 里写着
GALAXY_AUTH_ENABLED=false —— 鉴权被关了,不是问题修好了。

这里逐条钉住,都走真实代码:真的签令牌、真的起 ASGI 应用、真的截住拉桌面壳的 Popen。
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

import core.auth as auth


@pytest.fixture
def fresh_clone(tmp_path, monkeypatch):
    """全新克隆的环境:没有 .env,没配令牌,没设鉴权开关。"""
    for k in ("GALAXY_API_TOKEN", "GALAXY_API_TOKENS", "GALAXY_AUTH_ENABLED", "GALAXY_MODE", "GALAXY_DATA_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(auth, "_auth_config_validated", False)
    return tmp_path


# ── 1. 令牌:真实启动路径必须在拉起桌面壳之前签好 ─────────────────────────────────


def test_a_fresh_clone_starts_with_auth_on_and_no_token_which_is_the_real_machine_state(fresh_clone):
    """先把真机那一刻的状态复现出来,后面的修复才有意义。"""
    assert auth.auth_posture() == {"enabled": True, "token": "missing"}
    assert not (fresh_clone / "data" / "api_token.json").exists()


def test_phase_3_signs_the_local_token_before_the_desktop_shell_is_launched(fresh_clone):
    from core.system_orchestrator import StartupPhase, SystemOrchestrator

    orch = SystemOrchestrator()
    result = orch._run_phase_3_env_checks()

    token_file = fresh_clone / "data" / "api_token.json"
    assert token_file.is_file(), "Phase 3 跑完令牌还没签 —— 桌面壳一起来就会 401"
    assert json.loads(token_file.read_text(encoding="utf-8"))["token"]
    assert result.phase is StartupPhase.ENV_CHECKS
    # 启动输出如实说出鉴权状态 —— 第一次/第二次启动的区别以前一个字都没提
    assert "鉴权开着(本机令牌已就绪)" in (result.said or ""), result.said
    # Phase 3 在 Phase 6(拉起桌面壳)之前
    assert StartupPhase.ENV_CHECKS.value < StartupPhase.DESKTOP_SURFACE.value


def test_the_signed_token_is_accepted_by_the_server(fresh_clone):
    from core.system_orchestrator import SystemOrchestrator

    SystemOrchestrator()._run_phase_3_env_checks()
    token = json.loads((fresh_clone / "data" / "api_token.json").read_text(encoding="utf-8"))["token"]
    assert token in auth.get_active_tokens()


def test_when_auth_is_off_the_startup_line_says_so_and_why(fresh_clone, monkeypatch):
    from core.system_orchestrator import SystemOrchestrator

    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
    result = SystemOrchestrator()._run_phase_3_env_checks()
    assert "鉴权关着(GALAXY_AUTH_ENABLED=false)" in (result.said or ""), result.said


def test_production_without_a_token_still_refuses_to_start(fresh_clone, monkeypatch):
    """修复不能把原来该拦的拦松了:生产模式缺令牌,以前在 lifespan 里直接抛,现在同样失败。"""
    from core.system_orchestrator import PhaseStatus, SystemOrchestrator

    monkeypatch.setenv("GALAXY_MODE", "production")
    result = SystemOrchestrator()._run_phase_3_env_checks()
    assert result.status is PhaseStatus.FAILED
    assert "没有可用令牌" in (result.said or ""), result.said


def test_the_launcher_also_signs_before_serving():
    """绕开编排器直接起后端的路径,也不能带着"鉴权开着、零令牌"对外服务。"""
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "launcher", "services.py"), encoding="utf-8"
    ).read()
    head = src.split("server = uvicorn.Server(_uvi_config)")[0]
    assert "ensure_auth_config_validated()" in head.split("# === 步骤 7")[-1]


# ── 2. 桌面壳和后端必须看同一个令牌文件 ───────────────────────────────────────────


def _launch_desktop_shell(monkeypatch, project_root):
    """真跑 Phase 6,截住最后那个 Popen,拿到传给桌面壳的环境变量。"""
    from core.system_orchestrator import SystemOrchestrator

    electron_dir = project_root / "electron"
    (electron_dir / "node_modules" / "electron").mkdir(parents=True)
    (electron_dir / "package.json").write_text("{}", encoding="utf-8")

    # 只把"编排器算项目根"那一处指到临时目录。整个替换 os.path.dirname 会连
    # auth.local_token_dir() 里的 dirname 一起换掉,测到的就不是真实行为了。
    import core.system_orchestrator as orch_mod

    real_dirname = os.path.dirname
    orch_file = os.path.abspath(orch_mod.__file__)
    core_dir = real_dirname(orch_file)

    def _dirname(p):
        # project_root = dirname(dirname(__file__)):内层照常得到 core/,外层把 core/ 映到临时目录
        return str(project_root) if p == core_dir else real_dirname(p)

    monkeypatch.setattr("core.system_orchestrator.os.path.dirname", _dirname)
    monkeypatch.setattr("core.electron_launch_guard.already_running", lambda: False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm" if "npm" in name else "/usr/bin/node")
    monkeypatch.setattr("core.electron_launch_guard.electron_package_intact", lambda _d: True)

    seen = {}

    class _FakeProc:
        pid = 4242
        stdout = None

        def poll(self):
            return None

    def _popen(argv, **kw):
        seen["argv"] = argv
        seen["env"] = kw.get("env") or {}
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", _popen)
    SystemOrchestrator()._run_phase_6_desktop_surface()
    return seen


@pytest.mark.real_desktop_surface  # 真跑 Phase 6;Popen 已截住,不会真装 npm / 起 Electron
def test_the_desktop_shell_is_told_exactly_where_the_token_lives(fresh_clone, monkeypatch):
    seen = _launch_desktop_shell(monkeypatch, fresh_clone)
    assert seen, "Phase 6 没走到拉起桌面壳那一步 —— 测试环境没搭对"
    data_dir = seen["env"].get("GALAXY_DATA_DIR")
    assert data_dir and os.path.isabs(data_dir), data_dir
    # 与后端写令牌的位置是同一个目录
    assert os.path.join(data_dir, "api_token.json") == os.path.abspath(auth._local_token_path())


@pytest.mark.real_desktop_surface
def test_an_explicit_data_dir_is_passed_through_untouched(fresh_clone, monkeypatch, tmp_path_factory):
    mine = str(tmp_path_factory.mktemp("my_data"))
    monkeypatch.setenv("GALAXY_DATA_DIR", mine)
    seen = _launch_desktop_shell(monkeypatch, fresh_clone)
    assert seen["env"]["GALAXY_DATA_DIR"] == mine


# ── 3. IP 封禁:不封本机,5xx 不算客户端的错,远端照样封 ──────────────────────────


def _app_that_always_answers(status_code: int):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from core.security_middleware import IPBlockList, create_ip_block_middleware

    app = FastAPI()

    @app.get("/api/perception/desktop/frame")
    async def frame():
        return JSONResponse({"detail": "x"}, status_code=status_code)

    blocks = create_ip_block_middleware(app, IPBlockList())
    return app, blocks


def _hammer(app, host: str, n: int):
    from starlette.testclient import TestClient

    with TestClient(app, client=(host, 50000)) as c:
        return [c.get("/api/perception/desktop/frame").status_code for _ in range(n)]


def test_the_desktop_on_localhost_is_never_banned_by_its_own_401s():
    """真机那一幕:桌面壳在本机连续拿 401。旧代码第 50 次之后全变 403。"""
    app, blocks = _app_that_always_answers(401)
    codes = _hammer(app, "127.0.0.1", 120)
    assert 403 not in codes, "本机被自己封了 —— 面板与后端的通讯会全部断掉"
    assert set(codes) == {401}
    assert not blocks.is_blocked("127.0.0.1")


def test_a_remote_client_hammering_401_is_still_banned():
    """修复不能把保护拿掉:远端照样封。"""
    app, blocks = _app_that_always_answers(401)
    codes = _hammer(app, "203.0.113.7", 60)
    assert 403 in codes, "远端连续失败没被封 —— 保护被拆掉了"
    assert blocks.is_blocked("203.0.113.7")


def test_server_errors_are_not_counted_against_the_client():
    """5xx 是服务端自己的问题(模型没就绪、下游挂了),不能因此把来访者封掉。"""
    app, blocks = _app_that_always_answers(503)
    codes = _hammer(app, "203.0.113.8", 80)
    assert 403 not in codes
    assert not blocks.is_blocked("203.0.113.8")


def test_loopback_banning_can_still_be_forced_for_testing(monkeypatch):
    monkeypatch.setenv("GALAXY_IP_BLOCK_LOOPBACK", "1")
    app, _ = _app_that_always_answers(401)
    assert 403 in _hammer(app, "127.0.0.1", 60)
