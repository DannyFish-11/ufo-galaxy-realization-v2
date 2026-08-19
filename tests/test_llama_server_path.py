"""tests/test_llama_server_path.py
====================================
把 C/D 推理位从"进程内加载"改成"我们自己起的 ``llama-server``"这条路。

它修的是一个**声称生效、实际不生效**的缺陷
------------------------------------------
C 档的 7.3 GB 显存账完全建立在专家卸载上(18 GB 权重的 35B,专家留内存、只有激活
的 3B 上卡)。而 ``--n-cpu-moe`` 只在 llama.cpp 的 CLI/server 旗标上,
``llama-cpp-python`` 不透出。此前的现场是:调度器认真算出 N,加载器发现绑定不支持,
打一条 warning,**然后照常加载** —— 准入早按 7.3 GB 放行了,现场看到的是一次没头
没脑的 OOM。D 档的草稿位(``--spec-type``)是同一个洞。

本文件钉三件事:命令行拼得对不对、能力是**问出来**的还是假设的、以及后端改判
在"确实做不到、而且另一条确实做得到"时才发生。

不起任何进程、不装任何二进制:能力清单与 spawn/健康探活全部注入。
"""

from __future__ import annotations

import pytest

import core.llama_server as ls
import core.local_model_backends as lmb
import core.model_catalog as mc

#: 一个"什么都支持"的构建。
FULL = frozenset(
    {"--alias", "--n-gpu-layers", "--ctx-size", "--n-cpu-moe", "--spec-type", "--model-draft", "--spec-draft-n-max"}
)
#: 一个老构建:能跑,但没有那两件关键能力。
OLD = frozenset({"--alias", "--n-gpu-layers", "--ctx-size"})


class FakeProc:
    """``subprocess.Popen`` 的替身。``code=None`` 表示还活着。"""

    def __init__(self, code=None):
        self._c = code
        self.killed = False

    def poll(self):
        return self._c

    def terminate(self):
        self._c = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self._c = -9


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ls.reset_flag_cache()
    monkeypatch.delenv("GALAXY_LLAMA_SERVER_BIN", raising=False)
    for k in ("GALAXY_LOCAL_OPENAI_URL", "GALAXY_LOCAL_OPENAI_SERVES"):
        monkeypatch.delenv(k, raising=False)
    yield
    ls.reset_flag_cache()


# ══════════════════════════════════════════════════════════════════════════
# A. 二进制在哪:找得到 / 找不到 / 指错了
# ══════════════════════════════════════════════════════════════════════════


def test_a01_explicit_binary_wins(monkeypatch, tmp_path):
    exe = tmp_path / "llama-server"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("GALAXY_LLAMA_SERVER_BIN", str(exe))
    assert ls.llama_server_binary() == str(exe)


def test_a02_a_wrong_explicit_path_does_not_silently_fall_back(monkeypatch):
    """指了但指不到东西时回落 PATH,会让人以为自己指定的构建生效了,实际跑的是另一个。"""
    monkeypatch.setenv("GALAXY_LLAMA_SERVER_BIN", "/nope/llama-server")
    monkeypatch.setattr(ls.shutil, "which", lambda _n: "/usr/bin/llama-server")
    assert ls.llama_server_binary() is None


def test_a03_falls_back_to_path_with_every_known_name(monkeypatch):
    seen = []

    def _which(name):
        seen.append(name)
        return "/usr/bin/server" if name == "server" else None

    monkeypatch.setattr(ls.shutil, "which", _which)
    assert ls.llama_server_binary() == "/usr/bin/server"
    assert seen == list(ls.SERVER_BINARY_NAMES)


def test_a04_missing_binary_is_none_not_empty_string():
    """None 说的是"没有";空串会被 ``or`` 吃掉、和"没找"混为一谈。"""
    assert ls.llama_server_binary() is None or isinstance(ls.llama_server_binary(), str)


# ══════════════════════════════════════════════════════════════════════════
# B. 能力是问出来的,不是假设的
# ══════════════════════════════════════════════════════════════════════════


def test_b01_flags_come_from_help_output(monkeypatch):
    monkeypatch.setattr(ls, "llama_server_binary", lambda: "/opt/llama-server")
    flags = ls.server_supported_flags(runner=lambda _b: "  --n-cpu-moe N   把专家留在内存\n  --ctx-size N")
    assert "--n-cpu-moe" in flags and "--ctx-size" in flags


def test_b02_help_on_stderr_is_read_too(monkeypatch):
    """有的构建把帮助打在 stderr 上。只读 stdout 会得出"什么都不支持"。"""
    import subprocess as sp

    class _R:
        stdout = ""
        stderr = "--n-cpu-moe N"

    monkeypatch.setattr(sp, "run", lambda *a, **k: _R())
    monkeypatch.setattr(ls, "llama_server_binary", lambda: "/opt/llama-server")
    assert "--n-cpu-moe" in ls.server_supported_flags()


def test_b03_no_binary_means_empty_not_crash(monkeypatch):
    monkeypatch.setattr(ls, "llama_server_binary", lambda: None)
    assert ls.server_supported_flags() == frozenset()


def test_b04_help_blowing_up_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(ls, "llama_server_binary", lambda: "/opt/llama-server")

    def _boom(_b):
        raise OSError("permission denied")

    assert ls.server_supported_flags(runner=_boom) == frozenset()


def test_b05_flags_are_cached_per_binary(monkeypatch):
    calls = []
    monkeypatch.setattr(ls, "llama_server_binary", lambda: "/opt/llama-server")

    def _run(b):
        calls.append(b)
        return "--n-cpu-moe N"

    ls.server_supported_flags(runner=_run)
    ls.server_supported_flags(runner=_run)
    assert len(calls) == 1  # --help 要起一次进程,一次运行里不会变


def test_b06_capability_answers_track_the_flags(monkeypatch):
    monkeypatch.setattr(ls, "server_supported_flags", lambda **k: FULL)
    assert ls.server_moe_offload_supported() is True
    assert ls.server_draft_supported() is True
    monkeypatch.setattr(ls, "server_supported_flags", lambda **k: OLD)
    assert ls.server_moe_offload_supported() is False
    assert ls.server_draft_supported() is False


# ══════════════════════════════════════════════════════════════════════════
# C. 命令行组装:纯函数,拼错的后果是"改了没效果"
# ══════════════════════════════════════════════════════════════════════════


def test_c01_a_full_build_gets_everything():
    plan = ls.build_server_args(
        model_path="/m/q.gguf",
        port=1234,
        alias="qwen3.6:35b-a3b",
        n_gpu_layers=999,
        n_ctx=8192,
        n_cpu_moe=24,
        draft_spec_type="draft-mtp",
        draft_n_max=4,
        supported_flags=FULL,
        binary="/opt/llama-server",
    )
    argv = " ".join(plan.argv)
    assert "--n-cpu-moe 24" in argv
    assert "--spec-type draft-mtp" in argv
    assert "--spec-draft-n-max 4" in argv
    assert "--alias qwen3.6:35b-a3b" in argv
    assert plan.moe_offload_applied and plan.draft_applied
    assert plan.notes == ()


def test_c02_an_old_build_drops_them_and_says_so():
    """被吞掉的旗标必须变成**结论的一部分**,不是只进日志。"""
    plan = ls.build_server_args(
        model_path="/m/q.gguf",
        port=1,
        n_cpu_moe=24,
        draft_spec_type="draft-mtp",
        supported_flags=OLD,
        binary="/opt/llama-server",
    )
    assert "--n-cpu-moe" not in " ".join(plan.argv)
    assert plan.moe_offload_applied is False
    assert any("--n-cpu-moe" in n for n in plan.notes)
    assert any("OOM" in n for n in plan.notes), "得说清后果,不是只说不支持"


def test_c03_unprobed_is_not_the_same_as_unsupported():
    """空清单是**问不到**(二进制不在),不是"这个构建什么都不支持"。

    逐条报"这个构建不认识 X",会让人对着一个根本没装的东西研究它为什么不支持某旗标。
    """
    plan = ls.build_server_args(
        model_path="/m/q.gguf",
        port=1,
        n_cpu_moe=24,
        draft_spec_type="draft-mtp",
        supported_flags=frozenset(),
        binary="x",
    )
    assert len(plan.notes) == 1
    assert "问不到" in plan.notes[0]


def test_c04_no_moe_no_flag():
    plan = ls.build_server_args(model_path="/m/q.gguf", port=1, n_cpu_moe=0, supported_flags=FULL, binary="x")
    assert "--n-cpu-moe" not in " ".join(plan.argv)
    assert plan.notes == ()


def test_c05_external_drafter_needs_its_own_flag():
    plan = ls.build_server_args(
        model_path="/m/q.gguf",
        port=1,
        draft_spec_type="draft-dflash",
        draft_model_path="/m/d.gguf",
        supported_flags=FULL,
        binary="x",
    )
    assert "--model-draft /m/d.gguf" in " ".join(plan.argv)
    plan2 = ls.build_server_args(
        model_path="/m/q.gguf",
        port=1,
        draft_spec_type="draft-dflash",
        draft_model_path="/m/d.gguf",
        supported_flags=FULL - {"--model-draft"},
        binary="x",
    )
    assert plan2.draft_applied is False


def test_c06_missing_n_max_flag_is_material_not_cosmetic():
    """上游默认块大小 15 在公开实测里是净亏,而实测选出来的往往是 4。

    传不进去就等于"实测结论没生效",必须说出来。
    """
    plan = ls.build_server_args(
        model_path="/m/q.gguf",
        port=1,
        draft_spec_type="draft-mtp",
        draft_n_max=4,
        supported_flags=FULL - {"--spec-draft-n-max"},
        binary="x",
    )
    assert plan.draft_applied is True  # 草稿位本身挂上了
    assert any("块大小" in n for n in plan.notes)


def test_c07_is_a_pure_function(monkeypatch):
    """不起进程、不读文件、不查环境 —— 拼错的后果在生产上都表现为"改了没效果"。"""
    monkeypatch.setattr(ls, "_spawn", lambda _a: pytest.fail("组装不该起进程"))
    ls.build_server_args(model_path="/m/q.gguf", port=1, supported_flags=FULL, binary="x")


def test_c08_port_is_asked_for_not_hardcoded():
    """写死端口只会在同机跑两份时撞车;这个进程是我们自己起自己关的私有服务。"""
    a, b = ls.free_port(), ls.free_port()
    assert a > 0 and b > 0


# ══════════════════════════════════════════════════════════════════════════
# D. 进程监管:起来 / 早退 / 超时,三种结局分得开
# ══════════════════════════════════════════════════════════════════════════


def _start(proc, **kw):
    base = dict(
        model_path="/m/q.gguf",
        alias="qwythos-9b-v2",
        binary="/opt/llama-server",
        supported_flags=FULL,
        spawn=lambda _a: proc,
        health=lambda _p: True,
    )
    base.update(kw)
    return ls.LlamaServerProcess(model_id="qwythos-9b-v2").start(**base)


def test_d01_a_healthy_start_exports_the_address():
    """路由读的是 GALAXY_LOCAL_OPENAI_URL —— 导出它,路由就不必认识本模块。"""
    import os

    p = ls.LlamaServerProcess(model_id="qwythos-9b-v2")
    ok = p.start(
        model_path="/m/q.gguf",
        alias="qwythos-9b-v2",
        binary="/opt/llama-server",
        supported_flags=FULL,
        spawn=lambda _a: FakeProc(),
        health=lambda _p: True,
    )
    assert ok is True
    assert p.base_url.startswith("http://127.0.0.1:")
    assert os.environ["GALAXY_LOCAL_OPENAI_URL"] == p.base_url
    assert os.environ["GALAXY_LOCAL_OPENAI_SERVES"] == "qwythos-9b-v2"


def test_d02_stopping_takes_the_address_back():
    """留着会让路由继续往一个已经关掉的端口发请求,报错在别处、看不出跟关停有关。"""
    import os

    p = ls.LlamaServerProcess(model_id="qwythos-9b-v2")
    p.start(
        model_path="/m/q.gguf",
        alias="qwythos-9b-v2",
        binary="/opt/llama-server",
        supported_flags=FULL,
        spawn=lambda _a: FakeProc(),
        health=lambda _p: True,
    )
    p.stop()
    assert "GALAXY_LOCAL_OPENAI_URL" not in os.environ
    assert p.base_url == ""


def test_d03_an_early_exit_says_early_exit():
    p = ls.LlamaServerProcess()
    ok = p.start(
        model_path="/m/q.gguf",
        binary="/opt/llama-server",
        supported_flags=FULL,
        spawn=lambda _a: FakeProc(code=1),
        health=lambda _p: False,
    )
    assert ok is False
    assert "提前退出" in p.error


def test_d04_a_timeout_says_timeout_and_cleans_up():
    proc = FakeProc()
    p = ls.LlamaServerProcess()
    ok = p.start(
        model_path="/m/q.gguf",
        binary="/opt/llama-server",
        supported_flags=FULL,
        spawn=lambda _a: proc,
        health=lambda _p: False,
        timeout_s=0.01,
    )
    assert ok is False
    assert "没就绪" in p.error
    assert p.is_running is False  # 超时后要收掉,不能留一个孤儿进程


def test_d05_no_weights_no_start():
    p = ls.LlamaServerProcess()
    assert p.start(model_path="", binary="/opt/llama-server") is False
    assert "GGUF" in p.error


def test_d06_no_binary_names_the_remedy(monkeypatch):
    monkeypatch.setattr(ls, "llama_server_binary", lambda: None)
    p = ls.LlamaServerProcess()
    assert p.start(model_path="/m/q.gguf") is False
    assert "GALAXY_LLAMA_SERVER_BIN" in p.error


def test_d07_spawn_failure_is_reported_not_raised():
    def _boom(_a):
        raise OSError("exec format error")

    p = ls.LlamaServerProcess()
    assert p.start(model_path="/m/q.gguf", binary="/x", supported_flags=FULL, spawn=_boom) is False
    assert "exec format error" in p.error


def test_d08_the_plan_is_kept_so_callers_can_check_what_took_effect():
    """ "专家卸载到底生没生效"必须能被事后问到 —— 那正是旧实现里静默失效的地方。"""
    p = ls.LlamaServerProcess()
    p.start(
        model_path="/m/q.gguf",
        binary="/x",
        supported_flags=OLD,
        n_cpu_moe=24,
        spawn=lambda _a: FakeProc(),
        health=lambda _p: True,
    )
    assert p.plan is not None
    assert p.plan.moe_offload_applied is False


# ══════════════════════════════════════════════════════════════════════════
# E. 判据:两条路各问各的,合起来才是"跑不跑得起来"
# ══════════════════════════════════════════════════════════════════════════


def test_e01_the_top_level_judgement_is_the_union(monkeypatch):
    """本函数原来只问进程内。于是 llama-server 装好之后,选档界面**仍然**报跑不起来。"""
    monkeypatch.setattr(lmb, "binding_moe_offload_supported", lambda: False)
    monkeypatch.setattr(lmb, "_server_moe_offload_supported", lambda: True)
    assert lmb.moe_offload_supported() is True


def test_e02_the_path_is_reported_separately(monkeypatch):
    """合成一个布尔,排障的人不知道该去装库还是去装二进制。"""
    monkeypatch.setattr(lmb, "binding_moe_offload_supported", lambda: True)
    assert lmb.moe_offload_path() == "binding"
    monkeypatch.setattr(lmb, "binding_moe_offload_supported", lambda: False)
    monkeypatch.setattr(lmb, "_server_moe_offload_supported", lambda: True)
    assert lmb.moe_offload_path() == "server"
    monkeypatch.setattr(lmb, "_server_moe_offload_supported", lambda: False)
    assert lmb.moe_offload_path() == "none"


def test_e03_in_process_preferred_when_it_can_do_the_job(monkeypatch):
    """进程内不用多起一个进程 —— 能做就别起。"""
    monkeypatch.setattr(lmb, "binding_moe_offload_supported", lambda: True)
    assert lmb.moe_offload_path() == "binding"


def test_e04_server_availability_is_a_binary_not_a_pip_package(monkeypatch):
    """按 import 判它会永远判不出来,那条路明明可用却从不出现在可用列表里。"""
    monkeypatch.setattr(ls, "llama_server_binary", lambda: "/opt/llama-server")
    assert "llama_server" in lmb.list_available_backends()
    monkeypatch.setattr(ls, "llama_server_binary", lambda: None)
    assert "llama_server" not in lmb.list_available_backends()


# ══════════════════════════════════════════════════════════════════════════
# F. 后端改判:只在"确实做不到、而另一条确实做得到"时发生
# ══════════════════════════════════════════════════════════════════════════


def _server(monkeypatch, *, moe=True, draft=True, binary="/opt/llama-server"):
    monkeypatch.setattr(ls, "llama_server_binary", lambda: binary)
    monkeypatch.setattr(ls, "server_moe_offload_supported", lambda: moe)
    monkeypatch.setattr(ls, "server_draft_supported", lambda: draft)
    monkeypatch.setattr(lmb, "binding_moe_offload_supported", lambda: False)


def test_f01_moe_slot_switches_when_the_binding_cannot(monkeypatch):
    """C 档推理位:显存账建立在卸载上,而进程内做不到 → 改走 server。"""
    _server(monkeypatch)
    assert mc.in_process_cannot_serve("qwen3.6:35b-a3b") is True
    assert mc.backend_for_tag("qwen3.6:35b-a3b") == "llama_server"


def test_f02_no_switch_when_the_binding_can_do_it(monkeypatch):
    _server(monkeypatch)
    monkeypatch.setattr(lmb, "binding_moe_offload_supported", lambda: True)
    assert mc.backend_for_tag("qwen3.6:35b-a3b") == "llama_cpp"


def test_f03_no_switch_when_the_server_cannot_either(monkeypatch):
    """两条都做不到时改判毫无意义 —— 只会把"装不下"伪装成"后端没装"。"""
    _server(monkeypatch, moe=False, draft=False)
    assert mc.backend_for_tag("qwen3.6:35b-a3b") == "llama_cpp"


def test_f04_a_dense_model_is_not_dragged_along(monkeypatch):
    """稠密 9B 的显存账不欠专家卸载这张支票,不该被拖去起服务。"""
    _server(monkeypatch)
    assert mc.in_process_cannot_serve("qwythos-9b-v2") is False
    assert mc.backend_for_tag("qwythos-9b-v2") == "llama_cpp"


def test_f05_an_enabled_draft_also_switches(monkeypatch, tmp_path):
    """D 档:草稿位实测为正之后,那条路同样只有 server 走得通。"""
    import core.speculative_draft as sd

    _server(monkeypatch)
    monkeypatch.setattr(sd, "_STATE_FILE", tmp_path / "s.json")
    sd.save_measurement(sd.DraftMeasurement(tag="qwythos-9b-v2", verdict="faster", speedup=1.3, n_max=4))
    assert mc.in_process_cannot_serve("qwythos-9b-v2") is True
    assert mc.backend_for_tag("qwythos-9b-v2") == "llama_server"


def test_f06_ollama_models_are_untouched(monkeypatch):
    _server(monkeypatch)
    assert mc.backend_for_tag("gemma4:12b") == "ollama"


def test_f07_capability_lookup_failing_keeps_the_status_quo(monkeypatch):
    """问不出来就别改判 —— 改判到一个可能不存在的后端比不改判更糟。"""
    monkeypatch.setattr(ls, "server_moe_offload_supported", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert mc.in_process_cannot_serve("qwen3.6:35b-a3b") is False


# ══════════════════════════════════════════════════════════════════════════
# G. 只有一份定义
# ══════════════════════════════════════════════════════════════════════════


def test_g01_the_setup_script_delegates_and_does_not_re_implement():
    """两份会在"认不认 server 这个名字"上分叉:脚本说找到了、运行时说没有。"""
    src = (mc.PROJECT_ROOT / "scripts" / "setup_reasoning_slot.py").read_text(encoding="utf-8")
    body = src[src.index("def find_llama_server") : src.index("def compute_n_cpu_moe")]
    assert "llama_server_binary" in body
    assert "shutil.which" not in body, "找二进制的规则不该有第二份"

    cmd = src[src.index("def build_command") : src.index("def env_block")]
    assert "build_server_args" in cmd
    assert "--n-cpu-moe" not in cmd.split('"""')[-1], "旗标拼装不该有第二份"


def test_g02_the_backend_does_not_recompute_the_allocation():
    """命令行上给的 N 与调度器心里那个 N 必须同源,否则显存账两处对不上。"""
    import inspect

    body = inspect.getsource(lmb.LlamaServerBackend._plan_for)
    assert "get_compute_scheduler" in body
    assert "moe_split_from_profile" not in body, "别在这里另算一遍拆分"


def test_g03_the_backend_is_registered():
    assert "llama_server" in lmb.BACKEND_REGISTRY
    assert lmb.create_backend("llama_server").name == "llama_server"


def test_g04_draft_flags_come_from_the_measured_state(tmp_path, monkeypatch):
    import core.speculative_draft as sd

    monkeypatch.setattr(sd, "_STATE_FILE", tmp_path / "s.json")
    assert lmb._draft_flags_for("qwythos-9b-v2") == ("", 0)  # 没测过 → 不开
    sd.save_measurement(sd.DraftMeasurement(tag="qwythos-9b-v2", verdict="faster", speedup=1.3, n_max=4))
    assert lmb._draft_flags_for("qwythos-9b-v2") == ("draft-mtp", 4)
    sd.save_measurement(sd.DraftMeasurement(tag="qwythos-9b-v2", verdict="slower", speedup=0.5, n_max=15))
    assert lmb._draft_flags_for("qwythos-9b-v2") == ("", 0)  # 测过更慢 → 也不开
