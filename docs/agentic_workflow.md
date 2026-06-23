# 统一 Agent/Workflow 编排层（`forward(session) -> session`）

把现有三种形状各异的 agent 统一到一个最薄的契约之上,借鉴 PyTorch/OpenRath「层是变换、
数据在 Session 里流动」:**Workflow = 一层 Session→Session 变换**,可任意嵌套组合;状态不在
agent 里,而在 Session 里（复用证据链 #1395 / recall-commit #1396）。

模块:`core/agentic/workflow.py`。**最优做法:适配器而非重写** —— 不动任何现有 agent,只把
它们包成 Workflow;适配器接受一个 `invoke` 协程,与具体 agent 构造解耦,因而本层可在无 LLM、
无重依赖下完整单测。

## Session I/O 契约（固定）
- **读输入**:`session.metadata["pending_task"]`,缺省取 history 最后一条 user 消息。
- **写输出**:追加 assistant 消息（自动落 message 证据 chunk）+ `session.metadata["last_result"]`
  + 一条 `workflow:<name>` 证据 chunk。
- forward 进出都是同一个 Session 对象（SessionManager 的活引用),全程可回放。

## 契约与组合子
```python
class Workflow(ABC):
    name: str; description: str          # description 供 Selector 自我描述路由
    async def forward(self, session) -> session: ...
```
- `Agent(invoke, name=...)` —— 通用单层适配器（结果经 `coerce_text` 压成文本写回；失败被
  捕获落证据、不崩整条链）。
- `from_task_agent(factory, agent_id)` / `from_team(team_manager, strategy)` /
  `from_fractal(fractal)` —— 三种真实形状的接线构造器。
- `Sequential([w1, w2, ...])` —— 串联。
- `Parallel([...], merge="collect"|"first_success"|fn)` —— 并联,**每条分支 fork 一个子会话**
  并行跑再 merge 回父会话（复用 Session 血缘;无 SessionManager 时退化为共享会话）。
- `Selector(select_fn, [...], max_steps=)` —— 动态路由,在自我描述的 Workflow 间选下一个,
  返回 <0 终止,带防抖死循环上限。
- `EmptyWorkflow` —— 终止态空操作。
- `WorkflowRunner(workflow).run(session_id, task)` —— 一行驱动入口。

## 边界（重要）
`Selector` 只做**单机内 agent/工作流**编排路由,**不替代**设备级派发权威
（`core.canonical_dispatch_slot_authority` / `openclawd` 执行路径决策）。两层不打架:前者是
执行编排层,后者是控制平面。

## 迁移分阶段（A/B/C 均已落地）
- **A — 纯增量零风险** ✅:契约 + 适配器 + 组合子 + 自测。无任何现有调用方改动。
- **B — 灰度接入** ✅:`from_fractal_executor` / `from_team_manager` 接真实一站式执行器;
  `core/agentic/strategy.py` 的 `run_strategy_workflow` 经会话驱动并压回 ExecutionPlanner
  可消费的 dict;`ExecutionPlanner._dispatch` 用开关 **`GALAXY_UNIFIED_WORKFLOW=1`** 接入,
  **默认关闭**、legacy 为默认与异常兜底 → 零默认行为变化。
- **C — 收口去特判** ✅:`strategy.py` 用**策略注册表**(`register_strategy` / 内置
  fractal·specialized·swarm·parallel·single)取代 if/elif 特判;新增一种 agent 策略只需
  `register_strategy(name, builder)`,无需改动 `build_strategy_workflow` 或 `_dispatch`,
  未知策略回退 `single`。

### 用法
```python
# 灰度开启统一 Workflow 执行路径
import os; os.environ["GALAXY_UNIFIED_WORKFLOW"] = "1"

# 扩展一种新策略（无需改任何 if 分支）
from core.agentic.strategy import register_strategy
from core.agentic.workflow import from_team_manager
register_strategy("my_strategy", lambda llm, fac: from_team_manager(MyManager(), "specialized"))
```

> 把默认翻转成 Workflow 模式（删 legacy `_run_*`）需先在真机上做 parity 验证——legacy 路径
> 携带 StepRecords/twin/SOUL/provider 等丰富元数据,沙箱无法等价复现,故当前保留为默认与兜底。
