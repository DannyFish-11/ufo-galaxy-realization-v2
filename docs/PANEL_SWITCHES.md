# 面板开关清单

> 本文件由 `python scripts/gen_panel_switches_doc.py --write` 从 `core/routes/panel_switch_policy.py` 生成，**不要手改**；
> `tests/test_every_switch_has_a_disposition.py` 会核对它与清单一致。

## 结论

设置页「全部设置」共登记 390 个键，其中布尔开关 **96** 个。逐个对着生产代码核过之后，它们分成三种去处：

| 去处 | 个数 | 含义 |
|---|---|---|
| **留在面板** | 45 | 用户真有取舍：隐私（录音存不存）、花费（多模型协作）、硬件与网络（下不下 310MB 模型）、安全姿态（要不要强制令牌） |
| **内置**（面板不列） | 33 | 不该有人去关的内部机制：熔断器、派发幂等、回声消除的子参数、自回声闸门……默认开，关掉只会变差或出事 |
| **开发 / 运维**（面板不列） | 18 | 开发、运维、打包、测试用的逃生口。其中「本机回环也封禁」打开后，桌面会把自己锁在自己的后端门外 |

面板不列 ≠ 没接上：这些键仍在 `CONFIG_SCHEMA` 里，`POST /api/config` 照收、`.env` 照写、环境变量照读，只是 `GET /api/config/all` 不列。

## 面板上的控制点

设置浮层里有三类控件，不止「全部设置」：

| 控件 | 在哪 | 管什么 |
|---|---|---|
| 整档「全模态」 | 浮层 | 推拉开关（一个开关管一整片），主键 `GALAXY_AMBIENT_LOOP` |
| 整档「跨设备」 | 浮层 | 推拉开关（一个开关管一整片），主键 `GALAXY_CROSS_DEVICE_ENABLED` |
| 整档「声字同文」 | 浮层 | 推拉开关（一个开关管一整片），主键 `GALAXY_SPEAK` |
| 整档「自主」 | 浮层 | 三档牌，主键 `GALAXY_AUTONOMY` |
| 本机模型档位 A / B / C / D | 浮层 | 四选一，写 `GALAXY_MODEL_TIER` |
| 感知隐私暂停 | 浮层 | `POST /api/perception/desktop/privacy/pause` 与 `…/resume`，不是配置键 |
| 全部设置 | 浮层「全部设置」按钮 | 下面按分组列出的 45 个开关 + 其余数值/文本/选择项 |

## 留在面板上的开关

### 声音（7）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_AEC` | 开 | 回声消除：没有回环设备的机器上等于旁通，有人想整个关掉 |
| `GALAXY_INDEXTTS_AUTOFETCH` | 关 | 首次使用时后台下载 IndexTTS 模型（体积很大）：流量与磁盘的取舍 |
| `GALAXY_KOKORO_AUTOFETCH` | 开 | 首次使用时后台下载约 310MB 模型：流量与磁盘的取舍 |
| `GALAXY_LOCAL_AUDIO` | 开 | 本机出不出声：可以朗读给别的设备、但不想电脑外放 |
| `GALAXY_NATIVE_AUDIO` | 关 | 让模型直接听音频（需全模态服务）还是先转文字：花费与能力的取舍 |
| `GALAXY_SPEAK` | 开 | 朗读回复：有人想只要文字 |
| `GALAXY_VOICE` | 开 | 语音总闸：关掉后启动时不起语音循环，麦克风也不占用 |

### 感知与在场（7）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ACTIVE_PERCEPTION` | 关 | 主动感知（不等你开口自己找事做）：默认关，开了会多花算力与注意力 |
| `GALAXY_AMBIENT_LOOP` | 开 | 自发在场（持续看/听、自己判断何时开口）：整档「全模态」的主键 |
| `GALAXY_AMBIENT_SHARE_SESSION` | 开 | 主动开口续在当前对话上，还是另起一条不打断你的会话：偏好 |
| `GALAXY_NATIVE_AUDIO_CHAT` | 关 | 把录音原样发给模型（默认走转文字）：隐私与 token 的取舍 |
| `GALAXY_PROACTIVE_SCREEN` | 关 | 屏幕变化也触发主动开口：默认关，屏幕一直在变会话会很多 |
| `GALAXY_SYSTEM_AUDIO_CAPTURE` | 开 | 采集本机播放声：隐私 —— AI 能听见电脑在放什么 |
| `GALAXY_SYSTEM_AUDIO_TO_PERCEPTION` | 开 | 播放声送不送进模型（关掉则只用于回声消除）：隐私 |

### 记忆与隐私（3）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_EXPERIENCE_STRATEGY` | 开 | 用历史经验调整策略：面板上这是它唯一的开关（模式档 GALAXY_EXPERIENCE_GUIDANCE 没登记进面板） |
| `GALAXY_MEMORY_MEDIA` | 关 | 把记忆里的截图/录音真的存盘：隐私。代码里默认关 |
| `GALAXY_MEMORY_REPLAY_MEDIA` | 关 | 召回时把过往截图/录音也发给模型：很费 token、也是隐私 |

### 桌面操作与自治（3）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_COMPUTER_USE` | 开 | 桌面操作闭环（AI 自己点鼠标敲键盘）：整档「自主」管的键，安全相关 |
| `GALAXY_DURABLE_EXEC` | 关 | 任务状态落盘、重启接着跑：默认关，开了有写盘开销 |
| `GALAXY_STOP_KEY` | 开 | 动手时按 Esc 叫停：个别人的 Esc 另有用途 |

### 模型与花费（2）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_MOA_ENABLED` | 开 | 难题让几个模型各出方案再汇总：质量与花费的取舍 |
| `GALAXY_OPENSOURCE_FIRST` | 开 | 同等能力下先用本地/开源：省钱、不出网 |

### 多设备与网络（12）

| 键 | 默认 | 为什么 |
|---|---|---|
| `FEDERATION_ENABLED` | 关 | 联邦（把多套 Galaxy 连成一片）：默认关的 opt-in |
| `GALAXY_CROSS_DEVICE_ENABLED` | 开 | 跨设备编排：整档「跨设备」的主键。关掉则只在本机跑 |
| `GALAXY_ENABLE_WEBRTC_DATA_CHANNEL` | 关 | WebRTC 数据通道（浏览器/手机把摄像头麦克风直接推给感知层）：opt-in |
| `GALAXY_HA_BRIDGE` | 开 | 接入 Home Assistant：有 HA 的人可能不想让 AI 去控智能家居 |
| `GALAXY_HF_MIRROR` | 开 | 模型下载走国内镜像：按所在网络选 |
| `GALAXY_LAN_DISCOVERY` | 开 | 局域网自动发现设备：会在局域网里探测，有人不想 |
| `GALAXY_MASTER_BRAIN_ENABLED` | 关 | 主脑编排 + worker/NATS 分布式：默认关=单机。与「跨设备」的关系见 docs/PANEL_SWITCHES.md 的合并建议 |
| `GALAXY_MDNS` | 开 | mDNS 广播网关，手机/手表免输 IP：会在局域网里宣告自己 |
| `GALAXY_NATS_ENABLED` | 开 | NATS 消息总线：单机自用可以关，省一个常驻进程 |
| `GALAXY_ONBOARDING_ENABLED` | 开 | 设备接入平面（发现附近设备、候选/成员）：总闸 |
| `GALAXY_REMOTE_DESKTOP` | 关 | 远程桌面接入：默认关，打开就是对外开一个口 |
| `GALAXY_TS_FUNNEL` | 关 | 把网关经 Tailscale Funnel 暴露到公网：必须让人看见 |

### 安全姿态（11）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ALLOW_ENDPOINT_OVERRIDE` | 开 | 允许覆盖 provider 的 base_url：中转/relay 要用，也是一个可被滥用的口 |
| `GALAXY_ALLOW_REMOTE_INSTALL_SCRIPT` | 关 | 允许执行远程安装脚本：有供应链风险 |
| `GALAXY_AUTH_ENABLED` | 开 | 鉴权：默认开（本机自动签令牌）。关掉等于谁都能调接口 |
| `GALAXY_EGRESS_ALLOW_PRIVATE` | 开 | 允许连内网地址：跨设备编队走的就是内网 |
| `GALAXY_HITL_CONFIRM_GATE` | 关 | 执行前都要你点确认：最稳但最慢 |
| `GALAXY_PERM_STRICT` | 关 | 节点权限从严：没显式授权的动作一律拒绝 |
| `GALAXY_REQUIRE_API_TOKEN` | 关 | 强制要求令牌：没带令牌的请求一律拒绝 |
| `GALAXY_REQUIRE_DEVICE_APPROVAL` | 关 | 未配对批准的设备只能连接、不作为派发目标 |
| `GALAXY_SSH_STRICT_HOST_KEYS` | 关 | 严格核对远程机器指纹：第一次见的机器也拒 |
| `GALAXY_STRICT_AUTHORITY_CHECK` | 关 | 权威校验从严：来源存疑的指令一律拒绝 |
| `GALAXY_WEIGHTS_ALLOW_PICKLE` | 关 | 允许加载 pickle 格式权重：反序列化即执行代码 |

## 内置：不再列在面板上，默认开

### 声音（8）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_AEC_COMFORT_NOISE` | 开 | 回声消除的子参数：把压掉的部分填回极低底噪，消除呼吸感；没有理由单独关 |
| `GALAXY_AEC_RES` | 开 | 回声消除的子参数：线性对消后再压一层非线性残余；没有理由单独关 |
| `GALAXY_TTS_STREAMING` | 开 | 分句流式朗读（边生成边说）：关掉只会更慢 |
| `GALAXY_VOICE_BACKCHANNEL` | 开 | 后台干活时的短应答（嗯，还在处理）：对话节奏的内部细节 |
| `GALAXY_VOICE_BACKCHANNEL_TOLERANCE` | 开 | 用户只是嗯/对/好时不打断：关掉则一出词就打断，是退步 |
| `GALAXY_VOICE_DELEGATE` | 开 | 重活先口头致谢、后台跑：关掉对话会被堵死 |
| `GALAXY_VOICE_DUCKING` | 开 | 用户开口先压低音量再判断是不是真打断：关掉只会更突兀 |
| `GALAXY_VOICE_ECHO_GUARD` | 开 | 自回声文字闸门：识别结果与刚念过的话高度重合就不当用户输入；关掉 AI 会对自己说话起反应 |

### 感知与在场（2）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_NATIVE_MM_CHAT` | 开 | 图片按模型原生格式发：关掉只会退回文字摘要，看不见图 |
| `GALAXY_NATIVE_MODAL_AUTO` | 开 | 切到 B 档时自动激活原生后端：关掉只是多一步手动 |

### 记忆与隐私（2）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ACI_ENABLED` | 开 | 预取上下文：纯加速，没有理由关 |
| `GALAXY_FOCUS_STACK_ENABLED` | 开 | 注意力栈（记住刚才在聊什么）：关掉被打断后接不回去 |

### 桌面操作与自治（1）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_CU_MEMORY` | 开 | 桌面操作记住失败经验：纯正向，没有理由关 |

### 模型与花费（6）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_BANDIT_ROUTING` | 开 | 按实测表现挑模型：路由的内部学习，关掉退回固定顺序 |
| `GALAXY_DISPATCH_IDEMPOTENCY` | 开 | 派发幂等（同一任务重复下发只执行一次）：关掉会重复执行副作用，不该有人去关 |
| `GALAXY_FAST_LOOP` | 开 | 简单请求走短路径：关掉只会更慢 |
| `GALAXY_HF_OLLAMA_FALLBACK` | 开 | HuggingFace 拉不到时回落 Ollama：只在兜底时起作用 |
| `GALAXY_ROUTER_ADAPTIVE_CONCURRENCY` | 开 | 按实测延迟自动调并发：内部调节 |
| `GALAXY_ROUTER_CB_ENABLED` | 开 | 熔断器：后端连续出错就暂停用它。关掉会一直撞墙 |

### 多设备与网络（8）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_CONSENSUS_ROUND` | 开 | 多候选设备时派发前先收敛一轮：内部机制，关掉与加入这一轮之前逐字相同 |
| `GALAXY_HEADSCALE_AUTOJOIN` | 开 | 配好 Headscale 后自动加入：没配时什么都不做 |
| `GALAXY_ONBOARDING_BLUETOOTH` | 开 | 接入平面的蓝牙扫描：受「设备接入平面」总闸管，没有理由单独关 |
| `GALAXY_ONBOARDING_CAN` | 开 | 接入平面的 CAN 总线扫描：同上 |
| `GALAXY_ONBOARDING_SERIAL` | 开 | 接入平面的串口扫描：同上 |
| `GALAXY_ONBOARDING_SSDP` | 开 | 接入平面的 SSDP/UPnP 扫描：同上 |
| `GALAXY_TRANSPORT_ADAPTIVE` | 开 | 传输方式自适应：内部调节 |
| `GALAXY_TS_ADVERTISE_RELAY` | 开 | 把本机登记为 Tailscale 中继：Tailscale 的内部细节 |

### 安全姿态（1）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_MANIFEST_ON_FIRST_TOKEN` | 开 | 首个字一出就显形：界面时序，不是安全选项（登记在 security 类是历史遗留） |

### 启动与诊断（5）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_OTEL_ENABLED` | 开 | 链路追踪：没配导出地址时只在进程内产生、不外发 |
| `GALAXY_PHASE_TIMING` | 开 | 记录启动各阶段耗时：廉价，排查启动慢时要用 |
| `GALAXY_TAURI_AUTOBUILD` | 开 | Tauri 外壳缺产物时自动构建：打包细节 |
| `GALAXY_TAURI_AUTO_INSTALL_MSVC` | 开 | Windows 缺 MSVC 时自动装：打包细节 |
| `GALAXY_URL_SENTINEL` | 开 | Ollama 地址自检：启动时探一次，不对就纠正 |

## 开发 / 运维：不再列在面板上

### 声音（2）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_INDEXTTS_FP16` | 关 | IndexTTS 的 fp16 推理：只对显存紧张的特定 GPU 有意义，改 .env 即可 |
| `GALAXY_INDEXTTS_USE_EMO_TEXT` | 关 | IndexTTS 由台词推断情绪：引擎专属调参 |

### 桌面操作与自治（2）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_COMPUTER_USE_NATIVE_TOOL` | 关 | 声明厂商原生 computer 工具：实验特性，要求路由落到特定型号 |
| `GALAXY_UNIFIED_WORKFLOW` | 关 | 统一工作流引擎：实验特性，默认关 |

### 模型与花费（1）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_IGNORE_CONTEXT_MEASUREMENTS` | 关 | 忽略本机实测的 KV 单价：排障用 |

### 多设备与网络（2）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ANDROID_WS_ENABLED` | 关 | 安卓 WS 接入面：鉴权默认开，开鉴权时它会连带打开 —— 实际上没有可选的 |
| `GALAXY_FABRIC_STRICT` | 关 | NATS 不可达即视为致命：严格部署用，桌面用不到 |

### 安全姿态（4）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK` | 关 | 回落旧调度器：迁移期兜底，默认关 |
| `GALAXY_INPUT_VALIDATION_LOOPBACK` | 关 | 本机回环也做输入校验：测试用；本机来的请求本来就是桌面自己 |
| `GALAXY_IP_BLOCK_LOOPBACK` | 关 | 本机回环也会因连续失败被封：打开它，桌面会把自己锁在自己的后端门外（真发生过） |
| `GALAXY_RATE_LIMIT_LOOPBACK` | 关 | 本机回环也限流：测试用 |

### 启动与诊断（7）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_DEV_MODE` | 关 | 开发者模式：放宽部分校验。不该出现在用户面板上 |
| `GALAXY_ENTRYMODE_USE_READINESS` | 关 | 入口按就绪度判定的实验路径：代码里默认关 |
| `GALAXY_PREFLIGHT_FAIL_FAST` | 开 | 只影响预检命令行的退出码，不影响正常启动 |
| `GALAXY_SKIP_DESKTOP_SURFACE` | 关 | 同上，是 GALAXY_SKIP_ELECTRON 的第二个写法 |
| `GALAXY_SKIP_ELECTRON` | 关 | 跳过桌面外壳（无头部署）：在面板上打开它，下次启动就没有面板了 |
| `GALAXY_STRICT_PREFLIGHT` | 关 | 启动前检查从严：运维用，面板打开它只会让下次起不来 |
| `GALAXY_VERBOSE` | 关 | 启动输出展开每一步：等价于命令行 -v |

## 还可以再合并的（需要你定）

下面这些**没有动** —— 合并会改变行为或牵动多处，需要你定：

| 建议 | 现状 | 为什么没直接做 |
|---|---|---|
| 「多设备」只留一个总闸 | `GALAXY_CROSS_DEVICE_ENABLED`、`GALAXY_MASTER_BRAIN_ENABLED`、`GALAXY_NATS_ENABLED`、`GALAXY_SYSTEM_MODE`（档位）四处都在说「要不要跨设备」；启动日志里能同时出现 `cross_device=False` 与 `nats_enabled=True` | 它们分别管编排、主脑、总线、运行模式，彼此的组合关系要对着 `core/system_orchestrator.py` 的模式解析才能合 |  # noqa: E501
| 「出声」只留一个 | `GALAXY_SPEAK`（朗读回复）与 `GALAXY_LOCAL_AUDIO`（本机播放）：只开前者、关后者就是「朗读给别的设备、电脑不外放」 | 这个组合可能是有意的 |
| 「原生听」两个合一 | `GALAXY_NATIVE_AUDIO`（语音链路里模型直接听）与 `GALAXY_NATIVE_AUDIO_CHAT`（文字对话里附录音）是两条不同的路径 | 合并要先确认两条路径对「听」的定义一致 |
| 安全姿态做成一个「宽松 / 默认 / 严格」档位 | 现在有 11 个互相独立的开关，其中 6 个是「开了更严」的选项 | 这是新的设计，且每个开关的「严」到底牵动什么要逐个确认 |
| `GALAXY_EXPERIENCE_STRATEGY` 并进 `GALAXY_EXPERIENCE_GUIDANCE` | 后者是 off / shadow / on 三档，前者是它的历史总闸；面板上只登记了前者 | 要先把三档登记进面板，再把前者降为内置 |  # noqa: E501

## 清点时顺带查出的真问题

1. **「保存设置」会把登记表里每个键的默认值整体写进 `.env`**（`core/routes/config.py::_write_env_file_with`）。所以登记表的默认值写错，保存一次就会悄悄改变行为。
   `GALAXY_MEMORY_MEDIA` 登记成「默认开」，而代码里三处读取的默认都是关 —— 保存一次设置，截图和录音就在没人点过的情况下开始落盘。已改成默认关；
   `GALAXY_ENTRYMODE_USE_READINESS`（登记开、代码关）与 `GALAXY_PREFLIGHT_FAIL_FAST`（登记关、代码开，且只影响预检命令行）同样对齐到代码。
2. **设置页只认字面量 `"true"` 为开**：`.env` 里手写的 `=1` / `=on`、或登记表里写成 `1` 的默认值（`GALAXY_CONSENSUS_ROUND`），代码都认作开，面板却显示成关，点一下还会把它「关」成 `false`。  # noqa: E501
   现在 `GET /api/config/all` 把布尔值统一规整成 `true` / `false`，登记表里的默认值也都写成字面量。
3. `GALAXY_COMPUTER_USE_NATIVE_TOOL` 的类型登记成 `bool`（不是 `boolean`），设置页会把它画成一个文本框；已归一。
