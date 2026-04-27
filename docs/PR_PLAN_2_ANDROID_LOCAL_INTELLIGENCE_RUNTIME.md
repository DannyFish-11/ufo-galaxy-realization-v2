# PR-2：Android Local Intelligence Runtime Closure

> **目标仓库**：`DannyFish-11/ufo-galaxy-android`（主要）+ `DannyFish-11/ufo-galaxy-realization-v2`（能力状态联动）  
> **优先级**：次高（关闭 P1 gap `GAP_ANDROID_LOCAL_AI_DEFAULT_OFF`）  
> **核心问题**：Android 是成熟的执行 participant，但本地 AI runtime 默认是 NoOp，不是 managed runtime

---

## Problem Statement

Android 端当前状态：

1. **`LocalPlannerService` / `LocalGroundingService` 接口完整**（`inference/` 目录），目标模型已定义（MobileVLM V2-1.7B / SeeClick），WarmupResult 机制已定义
2. **默认实现是 NoOpPlannerService / NoOpGroundingService**：`loadModel()` 返回 `false`，`plan()` 返回 `error = "MobileVLM planner not available: model not loaded"`
3. **无 runtime lifecycle manager**：无 LocalInferenceRuntimeManager，无模型资产 manifest，无下载/校验/缓存机制
4. **能力上报不联动 runtime 状态**：device 在 `capability_report` 中上报的 `local_ai` 能力是否 ready，与实际 `isModelLoaded()` 状态之间没有自动联动
5. **`GAP_ANDROID_LOCAL_AI_DEFAULT_OFF`** 在 `core/dual_repo_system_map.py` 标记 `resolved=False`（P1）

这意味着：Android 在架构上有完整的本地智能接口，但实际运行时是纯执行端，没有本地推理能力的 runtime 治理。

---

## 目标

使 Android 从"强执行端 + NoOp 智能骨架"变为"强执行端 + **有 runtime lifecycle 治理的**本地智能参与端"。

不要求首次提交就实现完整的 MobileVLM/SeeClick 推理。要求：
1. runtime manager 存在并管理 model lifecycle
2. capability report 状态与 runtime 状态诚实联动
3. 降级 fallback 有明确代码路径（不是静默 NoOp）

---

## 具体工作项（Android 侧）

### 1. 实现 LocalInferenceRuntimeManager

**新文件**：`app/src/main/java/com/ufo/galaxy/local/LocalInferenceRuntimeManager.kt`

职责：
- 统一管理 planner 和 grounding 的 model lifecycle（load/unload/warmup）
- 维护 runtime state：`UNLOADED` / `LOADING` / `READY` / `FAILED` / `DEGRADED`
- 提供 `isReady(): Boolean` 作为 capability report 的 truth source
- 在 app 启动时（按配置）触发 warmup，记录 `WarmupResult`

```kotlin
class LocalInferenceRuntimeManager(
    private val plannerService: LocalPlannerService,
    private val groundingService: LocalGroundingService,
    private val config: LocalInferenceConfig
) {
    enum class RuntimeState { UNLOADED, LOADING, READY, FAILED, DEGRADED }
    
    fun startup(): RuntimeState
    fun isReady(): Boolean
    fun getPlannerWarmupResult(): WarmupResult
    fun getGroundingWarmupResult(): WarmupResult
    fun shutdown()
}
```

### 2. 实现 ModelAssetConfig（模型资产 manifest）

**新文件**：`app/src/main/java/com/ufo/galaxy/local/ModelAssetConfig.kt`

字段：
- `modelId`：模型标识符
- `sourceUrl`：HuggingFace 或自定义下载 URL
- `localPath`：设备本地存储路径
- `expectedSha256`：完整性校验
- `quantization`：INT4 / INT8
- `minMemoryMB`：最低内存需求
- `runtimeBackend`：`LLAMA_CPP` / `MLC_LLM` / `NCNN` / `MNN`

### 3. 实现 ModelDownloadManager

**新文件**：`app/src/main/java/com/ufo/galaxy/local/ModelDownloadManager.kt`

职责：
- 检测本地是否有模型文件
- 触发下载（支持后台下载）
- sha256 校验
- 版本/更新检测
- 清理旧版本

不要求在此 PR 中实现完整 HF 下载流程，但接口要定义清楚，占位实现需要诚实返回 `UNAVAILABLE` 而不是 `READY`。

### 4. 将 capability_report 与 runtime 状态联动

**修改文件**：capability 上报逻辑（`capability/` 目录或 WebSocket handler）

当前：capability_report 中的 `local_ai`/`local_planner`/`local_grounding` 字段不与实际 runtime 状态绑定。

需要：
```kotlin
// 上报时查询 runtime manager
val localAiReady = localInferenceRuntimeManager.isReady()
capabilityReport.put("local_ai", localAiReady)
capabilityReport.put("local_planner", plannerService.isModelLoaded())
capabilityReport.put("local_grounding", groundingService.isModelLoaded())
```

### 5. 明确降级 fallback 路径

当 `LocalInferenceRuntimeManager.isReady() == false` 时：
- **选项 A**（推荐）：disable local AI，上报 `local_ai: false`，V2 side 使用其他 provider
- **选项 B**：remote fallback（调用 V2 侧推理），需显式配置
- 禁止：静默 NoOp（调用 plan() 返回 empty steps 但不告知调用方 runtime 不可用）

### 6. Android CI 增加 LocalInferenceRuntimeManager 单测

**新文件**：`app/src/test/.../LocalInferenceRuntimeManagerTest.kt`

测试：
- `UNLOADED` 状态时 `isReady() == false`
- `FAILED` warmup 时 `isReady() == false`，`WarmupResult` 包含 failure stage
- capability_report 中 `local_ai` 与 `isReady()` 一致

---

## 具体工作项（V2 侧）

### 7. 更新 canonical_capability_status.py

**文件**：`core/canonical_capability_status.py`

当 Android runtime manager 存在后，`local_ai` 的 `CapabilityRuntimeStatus` 可以从 `STRUCTURAL_ONLY` 升级为 `DEGRADED`（runtime exists, capability inactive by default）或 `CONDITIONAL`（ready when model loaded）。这需要 PR-2 代码落地后单独更新。

### 8. 将 GAP_ANDROID_LOCAL_AI_DEFAULT_OFF 标记为 resolved

**文件**：`core/dual_repo_system_map.py`

---

## 验收标准

- [ ] `LocalInferenceRuntimeManager` 存在并有单测覆盖
- [ ] `ModelAssetConfig` 定义完整，包含 sha256 字段
- [ ] capability_report 中 `local_ai` 字段值与 `LocalInferenceRuntimeManager.isReady()` 一致
- [ ] 降级路径有明确代码（fallback = disabled or remote），无静默 NoOp
- [ ] `GAP_ANDROID_LOCAL_AI_DEFAULT_OFF` 在 `WORKSTREAM_GAP_REGISTRY` 中 `resolved=True`
- [ ] Android CI unit test 覆盖 runtime manager lifecycle

---

## 预期影响

完成后，Android 从"执行端 + 接口骨架"变为"执行端 + 可治理的本地智能参与端"。即使模型权重暂时不下载，runtime 的状态管理、能力诚实性、降级路径都已成立。这是让系统跨过"准成熟系统"门槛 B 的必要条件。
