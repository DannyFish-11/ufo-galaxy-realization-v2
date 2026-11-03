"""第 12 轮真跑(合并后的 main,六期 + 节点一次全打一遍)查出、本文件钉住的一处。

其余两处在各自的文件里:收住要等到句界(``test_a_wrong_sentence_is_corrected_in_the_same_breath.py``)、
循环上第一次 import 的模块先在旁边线程载(``test_slow_work_stays_off_the_loop_round9.py``)。

* 模型经 ``nodes__invoke`` 让文件系统节点删一个**真实存在**的绝对路径,人批了,节点回「Path not found」——
  节点只在自己的根目录(``FILESYSTEM_BASE_DIR``)里操作,开头的「/」被当成根目录下的路径;
  回的那句话看不出是根目录不同,模型只能猜。现在照实说按哪个路径找的、根目录在哪儿。
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def fs_manager(monkeypatch, tmp_path):
    base = tmp_path / "fsroot"
    monkeypatch.setenv("FILESYSTEM_BASE_DIR", str(base))
    spec = importlib.util.spec_from_file_location("_r12_node06_main", REPO / "nodes/Node_06_Filesystem/main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FilesystemManager(), base, tmp_path


def test_a_missing_path_says_which_path_was_looked_up_and_where_the_root_is(fs_manager):
    from fastapi import HTTPException

    mgr, base, tmp_path = fs_manager
    outside = tmp_path / "victim.txt"
    outside.write_text("x")
    with pytest.raises(HTTPException) as err:
        mgr.delete_file(str(outside))
    assert err.value.status_code == 404
    detail = err.value.detail
    assert str(base.resolve()) in detail, "说出根目录"
    assert str(base.resolve() / str(outside).lstrip("/")) in detail, "说出实际按哪个路径找的"
    assert outside.exists(), "根目录外的文件不碰"


def test_inside_the_root_it_still_deletes(fs_manager):
    mgr, base, _ = fs_manager
    (base / "a.txt").write_text("x")
    assert mgr.delete_file("/a.txt") is True and not (base / "a.txt").exists()


@pytest.mark.parametrize(
    "call",
    [
        lambda m: m.read_file("nope.txt"),
        lambda m: m.list_directory("nope"),
        lambda m: m.move_file("nope.txt", "b.txt"),
        lambda m: m.copy_file("nope.txt", "b.txt"),
        lambda m: m.extract_archive("nope.zip"),
    ],
)
def test_every_not_found_names_the_root(fs_manager, call):
    from fastapi import HTTPException

    mgr, base, _ = fs_manager
    with pytest.raises(HTTPException) as err:
        call(mgr)
    assert err.value.status_code == 404 and str(base.resolve()) in err.value.detail


# ── 同一句话第一次判成任务、第二次判成聊天(第 12 轮真跑) ─────────────────────────────────
#
# 规则分类看的是整条消息,包括机器追加在末尾的注解;英文聊天词按子串认。第二次那条末尾挂着
# ``[desktop_context_strategy execution_readiness=high; …]``,``high`` 含「hi」→ 聊天 → 模型拿不到工具,删文件没做。


def test_appended_machine_annotations_do_not_decide_the_intent():
    from core.agent.intent_router import IntentMode, _classify_by_rules

    said = "用节点删文件:/r12/victim-a.txt"
    for tail in (
        "",
        "\n\n[Multimodal context: device=unknown]\n\n[desktop_context_strategy execution_readiness=high; "
        "sampling_intensity=focused; fusion_strategy=execution_aligned_fusion]",
        "\n\n[Multimodal context: device=unknown]\n\n[desktop_context_strategy presence_transition=manifest_to_liminal; "
        "presence_transition_reason=execution_completed_or_result_committed; sampling_intensity=moderate]",
    ):
        assert _classify_by_rules(said + tail) == _classify_by_rules(said), repr(tail)
    assert _classify_by_rules(said).mode is not IntentMode.CHAT_ONLY


@pytest.mark.parametrize("msg", ["i think this machine is slow", "which one is higher", "do the thing on my phone"])
def test_english_chat_words_match_whole_words_only(msg):
    from core.agent.intent_router import _CHAT_KW, _has_chat_word

    assert [kw for kw in _CHAT_KW if _has_chat_word(msg, kw)] == [], "「hi」不认 this / think / which / higher / thing"


@pytest.mark.parametrize("msg", ["hi there", "hello, how are you", "Hi! 讲个故事"])
def test_real_greetings_are_still_chat(msg):
    from core.agent.intent_router import IntentMode, _classify_by_rules

    assert _classify_by_rules(msg).mode is IntentMode.CHAT_ONLY


def test_a_user_typed_bracket_is_kept():
    """只剥已知的机器注解:用户自己打的方括号不动(``strip_appended_annotations`` 的约定)。"""
    from core.agent.intent_router import IntentMode, _classify_by_rules

    assert _classify_by_rules("你好 [hi]").mode is IntentMode.CHAT_ONLY


@pytest.mark.parametrize("msg", ["用节点查时间", "客厅灯亮一点", "用节点调旧编排", "拼错一个工具名试试"])
def test_a_short_message_without_signals_is_left_to_the_model(msg):
    """剥掉注解之后才露出来的:以前每条消息末尾都挂着注解、从不短于 10 个字,没信号的短句实际上一直交给模型判。"""
    from core.agent.intent_router import _classify_by_rules

    assert _classify_by_rules(msg).confidence < 0.6, "低于复核线:让模型判"


def test_the_router_asks_the_model_about_a_short_ambiguous_task():
    import asyncio

    from core.agent.intent_router import IntentMode, IntentResult, IntentRouter

    class _Router:
        pass

    async def fake_llm(message, router):
        return IntentResult(mode=IntentMode.TASK_EXECUTE, confidence=0.95, method="llm")

    import core.agent.intent_router as ir

    orig = ir._classify_by_llm
    ir._classify_by_llm = fake_llm
    try:
        got = asyncio.run(IntentRouter(_Router()).route("用节点查时间\n\n[Multimodal context: device=unknown]"))
    finally:
        ir._classify_by_llm = orig
    assert got.mode is IntentMode.TASK_EXECUTE and got.method == "rules+llm"


# ── 换了数据目录,成本记录 / 任务记忆 / 任务账本照样写进源码树(第 12 轮真跑) ───────────────────
#
# 真跑用的是独立的 GALAXY_DATA_DIR,源码树 data/ 里的 cost_records.jsonl、task_memory.jsonl、task_cost_ledger.jsonl
# 却在同一秒被写了:前两个把「源码树 data/」写死在代码里,第三个是 .env.example 把路径钉成 data/...(照着模板
# 复制出来的 .env 都带着它)。


def test_the_cost_tracker_and_task_memory_follow_the_data_dir(monkeypatch, tmp_path):
    import core.cost_tracker as ct
    import core.task_memory as tm

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setattr(ct, "_REPO_DATA", str(tmp_path / "old"))
    monkeypatch.setattr(tm, "_DEFAULT_DATA_DIR", str(tmp_path / "old"))
    assert ct.CostTracker()._log_file == str(tmp_path / "d" / "cost_records.jsonl")
    assert tm.TaskMemory()._file == str(tmp_path / "d" / "task_memory.jsonl")


def test_what_is_already_in_the_old_place_keeps_being_used(monkeypatch, tmp_path):
    import core.cost_tracker as ct
    import core.task_memory as tm

    old = tmp_path / "old"
    old.mkdir()
    (old / "cost_records.jsonl").write_text("")
    (old / "task_memory.jsonl").write_text("")
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setattr(ct, "_REPO_DATA", str(old))
    monkeypatch.setattr(tm, "_DEFAULT_DATA_DIR", str(old))
    assert ct.CostTracker()._log_file == str(old / "cost_records.jsonl"), "已有的成本记录不甩在后面"
    assert tm.TaskMemory()._file == str(old / "task_memory.jsonl"), "已有的任务经验不甩在后面"


def test_the_template_does_not_pin_paths_into_the_source_tree():
    import re

    text = (REPO / ".env.example").read_text(encoding="utf-8")
    pinned = re.findall(r"^([A-Z_]+)=(?:\./)?(?:data|runtime)/", text, flags=re.M)
    assert pinned == [], "路径不设就随数据总目录走;模板里写成 data/... 就钉在源码树里:" + ", ".join(pinned)


@pytest.mark.parametrize("value", ["", "  "])
def test_a_blank_ledger_path_means_the_default_not_off(monkeypatch, tmp_path, value):
    """登记表说「留空 = 数据总目录下的 task_cost_ledger.jsonl」;原先空串被当成关掉,账本一声不响就不记了。"""
    from core.task_cost_ledger import TaskBill, TaskCostLedger

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_TASK_LEDGER_PATH", value)
    TaskCostLedger().commit(TaskBill(trace_id="t1"))
    assert (tmp_path / "task_cost_ledger.jsonl").read_text(encoding="utf-8").count("t1") == 1


def test_off_still_turns_the_ledger_off(monkeypatch, tmp_path):
    from core.task_cost_ledger import TaskBill, TaskCostLedger

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_TASK_LEDGER_PATH", "off")
    TaskCostLedger().commit(TaskBill(trace_id="t1"))
    assert not (tmp_path / "task_cost_ledger.jsonl").exists()


@pytest.mark.parametrize(
    "module, key, sub",
    [
        ("core/memory/clip_provider.py", "GALAXY_CLIP_DIR", "clip_memory"),
        ("core/memory/clap_provider.py", "GALAXY_CLAP_DIR", "clap_memory"),
        ("core/memory/omni_simplemem_provider.py", "GALAXY_OMNIMEM_DIR", "omni_simplemem"),
    ],
)
def test_a_blank_memory_dir_means_the_default(module, key, sub):
    """这三个目录键空着就是数据总目录下的默认位置(原先 ``os.getenv(key, 默认)`` 拿到空串,makedirs("") 失败)。"""
    text = (REPO / module).read_text(encoding="utf-8")
    assert f'os.getenv("{key}") or' in text and f'data_path("{sub}")' in text
