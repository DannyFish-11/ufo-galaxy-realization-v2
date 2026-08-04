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
| `launcher/` 包 | 3,032 | bootstrap / config_manager(已退役删除) / core_services / dependency_resolver / health_checks / launcher_adapter / node_startup(1,003) / service_manager / shutdown |
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

~~同名同职责，一个是另一个的子集。~~ **✅ 已结（结法与原判断相反）**：方法多的
那个是 HARD_DEPRECATED、零生产 importer、且自认端口数据陈旧；端口走对了路的是
`system_manager` 那份（`_get_canonical_port` → `core.port_config`）。两个
`NodeConfig` 字段互有出入（`group: str` vs `NodeGroup` 枚举、`health_check_path`
vs `health_check_url`、`critical` 只有 `system_manager` 有），**不是**子集/超集。
`launcher/config_manager.py` 已按其登记的退役条件删除，详见 §"步骤 1 的前提是错的"。

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
   ├─ env_check.py            ← ✅ 已建：main.py Phase 0 + launch_desktop phase0 合成一份判据
   ├─ deps.py                 ← ✅ 已建：镜像轮换/重试/单一依赖清单（两层时序留在各调用方）
   ├─ shell.py（新）           ← start_tauri / start_electron / npm 自愈 / launch_desktop
   ├─ services.py             ← core_services + NATS / Tailscale / 大脑 / 语音
   ├─ nodes.py                ← node_startup + system_manager 的节点生命周期
   ├─ health.py               ← health_checks + health_monitor + 与 scripts/*.sh 的分工
   ├─ tray.py（新）            ← 托盘与 windows_service/daemon 的自启统一
   │                          （config_manager.py 已退役删除：配置走
   │                           core.unified.config_manager，端口走 core.port_config）
   ├─ record.py               ← 现有：启动事实（StartupRecord / StepResult），零表现层
   ├─ ui.py                   ← 现有：三个渲染器（TUI / JSON / log）+ 唯一打印咽喉
   ├─ service_manager.py      ← 现有
   ├─ dependency_resolver.py  ← 现有（已解耦：按 NodeSpec 结构协议收节点表）
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
| 1 | ~~`system_manager.ConfigManager` → 删，改用 `launcher/config_manager.py`~~ → **反过来：`launcher/config_manager.py` 退役删除** | ✅ 已完成。见下方"步骤 1 的前提是错的" |
| 2 | 环境检查合并 → `launcher/env_check.py` | ✅ 已完成。见下方"步骤 2：两份判据实测差在哪" |
| 3 | 依赖引导合并 → `launcher/deps.py` | ✅ 共享层已建。见下方"步骤 3：四份引导，四种抗弱网强度" |
| 4 | 桌面壳合并 → `launcher/shell.py` | 含 npm 自愈链，**最需要小心**，但收益最大 |
| 5 | 节点生命周期 → `launcher/nodes.py`（吸收 `system_manager`） | 要同时改 `docs/CONFIGURATION_AUTHORITY.md` 的用户指引 |
| 6 | 健康检查分工 → `launcher/health.py` | 五处合并，并明确 `scripts/*.sh` 是运维面、不是启动面 |
| 7 | 服务编排 → `launcher/services.py` | 最大一块，放最后 |
| 8 | 删 `unified_launcher.py` / `launch_desktop.py` / `system_manager.py` / `install.py` | 前面全绿之后 |
| 9 | `node_startup.py` 改自动发现（借鉴 ②） | 独立优化，可与统一并行 |

### 步骤 1 的前提是错的（订正记录）

上表原来写的是"`system_manager.ConfigManager` 是子集，并进 `launcher/config_manager.py`
这个超集"。**这个前提不成立**，动手前核过一遍才发现：

- `launcher/config_manager.py` 是 **HARD_DEPRECATED (D2)**，import 时就发
  `DeprecationWarning`，且**零生产 importer**；
- 它的模块头自己写着"下面的硬编码端口默认值是 **STALE** 的，与
  `config/unified_ports.yaml` 冲突"；
- 真正做对了事的是 `system_manager.ConfigManager`：它的 `_get_canonical_port`
  委派 `core.port_config`（权威源就是那份 YAML）；
- 两个 `NodeConfig` 也不是子集/超集关系，而是字段互有出入：
  `group: str` vs `NodeGroup` 枚举、`health_check_path` vs `health_check_url`、
  `critical` 只有 `system_manager` 有。

所以方向是反的：**删的是 `launcher/config_manager.py`**，而不是把权威并进它。
它在 `core/compat_surface_retirement.py` 里登记的退役条件恰好已经满足，于是按
那条条件退役。

**退役时暴露的真 bug**：`launcher/dependency_resolver.py` 用的是**相对** import
`from .config_manager import NodeConfig`。第一版核验用子串搜 `launcher.config_manager`，
永远匹配不到它 —— 删完之后整个模块 `ModuleNotFoundError`，而核验是"绿"的。
改成按 AST 判定（`ImportFrom.level` 还原绝对模块名）后暴露并修复。

**顺带的结构改善**：拓扑排序真正需要的只有 `name` / `priority` / `dependencies`
三个属性，它却被钉死在某个启动器的配置类上。现在改为模块自带 `NodeSpec`
结构协议（`typing.Protocol`，运行时零 import），步骤 5 的 `nodes.py` 把节点表
递给它时不必先适配某个历史 dataclass。

**`dependency_resolver` 本身保留**：它不发 `DeprecationWarning`，也没有退役登记
（`launcher/__init__.py` 此前声称它和 `config_manager` 一样是 HARD_DEPRECATED，
两条都不属实，已订正）。它此前唯一的 importer 就是 `config_manager`，所以看着
像"没人用" —— 那是引用计数，不是能力判断。

**新增的门**（防同类问题复发）：

- `RETIRED` 记录的 `module_path` 必须在磁盘上确实不存在（否则登记表会替一个
  复活的模块背书）；
- `launcher/` 下每个模块都必须真能 `import` —— 这是本轮漏检的根因：
  `dependency_resolver` 断了整整一次提交，因为所有测试都只静态断言、
  没有一条**执行**过它。

### 步骤 2：两份判据实测差在哪

`launch_desktop.phase0_environment_check` 的 docstring 自称"精简版环境检查"。
**这个说法不准确** —— 它不是 `main.py` Phase 0 的子集，两份各有对方没有的判据，
而且同一个问题会给出**不同答案**：

| 检查项 | `main.py` Phase 0 | `launch_desktop` phase0 | 合并取谁 |
|---|---|---|---|
| Python 版本 | 只报版本，**无下限门** | 要求 `>= 3.10`，不满足直接 return | **launch_desktop** |
| pip | `which("pip") or which("pip3")` | `sys.executable -m pip --version` | **launch_desktop** |
| .env | 存在 + 文件大小 | 只看存在 | **main.py** |
| API Key | `.env` **+ runtime/secrets.env**，按 `PLACEHOLDER_PREFIXES` 过滤 | 只读 `os.environ`，子串过滤 | **main.py** |
| npm | `which` 出**绝对路径**再取版本 | 只 `which("npm")` | **main.py** |
| Node.js | 查 | **不查** | **main.py** |
| Electron | `electron_package_intact()`（识别残缺安装） | 只看 `node_modules/electron` 目录在不在 | **main.py** |
| Ollama | 只查装没装 | 装没装 + **在不在跑** + **有哪些模型** | **launch_desktop** |
| 就绪判据 | pip / .env / npm 任一缺失即 not ready | python && pip && npm（**.env 不算**） | **launch_desktop** |

有几处不是"详略"之别，是**对错**之别：

- **pip**：`which("pip")` 找到的可能是**另一个解释器**的 pip（venv 没激活、
  或系统 pip 排在前面）。它在不在，都不代表当前解释器装得上包。
- **API Key**：密钥经面板保存后收敛进 `runtime/secrets.env`，**不再明文留在
  .env**。只读 `os.environ` 的那份在密钥已正确保存时会一直报"未配置"。
  **本机实测**：旧 `launch_desktop` 判据报 `0 个`，合并后判据报 `5 个` ——
  同一台机器、同一时刻，两份判断相反。
- **Electron**：只看目录存在，会漏掉 `npm install` 中途断掉的**残缺安装**
  （`electron.cmd` 存根在、`electron/cli.js` 没了），于是跳过安装直接拉起，然后崩。

**合并原则是逐行取更强的那个判据**，不是取并集、也不是取交集。取谁不取谁是
行为决定，所以每一条都有测试钉住（`tests/test_launcher_env_check.py`，25 条）。

**唯一一处行为变化**：`main.py` 原本没有 Python 版本下限门，合并后有了。这是
刻意的 —— 没有它，3.9 上的失败会推迟到某个 import 处才炸，报错完全指不到真正
的原因。

**两个老调用方都没改坏**：`to_status_dict()` 返回的键取两侧**并集**且仍可变
（自愈成功后要回写）。少给任何一个键，对应调用点会静默走进 `.get()` 的 `None`
分支 —— 那比报错更难查。

**`launch_desktop` 也当场改成调用合并后的那份**，而不是等到步骤 8 删除它时才
顺带消失：漂移在它还活着的时候就已经不存在了。

顺带修好的一处测试隔离：`tests/test_phase0_env_check_secrets_banner.py` 通过
`monkeypatch.setattr(main_mod, "ENV_FILE", ...)` 注入临时 `.env`。若检查器自持
一份模块级 `ENV_FILE`，这个注入会**静默失效**、测试转而读开发者的真 `.env`。
所以路径改为**由调用方传入**（`check_environment(env_file=..., electron_dir=...)`），
所有权留在入口 —— 同一个文件不该在三个模块里各有一份常量。

### 步骤 3：四份引导，四种抗弱网强度

|  | 装什么 | 怎么抗弱网 |
|---|---|---|
| `main.py` Phase 2 | **探测**精选模块清单，只装缺的 | pip **三候选**轮换（默认→清华→阿里云）+ electron 镜像三候选 |
| `install.py` | `requirements-core/-enhance/-windows.txt` 三档 | **零镜像** |
| `install.sh` | `requirements.txt` 一把梭 | **一个**镜像（清华，`GALAXY_PIP_INDEX` 可覆盖）+ `--trusted-host` |
| `install_windows.ps1` | 同 `install.py` 三档 | **零镜像** |
| `launch_desktop` Phase 1 | `requirements.txt` 一把梭 | **零镜像、零重试** |

`install.py` / `install.sh` / `install_windows.ps1` **全都没有调用方** ——
README 与 INSTALL.md 直接教用户 `pip install -r requirements.txt`。按"零引用 ≠
死重"的判据，它们是没接线的**能力**，不因此删除；但零镜像是**真缺陷**：一旦有人
真去跑，国内网络下基本必失败，而且它不会提示"换个源试试"。

#### 为什么不合成一个函数

表面是"四份重复"，实际是**两类不同的工作**，合成一个会两头做坏：

- **启动期自愈**（`main.py` Phase 2 / `launch_desktop` Phase 1）：每次开机都跑，
  必须快，且位于网关 bind **之前**。在这里做全量 `pip install -r requirements.txt`
  会让首启多等几分钟、网关一直不监听。所以它**探测**：import 得动就跳过。
- **安装期引导**（`install*`）：从 clone 起跑一次，可以慢、可以阻塞、该装全就装全，
  还要建 venv、预下载模型、建桌面快捷方式。

`main.py` Phase 2 的注释明确写着**不在启动期现装语音依赖**（pip 慢、
faster-whisper 几百 MB、卡住就把首启拖死），而 `install.sh` 恰恰阻塞式装它们。
这**不是**矛盾，正是两层该分开的证据：安装期阻塞没问题，启动期不行。

所以 `launcher/deps.py` 合并的是两层**真正共用**的部分，两层各自的时序策略留在
各自调用方：

- `pip_index_candidates()` — 候选表只有一份，认 `GALAXY_PIP_INDEX`（沿用
  `install.sh` 已有的约定，不另发明开关）；
- `pip_install()` / `npm_install()` — 镜像轮换 + 重试 + 流式输出，返回
  `InstallResult` 而非裸 bool；
- `CORE_MODULES` / `VOICE_MODULES` — "启动需要什么"此前只存在于 `main.py` 函数体
  里，三个 installer 谁也不知道它；
- `REQUIREMENT_TIERS` — 三档分层取自 `install.py`（唯一做了分层的那份）。

#### 顺带修掉的两个真问题

1. **`--trusted-host` 补上**：`install.sh` 有，`main.py` 没有。某些企业网下镜像
   证书链不受信任时会卡死在这一步。合并取更强的那个。
2. **"跳过"不再冒充"成功"**：原 `install.py` 在 requirements 文件不存在时直接
   `return True`，于是一个打错名字的档位会被报成安装成功。现在 `InstallResult`
   把 `skipped_reason` 单独拿出来。

#### 一处**看着该改、其实不能改**的地方（记录下来免得下次又想优化）

`probe_missing` 用的是真 `__import__`，不是 `importlib.util.find_spec`。
后者更轻（不执行模块顶层代码），但**不能用**：`sounddevice` 的顶层 import 会
一并加载 PortAudio 原生库，import 失败才能兜住"PortAudio 缺失"。换成 `find_spec`，
一台"装了 sounddevice 但系统没 PortAudio"的机器会被判成语音依赖齐全、横幅打 ✓，
而麦克风根本打不开 —— 那正是 `main.py` 注释里记录过、已经修过一次的误导。
`tests/test_launcher_deps.py` 有一条 AST 测试钉住它。

#### `main.py install` 子命令（已做）

命令面替换 `python install.py --all` → `python main.py install --all`。

子命令走**可选位置参数**而不是 argparse 的 subparsers。理由是兼容性：现有的全部
调用形态都是纯 flag（`python main.py --host ... --port ...`，start.bat / start.sh /
文档 / 三端说明全是这么写的）。改成 subparsers 会让"不带子命令"变成一种需要显式
处理的特例，稍不留神就把最常用的那条路径打断。可选位置参数则是纯增量：不给就是
原来的"启动整套系统"。实测四种既有形态（裸启动 / `--host --port` / `-v` /
`--setup`）全部原样可解析，未知子命令按用法错误退出 2。

`install.py` 本体的删除留到步骤 8（连同其余启动器一起），现在两条路通向同一份
实现，先把漂移消掉。

#### 还没做的（下一步）

- `install.sh` / `install_windows.ps1` 瘦成纯引导（venv + 调 `python main.py install`），
  它们现在仍各自实现一份；
- `install.sh` 的 venv 创建与 `predownload_models.py` 预下载尚未搬进 `deps.py`。

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
