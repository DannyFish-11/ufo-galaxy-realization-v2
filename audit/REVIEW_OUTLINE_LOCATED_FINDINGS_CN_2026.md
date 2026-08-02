# 审查大纲问题定位报告（B 级 + P 级 + 三仓清单）· 完整版

对《UFO Galaxy V2 第一次与第二次审查问题完整合并总大纲》的 **B1–B22 / P1–P20**，
以及《Galaxy 双仓系统现状清单》的 10 条"还没弄完"，逐条**在代码里定位**。

**审查基线**
- `ufo-galaxy-realization-v2` @ `c4a7949`
- `ufo-galaxy-android` @ `c149d62`
- `galaxy-wearos` @ `9fe2a12`

---

## 零、覆盖度与置信度声明（先读这节）

本报告的结论**强度不均匀**。为免误读，先声明每条结论的来源等级：

| 等级 | 含义 | 条目数 |
|---|---|---|
| **A — 机器验证** | 跑了脚本 / 测试 / probe，有可复现输出 | 14 |
| **B — 精确定位** | 人工读了代码，有确切 `文件:行号` | 31 |
| **C — 静态推断** | 有证据但未穷尽，方向可信、边界可能不准 | 7 |
| **D — 未覆盖** | 明确没审，不下结论 | 见第八节 |

**本轮相对第一版的变化**：新增 wearos 仓（原完全空白）、跑了 4 个既有 probe 与
2 个守卫测试、**修正了 4 条第一版下错的结论**、新增 **11 条**第一版未发现的问题。

**明确未覆盖的范围见第八节** —— 不在报告里的东西不代表没问题，只代表没审。

---

## 一、执行摘要

| 分类 | 已修复 | 部分修复 | 仍存在 |
|---|---|---|---|
| B 级（22） | 8 | 7 | 7 |
| P 级（20） | 2 | 5 | 13 |
| 三仓清单（10） | 5 | 3 | 2 |
| **新发现（原大纲未列）** | — | — | **11** |

### 最高优先级 6 项

1. **B17 感知资源永不释放** — 用户点"隐私暂停"后摄像头指示灯**依然亮着**。
2. **新-1 权威层大规模空转** — 16 个权威模块中 **8 个不在活路径、3 个只告警**（机器验证）。
3. **新-2 三处 `compat` 默认 fail-open** — 闸门自身抛异常时默认**放行**。
4. **B4 Compose 硬编码 Mongo 凭据** — `docker-compose.yml:44` 不可用环境变量覆盖。
5. **新-3/新-4 WearOS 不能独立构建 + 在操作面完全不可见**。
6. **B9 远程脚本直接执行** — `core/nats_server.py:133`、`core/local_brain_manager.py:853`。

---

## 二、新发现（原大纲未列，本轮挖出）

### 新-1 权威层大规模空转 — 仍存在【A：机器验证】

跑 `python3 audit/system_runthrough_prober.py`：

```
Summary: {'architecturally_present': 8, 'soft_path': 3, 'hot_path': 5}
```

**8 个"模块存在但绕过活路径"**：

| PR | 模块 |
|---|---|
| L1 | `core.llm.route_authority` |
| L2 | `core.llm.supply_authority` |
| L3 | `core.llm.context_authority` |
| L4 | `core.llm.execution_authority` |
| V2 | `core.unified_continuity_legality_authority` |
| V4 | `core.unified_orchestration_spine` |
| V5 | `core.canonical_group_completion_closure` |
| V6 | `core.center_authority_boundary` |

**3 个 soft_path（try/except 包裹，失败只告警不阻断）**：
V1 `task_result_canonical_truth_chain`、A2 `android_v2_continuity_contract`、
A4 `android_participant_truth_ingress`。

probe 原文结论：

> L1-L4 cognitive authority and V3-V4 dispatch authority are architecturally
> present but not wired into the live execution chain.

**这是全仓最大的架构问题**，同时是 P5/P6/P7/P16/P18 的根因。

### 新-2 三处 `compat` 默认 fail-open — 仍存在【B】

| 文件:行 | 环境变量 | 默认 |
|---|---|---|
| `core/command_router.py:2076` | `GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE` | `compat` |
| `core/unified_runtime_truth_ingress.py:371` | `GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE` | `compat` |
| `core/unified_result_ingress.py:1310` | `GALAXY_RESULT_INGRESS_CONTINUITY_MODE` | `compat` |

以 V3 派发门为例（`core/command_router.py:2245` 起）：

```python
except Exception as _v3_exc:
    logger.debug("Fallback triggered: %s", _v3_exc)
    _v3_block_reason = f"slot_authority_unavailable:{_v3_exc}"
    if _v3_authority_mode == "strict":
        ...  return V3_SLOT_BLOCKED     # 只有 strict 才拦
    # compat（默认）→ 继续往下派发
```

**语义**：权威模块正常时 V3 是硬门（全部目标被拒会返回 `V3_SLOT_BLOCKED`，`:2153`）；
但**权威模块自己挂了，默认放行** —— "闸门坏了 = 闸门打开"。

`core/unified_result_ingress.py:1318-1324` 同理：`require_review` 裁决**只在 strict 下阻断**。

### 新-3 WearOS 不能独立构建 — 仍存在【B】

`galaxy-wearos/settings.gradle.kts:20-27`：

```kotlin
include(":shared-transport")
project(":shared-transport").projectDir =
    file("${settingsDir}/../ufo-galaxy-android/shared-transport")
include(":shared-protocol")
project(":shared-protocol").projectDir =
    file("${settingsDir}/../ufo-galaxy-android/shared-protocol")
```

`app/build.gradle.kts:125,128` 依赖这两个 project。

**后果**：单独 clone `galaxy-wearos` **无法构建** —— 必须把 `ufo-galaxy-android`
以**精确目录名**放在同级父目录。README 未说明这条硬约束。

### 新-4 WearOS 在操作面完全不可见 — 仍存在【B】

WearOS **是一等设备**：
- 直连 V2 网关：`AIPClient.kt:181-182` → `$url/ws/device/$devId`
- 注册设备：`AIPClient.kt:674` 发 `device_register`
- V2 认它：`galaxy_gateway/android/handlers/auth.py:38`
  `_VALID_DEVICE_TYPES = frozenset({"android", "wearos", "windows", "desktop"})`
- V2 有专属处理：`handlers/wearos_sync.py`、`android_bridge.py:1132` `push_decision_to_wearos`

**但 WearOS 不发 `DEVICE_STATE_SNAPSHOT`**（`app/src/main` 全文无此 MsgType）。

而 `/api/v1/operator/devices/ecosystem`（`core/routes/operator.py:944`）数据源是
`core.android_device_state_store.get_device_ecosystem_summary()`，该 store 只由
`absorb_device_state_snapshot()`（`:1575`）填充。

**→ 手表在 operator 生态视图里是空白的。**「Android→V2 状态投影已闭环」
**只对手机成立**。原清单写"双仓"掩盖了这个盲区。

### 新-5 WearOS 加密存储静默降级明文 — 仍存在【B】

`galaxy-wearos/app/src/main/java/com/galaxy/wear/GalaxyWearApplication.kt:133-137`：

```kotlin
} catch (e: Exception) {
    Log.e(TAG, "EncryptedSharedPreferences init failed, falling back to plaintext: ${e.message}")
    getSharedPreferences(PREFS_FILE, Context.MODE_PRIVATE)
}
```

`auth_token` **静默**落到明文 SharedPreferences，只有一行 `Log.e`，用户与 V2 均无感知。

### 新-6 WearOS 协议覆盖 12/62 — 设计风险【B】

WearOS 只用 12 个 MsgType（`ACK / AUTH / COMMAND / COMMAND_RESULT / DECISION_REQUEST /
EVENT / HANDOFF_ENVELOPE_V* / LIQUID_EVENT / PING / STATE_EVENT / TAKEOVER_RESPONSE`），
而 `shared-protocol/MsgType.kt` 共 **62** 个。共享同一份协议模块却只实现 1/5，
且无契约门标注"手表不支持哪些"，跨设备派发到手表的行为未定义。

### 新-7 审计工具自相矛盾 — 设计风险【A】

四个 probe 对 **V3 是否接线**给出四种答案：

| probe | 结论 | 正确性 |
|---|---|---|
| `system_runthrough_prober.py` | `hot_path / hard` | ✅ |
| `reconciliation_probe.py` | "V3 wired into route_envelope — CLOSED" | ✅ |
| `final_validation_probe.py` SPLIT-01 | "CommandRouter does NOT call V3" | ❌ **过期** |
| `dual_repo_wiring_probe.py` | "Shadow authority — not on hot path" | ❌ **过期** |

**真相**（人工核实）：`core/command_router.py:2084` 确实调用
`get_canonical_dispatch_slots()`，是**懒导入**，两个过期 probe 的朴素 grep 没匹配到。

**问题**：`final_validation_probe.py` 当前输出 `1 CRITICAL PROBE(S) FAILED`，
而该失败是 **probe 自己错了**。长期如此会训练团队忽略 probe 输出。

### 新-8 启动预检软失败 — 仍存在【A】

`audit/reconciliation_probe.py` PROBE 7：

```
[GAP] Startup pre-flight exception handler returns True (soft proceed) — confirmed
      main.py line 449: return True
      main.py line 633: return True
[GAP] main.py: does NOT call center_authority_boundary (V6 not in startup chain)
[OK]  core/system_orchestrator.py: calls center_authority_boundary
```

预检异常 → `return True` → 当作通过继续启动；且 `main.py` 这条路径不做 V6 中心权威断言。

### 新-9 CommandRouter 不用 V1 连续性门，自己另起一套 — 仍存在【A】

`audit/reconciliation_probe.py` PROBE 8：

```
[GAP] CommandRouter does NOT use V1 unified_continuity_legality_authority (gap OPEN)
[--]  CommandRouter has its own independent posture check (Gate A):
      core/command_router.py:511-534  source_execution_eligibility / source_runtime_posture
```

同一个"能不能执行"的判断有两套独立实现。**P16「重复造轮子」最硬的实证。**

### 新-10 CI 平台矩阵：56 个 job 全在 ubuntu — 仍存在【A】

```
$ grep -rn "runs-on" .github/workflows/*.yml | sed 's/.*runs-on: *//' | sort | uniq -c
     56 ubuntu-latest
```

**零 Windows、零 macOS runner**。且
`grep -rln "npm ci|npm run build|electron" .github/workflows/` **零命中**。

而仓库明确支持 Windows：`install_windows.ps1`、`install_taskscheduler.ps1`、
`start.bat`、`requirements-windows.txt`、`windows_service/`、`windows_client/`。

### 新-11 `completion_matrix.json` 不被任何 CI 引用 — 仍存在【B】

`grep -rn "completion_matrix" .github/workflows/ scripts/ Makefile` **零命中**。
对照：`check_repo_hygiene` / `check_debt_freeze` / `check_import_boundaries` /
`check_legacy_regression` / `check_mainline_routing_enforcement` **五个脚本都在 CI 里**。

---

## 三、B 级问题定位

### B1 配置写入接口认证 — 部分修复【B】

- `galaxy_gateway/middleware.py:23-27` `_AUTH_EXEMPT_PATHS` 含 `/api/v1/config`，
  **路径级豁免、不分方法**。
- `core/routes/config.py:17` `APIRouter(prefix="/api/config")` 无 `Depends(require_auth)`；
  `:808` 注释自述"POST /api/config 在本开放路由组"。
- `core/auth.py:70-76` `is_auth_enabled()` **默认 False**（仅 `GALAXY_MODE=production` 强制开）。
- 已修复：读写对称性（`config.py:806-811`，消除"写得进读不出"）。

### B2 桌面感知接口未认证 — 仍存在【B】

`core/routes/perception.py:75` 起，`/api/perception/desktop/{frame,audio,system_audio,analyze,status}`
**全部无 auth 依赖**。默认（auth 关）下任何能连 9000 的进程可投递伪造帧、触发 `/analyze` 模型调用。

### B3 Node_122_Shell — 部分修复【B】

已有 `nodes/Node_122_Shell/main.py:133-157` `_is_command_safe()` = 黑名单（`:53-65`）+
shell 模式元字符拒绝（`:67-69`），`execute()`（`:168`）与 `execute_background()`（`:333`）都调用。
仍存在：黑名单**子串匹配**（`:143-145`），`rm  -rf /` 双空格绕得过；**无白名单**；
`:200`、`:353` 仍是 `create_subprocess_shell`。

### B4 Compose 硬编码 MongoDB 凭据 — 仍存在（高危）【B】

`docker-compose.yml:44`：`MONGODB_URI=mongodb://mongoadmin:mongoadmin123@mongodb:27017`
—— **无 `${...:-}` 包装**。对比 `:126` 可覆盖，说明是遗漏而非设计。

### B5 弱默认凭据 — 仍存在【B】

| 行 | 变量 | 值 |
|---|---|---|
| 107/155/311 | `NEO4J_PASSWORD` / `NEO4J_AUTH` | `neo4j123` |
| 122/249 | `MINIO_SECRET_KEY` / `MINIO_ROOT_PASSWORD` | `minioadmin123` |
| 217/225 | `TURN_PASSWORD` | `galaxy123` |
| 272 | `ONEAPI_SESSION_SECRET` | `galaxy-secret` |
| 370 | `POSTGRES_PASSWORD` | `temporal`（**硬编码，连 `${}` 都没有**） |
| 453 | `MONGO_INITDB_ROOT_PASSWORD` | `mongoadmin123` |

### B6 认证豁免过宽 — 部分修复【B】

过宽项：`/api/v1/config`（见 B1）、`/metrics`（暴露内部拓扑/设备数）、
`/docs` + `/openapi.json`（生产下泄漏完整 API 面）。
已修复：`middleware.py:181-190` fail-safe；`:198-204` `hmac.compare_digest`。

### B7 凭据日志泄漏 — 部分修复（**范围比第一版判断的窄**）【B】

系统扫描 `logger.*(...password|token|secret|api_key...)` 后，绝大多数只是**消息文本**
提到 token，没打印值。真正有风险的只有 3 处：

| 文件:行 | 问题 |
|---|---|
| `nodes/Node_05_Auth/oauth_providers.py:152` | `f"Google token 交换失败: {resp.status_code} {resp.text}"` — **打印 OAuth 响应体** |
| `nodes/Node_05_Auth/oauth_providers.py:271` | GitHub 同上 |
| `nodes/Node_125_MediaGen/pixverse_adapter.py:46` | `f"...API Key: {self.api_key[:8]}..."` — 泄漏前 8 字符 |

结构性缺口仍在：全仓只有 `galaxy_gateway/android/handlers/auth.py:41` 一个 `_mask()`，
**无通用 URL 凭据脱敏**。与 B4 叠加时风险被放大。

### B8 `shell=True` — 部分修复【B】

`windows_service/tray_icon.py:340`（argv 列表 + `shell=True`）、
`nodes/Node_122_Shell/main.py:200,353`、`core/nats_server.py:133`、
`core/local_brain_manager.py:853`、`external/microsoft_ufo/.../shell_client.py:47`。
已修复：`Node_36_UIAWindows/ufo_deep_integration.py:535,548`；
`Node_117_OpenCode/core/opencode_engine.py:279-280`。

### B9 `curl | bash` — 仍存在（高危）【B】

真正执行的两处：
- `core/nats_server.py:133` — `["sh","-c","curl -sf https://get-nats.io | sh"]`
- `core/local_brain_manager.py:853` — `["sh","-c","curl -fsSL https://ollama.com/install.sh | sh"]`

**对照组**：同文件 `core/nats_server.py:218` 对 zip 下载**已做 SHA256SUMS 校验**。
正确做法已存在，只是这条捷径没收口。

### B10 依赖锁定 — 部分修复【B】

Python：`requirements.txt` 84 条大量 `>=`；另有 `requirements-lock.txt` + `requirements.hash.txt`。
**npm：完全未锁定** —— 根 / `electron/` / `electron/renderer/panel/` 三处
`package.json` **均无 `package-lock.json`**。

### B11 Electron CSP — 已修复【B】

`electron/main.js:463-497` dev/prod 双 CSP。prod（`:479-489`）：`default-src 'self'`、
`script-src 'self'`（**无 `unsafe-eval`**）、`object-src 'none'`、`base-uri 'none'`、
`frame-ancestors 'none'`。残留 `style-src 'unsafe-inline'` 属 React 内联样式所需。

### B12 Electron IPC 校验 — 部分修复【B】

已修复：`webPreferences`（`:379-383, 769-772`）全部正确；`galaxy:set-config`
（`:1219-1231`）类型校验；`galaxy:test-runtime`（`:994-995`）白名单。
仍存在：`set-config` **无键白名单**；`_runRuntimeBridge`（`:972-991`）经
`spawnSync(python, ['-c', SCRIPT, ...])` 把渲染层数据送进内联 Python。

### B13 原子写入 / 权限 / 并发 — 部分修复【B】

已修复（`core/atomic_json.py:53-118`）：同目录 mkstemp + `os.replace` + fsync +
finally 清碎片；`:1-12` 记录**刻意回退**"写入时清扫目录"的能力扩张（commit `fae57b1`）——
正确决策。
仍存在：**无显式权限设置**（隐式继承 mkstemp 的 0600，属"碰巧正确"，且会静默改变已有文件权限）；
**无进程间锁**，读-改-写会丢更新。

### B14 `.env` / import 副作用 — 部分修复【B】

本仓已修复且做得好：`main.py:20-31, 89-95, 128-151` 全部关进 `__main__` 守卫，
有测试 `tests/test_entrypoint_import_has_no_env_side_effects.py` 锁定。
仍存在（vendored）：`external/memos/src/memos/log.py:27`、
`api/config.py:26`（**`override=True`**）、`api/start_api.py:23`（**`override=True`**）、
`api/mcp_serve.py:15` 模块级 `load_dotenv()`，会绕过上述守卫。

### B15 Docker/Podman — 部分修复【B】

已修复：`core/container_runtime.py` 完整抽象（`:39` 双运行时、`:483-540` 四种 compose 形态）。
仍存在：`unified_launcher.py:2336, 2391, 2392` **硬编码 `docker compose`**，
podman 用户拿到错误命令。

### B16 stop.sh / PID / 清理 — 部分修复【B】

已修复：`stop.sh:34-38` 修正了"旧 pkill 从来没杀掉过后端"的历史 bug。
仍存在：
1. `stop.sh:21-30` PID **无归属校验**，PID 复用时误杀；
2. `stop.sh:35-37` `A && ok || B && ok || true` 求值为 `(((A&&ok)||B)&&ok)||true`，成功时**重复打印**；
3. **无 `stop.bat`**。

### B17 感知资源释放 — 仍存在（高危 · 隐私）【B】

`electron/renderer/perception-capture.js`：`:64` 摄像头、`:85` 屏幕、`:96` 麦克风；
**全文零 `getTracks()` / `.stop()` / `beforeunload`**。

后端 `/api/perception/desktop/pause`（`core/routes/perception.py:217`）只让 store 拒收帧，
**前端采集不停** —— 摄像头指示灯依然亮、麦克风依然在采。

### B18 日志句柄 / Windows 文件锁 — 仍存在【B】

`unified_launcher.py:993`（docker.log）、`:1161`、`:1259`（同一个 electron.log）
三处 `open(...,"ab")`，**全仓零 `.close()`**。
对照 `launch_desktop.py:468-479` 做对了。

### B19 测试污染 — **已修复（第一版判断有误）**【A】

第一版标"需要运行验证"。实际已有**两个专职守卫测试**（commit `fb9708a`）：
`tests/test_repo_write_isolation.py`、`tests/test_no_test_hijacks_a_singleton.py`。

实跑：

```
8 passed, 1 warning in 10.28s
=== 污染检查 === >>> 工作区干净
```

守卫记录了两个真实回归：`CapabilityManager` 落盘到仓库路径；
`KnowledgeBaseSystem` 把 `knowledge_db/knowledge_entries.json` 提交进仓库。
隔离在 `tests/conftest.py` **模块级**完成（进程单例，fixture 太晚）。

**残留**：全量套件因沙箱缺 `numpy` 等依赖无法跑（29 个 collection error），
全量污染面仍需完整依赖环境验证一次。

### B20 CI 门 — 部分修复【A】

已有 12 条 workflow、56 个 job，5 个自研检查脚本在 CI 内。
仍存在：**零前端构建**、**零 Windows/macOS runner**（新-10）→ 生产加载路径零覆盖。

### B21 文档漂移 — 部分修复（**分项结论差异很大**）【A + B】

| 子项 | 结论 | 证据 |
|---|---|---|
| 端口 | ✅ **无漂移** | README `:38,114,119,303,334` 与 `electron/main.js:111` 一致 9000，`:95` env 优先 |
| Provider / 模型 | ✅ **无漂移** | 跑 `scripts/verify_provider_apis.py`：`registry 17 家 · CONFIG_SCHEMA 155 键 · 角标名单 23 · 面板输入框 23 · ✅ 四份清单无漂移` |
| **快捷键** | ❌ **严重漂移** | 见下 |

`electron/main.js:691-692` 原文：

> 之前没有任何唤醒快捷键被真正注册（**启动横幅写的 Ctrl+Space 是假的**），而且
> Ctrl+Space 在中文 Windows 会被输入法抢去切换中英文 → 用户「按不开」。

实际注册（`:694-704`）：
- 唤醒：`CommandOrControl+Alt+Space`、`CommandOrControl+Shift+Space`、
  `CommandOrControl+Alt+G`、`CommandOrControl+Shift+G`
- 隐藏：`CommandOrControl+Alt+H`、`CommandOrControl+Shift+H`

**文档仍写 `Ctrl+Space`**：`docs/CLONE_TO_USE_DESKTOP.md:25,159,162`、
`docs/OFFICIAL_DOCUMENTATION.md:85,555`。
**第三个值**：`docs/HARDWARE_TRIGGER_FIX_REPORT.md:238` 写 `Ctrl+Shift+Space`。
**隐藏快捷键文档里一处都没有。**

→ 用户照文档按 `Ctrl+Space` **永远唤不出覆盖层**。

### B22 Panel 构建产物一致性 — 部分修复【B】

**已修复的两个历史坑**：
1. `.gitignore:16-21` 显式放行 `panel/src/lib/**` —— Python 的 `lib/` 规则曾误伤，
   导致 `api.ts`"从未进过仓库，克隆方只能用预编译 dist"。现 26 个 src 文件全部入库。
2. Vite 入口曾误指向已构建的 `assets/*.js`，"每次构建只是复制旧产物、源码改动永远不生效"。
   现 `index.html` 正确指向 `/src/main.tsx`。

**仍存在**：无一致性门（见 B20）。抽样 6 个 UI 字面量在 dist 中**均命中**，
说明当前 dist 不是明显过期 —— **但这是抽样，不是证明**。

---

## 四、P 级问题定位

### P1 多入口重复实现 — 仍存在【B】

| 入口 | 行数 | 自述 |
|---|---|---|
| `main.py` | 1149 | `:178` 权威入口，`unified_launcher` 是 **subordinate** |
| `unified_launcher.py` | 2512 | 实际编排实现体 |
| `launch_desktop.py` | 766 | `:27` "Phase 2: 启动 Gateway (python main.py)" |
| `system_manager.py` | 661 | 第四套 |

`launch_desktop.py:471-472` 把 `python main.py` 拉起为子进程，同时 `:488-541` 自带
Electron、`:543-599` 自带 Tauri。

### P2 权威边界不清 — 部分修复【B】

已有 `main.py:178-193` subordinate 声明 + `entrypoint_role_contract.py`（`main.py:269`）。
仍存在：`launch_desktop.py` 不在契约表述内。

### P3 Electron 第二套后端生命周期 — 仍存在【B】

`electron/main.js:947-950` `galaxy:start-backend` → `ensureGatewayOnline(true)` →
`:281` 自行 spawn 后端。四个可能的拉起者。
已有缓解（`launch_desktop.py:491-494` 共享锁、`electron/main.js:262-271` 端口占用判活）
**是补丁，不是消除**。

### P4 启动参数语义不一致 — 仍存在【B】

`main.py:1015-1031` 与 `launch_desktop.py:613-628` 参数集**几乎不相交**。
`--verbose` vs `--debug` 同义不同名；`--model` 同名不同义
（`main.py:1022` 自由字符串 vs `launch_desktop.py:621` `choices=AVAILABLE_MODELS`）。

### P5 无唯一 StartupOrchestrator — 仍存在【B】

`core/system_orchestrator.SystemOrchestrator` 存在，`main.py:420` 实例化，
但 `launch_desktop.py` 与 `electron/main.js` 都绕过它。

### P6 / P7 无统一 StartupPlan / 启动状态模型 — 仍存在（**结论已精确化**）【B】

**第一版写"搜不到即不存在"是弱结论。实际更值得说：模型存在，但启动器不用。**

- `core/system_orchestrator.py:85` **有** `class StartupPhase(Enum)`，配套
  `:117` `phase: StartupPhase`、`:213` `PhaseHook` 注册机制 —— 正经状态模型。
- **`unified_launcher.py`（2512 行，真正跑 Phase 1–6 的那个）从不 import 它**，
  用的是 ad-hoc 元组列表：
  - `:1680` `phases_state.append((name, status, hint))`
  - `:427-430` 按**整数下标**改写：
    ```python
    name0, status0, _hint0 = phases_state[ai_brain_phase_idx]
    if status0 != "ok" and st2 != status0:
        phases_state[ai_brain_phase_idx] = (name0, st2, ...)
    ```
- `StartupPhase` 唯一外部使用者是 `scripts/validate_runtime.py:1860`。

→ 与新-1 同构：**模型建好了，主执行体不用**。

### P8 / P15 状态源分裂 — 仍存在【C】

Electron `main.js:1096-1097` 两份缓存；后端 `core/projection/` 四个编译器
（`projection_compiler` / `runtime_projection` / `runtime_truth_compiler` / `assembly_governance`）；
Overlay `renderer/app.js` 独立。三者无共同状态模型。（C 级：未穷尽枚举。）

### P9 端口 / URL 多真相源 — 部分修复【B】

已收敛：`electron/main.js:91-118` `resolveGatewayPort()` 单点，CSP（`:470,482`）复用同一常量。
仍存在：`launch_desktop.py:472` 独立传 `--host/--port`。

### P10 容器/网关/Electron 生命周期未统一 — 仍存在【B】

见 B15、P3、B18。

### P11 进程归属规则 — 部分修复【B】

启动侧有复用规则（`electron/main.js:262-271`），停止侧无归属判定（B16.1）。**不对称**。

### P12 停止/重启/异常清理 — 仍存在【B】

见 B16、B18。另：`launch_desktop.py:536,598` 用
`CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` 起 Electron/Tauri ——
detached 进程在父进程异常退出后**不被清理**，且不在任何 PID 文件里。

### P13 Panel 未成为统一控制面 — 仍存在（确证）【B】

后端 `core/routes/operator.py` **32 个**端点：`/api/v1/readiness`（`:643`）、
`operator/snapshot`（`:289`）、`devices/ecosystem`（`:944`）、
`devices/execution-events`（`:1074`）、`devices/dispatch-readiness`（`:1871`）、
`operator/flows`（`:670`）、`operator/action`（`:1179`）、9 个 `inspect/*`（`:340-545`）…

面板实际消费（从 `src/lib/api.ts` + `hooks/*.ts` + `components/*.tsx` 提取）：
```
/api/config, /api/config/all, /api/config/probe
/api/perception/desktop/status
/api/v1/chat/stream
/api/v1/connectors[...]
/api/v1/mesh/worker/toggle
/api/v1/models/{catalog,latency-probe,status,tier,verify-provider}
/api/v1/nodes/roster, /api/v1/nodes/{n}/{action}
/api/v1/sessions/{id}
```

**交集为空 —— operator 端点消费数 = 0。**

### P14 src/dist/Electron 一致性门 — 仍存在【B】

见 B20 + B22。`electron/main.js:740` 注释"优先加载 Vite 构建产物 (dist/)"、
`:776` `loadFile(panelPath)` —— dist 过期则用户看到旧界面且无人报警。

### P16 重复造轮子 — 仍存在（有硬实证）【A】

**最硬的一条**：新-9 —— CommandRouter 不用 V1 连续性权威，自己另有 Gate A。
其余：配置三份（`config.py` CONFIG_SCHEMA / Electron 双缓存 / `core/config_store`）；见 P9/P10。

### P17 重试/退避未统一 — 仍存在【B】

17 个非测试模块各自实现，包括 `core/reliability_contract/retry_policy.py`（意图中的统一实现）、
`core/llm/failover.py`、`core/unified/connection_manager.py` 与
`core/connection_manager.py`（**重名不同路径**）、`core/task_graph_runtime.py`、
`core/task_graph.py`、`core/command_router.py`、`core/tool_guardian.py`、
`core/galaxy_federation.py`、`core/ha_bridge.py`、`core/openclawd.py`、
`core/desktop_presence_runtime.py`、`core/continuum/temporal_engine.py`、
`core/orchestration/lifecycle.py`、`core/canonical_task.py`、
`core/schemas/execution_failure.py`、`core/unified/error_mapper.py`。

前端第三套：`electron/main.js` `fetchWithRetry` + `CONFIG_FETCH_BUDGET_MS`（`:1120`）。
`:1278` 注释自述 **"= 78000ms 今日实际值；main.js 改动后渲染层兜底常量需同步更新"**
—— 手工同步常量的漂移风险，正是统一化缺失的直接症状。

### P18 功能保留矩阵 — 仍存在【B】

`audit/completion_matrix.json` 存在但**不被任何 CI 引用**（新-11）。

### P19 测试未覆盖生产启动链路 — 仍存在【A】

CI 无前端构建（新-10）→ 生产加载路径零覆盖。
未见 "`start.sh` → 后端就绪 → Electron 加载 dist → 面板取数" 的端到端冒烟。

### P20 Windows/安装器/容器/Electron 验收门 — 仍存在【A】

56 job 全 ubuntu、零 Windows、零 Electron（新-10）。
仓库明确支持 Windows 却零 CI 覆盖，且无 `stop.bat`。

---

## 五、三仓清单逐条核对

### P0 三条 —— 实际都已闭环，清单已过期

#### 1. `DEVICE_STATE_SNAPSHOT` 入向 — 已修复（**仅手机**）

| 环节 | 证据 |
|---|---|
| 协议 V2 | `galaxy_gateway/protocol/aip_v3.py:392` |
| 协议 Android | `shared-protocol/MsgType.kt:151` |
| **V2 注册** | `galaxy_gateway/android_bridge.py:1113` |
| V2 handler | `galaxy_gateway/android/handlers/device_state_snapshot.py` |
| V2 存储 | `core/android_device_state_store.py:1575` |
| **Android 发射** | `GalaxyConnectionService.kt:5722-5728` |
| 触发点 | `GalaxyConnectionService.kt:4790-4795`（服务启动 + WS 重连）；`StateHandler.kt:236` |
| REST 出口 | `core/routes/operator.py:944, 1021` |

⚠️ **WearOS 不发** —— 见新-4。

#### 2. `DEVICE_EXECUTION_EVENT` 入向 — 已修复（**仅手机**）

V2 注册 `android_bridge.py:1114`；Android 发射 `GalaxyWebSocketClient.kt:2793-2800`，
调用点 `GalaxyConnectionService.kt:1017`；离线补偿 `OfflineQueue.QUEUEABLE_TYPES`；
REST 出口 `core/routes/operator.py:1074`。

#### 3. 报告结构化摄取 — 已修复

| 类型 | 协议 | 摄取 |
|---|---|---|
| `device_readiness_report` | `aip_v3.py:378` | `handlers/generic.py:36` → `android_evaluator_artifact_ingress` |
| `device_governance_report` | `aip_v3.py:379` | `generic.py:37` → 同上 |
| `device_strategy_report` | `aip_v3.py:381` | `generic.py:38` → 同上 |
| `device_acceptance_report` | — | `handlers/acceptance_report.py:36` → `android_acceptance_evidence_store` |

映射 `handlers/evaluator_artifact_report.py:16-18`；归一化 `runtime_ws_profile.py:95-125`。
**不再是日志转发。**

### P1 两条

#### 4. Operator 控制台 UI — 仍存在（确证）→ 见 P13

#### 5. 就绪矩阵 REST — 已修复

`/api/v1/readiness`（`:643`）、`operator/snapshot`（`:289`）、
`devices/{id}/dispatch-readiness`（`:1817`）、`devices/dispatch-readiness`（`:1871`）、
`board/operable-truth`（`:1514`）、`/api/v1/ports`（`:908`）、
`operator/{llm,nats,heartbeat}`（`:744,804,850`）、9 个 `inspect/*`。

#### 6. `hybrid_execute` — 部分修复（单边死路）

- **Android 已完整实现**：`HybridExecuteFullCoordinator.kt:47`，接线
  `GalaxyConnectionService.kt:266-268`，能力标注 `HybridParticipantCapability.kt:44`
  `HYBRID_EXECUTE_FULL | AVAILABLE`
- **V2 从未接线**：`aip_v3.py:313` 仅常量；`android_bridge._message_handlers` 无此条目；
  全仓非测试代码**零发送点**
- `core/routes/hybrid.py:58` 的 REST 走本地 `core.hybrid_executor`（A2A→GUI→VLM），
  与跨设备协议无关
- probe 佐证：`reconciliation_probe.py` → `[!!] hybrid_execute dead path retired — OPEN`

→ 准确说法：**Android 单边实现，V2 侧未接线，跨设备混合执行不可达**。

### P2 四条

#### 7. Android 本地推理（llama.cpp / NCNN）— 仍存在

`app/build.gradle:260-278` 说明原因（JitPack 坐标永远无法解析，走
`System.loadLibrary` + 手动放 `.so`）。
**实况**：`app/src/main/jniLibs/` 下**只有 README.md，零 `.so`**；
`app/build.gradle` 无 `externalNativeBuild` / `ndkVersion` / `CMakeLists`。
→ `NativeInferenceLoader` 必然 loadLibrary 失败，本地推理走降级。

#### 8. 模型 SHA-256 — 部分修复（TOFU 已落地）

静态常量仍 null：`ModelAssetManager.kt:114-115`。
**已实现 TOFU**：`:424-441` `persistComputedChecksum()` 首下载落盘；
`:452-470` 启动回读 + `Regex("[0-9a-fA-F]{64}")` 格式校验；
`:30` "TOFU 窗口仅存在于首次下载"；commit `f6f942d` 补齐两处下载点。
**残留**：首次下载窗口零完整性保证，中间人投毒 → 毒化摘要被持久化 → 之后每次都"通过"。

#### 9. 多设备并发编排 — 部分修复【C】

已有 `core/multi_device_coordination_authority.py`、
`handlers/goal_execution.py`（含 `handle_parallel_subtask`）、
`mesh_lifecycle.py` / `mesh_topology.py` / `peer_exchange.py`、
`/api/v1/operator/dispatch`（`operator.py:1268`）。
**但** V5 `canonical_group_completion_closure`（群体完成闭合）在新-1 中被判为
`architecturally_present` —— **群体完成闭合不在活路径上**。回归验证需实机。

#### 10. clone 后零门槛即用 — 仍存在

阻塞项：Android 需自编译 `.so`（第 7）；**WearOS 需兄弟仓同级放置才能构建（新-3）**；
npm 无 lock（B10）；Compose 弱默认凭据（B5）；`curl|sh` 依赖外网（B9）；
面板 dist 无一致性保证（B22）。

---

## 六、修复优先级

### 立即（安全 / 隐私，均为单文件小改动）

| 编号 | 位置 | 动作 |
|---|---|---|
| B17 | `perception-capture.js` | `stopAll()` + `beforeunload` + 隐私暂停时同步停轨 |
| 新-2 | `command_router.py:2076` 等 3 处 | `compat` 默认改 `strict`，或至少让 fail-open 显式可见 |
| B4 | `docker-compose.yml:44` | 改 `${MONGODB_URI:?}` |
| B5 | `docker-compose.yml` 7 处 | 弱默认改 `${VAR:?}` |
| B9 | `nats_server.py:133`、`local_brain_manager.py:853` | 删 `curl|sh`，复用 `:218` 已有的 SHA256 校验 |
| B2 | `core/routes/perception.py:75` | 路由组加 `Depends(require_auth)` |
| 新-5 | `GalaxyWearApplication.kt:133` | 明文降级必须上报，不能只 `Log.e` |

### 短期（工程闭环）

| 编号 | 动作 |
|---|---|
| B10 | 提交 3 份 `package-lock.json`，CI 改 `npm ci` |
| B20/B22/P14 | CI 加 `npm ci && npm run build && git diff --exit-code dist/` |
| B21 | 改 5 处文档的快捷键，补隐藏快捷键说明 |
| B18 | `unified_launcher.py:993,1161,1259` 三句柄显式关闭 |
| B16 | `stop.sh` PID 归属校验 + 修 `&&/||` + 补 `stop.bat` |
| B15 | `unified_launcher.py:2336,2391,2392` 改用 `container_runtime.compose_base()` |
| 新-3 | wearos README 写明兄弟仓约束，或改 composite build / maven 发布 |
| 新-7 | 修或删两个过期 probe |
| 新-10/P20 | CI 加 Windows runner + Electron 构建 job |

### 中期（架构）

| 编号 | 动作 |
|---|---|
| **新-1** | **决定 8 个 architecturally_present 模块的去留：接进活路径，或正式删除。留着最糟** |
| 新-9/P16 | CommandRouter Gate A 与 V1 连续性权威二选一 |
| P13 | 面板接入 32 个 operator 端点（纯前端工作，后端已就绪） |
| 新-4 | WearOS 发 `DEVICE_STATE_SNAPSHOT`，进 operator 生态视图 |
| 三仓-6 | `hybrid_execute`：V2 接线 or 正式退役 |
| P6/P7 | `unified_launcher` 改用 `StartupPhase`，消除 ad-hoc 元组 |
| P1–P5 | `launch_desktop.py` 退化为 `main.py` 薄 wrapper |
| P17 | 统一到 `core/reliability_contract/retry_policy.py` |
| 三仓-8 | 钉死模型 SHA-256，TOFU 降为兜底 |
| 三仓-7 | 提供预编译 `.so` 或 `externalNativeBuild` 通路 |

---

## 七、需要运行验证的条目

1. **B19 全量污染面** —— 本轮只验了 2 个守卫测试（通过、工作区干净）。全量需完整依赖：
   ```bash
   git status --porcelain > /tmp/a; python -m pytest tests/ -q; git status --porcelain > /tmp/b; diff /tmp/a /tmp/b
   ```
2. **B22 dist 与 src 是否真一致**：
   ```bash
   cd electron/renderer/panel && npm ci && npm run build && git diff --stat dist/
   ```
3. **B17 摄像头指示灯** —— 隐私暂停后观察硬件指示灯（预期：不熄灭）。
4. **新-3 WearOS 独立构建** —— 单独 clone 跑 `./gradlew assembleDebug`（预期：失败）。
5. **B13 并发写配置** —— 两进程同时 POST `/api/config` 不同键，验证丢更新。
6. **三仓-9 多设备并发编排** —— 两台真机并行子任务（V5 不在活路径，风险高）。
7. **新-2 fail-open** —— 人为让 slot authority 抛异常，确认 compat 下派发确实继续。

---

## 八、明确未覆盖的范围（不下结论）

以下**没有审**，不代表没问题：

| 范围 | 规模 | 说明 |
|---|---|---|
| `nodes/` 其余节点 | 128 个目录 | 只审了 `Node_122_Shell` / `Node_05_Auth` / `Node_117` / `Node_125` / `Node_36` |
| `enhancements/` | 19 个目录 | 完全未审 |
| `external/` vendored | memos / microsoft_ufo 等 | 仅就 B8/B14 扫了两个点 |
| `unified_launcher.py` 全文 | 2512 行 | 只读 Phase / 日志 / compose 片段 |
| `core/openclawd.py` | 9718 行 | 未读 |
| `core/routes/projection.py` | 7715 行 | 未读 |
| `core/command_router.py` 全文 | 5435 行 | 只读 V3 门与 Gate A 片段 |
| `audit/` 既有 30 份文档正文 | ~800 KB | 只跑了 4 个 probe，未逐字读 |
| WearOS UI / sensing 层 | ~10.5k 行中的多数 | 只审了协议 / 网络 / 凭据 / 构建 |
| `panel/src` 组件逻辑 | 26 文件 | 只做端点消费面提取，未审逻辑正确性 |
| 性能 / 并发正确性 | — | 全未审 |

---

## 九、结论

**大纲 42 项（B22 + P20）+ 三仓清单 10 项全部完成定位；另新增 11 项原大纲未列的问题。**

需要修正原判断的地方：

1. **三仓清单的 P0 三条实际已闭环**（清单过期）—— 但**仅对手机成立**，
   WearOS 是操作面盲区（新-4）。原清单写"双仓"掩盖了第三个仓。

2. **`hybrid_execute` 是单边死路**，不是双侧未实现：Android 完整实现、V2 从未接线。

3. **第一版我下错的 4 条已更正**：B19 实为已修复（有回归门，8/8 通过）；
   B21 的端口/Provider 零漂移、真正漂移的是快捷键；B7 范围比我说的窄；
   P6/P7 不是"模型不存在"而是"模型存在但启动器不用"。

4. **真正的系统性问题不在协议层，在两处**：
   - **展示层**：32 个 operator 端点，面板消费 0 个（P13）
   - **权威层**：16 个权威模块，8 个不在活路径、3 个只告警（新-1）

   两者同构 —— **建好了，但没接上**。

最该立刻处理的仍是 **B17**：唯一一个"用户以为已关闭、实际仍在采集"的问题。
其次是 **新-2 的三处 `compat` fail-open** ——「闸门坏了等于闸门打开」是
安全设计上的方向性错误，改一个默认值即可。
