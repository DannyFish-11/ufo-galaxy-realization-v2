"""模型与 provider 探测：问，而不是猜。

为什么要有这个模块
==================
``core.model_catalog`` 一条记录要填确切 tag、原生模态、权重、**实测运行时显存**、
最长上下文、KV 开销、是不是 MoE。这些数必须是量出来的 —— 模块自己写着
「``0`` = 没人量过 → 退回权重大小（即历史行为，**不臆造数字**）」，并记了臆造的
后果：MiniCPM-o 记 6000 → 8 GB 卡准入判"放得下" → 加载到 11 GB 时 OOM。

云端那张表同理：``base_url`` 对不对、``default_model`` 今天还在不在、这把 key
到底能调哪些 —— 都是**可以问出来的事实**。人肉眼看十几家、几十个型号名，
看不出 ``kimi-k3`` 是不是真的存在。

覆盖矩阵
========
A. 三态可区分：``unreachable``（没问到）≠ ``empty``（问到了、是空的）
B. 本地探测：``/api/tags`` + ``/api/show`` 逐个核实
C. 云端探测：区分 key 没填 / key 被拒 / 这家没有 /models 口
D. 比对：对不上的报出来，全对上返回空
E. 不触网就退化，绝不抛
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.model_probe import (
    PROBE_OUTCOMES,
    CatalogFinding,
    ProbeOutcome,
    audit_provider_catalog,
    format_audit_report,
    probe_local_models,
    probe_provider_models,
)


class _Resp:
    def __init__(self, status: int = 200, payload: Any = None, bad_json: bool = False):
        self.status_code = status
        self._payload = payload
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


class _Client:
    """按 URL 后缀派发的假 httpx 客户端 —— 不触网。"""

    def __init__(self, get_map: Dict[str, Any] = None, post_map: Dict[str, Any] = None, boom: bool = False):
        self.get_map = get_map or {}
        self.post_map = post_map or {}
        self.boom = boom
        self.calls: List[str] = []

    def _pick(self, table, url):
        self.calls.append(url)
        if self.boom:
            raise OSError("network down")
        for suffix, resp in table.items():
            if url.endswith(suffix):
                return resp
        return _Resp(404, {})

    def get(self, url, **kw):
        return self._pick(self.get_map, url)

    def post(self, url, **kw):
        return self._pick(self.post_map, url)

    def close(self):
        pass


class _Cfg:
    def __init__(self, base_url="https://x.invalid/v1", api_key="k", models=(), default_model="", source_type="api"):
        self.base_url = base_url
        self.api_key = api_key
        self.models = list(models)
        self.default_model = default_model
        self.source_type = source_type


# ---------------------------------------------------------------------------
# A. 三态可区分
# ---------------------------------------------------------------------------


class TestGroupAOutcomesAreDistinguishable:
    def test_a01_vocabulary(self) -> None:
        assert set(PROBE_OUTCOMES) == {"ok", "empty", "unreachable", "unauthorized"}

    def test_a02_unreachable_is_not_empty(self) -> None:
        """**这一条是整组的要点。**

        "没问到"和"问到了、答案是空的"混成一个空列表，会把环境问题
        （服务没起）报成"你配的模型都不存在"—— 那是最坏的一种误导。
        """
        assert ProbeOutcome("unreachable").reached is False
        assert ProbeOutcome("empty").reached is True

    def test_a03_ok_is_reached(self) -> None:
        assert ProbeOutcome("ok").reached is True


# ---------------------------------------------------------------------------
# B. 本地探测
# ---------------------------------------------------------------------------


class TestGroupBLocalProbe:
    def test_b01_reads_tags_then_verifies_each_with_show(self) -> None:
        c = _Client(
            get_map={"/api/tags": _Resp(200, {"models": [{"name": "qwen3.6:35b-a3b", "size": 18_000 * 1024 * 1024}]})},
            post_map={
                "/api/show": _Resp(
                    200,
                    {
                        "details": {"parameter_size": "35B", "quantization_level": "Q4_K_M"},
                        "model_info": {"qwen3.context_length": 262144},
                        "capabilities": ["completion", "tools"],
                    },
                )
            },
        )
        outcome, facts = probe_local_models("http://h:1", client=c)
        assert outcome.status == "ok"
        assert len(facts) == 1
        f = facts[0]
        assert (f.tag, f.parameter_size, f.quantization) == ("qwen3.6:35b-a3b", "35B", "Q4_K_M")
        assert f.context_length == 262144
        assert f.size_mb == 18000
        assert "tools" in f.capabilities
        assert f.healthy is True

    def test_b02_context_length_key_is_found_by_suffix(self) -> None:
        """键名带架构前缀（``qwen3.`` / ``gemma3.`` …），写死键名换个架构就恒为 0。"""
        c = _Client(
            get_map={"/api/tags": _Resp(200, {"models": [{"name": "x"}]})},
            post_map={"/api/show": _Resp(200, {"model_info": {"someotherarch.context_length": 4096}})},
        )
        _, facts = probe_local_models("http://h:1", client=c)
        assert facts[0].context_length == 4096

    def test_b03_listed_but_broken_manifest_is_reported_not_hidden(self) -> None:
        """``/api/tags`` 列得出名字 ≠ 装好了。

        失败的拉取会留下能列名、打不开的残缺 manifest。这种条目要**如实报出来**，
        不是悄悄剔除 —— "装了但打不开"是需要被看见的事实。
        """
        c = _Client(
            get_map={"/api/tags": _Resp(200, {"models": [{"name": "broken"}]})},
            post_map={"/api/show": _Resp(500, {})},
        )
        outcome, facts = probe_local_models("http://h:1", client=c)
        assert outcome.status == "ok"
        assert facts[0].healthy is False

    def test_b04_running_but_nothing_installed_is_empty(self) -> None:
        c = _Client(get_map={"/api/tags": _Resp(200, {"models": []})})
        outcome, facts = probe_local_models("http://h:1", client=c)
        assert outcome.status == "empty"
        assert facts == []

    def test_b05_service_down_is_unreachable(self) -> None:
        outcome, facts = probe_local_models("http://h:1", client=_Client(boom=True))
        assert outcome.status == "unreachable"
        assert facts == []


# ---------------------------------------------------------------------------
# C. 云端探测
# ---------------------------------------------------------------------------


class TestGroupCProviderProbe:
    def test_c01_lists_what_the_key_can_actually_call(self) -> None:
        c = _Client(get_map={"/models": _Resp(200, {"data": [{"id": "m-a"}, {"id": "m-b"}]})})
        p = probe_provider_models("acme", _Cfg(), client=c)
        assert p.outcome.status == "ok"
        assert p.models == ("m-a", "m-b")

    def test_c02_no_key_is_not_an_error(self) -> None:
        """key 没填 = 这家没启用，与"填了但不对"必须分开。"""
        p = probe_provider_models("acme", _Cfg(api_key=""), client=_Client())
        assert p.outcome.status == "unreachable"
        assert "没启用" in p.outcome.detail

    @pytest.mark.parametrize("code", [401, 403])
    def test_c03_rejected_key_is_its_own_status(self, code: int) -> None:
        p = probe_provider_models("acme", _Cfg(), client=_Client(get_map={"/models": _Resp(code, {})}))
        assert p.outcome.status == "unauthorized"

    def test_c04_no_models_endpoint_is_not_a_config_error(self) -> None:
        """有的家不提供这个口（如走自有协议的）。**不能**把"这家没这个口"
        说成"你配的模型不存在"—— 那会让排错指向完全错误的方向。"""
        p = probe_provider_models("acme", _Cfg(), client=_Client(get_map={"/models": _Resp(404, {})}))
        assert p.outcome.status == "unreachable"
        assert "不代表配置有错" in p.outcome.detail


# ---------------------------------------------------------------------------
# D. 比对
# ---------------------------------------------------------------------------


class TestGroupDAudit:
    def test_d01_all_matched_returns_empty(self) -> None:
        c = _Client(get_map={"/models": _Resp(200, {"data": [{"id": "m-a"}]})})
        findings = audit_provider_catalog({"acme": _Cfg(models=["m-a"], default_model="m-a")}, client=c)
        assert findings == []

    def test_d02_configured_but_absent_model_is_reported(self) -> None:
        c = _Client(get_map={"/models": _Resp(200, {"data": [{"id": "m-a"}]})})
        findings = audit_provider_catalog({"acme": _Cfg(models=["m-a", "ghost"], default_model="m-a")}, client=c)
        kinds = {f.kind for f in findings}
        assert "model_missing" in kinds
        assert any("ghost" in f.detail for f in findings)

    def test_d03_bad_default_is_called_out_separately(self) -> None:
        """默认型号错 = **每一次调用都会撞**，比多配一个用不到的型号严重得多。"""
        c = _Client(get_map={"/models": _Resp(200, {"data": [{"id": "m-a"}]})})
        findings = audit_provider_catalog({"acme": _Cfg(models=["m-a"], default_model="ghost")}, client=c)
        assert any(f.kind == "default_missing" for f in findings)

    def test_d04_untested_is_reported_not_silently_clean(self) -> None:
        """ "一条都没探到"不是"没问题"，是"没验成"。两者不能都表现为空列表。"""
        findings = audit_provider_catalog({"acme": _Cfg(api_key="")}, client=_Client())
        assert [f.kind for f in findings] == ["untested"]

    def test_d05_local_providers_are_skipped(self) -> None:
        """本地那几家走 probe_local_models，不是 /models。"""
        findings = audit_provider_catalog({"ollama": _Cfg(source_type="local")}, client=_Client())
        assert findings == []

    def test_d06_report_orders_by_severity(self) -> None:
        text = format_audit_report(
            [
                CatalogFinding("a", "untested", "没填 key"),
                CatalogFinding("b", "default_missing", "默认型号不存在"),
            ]
        )
        assert text.index("默认型号对不上") < text.index("没验成")

    def test_d07_empty_report_says_so(self) -> None:
        assert "✅" in format_audit_report([])


# ---------------------------------------------------------------------------
# E. 不触网就退化
# ---------------------------------------------------------------------------


class TestGroupEDegradesInsteadOfRaising:
    def test_e01_local_probe_without_network(self) -> None:
        outcome, facts = probe_local_models()
        assert outcome.status in PROBE_OUTCOMES
        assert isinstance(facts, list)

    def test_e02_provider_probe_never_raises(self) -> None:
        p = probe_provider_models("acme", _Cfg(base_url=""), client=_Client())
        assert p.outcome.status == "unreachable"

    def test_e03_bad_json_is_unreachable_not_a_crash(self) -> None:
        c = _Client(get_map={"/models": _Resp(200, bad_json=True)})
        assert probe_provider_models("acme", _Cfg(), client=c).outcome.status == "unreachable"


# ---------------------------------------------------------------------------
# F. provider 配置的静态自洽性（不触网也能查的那几类）
# ---------------------------------------------------------------------------


class TestGroupFProviderTableIsSelfConsistent:
    """有些配置错**不需要联网就能看出来**，那就不该等到线上才发现。

    联网才能答的那半边（``gpt-5.6`` 这个名字今天还在不在、``base_url`` 有没有改版）
    由 ``scripts/probe_models.py`` 在真机上问 —— CI 与开发沙箱都够不到那些主机。
    这一组守的是另一半：表自己跟自己对不对得上。
    """

    @staticmethod
    def _entries():
        from core.multi_llm_router import PROVIDER_REGISTRY  # noqa: PLC0415

        return PROVIDER_REGISTRY

    def test_f01_default_model_is_in_its_own_model_list(self) -> None:
        """默认型号不在自己的清单里 = 这家**每一次**调用都会撞。

        这是所有配置错里最贵的一种，而且完全静态可查。
        """
        bad = []
        for entry in self._entries():
            models = list(entry.get("models") or [])
            default = str(entry.get("default_model") or "")
            if default and default not in models:
                bad.append(f"{entry.get('name')}: default={default!r} 不在 {models}")
        assert not bad, "默认型号与自己的 models 列表对不上：\n  " + "\n  ".join(bad)

    def test_f02_base_urls_are_https_without_trailing_slash(self) -> None:
        """尾斜杠会拼出双斜杠；非 https 是明摆着的错。"""
        from urllib.parse import urlparse

        bad = []
        for entry in self._entries():
            url = str(entry.get("base_url") or "")
            u = urlparse(url)
            if u.scheme != "https":
                bad.append(f"{entry.get('name')}: {url} 不是 https")
            if url.endswith("/"):
                bad.append(f"{entry.get('name')}: {url} 结尾多一个 /")
        assert not bad, "base_url 有问题：\n  " + "\n  ".join(bad)

    def test_f03_no_duplicate_models_within_a_provider(self) -> None:
        bad = []
        for entry in self._entries():
            models = list(entry.get("models") or [])
            if len(models) != len(set(models)):
                bad.append(f"{entry.get('name')}: {models}")
        assert not bad, "同一家里有重复型号：\n  " + "\n  ".join(bad)

    def test_f04_every_provider_declares_at_least_one_model(self) -> None:
        """没有型号的 provider 会被选中然后无模型可用 —— 失败发生在调用时。"""
        bad = [e.get("name") for e in self._entries() if not (e.get("models") or [])]
        assert not bad, f"这些 provider 一个型号都没配：{bad}"

    def test_f05_required_fields_are_present(self) -> None:
        """表头注释写着 name/env_key/base_url/models/default_model 必填。"""
        required = ("name", "env_key", "base_url", "models", "default_model")
        bad = []
        for entry in self._entries():
            missing = [k for k in required if k not in entry]
            if missing:
                bad.append(f"{entry.get('name', '(无名)')}: 缺 {missing}")
        assert not bad, "必填字段缺失：\n  " + "\n  ".join(bad)
