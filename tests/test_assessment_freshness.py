"""判据保鲜:对仓库自身状态的结论,过期了要自己红。

为什么需要这一道
----------------
本仓已有的门全在查**代码**。没有任何一道在查**结论** —— 而 2026-08-28 那次全仓
评估发现,结论烂得比代码快,而且每一处都带着绿灯:

* ``completion_matrix`` 的分数停在 2026-04-29,四个月没重推;它自己的证据校验一直
  绿,因为那道门查的是**文件在不在**,35 条路径一条不缺。
* 路线图把 ``task_cancel`` 列为唯一的 P0 correctness failure,而它早就实现了。
* in-code 缺口清单仍列 GAP-512-004 为开着,而 harness 明写已关闭。
* 七个"阻塞中的设计问题"里四个已经不成立。

同一个缺陷四处独立复现。**判据以判据的形式被钉住之后,比没有它更难被质疑。**

这个文件钉四件事:
A. 谓词真的能分辨"写了没有"和"写了有没有人用"——后者正是本仓反复踩的那一类;
B. "问不出来"与"过期"分得开 —— 混成一个,一次环境故障就会被读成一批结论作废;
C. 清单读不出来时这道门**不许报绿** —— 一道什么都没查的门显示成功,是最坏的失效;
D. 它不假装能重算分数。
"""

from __future__ import annotations

import json

import pytest

from core import assessment_freshness as af

# ══════════════════════════════════════════════════════════════════════════
# A. 谓词分得清"写了"和"有人用"
# ══════════════════════════════════════════════════════════════════════════


def test_a01_symbol_exists_finds_a_real_definition():
    ok, _ = af._symbol_exists("handle_task_cancel", "galaxy_gateway")
    assert ok is True


def test_a02_symbol_exists_is_false_for_something_never_defined():
    ok, detail = af._symbol_exists("ThisSymbolDoesNotExistAnywhereXYZ", "core")
    assert ok is False
    assert "无定义" in detail


def test_a03_production_caller_excludes_the_definition_line_itself():
    """ "定义了"不等于"有人用" —— 把定义行算成调用方,这个谓词就废了,
    而它要抓的恰恰是"写好了、测过了、导出去了,一个调用点都没有"。"""
    ok, _ = af._has_production_caller("bind_webrtc_session_to_task", "core")
    assert ok is True  # 已接线;若哪天被摘掉,这条会先响


def test_a04_production_caller_excludes_tests():
    """只被测试用到的东西,不算生产接线。"""
    assert "tests/" in af._NOT_A_CALLER


def test_a05_production_caller_excludes_pure_reexport_aggregators():
    """re-export 不是"用了"。

    WebRTC 那次就栽在这儿:整套 API 出现在 core/runtime/__init__.py 的
    re-export 里,粗看像是接上了,实际生产调用点是 0。
    """
    assert "core/runtime/__init__.py" in af._NOT_A_CALLER


def test_a06_an_unknown_predicate_kind_is_unverifiable_not_fresh():
    """认不出的谓词种类必须是"问不出来",不能默默算通过 —— 那会让一个拼错的
    kind 变成一条永远绿的假判据。"""
    result = af.verify_claim({"id": "x", "predicates": [{"kind": "no_such_kind", "target": "y"}]})
    assert result.verdict == "unverifiable"


# ══════════════════════════════════════════════════════════════════════════
# B. "问不出来"与"过期"分得开
# ══════════════════════════════════════════════════════════════════════════


def test_b01_a_changed_fact_is_stale():
    """记录说"不存在",实际存在了 → 过期。这正是 task_cancel 那一条的形状。"""
    result = af.verify_claim(
        {
            "id": "t",
            "predicates": [
                {"kind": "symbol_exists", "target": "handle_task_cancel", "scope": "galaxy_gateway", "expected": False}
            ],
        }
    )
    assert result.verdict == "stale"


def test_b02_an_unaskable_predicate_is_unverifiable_not_stale(monkeypatch):
    """搜不动 ≠ 结论过期。

    混成一个的后果:一次环境故障(目录没挂上、grep 挂了)会被读成"一批结论作废",
    然后没有人再信这道门。
    """
    monkeypatch.setattr(af, "_grep", lambda *_a, **_k: None)
    result = af.verify_claim(
        {"id": "t", "predicates": [{"kind": "symbol_exists", "target": "whatever", "scope": "core", "expected": True}]}
    )
    assert result.verdict == "unverifiable"


def test_b03_the_three_verdicts_stay_three():
    assert set(af.VERDICTS) == {"fresh", "stale", "unverifiable"}


def test_b04_the_report_explains_both_words():
    report = af.freshness_report()
    assert "不是说结论一定错" in report["stale_means"]
    assert "两回事" in report["unverifiable_means"]


# ══════════════════════════════════════════════════════════════════════════
# C. 什么都没查的时候不许报绿
# ══════════════════════════════════════════════════════════════════════════


def test_c01_zero_claims_is_reported_as_zero_not_as_all_fresh(monkeypatch):
    """0 条结论与"全都新鲜"是两回事。前者意味着这道门什么都没查。"""
    monkeypatch.setattr(af, "load_claims", lambda: [])
    report = af.freshness_report()
    assert report["claims_loaded"] == 0
    assert report["verdicts"]["fresh"] == 0


def test_c02_the_gate_exits_nonzero_when_the_claims_file_is_unreadable(tmp_path, monkeypatch):
    """清单读不出来时门必须非零退出 —— 一道什么都没查的门报成功,是最坏的失效方式。"""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "check_assessment_freshness.py"
    spec = importlib.util.spec_from_file_location("check_assessment_freshness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(af, "CLAIMS_FILE", tmp_path / "nope.json")
    monkeypatch.setattr("sys.argv", ["check_assessment_freshness.py"])
    assert mod.main() == 2


def test_c03_the_real_claims_file_parses_and_is_not_empty():
    claims = af.load_claims()
    assert len(claims) >= 8, "结论清单太薄 —— 它至少要覆盖那几处已知失真"
    for claim in claims:
        assert claim.get("id")
        assert claim.get("statement")
        assert claim.get("predicates"), f"{claim.get('id')} 没有任何可复验的谓词 —— 那它就不是一条判据"


def test_c04_every_predicate_kind_in_the_file_is_known():
    for claim in af.load_claims():
        for pred in claim["predicates"]:
            assert pred["kind"] in af.PREDICATE_KINDS, f"{claim['id']} 用了不认识的谓词 {pred['kind']!r}"


def test_c05_the_shipped_claims_are_all_fresh_right_now():
    """出厂时全绿 —— 一道从出生就红的门,三周内一定被忽略。

    历史上的失真记在每条的 supersedes 里(那是给人看的、要人去改文档的),
    不是靠让这道门长期红着来表达。
    """
    stale = [r.claim_id for r in af.verify_all() if r.verdict == "stale"]
    assert not stale, f"这些结论所依据的事实已经变了,需要重新推导: {stale}"


# ══════════════════════════════════════════════════════════════════════════
# D. 它不假装能重算分数
# ══════════════════════════════════════════════════════════════════════════


def test_d01_it_does_not_invent_scores():
    """完成度矩阵的方法是人工 code-path tracing,"65% 还是 80%"没有机械算法。
    这个模块里不该出现任何算分的东西 —— 硬算就是臆造。"""
    import inspect

    src = inspect.getsource(af)
    for forbidden in ("score_pct", "def _score", "percent"):
        assert forbidden not in src


def test_d02_the_known_stale_documents_are_named():
    """已知"文档仍然说反话"的那几条,必须点名到文档 —— 否则没人知道该去改哪儿。"""
    named = [c for c in af.load_claims() if str(c.get("supersedes", "")).strip()]
    assert len(named) >= 5
    for claim in named:
        assert claim.get("source"), f"{claim['id']} 说有文档说反话,却没说是哪份"


def test_d03_the_claims_file_says_how_to_use_it():
    """改完 expected 就完事,等于把过期挪了个地方 —— 这句必须写在文件里。"""
    from pathlib import Path

    raw = json.loads((Path(af.CLAIMS_FILE)).read_text(encoding="utf-8"))
    how = " ".join(raw.get("_how_to_use", []))
    assert "去改" in how and "文档" in how


@pytest.mark.parametrize("kind", ["symbol_exists", "has_production_caller", "path_exists"])
def test_d04_predicate_kinds_stay_few(kind):
    """种类刻意很少。一多就会有人往里塞"差不多能表达"的东西,然后判据本身开始漂。"""
    assert kind in af.PREDICATE_KINDS
    assert len(af.PREDICATE_KINDS) == 3
