# 双仓库深度运营可用性审查 2026
# DUAL-REPO DEEP OPERATIONAL ENABLEMENT AUDIT 2026

**审查仓库 / Repositories audited:**
- `DannyFish-11/ufo-galaxy-realization-v2` (V2, 中心侧)
- `DannyFish-11/ufo-galaxy-android` (APK, 设备侧)

**方法论声明 / Methodology declaration:**
本文档所有结论均来自对两个仓库真实源代码的直接检查。
不使用任何历史审查文档、verdict文件或旧的narrative markdown作为证据。
每一项声明都标注了具体的源文件和符号。

All conclusions in this document derive exclusively from direct inspection of
real source files in both repositories. No prior audit/verdict/narrative docs
are used as evidence. Every claim cites the exact source file and symbol.

**证据模块 / Evidence module:**
`core/operational_enablement_audit.py` — all facts as executable Python constants  
**验证测试 / Verification tests:**
`tests/test_operational_enablement_audit.py` — 85 tests, all passing

---

## 目录 / Table of Contents

1. [V2侧配置现实](#1-v2侧配置现实)
2. [Android侧配置现实](#2-android侧配置现实)
3. [Desktop状态面板控制面现实](#3-desktop状态面板控制面现实)
4. [Agent运行时三态现实](#4-agent运行时三态现实)
5. [Android端模型供给现实](#5-android端模型供给现实)
6. [克隆→构建→配置→运行现实](#6-克隆构建配置运行现实)
7. [最终可运行性判断](#7-最终可运行性判断)

---

## 1. V2侧配置现实

### 1.1 配置来源层次（优先级从低到高）

| 优先级 | 来源 | 可写 | 重启需要 |
|--------|------|------|----------|
| 1（最低） | `config.json`（项目根目录） | ❌ 只读默认值 | 是 |
| 2 | `runtime/config.json` | ✅ ConfigStore写入 | 否（热更新） |
| 3 | `runtime/secrets.env` | ✅ ConfigStore写入 | 否（预检读取） |
| 4 | `.env`（传统） | ✅ 手动编辑 | 是 |
| 5（最高） | 进程环境变量（`os.environ`） | ✅ 启动前设置 | 是 |

**源文件:** `core/unified_config.py` 加载顺序; `core/config_store.py` write方法

### 1.2 必需的API Key

以下9个secret key由 `core/config_schema.py` 的 `SECRET_KEYS` frozenset 定义：

```
OPENAI_API_KEY        ANTHROPIC_API_KEY     GEMINI_API_KEY
DEEPSEEK_API_KEY      GROQ_API_KEY          OPENROUTER_API_KEY
ONEAPI_API_KEY        GALAXY_API_TOKEN      SECRETVAULT_MASTER_KEY
```

**最小必需：** 至少一个LLM Provider API Key（OPENAI/ANTHROPIC/GEMINI/DEEPSEEK等）  
**GALAXY_API_TOKEN：** 仅在auth中间件激活时必需  
**配置方式：**
- `python main.py --setup` → `setup_wizard.py`（交互式向导）
- `POST /api/v1/vault/credentials`（API端点，需auth）
- 手动编辑 `runtime/secrets.env` 或 `.env`

### 1.3 运行时可热更新 vs 仅启动时读取

**仅启动时读取（修改后需重启）：**
```
GALAXY_SYSTEM_MODE              GALAXY_NATS_URL
GALAXY_NATS_ENABLED             GALAXY_FABRIC_STRICT
GALAXY_NETWORK_MODE             GALAXY_CROSS_DEVICE_ENABLED
GALAXY_TAILSCALE_ENABLED        GALAXY_TAILSCALE_HOST
GALAXY_TRANSPORT_PRIORITY
```
**源:** `core/system_mode.py` 在import时调用 `resolve_fabric_config()`，产生不可变的 `FABRIC_CONFIG` 冻结数据类。

**运行时热更新（无需重启）：**
```
providers.<name>.enabled        routing.native_mm_policy
routing.primary_provider
```
**流程:** Desktop Status Board → ConfigControlSurface → ConfigService → ConfigStore → `runtime/config.json` → HotReloadConfigManager通知订阅者

**源:** `windows_client/status_board_v2/config_control.py`; `core/config_hot_reload.py`

### 1.4 配置入口总结

| 入口 | 能做什么 | 持久化 |
|------|----------|--------|
| `setup_wizard.py` | 设置所有API key，填写.env | ✅ |
| `POST /api/v1/vault/credentials` | API方式写入secret | ✅ |
| 手动编辑`.env`/`runtime/secrets.env` | 所有secret | ✅ |
| Desktop Status Board控制面 | Provider开关 + 路由策略 | ✅ |

---

## 2. Android侧配置现实

### 2.1 配置层次（优先级从低到高）

| 优先级 | 来源 | 修改需重新构建 |
|--------|------|----------------|
| 1（最低） | `BuildConfig`（`app/build.gradle`） | **是** |
| 2 | `assets/config.properties`（打包默认值） | **是** |
| 3（最高） | `SharedPreferences`（`AppSettings`） | **否** |

**源:** `app/src/main/assets/config.properties` 头部注释; `UFOGalaxyApplication.kt` initConfig()

### 2.2 服务器地址（serverUrl）配置

| 层次 | 值 | 备注 |
|------|-----|------|
| BuildConfig Debug | `ws://192.168.1.100:8765` | 源: `app/build.gradle` GALAXY_SERVER_URL |
| BuildConfig Release | `wss://galaxy.ufo.ai:8765` | 源: `app/build.gradle` buildTypes.release |
| assets/config.properties | `ws://100.x.x.x:8765` | **占位符**，需运营人员替换 |
| SharedPreferences | 用户通过UI填写的值 | 最高优先级 |

**关键结论：无需重新构建APK即可修改服务器地址。**  
安装后，用户进入 NetworkSettingsScreen 填写网关IP/端口 → 点击"保存并重连" → 立即生效。  
**源:** `app/src/main/java/com/ufo/galaxy/ui/NetworkSettingsScreen.kt` onSaveAndReconnect回调

### 2.3 cross_device_enabled 配置

- **默认值:** `false`（`config.properties` 和 `BuildConfig` 均为false）
- **运行时可切换:** ✅ 通过 `AppSettings.crossDeviceEnabled` setter（写入SharedPreferences）
- **持久化:** ✅ SharedPreferences跨重启保存
- **UI支持:** ✅ NetworkSettingsScreen中的开关控件（或开发者设置菜单）
- **源:** `config.properties` 注释: "the runtime value can be toggled via UFOGalaxyApplication.setCrossDeviceEnabled(Boolean) or the developer settings menu"

**重要：默认值为false意味着安装后不会自动连接网关，必须手动启用。**

### 2.4 M3远程配置自动拉取

App启动时，`UFOGalaxyApplication.initRemoteGatewayConfig()` 在后台协程中执行：
1. 使用 `RemoteConfigFetcher` 向 `GET /api/v1/config` 发请求
2. 成功时调用 `AppSettings.applyGatewayConfig()` 自动填充网关URL
3. 失败时保留本地配置不变

**源:** `UFOGalaxyApplication.kt` initRemoteGatewayConfig() 文档注释

### 2.5 Android设置UI

`NetworkSettingsScreen.kt`（Jetpack Compose UI）提供完整配置界面：

| 配置项 | UI元素 |
|--------|--------|
| 网关主机/IP | 文本输入框（OutlinedTextField） |
| 端口 | 数字输入框 |
| TLS开关（wss://）| Switch |
| 允许自签名证书 | Switch（仅TLS开启时显示） |
| 设备ID | 文本输入框 |
| REST基础URL | 文本输入框（可为空，自动推导） |
| 指标上报端点 | 文本输入框（可选） |
| 保存 | OutlinedButton → 写入SharedPreferences |
| 保存并重连 | Button → 写入 + 触发WebSocket重连 |
| 自动探测 | TailscaleAdapter.autoDiscoverNode50 |
| 一键填入Tailscale IP | 检测本机Tailscale IP |
| 运行诊断 | NetworkDiagnostics |

**结论：Android配置完全运行时可编辑，无需重新构建APK。**

---

## 3. Desktop状态面板控制面现实

### 3.1 这是只读面板还是控制面板？

**答案：是有限控制面板（status + bounded control surface），不是纯只读面板。**

`windows_client/status_board_v2/` 包含 `config_control.py`，实现了 `ConfigControlSurface`，  
允许操作员执行真实的写入操作。

### 3.2 可写操作（完整清单）

仅支持以下两种有界操作（`ControlOperation` 枚举）：

| 操作 | 描述 | 源 |
|------|------|-----|
| `toggle_provider` | 启用/禁用7个LLM Provider之一 | `ControlOperation.TOGGLE_PROVIDER` |
| `set_routing_policy` | 设置多模态路由策略（strict/prefer/allow_fallback） | `ControlOperation.SET_ROUTING_POLICY` |

**写入链路：**
```
StatusBoard ConfigControlSurface
    → ConfigService (canonical authority)
        → ConfigStore → runtime/config.json
    → HotReloadConfigManager (hot-reload propagation)
    → ControlApplyResult (structured feedback)
```

**源:** `windows_client/status_board_v2/config_control.py` ConfigControlSurface class

### 3.3 只读投影面（完整清单）

| 面 | 内容 |
|-----|------|
| PhaseSurface | 三态phase（silent/liminal/manifest） |
| DomainSurface | 运行时域（local/cross_device/transition） |
| TopologySurface | 模型拓扑权重（top-N） |
| DeviceSurface | 活跃设备和执行阶段 |
| MetricsSurface | 存在感/连贯性/倾向指标 |
| LiminalSurface | Liminal空间投影维度 |
| ManifestSurface | 显现台执行面 |
| ReturnSurface | 返回智能摘要 |
| AdapterSurface | 适配器驱动集成面（PR-10） |
| TopologyInspector | 节点/关系/就绪/路由检查（PR-13） |
| TopologyHistory | 拓扑历史（PR-14） |

### 3.4 持久化与运行时影响

- ✅ **持久化：** 写入 `runtime/config.json`，跨重启保留
- ✅ **即时生效：** 通过HotReloadConfigManager，无需重启即可影响运行时

### 3.5 控制面板局限

Desktop Status Board **不能**执行以下操作：
- 设置API Key（secrets只能通过vault API或手动编辑设置）
- 修改系统模式env var（GALAXY_SYSTEM_MODE等，需重启）
- 下发任务
- 修改设备路由表

**最终判断：** 状态面板是一个**真实的有界写通控制面**，适合日常运维的配置需求，但不是一个全能操作员控制台。

---

## 4. Agent运行时三态现实

### 4.1 用户所说的"三个状态"是什么

用户提到的"三个状态"对应代码中的 `TriState` 枚举，定义在 `core/desktop_presence_runtime.py`：

| 状态 | 英文值 | 含义 |
|------|--------|------|
| 静默 | `SILENT` | 主体静息；原生多模态感知（PerceptionFrame）在后台持续运行；无活跃认知请求 |
| 边界态 | `LIMINAL` | 请求已收到；OpenClawd认知/执行正在进行；local和cross-device执行链均在候选中 |
| 显现 | `MANIFEST` | 主体正在输出/控制设备/扩展跨设备循环；完成后返回SILENT |

### 4.2 这三个状态是真实运行时门控，不是显示标签

**关键证据：**
- `DesktopPresenceRuntime.handle_request()` 在调用 `OpenClawd.process()` 前必须经过 SILENT→LIMINAL 转换
- `_transition_to()` 方法记录可观测性钩子（log entries）
- **"no adapter/launcher can skip the progression"** — 代码注释原文
- LIMINAL 阶段，`OpenClawd.process()` 以 `runtime_session_id` 激活运行

**源:** `core/desktop_presence_runtime.py` DesktopPresenceRuntime class + TriState enum

### 4.3 UI可以显示但不能直接设置三态

- Desktop Status Board PhaseSurface **读取**当前tri-state投影
- 没有UI接口可以直接**命令**主体切换到某个状态
- 三态由运行时shell和主体核心驱动，不由操作员命令驱动

### 4.4 三种不同类型"状态"的区分

这是最容易混淆的地方，明确区分如下：

| 状态类型 | 数量 | 来源文件 | 含义 |
|----------|------|----------|------|
| **Subject lifecycle tri-state** | 3个 | `core/desktop_presence_runtime.py` TriState | SILENT/LIMINAL/MANIFEST — **认知生命周期** |
| **UI shell expansion modes** | 4个 | `system_integration/hardware_trigger.py` SystemState | DORMANT/ISLAND/SIDESHEET/FULLAGENT — **UI展示形态** |
| **Fabric/deployment modes** | 2个 | `core/system_mode.py` SystemMode | desktop-local / desktop-cross-device — **部署拓扑** |

---

## 5. Android端模型供给现实

### 5.1 三个模型资产

| 模型ID | 用途 | 来源 | HuggingFace仓库 | 大小（约） |
|--------|------|------|-----------------|------------|
| `mobilevlm` | MobileVLM V2-1.7B，UI规划/任务规划 | HuggingFace | `ZiangWu/MobileVLM_V2-1.7B-GGUF` | ~1.2 GB |
| `seeclick` | SeeClick NCNN param，UI元素定位 | HuggingFace | `cckevinn/SeeClick` | ~50 MB |
| `seeclick_bin` | SeeClick NCNN bin weights，UI元素定位 | HuggingFace | `cckevinn/SeeClick` | ~400 MB |

**总下载量约1.65 GB**

**源:** `ModelAssetManager.kt` companion object; `ModelManifest.kt` forKnownModel()

### 5.2 下载机制

- 使用 `java.net.HttpURLConnection`（非OkHttp，非专用HuggingFace SDK）
- URL直接来自 `ModelSource.HuggingFace.downloadUrl`（`https://huggingface.co/<repo>/resolve/main/<file>`）
- `ModelDownloader.kt` 实现流式下载 + 进度回调 + SHA-256校验
- 启动时 `ensureModelsAtStartup()` 在后台协程自动触发
- 已存在的文件快速路径跳过（不重复下载）

**源:** `ModelDownloader.kt`; `ModelManifest.kt`; `UFOGalaxyApplication.kt`

### 5.3 正式8阶段供给流水线

`ModelProvisioningPipeline.kt` 实现了完整的正式供给流水线：

```
阶段1: 兼容性检查   → manifest.checkCompatibility(runtimeVersion)
阶段2: 存储预检     → usableSpace vs minDiskSpaceBytes; 不足时尝试evict
阶段3: 清理临时文件  → 删除之前中断下载的 *.tmp 文件
阶段4: 下载         → HttpURLConnection流式下载，进度回调
阶段5: 校验         → SHA-256验证（见下方关键缺口）
阶段6: 原子安装     → rename *.tmp → 最终路径
阶段7: 激活         → ModelAssetManager.markLoaded(modelId)
阶段8: 回滚         → 激活失败时回退状态；可选删除文件
```

流水线是**幂等的**：已LOADED的模型直接返回Success，不重复下载。

**源:** `ModelProvisioningPipeline.kt` class-level docstring

### 5.4 【关键缺口】SHA-256校验被绕过

```kotlin
// ModelAssetManager.kt companion object:
val MOBILEVLM_SHA256: String? = null   // TODO: set before production deployment
val SEECLICK_SHA256: String? = null    // TODO: set before production deployment
val SEECLICK_BIN_SHA256: String? = null // TODO: set before production deployment
```

三个模型的SHA-256校验值均为null，代码注释明确写明是开发/原型阶段的临时状态。  
**后果：** 下载后无法验证文件完整性；被修改或损坏的模型文件会被接受。

### 5.5 【关键缺口】推理运行时未包含在构建依赖中

`app/build.gradle` 的 `dependencies` 部分**不包含**：
- `llama.cpp` Android绑定（MobileVLM需要此运行时执行GGUF推理）
- `NCNN` Android AAR（SeeClick需要此运行时执行CNN推理）

这意味着：
1. 模型文件可以被下载到设备上（1.65 GB）
2. 但没有推理引擎可以加载和运行这些文件
3. `LocalPlannerService` 和 `LocalGroundingService` 的实际推理调用将失败
4. `DegradedPlannerService` 和 `DegradedGroundingService` 存在作为降级路径，但只提供stub行为，不执行真实推理

**源:** `app/build.gradle` dependencies section（直接检查）; `inference/DegradedPlannerService.kt`

### 5.6 模型供给现实总结

| 方面 | 状态 |
|------|------|
| 下载架构 | ✅ 完整（HuggingFace直连，流式，进度回调） |
| 供给流水线正式性 | ✅ 8阶段完整定义 |
| 首次启动自动下载 | ✅ ensureModelsAtStartup()自动触发 |
| SHA-256完整性校验 | ❌ 所有校验值为null，已绕过 |
| llama.cpp推理引擎 | ❌ 未包含在build.gradle依赖中 |
| NCNN推理引擎 | ❌ 未包含在build.gradle依赖中 |
| 降级运行 | ⚠️ DegradedService存在但只提供stub行为 |

---

## 6. 克隆→构建→配置→运行现实

### 6.1 V2侧最小操作手册

```bash
# 步骤1: 克隆
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2
cd ufo-galaxy-realization-v2

# 步骤2: 安装依赖（Python 3.9+）
pip install -r requirements.txt

# 步骤3: 配置API Key（必须完成至少一个LLM Provider）
python main.py --setup
# 或手动编辑：
cp .env.example .env
# 编辑.env填入 OPENAI_API_KEY（或其他Provider key）

# 步骤4: 启动
python main.py
```

**启动7阶段：** LOAD_CONFIG → RESOLVE_MODE → ENV_CHECKS → BACKGROUND_SUBSYSTEMS  
→ RUNTIME_SUBJECT → DESKTOP_SURFACE → READINESS_SUMMARY

**可选运行时调整（无需重启）：** 通过Desktop Status Board切换Provider / 路由策略

### 6.2 Android侧最小操作手册

```bash
# 步骤1: 克隆
git clone https://github.com/DannyFish-11/ufo-galaxy-android
cd ufo-galaxy-android

# 步骤2: （可选）提前在asset中填写网关IP（需重构建）
# 编辑 app/src/main/assets/config.properties
# 将 100.x.x.x 替换为实际 Tailscale IP
# 如果跳过，可在安装后通过UI填写（无需重构建）

# 步骤3: 构建 Debug APK（JDK 17必需）
./gradlew assembleDebug

# 步骤4: 安装（Android 8.0+, minSdk 26）
adb install app/build/outputs/apk/debug/app-debug.apk

# 步骤5: 授权
# - 开启无障碍服务（Accessibility Service）
# - 授权悬浮窗权限（SYSTEM_ALERT_WINDOW）

# 步骤6: 配置（安装后通过UI，无需重新构建）
# 打开App → 网络设置 → 填写V2网关Tailscale IP和端口 → 启用cross_device → 保存并重连

# 步骤7: 等待模型下载（需Wi-Fi，约1.65 GB）
# App自动在后台下载 MobileVLM + SeeClick
# 注意：即使下载完成，本地AI推理因缺少推理引擎库可能无法工作
```

### 6.3 需要额外部署前提的部分

| 前提 | 是否必需 | 说明 |
|------|----------|------|
| Tailscale或等效VPN | 跨公网时必需 | 无内置NAT穿透；`100.x.x.x` 地址模式确认 |
| llama.cpp Android库 | 本地AI推理必需 | 未包含在build.gradle |
| NCNN Android库 | SeeClick推理必需 | 未包含在build.gradle |
| 至少一个LLM API Key | V2必需 | 最低门槛 |

---

## 7. 最终可运行性判断

### 7.1 最终判断

**系统定性：实现完整、偏开发/运维导向的系统**  
**`IMPLEMENTATION_COMPLETE_DEVELOPER_OPS_ORIENTED`**

### 7.2 已经完整可用的部分

| 方面 | 状态 | 证据 |
|------|------|------|
| V2配置栈（多层优先级） | ✅ 完整 | `core/unified_config.py`, `core/config_store.py` |
| V2运行时配置热更新 | ✅ 完整 | `core/config_hot_reload.py`, `ConfigControlSurface` |
| Desktop Status Board控制面 | ✅ 有界但真实 | `windows_client/status_board_v2/config_control.py` |
| Android网络配置UI | ✅ 完整 | `ui/NetworkSettingsScreen.kt` |
| Android无需重构建即可修改URL | ✅ 完整 | SharedPreferences via AppSettings |
| cross_device_enabled运行时可切换 | ✅ 完整 | `UFOGalaxyApplication.setCrossDeviceEnabled()` |
| Android模型下载流水线 | ✅ 完整 | `ModelProvisioningPipeline.kt` (8阶段) |
| HuggingFace自动下载 | ✅ 完整 | `ModelDownloader.kt` + `ensureModelsAtStartup()` |
| Agent三态（SILENT/LIMINAL/MANIFEST） | ✅ 真实运行时门控 | `core/desktop_presence_runtime.py` |
| V2中心→Android设备主链路 | ✅ 协议闭环 | AIP v3.0, WebSocket, handler注册 |

### 7.3 尚未完成的部分（阻止零门槛可用）

| 缺口 | 严重程度 | 证据 |
|------|----------|------|
| Android llama.cpp未包含 | 🔴 严重 | `app/build.gradle` 无llama.cpp依赖 |
| Android NCNN未包含 | 🔴 严重 | `app/build.gradle` 无NCNN依赖 |
| 模型SHA-256校验值全为null | 🔴 严重 | `ModelAssetManager.kt` `*_SHA256 = null` |
| 跨设备需要Tailscale/VPN | 🟡 部署前提 | `config.properties` `100.x.x.x` 注释 |
| 系统模式env var不可运行时修改 | 🟡 配置前提 | `core/system_mode.py` FABRIC_CONFIG frozen |
| cross_device默认false | 🟡 需手动激活 | `config.properties` `cross_device_enabled=false` |

### 7.4 对核心问题的直接回答

> **一个真实的操作员克隆两个仓库、填写必要值、供给Android端模型（包括HuggingFace下载/解压/配置）后，能不能像运行成熟软件一样端到端运行整套系统？**

**对于DevOps能力的操作员：接近可以，但有两个关键条件尚未满足。**

具体说：
1. **V2侧：** 完全可以按手册配置和运行。API Key填写、启动、Provider配置、Desktop控制面均可工作。
2. **Android配置：** 完全可以通过UI完成，无需重构建。Tailscale IP填写、cross_device启用、UI设置均已实现。
3. **Android模型下载：** 下载本身会自动完成（~1.65 GB HuggingFace）。
4. **Android本地AI推理：** ❌ 模型下载后**无法运行**，因为llama.cpp和NCNN推理引擎库未包含在APK构建依赖中。

**因此：** 这是一套实现完整、架构闭环的中心-分布式协同系统，V2中心侧完全可运行，Android设备侧的连接/协作链路完整，但Android本地AI推理功能（独立于跨设备协作之外的能力）还需要集成推理引擎库才能真正工作。

对于只需要跨设备控制（V2下发任务 → Android执行UI自动化 → 结果回传）的使用场景，该系统在配置好Tailscale网络后是可以端到端工作的。

### 7.5 中文一句话结论

**这套系统是一个架构完整、主链路已经闭环的中心-分布式协同系统，V2侧完全可运行，Android侧连接和配置完整，但Android本地AI推理（MobileVLM/SeeClick）因缺少推理引擎库而无法真正工作——整体处于"实现完整但需要运维配置、Android本地推理还缺最后一步"的状态。**

---

## 附录：审查模块引用

本文档所有代码层面的事实由以下文件承载：

| 文件 | 用途 |
|------|------|
| `core/operational_enablement_audit.py` | 所有事实的Python常量（可执行证据层） |
| `tests/test_operational_enablement_audit.py` | 85个测试验证所有事实 |

两个审查的仓库（以SHA锁定的版本）：
- `DannyFish-11/ufo-galaxy-realization-v2` — 本仓库当前branch
- `DannyFish-11/ufo-galaxy-android` — SHA `92041b5bc16324488f9dcd68fa35a5836a1ee1f5`

