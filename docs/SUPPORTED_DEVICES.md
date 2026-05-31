# Galaxy — 支持的设备清单

> **版本**: v10.0 | **更新**: 2026-05-31 | **节点**: 133 个

---

## 按方便程度分类

### ⭐ 开箱即用（无需额外硬件，直接可用）

| 设备 | 节点 | 说明 | 使用方式 |
|------|------|------|----------|
| **本地文件系统** | Node_06_Filesystem | 文件读写、目录管理 | 直接调用 |
| **本地 Shell** | Node_122_Shell | 命令执行（带沙箱安全检查） | 直接调用 |
| **Git** | Node_07_Git | 代码版本控制 | 直接调用 |
| **SQLite** | Node_13_SQLite | 本地数据库 | 直接调用 |
| **沙箱执行** | Node_09_Sandbox | 安全代码执行（256MB/30s限制） | 直接调用 |
| **记忆系统** | Node_100_MemorySystem | 持久记忆存储 | 直接调用 |
| **知识库** | Node_72_KnowledgeBase | 知识检索 | 直接调用 |
| **代码引擎** | Node_101_CodeEngine | 代码生成与执行 | 直接调用 |

### ⭐⭐ 配置一次，永久使用（需要 API Key / SSH）

| 设备 | 节点 | 说明 | 配置方式 |
|------|------|------|----------|
| **远程 Linux 服务器** | Node_Linux_Agent | SSH 远程操作任意 Linux | SSH 密钥或密码 |
| **AI 搜索 (Tavily)** | Node_Tavily_Search | AI 原生搜索 | `TAVILY_API_KEY` |
| **Brave 搜索** | Node_22_BraveSearch | 隐私搜索 | 直接可用（部分限流） |
| **Google 搜索** | Node_25_GoogleSearch | 网页搜索 | 可能需要 Key |
| **Slack** | Node_10_Slack | 团队消息 | `SLACK_API_KEY` |
| **Email (SMTP)** | Node_16_Email | 邮件发送 | SMTP 配置 |
| **Discord** | Node_26_Discord | 社区消息 | `DISCORD_API_KEY` |
| **GitHub** | Node_11_GitHub | 代码仓库操作 | `GITHUB_API_KEY` |
| **DeepL 翻译** | Node_18_DeepL | 文本翻译 | `DEEPL_API_KEY` |
| **Notion** | Node_21_Notion | 知识管理 | `NOTION_API_KEY` |
| **PostgreSQL** | Node_12_Postgres | 关系数据库 | 连接字符串 |
| **Qdrant 向量库** | Node_20_Qdrant | 向量相似度搜索 | 连接字符串 |

### ⭐⭐⭐ 需要物理设备（硬件）

| 设备 | 节点 | 说明 | 硬件要求 |
|------|------|------|----------|
| **Android 手机** | Node_33_ADB + Node_34_Scrcpy | 屏幕投射 + ADB 控制 | USB 连接安卓设备 |
| **Android VLM** | Node_113_AndroidVLM | 安卓 GUI 视觉理解 | 安卓设备 + VLM 模型 |
| **摄像头** | Node_46_Camera | 视频捕获 | USB/内置摄像头 |
| **麦克风** | Node_47_Audio | 音频输入 | 内置/外接麦克风 |
| **蓝牙 BLE** | Node_38_BLE | 低功耗蓝牙设备 | 蓝牙适配器 |
| **NFC** | Node_44_NFC | 近场通信 | NFC 读卡器 |
| **串口设备** | Node_48_Serial | RS-232/RS-485 | USB 转串口线 |
| **CAN 总线** | Node_42_CANbus | 汽车/工业控制 | CAN 适配器 |
| **无人机 (MAVLink)** | Node_43_MAVLink | 无人机通信 | MAVLink 兼容飞控 |
| **3D 打印机** | Node_49_OctoPrint + Node_127_BambuLab | 3D 打印控制 | OctoPrint/BambuLab 打印机 |
| **智能家居** | Node_27_SmartHome | 智能家居控制 | 智能家居网关 |
| **MQTT 设备** | Node_41_MQTT | IoT 消息队列 | MQTT Broker |

### ⭐⭐⭐⭐ 需要云端服务 / 专业环境

| 设备 | 节点 | 说明 | 环境要求 |
|------|------|------|----------|
| **量子计算** | Node_51_QuantumDispatcher + Node_52_QiskitSimulator + Node_57_QuantumCloud | IBM/AWS 量子云 | IBM Quantum / AWS Braket 账号 |
| **数字孪生** | Node_74_DigitalTwin | 物理系统仿真 | 专业建模环境 |

---

## 按功能领域分类

### 计算机与自动化

| 节点 | 功能 | 方便度 |
|------|------|--------|
| Node_06_Filesystem | 文件读写、目录遍历 | ⭐ |
| Node_122_Shell | Shell 命令执行（带沙箱） | ⭐ |
| Node_07_Git | Git 操作 | ⭐ |
| Node_124_LinuxDesktopAuto | Linux 桌面自动化 | ⭐ |
| Node_45_SystemAgent | 系统管理 | ⭐ |
| Node_Linux_Agent | 远程 SSH 操作 | ⭐⭐ |
| Node_09_Sandbox | 沙箱代码执行 | ⭐ |

### 数据库与存储

| 节点 | 功能 | 方便度 |
|------|------|--------|
| Node_13_SQLite | SQLite 本地数据库 | ⭐ |
| Node_12_Postgres | PostgreSQL 远程数据库 | ⭐⭐ |
| Node_20_Qdrant | 向量数据库 | ⭐⭐ |
| Node_72_KnowledgeBase | 知识库 | ⭐ |
| Node_80_KnowledgeBase | 混合知识库（向量+图） | ⭐ |
| Node_100_MemorySystem | 持久记忆系统 | ⭐ |

### 搜索引擎

| 节点 | 功能 | 方便度 |
|------|------|--------|
| Node_Tavily_Search | AI 原生搜索（推荐） | ⭐⭐ |
| Node_22_BraveSearch | Brave 隐私搜索 | ⭐⭐ |
| Node_25_GoogleSearch | Google 搜索 | ⭐⭐ |
| Node_97_AcademicSearch | 学术搜索 | ⭐⭐ |

### 通信与消息

| 节点 | 功能 | 方便度 |
|------|------|--------|
| Node_10_Slack | Slack 消息 | ⭐⭐ |
| Node_16_Email | SMTP 邮件 | ⭐⭐ |
| Node_26_Discord | Discord 消息 | ⭐⭐ |
| Node_95_WebRTC_Receiver | WebRTC 实时通信 | ⭐⭐ |

### 媒体处理

| 节点 | 功能 | 方便度 |
|------|------|--------|
| Node_14_FFmpeg | 视频转码、剪辑 | ⭐ |
| Node_15_OCR | 文字识别 | ⭐ |
| Node_17_EdgeTTS | 文本转语音 | ⭐ |
| Node_46_Camera | 摄像头 | ⭐⭐⭐ |
| Node_47_Audio | 音频处理 | ⭐ |
| Node_86_VideoProcessor | 视频处理 | ⭐ |
| Node_87_ImageAnalysis | 图像分析 | ⭐ |
| Node_90_MultimodalVision | 多模态视觉 | ⭐ |
| Node_125_MediaGen | 媒体生成 | ⭐ |

### 物理设备

| 节点 | 功能 | 硬件要求 |
|------|------|----------|
| Node_33_ADB | Android 调试桥 | 安卓手机 |
| Node_34_Scrcpy | 屏幕投射 | 安卓手机 |
| Node_113_AndroidVLM | 安卓 GUI 理解 | 安卓手机 + VLM |
| Node_38_BLE | 蓝牙低功耗 | 蓝牙适配器 |
| Node_44_NFC | 近场通信 | NFC 读卡器 |
| Node_48_Serial | 串口通信 | USB 转串口 |
| Node_42_CANbus | CAN 总线 | CAN 适配器 |
| Node_43_MAVLink | 无人机 | MAVLink 飞控 |
| Node_49_OctoPrint | 3D 打印 (OctoPrint) | 3D 打印机 |
| Node_127_BambuLab | 3D 打印 (BambuLab) | BambuLab 打印机 |

---

## 推荐入门组合

如果你是第一次使用 Galaxy，推荐按以下顺序启用设备：

### 第一阶段（5分钟，全部免费）

```bash
# 1. 本地 Shell + 文件系统 — 直接可用
# 2. Git — 直接可用
# 3. SQLite — 直接可用
# 4. 沙箱执行 — 直接可用
```

### 第二阶段（10分钟，需要 API Key）

```bash
# 5. AI 搜索 — 配置 TAVILY_API_KEY
# 6. Email — 配置 SMTP
# 7. GitHub — 配置 GITHUB_API_KEY
```

### 第三阶段（15分钟，需要 SSH 密钥）

```bash
# 8. 远程 Linux 服务器 — 注册 SSH 密钥
curl -X POST http://localhost:8765/api/v1/agents/linux/servers \
  -d '{"name":"我的服务器","host":"IP","user":"root","key_path":"~/.ssh/id_rsa"}'
```

### 第四阶段（需要硬件）

```bash
# 9. Android 手机 — USB 连接
# 10. 摄像头/麦克风 — 直接可用
# 11. 蓝牙/NFC — 需要适配器
# 12. 3D 打印机 — 需要打印机
```

---

## REST API 端点（设备操作）

以下设备操作通过 REST API 暴露：

### Linux Agent（远程服务器）

```
POST /api/v1/agents/linux/servers              — 注册服务器
GET  /api/v1/agents/linux/servers               — 列出服务器
GET  /api/v1/agents/linux/servers/{id}          — 查看详情
DELETE /api/v1/agents/linux/servers/{id}        — 注销
POST /api/v1/agents/linux/servers/{id}/execute  — 执行命令
POST /api/v1/agents/linux/servers/{id}/file/read   — 读文件
POST /api/v1/agents/linux/servers/{id}/file/write  — 写文件
GET  /api/v1/agents/linux/servers/{id}/info     — 系统信息
POST /api/v1/agents/linux/servers/{id}/probe    — 探测连通性
```

### 沙箱（安全执行）

```
POST /api/v1/agents/sandbox/validate  — 验证命令安全性
POST /api/v1/agents/sandbox/execute   — 沙箱执行代码
GET  /api/v1/agents/sandbox/status    — 沙箱状态
```

---

*最后更新: 2026-05-31 | 节点: 133 | API 端点: 37*
