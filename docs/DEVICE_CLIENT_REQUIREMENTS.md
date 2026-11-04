# 安卓仓与手表仓要补的（逐条、可照做）

> 2026-11-02（第 16 轮）对着三个仓库的代码写：中心 `ufo-galaxy-realization-v2` main、
> 安卓 `DannyFish-11/ufo-galaxy-android` @ `63453a2`、手表 `DannyFish-11/galaxy-wearos` @ `04f725b`（后两个只读核对过源码）。
> 帧格式以中心的代码为准，每一条都写了中心那边是哪个文件、哪条测试守着；改动时**两边一起看**。

所有者定的原则（第 15 轮）：危险操作需授权，就发给那个设备，或者由哪个设备来授权；**接受各种生态的设备，不用每一次都要自己加一种设备**。
所以中心不按设备种类写死任何东西：设备自己声明它会什么，中心照声明办（`core/approvers.py`）。

## 一览

| # | 仓库 | 要做的 | 必须 / 建议 | 做之前的现状 |
|---|---|---|---|---|
| A1 | 安卓 | 能回答批准：处理 `decision_request` / `decision_withdraw`，点了经 `human_input` 回 | **必须** | 收到 `decision_request` 落进 `else -> onMessage(text)`，没人显示 |
| A2 | 安卓 | `capability_report` 里声明 `"approvals": true`（**A1 做完之后**） | **必须** | 没有声明 → 中心不问手机，改在电脑面板 / 别的设备上问 |
| A3 | 安卓 | 桥接 Agent 把 `progress: true` 的对话下行当「进度」显示，不当最终回答 | 建议 | 每条都交给 `host.onReply`，进度句和回答长得一样 |
| W1 | 手表 | `capability_report` 里声明 `"approvals": true` | **必须**（不做也照旧能批，但那是兼容，不是正路） | 不声明；中心按「已发出去的手表客户端」兼容认它 |
| W2 | 手表 | 确认 `human_input` 只在用户点了选项时带 `selected_option`，语音只放 `voice_input` | 核对（现状已对） | 已对 |
| X1 | 两边 | 旧入口 `/ws/ufo3`、`/ws/android` 退役 | **已做（2026-11-02，中心这边）**，两边不用改 | 两个 App 的全部历史里都只连 `/ws/device/{device_id}` |
| X2 | 手表 | 通话时让智能体能动手（实时语音接工具） | 要所有者先定用哪家实时语音 | 通话是独立的实时模型对话，不接智能体的工具 |

第三节是**任何一台别家生态的设备**（平板、车机、家居面板、别家手表……）接进来要做的同一套事 —— 安卓和手表只是其中两种。

---

## 一、安卓 App（`DannyFish-11/ufo-galaxy-android`）

### A1 能回答批准（必须）

**为什么**：中心智能体要做危险动作（删文件、发消息、操控设备……）前会问人。从哪台设备发起就在哪台上问。
今天安卓 App 只在 `shared-protocol/.../MsgType.kt` 里**定义**了 `DECISION_REQUEST` / `DECISION_WITHDRAW`，
`app/.../network/GalaxyWebSocketClient.kt::handleMessage`（约 1528–1620 行的 `when`）里没有它们的分支，
这一帧落进最后的 `else -> listeners.forEach { it.onMessage(text) }`，没人显示。第 15 轮起中心不再往不会答的手机上发，
手机发起的危险动作改在电脑面板或别的能批的设备上批，手机上收到一句「已在电脑面板上问你」。做完 A1 + A2，手机发起的就在手机上批。

**1. 收 `decision_request`**（中心 `core/interaction/pending_decision_registry.py::request_human_decision`，选项来自
`core/interaction/high_risk_confirmation.py::build_options`）。线上逐字是：

```json
{
  "type": "decision_request",
  "payload": {
    "decision_id": "3f0c…",
    "title": "要执行 Node_06_Filesystem.delete(/a.txt) —— 你让我删这个文件 吗？",
    "summary": "这是一个 dangerous 级操作，需要你点头才会执行。",
    "options": [{"id": "deny", "label": "不要"}, {"id": "approve", "label": "批准"}],
    "urgency": "high",
    "timeout_ms": 90000,
    "default_option": null,
    "source": "openclawd",
    "timestamp": 1762060800.123
  }
}
```

要做：
- `handleMessage` 加一个分支 `MsgType.DECISION_REQUEST -> listeners.forEach { it.onDecisionRequest(payloadJson) }`，
  `Listener` 里加 `fun onDecisionRequest(payloadJson: String) = Unit`（与 `onA2AFrame` 同一个写法）。
- 弹一条**高优先级**通知（heads-up）：标题 = `title`，正文 = `summary`，按钮**按 `options` 的顺序**、文字用 `label`，
  点了回传那个按钮的 `id`。通知的 id 由 `decision_id` 算出来（下面撤回要按它收）。
- `timeout_ms` 到了把通知收起来（中心那边超时已判「没人应答 = 不执行」，不用回）。
- **不要**：替人自动选、超时默认选、把语音 / 输入的文字当批准。中心只认 `selected_option == "approve"` 且是人真的答了；
  只有语音一律不算授权（`core/interaction/high_risk_confirmation.py::interpret_decision`），所以给批准就**必须**带按钮 `id`。
- 「批准」放在后面、不要做成默认焦点：误触第一个按钮的代价不该是执行破坏性操作。

**2. 回 `human_input`**（中心 `galaxy_gateway/websocket_handler.py` 的 `command_text == "human_input"` 分支）。
走**同一条已认证的** `/ws/device/{device_id}` 连接，用 `sendJson` 发：

```json
{
  "type": "command",
  "version": "3.0",
  "device_id": "<本机设备号>",
  "correlation_id": "hi_<uuid>",
  "timestamp": 1762060805123,
  "payload": {
    "command": "human_input",
    "payload": {
      "decision_id": "3f0c…",
      "selected_option": "approve",
      "device": "android",
      "timestamp": 1762060805123
    }
  }
}
```

- 帧里不用带令牌：规范设备入口把这条连接自己的凭证带给不带令牌的帧（与 `device_register` 同一条，`tests/test_phone_joins_through_its_bridge_agent.py` 守着）。
- **只有被问到的设备答了才算**（第 16 轮）：中心按这条连接认证过的设备号核对「这个问题发给过你没有」，没问你的设备拿着
  `decision_id` 回「批准」会被拒。所以一定从收到这条 `decision_request` 的那条连接回。
- 中心回一条 `command_result`，`correlation_id` 等于你发的那个：
  - 收下了：`{"success": true, "decision_id": "…", "resolved": true}` → 通知收起来，可以显示「已批准 / 已拒绝」；
  - 没问这台：`{"success": false, "error": "这条决定没有问这台设备", "decision_id": "…"}`；
  - 这个决定已经结束（别处答了、超时了）时，中心会把这次回答当成人说的一句话交给智能体（主动开口那条路）——
    所以**收到 `decision_withdraw` 或超时之后就不要再发**。

**3. 收 `decision_withdraw`**（中心 `core/interaction/decision_withdrawal.py::build_withdraw_message`）。
同一个问题会同时发给几台能批的设备，一台答了，其余几台收到：

```json
{"type": "decision_withdraw", "payload": {"decision_id": "3f0c…", "reason": "answered_elsewhere"}}
```

`reason` 只有四个值：`answered_elsewhere` / `timed_out` / `cancelled` / `superseded`。按 `decision_id` 把那条通知收掉；
人已经点过了就什么都不做。撤回帧里**故意不带**别处答了什么。答了的那一台不会收到撤回。

**4. 测试**（安卓仓，照手表仓现成的几条写）：
- 解析 `decision_request` → 通知的标题 / 正文 / 按钮顺序与 id（对照手表 `domain/DecisionRequestParsing.kt`）；
- 点「批准」→ 发出去的帧**逐字段**等于上面的 `human_input`；点「不要」→ `selected_option` 是 `deny`；
- `decision_withdraw` 收掉的是**那一条**通知（对照手表 `DecisionWithdrawCancelsTheRightNotificationTest`）；
- 智能体发来的普通消息不能被当成决策回（对照手表 `AgentMessageNotificationIsNotAnAlarmTest`：消息回复不是 `human_input`）。

### A2 声明「我能回答批准」（必须，A1 做完之后）

在 `GalaxyWebSocketClient.kt` 拼 `capability_report` 的地方（约 2548 行 `addProperty("bridge_agent", …)` 旁边）加：

```kotlin
// 这台手机收得到 decision_request、会经 human_input 回 decision_id 与 selected_option(中心 core/approvers.py)
addProperty("approvals", true)
```

- **先做 A1 再声明**：声明了却不显示，中心会往手机上问，人白等一个确认超时（中心不执行，但人不知道要去哪儿批）。
- 中心的规则（`core/approvers.py`）：设备在 `device_register`、`capability_report` 或 `POST /api/v1/participants/register` 里说
  `"approvals": true`（顶层、`payload`、`metadata` 都认）就记进它的登记（UDM 元数据 `answers_approvals`），之后它发起的危险动作在它自己身上问，
  电脑面板没开时别处发起的也会问它；说 `false` 就不问。
- 声明之后手机发起的危险动作：在手机上弹（A1），手机上不再收到「已在电脑面板上问你」那句。

### A3 进度句当进度显示（建议）

中心往桥接 Agent 发的对话下行有两种（`core/phone_bridge.py`）：

```json
{"kind": "conversation", "body": {"role": "assistant", "text": "这一步要你点头才做:…已在电脑面板上问你。", "progress": true, "success": true}}
{"kind": "conversation", "body": {"role": "assistant", "text": "删好了。", "success": true}}
```

`bridge/BridgeAgentRuntime.kt` 约 125 行 `A2A.Kind.CONVERSATION ->` 把每一条都交给 `host.onReply(text, success)`。
建议看 `body.progress`：为 `true` 时显示成一条状态 / 进度（不结束「正在处理」的状态、不当最终回答），没有或为 `false` 才是回答。
A2 做完后这类进度句会很少（只在手机声明了 `false`、或中心对它一无所知时出现），所以这是建议，不是必须。

---

## 二、手表（`DannyFish-11/galaxy-wearos`）

手表的批准这条路是通的：`data/AIPClient.kt` 收 `decision_request`、`receiver/ReplyReceiver.kt` 与 `GalaxyWearApplication.kt` 经
`sendCommand("human_input", …)` 回 `decision_id` / `selected_option`，`decision_withdraw` 也处理了（第 13 轮按真实帧形状真跑打通）。

### W1 声明「我能回答批准」（必须）

`data/WatchMember.kt::capabilityReportFrame` 里加一行：

```kotlin
put("approvals", true) // 收得到 decision_request、会经 human_input 回(中心 core/approvers.py)
```

- 不加今天也照旧能批：中心对**没声明**的设备只认「已经发出去、确实会答的手表」这一类（种类里带 `watch` / `wear`），这是给旧版本留的兼容，
  不是正路 —— 新设备一律声明，中心不再按种类加东西。
- 同时在 `WatchMemberFramesTest` 里钉一条：`capability_report` 里 `approvals == true`。

### W2 核对（现状已对，不用改）

- `human_input` 的 `selected_option` 只在人点了某个选项时带，语音回答只放 `voice_input` —— 中心对只有语音的回答一律不算批准，现状就是这样写的。
- 回答一律从收到问题的那条连接发（第 16 轮起中心只认被问到的设备的回答）—— 手表只有一条连接，天然满足。

---

## 三、任何一台别家生态的设备接进来（通用清单）

平板、车机、别家手表、家居面板、Linux 小盒子……不用改中心的代码，按下面说清楚自己就行：

1. **连上**：`ws(s)://<电脑>:<端口>/ws/device/{device_id}`，握手头带 `Authorization: Bearer <令牌>`（配对码换来的设备令牌，或主人的 API 令牌）。
2. **登记** `device_register`：`device_type` / `platform` 用**你自己的叫法**（如 `harmonyos_smart_screen`）。中心认不出也照收，
   只记一行 INFO，设备卡上照你的原话显示（`core/device_onboarding/service.py::_type_of`）。
   ```json
   {"version": "3.0", "type": "device_register", "device_id": "screen-1", "timestamp": 1762060800000,
    "device_type": "harmonyos_smart_screen", "platform": "harmonyos", "device_name": "客厅智慧屏",
    "payload": {"device_type": "harmonyos_smart_screen", "platform": "harmonyos", "device_name": "客厅智慧屏"}}
   ```
3. **报能力** `capability_report`：你能替智能体做的动作 + 一句说明（模型据此决定让谁做什么），以及两个可选声明：
   ```json
   {"version": "3.0", "type": "capability_report", "device_id": "screen-1", "timestamp": 1762060801000,
    "platform": "harmonyos",
    "supported_actions": ["notify", "get_status"],
    "action_descriptions": {"notify": "在屏幕上弹一条通知", "get_status": "读屏幕的开关与音量"},
    "approvals": true,
    "bridge_agent": "bridge/1"}
   ```
   - `approvals: true`：你会处理 `decision_request` / `decision_withdraw` 并经 `human_input` 回（第一节 A1 的 1–3 条，帧格式一样）；
   - `bridge_agent`：你能装中心派来的桥接 Agent（走对外 A2A，`core/a2a_link.py`；安卓 `bridge/BridgeAgentRuntime.kt` 是参照实现）。不会就别写。
4. **执行动作并回话**：智能体让你做事时回 `command_result`，失败必须带原因（对照手表 `WatchMember.commandResultFrame`）。
5. **人说的话交给智能体**：`command` 帧，`payload.command = "voice_query"`，`payload.payload.text = "…"`；回答在 `command_result` 里。
6. **没被主人批准的设备说了也不算**：主人开了设备准入闸（`GALAXY_REQUIRE_DEVICE_APPROVAL`）时，在面板「等你同意的设备」里点「接入」之前，
   你声明 `approvals` 也不会被问。

中心这边守着这套的测试：`tests/test_any_device_that_says_it_can_approve_is_asked.py`（声明、发现、谁来批、准入闸、设备卡上的叫法）、
`tests/test_watch_reaches_the_central_agent.py`（真实帧形状的一整圈、没问的设备答了不算）、`tests/test_decision_fork_is_withdrawn.py`（撤回）。

---

## 四、要所有者定的

- **X1 旧入口退役 —— 已做（2026-11-02，所有者：「退役吧，确保没有东西在用它也不影响什么」）**：`/ws/ufo3/{device_id}`、`/ws/android/{device_id}`、`/ws/android`
  没有路由了，握手即被拒；`GALAXY_ENABLE_LEGACY_PROTOCOLS`（只为 `/ws/ufo3` 存在）随之删除。退役前核对过：安卓（完整 195 个提交）与手表（完整 141 个提交）
  的源码历史里一次都没连过这三条，一直只连 `/ws/device/{device_id}`（安卓 `AppSettings.CANONICAL_WS_DEVICE_PATH_TEMPLATE`）；安卓读配置发现时期望 `ws_paths`
  是对象、服务端给的是列表，所以那份列表里的旧路径从没被用上。**两边什么都不用改。** 配置发现现在只给 `/ws/device/{id}`，`ws_paths_compat` 键留着、给空表。
  守着的测试：`tests/test_retired_device_ingress_stays_retired.py`。
- **X2 手表通话时智能体动手**：通话走 provider 的实时语音会话，没接智能体的工具。要接得先定用哪家实时语音（OpenAI realtime / Gemini live 的函数调用协议不同），
  然后把函数调用桥到 `handle_request(source="wear_call")`。

## 五、做完之后怎么验

1. 中心起 `python main.py`，手机 / 手表照常配对连上。
2. **手机上**说「帮我删掉电脑上的 `<某个测试文件>`」：手机弹一条「要执行 … 吗？」，点「批准」文件被删；再来一次点「不要」，文件还在；
   不理它，超时后文件还在。电脑面板上不出卡。
3. 手机声明了 `approvals: true` 之后，**手机自己发起的只在手机上问**（面板开不开都一样，从哪发起就在哪批）。要看「同一个问题发给几台、一台答了别的收起」，
   让一台**答不了**批准的设备发起（或手机临时声明 `approvals: false`），电脑面板关着：手机和手表都弹，在手表上点「批准」→ 删掉，
   手机上那条自己收起来（`decision_withdraw`，`reason: answered_elsewhere`）；反过来在手机上点也一样，手表收起。
   （2026-11-04 更正：原先这里写成「手机发起、面板关掉时手机和手表都弹」，与中心 `core/approval_gate.py::request_approval` 的规则不符。）
4. `GET /api/v1/onboarding/cards`：手机、手表都在，种类是它们自己报的。
5. 中心日志里没有 `HITL.resolve: 不是问它的设备回的答`（有就说明回答走错了连接）。
