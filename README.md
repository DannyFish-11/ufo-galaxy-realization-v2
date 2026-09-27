# Galaxy — 桌面原生 AI 助手系统

> **版本**：v2.3.23（唯一来源 `core/version.py`；`python main.py --version`）· **Python**：3.11 · **许可证**：MIT
>
> **当前做到了哪儿、哪里还是断的**：见 [`docs/SYSTEM_STATUS.md`](docs/SYSTEM_STATUS.md)（逐项复测，每条附复测命令）。
> 本 README 只写代码里真实存在、可以复核的东西。

---

## 一句话介绍

**Galaxy** 是一个以电脑为主体的 AI 助手。它常驻在桌面上，边看边听，用三态覆盖层（SILENT / LIMINAL / MANIFEST）
表达自己；能调本地模型（Ollama，按显卡分档）或云端模型，能操作本机、远程 Linux 服务器和接入的其它设备，
有持久记忆、MCP / Skill 扩展，以及一个默认关闭、由验证器而不是由自己裁决的自我改进层。

---

## 整体架构（按代码实际分层）

```
                    ┌──────────── 用户交互 ─────────────┐
   桌面三态覆盖层  electron/（或 desktop-tauri/）   面板 electron/renderer/panel/（纯 TS）
                    │   WS  /ws/desktop-presence（只认 payload.render）
                    ▼
┌──────────────────────────── Galaxy 后端 · python main.py · 端口 9000 ─────────────────────────────┐
│ 入口与编排   main.py → launcher/（环境检查 · 依赖 · 桌面壳 · 服务编排 · 节点生命周期）               │
│ HTTP / WS   core/api_routes.py 挂 core/routes/*，并合并网关表层 → 约 420 个 HTTP 端点、7 个 WS 端点 │
│                                                                                                   │
│ 主体        core/desktop_presence_runtime.py  桌面三态运行时（唯一主体核心）                        │
│ 入口分流    core/presence_line.py  只有电脑发起的请求进三态；别的设备、智能体自主工作直接交给智能体  │
│ 智能体      core/openclawd.py（执行）· core/agent/execution_planner.py（策略选择唯一决策点）        │
│ 模型路由    core/multi_llm_router.py  本地优先 → 按任务类型的云端候选 → 都不可用时明确告知          │
│ 对象层      core/canonical_task.py · canonical_task_store.py · ontology/links.py（决策走确定性查询）│
│ 设备        galaxy_gateway/（安卓规范入口 /ws/device/{id}）· participant_admission.py（非安卓通用接入）│
│             device_onboarding/（设备接入平面：候选 → 成员）                                        │
│ 语音        speech_output.py（说）· modality_bridge.py（听）· tts/ · routes/openai_audio.py         │
│ 记忆        core/memory/ · conversation_mainline.py（声字同文：所有说过的话进同一条主线）           │
│ 元层 (RSI)  core/meta/  采集 → 提案 → 验证 → 裁决 → 生效/回滚；GALAXY_META_RSI 默认 off             │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
        │                              │                                 │
   节点 nodes/（125 个，按需启动）   本地模型 Ollama（A/B/C/D 档）      云端模型（DeepSeek / OpenAI / Anthropic / … 按 Key 启用）
```

统一主体：桌面在场运行时（DesktopPresenceRuntime）是唯一主体核心，Electron / Tauri 覆盖层和面板只是它的
运行时外壳；OpenClawd 作为执行策略层（PolicyGate 白名单 + 沙箱）挂在主体之下。

- 代码地图与约定（每轮给 AI 助手加载的那份）：[`AGENTS.md`](AGENTS.md)
- 统一主体架构：[`docs/UNIFIED_SUBJECT_ARCHITECTURE.md`](docs/UNIFIED_SUBJECT_ARCHITECTURE.md)
- 元层设计与落地状态：[`docs/META_LAYER_RSI_ARCHITECTURE_CN_2026.md`](docs/META_LAYER_RSI_ARCHITECTURE_CN_2026.md)
- 前端必须遵守的渲染契约：[`docs/RENDER_CONTRACT_DIRECTION.md`](docs/RENDER_CONTRACT_DIRECTION.md)

### 规模（2026-09-27 实测）

| 部分 | Python 文件 | 行数 | 说明 |
|---|---:|---:|---|
| `core/` | 1,008 | ~55 万 | 主体 |
| `nodes/` | 476 | ~9.5 万 | 125 个节点 |
| `galaxy_gateway/` | 107 | ~4.2 万 | 设备网关 |
| `contracts/` · `launcher/` | 48 | ~3.8 万 | 跨运行时契约 · 启动编排 |
| `tests/` | 1,300+ | ~64 万 | 全量约 4.5 万个测试 |
| `external/` | 807 | ~20 万 | 外部代码原样入库，不算本仓自写 |

本仓自写 Python（不含测试与 `external/`）约 79 万行；另有 Electron 外壳与面板约 1.2 万行 TS/JS。

---

## 三态交互

一条编排，不是三个画面。画什么只看后端的渲染契约（`core/phase_contract.py` 的 `RenderPosture`），
覆盖层（`electron/renderer/app.js`）照着画。

| 状态 | 画面 | 什么时候 | 你能做什么 |
|------|------|----------|------------|
| **SILENT** 第一态 | 左、右、上三条边的氛围光，缓慢呼吸。浓度跟感知走：在看/在听 → 亮，闲着 → 淡，被压下 → 细；按了隐私急停 → 只剩顶上一道贴边细线；没有感知通路 → 不亮 | 在场但不表达：它边看边听（全模态输入），多半时候选择不打扰 | 直接说话；鼠标穿透，不挡你 |
| **LIMINAL** 第二态 | 边光收回，四条边一起向后延伸出空间；灵动岛从上边框长出来，写着它在干嘛（正在理解 / 正在规划 / 正在推演） | 在想、在推演（空间就是沙盒） | 等它；打开面板看细节 |
| **MANIFEST** 第三态 | 空间收回，屏幕是干净的 —— 它在出字、出声，或动手。**念出声也算这一态**，不会因为开口把空间重新推开 | 对外表达 | 它动你的鼠标键盘时岛上写「正在操作 · Esc 停止」，按 Esc 就停 |

收场有两种：做完就散，光从顶部中间铺回三条边；做完接着下一轮，直接回到第二态。

**声字同文**：它说出口的每一句话（打字的回答、语音、双工里边说边出的字、它自己开口的那句），
同时进面板那份上下文。面板只是这份上下文的一个视图 —— 面板关着时说过的话照样记在当前对话主线上，
再打开时从后端读回来，一句不少（`core/conversation_mainline.py`）。

快捷键（全局键常被输入法、远程桌面、开发者工具抢走，所以都是**多个候选、谁注册上用谁**）：
- 唤醒覆盖层：`Ctrl+Alt+Space`（候选 `Ctrl+Shift+Space` 等）
- 隐藏覆盖层：`Ctrl+Alt+H`（或 `Ctrl+Shift+H`）
- 打开/收起控制面板：依次尝试 `Ctrl+Shift+P`、`Ctrl+Alt+P`……`F12`，启动时系统通知会告诉你实际生效的是哪个；托盘图标永远能打开
- 叫停：它动你的鼠标键盘时按 `Esc`（只认你亲手按的，它自己按的 Esc 不算，也不吞键；
  Windows / macOS 可用，Linux 分不清人按的和注入的，不占 —— 那时岛上也不写「Esc 停止」，见 `core/stop_key.py`）。
  任何时候面板的发送键在它忙的时候就是停止键

---

---

## 核心能力

### 1. 本地模型（Ollama），按显卡分档

| 档 | 组成 | 说明 |
|---|---|---|
| **A** 轻量本地 | Gemma 4 系（e2b / e4b / 12b）单模型 | 看 + 听（原生），说走 TTS；无独显也能跑 |
| **B** 全模态单模型 | MiniCPM-o 4.5 | 看 / 听 / 说全原生，需要显卡 |
| **C** 双模型 · 35B 推理位 | 推理位 Qwen3.6-35B-A3B 或 Agents-A1（MoE，需专家卸载），感知位四选一 | 推理位常驻独显，感知位走核显 |
| **D** 双模型 · 9B 推理位 | 推理位 Qwythos-9B v2（稠密），感知位同 C | |

启动时按硬件推荐一档（装得下且跑得起来的最高档；无独显 → A）；`python main.py --select-model` 或面板里随时换。
定义在 `core/model_catalog.py`，推荐逻辑在 `core/model_selection.py`。

### 2. 模型路由与降级

`core/multi_llm_router.py`：本地模型可用时优先走本地，同时按任务类型带上云端候选（例如推理类依次
ollama → anthropic → openai → meta → deepseek → …，偏好表 `TASK_ROUTING_PREFERENCES`）；
失败自动切下一个，断路器拦住连续失败的提供商。一个都不可用时**不崩**，明确告诉用户缺什么：
没配 Key、也没本地模型时回「还没有可用的 AI 服务……」，试过但都失败时列出试过哪些（`core/llm_unavailable_reply.py`）。

### 3. 入口分流：谁发起的请求进桌面三态

只有**电脑这边发起**的请求进三态（桌面外壳、本机感官、本机标识、不带设备号且来自本机的连接）；
手机、手表、别的机器、智能体自己的定时心跳都不进 —— 直接交给智能体，不在电脑上朗读。
这是架构，没有开关（`core/presence_line.py`）。`GET /api/v1/agent/activity` 列出智能体手上的全部请求，
包括不进三态的那些。

### 4. 设备接入

- 安卓：规范入口 `galaxy_gateway/routes/websocket.py` 的 `/ws/device/{device_id}`（AIP v3）。
- 非安卓设备：`POST /api/v1/participants/register` → `/tasks` → `/heartbeat` → `/disconnect`，全程不经安卓命名模块。
- 设备接入平面（`core/device_onboarding/`）：发现候选 → 需要人做什么就说清楚 → 成为成员；同型号设备复用驱动。

### 5. 远程 Linux 服务器（`/api/v1/agents/linux/*`）

注册服务器后通过对话远程操作（SSH 密钥/密码、远程文件读写、系统信息、批量操作）：
```bash
curl -X POST http://localhost:9000/api/v1/agents/linux/servers \
  -H "Authorization: Bearer $GALAXY_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"我的服务器","host":"IP","port":22,"user":"root","key_path":"~/.ssh/id_rsa"}'
```

### 6. 沙箱执行（`/api/v1/agents/sandbox/*`）

32 条危险命令模式拦截；默认内存 256 MB、超时 30 秒（`galaxy_gateway/routes/sandbox.py`）。
OpenClawd 的 PolicyGate 另有应用启动白名单与命令注入检测。

### 7. MCP 与技能

- MCP 服务器：`/api/v1/protocols/mcp/*`（加载、列工具、调用、重载），实现在 `core/mcp_loader.py`。
- 技能：`skill.json` 包（`core/skill_loader.py`，按 SkillPackageContract 校验）或 `SKILL.md`（`core/skill_md_loader.py`）；
  以 `skill__<id>` 工具的形式交给智能体。

### 8. 记忆与语音

- 记忆：`core/memory/` 统一记忆层；`Node_80_MemorySystem` 提供短期（Redis）/ 长期（Memos）/ 语义（ChromaDB）/ 画像（SQLite）四层。
- 说：`core/speech_output.py` 选引擎、失败降级；克隆音色默认打 AudioSeal 水印。听：`core/modality_bridge.py`
  （全模态模型在线时让它自己听，否则 Whisper / SenseVoice）。OpenAI 兼容端点 `/v1/audio/*`。

### 9. 自我改进（元层，默认关闭）

`core/meta/`：一次改进 = 采集 → 提案 → 由 harness 跑验证 → 四值证据裁决 → 生效或回滚，每一步留 lineage。
提案者自报的成败只记为 claimed，不算数；算子不得改验证器。总闸 `GALAXY_META_RSI=off|shadow|on`，**默认 off**，
面板「全部设置 → 自我改进」里就这一个开关。CLI：`python scripts/meta_rsi.py`。

### 10. 节点（125 个，按需启动）

节点定义在 `node_dependencies.json`，启动档位由 `core/node_activation_policy.py` 判定：
13 个常开（核心组：StateMachine、OneAPI、Tasker、SecretVault、Router、Auth、Filesystem、Git、Fetch、
Sandbox、SmartOrchestrator、ContextManager、SelfHealing），102 个首次用到时才起（lazy），
2 个设备接入时起（on_demand），2 个共享，6 个不启动。分组：extended 55 · development 31 · academic 23 · core 13 · tools 2 · enhancement 1。
完整清单见 `nodes/`，`python main.py nodes status` 查看运行情况。

---

## 启动方式

### 方式一：一体化启动（推荐）
```bash
python main.py
```
自动完成：环境检查 → 缺的依赖补装 → 本机模型档位 → 后端启动（9000）→ 桌面壳启动。
缺什么就降级什么，并在启动总结里逐项写明原因和装法（没有 Key、没有 Ollama 也能起来）。

```bash
python main.py --version        # 版本号
python main.py --check          # 只检查环境
python main.py --check-only     # 依赖 / 配置 / 核心模块 / 节点导入全查一遍，不启动
python main.py --backend        # 只启动后端，不拉桌面壳
python main.py --desktop-only   # 只把桌面壳挂到已在跑的后端上
python main.py --status         # 查看系统状态
python main.py doctor           # 给启动器自身做一次体检
python main.py nodes start -g core   # 节点生命周期
```

桌面壳默认优先 Tauri（`desktop-tauri/`，轻量），没有 Rust 工具链或构建失败时自动回退 Electron（`electron/`），
两者用同一套前端。`GALAXY_TAURI_AUTOBUILD=0` 关闭自动构建；`GALAXY_DESKTOP_SHELL=electron` 强制 Electron。

#### Tauri 桌面壳构建依赖（想用轻量壳时）
启动器会**自动构建**一次 Tauri 壳，但需要以下系统依赖（缺则自动回退 Electron，并在日志给出安装命令）：

- **通用**：Rust 工具链 — 一行装：`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`（或见 https://rustup.rs ）
- **Linux**（Debian/Ubuntu）额外需 WebView 开发库：
  ```bash
  sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev \
    libsoup-3.0-dev libjavascriptcoregtk-4.1-dev build-essential pkg-config
  ```
- **Windows**：仅需 Rust（WebView2 一般随 Edge 自带；缺则装 Evergreen WebView2 Runtime）
- **macOS**：Rust + Xcode Command Line Tools（`xcode-select --install`）

装好后跑 `python main.py`，首次自动 `cargo build --release`（约数分钟），之后每次秒起并直接优先 Tauri。
不想用 Tauri：`GALAXY_TAURI_AUTOBUILD=0`（关自动构建）或 `GALAXY_DESKTOP_SHELL=electron`（强制 Electron）。

### 方式二：Docker Compose
```bash
cp .env.example .env            # 先填必填项（NEO4J_PASSWORD 等，缺了 compose 会直接报出来）
docker compose up -d
```
默认起：galaxy（后端）、galaxy-gateway、ollama、neo4j、qdrant、redis、mongodb、minio、nats；
`--profile full` 再加 oneapi、memos、temporal、agentcpm 等，`--profile webrtc` 加 coturn。

其它编排在 `deploy/compose/`：`full.yml`（全部节点，`python main.py --docker-full`）、`production.yml`（24/7 + 监控）。
这些文件的相对路径按文件所在目录解析，2026-09-27 前全都指错了地方（构建找不到 Dockerfile、挂载盖成空目录），
现已改为指向仓库根，由 `tests/test_deploy_surfaces_resolve.py` 守着；镜像拷进去的文件够不够自己跑，
由 `tests/test_container_images_ship_what_they_run.py` 守着。

### 方式三：手动分别启动
```bash
python main.py --backend                 # 终端 1：后端
cd electron && npm install && npm start  # 终端 2：Electron 桌面覆盖层
```

---

## 安装步骤

### 前提
- Python 3.11（CI 与镜像唯一验证过的版本）
- Node.js 18+（桌面壳）
- Ollama（可选，本地模型）

### 1. 克隆仓库

```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git ufo-galaxy
cd ufo-galaxy
```

**弱网/克隆卡住？** 按下面顺序处理（逐级降低对网络的要求）：

```bash
# ① 先给 git 配置弱网参数（一次性，全局生效）：
#    低速阈值 1KB/s 持续 60s 才判失败，避免"慢"被当成"死"；缓冲放大避免大包中断
git config --global http.lowSpeedLimit 1000
git config --global http.lowSpeedTime  60
git config --global http.postBuffer    536870912

# ② 浅克隆（只拉最新一版历史，体积显著减小；后续可 git fetch --unshallow 补全）
git clone --depth 1 https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git ufo-galaxy

# ③ 还是卡：部分克隆 + 跳过评测数据（external/agentcpm/eval 约 40MB，仅离线评测用，
#    运行时完全不需要；其余目录全部保留）
git clone --filter=blob:none --sparse https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git ufo-galaxy
cd ufo-galaxy
git sparse-checkout set --no-cone '/*' '!external/agentcpm/eval'
```

> git clone 不支持断点续传——中断后重试是从零开始，所以弱网下**优先用 ②/③ 减小体积**，
> 而不是反复重试完整克隆。

### 2. 安装依赖
```bash
python3 -m venv .venv && source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
cd electron && npm install && cd ..
```
（`python main.py install --core|--enhance|--all` 也能装。）

### 3. 配置
```bash
cp .env.example .env
```
至少配一个 LLM API Key，或者装好 Ollama。所有配置项（约 390 个）都登记在 `CONFIG_SCHEMA`
（`core/routes/config_schema_registry.py`），面板「全部设置」里能看能改，保存即时生效。常用的几个：

```bash
DEEPSEEK_API_KEY=...            # 或 OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY …
OLLAMA_URL=http://localhost:11434
GALAXY_MODEL_TIER=              # 空 = 按硬件推荐；A / B / C / D
GALAXY_API_TOKEN=               # 后端 API 鉴权令牌（GALAXY_AUTH_ENABLED 默认开）
GALAXY_DATA_DIR=                # 运行时数据目录，缺省为仓库的 data/
```

### 4. 启动
```bash
python main.py
```

---

## API

后端在 `http://localhost:9000`，约 420 个 HTTP 端点，完整列表看 `http://localhost:9000/docs`（OpenAPI）。
主要分组（按端点数）：

| 前缀 | 用途 |
|---|---|
| `/api/v1/operator/*` · `/api/v1/projection/*` · `/api/v1/observability/*` | 运行时状态、投影、可观测 |
| `/api/v1/devices/*` · `/api/v1/participants/*` · `/api/v1/pair/*` · `/api/v1/onboarding/*` | 设备与参与方 |
| `/api/v1/mesh/*` · `/api/v1/federation/*` · `/api/v1/relay/*` | 多设备协同（结构在、未经真机验证，见 SYSTEM_STATUS） |
| `/api/v1/agents/linux/*` · `/api/v1/agents/sandbox/*` · `/api/v1/agent/activity` | 智能体能力与活动 |
| `/api/v1/protocols/mcp/*` · `/api/v1/protocols/skills/*` | MCP 与技能 |
| `/api/v1/chat` · `/api/v1/chat/stream` · `/api/v1/sessions/*` · `/api/v1/memory/*` | 对话、会话、记忆 |
| `/api/v1/models/*` · `/api/config*` · `/api/v1/vault/*` | 模型档位、配置、密钥 |
| `/health/live` · `/health` · `/metrics` · `/gateway/metrics` | 健康与 Prometheus 指标 |

WebSocket：`/ws/desktop-presence`（桌面外壳）、`/ws/device/{id}`（安卓规范入口）、`/ws/status`、
`/ws/android*`、`/ws/webrtc/{id}`，以及兼容旧客户端的 `/ws/ufo3/{id}`（待退役）。

---

## 关键文件

| 文件 | 说明 |
|---|---|
| `main.py` · `launcher/` | 唯一入口 · 启动编排 |
| `core/version.py` | 版本号唯一来源 |
| `core/desktop_presence_runtime.py` · `core/presence_line.py` | 桌面三态主体 · 入口分流 |
| `core/openclawd.py` · `core/agent/execution_planner.py` | 智能体执行 · 策略选择 |
| `core/multi_llm_router.py` · `core/model_catalog.py` | 模型路由 · 模型与档位目录 |
| `core/canonical_task.py` · `core/semantic_anchoring.py` | 任务本体 · 「决策走对象层」判据 |
| `core/meta/` · `core/genome.py` · `config/genomes/` | 元层 · 提示词资产 |
| `galaxy_gateway/` · `core/participant_admission.py` · `core/device_onboarding/` | 设备接入 |
| `electron/` · `electron/renderer/panel/` · `desktop-tauri/` | 桌面外壳 · 面板 · Tauri 壳 |
| `nodes/` · `node_dependencies.json` | 节点 · 节点定义 |
| `config/prometheus.yml` · `config/prometheus_alerts.yml` | 指标抓取 · 告警规则 |
| `scripts/check_*.py` | 仓库守卫（导入边界、复杂度、可达性、接线、裁决独立性…） |

---

## 测试与质量门

```bash
python -m pytest tests/                                  # 全量（约 4.5 万个，30 分钟左右）
python scripts/select_affected_tests.py <改过的文件…>     # 只跑受影响的
for s in scripts/check_*.py; do python "$s"; done        # 仓库守卫
```
CI 在 `.github/workflows/`（15 条），全部跑在 Python 3.11 上。

---

## 相关仓库

- [ufo-galaxy-android](https://github.com/DannyFish-11/ufo-galaxy-android) —— Android 客户端（AIP v3 协议、本地推理、视觉定位）。
  文档见 `docs/ANDROID_COMPAT.md`。本仓复测不覆盖安卓侧。

---

## 安全

- API 鉴权默认开启（`GALAXY_AUTH_ENABLED`），令牌 `GALAXY_API_TOKEN`；密钥经 `core/credential_vault.py` 统一取用，占位符不算密钥。
- 节点 HTTP 面一律 fail-closed（`docs/NODE_HTTP_SECURITY_CONTRACT.md`）。
- 沙箱危险命令拦截 + 资源限制；OpenClawd PolicyGate 白名单。
- CI：CodeQL、gitleaks 密钥扫描、供应链（依赖哈希校验、SBOM 签名）。

---

## 许可证

MIT License（见 `LICENSE`）
