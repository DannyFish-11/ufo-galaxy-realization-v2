# Galaxy Wear OS

Galaxy 手表伴侣应用。通过 AIP v3 协议与 Galaxy 主系统实时同步，支持语音输入、三态指示器和表盘小部件。

## 支持的设备

### 完全支持（Wear OS 3.0+）

| 品牌 | 型号 | 系统 | 状态 |
|------|------|------|------|
| Google | Pixel Watch 1/2/3 | Wear OS 3.5+ | ✅ |
| Samsung | Galaxy Watch 4/5/6/7 | Wear OS 3.0+ | ✅ |
| 小米 | Watch 2 Pro | Wear OS 3.5 | ✅ |
| OPPO | Watch 3/4 Pro | Wear OS 3.0+ | ✅ |
| 其他 | 所有 Wear OS 3.0+ 手表 | Wear OS | ✅ |

### 不支持（封闭系统）

| 品牌 | 型号 | 系统 | 原因 |
|------|------|------|------|
| 小米 | Watch S1/S2/S3/S4 | HyperOS Watch | 封闭系统，不支持第三方 APK |
| 小米 | Watch Color/Color 2 | RTOS | 轻量系统，无法安装应用 |
| 小米 | 手环 8/9/Pro | 小米自研固件 | 不支持 APK，见下方替代方案 |
| 华为 | Watch GT/GT2/GT3/GT4 | HarmonyOS/HarmonyOS NEXT | 封闭系统 |
| 华为 | 手环 8/9 | LiteOS | 不支持第三方应用 |
| Apple | Watch 全系列 | watchOS | 封闭生态 |

### 小米手环替代方案

小米手环不能装 Galaxy APP，但可以作为**通知接收端**使用：

1. 在 Galaxy 主系统中配置手环的蓝牙 MAC 地址
2. Galaxy 通过蓝牙将消息推送到手环显示
3. 手环按钮操作可回传到 Galaxy

这种方式走的是小米蓝牙通知协议，不需要在手环上安装任何应用。
配置方式：在 Galaxy 的 `devices.yml` 中添加手环条目，类型选 `mi_band`。

## 构建

### 环境要求

- Android Studio Koala (2024.1.1) 或更新版本
- JDK 17+
- Wear OS 3.0+ 模拟器或物理手表

### 编译

```bash
# 克隆本仓库
git clone <repo-url> galaxy-wearos
cd galaxy-wearos

# 用 Android Studio 打开，或命令行编译
./gradlew :app:assembleDebug

# 安装到手表（USB 调试或 WiFi ADB）
adb install app/build/outputs/apk/debug/app-debug.apk
```

### 首次配对

1. 手表上打开 Galaxy APP
2. 进入**设置**
3. 填入 Galaxy 服务器的 WebSocket 地址（如 `ws://192.168.1.100:7788`）
4. 填入 Token
5. 点击**连接**

连接成功后状态指示器会变化：
- **⚫ SILENT**（黑）→ 未连接
- **⚪ LIMINAL**（灰）→ 已连接，正在认证
- **⚪ MANIFEST**（白）→ 完全就绪

## 功能

- **三态指示器** — 实时同步 Galaxy 的 SILENT/LIMINAL/MANIFEST 状态
- **语音输入** — 按住说话，语音转文字后通过 AIP 发送给 Galaxy
- **智能体列表** — 查看当前活跃的 Galaxy 智能体
- **表盘小部件** — 在 Wear OS 表盘划动中查看 Galaxy 状态
- **后台常驻** — 前台服务保持 AIP 连接不中断

## AIP v3 协议

```json
// 认证
{"type":"auth","token":"<jwt>"}

// 语音查询
{"type":"command","id":1,"command":"voice_query","payload":{"text":"开灯","source":"wear_os"}}

// 状态上报（手表 → 服务器）
{"type":"command","id":2,"command":"phase_report","payload":{"phase":"manifest","device":"wear_os"}}

// 服务器推送事件
{"type":"event","event":"phase_change","data":{"phase":"liminal"}}
```

## 项目结构

```
galaxy-wearos/
├── app/
│   ├── build.gradle.kts
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/galaxy/wear/
│       │   ├── GalaxyWearApplication.kt   # 全局状态和 AIP 客户端
│       │   ├── MainActivity.kt            # 主界面
│       │   ├── VoiceActivity.kt           # 语音命令
│       │   ├── data/
│       │   │   └── AIPClient.kt           # WebSocket + 消息协议
│       │   ├── service/
│       │   │   └── GalaxyWearService.kt   # 前台服务
│       │   ├── tile/
│       │   │   └── GalaxyTileService.kt   # 表盘小部件
│       │   └── ui/
│       │       ├── screens/               # 四个页面
│       │       └── theme/                 # 暗色主题
│       └── res/values/
├── build.gradle.kts
├── settings.gradle.kts
└── gradle.properties
```

## License

与 Galaxy 主项目相同。
