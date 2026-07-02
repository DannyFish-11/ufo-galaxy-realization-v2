"""tests/test_background_pull_verifies_loadable.py
=====================================================
用户实测反馈:升级到最新 Ollama 后，gemma4:e2b 依然 404，且日志里也没再
看到 HuggingFace 回退被触发的迹象——怀疑 background_pull() 的"已安装"判断
被一次失败的历史拉取悄悄短路了。

根因:background_pull() 之前只看 ``GET /api/tags`` 里【有没有这个名字】就
判定"已安装、跳过拉取"。但一次失败的拉取(比如旧版本 Ollama 解析 manifest
失败、网络中断等)偶尔会在 Ollama 本地留下一个【能列出名字、但打不开】的
残缺 manifest 条目——若只看 /api/tags 就直接放行，这个坏掉的条目会【永久】
拦住后续所有重试和 HuggingFace 回退：每次重启都被误判"已安装"，实际每次
对话都还是 404，且 HF 回退代码根本没有被跑到过(因为函数在最早的"已安装"
分支就 return 了)。

修复:在判定"已安装"前，额外用 ``POST /api/show`` 核实这个名字是否真的能
打开；打不开就当作未安装，继续走拉取(以及失败后的 HuggingFace 回退)。
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import core.model_selection as ms


class _FakeResp:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json


class _FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_background_pull_and_wait(tag: str, fake_subprocess_run, fake_get, fake_post):
    with patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch("shutil.which", return_value="/usr/bin/ollama"), \
         patch("httpx.get", side_effect=fake_get), \
         patch("httpx.post", side_effect=fake_post):
        ms.background_pull(tag)
        for t in threading.enumerate():
            if t.name == "GalaxyModelPull":
                t.join(timeout=5)


def test_broken_manifest_entry_triggers_retry_not_silent_skip():
    """/api/tags 有名字但 /api/show 核实不通过 —— 必须重新拉取,不能悄悄跳过。"""
    pull_attempted = []

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ollama", "pull"]:
            pull_attempted.append(cmd)
            return _FakeProc(0)
        return _FakeProc(0, stdout="ollama version is 0.30.8")

    def fake_get(url, **kwargs):
        if url.endswith("/api/tags"):
            return _FakeResp(200, {"models": [{"name": "gemma4:e2b"}]})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kwargs):
        if url.endswith("/api/show"):
            return _FakeResp(404)  # 残缺条目,打不开
        raise AssertionError(f"unexpected POST {url}")

    _run_background_pull_and_wait("gemma4:e2b", fake_run, fake_get, fake_post)

    assert pull_attempted, (
        "/api/show 核实失败时必须重新尝试拉取，不能因为 /api/tags 里有名字就"
        "永久跳过(这会让坏掉的残缺条目拦死后续所有重试和 HF 回退)"
    )


def test_genuinely_loadable_model_skips_pull():
    """/api/show 核实通过时,才应该真正跳过拉取(避免无意义的重复 pull)。"""
    pull_attempted = []

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ollama", "pull"]:
            pull_attempted.append(cmd)
        return _FakeProc(0)

    def fake_get(url, **kwargs):
        if url.endswith("/api/tags"):
            return _FakeResp(200, {"models": [{"name": "gemma4:e2b"}]})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kwargs):
        if url.endswith("/api/show"):
            return _FakeResp(200, {"modelfile": "FROM ..."})  # 真的能打开
        raise AssertionError(f"unexpected POST {url}")

    _run_background_pull_and_wait("gemma4:e2b", fake_run, fake_get, fake_post)

    assert not pull_attempted, "已验证真实可用的模型不该被重新拉取"


def test_show_check_exception_also_triggers_retry():
    """/api/show 请求本身抛异常(网络问题等)时,同样应保守地当作"未安装"处理。"""
    pull_attempted = []

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ollama", "pull"]:
            pull_attempted.append(cmd)
            return _FakeProc(0)
        return _FakeProc(0, stdout="ollama version is 0.30.8")

    def fake_get(url, **kwargs):
        if url.endswith("/api/tags"):
            return _FakeResp(200, {"models": [{"name": "gemma4:e2b"}]})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kwargs):
        raise ConnectionError("ollama daemon busy")

    _run_background_pull_and_wait("gemma4:e2b", fake_run, fake_get, fake_post)

    assert pull_attempted, "/api/show 核实本身出异常时也应保守地重新尝试拉取"


def test_broken_manifest_then_pull_fails_still_reaches_hf_fallback():
    """完整链路:残缺条目 → 判定未安装 → 重新拉取仍失败 → 必须继续走到 HF 回退,
    而不是在"已安装"这一步就提前退出、永远碰不到 HF 回退代码。"""
    hf_fallback_called = []

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ollama", "pull"]:
            return _FakeProc(1, stderr="Error: pull model manifest: file does not exist")
        return _FakeProc(0, stdout="ollama version is 0.30.8")

    def fake_get(url, **kwargs):
        if url.endswith("/api/tags"):
            return _FakeResp(200, {"models": [{"name": "gemma4:e2b"}]})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, **kwargs):
        if url.endswith("/api/show"):
            return _FakeResp(404)
        raise AssertionError(f"unexpected POST {url}")

    def fake_hf_fallback(tag):
        hf_fallback_called.append(tag)
        return None

    with patch("subprocess.run", side_effect=fake_run), \
         patch("shutil.which", return_value="/usr/bin/ollama"), \
         patch("httpx.get", side_effect=fake_get), \
         patch("httpx.post", side_effect=fake_post), \
         patch("core.hf_ollama_import_fallback.download_and_import_to_ollama", side_effect=fake_hf_fallback):
        ms.background_pull("gemma4:e2b")
        for t in threading.enumerate():
            if t.name == "GalaxyModelPull":
                t.join(timeout=5)

    assert hf_fallback_called == ["gemma4:e2b"], (
        "残缺条目被正确识别为未安装、重新拉取又失败后，必须真正走到 HF 回退这一步"
    )


def test_ollama_not_on_path_prints_reason_instead_of_silent_skip(capsys):
    """真机复现:用户反馈"看到[尝试]任何 HuggingFace 下载模型,Ollama 上没找到
    模型就默认直接跳过了"——根因是 shutil.which("ollama") 找不到命令时,函数
    直接 return,不打印任何东西(pull 和 HF 回退都需要 ollama 命令,确实都跳过
    了没错,但控制台一片沉默，用户完全不知道发生了什么、也不知道该怎么办)。
    修复后必须至少打印一条说明原因的提示。
    """
    with patch("shutil.which", return_value=None):
        ms.background_pull("gemma4:e2b")
        for t in threading.enumerate():
            if t.name == "GalaxyModelPull":
                t.join(timeout=5)

    out = capsys.readouterr().out
    assert "未检测到 ollama 命令" in out, (
        f"找不到 ollama 命令时必须打印清楚的原因，不能彻底沉默。实际输出: {out!r}"
    )


def test_empty_tag_still_silently_returns():
    """tag 为空是正常的"没有主脑模型可拉"状态(比如用户还没选主脑)，不算故障，
    维持静默返回，不应该被上面的修复误伤成也打印一堆东西。"""
    with patch("shutil.which", return_value="/usr/bin/ollama"), \
         patch("subprocess.run") as mock_run:
        ms.background_pull("")
        for t in threading.enumerate():
            if t.name == "GalaxyModelPull":
                t.join(timeout=1)

    mock_run.assert_not_called()
