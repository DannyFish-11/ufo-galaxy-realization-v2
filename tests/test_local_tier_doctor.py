"""C/D 档体检:二进制发现覆盖真实安装位置,以及"差什么"说得准。

这两档卡的是同一件事 —— llama-server 在不在。而它最常见的装法是从源码编译,
产物落在 build/bin/,**不在 PATH 上**。只查 PATH 会让用户明明装好了系统仍报
"没装",然后去查一个不存在的问题。
"""

from __future__ import annotations

import stat

import pytest

from core import llama_server as ls


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GALAXY_LLAMA_SERVER_BIN", raising=False)
    # 旗标缓存按二进制路径缓存,跨用例会串味
    monkeypatch.setattr(ls, "_flags_cache", None, raising=False)


def _make_binary(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


# ══════════════════════════════════════════════════════════════════════════
# A. 二进制发现
# ══════════════════════════════════════════════════════════════════════════


def test_a01_explicit_env_wins(tmp_path, monkeypatch):
    """ "我知道它在哪"这件事,人比探测权威。"""
    b = _make_binary(tmp_path / "my-build" / "llama-server")
    monkeypatch.setenv("GALAXY_LLAMA_SERVER_BIN", str(b))
    assert ls.llama_server_binary() == str(b)


def test_a02_a_bad_explicit_path_does_not_fall_back_silently(tmp_path, monkeypatch):
    """给了但指不到东西时静默回落 PATH,会让人以为自己指定的构建生效了,
    实际跑的是另一个。"""
    monkeypatch.setenv("GALAXY_LLAMA_SERVER_BIN", str(tmp_path / "nope"))
    assert ls.llama_server_binary() is None


def test_a03_build_dir_is_searched(tmp_path, monkeypatch):
    """从源码编译的产物在 build/bin/ —— 这是最常见的装法,而它不在 PATH 上。"""
    b = _make_binary(tmp_path / "build" / "bin" / "llama-server")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ls.shutil, "which", lambda _n: None)
    assert ls.llama_server_binary() == str(b)


def test_a04_windows_exe_suffix_is_searched(tmp_path, monkeypatch):
    b = _make_binary(tmp_path / "build" / "bin" / "llama-server.exe")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ls.shutil, "which", lambda _n: None)
    assert ls.llama_server_binary() == str(b)


def test_a05_path_still_wins_over_guessed_dirs(tmp_path, monkeypatch):
    """常见目录是**位置猜测**,PATH 是明确的 —— 猜测不该盖过明确的。"""
    _make_binary(tmp_path / "build" / "bin" / "llama-server")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ls.shutil, "which", lambda n: "/usr/bin/llama-server" if n == "llama-server" else None)
    assert ls.llama_server_binary() == "/usr/bin/llama-server"


def test_a06_nothing_anywhere_is_none_not_empty_string(monkeypatch):
    """``None`` 与空串必须可区分:空串是个假路径,会被当成"有"往下传。"""
    monkeypatch.setattr(ls.shutil, "which", lambda _n: None)
    monkeypatch.setattr(ls, "_COMMON_INSTALL_DIRS", ())
    assert ls.llama_server_binary() is None


def test_a07_unreadable_candidate_does_not_crash_discovery(tmp_path, monkeypatch):
    """权限不足/坏链接要换下一个,不能让整条发现路径炸掉。"""
    monkeypatch.setattr(ls.shutil, "which", lambda _n: None)
    monkeypatch.setattr(ls, "_COMMON_INSTALL_DIRS", (str(tmp_path / "does-not-exist"),))

    def _boom(_p):
        raise OSError("permission denied")

    monkeypatch.setattr(ls.os.path, "isfile", _boom)
    assert ls.llama_server_binary() is None


# ══════════════════════════════════════════════════════════════════════════
# B. 体检:说得出"差什么",而且不硬凑
# ══════════════════════════════════════════════════════════════════════════


def _doctor():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "local_tier_doctor.py"
    spec = importlib.util.spec_from_file_location("local_tier_doctor", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_b01_missing_binary_is_the_first_thing_reported(monkeypatch):
    monkeypatch.setattr(ls.shutil, "which", lambda _n: None)
    monkeypatch.setattr(ls, "_COMMON_INSTALL_DIRS", ())
    doc = _doctor()
    facts = doc._collect()
    assert facts["llama_server_binary"] is None
    assert "llama-server" in doc._next_steps(facts)[0]


def test_b02_flags_unprobed_is_not_the_same_as_absent(monkeypatch):
    """二进制不在时旗标是**问不到**,不是"问过了没有"。

    把两者混成 False,报告会说"这个构建没有 --n-cpu-moe" —— 而实际上根本没构建。
    """
    monkeypatch.setattr(ls.shutil, "which", lambda _n: None)
    monkeypatch.setattr(ls, "_COMMON_INSTALL_DIRS", ())
    facts = _doctor()._collect()
    assert facts["llama_server_flags_probed"] is False
    assert facts["llama_server_has_n_cpu_moe"] is None
    assert facts["llama_server_has_spec_type"] is None


def test_b03_the_measurement_step_is_always_listed():
    """实测只能在用户机器上做,数字不能由别处代填 —— 所以这一条不因为
    二进制装好了就消失。"""
    doc = _doctor()
    steps = doc._next_steps(
        {
            "llama_server_binary": "/usr/bin/llama-server",
            "llama_server_has_n_cpu_moe": True,
            "llama_server_has_spec_type": True,
        }
    )
    assert any("probe_models.py --draft" in s for s in steps)


def test_b04_an_old_build_is_called_out_specifically():
    doc = _doctor()
    steps = doc._next_steps(
        {
            "llama_server_binary": "/usr/bin/llama-server",
            "llama_server_has_n_cpu_moe": False,
            "llama_server_has_spec_type": False,
        }
    )
    joined = "\n".join(steps)
    assert "--n-cpu-moe" in joined
    assert "--spec-type" in joined


def test_b05_render_never_crashes_on_missing_facts():
    """任何一处判据问不到都如实记,渲染不能因此炸掉。"""
    assert "体检" in _doctor()._render({})


def test_b06_the_doctor_is_read_only():
    """它不下载、不加载模型、不起服务 —— 体检把机器拖住是不能接受的。"""
    import inspect

    src = inspect.getsource(_doctor())
    for forbidden in ("start(", "download", "from_pretrained", "LlamaServerProcess("):
        assert forbidden not in src
