"""第 9 轮从真机 / 真跑日志里收的两处「循环被占住」,和一处「Unclosed client session」的来源。

* ``logs/lumiv.log``:「事件循环被卡住 1.7 秒 —— 卡在 core/tts/kokoro_engine.py available ← _try_kokoro ←
  _select_engine〔正在 import kokoro_onnx〕」。Edge 云端不可达 → 运行期降级 → 在循环线程上重选下一家引擎;
  状态接口第一次问「当前引擎是谁」也会在循环上把引擎选一遍。
* SYSTEM_STATUS 第 7 节那条偶发的「Unclosed client session」:在场桥共享的 IPC 会话换了循环就丢引用、不关,
  被回收时 aiohttp 记一条。
"""

from __future__ import annotations

import asyncio
import threading


def test_runtime_demotion_reselects_off_the_loop(monkeypatch):
    from core import speech_output as so

    seen = {}

    def demote(reason="", failed_engine=None):
        seen["thread"] = threading.current_thread()
        return "next-engine"

    monkeypatch.setattr(so, "demote_current_engine", demote)

    async def go():
        return threading.current_thread(), await so._demote_off_loop("edge 不可达", object())

    loop_thread, got = asyncio.run(go())
    assert got == "next-engine" and seen["thread"] is not loop_thread


def test_asking_which_engine_does_not_select_one_on_the_callers_loop(monkeypatch):
    from core import speech_output as so

    monkeypatch.setattr(so, "_engine", None)
    monkeypatch.setattr(so, "_engine_failed", False)
    warmed = []
    monkeypatch.setattr(so, "warm_speech_engine", lambda: warmed.append(True))
    monkeypatch.setattr(so, "_select_engine", lambda: (_ for _ in ()).throw(AssertionError("在调用方线程上选了引擎")))
    assert so.current_engine_name() == "" and warmed == [True]


def test_no_tts_engine_is_demoted_synchronously_inside_a_coroutine():
    import inspect

    from core import speech_output as so

    src = inspect.getsource(so)
    assert "= demote_current_engine(" not in src, "运行期降级要经 _demote_off_loop(工作线程)"


def test_a_session_from_an_old_loop_is_closed_when_the_loop_changes():
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge as Bridge

    async def first():
        return Bridge._ipc_session()

    old = asyncio.run(first())

    async def second():
        new = Bridge._ipc_session()
        for _ in range(3):
            await asyncio.sleep(0)  # 让后台的关闭跑完
        return new

    new = asyncio.run(second())
    assert old is not new and old.closed, "换了循环的旧会话要关掉,不只是丢引用"


def test_model_downloads_run_in_a_worker_thread(monkeypatch, tmp_path):
    """``_download_gguf`` / ``_download_transformers`` 名字是 async、里面全是同步的网络与磁盘调用 —— 真跑停跳 0.7~0.9 秒。"""
    from core import huggingface_model_manager as hf

    seen = {}

    def blocking(self, *args):
        seen["thread"] = threading.current_thread()
        return "entry"

    monkeypatch.setattr(hf.HuggingFaceModelManager, "_gguf_blocking", blocking, raising=False)
    monkeypatch.setattr(hf.HuggingFaceModelManager, "_transformers_blocking", blocking, raising=False)
    mgr = hf.HuggingFaceModelManager.__new__(hf.HuggingFaceModelManager)

    async def go():
        loop_thread = threading.current_thread()
        a = await mgr._download_gguf("m", hf.ModelFamily.LLM, "q4", str(tmp_path))
        b = await mgr._download_transformers("m", hf.ModelFamily.LLM, str(tmp_path))
        return loop_thread, a, b

    loop_thread, a, b = asyncio.run(go())
    assert (a, b) == ("entry", "entry") and seen["thread"] is not loop_thread


def test_the_target_policy_engine_is_imported_before_the_first_dispatch():
    import inspect

    import launcher.services as svc

    assert "core.runtime.execution_target_policy_engine" in inspect.getsource(svc._warm_routes)


def test_modules_first_used_on_the_loop_are_imported_beside_it_first():
    """第 12 轮真跑:启动那一阵别的线程在载 sklearn,循环上第一次 import 抢不到解释器(第一次对话 2.5 秒、设备连上 2.9 秒)。"""
    import importlib
    import inspect

    import launcher.first_use_imports as warm
    import launcher.services as svc

    assert "warm_first_use()" in inspect.getsource(svc._warm_routes)
    for name in (
        "core.execution_policy",
        "core.execution.intent_profile",
        "galaxy_gateway.android_bridge",
        "core.node_declared_class",
    ):
        assert name in warm.FIRST_USE_MODULES, name
    for name in warm.FIRST_USE_MODULES:
        importlib.import_module(name)  # 名字写错了,预热就一声不响地什么都没做


def test_the_first_use_sites_still_import_what_is_warmed():
    """预热的名单对着真在循环上 import 的那几处:那几处改了名字,这里要跟着改。"""
    import pathlib

    repo = pathlib.Path(__file__).resolve().parent.parent
    sites = {
        "core/desktop_presence_runtime.py": "core.execution_policy",
        "core/openclawd.py": "core.execution",
        "galaxy_gateway/routes/websocket.py": "android_bridge",
        "core/node_declared_class.py": "core.node_actions",
    }
    for path, name in sites.items():
        assert name in (repo / path).read_text(encoding="utf-8"), (path, name)
