#!/bin/bash
# UFO Galaxy Android - APK 打包脚本

set -e

echo "=========================================="
echo "  UFO Galaxy Android APK 打包"
echo "=========================================="
echo ""

# 检查 Java 环境
if ! command -v java &> /dev/null; then
    echo "❌ 错误: 未找到 Java，请先安装 JDK 17+"
    exit 1
fi

JAVA_VERSION=$(java -version 2>&1 | head -n 1 | cut -d'"' -f2 | cut -d'.' -f1)
echo "✅ Java 版本: $JAVA_VERSION"

# 检查 Android SDK
if [ -z "$ANDROID_HOME" ]; then
    echo "⚠️  警告: ANDROID_HOME 未设置"
    echo "   请设置 ANDROID_HOME 环境变量指向 Android SDK 目录"
    echo "   例如: export ANDROID_HOME=~/Android/Sdk"
fi

# 进入项目目录
cd "$(dirname "$0")"
PROJECT_DIR=$(pwd)
echo "📁 项目目录: $PROJECT_DIR"

# 清理旧构建
echo ""
echo "🧹 清理旧构建..."
./gradlew clean 2>/dev/null || {
    echo "   首次运行，下载 Gradle..."
}

# 构建 Debug APK
echo ""
echo "🔨 构建 Debug APK..."
./gradlew assembleDebug

# 检查输出
DEBUG_APK="$PROJECT_DIR/app/build/outputs/apk/debug/app-debug.apk"
if [ -f "$DEBUG_APK" ]; then
    echo ""
    echo "✅ Debug APK 构建成功!"
    echo "   路径: $DEBUG_APK"
    echo "   大小: $(du -h "$DEBUG_APK" | cut -f1)"
else
    echo "❌ Debug APK 构建失败"
    exit 1
fi

# 询问是否构建 Release
echo ""
read -p "是否构建 Release APK? (y/n): " BUILD_RELEASE

if [ "$BUILD_RELEASE" = "y" ] || [ "$BUILD_RELEASE" = "Y" ]; then
    echo ""
    echo "🔨 构建 Release APK..."
    
    # 检查签名配置
    if [ ! -f "$PROJECT_DIR/keystore.jks" ]; then
        echo "⚠️  未找到签名密钥，生成临时密钥..."
        keytool -genkey -v -keystore "$PROJECT_DIR/keystore.jks" \
            -alias ufo_galaxy \
            -keyalg RSA -keysize 2048 -validity 10000 \
            -storepass ufogalaxy123 -keypass ufogalaxy123 \
            -dname "CN=UFO Galaxy, OU=Development, O=UFO, L=Beijing, ST=Beijing, C=CN"
    fi
    
    ./gradlew assembleRelease
    
    RELEASE_APK="$PROJECT_DIR/app/build/outputs/apk/release/app-release.apk"
    if [ -f "$RELEASE_APK" ]; then
        echo ""
        echo "✅ Release APK 构建成功!"
        echo "   路径: $RELEASE_APK"
        echo "   大小: $(du -h "$RELEASE_APK" | cut -f1)"
    fi
fi

echo ""
echo "=========================================="
echo "  构建完成!"
echo "=========================================="
