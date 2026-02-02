# UFO³ Galaxy Android Agent - 部署和配置指南

**版本:** 2.2
**作者:** UFO³ Galaxy Enhancement Team
**日期:** 2026-01-22

---

## 1. 概述

本文档将指导您如何部署和配置 UFO³ Galaxy Android Agent，使其成为您 Galaxy 系统的一个强大移动端节点。

## 2. 准备工作

- 一台 Android 设备 (Android 8.0+)
- Android Studio
- 您的 Windows PC 已部署并运行 Galaxy 系统
- 您的 Windows PC 和 Android 设备已安装并登录 Tailscale

## 3. 构建 APK

1.  **克隆或拉取最新代码**
    ```bash
    git clone https://github.com/DannyFish-11/ufo-galaxy.git
    cd ufo-galaxy
    ```

2.  **打开项目**
    在 Android Studio 中打开 `enhancements/clients/android_client` 目录。

3.  **修改配置**
    打开 `app/src/main/assets/config.properties` 文件。

    将 `galaxy.gateway.url` 的 IP 地址修改为您 **Windows PC 的 Tailscale IP 地址**。
    ```properties
    galaxy.gateway.url=ws://<YOUR_TAILSCALE_IP>:8000/ws/agent
    ```

4.  **构建 APK**
    - 在 Android Studio 中，点击 `Build` -> `Build Bundle(s) / APK(s)` -> `Build APK(s)`。
    - APK 文件将生成在 `app/build/outputs/apk/debug/app-debug.apk`。

## 4. 安装和配置

1.  **安装 APK**
    将 `app-debug.apk` 文件传输到您的 Android 设备并安装。

2.  **授予权限**
    首次打开应用时，请授予所有必要的权限：
    - **悬浮窗权限** (SYSTEM_ALERT_WINDOW)
    - **无障碍服务权限** (Accessibility Service)
    - **麦克风权限** (RECORD_AUDIO)

3.  **启动服务**
    - 在应用主界面，点击 **“启动 Galaxy Agent”** 按钮。
    - 点击 **“启动悬浮窗”** 按钮。

## 5. 验证

1.  **查看 Galaxy Gateway 日志**
    您应该能看到类似以下的日志：
    ```
    INFO:     100.x.x.x:xxxxx - "GET /ws/agent HTTP/1.1" 101 Switching Protocols
    INFO:     Agent 'Android Agent' (ID: xxxxx) connected.
    ```

2.  **使用悬浮窗**
    - 点击悬浮窗上的麦克风按钮，说出指令，例如“你好”。
    - 您应该能在 Galaxy Gateway 的日志中看到接收到的消息。

3.  **测试自主操纵**
    - 在悬浮窗中输入文本指令，例如：`打开微信`。
    - 您的 Android 设备应该会自动打开微信应用。

## 6. 多设备部署

您可以将同一个 APK 安装到多个 Android 设备（手机、平板）。每个设备都会自动注册为 Galaxy 系统的一个独立节点。

您可以在 `config.properties` 文件中为每个设备设置不同的 `agent.name` 以便区分。

---

**部署完成！享受您的多设备自动化系统吧！** 🚀
