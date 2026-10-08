"""对话历史里同一轮只记一遍，且存的是用户说的话，不带机器追加的注解。

被修的问题（截图时发现，面板上看得见）：走内核的请求，同一轮被两处各记了一遍 ——
``AgentKernel._record_session``（带模态信息，但用户那句是**带注解**的版本）与 ``OpenClawd._record_turn``
（干净版本）。会话历史里于是有两对 user/assistant，面板把两对都画出来，第一对的用户消息后面挂着

    [Multimodal context: device=unknown]
    [desktop_context_strategy presence_transition=static_to_liminal; ...]

这是写给模型看的内部注解（``OpenClawd`` 在把消息交给内核前追加），不该进用户的历史。
"""

from __future__ import annotations

import asyncio

import pytest

from core.anticipatory_context import strip_appended_annotations

MM = "[Multimodal context: device=unknown]"
STRAT = "[desktop_context_strategy presence_transition=static_to_liminal; sampling_intensity=moderate]"


class TestStripAppendedAnnotations:
    def test_both_machine_blocks_at_the_end_are_removed(self):
        assert strip_appended_annotations(f"帮我看看状态\n\n{MM}\n\n{STRAT}") == "帮我看看状态"

    def test_the_nested_bracket_form_of_the_multimodal_block_is_removed_whole(self):
        text = "看这张图\n\n[Multimodal context: 1 image(s) [webcam], device=dev-1]"
        assert strip_appended_annotations(text) == "看这张图"

    def test_the_users_own_text_is_untouched_newlines_and_brackets_included(self):
        text = "第一行\n第二行 [这是我自己写的方括号]\n\n  缩进"
        assert strip_appended_annotations(text) == text

    def test_an_annotation_in_the_middle_is_not_removed(self):
        """只剥**追加在末尾**的；中间位置那条是用户贴进来的内容，不动。"""
        text = f"我贴一段日志：{MM} 然后继续说"
        assert strip_appended_annotations(text) == text

    def test_a_message_that_is_only_annotations_becomes_empty(self):
        assert strip_appended_annotations(f"{MM}\n\n{STRAT}") == ""

    def test_empty_and_none_pass_through(self):
        assert strip_appended_annotations("") == ""
        assert strip_appended_annotations(None) is None

    def test_it_is_idempotent(self):
        once = strip_appended_annotations(f"你好\n\n{MM}")
        assert strip_appended_annotations(once) == once == "你好"


class _Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, **kw):
        self.calls.append(kw)


@pytest.fixture()
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr("core.session_memory_facade.record_session_turn", rec)
    return rec


class TestTheKernelRecordsTheCleanText:
    def test_the_user_turn_it_stores_has_no_annotations_and_keeps_its_origin_tag(self, recorder):
        from core.agent.kernel import AgentKernel

        k = AgentKernel.__new__(AgentKernel)
        asyncio.run(k._record_session("s1", f"你好\n\n{MM}\n\n{STRAT}", "收到"))
        user = [c for c in recorder.calls if c["role"] == "user"]
        assert [c["content"] for c in user] == ["你好"]
        assert user[0]["metadata"]["record_origin"] == "agent_kernel"
        assert [c["content"] for c in recorder.calls if c["role"] == "assistant"] == ["收到"]


class TestOpenClawdDoesNotWriteTheSameTurnAgain:
    def _claw(self):
        from core.openclawd import OpenClawd

        c = OpenClawd.__new__(OpenClawd)
        c._session_memory = {}
        return c

    def test_unified_false_keeps_only_the_in_process_copy(self, recorder):
        c = self._claw()
        asyncio.run(c._record_turn("s1", "user", "你好", unified=False))
        assert recorder.calls == []
        assert c._session_memory["s1"] == [{"role": "user", "content": "你好"}]

    def test_the_default_still_writes_the_unified_store_once(self, recorder):
        c = self._claw()
        asyncio.run(c._record_turn("s1", "user", "你好"))
        assert len(recorder.calls) == 1 and recorder.calls[0]["metadata"]["record_origin"] == "openclawd"

    def test_the_kernel_path_asks_for_the_in_process_copy_only(self):
        """走内核的那一处两次 _record_turn 都要带 unified=False —— 内核已经记过这一轮。"""
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "core" / "openclawd.py").read_text(encoding="utf-8")
        calls = re.findall(r"await self\._record_turn\(session_id, \"(user|assistant)\", [^)]*unified=False\)", src)
        assert sorted(calls) == ["assistant", "user"]
