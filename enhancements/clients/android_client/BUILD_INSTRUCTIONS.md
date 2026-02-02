# UFO³ Galaxy Android 客户端构建说明

## 快速构建

### 方法 1: 使用 Android Studio（推荐）

1. **打开项目**
   - 启动 Android Studio
   - 选择 "Open an Existing Project"
   - 导航到 `ufo-galaxy-android` 目录

2. **配置连接地址**
   - 打开 `app/src/main/java/com/ufo/galaxy/client/AIPClient.kt`
   - 修改 `NODE50_URL` 为您的 Windows PC 的 Tailscale IP:
     ```kotlin
     private val NODE50_URL = "ws://100.123.215.126:8050/ws/ufo3/android-device"
     ```
   - 将 `100.123.215.126` 替换为您实际的 IP 地址

3. **构建 APK**
   - 点击菜单: **Build** → **Build Bundle(s) / APK(s)** → **Build APK(s)**
   - 等待构建完成（首次构建可能需要 5-10 分钟）
   - 构建完成后，点击通知中的 "locate" 找到 APK 文件

4. **安装到设备**
   - 将 APK 传输到您的 Android 设备
   - 在设备上点击 APK 文件进行安装
   - 如果提示"未知来源"，请在设置中允许安装

### 方法 2: 使用命令行构建

```bash
cd ufo-galaxy-android

# 首次构建需要下载依赖
./gradlew assembleDebug

# APK 位置
# app/build/outputs/apk/debug/app-debug.apk
```

## 配置说明

### 1. 修改连接地址

在 `app/src/main/java/com/ufo/galaxy/client/AIPClient.kt` 中:

```kotlin
// 将此 IP 改为您的 Windows PC 的 Tailscale IP
private val NODE50_URL = "ws://YOUR_WINDOWS_IP:8050/ws/ufo3/YOUR_DEVICE_ID"
```

**如何获取 Windows IP:**
- 在 Windows PC 上打开 PowerShell
- 运行: `tailscale ip -4`
- 复制显示的 IP 地址（例如: 100.123.215.126）

### 2. 修改设备 ID（可选）

如果您有多个 Android 设备，建议为每个设备设置不同的 ID:

```kotlin
private val NODE50_URL = "ws://100.123.215.126:8050/ws/ufo3/android-xiaomi-14"
// 或
private val NODE50_URL = "ws://100.123.215.126:8050/ws/ufo3/android-oppo-tablet"
```

## 权限说明

应用需要以下权限:

1. **显示在其他应用上层** (悬浮窗)
   - 首次启动时会自动请求
   - 或在 设置 → 应用 → UFO³ Galaxy → 权限 中手动开启

2. **麦克风** (语音输入)
   - 点击悬浮窗时会请求
   - 或在应用权限设置中手动开启

3. **网络访问**
   - 自动授予，无需手动操作

## 故障排除

### 构建失败

**问题**: Gradle 同步失败
**解决**: 
```bash
# 清理构建缓存
./gradlew clean

# 重新构建
./gradlew assembleDebug
```

### 无法连接到 Node 50

**问题**: 应用显示"连接失败"
**检查清单**:
1. ✓ Windows PC 上的 Podman 容器是否正在运行?
2. ✓ Tailscale 在 Android 设备上是否已登录?
3. ✓ Android 设备和 Windows PC 是否在同一个 Tailscale 网络中?
4. ✓ `NODE50_URL` 中的 IP 地址是否正确?

**测试连接**:
```bash
# 在 Android 设备的 Termux 中测试
curl http://100.123.215.126:8050/health
```

### 悬浮窗不显示

**问题**: 安装后看不到悬浮窗
**解决**:
1. 打开 设置 → 应用 → UFO³ Galaxy
2. 找到 "显示在其他应用上层" 权限
3. 开启此权限
4. 重启应用

## 预配置版本

如果您需要为多个设备快速部署，可以使用以下脚本自动生成预配置的 APK:

```bash
# 编辑 build_configured_apk.sh 中的 IP 地址
nano build_configured_apk.sh

# 运行构建脚本
./build_configured_apk.sh
```

这将生成一个已配置好连接地址的 APK，可以直接分发给其他设备使用。
