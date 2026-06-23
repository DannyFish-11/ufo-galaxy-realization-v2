# 记忆生命周期：recall → run → commit（+ 零依赖 BM25 检索）

把「跑前召回相关记忆、跑后提交本轮」从隐式约定升格为**显式 API**，并把本地词法检索
从朴素 Jaccard 升级到 **BM25**（无需 embedding 服务、无第三方依赖）。

## BM25 检索 — `core/cognitive/bm25_index.py`

零依赖 BM25 Okapi 排序器，比 Jaccard（只看词集合交并比）准:考虑**词频饱和(k1)**、
**文档长度归一(b)**、**稀有词 IDF**。中英混排分词:ASCII 走 `[a-z0-9]+`,CJK 走
「单字 + 相邻双字」二元组。

```python
from core.cognitive.bm25_index import bm25_rank
bm25_rank("微信 消息", [("d1","打开微信发消息"), ("d2","查天气")], top_k=5)
# → [("d1", 3.78), ...]
```

接入点:
- `LongTermMemory.search(query=..., namespace=..., top_k=)` — 按相关度召回长期记忆条目。
- `TaskMemory.retrieve_similar(query, k, min_score)` — 跨会话相似任务检索
  （**顺带修复**:旧实现引用了不存在的 `self._tokenize`/`self.jaccard`,调用即
  `AttributeError`;现改用 BM25,`get_task_lineage` 等依赖它的 live 路径不再崩）。

## 显式生命周期 — `core/session_memory_facade.py`

```python
from core.session_memory_facade import MemoryScope

async with MemoryScope(session_id, query=user_text,
                       user_id=uid, device_id=did) as mem:
    # 【recall】进入作用域即完成召回（短期/任务/长期 + BM25 词法 + 向量）
    messages = mem.context
    await mem.commit("user", user_text)        # 【commit】落库本轮
    reply = await llm(messages + [...])         # 【run】
    await mem.commit("assistant", reply)        # 【commit】
```

或分步调用:
- `recall(session_id, query, depth=, max_turns=)` — 召回，返回可直接喂 LLM 的 messages,
  并在证据链上留一条 `memory.recall` note。
- `commit_turn(...)` — 提交本轮到会话历史 / 工作记忆 / 统一记忆 / 证据链。

`recall()` 是 `get_unified_context()` 的语义化别名（单一召回入口）;`commit_turn()` 是
`record_session_turn()` 的语义化别名。两者都 best-effort,缺可选依赖时优雅降级,绝不影响主流程。
