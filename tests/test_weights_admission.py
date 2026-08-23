"""权重准入:下载源、格式、自带代码,三维互不冒充。

这道闸挡的是**唯一一条不需要任何注入就能被利用**的路径:
``trust_remote_code=True`` 会执行模型仓库自带的 ``.py``,而下载源默认是第三方镜像
且没有哈希校验。它不走 ``SafeExecutor``,所以容器隔离对它无效。
"""

from __future__ import annotations

import json

import pytest

from core import weights_admission as wa


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每条用例自己钉死前提,不靠"这台机器恰好没设什么"。

    (环境耦合探测器会把依赖 ambient 状态的用例揪出来 —— 这里从一开始就不留口子。)
    """
    for key in (
        "GALAXY_TRUST_REMOTE_CODE",
        "GALAXY_WEIGHTS_HOSTS",
        "GALAXY_WEIGHTS_ALLOW_PICKLE",
        "HF_ENDPOINT",
    ):
        monkeypatch.delenv(key, raising=False)


def _model_dir(tmp_path, *, fmt="safetensors", code=None):
    """造一个模型目录。``code`` 是 {文件名: 内容} 的自带代码。"""
    d = tmp_path / "model"
    d.mkdir(exist_ok=True)
    suffix = {"safetensors": ".safetensors", "gguf": ".gguf", "pickle": ".bin"}[fmt]
    (d / f"weights{suffix}").write_bytes(b"\x00" * 8)
    for name, body in (code or {}).items():
        (d / name).write_text(body, encoding="utf-8")
    return d


# ══════════════════════════════════════════════════════════════════════════
# A. 判定取值:"判不出来"不能被当成"允许"
# ══════════════════════════════════════════════════════════════════════════


def test_a01_unverified_is_not_allowed():
    """三个取值里只有 admitted 放行 —— unverified 是"我没看到",不是"没问题"。"""
    assert wa.WeightsAdmission(verdict="unverified").allowed is False
    assert wa.WeightsAdmission(verdict="denied").allowed is False
    assert wa.WeightsAdmission(verdict="admitted").allowed is True


def test_a02_defaults_assume_the_worst():
    """拿不到判据时不能让人以为自带代码是被审过的。"""
    fresh = wa.WeightsAdmission()
    assert fresh.remote_code is False
    assert fresh.verdict == "unverified"
    assert fresh.pinned is False


def test_a03_verdict_vocabulary_is_closed():
    """取值表是唯一定义处,不能有第二份会漂移的列表。"""
    assert wa.ADMISSION_VERDICTS == ("admitted", "denied", "unverified")


# ══════════════════════════════════════════════════════════════════════════
# B. 下载来源
# ══════════════════════════════════════════════════════════════════════════


def test_b01_host_comes_from_the_variable_that_actually_drives_downloads(monkeypatch):
    """判据必须问 HF_ENDPOINT —— 那是 huggingface_hub 真正读的那一个。

    自己另攒一套镜像配置的话,报告里说的主机会和实际下载的主机漂移。
    """
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    assert wa.download_host() == "hf-mirror.com"


def test_b02_unset_endpoint_means_official():
    assert wa.download_host() == "huggingface.co"


def test_b03_host_not_on_the_list_is_denied(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_ENDPOINT", "https://evil.example.com")
    d = _model_dir(tmp_path)
    decision = wa.evaluate("some/model", local_path=str(d))
    assert decision.verdict == "denied"
    assert "evil.example.com" in decision.reason


def test_b04_empty_allowlist_does_not_mean_allow_all(monkeypatch):
    """留空 = 用默认表。**不是**"没配就放开" —— 那是这类白名单最常见的失效方式。"""
    monkeypatch.setenv("GALAXY_WEIGHTS_HOSTS", "")
    assert wa.allowed_hosts() == wa.DEFAULT_WEIGHT_HOSTS
    assert "evil.example.com" not in wa.allowed_hosts()


def test_b05_mirror_is_on_the_default_list_on_purpose():
    """国内镜像在列是刻意的(否则国内下不动),但这**不代表它可信** ——
    正因为它是第三方,自带代码那一维才必须默认拒。"""
    assert "hf-mirror.com" in wa.DEFAULT_WEIGHT_HOSTS


# ══════════════════════════════════════════════════════════════════════════
# C. 权重格式
# ══════════════════════════════════════════════════════════════════════════


def test_c01_pickle_is_denied_by_default(tmp_path):
    """pickle 反序列化即执行代码 —— 这是历次模型投毒事件的载体。"""
    d = _model_dir(tmp_path, fmt="pickle")
    decision = wa.evaluate("some/model", local_path=str(d))
    assert decision.verdict == "denied"
    assert decision.fmt == "pickle"


def test_c02_pickle_can_be_opened_explicitly(monkeypatch, tmp_path):
    """少数老模型只有 .bin,得给一条显式的路 —— 但必须是显式的。"""
    monkeypatch.setenv("GALAXY_WEIGHTS_ALLOW_PICKLE", "1")
    d = _model_dir(tmp_path, fmt="pickle")
    assert wa.evaluate("some/model", local_path=str(d)).verdict == "admitted"


@pytest.mark.parametrize("fmt", ["safetensors", "gguf"])
def test_c03_safe_formats_pass(tmp_path, fmt):
    d = _model_dir(tmp_path, fmt=fmt)
    decision = wa.evaluate("some/model", local_path=str(d))
    assert decision.verdict == "admitted"
    assert decision.fmt == fmt


def test_c04_safetensors_wins_over_leftover_bin(tmp_path):
    """同目录里残留的 .bin 不会被 transformers 读到(它优先 safetensors),
    所以不能因为看见一个 .bin 就把整个模型判死。"""
    d = _model_dir(tmp_path, fmt="safetensors")
    (d / "pytorch_model.bin").write_bytes(b"\x00")
    assert wa.detect_format(str(d)) == "safetensors"


def test_c05_no_local_path_is_unknown_not_safe():
    """远端 repo 还没下 → 看不到文件 → unknown。不能当成"没问题"。"""
    assert wa.detect_format(None) == "unknown"
    assert wa.evaluate("some/model").verdict == "unverified"


# ══════════════════════════════════════════════════════════════════════════
# D. 自带代码:默认一个都不许
# ══════════════════════════════════════════════════════════════════════════


def test_d01_remote_code_is_off_by_default(tmp_path):
    """这一条是整个模块存在的理由。"""
    d = _model_dir(tmp_path, code={"modeling_x.py": "print('hi')"})
    decision = wa.evaluate("some/model", local_path=str(d))
    assert decision.remote_code is False
    assert "默认不执行" in decision.reason


def test_d02_allowlist_admits_only_the_listed_model(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXY_TRUST_REMOTE_CODE", "trusted/model")
    d = _model_dir(tmp_path, code={"modeling_x.py": "x = 1"})
    assert wa.evaluate("trusted/model", local_path=str(d)).remote_code is True
    assert wa.evaluate("other/model", local_path=str(d)).remote_code is False


def test_d03_wildcard_is_allowed_but_reported(monkeypatch, tmp_path):
    """'*' 得给(否则用户会直接去改源码,那更糟),但报告必须如实标出来。"""
    monkeypatch.setenv("GALAXY_TRUST_REMOTE_CODE", "*")
    d = _model_dir(tmp_path, code={"m.py": "x = 1"})
    assert wa.evaluate("anything/at-all", local_path=str(d)).remote_code is True
    assert wa.weights_report()["remote_code_wildcard"] is True


def test_d04_unknown_format_never_admits_remote_code(monkeypatch):
    """登记过,但这次看不到本地文件 —— 不能凭"登记过"就放行执行。"""
    monkeypatch.setenv("GALAXY_TRUST_REMOTE_CODE", "trusted/model")
    decision = wa.evaluate("trusted/model", local_path=None)
    assert decision.remote_code is False


# ══════════════════════════════════════════════════════════════════════════
# E. 指纹钉子:挡 rug-pull
# ══════════════════════════════════════════════════════════════════════════


def test_e01_fingerprint_changes_when_code_changes(tmp_path):
    d = _model_dir(tmp_path, code={"modeling_x.py": "x = 1"})
    before = wa.remote_code_fingerprint(str(d))
    (d / "modeling_x.py").write_text("import os; os.system('rm -rf /')", encoding="utf-8")
    assert wa.remote_code_fingerprint(str(d)) != before


def test_e02_no_code_is_distinguishable_from_cannot_tell(tmp_path):
    """ "目录里没有 .py"是**确定的**,"路径拿不到"是判不出来 —— 两者不能同一个取值。"""
    d = _model_dir(tmp_path)
    assert wa.remote_code_fingerprint(str(d)) == "none"
    assert wa.remote_code_fingerprint(None) == ""


def test_e03_changed_code_is_refused(monkeypatch, tmp_path):
    """登记过 + 钉过指纹 + 上游改了 → 拒。这就是 rug-pull 的形状。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GALAXY_TRUST_REMOTE_CODE", "trusted/model")
    d = _model_dir(tmp_path, code={"modeling_x.py": "x = 1"})

    assert wa.pin_remote_code("trusted/model", wa.remote_code_fingerprint(str(d))) is True
    assert wa.evaluate("trusted/model", local_path=str(d)).remote_code is True

    (d / "modeling_x.py").write_text("import socket  # 后加的", encoding="utf-8")
    after = wa.evaluate("trusted/model", local_path=str(d))
    assert after.remote_code is False
    assert after.pinned is True
    assert "指纹不一致" in after.reason


def test_e04_pinning_is_never_automatic(monkeypatch, tmp_path):
    """加载路径**不能**自动钉 —— 自动钉等于"第一次见到什么就信什么",
    那样只挡得住"后来改了",挡不住"一开始就是坏的"。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GALAXY_TRUST_REMOTE_CODE", "trusted/model")
    d = _model_dir(tmp_path, code={"m.py": "x = 1"})

    wa.evaluate("trusted/model", local_path=str(d))
    assert wa.pinned_fingerprint("trusted/model") == ""


def test_e05_unreadable_pin_file_does_not_crash_the_gate(monkeypatch, tmp_path):
    """钉子文件坏了要按"没有钉子"处理,不能让整个加载路径炸掉。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "weights_remote_code_pins.json").write_text("{ broken", encoding="utf-8")
    assert wa.pinned_fingerprint("any/model") == ""


def test_e06_pins_survive_a_round_trip(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert wa.pin_remote_code("a/b", "deadbeef") is True
    assert wa.pinned_fingerprint("a/b") == "deadbeef"
    raw = json.loads((tmp_path / "runtime" / "weights_remote_code_pins.json").read_text())
    assert raw == {"a/b": "deadbeef"}


# ══════════════════════════════════════════════════════════════════════════
# F. 加载点真的问了判据 —— 否则就是"看起来接上了,其实没有"
# ══════════════════════════════════════════════════════════════════════════


def _code_only(source: str) -> str:
    """去掉整行注释。

    否则这条用例会被**解释这个洞的注释**本身触发 —— 注释里必然要写出
    ``trust_remote_code=True`` 才能说清楚问题是什么。
    """
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))


def test_f01_the_dangerous_call_site_no_longer_hardcodes_true():
    """``trust_remote_code=True`` 这个字面量必须已经从加载点的**代码**里消失。"""
    import inspect

    from core.local_model_backends import TransformersBackend

    body = _code_only(inspect.getsource(TransformersBackend.load_model))
    assert "trust_remote_code=True" not in body
    assert "ensure_admitted" in body


def test_f02_a_refusal_is_not_reported_as_a_load_failure():
    """拒绝必须与"加载失败"分开 —— 混在一起,运维只会当成偶发故障去"修掉"。"""
    import inspect

    from core.local_model_backends import TransformersBackend

    body = inspect.getsource(TransformersBackend.load_model)
    assert "except WeightsRejected" in body


def test_f04_denied_raises_rather_than_returning_a_flag(tmp_path):
    d = _model_dir(tmp_path, fmt="pickle")
    with pytest.raises(wa.WeightsRejected):
        wa.ensure_admitted("some/model", local_path=str(d))


# ══════════════════════════════════════════════════════════════════════════
# G. 开关登记齐全 —— 没登记 = 面板上改不了
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "key",
    ["GALAXY_TRUST_REMOTE_CODE", "GALAXY_WEIGHTS_HOSTS", "GALAXY_WEIGHTS_ALLOW_PICKLE"],
)
def test_g01_switches_are_registered_in_the_schema(key):
    from core.routes.config_schema_registry import CONFIG_SCHEMA

    assert key in CONFIG_SCHEMA


@pytest.mark.parametrize(
    "key",
    ["GALAXY_TRUST_REMOTE_CODE", "GALAXY_WEIGHTS_HOSTS", "GALAXY_WEIGHTS_ALLOW_PICKLE"],
)
def test_g02_switches_reach_the_panel(key):
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / ("electron/renderer/panel/src/components/SettingsTab.tsx")
    assert f"'{key}'" in src.read_text(encoding="utf-8")


def test_g03_report_is_readonly_and_says_the_global_posture():
    report = wa.weights_report()
    assert report["remote_code_allowlist_size"] == 0
    assert report["pickle_allowed"] is False
    assert "model" not in report
