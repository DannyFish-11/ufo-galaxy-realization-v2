package com.ufo.galaxy.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * UFO³ Galaxy 极简极客主题系统
 * 
 * 设计理念：
 * - 黑白渐变为主色调
 * - 等宽字体 (Monospace) 营造终端感
 * - 高对比度确保可读性
 * - 科技蓝作为强调色
 * 
 * @author Manus AI
 * @date 2026-01-22
 */

// ============================================
// 颜色定义
// ============================================

/**
 * 极客主题颜色方案
 */
object GeekColors {
    // 主色调 - 黑白渐变
    val Black = Color(0xFF000000)
    val DarkGray = Color(0xFF0A0A0A)
    val MediumGray = Color(0xFF1A1A1A)
    val LightGray = Color(0xFF2A2A2A)
    val White = Color(0xFFFFFFFF)
    
    // 文本颜色
    val TextPrimary = Color(0xFFFFFFFF)
    val TextSecondary = Color(0xFFCCCCCC)
    val TextTertiary = Color(0xFF888888)
    val TextDisabled = Color(0xFF555555)
    
    // 强调色
    val AccentBlue = Color(0xFF00BFFF)      // 科技蓝
    val AccentGreen = Color(0xFF00FF00)     // 矩阵绿
    val AccentRed = Color(0xFFFF4500)       // 警告红
    val AccentYellow = Color(0xFFFFD700)    // 提示黄
    
    // 状态颜色
    val StatusOnline = Color(0xFF00FF00)
    val StatusWorking = Color(0xFF00BFFF)
    val StatusError = Color(0xFFFF4500)
    val StatusOffline = Color(0xFF808080)
    
    // 背景渐变
    val BackgroundStart = Black
    val BackgroundMiddle = DarkGray
    val BackgroundEnd = MediumGray
    
    // 边框和分隔线
    val Border = Color(0xFF333333)
    val Divider = Color(0xFF1A1A1A)
}

/**
 * 暗色主题配色
 */
private val DarkColorScheme = darkColorScheme(
    primary = GeekColors.AccentBlue,
    onPrimary = GeekColors.Black,
    primaryContainer = GeekColors.MediumGray,
    onPrimaryContainer = GeekColors.TextPrimary,
    
    secondary = GeekColors.AccentGreen,
    onSecondary = GeekColors.Black,
    secondaryContainer = GeekColors.LightGray,
    onSecondaryContainer = GeekColors.TextSecondary,
    
    tertiary = GeekColors.AccentYellow,
    onTertiary = GeekColors.Black,
    
    error = GeekColors.AccentRed,
    onError = GeekColors.White,
    
    background = GeekColors.Black,
    onBackground = GeekColors.TextPrimary,
    
    surface = GeekColors.DarkGray,
    onSurface = GeekColors.TextPrimary,
    surfaceVariant = GeekColors.MediumGray,
    onSurfaceVariant = GeekColors.TextSecondary,
    
    outline = GeekColors.Border,
    outlineVariant = GeekColors.Divider
)

// ============================================
// 字体定义
// ============================================

/**
 * 极客主题字体
 */
object GeekTypography {
    val MonoFontFamily = FontFamily.Monospace
    
    val displayLarge = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 57.sp,
        lineHeight = 64.sp,
        letterSpacing = (-0.25).sp
    )
    
    val displayMedium = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 45.sp,
        lineHeight = 52.sp,
        letterSpacing = 0.sp
    )
    
    val displaySmall = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 36.sp,
        lineHeight = 44.sp,
        letterSpacing = 0.sp
    )
    
    val headlineLarge = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 32.sp,
        lineHeight = 40.sp,
        letterSpacing = 0.sp
    )
    
    val headlineMedium = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 28.sp,
        lineHeight = 36.sp,
        letterSpacing = 0.sp
    )
    
    val headlineSmall = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 24.sp,
        lineHeight = 32.sp,
        letterSpacing = 0.sp
    )
    
    val titleLarge = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 22.sp,
        lineHeight = 28.sp,
        letterSpacing = 0.sp
    )
    
    val titleMedium = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        letterSpacing = 0.15.sp
    )
    
    val titleSmall = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.1.sp
    )
    
    val bodyLarge = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        letterSpacing = 0.5.sp
    )
    
    val bodyMedium = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.25.sp
    )
    
    val bodySmall = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.4.sp
    )
    
    val labelLarge = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.1.sp
    )
    
    val labelMedium = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.5.sp
    )
    
    val labelSmall = TextStyle(
        fontFamily = MonoFontFamily,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.5.sp
    )
}

/**
 * Material 3 Typography 适配
 */
private val GeekTypographyScheme = Typography(
    displayLarge = GeekTypography.displayLarge,
    displayMedium = GeekTypography.displayMedium,
    displaySmall = GeekTypography.displaySmall,
    headlineLarge = GeekTypography.headlineLarge,
    headlineMedium = GeekTypography.headlineMedium,
    headlineSmall = GeekTypography.headlineSmall,
    titleLarge = GeekTypography.titleLarge,
    titleMedium = GeekTypography.titleMedium,
    titleSmall = GeekTypography.titleSmall,
    bodyLarge = GeekTypography.bodyLarge,
    bodyMedium = GeekTypography.bodyMedium,
    bodySmall = GeekTypography.bodySmall,
    labelLarge = GeekTypography.labelLarge,
    labelMedium = GeekTypography.labelMedium,
    labelSmall = GeekTypography.labelSmall
)

// ============================================
// 主题组合
// ============================================

/**
 * UFO³ Galaxy 极客主题
 * 
 * 使用方法：
 * ```kotlin
 * @Composable
 * fun MyApp() {
 *     GeekTheme {
 *         // 您的 UI 组件
 *     }
 * }
 * ```
 */
@Composable
fun GeekTheme(
    darkTheme: Boolean = true, // 强制使用暗色主题
    dynamicColor: Boolean = false, // 禁用动态颜色
    content: @Composable () -> Unit
) {
    val colorScheme = DarkColorScheme
    
    MaterialTheme(
        colorScheme = colorScheme,
        typography = GeekTypographyScheme,
        content = content
    )
}

// ============================================
// 扩展函数
// ============================================

/**
 * 获取状态颜色
 */
fun getStatusColor(status: String): Color {
    return when (status.lowercase()) {
        "online", "connected", "idle" -> GeekColors.StatusOnline
        "working", "processing", "busy" -> GeekColors.StatusWorking
        "error", "failed", "disconnected" -> GeekColors.StatusError
        "offline", "unknown" -> GeekColors.StatusOffline
        else -> GeekColors.TextTertiary
    }
}

/**
 * 获取语法高亮颜色
 */
fun getSyntaxColor(type: String): Color {
    return when (type.lowercase()) {
        "user" -> GeekColors.TextPrimary
        "system" -> GeekColors.AccentBlue
        "error" -> GeekColors.AccentRed
        "warning" -> GeekColors.AccentYellow
        "success" -> GeekColors.AccentGreen
        "code" -> GeekColors.AccentBlue
        "comment" -> GeekColors.TextTertiary
        else -> GeekColors.TextSecondary
    }
}
