# 基于双仓真实代码明确 V2/Android 后续收口责任：推进 Android 真值全链传播与系统可用性补完

> 范围：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`（按一个活系统审查）
>
> 前置：PR 1140（双仓认知基线）→ PR 1141（evidence gate/closure 一致性）→ PR 1142（Android participation truth 进入选路）→ PR 1143（可操作性与三态/治理传播审计）

---

## 1) V2 侧未完成收口（A）

1. **operator/board/readiness 仍未全线同源消费 Android 真值**
   - 已推进：`core/pr4_operator_action_governance.py` 的 board projection 开始输出 `android_participation_verdict` + `latest_closure_reasoning`。
   - 未完成：其他 operator/readiness 投影尚未统一消费同一因果块。
2. **部分路径仍是“摘要可见”而非“决策原因可追溯”**
   - `core/unified_panel_aggregation.py` 已有 `android_participation_verdict`，但并非所有路由都把它当成解释主字段。
3. **closure/readiness 与 Android context 仍需更强绑定**
   - `core/canonical_completion_ingress.py` 已有 `notify_with_android_context()`；
   - 但 readiness 的降级门控与 Android 细粒度约束信号仍未完全拉通。

关键锚点：  
`core/routes/operator.py`, `core/pr4_operator_action_governance.py`, `core/operational_readiness_surface.py`, `core/unified_panel_aggregation.py`, `core/v2_unified_state_contract.py`, `core/canonical_completion_ingress.py`, `core/unified_result_ingress.py`

---

## 2) Android 侧未完成收口（B）

1. delegated result 中 `participation_tier` 需稳定上送（而非偶发/缺失）。
2. `constrained` / `deferred` / local-mode gate / local inference availability / execution pressure 需稳定进入 WS payload 与结果包络。
3. `LocalExecutionModeGate` 与 `AndroidMeshParticipationContract` 的运行时判定，仍有“概念定义 > 稳定上游可消费信号”的缺口。
4. `DurableParticipantIdentity` 连续性语义需与 V2 closure/readiness 路由做更稳定字段对齐。

Android 锚点：  
`GalaxyWebSocketClient.kt`, `AutonomousExecutionPipeline.kt`, `AndroidMeshParticipationContract.kt`, `LocalExecutionModeGate.kt`, `DurableParticipantIdentity.kt`

---

## 3) 跨仓闭环依赖图（C）

Android runtime  
→ WS/reporting payloads  
→ `android_device_state_store`  
→ routing/selection  
→ result acceptance  
→ canonical completion  
→ closure  
→ panel/operator/board explanation  
→ readiness / board projection

| 阶段 | 当前状态 | 证据/说明 |
|---|---|---|
| Android runtime | Android 侧部分 | runtime 能力存在，但部分真值信号未稳定上送 |
| WS/reporting payloads | Android 侧部分 | WS 主链存在，但 `participation_tier/constrained/deferred` 稳定性仍不足 |
| `android_device_state_store` | 已闭合 | V2 可吸收并查询 Android 参与证据 |
| routing/selection | 已闭合 | 已消费 `get_android_participation_evidence` |
| result acceptance | 已闭合 | acceptance gate + quarantine/reject 阻断 fully_closed |
| canonical completion | V2 侧部分 | 已有 `notify_with_android_context()`，但依赖 Android 侧稳定字段 |
| closure | V2 侧部分 | closure 有证据门控，但跨仓解释粒度仍不均匀 |
| panel/operator/board explanation | V2 侧部分 | 本次 board 已开始输出 Android tier + closure reasoning，尚未全路由统一 |
| readiness / board projection | 跨仓未解 | readiness 降级门控仍需 Android 侧更多稳定信号协同 |

---

## 4) 双仓实操可用性跟进（D）

### 仍阻塞 V2 clone/build/use
- 依赖与运行入口清晰度已有基础，但多处“可读存在”与“新用户即跑通”仍有距离（环境配置、联调步骤）。

### 仍阻塞 Android app build/use
- App 构建/安装与本地推理资源准备仍是额外门槛；非 V2 单仓可直接完成。

### 仍阻塞本地模式实用化
- local inference availability 与 gate 决策信号尚未稳定、统一映射到中心侧 readiness/closure 解释。

### 仍阻塞跨设备/多设备实用化
- 体系是中心编排型分布式（非 P2P 对等 mesh fully closed）；多设备协同仍受 Android 信号完备度影响。

### 本次可立即落实的 V2 最小改进
1. `build_operator_board_projection()` 直接消费 `android_participation_verdict`。
2. `build_operator_board_projection()` 输出 `latest_closure_reasoning`（来自统一 reasoning API）。
3. `/api/v1/operator/board/operable-truth` 随 projection 带出上述字段，减少“只有摘要没有原因”的操作面断层。

---

## 5) 本次 PR 的诚实边界

- **不是**宣称双仓已经 fully complete。  
- **不是**把 Android 当被动客户端。  
- **是**把 V2 已可落地的 operator/board 收口继续向前推进，并明确剩余 Android 责任与跨仓依赖。
