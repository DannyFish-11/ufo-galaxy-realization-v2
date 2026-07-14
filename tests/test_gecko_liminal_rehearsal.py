"""Gecko 借鉴三阶段(工具参数双层校验 + 阈限态预演)测试
=========================================================

覆盖:
  1. 规则层校验 validate_tool_call:未知工具/必填缺失/类型错误/enum 违例/通过。
  2. 只读/高风险工具分类(hybrid 边界 + 语义校验触发线)。
  3. _react_loop 派发前拦截:非法参数【不派发】,结构化反馈回喂,模型下轮自纠。
  4. ShadowState 快照/恢复隔离(失败尝试不污染后续)。
  5. ShadowToolSimulator hybrid:只读直通真实派发,写状态走 LLM 模拟 + 状态增量。
  6. LiminalRehearsal.rehearse:失败→反馈→重试→成功,轨迹产出 GATS 指导文本。
  7. should_rehearse 成本闸门(0/1/auto × 复杂度门槛)。
  8. semantic_check 语义层(高风险路径,失败放行)。
"""

import json

import pytest

from core.tool_call_validator import (
    ToolCallValidation,
    is_high_risk_tool,
    is_read_only_tool,
    semantic_check,
    validate_tool_call,
)


def _tool(name, params=None, required=None):
    """OpenAI function 工具定义速写。"""
    schema = {"type": "object", "properties": params or {}}
    if required:
        schema["required"] = required
    return {"type": "function", "function": {"name": name, "parameters": schema}}


TOOLS = [
    _tool("node__fs__read_file", params={"path": {"type": "string"}}, required=["path"]),
    _tool(
        "node__fs__write_file",
        params={"path": {"type": "string"}, "content": {"type": "string"}},
        required=["path", "content"],
    ),
    _tool(
        "node__sys__set_volume",
        params={"level": {"type": "integer"}, "mode": {"type": "string", "enum": ["abs", "rel"]}},
        required=["level"],
    ),
]


# ---------------------------------------------------------------------------
# 1. 规则层校验
# ---------------------------------------------------------------------------


class TestValidateToolCall:
    def test_unknown_tool_rejected(self):
        v = validate_tool_call("node__fs__reed_file", {"path": "/a"}, TOOLS)
        assert not v.valid
        assert "不在本轮可用工具名单" in v.errors[0]

    def test_missing_required_rejected(self):
        v = validate_tool_call("node__fs__write_file", {"path": "/a"}, TOOLS)
        assert not v.valid
        assert any("content" in e for e in v.errors)

    def test_wrong_type_rejected(self):
        v = validate_tool_call("node__sys__set_volume", {"level": "五十"}, TOOLS)
        assert not v.valid
        assert any("level" in e for e in v.errors)

    def test_enum_violation_rejected(self):
        v = validate_tool_call("node__sys__set_volume", {"level": 50, "mode": "pct"}, TOOLS)
        assert not v.valid
        assert any("mode" in e for e in v.errors)

    def test_valid_call_passes(self):
        v = validate_tool_call("node__sys__set_volume", {"level": 50, "mode": "abs"}, TOOLS)
        assert v.valid
        assert v.feedback_text() == "参数校验通过。"

    def test_empty_schema_passes(self):
        tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
        assert validate_tool_call("t", {"anything": 1}, tools).valid

    def test_malformed_schema_never_blocks(self):
        tools = [
            {"type": "function", "function": {"name": "t", "parameters": {"type": "object", "properties": "不是字典"}}}
        ]
        assert validate_tool_call("t", {}, tools).valid

    def test_feedback_text_states_not_executed(self):
        v = validate_tool_call("node__fs__write_file", {}, TOOLS)
        fb = v.feedback_text()
        assert "未执行" in fb and "node__fs__write_file" in fb


# ---------------------------------------------------------------------------
# 2. 只读 / 高风险分类
# ---------------------------------------------------------------------------


class TestToolClassifiers:
    @pytest.mark.parametrize(
        "name",
        [
            "node__fs__read_file",
            "node__sys__get_status",
            "mcp__mem__search_notes",
            "node__app__list_windows",
            "device__query_battery",
            "node__net__health",
        ],
    )
    def test_read_only(self, name):
        assert is_read_only_tool(name)

    @pytest.mark.parametrize(
        "name",
        [
            "node__fs__write_file",
            "node__app__launch",
            "node__sys__set_volume",
            "node__fs__delete_file",
            "完全未知的工具",
        ],
    )
    def test_state_changing_or_unknown_conservative(self, name):
        assert not is_read_only_tool(name)

    @pytest.mark.parametrize(
        "name",
        [
            "node__fs__delete_file",
            "node__sys__shutdown",
            "node__pkg__uninstall",
            "mcp__bank__transfer_funds",
            "node__mail__send_email",
        ],
    )
    def test_high_risk(self, name):
        assert is_high_risk_tool(name)

    def test_low_risk(self):
        assert not is_high_risk_tool("node__fs__read_file")
        assert not is_high_risk_tool("node__sys__set_volume")


# ---------------------------------------------------------------------------
# 3. _react_loop 派发前拦截(不派发 + 反馈自纠)
# ---------------------------------------------------------------------------


class TestReactLoopInterception:
    @pytest.mark.asyncio
    async def test_invalid_args_not_dispatched_then_self_corrected(self):
        from core.multi_llm_router import LLMResponse
        from core.openclawd import OpenClawd

        rounds = []

        class _FakeRouter:
            async def chat_with_tools(self, messages, tools=None, task_type=None, max_tokens=4096, **kwargs):
                rounds.append([dict(m) for m in messages])
                n = len(rounds)
                if n == 1:  # 第一轮:缺必填 content 的非法调用
                    return LLMResponse(
                        content="",
                        provider="p",
                        model="m",
                        input_tokens=1,
                        output_tokens=1,
                        latency_ms=1.0,
                        tool_calls=[
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "node__fs__write_file", "arguments": '{"path": "/a"}'},
                            }
                        ],
                    )
                if n == 2:  # 第二轮:模型看到反馈后自纠
                    return LLMResponse(
                        content="",
                        provider="p",
                        model="m",
                        input_tokens=1,
                        output_tokens=1,
                        latency_ms=1.0,
                        tool_calls=[
                            {
                                "id": "c2",
                                "type": "function",
                                "function": {
                                    "name": "node__fs__write_file",
                                    "arguments": '{"path": "/a", "content": "hi"}',
                                },
                            }
                        ],
                    )
                return LLMResponse(
                    content="写好了。", provider="p", model="m", input_tokens=1, output_tokens=1, latency_ms=1.0
                )

        dispatched = []

        async def _fake_dispatch(name, args):
            dispatched.append((name, args))
            return {"success": True}

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._get_router = lambda: _FakeRouter()
        clawd._dispatch_tool_call = _fake_dispatch

        result = await clawd._react_loop([{"role": "user", "content": "写个文件"}], tools=TOOLS)

        assert result["response"] == "写好了。"
        # 非法那次没有派发;自纠后的那次才派发
        assert dispatched == [("node__fs__write_file", {"path": "/a", "content": "hi"})]
        # 第二轮模型能看到结构化校验反馈(tool 消息,tool_call_id 对应 c1)
        fb = [m for m in rounds[1] if m.get("role") == "tool" and m.get("tool_call_id") == "c1"]
        assert fb and "参数校验失败" in fb[0]["content"]
        assert "未执行" in fb[0]["content"]


# ---------------------------------------------------------------------------
# 4. 影子状态
# ---------------------------------------------------------------------------


class TestShadowState:
    def test_snapshot_restore_isolation(self):
        from core.liminal_rehearsal import ShadowState

        st = ShadowState()
        st.apply_delta({"files": ["a.txt"], "step": 1})
        snap = st.snapshot()
        st.apply_delta({"step": 2})
        st.facts["files"].append("b.txt")  # 深层变异也不能穿透快照
        st.restore(snap)
        assert st.facts == {"files": ["a.txt"], "step": 1}

    def test_apply_delta_ignores_non_dict(self):
        from core.liminal_rehearsal import ShadowState

        st = ShadowState(facts={"a": 1})
        st.apply_delta(None)
        st.apply_delta("不是字典")
        assert st.facts == {"a": 1}


# ---------------------------------------------------------------------------
# 5. 模拟派发器 hybrid
# ---------------------------------------------------------------------------


class _SimRouter:
    """写状态模拟:回 JSON {response, state_delta}。"""

    def __init__(self, payload=None, raise_on_chat=False):
        self._payload = payload
        self._raise = raise_on_chat
        self.prompts = []

    async def chat(self, messages, temperature=0.0, max_tokens=500, **kwargs):
        self.prompts.append(messages[-1]["content"])
        if self._raise:
            raise RuntimeError("模拟器 LLM 不可用")

        class _R:
            content = json.dumps(self._payload, ensure_ascii=False)

        return _R()


class TestShadowToolSimulator:
    @pytest.mark.asyncio
    async def test_read_only_passes_through_to_real_dispatch(self):
        from core.liminal_rehearsal import ShadowState, ShadowToolSimulator

        real_calls = []

        async def _real(name, args):
            real_calls.append((name, args))
            return {"success": True, "content": "真实内容"}

        sim = ShadowToolSimulator(_real, _SimRouter(), ShadowState(), TOOLS)
        out = await sim.simulate_call("node__fs__read_file", {"path": "/a"}, "读文件")
        assert out["simulated"] is False
        assert out["result"]["content"] == "真实内容"
        assert real_calls == [("node__fs__read_file", {"path": "/a"})]

    @pytest.mark.asyncio
    async def test_state_changing_simulated_with_delta(self):
        from core.liminal_rehearsal import ShadowState, ShadowToolSimulator

        real_calls = []

        async def _real(name, args):
            real_calls.append(name)
            return {}

        router = _SimRouter(
            payload={
                "response": {"success": True, "written": "/a"},
                "state_delta": {"file_written": "/a"},
            }
        )
        state = ShadowState()
        sim = ShadowToolSimulator(_real, router, state, TOOLS)
        out = await sim.simulate_call("node__fs__write_file", {"path": "/a", "content": "x"}, "写文件")
        assert out["simulated"] is True
        assert out["result"] == {"success": True, "written": "/a"}
        assert state.facts == {"file_written": "/a"}  # 状态增量已入影子状态
        assert real_calls == []  # 真实派发一次都没碰

    @pytest.mark.asyncio
    async def test_simulator_llm_failure_falls_back_to_generic_shell(self):
        from core.liminal_rehearsal import ShadowState, ShadowToolSimulator

        sim = ShadowToolSimulator(None, _SimRouter(raise_on_chat=True), ShadowState(), TOOLS)
        out = await sim.simulate_call("node__fs__write_file", {"path": "/a", "content": "x"}, "写文件")
        assert out["simulated"] is True
        assert out["result"].get("success") is True  # 通用成功壳,预演不中断


# ---------------------------------------------------------------------------
# 6. 预演循环:失败→反馈→重试→成功 + GATS 指导
# ---------------------------------------------------------------------------


class _RehearsalRouter:
    """按提示词内容分角色的假路由:影子 ReAct / 模拟器 / 裁判。"""

    def __init__(self):
        self.react_rounds = 0
        self.judge_rounds = 0
        self.react_messages = []  # 每轮影子 ReAct 收到的 messages

    async def chat_with_tools(self, messages, tools=None, max_tokens=1024, **kwargs):
        self.react_rounds += 1
        self.react_messages.append([dict(m) for m in messages])

        class _R:
            content = ""
            tool_calls = None

        r = _R()
        # 每次尝试:第一步发一个写文件调用,第二步宣告完成(无 tool_calls)
        if not any(m.get("role") == "tool" for m in messages):
            r.tool_calls = [
                {
                    "id": "s1",
                    "type": "function",
                    "function": {"name": "node__fs__write_file", "arguments": '{"path": "/a", "content": "hi"}'},
                }
            ]
        else:
            r.content = "完成了。"
        return r

    async def chat(self, messages, temperature=0.0, max_tokens=500, **kwargs):
        prompt = messages[-1]["content"]

        class _R:
            content = ""

        r = _R()
        if "任务完成度裁判" in prompt:
            self.judge_rounds += 1
            if self.judge_rounds == 1:  # 第一轮判未完成,给任务级反馈
                r.content = json.dumps({"complete": False, "feedback": "还差校验写入结果"}, ensure_ascii=False)
            else:
                r.content = json.dumps({"complete": True})
        else:  # 工具执行模拟器
            r.content = json.dumps(
                {
                    "response": {"success": True},
                    "state_delta": {"file_written": "/a"},
                },
                ensure_ascii=False,
            )
        return r


class TestLiminalRehearsal:
    @pytest.mark.asyncio
    async def test_fail_feedback_retry_success_and_guidance(self):
        from core.liminal_rehearsal import LiminalRehearsal

        router = _RehearsalRouter()
        rl = LiminalRehearsal(router=router, real_dispatch=None, tools=TOOLS, max_attempts=2, max_steps=4)
        outcome = await rl.rehearse("把 hi 写进 /a 并确认")

        assert outcome.success
        assert outcome.attempts == 2
        assert outcome.feedback_history == ["还差校验写入结果"]
        assert outcome.final_state == {"file_written": "/a"}
        assert [s["tool"] for s in outcome.trajectory] == ["node__fs__write_file"]
        assert outcome.trajectory[0]["simulated"] is True

        # 第二次尝试的影子 ReAct 能看到上一轮的任务级反馈(反馈穿线)
        second_attempt_first_round = router.react_messages[2]
        assert any(
            "上一轮预演反馈" in m.get("content", "") and "还差校验写入结果" in m.get("content", "")
            for m in second_attempt_first_round
        )

        guidance = outcome.guidance_text()
        assert "成功轨迹" in guidance and "node__fs__write_file" in guidance

    @pytest.mark.asyncio
    async def test_invalid_call_rejected_inside_rehearsal(self):
        """预演里的非法调用同样不进模拟器,反馈回喂后自纠。"""
        from core.liminal_rehearsal import LiminalRehearsal

        class _Router(_RehearsalRouter):
            async def chat_with_tools(self, messages, tools=None, max_tokens=1024, **kwargs):
                self.react_rounds += 1

                class _R:
                    content = ""
                    tool_calls = None

                r = _R()
                if self.react_rounds == 1:  # 缺必填 content
                    r.tool_calls = [
                        {
                            "id": "s1",
                            "type": "function",
                            "function": {"name": "node__fs__write_file", "arguments": '{"path": "/a"}'},
                        }
                    ]
                elif self.react_rounds == 2:
                    fb = [m for m in messages if m.get("role") == "tool"]
                    assert fb and "参数校验失败" in fb[0]["content"]
                    r.tool_calls = [
                        {
                            "id": "s2",
                            "type": "function",
                            "function": {
                                "name": "node__fs__write_file",
                                "arguments": '{"path": "/a", "content": "hi"}',
                            },
                        }
                    ]
                else:
                    r.content = "完成了。"
                return r

            async def chat(self, messages, **kwargs):
                prompt = messages[-1]["content"]

                class _R:
                    content = (
                        json.dumps({"complete": True})
                        if "任务完成度裁判" in prompt
                        else json.dumps({"response": {"success": True}, "state_delta": {}})
                    )

                return _R()

        rl = LiminalRehearsal(router=_Router(), real_dispatch=None, tools=TOOLS, max_attempts=1, max_steps=4)
        outcome = await rl.rehearse("写文件")
        assert outcome.success
        # 轨迹只含自纠后的合法调用,非法那次没进模拟器
        assert len(outcome.trajectory) == 1
        assert outcome.trajectory[0]["args"] == {"path": "/a", "content": "hi"}

    @pytest.mark.asyncio
    async def test_all_attempts_fail_returns_failure_with_history(self):
        from core.liminal_rehearsal import LiminalRehearsal

        class _Router(_RehearsalRouter):
            async def chat(self, messages, **kwargs):
                prompt = messages[-1]["content"]

                class _R:
                    content = (
                        json.dumps({"complete": False, "feedback": "始终差一步"}, ensure_ascii=False)
                        if "任务完成度裁判" in prompt
                        else json.dumps({"response": {"success": True}, "state_delta": {}})
                    )

                return _R()

        rl = LiminalRehearsal(router=_Router(), real_dispatch=None, tools=TOOLS, max_attempts=2, max_steps=3)
        outcome = await rl.rehearse("难任务")
        assert not outcome.success
        assert outcome.attempts == 2
        assert outcome.feedback_history == ["始终差一步", "始终差一步"]
        assert outcome.guidance_text() == ""  # 没跑通就没有"成功轨迹"指导


# ---------------------------------------------------------------------------
# 7. 成本闸门
# ---------------------------------------------------------------------------


class TestShouldRehearse:
    def test_off_never(self, monkeypatch):
        from core.liminal_rehearsal import should_rehearse

        monkeypatch.setenv("GALAXY_LIMINAL_REHEARSAL", "0")
        assert not should_rehearse(0.99, TOOLS)

    def test_force_on_any_complexity_with_tools(self, monkeypatch):
        from core.liminal_rehearsal import should_rehearse

        monkeypatch.setenv("GALAXY_LIMINAL_REHEARSAL", "1")
        assert should_rehearse(0.01, TOOLS)

    def test_no_tools_never(self, monkeypatch):
        from core.liminal_rehearsal import should_rehearse

        monkeypatch.setenv("GALAXY_LIMINAL_REHEARSAL", "1")
        assert not should_rehearse(0.99, [])
        assert not should_rehearse(0.99, None)

    def test_auto_uses_complexity_floor(self, monkeypatch):
        from core.liminal_rehearsal import should_rehearse

        monkeypatch.setenv("GALAXY_LIMINAL_REHEARSAL", "auto")
        monkeypatch.setenv("GALAXY_REHEARSAL_COMPLEXITY_FLOOR", "0.6")
        assert not should_rehearse(0.55, TOOLS)
        assert should_rehearse(0.65, TOOLS)

    def test_bad_floor_falls_back_to_default(self, monkeypatch):
        from core.liminal_rehearsal import should_rehearse

        monkeypatch.setenv("GALAXY_LIMINAL_REHEARSAL", "auto")
        monkeypatch.setenv("GALAXY_REHEARSAL_COMPLEXITY_FLOOR", "不是数")
        assert should_rehearse(0.56, TOOLS)  # 默认 0.55
        assert not should_rehearse(0.54, TOOLS)


# ---------------------------------------------------------------------------
# 8. 语义层校验
# ---------------------------------------------------------------------------


class TestSemanticCheck:
    @pytest.mark.asyncio
    async def test_semantic_reject_carries_reason(self):
        class _Router:
            async def chat(self, messages, **kwargs):
                class _R:
                    content = json.dumps({"ok": False, "reason": "要 ticker 不要公司名"}, ensure_ascii=False)

                return _R()

        v = await semantic_check("mcp__stock__delete_alert", {"symbol": "苹果公司"}, "删掉苹果的提醒", router=_Router())
        assert not v.valid
        assert "ticker" in v.errors[0]

    @pytest.mark.asyncio
    async def test_semantic_pass_and_failure_open(self):
        class _OkRouter:
            async def chat(self, messages, **kwargs):
                class _R:
                    content = '{"ok": true}'

                return _R()

        class _DeadRouter:
            async def chat(self, messages, **kwargs):
                raise RuntimeError("路由不可用")

        assert (await semantic_check("t", {}, "任务", router=_OkRouter())).valid
        # 语义层是增强不是闸门:路由挂了必须放行
        assert (await semantic_check("t", {}, "任务", router=_DeadRouter())).valid

    def test_validation_dataclass_defaults(self):
        v = ToolCallValidation(valid=True, tool_name="t")
        assert v.errors == []
