#!/bin/bash
# UFO³ Galaxy Android 客户端自动配置构建脚本

set -e

echo "========================================"
echo "   UFO³ Galaxy Android 自动构建"
echo "========================================"
echo ""

# 获取 Windows PC 的 Tailscale IP
echo "请输入 Windows PC 的 Tailscale IP 地址:"
read -r WINDOWS_IP

if [ -z "$WINDOWS_IP" ]; then
    echo "[错误] IP 地址不能为空"
    exit 1
fi

echo ""
echo "请输入设备 ID (例如: android-xiaomi-14):"
read -r DEVICE_ID

if [ -z "$DEVICE_ID" ]; then
    DEVICE_ID="android-device"
    echo "[提示] 使用默认设备 ID: $DEVICE_ID"
fi

# 构建完整的 WebSocket URL
WS_URL="ws://${WINDOWS_IP}:8050/ws/ufo3/${DEVICE_ID}"

echo ""
echo "配置信息:"
echo "  Windows IP: $WINDOWS_IP"
echo "  设备 ID: $DEVICE_ID"
echo "  WebSocket URL: $WS_URL"
echo ""
echo "按任意键继续，或 Ctrl+C 取消..."
read -n 1 -s

# 备份原始文件
AIPCLIENT_FILE="app/src/main/java/com/ufo/galaxy/client/AIPClient.kt"
if [ ! -f "${AIPCLIENT_FILE}.backup" ]; then
    cp "$AIPCLIENT_FILE" "${AIPCLIENT_FILE}.backup"
    echo "[✓] 已备份原始配置文件"
fi

# 修改配置
echo "[1/3] 正在修改配置..."
sed -i.tmp "s|private val NODE50_URL = .*|private val NODE50_URL = \"$WS_URL\"|g" "$AIPCLIENT_FILE"
rm -f "${AIPCLIENT_FILE}.tmp"
echo "[✓] 配置已更新"

# 清理旧的构建
echo ""
echo "[2/3] 清理旧的构建..."
./gradlew clean
echo "[✓] 清理完成"

# 构建 APK
echo ""
echo "[3/3] 正在构建 APK..."
echo "这可能需要几分钟，请耐心等待..."
./gradlew assembleDebug

# 查找生成的 APK
APK_PATH="app/build/outputs/apk/debug/app-debug.apk"
if [ -f "$APK_PATH" ]; then
    # 重命名 APK
    NEW_APK_NAME="UFO3_Galaxy_${DEVICE_ID}_$(date +%Y%m%d).apk"
    cp "$APK_PATH" "$NEW_APK_NAME"
    
    echo ""
    echo "========================================"
    echo "   构建成功！"
    echo "========================================"
    echo ""
    echo "APK 文件: $NEW_APK_NAME"
    echo "文件大小: $(du -h "$NEW_APK_NAME" | cut -f1)"
    echo ""
    echo "请将此 APK 传输到您的 Android 设备并安装"
    echo ""
else
    echo ""
    echo "[错误] 构建失败，未找到 APK 文件"
    exit 1
fi

# 恢复原始配置（可选）
echo "是否恢复原始配置文件? (y/n)"
read -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    mv "${AIPCLIENT_FILE}.backup" "$AIPCLIENT_FILE"
    echo "[✓] 已恢复原始配置"
fi
