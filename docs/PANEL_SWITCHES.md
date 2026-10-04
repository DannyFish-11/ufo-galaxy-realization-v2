# 面板开关清单

> 本文件由 `python scripts/gen_panel_switches_doc.py --write` 从 `core/routes/panel_switch_policy.py` 生成，**不要手改**；
> `tests/test_every_switch_has_a_disposition.py` 会核对它与清单一致。

## 结论

设置页「全部设置」共登记 392 个键，其中布尔开关 **96** 个。逐个对着生产代码核过之后，它们分成四种去处：

| 去处 | 个数 | 含义 |
|---|---|---|
| **留在面板** | 18 | 用户真有取舍：隐私（录音存不存）、花费（多模型协作）、硬件与网络（下不下 310MB 模型）、对 AI 行为的偏好（高危命令要不要你批准） |
| **内置**（面板不列） | 45 | 不该有人去关的内部机制和系统自己的保护：熔断器、派发幂等、回声消除、鉴权、Esc 叫停、自回声闸门……默认开，关掉只会变差或出事 |
| **开发 / 运维**（面板不列） | 28 | 开发、运维、打包、测试用的逃生口，以及对外部署的加固选项（强制令牌、设备准入、权限从严……）和危险逃生口（远程安装脚本、pickle 权重）。「本机回环也封禁」打开后，桌面会把自己锁在自己的后端门外 |
| **并进整档按钮**（面板不列） | 5 | 和某个整档按钮同一件事的另一面：翻按钮时一起写，不再各占一行（见下面「并进整档按钮的」） |

面板不列 ≠ 没接上：这些键仍在 `CONFIG_SCHEMA` 里，`POST /api/config` 照收、`.env` 照写、环境变量照读，只是 `GET /api/config/all` 不列。

## 面板上的控制点

设置浮层里有三类控件，不止「全部设置」：

| 控件 | 在哪 | 管什么 |
|---|---|---|
| 整档「全模态」 | 浮层 | 推拉开关（一个开关管一整片），主键 `GALAXY_AMBIENT_LOOP`，连带 1 个子开关 |
| 整档「跨设备」 | 浮层 | 推拉开关（一个开关管一整片），主键 `GALAXY_CROSS_DEVICE_ENABLED`，连带 4 个子开关 |
| 整档「声字同文」 | 浮层 | 推拉开关（一个开关管一整片），主键 `GALAXY_SPEAK` |
| 整档「自主」 | 浮层 | 三档牌，主键 `GALAXY_AUTONOMY` |
| 本机模型档位 A / B / C / D | 浮层 | 四选一，写 `GALAXY_MODEL_TIER` |
| 感知隐私暂停 | 浮层 | `POST /api/perception/desktop/privacy/pause` 与 `…/resume`，不是配置键 |
| 全部设置 | 浮层「全部设置」按钮 | 下面按分组列出的 18 个开关 + 其余数值/文本/选择项 |

## 留在面板上的开关

### 声音（1）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_VOICE` | 开 | 语音总闸：关掉后启动时不起语音循环，麦克风也不占用 |

### 感知与在场（5）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ACTIVE_PERCEPTION` | 关 | 主动感知（不等你开口自己找事做）：默认关，开了会多花算力与注意力 |
| `GALAXY_AMBIENT_LOOP` | 开 | 自发在场（持续看/听、自己判断何时开口）：整档「全模态」的主键 |
| `GALAXY_NATIVE_AUDIO_CHAT` | 关 | 把录音原样发给模型（默认走转文字）：隐私与 token 的取舍 |
| `GALAXY_PROACTIVE_SCREEN` | 关 | 屏幕变化也触发主动开口：默认关，屏幕一直在变会话会很多 |
| `GALAXY_SYSTEM_AUDIO_TO_PERCEPTION` | 开 | 播放声送不送进模型（关掉则只用于回声消除）：隐私 |

### 记忆与隐私（2）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_MEMORY_MEDIA` | 关 | 把记忆里的截图/录音真的存盘：隐私。代码里默认关 |
| `GALAXY_MEMORY_REPLAY_MEDIA` | 关 | 召回时把过往截图/录音也发给模型：很费 token、也是隐私 |

### 模型与花费（2）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_MOA_ENABLED` | 开 | 难题让几个模型各出方案再汇总：质量与花费的取舍 |
| `GALAXY_OPENSOURCE_FIRST` | 开 | 同等能力下先用本地/开源：省钱、不出网 |

### 多设备与网络（7）

| 键 | 默认 | 为什么 |
|---|---|---|
| `FEDERATION_ENABLED` | 关 | 联邦（把多套 Galaxy 连成一片）：默认关的 opt-in |
| `GALAXY_CROSS_DEVICE_ENABLED` | 关 | 跨设备编排：整档「跨设备」的主键。关掉则只在本机跑 |
| `GALAXY_ENABLE_WEBRTC_DATA_CHANNEL` | 关 | WebRTC 数据通道（浏览器/手机把摄像头麦克风直接推给感知层）：opt-in |
| `GALAXY_HF_MIRROR` | 开 | 模型下载走国内镜像：按所在网络选 |
| `GALAXY_MASTER_BRAIN_ENABLED` | 关 | 主脑编排 + worker/NATS 分布式：默认关=单机。与「跨设备」的关系见 docs/PANEL_SWITCHES.md 的合并建议 |
| `GALAXY_REMOTE_DESKTOP` | 关 | 远程桌面接入：默认关，打开就是对外开一个口 |
| `GALAXY_TS_FUNNEL` | 关 | 把网关经 Tailscale Funnel 暴露到公网：必须让人看见 |

### 安全姿态（1）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_HITL_CONFIRM_GATE` | 关 | 命令路由处的额外闸：高危命令（高危词表或零信任规则命中）要你批准才执行，超时按拒绝；是对 AI 行为的偏好，不是部署加固 |

## 内置：不再列在面板上，默认开

### 声音（11）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_AEC` | 开 | 回声消除：把喇叭放出去的声音从麦克风里减掉；关掉 AI 会听见自己说话。没有回环设备的机器上它自己旁通，不需要人去管 |
| `GALAXY_AEC_COMFORT_NOISE` | 开 | 回声消除的子参数：把压掉的部分填回极低底噪，消除呼吸感；没有理由单独关 |
| `GALAXY_AEC_RES` | 开 | 回声消除的子参数：线性对消后再压一层非线性残余；没有理由单独关 |
| `GALAXY_LOCAL_AUDIO` | 开 | 本机外放：默认开，是系统的基本能力；「朗读给别的设备、电脑不外放」这种少见组合改 .env |
| `GALAXY_SPEAK` | 开 | 朗读回复：默认开，是系统的一项基本能力。想关用面板上「声字同文」那个整档按钮（它的主键就是这个键），不再单列一行 |
| `GALAXY_TTS_STREAMING` | 开 | 分句流式朗读（边生成边说）：关掉只会更慢 |
| `GALAXY_VOICE_BACKCHANNEL` | 开 | 后台干活时的短应答（嗯，还在处理）：对话节奏的内部细节 |
| `GALAXY_VOICE_BACKCHANNEL_TOLERANCE` | 开 | 用户只是嗯/对/好时不打断：关掉则一出词就打断，是退步 |
| `GALAXY_VOICE_DELEGATE` | 开 | 重活先口头致谢、后台跑：关掉对话会被堵死 |
| `GALAXY_VOICE_DUCKING` | 开 | 用户开口先压低音量再判断是不是真打断：关掉只会更突兀 |
| `GALAXY_VOICE_ECHO_GUARD` | 开 | 自回声文字闸门：识别结果与刚念过的话高度重合就不当用户输入；关掉 AI 会对自己说话起反应 |

### 感知与在场（3）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_NATIVE_MM_CHAT` | 开 | 图片按模型原生格式发：关掉只会退回文字摘要，看不见图 |
| `GALAXY_NATIVE_MODAL_AUTO` | 开 | 切到 B 档时自动激活原生后端：关掉只是多一步手动 |
| `GALAXY_SYSTEM_AUDIO_CAPTURE` | 开 | 回环采集的电源：回声消除的参考信号来源，只在进程内做减法、不出网、不进上下文；真正的隐私取舍是「播放声送不送进模型」（GALAXY_SYSTEM_AUDIO_TO_PERCEPTION） |

### 记忆与隐私（3）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ACI_ENABLED` | 开 | 预取上下文：纯加速，没有理由关 |
| `GALAXY_EXPERIENCE_STRATEGY` | 开 | 历史遗留的总闸：设计上的控制是 GALAXY_EXPERIENCE_GUIDANCE 的 off / shadow / on 三档，这个只是向后兼容的 kill switch；从自己做过的事里学，不出本机 |
| `GALAXY_FOCUS_STACK_ENABLED` | 开 | 注意力栈（记住刚才在聊什么）：关掉被打断后接不回去 |

### 桌面操作与自治（4）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_COMPUTER_USE` | 开 | 桌面操作闭环（AI 自己点鼠标敲键盘）：默认开，是系统的基本能力。要不要放手由「自主」那一档（safe / guided / autonomous）决定，不另设开关 |
| `GALAXY_CU_MEMORY` | 开 | 桌面操作记住失败经验：纯正向，没有理由关 |
| `GALAXY_DURABLE_EXEC` | 开 | 任务状态落盘、重启接着跑：默认开，是系统的基本能力（任务不该因为一次重启就丢）。落盘有保留上限，只留要续跑的和它们依赖的 |
| `GALAXY_STOP_KEY` | 开 | 动手时按 Esc 叫停：是安全能力，关掉只会少一道刹车。唯一的例外是个别安全软件把键盘钩子当键盘记录器，那时改 .env 关掉，停止改走面板按钮 |

### 模型与花费（6）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_BANDIT_ROUTING` | 开 | 按实测表现挑模型：路由的内部学习，关掉退回固定顺序 |
| `GALAXY_DISPATCH_IDEMPOTENCY` | 开 | 派发幂等（同一任务重复下发只执行一次）：关掉会重复执行副作用，不该有人去关 |
| `GALAXY_FAST_LOOP` | 开 | 简单请求走短路径：关掉只会更慢 |
| `GALAXY_HF_OLLAMA_FALLBACK` | 开 | HuggingFace 拉不到时回落 Ollama：只在兜底时起作用 |
| `GALAXY_ROUTER_ADAPTIVE_CONCURRENCY` | 开 | 按实测延迟自动调并发：内部调节 |
| `GALAXY_ROUTER_CB_ENABLED` | 开 | 熔断器：后端连续出错就暂停用它。关掉会一直撞墙 |

### 多设备与网络（9）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_CONSENSUS_ROUND` | 开 | 多候选设备时派发前先收敛一轮：内部机制，关掉与加入这一轮之前逐字相同 |
| `GALAXY_HA_BRIDGE` | 开 | 接入 Home Assistant：URL 与令牌都配齐才会启动，没配时完全不动；配齐本身就是人的授权，不需要再有一个开关 |
| `GALAXY_HEADSCALE_AUTOJOIN` | 开 | 配好 Headscale 后自动加入：没配时什么都不做 |
| `GALAXY_ONBOARDING_BLUETOOTH` | 开 | 接入平面的蓝牙扫描：受「设备接入平面」总闸管，没有理由单独关 |
| `GALAXY_ONBOARDING_CAN` | 开 | 接入平面的 CAN 总线扫描：同上 |
| `GALAXY_ONBOARDING_SERIAL` | 开 | 接入平面的串口扫描：同上 |
| `GALAXY_ONBOARDING_SSDP` | 开 | 接入平面的 SSDP/UPnP 扫描：同上 |
| `GALAXY_TRANSPORT_ADAPTIVE` | 开 | 传输方式自适应：内部调节 |
| `GALAXY_TS_ADVERTISE_RELAY` | 开 | 把本机登记为 Tailscale 中继：Tailscale 的内部细节 |

### 安全姿态（4）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ALLOW_ENDPOINT_OVERRIDE` | 开 | 允许覆盖 provider 的 base_url：中转 / relay 要用，关掉会让这些部署断掉；要「绝不走中转」的部署由运维改 .env |
| `GALAXY_AUTH_ENABLED` | 开 | 鉴权：默认开（本机自动签令牌、其他设备走配对）。关掉等于谁都能调接口，不该有人在面板上一点就关 |
| `GALAXY_EGRESS_ALLOW_PRIVATE` | 开 | 允许连内网地址：跨设备编队走的就是内网，关掉会把多设备打死；要锁死的是部署的人，改 .env |
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

### 声音（5）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_INDEXTTS_AUTOFETCH` | 关 | 替补引擎 IndexTTS 的按需下载：体积很大，默认关；要用时先选这个引擎，再改 .env 打开 |
| `GALAXY_INDEXTTS_FP16` | 关 | IndexTTS 的 fp16 推理：只对显存紧张的特定 GPU 有意义，改 .env 即可 |
| `GALAXY_INDEXTTS_USE_EMO_TEXT` | 关 | IndexTTS 由台词推断情绪：引擎专属调参 |
| `GALAXY_KOKORO_AUTOFETCH` | 开 | 替补引擎 Kokoro 的按需下载：用到它时才在后台拉模型（约 310MB），默认开；不是用户每天要碰的开关 |
| `GALAXY_NATIVE_AUDIO` | 关 | 「服务现实」门控：本机有没有原生听/说的后端。由本机模型档位（B 档激活时 core/native_modal.py 自动开、离开时自动关）管着，不是用户的取舍；用户的取舍是选哪一档，以及 GALAXY_NATIVE_AUDIO_CHAT |

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

### 安全姿态（11）

| 键 | 默认 | 为什么 |
|---|---|---|
| `GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK` | 关 | 回落旧调度器：迁移期兜底，默认关 |
| `GALAXY_ALLOW_REMOTE_INSTALL_SCRIPT` | 关 | 危险逃生口：允许执行未经校验的远程安装脚本（供应链风险，装本地模型时才可能用到）。默认拦着，不该让人在面板上一点就放开 |
| `GALAXY_INPUT_VALIDATION_LOOPBACK` | 关 | 本机回环也做输入校验：测试用；本机来的请求本来就是桌面自己 |
| `GALAXY_IP_BLOCK_LOOPBACK` | 关 | 本机回环也会因连续失败被封：打开它，桌面会把自己锁在自己的后端门外（真发生过） |
| `GALAXY_PERM_STRICT` | 关 | 部署加固：没显式授权的节点动作一律拒绝。白名单还没全量普及，打开会拒掉未声明的节点 |
| `GALAXY_RATE_LIMIT_LOOPBACK` | 关 | 本机回环也限流：测试用 |
| `GALAXY_REQUIRE_API_TOKEN` | 关 | 部署加固：没带令牌的请求一律拒绝。本机桌面靠自签令牌，打开它要有共享口令，是对外暴露的部署才需要的决定 |
| `GALAXY_REQUIRE_DEVICE_APPROVAL` | 关 | 部署加固：未配对批准的设备只能连接、不作为派发目标。打开后手机要先被批准才接得到任务，是部署的人的决定 |
| `GALAXY_SSH_STRICT_HOST_KEYS` | 关 | 部署加固：连第一次见的远程机器也拒（指纹要事先录进来）。默认是第一次连时记下指纹并告诉你、之后对不上就拒 |
| `GALAXY_STRICT_AUTHORITY_CHECK` | 关 | 部署加固：来源存疑的指令一律拒绝（启动时的权威边界校验失败即中止）。是部署的人的决定 |
| `GALAXY_WEIGHTS_ALLOW_PICKLE` | 关 | 危险逃生口：允许加载 pickle 格式权重（反序列化即执行代码，历次模型投毒的载体）。默认拦着，不该让人在面板上一点就放开 |

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

## 并进整档按钮的

翻按钮时，主键和下面这些子开关**一次写完**（同一次落盘）：主键写 `false` → 子开关全写 `false`；主键写 `true` → 子开关回到登记表默认值（默认关的 opt-in 不会被按钮替人打开）。判据与「没并」的反例见 `core/routes/config_bundles.py` 模块说明。

| 按钮 | 主键 | 并进来的子开关 | 为什么 |
|---|---|---|---|
| 「全模态」 | `GALAXY_AMBIENT_LOOP` | `GALAXY_AMBIENT_SHARE_SESSION`（默认开） | 并进「全模态」：主动开口续在哪条对话上；自发在场关着时没有主动开口可续 |
| 「跨设备」 | `GALAXY_CROSS_DEVICE_ENABLED` | `GALAXY_ONBOARDING_ENABLED`（默认开） | 并进「跨设备」：设备接入平面（发现附近设备、候选/成员）的总闸 |
| 「跨设备」 | `GALAXY_CROSS_DEVICE_ENABLED` | `GALAXY_LAN_DISCOVERY`（默认开） | 并进「跨设备」：局域网自动发现设备；只用本机时没有对象可发现 |
| 「跨设备」 | `GALAXY_CROSS_DEVICE_ENABLED` | `GALAXY_MDNS`（默认开） | 并进「跨设备」：mDNS 广播网关，手机/手表免输 IP；只用本机时没有人需要它 |
| 「跨设备」 | `GALAXY_CROSS_DEVICE_ENABLED` | `GALAXY_NATS_ENABLED`（默认开） | 并进「跨设备」：NATS 消息总线；只用本机时白占一个常驻进程 |

## 还可以再合并的（需要你定）

**合并的判据只有一条：（主键关、这个键开）这个组合有没有意义。** 没有意义的才并进按钮（见「并进整档按钮的」一节）。
下面这些**看着像、没有并** —— 并了会替用户悄悄改一个有隐私、花费或对外暴露含义的选择，需要你定：

| 看着像一个的 | 没并的原因 |
|---|---|
| 「全模态」与「系统声送进模型」`GALAXY_SYSTEM_AUDIO_TO_PERCEPTION` | 「只要回声消除、不想让模型听见自己在放什么」是 `system_audio_capture_service.feed_perception_enabled` 的文档里特意拆开的隐私选择 |
| 「听」`GALAXY_VOICE`、「朗读」`GALAXY_SPEAK`、「本机外放」`GALAXY_LOCAL_AUDIO` | 三个方向：只要听写不要朗读、朗读给别的设备而电脑不外放，都是有意义的组合 |
| 「原生听」`GALAXY_NATIVE_AUDIO_CHAT` 并进本机模型档位 | 那是「每轮都把录音原样发给模型」的花费决定（音频 token 贵），不是「模型会不会听」；会不会听由档位说了算 |
| 「跨设备」并进主脑 / 联邦 / WebRTC 数据通道 / Funnel / 远程桌面 | 它们是默认关的 opt-in，有花费或对外暴露面；按钮「开」不能替用户打开 |
| 「全模态」并进主动感知 `GALAXY_ACTIVE_PERCEPTION` / 屏幕触发 `GALAXY_PROACTIVE_SCREEN` | 同上，默认关、开了会多花算力；它们更像「自主」档（safe / guided / autonomous）的内容，要不要把 autonomous 定义成「主动感知也开」是产品决定 |
| 安全姿态做成一个「宽松 / 默认 / 严格」档位 | 现在有 11 个互相独立的开关，其中 6 个是「开了更严」的选项；每个开关的「严」到底牵动什么要逐个确认 |
| `GALAXY_EXPERIENCE_STRATEGY` 并进 `GALAXY_EXPERIENCE_GUIDANCE` | 后者是 off / shadow / on 三档，前者是它的历史总闸；面板上只登记了前者，要先把三档登记进面板 |

## 清点时顺带查出的真问题

1. **「保存设置」会把登记表里每个键的默认值整体写进 `.env`**（`core/routes/config.py::_write_env_file_with`）。所以登记表的默认值写错，保存一次就会悄悄改变行为。
   `GALAXY_MEMORY_MEDIA` 登记成「默认开」，而代码里三处读取的默认都是关 —— 保存一次设置，截图和录音就在没人点过的情况下开始落盘。已改成默认关；
   `GALAXY_ENTRYMODE_USE_READINESS`（登记开、代码关）与 `GALAXY_PREFLIGHT_FAIL_FAST`（登记关、代码开，且只影响预检命令行）同样对齐到代码。
2. **设置页只认字面量 `"true"` 为开**：`.env` 里手写的 `=1` / `=on`、或登记表里写成 `1` 的默认值（`GALAXY_CONSENSUS_ROUND`），代码都认作开，面板却显示成关，点一下还会把它「关」成 `false`。  # noqa: E501
   现在 `GET /api/config/all` 把布尔值统一规整成 `true` / `false`，登记表里的默认值也都写成字面量。
3. `GALAXY_COMPUTER_USE_NATIVE_TOOL` 的类型登记成 `bool`（不是 `boolean`），设置页会把它画成一个文本框；已归一。
4. **`GALAXY_CROSS_DEVICE_ENABLED` 登记成「默认开」，而代码与 `.env.example` 都是关（出厂只用本机、opt-in）。** 同样走「保存设置整体写进 `.env`」
   这条路：保存一次，跨设备编排就在没人点过的情况下开了。已改成默认关。
5. `GALAXY_NATIVE_AUDIO` 以前列在面板上，但它是「服务现实」门控：切到 B 档时 `core/native_modal.py` 自动打开、离开时自动关掉。
   面板上的开关会被档位切换悄悄覆盖，是同一个事实两处各存一份；用户的取舍是选哪一档，已改为运维项。
6. **安全姿态不该是一排开关。** 它们要么是系统自己的保护（鉴权、Esc 叫停、允许覆盖地址、允许连内网），默认开、关掉只会出事或断功能；
   要么是危险逃生口（远程安装脚本、pickle 权重），一点就放开等于给人制造出事的机会；要么是对外部署才需要的加固（强制令牌、设备准入、权限从严、
   权威校验从严、SSH 严格指纹），普通用户看不懂也用不上。这 15 个（连同回声消除、采集本机播放声、历史经验总闸、Home Assistant 接入）已不再列在面板上，
   面板上只剩「高危命令要不要你批准」这一个对 AI 行为的偏好。
7. `GALAXY_HITL_CONFIRM_GATE` 原先写成「执行前都要你点确认」，实际只拦命中高危词表或零信任规则的命令；说明已改成它真正做的事。

8. **面板没有任何「要重启才生效」的提示。** 语音循环、自发在场、跨设备、主脑、远程桌面、联邦、Tailscale Funnel、模型镜像等读取点在启动（或导入）时，
   面板上点了、界面显示已保存，要等下次启动才起作用。现在 `core/routes/config_restart.py` 是唯一清单（只登记从读取位置核实过的键），
   `GET /api/config/all` 与 `GET /api/config/bundles` 带 `restart_required`，面板在对应行写「重启后生效」。
9. **任务状态落盘（`GALAXY_DURABLE_EXEC`）改成默认开**（所有者的决定：它是系统的基本能力）。默认开之前先补了三处会出事的地方：
   检查点以前落在仓库的 `runtime/`、不认 `GALAXY_DATA_DIR`（现在认，旧位置上已有文件则沿用）；以前每次状态变更都把「有史以来所有节点」整份重写，
   现在只留续跑要的（没结束的、它们依赖的、连接它们的边）加最近结束的 200 个；测试里一律关掉（`tests/conftest.py`），免得同一进程里前面用例留下的节点被后面新建的实例读到。
   **要知道的后果**：重启后会自动重派没做完的任务（逐节点先过派发幂等守卫，崩溃前已派发过的不会二次触发副作用）；想关写 `GALAXY_DURABLE_EXEC=false`。

## 已知、没有动的

- `GALAXY_MEMORY_MEDIA` 有四处读取：三处（入口）默认关，存储层 `core/memory/media_store.py` 默认开。所有入口都先过那三道门，所以实际默认是不存盘；
  边角情况是单独打开了环境注意力存帧、却没开这个键，此时存储层默认开会存下来，而「保存设置」写入的「关」会让它存不下来。
- `GALAXY_MASTER_BRAIN_ENABLED` 与 `GALAXY_CROSS_DEVICE_ENABLED` 在代码里互相独立（一个起主脑与 worker，一个决定运行模式），含义重叠，是否合并是产品决定。
