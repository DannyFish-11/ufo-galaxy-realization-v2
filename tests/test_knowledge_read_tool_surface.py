"""``knowledge__read`` 的接线：登记了、路由到了、执行器真能跑。

守的是**接线**而不是逻辑。这个仓库有过一次同形的教训，注释还留在
``core/openclawd.py`` 的 ``_INLINE_ONLY_PREFIXES`` 上：

    dispatcher 按设计只认 mcp/skill/node/device/github 前缀，未知前缀一律判
    "未知工具前缀"错误——此前 academic/engineer/resource/ask_human 一经委派即死
    （inline 处理器永远轮不到）。

也就是说：工具表里有、执行器也写好了，但前缀没登记，模型一调就死。这类缺陷不会被
任何逻辑测试抓到，因为两头各自都是对的。
"""

import asyncio

import pytest

import core.openclawd as oc
from core.rag_memory import RAGMemory


def _tool_spec():
    for t in oc._MEMORY_BUILTIN_TOOLS:
        if t["function"]["name"] == "knowledge__read":
            return t
    return None


def test_tool_is_registered():
    assert _tool_spec() is not None, "knowledge__read 不在内置工具表里，模型根本看不见它"


def test_tool_schema_shape():
    fn = _tool_spec()["function"]
    props = fn["parameters"]["properties"]
    assert set(props) == {"chunk_id", "offset", "limit"}
    assert fn["parameters"]["required"] == ["chunk_id"], "只有 chunk_id 该是必填"


def test_tool_description_tells_the_model_when_to_use_it():
    desc = _tool_spec()["function"]["description"]
    # 模型只在看到截断标记时才知道该回读；描述里必须把这个触发条件说出来，
    # 否则工具挂着也不会被调用。
    assert "已截断" in desc
    assert "next_offset" in desc, "长内容要能续读，描述里得说"


def test_prefix_is_registered_or_delegation_kills_it():
    src = open("core/openclawd.py", encoding="utf-8").read()
    start = src.index("_INLINE_ONLY_PREFIXES = (")
    block = src[start : start + 400]
    assert '"knowledge__"' in block, (
        "knowledge__ 没进 _INLINE_ONLY_PREFIXES —— 一经委派就会被判『未知工具前缀』，"
        "inline 执行器永远轮不到（academic/engineer/resource/ask_human 都栽过这一次）"
    )


def test_dispatch_branch_exists():
    src = open("core/openclawd.py", encoding="utf-8").read()
    assert 'tool_name.startswith("knowledge__")' in src
    assert "_dispatch_knowledge_tool" in src


class _Bare(oc.OpenClawd):
    """只借方法，不跑 OpenClawd 的完整初始化（执行器不依赖实例状态）。"""

    def __init__(self):  # noqa: D107
        pass


@pytest.fixture()
def kid(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    rag = RAGMemory()
    body = "".join(f"[{i}]很长的一条知识。" for i in range(1, 200))
    rag.ingest_knowledge(content=body, source="t", source_type="text")
    monkeypatch.setattr("core.rag_memory.get_rag_memory", lambda *a, **k: rag)
    return rag._experiences[-1].experience_id, body


def test_executor_reads_back_through_the_tool_path(kid):
    chunk_id, body = kid
    got = asyncio.run(_Bare()._dispatch_knowledge_tool("read", {"chunk_id": chunk_id, "limit": 500}))
    assert got["success"] is True
    assert body.startswith(got["content"])
    assert got["has_more"] is True
    assert got["next_offset"] == 500


def test_executor_rejects_missing_chunk_id():
    got = asyncio.run(_Bare()._dispatch_knowledge_tool("read", {}))
    assert got["success"] is False
    assert "chunk_id" in got["error"]


def test_executor_rejects_unknown_action():
    got = asyncio.run(_Bare()._dispatch_knowledge_tool("write", {"chunk_id": "x"}))
    assert got["success"] is False
    assert "Unknown knowledge action" in got["error"]


def test_executor_survives_garbage_pagination_args(kid):
    chunk_id, _ = kid
    got = asyncio.run(_Bare()._dispatch_knowledge_tool("read", {"chunk_id": chunk_id, "offset": "abc", "limit": None}))
    assert got["success"] is True, "非法分页参数应按默认处理，而不是把这一轮打断"


# ── engineer 记账三步：能一轮做完这件事要说给模型听 ──────────────────────


def _engineer_desc(name: str) -> str:
    for t in oc._ENGINEER_BUILTIN_TOOLS:
        if t["function"]["name"] == name:
            return t["function"]["description"]
    raise AssertionError(f"{name} 不在工具表里")


def test_bookkeeping_tail_tells_the_model_it_may_batch():
    """apply/validate/record 三步是纯记账，ReAct 循环本就一轮派发多个 tool_call。

    实跑确认过：三个放进一轮顺序执行、阶段门逐个校验、状态机走完，call_llm 只调一次。
    能力一直都在，缺的只是没人告诉模型 —— 描述里读起来像每步各占一轮。
    """
    assert "同一轮" in _engineer_desc("engineer__apply")
    assert "同一轮" in _engineer_desc("engineer__record")


def test_validate_does_not_invite_fabricated_results():
    """省往返不能变成『还没跑就先写结论』。

    engineer__validate 只登记结果、不替谁跑验证。批量的前提是结果已经拿到了，
    这一点必须写在描述里，否则『可以合并』会被读成『可以提前断言』。
    """
    val = _engineer_desc("engineer__validate")
    assert "不替你跑验证" in val
    assert "已经拿到结果" in val
    assert "不要提前发 engineer__validate" in _engineer_desc("engineer__apply")
