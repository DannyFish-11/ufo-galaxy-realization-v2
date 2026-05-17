# 认知型 PR 启动基线（基于当前 problem statement）

## 1. 问题背景与当前理解

本轮输入没有给出单一功能缺陷或明确 bug 编号，而是要求“开始这个认知 PR”。
据此，本 PR 将问题定义为：

- 先基于仓库现状建立**可落地的认知基线**；
- 明确“后续应在哪些代码路径继续推进”；
- 产出低风险、可审查、可回归的分析型变更，而非臆造大规模功能实现。

该定位与仓库现有审计/认知文档体系一致（`audit/` 与 `tests/test_*_doc.py` 约束模式）。

---

## 2. 证据边界与方法

本 PR 仅使用当前仓库真实代码与文档作为证据，不以历史口述或未落地设计替代代码事实。

核心核查入口：

- 启动权威：`main.py`
- 配置路径：`core/unified_config.py`
- 系统集成：`core/system_integration.py`
- API 聚合与边界：`core/api_routes.py`
- 设备注册与发现：`core/device_registry.py`
- 设备通信协议：`core/device_communication.py`
- MCP 扩展：`core/mcp_loader.py`、`core/routes/protocols.py`
- Skill 扩展：`core/skill_loader.py`、`core/routes/protocols.py`
- Agent 生成与协作：`core/agent_factory.py`
- 设备路由面：`core/routes/devices.py`
- Dashboard 兼容面：`dashboard/backend/main.py`

---

## 3. 代码路径与模块关系（当前可确认）

### 3.1 启动与权威分层

- `main.py` 明确 `python main.py` 为 canonical orchestrator 入口；
- `unified_launcher.py` 在文档注释中被定义为 subordinate bring-up 组件（由 `main.py` 委派）。

### 3.2 配置与运行时读取

- `core/unified_config.py` 明确自身是 compatibility facade；
- 配置权威链是 `config_schema -> config_store -> config_service -> config_preflight -> config_hot_reload`。

### 3.3 API 与协议扩展

- `core/api_routes.py` 是 API 聚合权威入口；
- `core/routes/devices.py` 提供 `/api/v1/devices/*` 设备治理面；
- `core/routes/protocols.py` 提供 `/api/v1/protocols/mcp/*` 与 `/api/v1/protocols/skills/*` 扩展入口；
- `core/api_routes.py` 同时标注 `/ws/device/{device_id}` 在 core 侧为兼容路径，gateway ingress 为 canonical。

### 3.4 设备、扩展与智能体协同

- `core/device_registry.py` 将 DeviceRegistry 定位为 compatibility/indexing/discovery 层，UDM 为权威；
- `core/device_communication.py` 维护统一消息封装（含 `type/action/payload/message_id/timestamp/device_id/correlation_id`）；
- `core/mcp_loader.py` 与 `core/skill_loader.py` 提供动态扩展装载能力；
- `core/system_integration.py` 负责跨能力注册、发现与执行协调；
- `core/agent_factory.py` 提供模板/LLM/分裂等智能体创建路径。

---

## 4. 问题范围推断（基于本次“认知 PR 启动”目标）

在缺少更细粒度需求时，当前最稳妥且高价值的问题范围是：

1. **统一语义层**：梳理“权威路径 vs 兼容路径”，避免后续实现混淆；
2. **协同边界层**：明确启动、配置、API、设备、MCP/Skill、Agent 的衔接关系；
3. **推进准备层**：形成后续功能 PR 可直接引用的上下文与检查清单。

不在本 PR 内做：

- 无证据的大规模架构改写；
- 未定义验收标准的行为变更；
- 对既有 runtime 路径的风险性重构。

---

## 5. 影响面分析

### 5.1 直接影响

- 文档与认知层：提升后续实现 PR 的问题定义清晰度；
- 评审层：为“是否偏离权威路径”提供可复核锚点。

### 5.2 间接影响

- 可减少后续改动中对 `main.py` / `core/api_routes.py` / `core/routes/protocols.py` / `core/device_registry.py` 职责边界的误判；
- 可作为跨模块改动前的最小对齐基线。

### 5.3 风险

- 仅文档与测试约束，运行时行为零改动；
- 风险主要在于文档漂移，已通过测试锚点降低漂移概率。

---

## 6. 建议的后续步骤（面向下一批功能 PR）

1. 在具体需求到位后，先把需求映射到本文件第 3 节路径；
2. 按“权威路径优先、兼容路径最小触碰”拆分技术任务；
3. 每个功能 PR 附带：
   - 变更前后的权威链说明；
   - 至少一个定向回归测试；
   - 对 `core/routes/projection.py` 或 operator/status surface 的可观测性确认（若涉及运行时行为）。

---

## 7. 本 PR 实际改动（最小必要）

- 新增本认知基线文档：`audit/COGNITIVE_PR_PROBLEM_STATEMENT_BOOTSTRAP_CN_2026.md`；
- 新增文档约束测试：`tests/test_cognitive_pr_problem_statement_bootstrap_doc.py`；
- 不修改生产代码逻辑，不引入功能性行为变化。
