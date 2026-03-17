# OpenClawd Capability Matrix — PR-5

> **目的**：对五项能力进行完整的证据链梳理，每项能力均有真实代码落地点、验证路径和可运行样例。

---

## 1. 完全自主执行复杂任务（端到端闭环）

### 能力描述
系统能够端到端自主执行复杂任务，任务生命周期强制流转：`created → running → done/failed`。

### 代码落地点

| 文件 | 改动内容 |
|------|----------|
| `core/schemas/task_envelope.py` | 新增 `lifecycle_status: TaskLifecycleStatus` 字段（默认 `"created"`）；新增 `transition()` 方法验证合法状态转换 |
| `core/task_lifecycle.py` | **新增**：`TaskLifecycleManager` 类，封装 `mark_running()`、`mark_done()`、`mark_failed()`、`run_with_lifecycle()` 四个接口；每次状态变更同时发出 M2 `task.lifecycle` 事件并写 TaskMemory |
| `core/command_router.py` | `route_envelope()` 入口新增生命周期钩子：进入时 `mark_running`；退出时根据结果 `mark_done` / `mark_failed` |
| `galaxy_gateway/orchestrator/task_orchestrator.py` | `_process_task()` 中同样挂载生命周期：`mark_running` → 执行 → `mark_done/failed` |

### 验证路径
```python
from core.schemas.task_envelope import TaskEnvelope
from core.task_lifecycle import TaskLifecycleManager

mgr = TaskLifecycleManager()
env = TaskEnvelope(tool_name="my_tool", targets=["dev1"])
# created
env = mgr.mark_running(env)    # → running
env = mgr.mark_done(env, result_summary="OK")  # → done
assert env.lifecycle_status == "done"
```

### 最小测试
`tests/test_pr5_capability_closure.py::TestTaskLifecycle`（11 个测试用例）

---

## 2. 不依赖视觉/UI 的复杂任务

### 能力描述
系统可以执行纯非视觉任务（文件系统、HTTP、系统命令），执行链路中不调用截图/屏幕状态采集。

### 代码落地点

| 文件 | 改动内容 |
|------|----------|
| `core/schemas/task_envelope.py` | `required_capabilities` 字段为显式列表，调用方可明确声明 `["filesystem"]` 而不包含 `"screen"`，由 ACLEnforcer 校验 |
| `scripts/non_visual_task_demo.py` | **新增**：纯非UI任务端到端演示（filesystem + system_cmd + http_client 三步链路） |

### 验证路径（运行 Demo）
```bash
python scripts/non_visual_task_demo.py
```
预期输出：所有步骤标记 `done`，无截图/UI 调用。

### 无视觉路径说明
`required_capabilities` 不包含 `"screen"` 或 `"screenshot"` → ACLEnforcer 不会要求视觉能力 → 执行器走纯系统/网络路径。

### 最小测试
`tests/test_pr5_capability_closure.py::TestNonVisualTaskPath`（5 个测试用例）

---

## 3. 记住历史操作与上下文

### 能力描述
每次任务附加 `trace_id / task_id / session_id`；任务完成时将摘要写入 `TaskMemory`（memory backflow）；执行前注入最近任务摘要。

### 代码落地点

| 文件 | 改动内容 |
|------|----------|
| `core/schemas/task_envelope.py` | 新增 `session_id: Optional[str]` 显式字段；`log_context()` 加入 `session_id` |
| `core/task_lifecycle.py` | `_write_memory()` 方法：在 `done/failed` 时调用 `TaskMemory.record_task()`；日志打印 `task.memory_backflow` 断言 |
| `core/command_router.py` | `route_envelope()` 进入时注入最近 3 条摘要到 `envelope.metadata["_injected_memory_summaries"]`；日志打印 `task.memory_inject` 断言 |

### 验证路径
```python
from core.schemas.task_envelope import TaskEnvelope
env = TaskEnvelope(
    tool_name="search_docs",
    session_id="session_001",
    trace_id="trace_abc",
)
ctx = env.log_context()
assert ctx["session_id"] == "session_001"
assert ctx["task_id"] == env.task_id
assert ctx["trace_id"] == "trace_abc"
```

日志中搜索：
```
task.memory_backflow | task_id=... session_id=... memory_written=True
task.memory_inject   | task_id=... injecting N recent summaries
```

### 最小测试
`tests/test_pr5_capability_closure.py::TestTaskMemoryContext`（7 个测试用例）

---

## 4. 跨应用 / 跨系统操作

### 能力描述
单次任务可以跨多个设备/系统分阶段执行，结果通过 TaskEnvelope `targets` 多目标字段传递，生命周期和记忆由 `TaskLifecycleManager` 统一管理。

### 代码落地点

| 文件 | 改动内容 |
|------|----------|
| `core/schemas/task_envelope.py` | `targets: List[str]` 已支持多目标；`target` 属性返回第一目标（向后兼容） |
| `scripts/cross_device_task_demo.py` | **新增**：device_a（生成 artifact）→ device_b（处理 artifact）完整两设备管道，使用 `TaskLifecycleManager.run_with_lifecycle()` 追踪每阶段生命周期 |

### 验证路径（运行 Demo）
```bash
python scripts/cross_device_task_demo.py
```
预期输出：
- Phase 1（device_a）: lifecycle `done`
- Phase 2（device_b）: lifecycle `done`
- 两阶段共享 `session_id` 和 `trace_id`

### 最小测试
`tests/test_pr5_capability_closure.py::TestCrossDeviceOrch`（3 个测试用例）

---

## 5. 可扩展高权限任务

### 能力描述
`TaskEnvelope` 携带 `permission_level`（0–3）和 `required_capabilities`；执行前由 `ACLEnforcer` 校验；每次检查（允许/拒绝）均记录审计事件。

### 代码落地点

| 文件 | 改动内容 |
|------|----------|
| `core/schemas/task_envelope.py` | 新增 `permission_level: int (0–3)` 和 `required_capabilities: List[str]` 两个显式字段 |
| `core/acl_enforcer.py` | **新增**：`ACLEnforcer` 类：校验 `permission_level` vs `caller_level`；校验 `required_capabilities` vs `agent_capabilities`；发出 M2 `skill.invoke` 审计事件；返回 `ACLCheckResult` |
| `config/acl_policy.json` | **新增**：策略文件（`strict_above_level`、默认能力集、`audit_all` 开关） |
| `core/command_router.py` | `route_envelope()` 进入时调用 `ACLEnforcer.check()`；ACL 拒绝时立即返回 `ACL_DENIED` 错误 |

### 权限级别
| 级别 | 含义 | 示例工具 |
|------|------|---------|
| 0 | 开放（无限制） | 截图、查询 |
| 1 | 普通（已认证） | 点击、输入 |
| 2 | 提升（管理员） | 写文件、停进程 |
| 3 | 关键（系统级） | 系统命令、批量删除 |

### 验证路径
```python
from core.acl_enforcer import ACLEnforcer
from core.schemas.task_envelope import TaskEnvelope

enforcer = ACLEnforcer()
env = TaskEnvelope(tool_name="system_reboot", permission_level=3)
result = enforcer.check(env, caller_level=0)  # 拒绝
assert result.allowed is False

result2 = enforcer.check(env, caller_level=3)  # 允许
assert result2.allowed is True
```

日志中搜索：
```
acl.audit | task_id=... permission_level=3 caller_level=0 outcome=denied
```

### 最小测试
`tests/test_pr5_capability_closure.py::TestACLPermissions`（9 个测试用例）

---

## 综合端到端验证

`tests/test_pr5_capability_closure.py::TestFullCapabilityChain::test_e2e_lifecycle_acl_memory_chain`

该测试串联所有五项能力：
1. 构造带 `session_id / permission_level / required_capabilities` 的 `TaskEnvelope`
2. ACLEnforcer 校验通过
3. `run_with_lifecycle()` 执行任务（lifecycle `done`）
4. TaskMemory 写入断言（`record_task` 被调用）
5. `trace_id / session_id / targets` 全程携带

### 运行所有测试
```bash
python -m pytest tests/test_pr5_capability_closure.py -v --tb=short
```

### 运行演示脚本
```bash
python scripts/non_visual_task_demo.py
python scripts/cross_device_task_demo.py
```

---

## 6. Multimodal Perception Bus (PR-1)

### Capability Description

OpenClawd can accept multimodal inputs (images, audio, screen metadata) alongside
every chat request.  A dedicated **Multimodal Perception Bus** fuses all modalities
into a single lightweight context dict and injects a compact summary into the LLM
prompt — without modifying text-only request handling.

### How to Send Multimodal Input

Set the `multimodal_context` field on `ChatRequest`:

```python
from core.schemas.multimodal import (
    MultiModalContext, MultiModalImage, MultiModalAudio
)
from core.routes._models import ChatRequest

request = ChatRequest(
    message="What is in this image?",
    multimodal_context=MultiModalContext(
        images=[
            MultiModalImage(
                mime="image/jpeg",
                data="<base64-encoded JPEG>",
                source="webcam",
            )
        ],
        audio=[
            MultiModalAudio(
                mime="audio/wav",
                data="<base64-encoded WAV>",
                source="microphone",
            )
        ],
        screen={"window_title": "VS Code", "resolution": "2560x1440"},
    ),
)
```

Text-only callers omit `multimodal_context` (or leave it `None`) — the behaviour
is **identical** to before PR-1.

### Fusion Pipeline Overview

```
ChatRequest.multimodal_context
        │
        ▼
OpenClawd.process()
        │
        ▼
MultimodalBus.ingest()          ← emits PERCEPTION_INGESTED event
        │
        ├─ extracts images / audio metadata (strips base64 payloads)
        ├─ extracts screen / device metadata
        │
        ▼
ContextFuser.fuse()
        │
        ├─ enforces MAX_IMAGES=20 / MAX_AUDIO=10 size limits
        ├─ builds fusion_summary string, e.g.
        │    "[Multimodal context: 2 image(s) [webcam], 1 audio clip(s) [microphone]]"
        │
        ▼
Fused context dict              ← emits PERCEPTION_FUSED event
  {text, images, audio,
   screen, device,
   fusion_summary}
        │
        ▼
Handler (e.g. _dispatch_chat)
  message = original_message + "\n" + fusion_summary
        │
        ▼
LLM prompt (user turn contains fusion summary)
```

Base64 payloads are **never** stored in the fused dict or written to logs.

### Code Entry Points

| File | Purpose |
|------|---------|
| `core/perception/multimodal_bus.py` | `MultimodalBus.ingest()` — unified entry point |
| `core/perception/context_fuser.py`  | `ContextFuser.fuse()` — pure fusion logic |
| `core/perception/event_types.py`    | `PERCEPTION_INGESTED`, `PERCEPTION_FUSED` aliases |
| `integration/event_bus.py`          | `EventType.PERCEPTION_INGESTED/FUSED` enum members |
| `core/openclawd.py`                 | `process()` wires MultimodalBus and injects summary |
| `core/routes/_models.py`            | `ChatRequest.multimodal_context` field |
| `core/schemas/multimodal.py`        | `MultiModalContext`, `MultiModalImage`, `MultiModalAudio` |

### Running the Tests

```bash
python -m pytest tests/test_pr1_multimodal_bus.py -v --tb=short
```

All 22 tests cover:
- Text-only path (no side-effects, no summary appended)
- Image + audio context → deterministic `fusion_summary`
- Base64 stripping in fused output
- Size-limit enforcement (MAX_IMAGES / MAX_AUDIO)
- `PERCEPTION_INGESTED` / `PERCEPTION_FUSED` event emission
- EventBus failure is non-fatal
- `OpenClawd.process()` text-only path unchanged
- `OpenClawd.process()` with context injects summary into handler message

---

## 7. Scene Interpreter / Interaction Mode Engine (PR-2)

### Capability Description

The **Scene Interpreter** analyses the fused multimodal context (from PR-1) together with the
raw message text and session metadata to select an `InteractionMode` and produce an
`InteractionDecision` carrying UI / voice / avatar hints.  The decision is attached to
`OpenClawd.process()` return payloads as `result["interaction"]` and broadcast on the EventBus
as `INTERACTION_MODE_SELECTED`.

All logic is **rule-based** (no model calls), so latency is near-zero and every rule is
deterministically testable.

### Interaction Modes

| Mode | Value | When selected |
|------|-------|---------------|
| `CHAT` | `"chat"` | Default fallback — no special signal |
| `DEEP_THINKING` | `"deep_thinking"` | Long message (> 40 chars) with analytical/philosophical keywords |
| `CONTROL_CONSOLE` | `"control_console"` | Execution / task / script / command keywords detected |
| `FIELD_ASSISTANT` | `"field_assistant"` | Visual context present **and** pointing/guidance keywords |
| `AMBIENT_COMPANION` | `"ambient_companion"` | Very short message (≤ 8 chars), no strong signal |
| `EXECUTION_BRIDGE` | `"execution_bridge"` | Reserved for future high-trust execution paths |

### InteractionDecision Schema

```python
@dataclass
class InteractionDecision:
    mode: InteractionMode          # Selected mode
    relationship_mode: str         # Human-readable relationship label
    ui_surface: str                # UI renderer hint (e.g. "chat_panel", "control_console")
    voice_mode: str                # Voice channel hint ("off", "ambient", "active")
    avatar_mode: str               # Avatar hint ("idle", "focused", "guiding", …)
    confidence: float              # [0.0, 1.0] interpreter confidence
    rationale: str                 # Short explanation of the decision
```

### Caller Override via `mode_hint`

Pass `mode_hint` (string matching `InteractionMode` value) to bypass all rules:

```python
from core.interaction.scene_interpreter import SceneInterpreter

interpreter = SceneInterpreter()
decision = interpreter.interpret(
    message="任意消息",
    fused_context=fused,
    mode_hint="deep_thinking",   # Force DEEP_THINKING regardless of keywords
)
```

### OpenClawd Integration

`OpenClawd.process()` automatically calls `SceneInterpreter.interpret()` after the PR-1
perception fusion step.  The decision is attached as a top-level `"interaction"` key:

```python
result = await openclawd.process(message="帮我执行部署脚本")
# result["interaction"]["mode"]         == "control_console"
# result["interaction"]["ui_surface"]   == "control_console"
# result["interaction"]["voice_mode"]   == "off"
# result["interaction"]["confidence"]   == 0.9
```

Text-only responses are **fully backward-compatible**: existing keys (`success`, `response`,
`intent`, `trace_id`, `metadata`) are unchanged.  If the interpreter fails for any reason,
`result["interaction"]` is `None` and the main response is unaffected.

### Code Entry Points

| File | Purpose |
|------|---------|
| `core/interaction/interaction_types.py` | `InteractionMode` enum + `InteractionDecision` dataclass |
| `core/interaction/mode_selector.py`     | `ModeSelector` — per-mode hint tables and decision builder |
| `core/interaction/scene_interpreter.py` | `SceneInterpreter` — rule engine + EventBus emission |
| `core/interaction/__init__.py`          | Package re-exports |
| `integration/event_bus.py`              | `EventType.INTERACTION_MODE_SELECTED` enum member |
| `core/openclawd.py`                     | `process()` wires SceneInterpreter after MultimodalBus |

### Running the Tests

```bash
python -m pytest tests/test_pr2_scene_interpreter.py -v --tb=short
```

All 39 tests cover:
- `InteractionMode` enum completeness
- `InteractionDecision` to_dict / from_dict round-trip
- `ModeSelector.build_decision` for every mode + confidence clamping + overrides
- `SceneInterpreter` rule engine: CONTROL_CONSOLE, FIELD_ASSISTANT, DEEP_THINKING, AMBIENT_COMPANION, CHAT
- Caller override via `mode_hint` (valid and invalid values)
- Error resilience (bad `fused_context` never raises)
- `INTERACTION_MODE_SELECTED` event emission
- `OpenClawd.process()` attaches `interaction` key for both text-only and multimodal requests
- No regression on existing text-only response structure


---

## 7. Persona / Spirit Engine (PR-3)

### 能力描述
轻量级 **PersonaState** 系统，跟踪 mood / energy / focus / curiosity / urgency / trust_level / expression_mode 等情感状态，并基于消息情绪、交互模式和任务结果进行规则化更新。完全无模型调用，完全向后兼容。

### 代码落地点

| 文件 | 改动内容 |
|------|----------|
| `core/schemas/persona_state.py` | **新增**：`PersonaState` dataclass + `to_dict()` + `_clip()` |
| `core/persona/persona_rules.py` | **新增**：关键词列表、delta 常量、`derive_mood()`、`derive_expression_mode()` |
| `core/persona/emotion_engine.py` | **新增**：`EmotionEngine.compute_delta()` + `apply_delta()`（纯规则） |
| `core/persona/state_store.py` | **新增**：`StateStore`（内存 per-session）+ `get_state_store()` 单例；emit `PERSONA_STATE_UPDATED` |
| `integration/event_bus.py` | 新增 `EventType.PERSONA_STATE_UPDATED` |
| `core/openclawd.py` | `process()` 在请求前读取状态、在响应后更新状态，并将 `persona_state` 写入返回字典（additive） |
| `tests/test_persona.py` | **新增**：34 个单元测试 |
| `docs/PERSONA_STATE.md` | **新增**：完整文档 |

### 验证路径

```python
from core.persona.state_store import get_state_store

store = get_state_store()
state, delta = store.update_state(
    "sess_demo",
    message="这个脚本崩溃了",
    interaction_mode="control_console",
    task_success=False,
)
assert state.urgency > 0.1
assert state.mood in ("concerned", "focused")
```

### 运行测试

```bash
python -m pytest tests/test_persona.py -v --tb=short
```

34 个测试覆盖：
- `PersonaState` schema + `to_dict()` 序列化
- `EmotionEngine` 所有规则分支（感激、挫败、好奇、紧迫、任务成功/失败、交互模式）
- `StateStore` get / update / reset + EventBus 异常不传播
- `derive_mood` / `derive_expression_mode` 所有优先级
- `OpenClawd.process()` 返回 `persona_state` 且文本调用路径的 `response` 字段不变


---

## 8. InteractionEnvelope — Unified Interaction Protocol (PR-4)

### 能力描述

**InteractionEnvelope** 是每个请求生命周期内，将前三个 PR 的输出统一装配到一个可序列化对象中的**联合上下文信封**。它由 `InteractionBuilder` 在 `OpenClawd.process()` 的末尾装配，并以 `interaction_envelope` 键附加到响应 payload 中，供 Windows / Android / Dashboard 三端动态渲染 UI 时消费。

核心字段：

| 字段 | 类型 | 来源 |
|------|------|------|
| `interaction_id` | `str` (`ix_<hex>`) | 生成于 envelope 构建时，每次请求唯一 |
| `trace_id` | `str \| null` | 来自 `OpenClawd.process()` 的 `trace_id`，与 `metadata.trace_id` 完全一致 |
| `session_id` | `str` | 当前会话 ID |
| `mode` | `str` | `SceneInterpreter` 选出的交互模式（如 `"chat"`, `"deep_thinking"`） |
| `relationship_mode` | `str` | 关系描述标签（如 `"scholar_companion"`, `"user_companion"`） |
| `persona_state` | `dict \| null` | `PersonaState.to_dict()` 序列化结果（PR-3）|
| `multimodal_context` | `dict \| null` | `MultimodalBus.ingest()` 融合结果，已剔除 `images`/`audio` 等二进制字段（PR-1）|
| `output_plan` | `dict` | 渲染提示：`text`, `voice`, `avatar`, `overlay`, `ui_surface` |
| `created_at` | `str` (ISO 8601) | 信封构建时的 UTC 时间戳 |

### 代码落地点

| 文件 | 改动内容 |
|------|----------|
| `core/schemas/interaction_envelope.py` | **新增**：`OutputPlan` dataclass + `InteractionEnvelope` dataclass（含 `to_dict()` / `model_dump()`） |
| `core/interaction/interaction_builder.py` | **新增**：`InteractionBuilder.build()`，装配 envelope；自动去除 binary context key；错误时返回 text-only fallback |
| `core/openclawd.py` | `process()` 在两条返回路径（agent_kernel 路径 + 直接调度路径）末尾各调用 `InteractionBuilder().build()`，将 `interaction_envelope` 写入返回 dict（additive，不改变已有字段） |
| `core/routes/chat.py` | `/api/v1/chat` 在 `JSONResponse` 中附加 `interaction_envelope`（仅当非 None 时） |
| `tests/test_pr4_interaction_envelope.py` | **新增**：36 个单元测试 |
| `docs/OPENCLAWD_CAPABILITY_MATRIX.md` | **更新**：本节 |

### OutputPlan — 各模式默认值

| 交互模式 | `text` | `voice` | `avatar` | `overlay` | `ui_surface` |
|----------|--------|---------|----------|-----------|--------------|
| `chat` | ✓ | — | — | — | `chat_panel` |
| `deep_thinking` | ✓ | — | ✓ | — | `infinite_canvas` |
| `control_console` | ✓ | — | — | — | `control_console` |
| `field_assistant` | ✓ | ✓ | ✓ | ✓ | `field_overlay` |
| `ambient_companion` | ✓ | ✓ | ✓ | — | `ambient` |
| `execution_bridge` | ✓ | — | — | — | `control_console` |

### 样例 JSON

`/api/v1/chat` 响应中新增的 `interaction_envelope` 字段示例（deep_thinking 场景）：

```json
{
  "interaction_envelope": {
    "interaction_id": "ix_3f7a1c9b2e4d5a60",
    "trace_id": "8bc4de02f1a34e99b71c55e2d3a70f61",
    "session_id": "session_4a9f12bc",
    "mode": "deep_thinking",
    "relationship_mode": "scholar_companion",
    "persona_state": {
      "session_id": "session_4a9f12bc",
      "mood": "focused",
      "energy": 0.72,
      "focus": 0.91,
      "curiosity": 0.83,
      "urgency": 0.12,
      "trust_level": 0.5,
      "expression_mode": "quiet_luminous",
      "updated_at": "2026-03-17T05:50:00+00:00"
    },
    "multimodal_context": {
      "fusion_summary": "",
      "modality_count": 0,
      "session_id": "session_4a9f12bc"
    },
    "output_plan": {
      "text": true,
      "voice": false,
      "avatar": true,
      "overlay": false,
      "ui_surface": "infinite_canvas"
    },
    "created_at": "2026-03-17T05:50:00.123456+00:00"
  }
}
```

### 客户端消费建议

* **向后兼容**：`interaction_envelope` 仅在成功响应时出现，不存在该字段时客户端应使用默认 UI。
* **Windows 客户端**：读取 `output_plan.ui_surface` 切换窗口布局；读取 `output_plan.avatar` 决定是否激活 Avatar 渲染层。
* **Android 客户端**：读取 `output_plan.overlay` 决定是否显示屏幕注解；读取 `output_plan.voice` 决定是否开启 TTS。
* **Dashboard**：将 `mode` 和 `relationship_mode` 渲染为状态指示器；展示 `persona_state` 情绪仪表盘。

### 验证路径

```python
from core.schemas.interaction_envelope import InteractionEnvelope, OutputPlan
from core.interaction.interaction_builder import InteractionBuilder
from core.interaction.scene_interpreter import SceneInterpreter

decision = SceneInterpreter().interpret(
    message="请深度分析这套架构设计的底层原理和本质逻辑以及哲学基础",
)
envelope = InteractionBuilder().build(
    trace_id="demo_trace_001",
    session_id="demo_sess",
    scene_decision=decision,
)
assert envelope.mode == "deep_thinking"
assert envelope.output_plan.ui_surface == "infinite_canvas"
d = envelope.to_dict()
assert d["output_plan"]["avatar"] is True
```

### 运行测试

```bash
python -m pytest tests/test_pr4_interaction_envelope.py -v --tb=short
```

36 个测试覆盖：
- `OutputPlan` text_only / from_mode（每种模式）/ to_dict 键
- `InteractionEnvelope` 构建 + to_dict / model_dump 序列化 + 唯一 ID + ISO 时间戳
- `InteractionBuilder` 全输入装配、仅 trace_id/session_id、persona dict/dataclass 两路径、binary key 剔除、error resilience、自定义 output_plan
- `OpenClawd.process()` 返回 `interaction_envelope`（含 trace_id 一致性、output_plan 完整性）
- 现有字段非回归检查（`success`, `response`, `intent`, `trace_id`, `metadata`）

---

## 6. 生成式交互运行时 — UI Surface 选择与渲染（PR-5）

### 能力描述

系统根据 `InteractionEnvelope` 中的交互模式（`mode`）动态选择 UI Surface，
Windows 客户端和 Dashboard 后端均可自适应切换界面布局，现有聊天界面保持回退。

### Surface 类型与映射规则

| 交互模式 (`InteractionMode`) | UI Surface 类型 | 说明 |
|---|---|---|
| `CHAT` | `chat_panel` | 默认对话面板，通用回退界面 |
| `DEEP_THINKING` | `deep_thinking_canvas` | 无限滚动深度分析画布 |
| `CONTROL_CONSOLE` | `control_console` | 任务/脚本执行控制台 |
| `FIELD_ASSISTANT` | `field_assistant_overlay_stub` | 现场辅助覆盖层存根（含视觉上下文） |
| `AMBIENT_COMPANION` | `ambient_companion` | 环境低介入伴侣模式 |
| `EXECUTION_BRIDGE` | `control_console` | 复用控制台界面 |

### 代码落地点

| 文件 | 内容 |
|------|------|
| `core/generative_ui/widget_schema.py` | `SurfaceType` 枚举（5 种 surface）、`SurfaceSpec` 数据类（含 layout_hints）、`get_surface_meta()` |
| `core/generative_ui/surface_selector.py` | `SurfaceSelector.select_surface(envelope)` — 核心映射逻辑 |
| `core/generative_ui/runtime.py` | `GenerativeUIRuntime`（façade）、`get_generative_ui_runtime()`（进程级单例） |
| `core/generative_ui/__init__.py` | 公开 API 入口 |
| `windows_client/windows_client_integrated.py` | `MinimalistWindow.switch_surface(surface_type)` + `render_interaction(envelope)` |
| `dashboard/backend/main.py` | `_make_response()` 接受 `interaction_envelope` 参数，输出 `surface_type` + `interaction_envelope` 字段；WebSocket 响应转发 `surface_type` |

### 验证路径

```python
from core.generative_ui import GenerativeUIRuntime, SurfaceType
from core.schemas.interaction_envelope import InteractionEnvelope, OutputPlan

runtime = GenerativeUIRuntime()

# CHAT 模式 → chat_panel
spec = runtime.render_surface({"mode": "chat"})
assert spec.surface_type == SurfaceType.CHAT_PANEL

# DEEP_THINKING 模式 → deep_thinking_canvas
spec = runtime.render_surface({"mode": "deep_thinking"})
assert spec.surface_type == SurfaceType.DEEP_THINKING_CANVAS

# None envelope → chat_panel (safe fallback)
spec = runtime.render_surface(None)
assert spec.surface_type == SurfaceType.CHAT_PANEL

# SurfaceSpec 可序列化为 JSON
import json
json.dumps(spec.to_dict())  # 不抛异常
```

### 最小测试

```bash
python -m pytest tests/test_pr5_generative_ui.py -v --tb=short
```

41 个测试覆盖：
- `SurfaceType` 枚举值完整性与字符串 round-trip
- `SurfaceSpec` 默认构造、`to_dict()` 键集、JSON 可序列化
- `SurfaceSelector.select_surface()` — 全部 6 种 `InteractionMode` 到 surface 的映射
- None / dict / 对象 / 枚举 `.mode` 等多种入参形式
- 未知模式回退到 `chat_panel`
- `GenerativeUIRuntime.render_surface()` 正常路径与错误容忍
- `get_generative_ui_runtime()` 单例行为
