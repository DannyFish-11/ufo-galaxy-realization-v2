"""知识可回读：截断必须留下把手，候选必须能回到证据。

修的是一个真实缺陷
==================
``RAGMemory.format_rag_context`` 此前是 ``chunk.content[:500]`` —— 超过 500 字符的
知识被**静默切掉**：

* 没有任何标记，模型察觉不到自己看的是残篇；
* ``chunk_id`` 没有渲染出来，就算有回读工具也没有把手；
* 而且根本没有回读工具 —— 剩下的内容在存储里好好的，模型够不着。

它在三条生产路径上：``galaxy_orchestrator``、``core/scheduler``、``core/routes/hybrid``。

为什么这条不一致要紧
--------------------
本仓会话侧的保证是**压缩可逆**：归档后可以用 ``context__query_memory`` 按段号把原文
查回来。知识侧却是不可逆的截断。同一个系统里，两条链对"截断"给了相反的承诺。

而 :mod:`core.semantic_anchoring` 定的规矩是：会改变控制流的读取不能从检索到的散文里
反解结构。可当模型确实需要这条知识的全文时，此前它唯一能做的是换个说法再检索一次，
然后祈祷这次命中的片段包含所需内容 —— 既不保证命中同一条，也读不到这一条的其余部分。

这类缺陷不会让任何测试变红：检索"成功"了，上下文也"注入"了，只是模型看到的是残篇，
而且它不知道。
"""

import pytest

from core.rag_memory import KnowledgeChunk, RAGMemory


@pytest.fixture()
def rag(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    return RAGMemory()


def _long_text(n_chars: int = 1500) -> str:
    unit = "这是一条需要被完整读回来的工程知识。"
    return (unit * (n_chars // len(unit) + 1))[:n_chars]


# ── 渲染侧：截断必须可见、可寻址 ──────────────────────────────────────────


def test_truncation_is_marked_and_addressable(rag):
    body = _long_text(1500)
    rendered = rag.format_rag_context(
        [KnowledgeChunk(chunk_id="k-1", content=body, source="Node_105", relevance_score=0.9)]
    )
    limit = rag.RAG_CONTEXT_PREVIEW_CHARS
    assert "已截断" in rendered, "截断必须标出来 —— 静默切掉正是这次修的缺陷"
    assert "k-1" in rendered, "chunk_id 必须渲染出来，否则模型没有回读的把手"
    assert "knowledge__read" in rendered, "必须告诉模型怎么把剩下的取回来"
    assert str(len(body) - limit) in rendered, "剩余字符数要如实报，模型据此判断值不值得再花一次调用"


def test_a_source_without_an_id_says_so_instead_of_pretending(rag):
    # 没有 id 就真的取不回来。这一点必须说出来 —— 让模型以为自己看到了全部，
    # 比让它知道"这里还有但够不着"更糟。
    rendered = rag.format_rag_context([KnowledgeChunk(chunk_id="", content=_long_text(1500), source="X")])
    assert "未提供可回读的 id" in rendered
    assert "knowledge__read" not in rendered, "不给一个用不了的把手"


def test_every_chunk_carries_a_usable_id_even_when_not_truncated(rag):
    """没被截断的那条也要带 id —— 这是它唯一的把手。

    截断的那条，回读提示的尾巴里已经带了 id；**没截断**的那条不出现尾巴。
    可它同样需要 id：这一轮看到的完整内容，会随着上下文压缩被挪走，之后模型想
    再看一眼就只能靠 id 回读。

    这条断言是补上来的 —— 反向验证时把 header 里的 ``id:`` 摘掉，测试竟然没红：
    当时唯一盯着 id 的断言用的是被截断的样本，而那份样本的 id 由尾巴提供，
    header 掉了也照样通过。假绿。
    """
    rendered = rag.format_rag_context(
        [KnowledgeChunk(chunk_id="k-full", content="短到不会被截断。", source="Node_105")]
    )
    assert "已截断" not in rendered
    assert "k-full" in rendered, "完整片段也必须带上 id，否则压缩之后就再也找不回来了"
    assert "id: k-full" in rendered, "id 要以稳定的形式出现，模型才认得出这是把手"


def test_short_knowledge_is_untouched(rag):
    rendered = rag.format_rag_context([KnowledgeChunk(chunk_id="k-2", content="短。", source="Node_105")])
    assert "已截断" not in rendered, "没超预算就不该加任何噪声"
    assert "短。" in rendered


def test_preview_budget_is_a_named_constant_not_a_literal(rag):
    # 500 这个数散在代码里就没法调；它现在是一个有名字的预算。
    assert isinstance(rag.RAG_CONTEXT_PREVIEW_CHARS, int) and rag.RAG_CONTEXT_PREVIEW_CHARS > 0


# ── 回读侧：从候选回到证据 ────────────────────────────────────────────────


def _ingest_and_get_id(rag: RAGMemory, content: str) -> str:
    """走真实的写入路径，拿本地经验日志那条的 id（ingest 无论主后端成没成功都会写它）。"""
    rag.ingest_knowledge(content=content, source="t", source_type="text")
    return rag._experiences[-1].experience_id


def test_read_knowledge_returns_the_original(rag):
    body = _long_text(1500)
    kid = _ingest_and_get_id(rag, body)
    got = rag.read_knowledge(kid)
    assert got["success"] is True
    assert got["total_chars"] == len(body)
    assert got["content"] == body, "默认页足够大时应一次给全"
    assert got["has_more"] is False


def test_pagination_reassembles_byte_for_byte(rag):
    body = _long_text(3000)
    kid = _ingest_and_get_id(rag, body)

    buf, offset, pages = "", 0, 0
    while True:
        page = rag.read_knowledge(kid, offset=offset, limit=700)
        assert page["success"] is True
        buf += page["content"]
        pages += 1
        if not page["has_more"]:
            break
        offset = page["next_offset"]
        assert pages < 50, "分页没有收敛"

    assert pages > 1, "这条内容应当需要多页"
    assert buf == body, "分页拼回的内容必须与原文逐字节相同 —— 回读不可逆就没有意义"


def test_missing_id_is_reported_not_faked(rag):
    got = rag.read_knowledge("根本不存在的-id")
    assert got["success"] is False
    assert not got.get("content"), "取不到时不得返回空串冒充『这条是空的』"
    assert "没有找到" in got["error"]


def test_empty_id_is_rejected(rag):
    assert rag.read_knowledge("")["success"] is False


def test_offset_past_the_end_is_not_an_error(rag):
    body = _long_text(400)
    kid = _ingest_and_get_id(rag, body)
    got = rag.read_knowledge(kid, offset=len(body) + 999)
    assert got["success"] is True
    assert got["returned_chars"] == 0
    assert got["has_more"] is False, "越界不是错误，但也不能谎报还有更多"


def test_negative_offset_is_clamped(rag):
    body = _long_text(400)
    kid = _ingest_and_get_id(rag, body)
    assert rag.read_knowledge(kid, offset=-10)["offset"] == 0


def test_read_reports_which_backend_answered(rag):
    # 回读走哪个后端要能看见 —— 排查"为什么这条读不回来"时这是第一个要问的。
    kid = _ingest_and_get_id(rag, _long_text(600))
    assert rag.read_knowledge(kid)["backend"] in {"Node_105", "experience_log"}


# ── 接线：渲染出的把手必须真的能用 ────────────────────────────────────────


def test_the_handle_rendered_into_the_prompt_actually_works(rag):
    """守的是接线，不是逻辑：渲染里给的 id，拿去回读必须真能取回同一条。

    两边各自正确、但对不上，是这类改动最容易留下的缺口 —— 模型会照着
    prompt 里的 id 去调，然后拿到一个 not found。
    """
    body = _long_text(1500)
    kid = _ingest_and_get_id(rag, body)
    rendered = rag.format_rag_context(
        [KnowledgeChunk(chunk_id=kid, content=body, source="Node_105", relevance_score=0.8)]
    )
    assert f'knowledge__read(chunk_id="{kid}")' in rendered

    got = rag.read_knowledge(kid)
    assert got["success"] is True
    assert got["content"].startswith(body[:50])
