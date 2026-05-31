# Android 兼容性文档

> **版本**: v3.0.0 | **Android App**: 2.0.1 | **协议**: AIP v3.0 | **更新**: 2026-05-31

---

## 仓库

| 仓库 | 地址 | 职责 |
|------|------|------|
| **服务端** (本仓库) | `DannyFish-11/ufo-galaxy-realization` | Galaxy Gateway + 桌面覆盖层 |
| **Android 客户端** | `DannyFish-11/ufo-galaxy-android` | Android APK |

克隆 Android 客户端：
```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-android.git
cd ufo-galaxy-android
```

---

## Android 端概况

| 项目 | 数据 |
|------|------|
| 代码规模 | ~28.3万行 Kotlin，200+ 源文件 |
| 技术栈 | Kotlin 1.9.21 + Jetpack Compose + llama.cpp JNI + NCNN |
| 最低系统 | Android 8.0 (API 26) |
| 目标 SDK | API 34 |
| 应用版本 | 2.0.1 (versionCode 201) |
| 本地模型 | MobileVLM (llama.cpp) + SeeClick (NCNN) |

### 双模式架构

Android 端支持两种运行模式：

**1. Cross-device（默认）**
- 通过 WebSocket 连接到 Galaxy Gateway
- 参与分布式任务网络
- 云端模型 + 本地 grounding

**2. Local-only（备选）**
- 完全本地推理和 UI 自动化
- MobileVLM 规划 + SeeClick 视觉定位
- 无需网络连接

---

## 克隆到使用完整步骤

### 前提条件

| 依赖 | 版本 |
|------|------|
| Android Studio | Arctic Fox (2020.3.1)+ |
| JDK | 17+ |
| Android SDK | API 26+ |
| Kotlin | 1.9.21 |
| Gradle | 8.4 |

### 1. 克隆两个仓库

```bash
# 服务端（本仓库）
git clone https://github.com/DannyFish-11/ufo-galaxy-realization.git
cd ufo-galaxy-realization

# Android 客户端（同级目录）
git clone https://github.com/DannyFish-11/ufo-galaxy-android.git
```

### 2. 启动服务端 Gateway

```bash
cd ufo-galaxy-realization
python main.py
# 或
python launch_desktop.py --backend
```

确保 Gateway 在 `ws://<host>:8765` 可访问。

### 3. 配置 Android 端连接

**推荐方式 — 应用内设置（无需重新打包）：**

打开 App → ⚙ 设置 → **Network & Diagnostics**：

| 字段 | 示例值 |
|------|--------|
| Host / IP | `192.168.1.100` 或 Tailscale IP |
| Port | `8765` |
| Use TLS | 开发关闭，生产开启 |
| Device ID | 留空使用系统默认值 |

点击 **Save & Reconnect**。

**备选方式 — 修改 `config.properties`：**

```bash
cd ufo-galaxy-android
# 编辑 app/src/main/assets/config.properties
galaxy_gateway_url=ws://192.168.1.100:8765
rest_base_url=http://192.168.1.100:8765
cross_device_enabled=true
```

**配置优先级（高 → 低）：**
1. 应用内设置 (SharedPreferences) — 运行时生效
2. `assets/config.properties` — 打包时配置
3. `app/build.gradle` BuildConfig — 编译时默认值

### 4. 构建 APK

```bash
cd ufo-galaxy-android
chmod +x build_apk.sh
./build_apk.sh
```

输出：`app/build/outputs/apk/debug/app-debug.apk`

### 5. 安装到设备

```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

### 6. 首次启动权限授予

安装后需要授予以下权限：

| 权限 | 用途 | 必须 |
|------|------|------|
| **无障碍服务** | 硬件按键监听、UI 自动化 | ✅ 必需 |
| **悬浮窗** | 灵动岛显示 | ✅ 必需 |
| **麦克风** | 语音输入 | ⚠️ 建议 |
| **相机** | 视觉 grounding | ⚠️ 建议 |
| **通知** | 状态通知 | ⚠️ 建议 |

授予步骤：
1. 打开应用
2. 跟随首次启动引导 (`FirstTimeSetupActivity`)
3. 在系统设置中启用 **UFO Galaxy 无障碍服务**
4. 允许 **悬浮窗权限**

---

## WebSocket 端点

Android 通过 AIP v3.0 协议与服务端通信。

| 端点 | 用途 |
|------|------|
| `ws://<host>:8765/ws/android/{device_id}` | **主路径**，推荐 |
| `ws://<host>:8765/ws/{device_id}` | 通用设备路径 |
| `ws://<host>:8765/ws` | 自动分配 device_id |
| `ws://<host>:8765/ws/device/{device_id}` | 兼容别名 |
| `ws://<host>:8765/ws/ufo3/{device_id}` | UFO3 遗留路径 |

**连接示例：**
```
ws://192.168.1.100:8765/ws/android/my-device-001
```

---

## 本地模型（Local-only 模式）

Android 端支持完全本地推理，无需连接 Gateway。

### 模型架构

| 组件 | 模型 | 框架 | 功能 |
|------|------|------|------|
| Planner | MobileVLM | llama.cpp JNI | 任务规划、意图理解 |
| Grounding | SeeClick | NCNN Vulkan | 屏幕元素视觉定位 |

### 模型下载

模型通过 `ModelProvisioningPipeline` 自动下载：
- MobileVLM GGUF 格式 (~2-4GB)
- SeeClick NCNN 模型 (~500MB)
- 首次启动时自动触发下载
- 支持断点续传

### 本地执行流程

```
用户输入 (语音/文字)
  ↓
InputRouter → GoalNormalizer
  ↓
MobileVLM (llama.cpp) → 生成操作计划
  ↓
SeeClick (NCNN) → 屏幕元素定位
  ↓
EdgeExecutor → 执行 UI 操作
  ↓
PostActionObserver → 验证结果
  ↓
LoopController → 循环或完成
```

---

## 故障排除

### 连接问题

| 症状 | 原因 | 解决 |
|------|------|------|
| WebSocket 连接失败 | Gateway 未启动 | 启动 `python main.py` |
| 连接超时 | IP/端口错误 | 检查 `config.properties` 中的 IP |
| TLS 握手失败 | 证书问题 | 开发环境关闭 TLS |
| 设备注册失败 | 防火墙拦截 | 检查 8765 端口开放 |

### 本地模型问题

| 症状 | 原因 | 解决 |
|------|------|------|
| 模型下载失败 | 网络问题 | 检查网络，支持断点续传 |
| 推理速度慢 | 设备性能不足 | 降低 `planner_max_tokens` |
| Grounding 失败 | 截图分辨率过高 | 降低 `scaled_max_edge` |

### 构建问题

| 症状 | 原因 | 解决 |
|------|------|------|
| Gradle 下载失败 | 网络问题 | 配置国内镜像 |
| NDK 缺失 | 未安装 NDK | `sdkmanager "ndk;25.1.8937393"` |
| 签名失败 | keystore 不存在 | 使用 debug 构建或配置签名 |

---

## 相关文档

| 文档 | 位置 | 内容 |
|------|------|------|
| 架构总览 | `docs/architecture.md` | 系统架构、组件索引 |
| 执行流程 | `docs/execution-flows.md` | 本地/跨设备执行流程 |
| 维护指南 | `docs/maintainer-guide.md` | 配置模型、构建指导 |
| 联合设置 | `docs/DUAL_REPO_SETUP.md` | 双仓库联合启动指南 |
| 协议对齐 | `docs/ANDROID_PROTOCOL_ALIGNMENT.md` | AIP v3 协议规范 |
| 系统分析 | `docs/SYSTEM_ANALYSIS_ZH.md` | 中文系统分析 |

---

## 附录: AndroidManifest 权限

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.VIBRATE" />
<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
<uses-permission android:name="android.permission.BLUETOOTH" />
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
<uses-permission android:name="android.permission.BLUETOOTH_SCAN" />
<uses-permission android:name="android.permission.NFC" />
```

---

*最后更新: 2026-05-31 | 服务端: v10.0 | Android: 2.0.1*
