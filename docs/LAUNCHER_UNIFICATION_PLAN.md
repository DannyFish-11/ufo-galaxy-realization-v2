# 启动器统一方案

> **状态**：方案，尚未执行。目标是把所有启动器**收敛到 `main.py` 一个入口**，
> 各启动器**真实有效的要素全部保留**（搬进 `launcher/` 包），**启动器本体删掉**。
>
> 本文所有数字都是实测的，不是估计。

---

## 1. 现状全景

### 1.1 启动面清单

| 文件 / 包 | 行数 | 它是什么 |
|---|---:|---|
| `main.py` | 1,149 | **唯一权威入口**（`entrypoint_role_contract` 里的 `UNIQUE_MAIN`）。参数解析、Phase 0 环境检查、Phase 2 依赖确保、setup wizard 分流、开机自启注册 |
| `unified_launcher.py` | 2,496 | 从属启动器（`SUB_ENTRY`）。服务编排、NATS / Tailscale / 本地大脑 / 语音、**双壳选择 + Electron npm 自愈**、托盘、进程看守、entrypoint.json 写出 |
| `launch_desktop.py` | 784 | **与 main.py 并行的第二条桌面启动路径**（见 §1.3） |
| `launcher/` 包 | 3,032 | bootstrap / config_manager / core_services / dependency_resolver / health_checks / launcher_adapter / node_startup(1,003) / service_manager / shutdown |
| `system_manager.py` | 676 | 节点生命周期管理（文档明确让用户 `python system_manager.py`） |
| `daemon/` | 917 | `galaxy_daemon.py`(656) 常驻守护 + `autostart.py`(232) 三平台开机自启 |
| `windows_service/` | 1,834 | Windows 服务 / 托盘 / watchdog / autostart |
| `install.py` | 121 | 一键装依赖（Python 版） |
| `install.sh` | 286 | 一键装依赖（Unix 版） |
| `install_windows.ps1` | 105 | Windows 安装 + 桌面快捷方式 + 开机自启 |
| `install_taskscheduler.ps1` | 89 | Windows 计划任务注册 |
| `start.bat` / `start.sh` | 28 / 45 | venv 引导 → `python main.py` |

**合计约 11,600 行**，其中"启动"这件事本身约 7,500 行。

### 1.2 正常启动链（当前）

```
start.bat / start.sh          venv 引导
  └─ main.py                  参数解析 → 契约校验 → Phase 0 环境检查 → Phase 2 依赖
       ├─ SystemOrchestrator  Phase 1..7（LOAD_CONFIG / RESOLVE_MODE / ENV_CHECKS /
       │                      BACKGROUND_SUBSYSTEMS / RUNTIME_SUBJECT / DESKTOP_SURFACE /
       │                      READINESS_SUMMARY）
       └─ unified_launcher.GalaxyUnified
            ├─ ensure_docker_infra / start_nats / start_tailscale
            ├─ start_local_brain / select_and_start_brain / start_voice_interaction
            ├─ start_desktop_shell → start_tauri() 优先，失败回退 start_electron()
            ├─ start_system_tray
            ├─ watch_processes（保活）
            └─ _write_entrypoint_json（写出 LAN / Tailscale 地址供三端发现）
```

### 1.3 实证的重复（这些是统一要解决的东西）

**① 桌面启动有两条并行实现**

`launch_desktop.py` 不是 `unified_launcher` 的子步骤，它自带：

```
phase0_environment_check()       ← 与 main.py:453 "Phase 0: Environment check" 同名同事
phase1_ensure_dependencies()     ← 与 main.py:590 "Phase 2: Ensure dependencies" 同事
select_model_interactive/auto()  ← 与 unified_launcher.select_and_start_brain 同事
start_tauri_frontend() or start_electron_frontend()   ← 与 start_desktop_shell 同事
wait_for_gateway() / gateway_is_ready()
```

它的 docstring 自称"精简版环境检查"。**两份判据会漂**，而且漂了没人发现——
它们没有任何交叉校验。

**② `ConfigManager` / `NodeConfig` 是两份**

| | 类 | 方法数 |
|---|---|---:|
| `system_manager.py` | `ConfigManager` | 3（`_get_canonical_port` / `load_nodes` / `_get_default_nodes`） |
| `launcher/config_manager.py` | `ConfigManager` | 11（`load_from_json` / `load_from_env` / `load_all` / `get_nodes_by_group` …） |

同名同职责，一个是另一个的子集。`NodeConfig` 也是两份。

**③ 依赖引导有四份**

`install.py`（Python）、`install.sh`（Unix）、`install_windows.ps1`（PowerShell）、
`main.py` 的 Phase 2、`launcher/dependency_resolver.py`（依赖图解析）。
其中 `install.py` 目前**零引用**——没有任何脚本或文档执行它。

**④ 健康检查有五处**

`launcher/health_checks.py`（启动后校验）、`health_monitor.py`（常驻循环，有
`__main__`）、`core/health_check.py`（**路由工厂**，不是 CLI）、
`scripts/health_check.sh` / `.ps1`（各 188 行，运维用）。

**⑤ 开机自启有两套**

`daemon/autostart.py`（三平台）与 `windows_service/autostart.py`（Windows 专用），
`main.py --autostart` 走的是后者。

---

## 2. 各启动器"真实有效的要素"逐条

统一的前提是**一样都不能丢**。这是清单：

### `main.py`（保留为唯一入口，本体不删）

- CLI 契约：`--setup` / `--host` / `--port` / `--model` / `--select-model` / `-v` /
  `--autostart` / `--autostart-remove`
- `assert_single_unique_main_entrypoint()` 入口角色契约校验
- `-v` 落到 `GALAXY_VERBOSE` 环境变量（子模块无需逐层透传）
- Phase 0 环境检查的**具体判据**：Python 版本 / `.env` / API Key / pip / npm
- Phase 2 依赖确保：pip 三镜像重试、npm 三镜像重试、Electron、Ollama、语音栈
- 「不在这里拉模型」那条刻意的时序决定（注释里写明了五条理由，交给 Phase 5）

### `unified_launcher.py`（要素搬走，本体删）

- **Electron npm 自愈链**（约 100 行，全是真机故障攒出来的）：
  `node_modules` 缺失检测 → `npm install` → `electron_package_intact()` 校验 →
  purge staging 重装 → `repair_electron_binary()` 补下运行时二进制 → GPU 崩溃后
  注入 `GALAXY_ELECTRON_GPU=0` 走软件渲染
- **双壳选择**：`start_tauri()` 优先（只查一个二进制在不在）→ 回退 `start_electron()`；
  `GALAXY_DESKTOP_SHELL=electron` 强制回退
- `.electron.pid` 锁与 `already_running()` 早退（防重复拉起 / 陈旧锁清理）
- `ensure_docker_infra` / `start_nats`（含 embedded/external/no-op 三态）/ `start_tailscale`
- `start_local_brain` / `select_and_start_brain`（主脑选择与后台拉取）
- `start_voice_interaction` + `_VoiceGalaxyAdapter`
- `start_system_tray`、`watch_processes`（保活）、`stop`、`show_status`
- `_write_entrypoint_json`：写出 LAN / Tailscale 地址，**三端靠它免手填 IP 发现网关**
- `_observe_node_resolutions`（`LauncherAdapter` 的观察模式接线）

### `launch_desktop.py`（要素合并后，本体删）

- **Windows 控制台编码修正** `_configure_windows_console()`（`main.py` 也有一份，
  合并时取二者中更完备的）
- `wait_for_gateway()` / `gateway_is_ready()` 的就绪等待语义
- `download_model_background()` 的后台拉取
- `kill_proc()` 与 `_signal_handler()` 的信号处理

### `system_manager.py`（要素搬走，本体删）

- 节点生命周期：启停单个节点、按组启停、状态查询
- `_get_canonical_port()` 的端口权威解析
- 文档 `docs/CONFIGURATION_AUTHORITY.md:275` 明确的用户指引
  `python system_manager.py` —— **删本体前必须给出等价的新命令并改文档**

### `install.py` / `install.sh` / `install_windows.ps1`（要素合并，本体删或降级）

- `--core` / `--enhance` / `--all` 三档依赖分层
- Windows 侧：桌面快捷方式、开机自启、`GALAXY_HOME` 约定
- `install.sh` 的 `predownload_models.py` 预下载

### `flags.py`（保留）

5 个 flag 里 **4 个对应真实在读的环境变量**（`LAUNCHER_ADAPTER_MODE` /
`LAUNCHER_ADAPTER_ALLOWLIST` / `GALAXY_SKIP_ELECTRON` / `WEBRTC_TASK_LIFECYCLE`），
带 owner / rollout / cleanup 记录。只有 `NATS_MODE` 已漂（全仓零引用）。

### `build_exe.py`（保留）

444 行 PyInstaller 打包链，`--onefile` / `--installer` 两档。它是**能力**，
只是没接线。

---

## 3. 目标形态

```
main.py                       ← 唯一入口。只做：参数解析 → 契约校验 → 分流。目标 < 250 行
└─ launcher/                  ← 所有实现收敛在这里
   ├─ bootstrap.py            ← 现有 + 吸收 install.py / install.sh / ps1 的依赖引导
   ├─ env_check.py（新）       ← main.py Phase 0 + launch_desktop phase0 合并成一份判据
   ├─ deps.py（新）            ← main.py Phase 2 + 四份依赖引导合并；三镜像重试只写一次
   ├─ shell.py（新）           ← start_tauri / start_electron / npm 自愈 / launch_desktop
   ├─ services.py             ← core_services + NATS / Tailscale / 大脑 / 语音
   ├─ nodes.py                ← node_startup + system_manager 的节点生命周期
   ├─ health.py               ← health_checks + health_monitor + 与 scripts/*.sh 的分工
   ├─ tray.py（新）            ← 托盘与 windows_service/daemon 的自启统一
   ├─ config_manager.py       ← 唯一的 ConfigManager（删掉 system_manager 里那份）
   ├─ service_manager.py      ← 现有
   ├─ dependency_resolver.py  ← 现有
   ├─ launcher_adapter.py     ← 现有
   └─ shutdown.py             ← 现有
```

`unified_launcher.py` / `launch_desktop.py` / `system_manager.py` / `install.py`
在迁移完成后**删除**；`start.bat` / `start.sh` / `install*.ps1` / `install.sh`
保留但只做**引导**（venv、调 `python main.py <子命令>`），不再各自实现逻辑。

### 命令面（替代被删的入口）

| 原来 | 之后 |
|---|---|
| `python main.py` | 不变 |
| `python unified_launcher.py` | `python main.py`（它本来就是从属） |
| `python launch_desktop.py` | `python main.py --desktop-only` |
| `python system_manager.py` | `python main.py nodes <start\|stop\|status> [name]` |
| `python install.py --all` | `python main.py install --all` |
| `python build_exe.py --onefile` | 保留原样（打包不属于运行期启动） |

---

## 4. 可以从 Hermes Agent 借鉴什么

[Hermes Agent](https://github.com/NousResearch/hermes-agent)（Nous Research）与本项目
形态接近：一个常驻的个人 AI，多端接入，插件化，需要长期在线。它有四点**直接对得上
本项目当前痛点**的做法。

### ① 入口极薄，且在 import 之前就把 profile 定死

Hermes 的 `hermes_cli/main.py` 只做一件事：`_apply_profile_override()` ——
**在任何模块 import 之前**应用 profile，从而支持多实例互不干扰。

对本项目：`main.py` 现在 1,149 行里混着环境检查与依赖安装，而这些都是"要在
import 重模块之前做的事"。把入口收薄到"解析 → 定 profile/模式 → 分流"，
其余全部下沉，正好也解决了 `main.py` 顶部那一堆 `sys.path` / 编码 / 警告
屏蔽的先后顺序问题。

### ② 注册表自动发现，不维护 import 清单

Hermes 的 `tools/registry.py` 做工具自动发现，AGENTS.md 里明写
*"no import list maintained"*。

对本项目：`launcher/node_startup.py` **1,003 行**，是整个包里最大的一个文件。
节点是数据（`nodes/Node_XX_*/`），不该靠一份手写清单驱动。改成扫描 + 注册表
可以把它砍掉大半，且新增节点不用改启动器。

### ③ 配置：`DEFAULT_CONFIG + 用户 YAML` 合并，旧键**自动桥接并打弃用警告**

Hermes 的 `load_config()` 合并默认与用户配置，遇到旧位置的设置会
*"print a deprecation warning"* 并**自动桥到新位置**。

对本项目：这正是"两条配置写入链"（`ConfigService`→`config.json` 与
`CONFIG_SCHEMA`→`.env`）该有的收敛方式——不是二选一强切，而是合并成一套读取、
旧键继续认但明确告知。这也顺带解决 `ConfigService` 那 5 个写方法没有运行期
入口的问题。

### ④ 三层可分离：gateway / core / execution backend

Hermes 把执行后端与 agent 逻辑分开，**智能跑在一台机器、代码执行在另一台的
隔离容器里**。

对本项目：这个形态**已经有了**（`galaxy_gateway` / `core` / `nodes` + mesh），
但启动器把它们绑成了一个进程树。借鉴点不是重构，而是让 `main.py` 的分流支持
"只起某一层"，为将来分机部署留门：

```
python main.py --only gateway
python main.py --only core
python main.py --only nodes
```

### 不借鉴的

- **Hermes 的插件三源发现**（`~/.hermes/plugins/` / `./.hermes/plugins/` / pip entry
  points）：本项目的节点是仓内的一等公民，不是第三方插件，引入 entry-point
  发现只会多一层间接。
- **它的 25+ 平台适配器**：本项目的多端是 Android / WearOS / 桌面三端加 mesh，
  形态完全不同。

---

## 5. 迁移方案：先搬不改，一次一块

**原则**：每一步都能单独回退，任何一步出问题不影响前一步。

### 每一块的固定动作

1. 把实现整块搬到 `launcher/<新模块>.py`，**一行不改**；
2. 原文件留 `from launcher.<新模块> import *` 的 shim，**对外行为不变**；
3. 加一条测试钉"新旧行为一致"（对纯函数比返回值，对有副作用的比调用序列）；
4. 全量跑一遍；
5. 下一块。

全部搬完之后，才统一删 shim 与原文件。

### 建议顺序（按风险从低到高）

| # | 内容 | 为什么排这里 |
|---|---|---|
| 1 | `system_manager.ConfigManager` → 删，改用 `launcher/config_manager.py` | 纯重复，子集并入超集，风险最低 |
| 2 | 环境检查合并 → `launcher/env_check.py` | 两份判据合一，先做能立刻消除漂移 |
| 3 | 依赖引导合并 → `launcher/deps.py` | 四份合一；三镜像重试逻辑只写一次 |
| 4 | 桌面壳合并 → `launcher/shell.py` | 含 npm 自愈链，**最需要小心**，但收益最大 |
| 5 | 节点生命周期 → `launcher/nodes.py`（吸收 `system_manager`） | 要同时改 `docs/CONFIGURATION_AUTHORITY.md` 的用户指引 |
| 6 | 健康检查分工 → `launcher/health.py` | 五处合并，并明确 `scripts/*.sh` 是运维面、不是启动面 |
| 7 | 服务编排 → `launcher/services.py` | 最大一块，放最后 |
| 8 | 删 `unified_launcher.py` / `launch_desktop.py` / `system_manager.py` / `install.py` | 前面全绿之后 |
| 9 | `node_startup.py` 改自动发现（借鉴 ②） | 独立优化，可与统一并行 |

### 每一步都要有的门

- **入口脚本目标存在**：已建（`tests/test_entry_script_targets_exist.py`）
- **单一主入口契约**：已有（`assert_single_unique_main_entrypoint`）
- **新增**：`launcher/` 之外不得再出现第二个"环境检查 / 依赖安装 / 桌面壳拉起"的实现
  —— 按函数名与关键字符串扫，命中即红。这道门是防"统一完又长回来"的关键。

---

## 6. 顺带该由启动器完善的事

这些是核查中浮出来、且**只能在启动器这一层解决**的：

1. **`NATS_MODE` 已漂**：`flags.py` 注册了它，但全仓零引用。要么接上（`start_nats`
   已经有 embedded/external 两态，缺 no-op），要么从注册表里摘掉并记录。
2. **`install.py` 零引用**：它的三档依赖分层是有用的，但没人调。合并进
   `launcher/deps.py` 后由 `main.py install` 暴露。
3. **`core/health_check.py` 没有 `__main__`**：它是路由工厂却叫 `health_check`，
   已经骗过一次（差点把 `npm run health` 指向它，那会变成静默 no-op）。
   统一时应改名或补一个明确的 CLI 入口。
4. **两套开机自启**（`daemon/autostart.py` 三平台 vs `windows_service/autostart.py`）
   要定一个权威，另一个转成 shim。
5. **`_write_entrypoint_json` 是三端发现的关键**，但它埋在 `unified_launcher` 里、
   没有独立测试。搬家时补一条：地址写出后三端能读到。
6. **Electron 兜底的去留**：`start_tauri()` 只查一个二进制在不在，而
   `start_electron()` 背着约 100 行 npm 自愈。**Tauri 在真机验证通过后**，
   删 Electron 分支能一次性消掉一整类失败模式——这是启动器统一最大的一笔化简，
   但前置条件是真机验证（见 `desktop-tauri/README.md` 的三条已知风险）。

---

## 7. 明确不做的事

- **不新建启动框架**。`entrypoint_role_contract.py` 已经定义了唯一主入口的契约，
  统一是往这个契约收敛，不是另起一套。
- **不动 `daemon/` 与 `windows_service/` 的进程模型**。它们是"常驻/服务"面，
  与"启动"面职责不同，只统一二者重复的 autostart。
- **不在统一的同时改行为**。搬家就是搬家；要改的行为单独一个 PR，否则出了问题
  分不清是搬坏的还是改坏的。

---

## 附：数据来源

本文所有数字来自 2026-08-04 对 `ufo-galaxy-realization-v2` 的实测：
`wc -l` 行数、`ast` 解析类与方法、`grep` 引用计数、`importlib.util.find_spec`
模块存在性核对。重复关系（§1.3）逐条用 AST 比对过类名与方法集合，不是靠读代码
的印象。

**Sources**：
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- [hermes-agent/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/main/AGENTS.md)
- [Hermes Agent — Architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
