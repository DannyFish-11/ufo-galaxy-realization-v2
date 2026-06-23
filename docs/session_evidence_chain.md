# Session 证据链 / 血缘（Session Evidence Chain & Lineage）

借鉴「把 Session 当证据载体，而不只是聊天历史」的思路：一次运行真正有价值的，是
「工作如何一步步推进」的可回放证据——派发决策、主脑选型理由、工具调用入参/结果、
否决与重试、分叉。这些都作为带 `(id, parent_id, trace_id)` 的 **EvidenceChunk** 落进
`Session`，串成一条 chunk 级的有向链；`Session` 之间又能 `fork`/`detach` 成会话级血缘图。

实现位于 `core/session_manager.py`，对既有会话/历史完全向后兼容（新增字段都有默认值，
旧的 `data/sessions.json` 可照常加载）。

## 落进了什么

| 来源 | 谁记录 | kind |
|---|---|---|
| 每条对话消息 | `add_message`（自动） | `message` |
| 主脑选型（候选/硬件/理由） | `unified_launcher` Phase 5 | `model_selection` |
| 执行路径决策（本地/跨设备/混合/none） | `openclawd._determine_execution_path` 两处分支 | `dispatch` |
| 工具调用（入参/结果/状态） | `tool_wrapper_engine.use_tool`（context 带 `session_id` 时） | `tool_call` |
| 校验/审查（通过/否决+理由） | 调用 `record_verdict` | `verdict` |
| 分叉 / 子会话起点 | `fork_session`（自动双向留痕） | `fork` / `branch_root` |

## 怎么用

```python
from core.session_manager import get_session_manager, record_evidence, EvidenceKind

sm = get_session_manager()

# 1) 任意子系统一行落证据（best-effort，采集失败绝不影响主流程）
record_evidence(session_id, EvidenceKind.TOOL_CALL, actor="tool:shell",
                payload={"cmd": "dir", "result": "..."}, trace_id="t-123")

# 2) 工具调用：在 use_tool 的 context 里带上 session_id 即自动留痕
engine.use_tool("shell", "列目录", context={"session_id": sid, "trace_id": "t-123"})

# 3) 校验否决 → 换条路重来：从当前会话分叉一条独立分支（继承历史快照）
child = await sm.fork_session(sid, branch_label="retry-after-reject")
#   detach=True 可切断父链、自成血缘根

# 4) 追溯「这个结论走的哪条分支」
sm.get_lineage(child.id)        # [根, …, 叶] 的会话摘要链
sm.get_evidence(sid, kind=EvidenceKind.DISPATCH)   # 按类别过滤

# 5) 导出可回放的「证据档案」JSONL（含整条血缘的合并视图）
path = sm.export_jsonl(sid, include_lineage=True)
```

## 持久化

- **实时**：每个 chunk 立即 append 到 `data/sessions/<session_id>.evidence.jsonl`
  （append-only、便宜、断电可回放）。
- **快照**：`Session.to_dict()` 也内嵌证据（内存最多保留 `MAX_EVIDENCE=1000` 条，
  JSONL 文件不截断），随 `data/sessions.json` 一起持久化、重启后恢复。
- **导出**：`export_jsonl()` 产出一份合并了血缘祖先的 JSONL 档案，每行一个对象
  （`_type=session_header` / `_type=evidence`），可直接交给下一个工具或做技术报告。
