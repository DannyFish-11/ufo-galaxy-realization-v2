package com.ufo.galaxy.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * UFO³ Galaxy 极客主题系统 - 高质感版本
 * 
 * 在原有基础上增强：
 * - 更丰富的色彩层次
 * - 更精致的渐变定义
 * - 更多的语义化颜色
 * - 支持动态主题切换
 * 
 * @author Manus AI
 * @date 2026-01-22
 */

/**
 * 高质感极客颜色方案
 */
object GeekColorsPremium {
    // ============================================
    // 基础色调 - 黑白灰渐变
    // ============================================
    val PureBlack = Color(0xFF000000)
    val DeepBlack = Color(0xFF050505)
    val DarkestGray = Color(0xFF0A0A0A)
    val DarkerGray = Color(0xFF101010)
    val DarkGray = Color(0xFF1A1A1A)
    val MediumGray = Color(0xFF2A2A2A)
    val LightGray = Color(0xFF3A3A3A)
    val LighterGray = Color(0xFF4A4A4A)
    val PureWhite = Color(0xFFFFFFFF)
    
    // ============================================
    // 文本颜色 - 多层次
    // ============================================
    val TextPrimary = Color(0xFFFFFFFF)          // 主要文本
    val TextSecondary = Color(0xFFE0E0E0)        // 次要文本
    val TextTertiary = Color(0xFFC0C0C0)         // 三级文本
    val TextQuaternary = Color(0xFFA0A0A0)       // 四级文本
    val TextDisabled = Color(0xFF808080)         // 禁用文本
    val TextHint = Color(0xFF606060)             // 提示文本
    val TextPlaceholder = Color(0xFF505050)      // 占位符文本
    
    // ============================================
    // 强调色 - 科技感配色
    // ============================================
    val CyberBlue = Color(0xFF00BFFF)            // 赛博蓝
    val CyberBlueDark = Color(0xFF0080FF)        // 深赛博蓝
    val CyberBlueLight = Color(0xFF00FFFF)       // 浅赛博蓝
    
    val MatrixGreen = Color(0xFF00FF00)          // 矩阵绿
    val MatrixGreenDark = Color(0xFF00CC00)      // 深矩阵绿
    val MatrixGreenLight = Color(0xFF00FF80)     // 浅矩阵绿
    
    val NeonPink = Color(0xFFFF1493)             // 霓虹粉
    val NeonPinkDark = Color(0xFFCC0066)         // 深霓虹粉
    val NeonPinkLight = Color(0xFFFF69B4)        // 浅霓虹粉
    
    val WarningRed = Color(0xFFFF4500)           // 警告红
    val WarningRedDark = Color(0xFFCC3300)       // 深警告红
    val WarningRedLight = Color(0xFFFF6347)      // 浅警告红
    
    val CautionYellow = Color(0xFFFFD700)        // 警示黄
    val CautionYellowDark = Color(0xFFCCAA00)    // 深警示黄
    val CautionYellowLight = Color(0xFFFFE44D)   // 浅警示黄
    
    val PurpleHaze = Color(0xFF9370DB)           // 紫霾
    val PurpleHazeDark = Color(0xFF7B68EE)       // 深紫霾
    val PurpleHazeLight = Color(0xFFBA55D3)      // 浅紫霾
    
    // ============================================
    // 状态颜色 - 系统反馈
    // ============================================
    val StatusOnline = MatrixGreen
    val StatusIdle = CyberBlue
    val StatusWorking = CyberBlueDark
    val StatusSuccess = MatrixGreenLight
    val StatusWarning = CautionYellow
    val StatusError = WarningRed
    val StatusOffline = Color(0xFF808080)
    val StatusUnknown = Color(0xFF606060)
    
    // ============================================
    // 背景渐变 - 多层次景深
    // ============================================
    val BackgroundGradientStart = PureBlack
    val BackgroundGradientMid1 = DeepBlack
    val BackgroundGradientMid2 = DarkestGray
    val BackgroundGradientMid3 = DarkerGray
    val BackgroundGradientEnd = DarkGray
    
    // ============================================
    // 表面颜色 - 卡片和容器
    // ============================================
    val SurfacePrimary = DarkestGray
    val SurfaceSecondary = DarkerGray
    val SurfaceTertiary = DarkGray
    val SurfaceElevated = MediumGray
    
    // ============================================
    // 边框和分隔线
    // ============================================
    val BorderPrimary = Color(0xFF333333)
    val BorderSecondary = Color(0xFF2A2A2A)
    val BorderHighlight = Color(0xFF4A4A4A)
    val Divider = Color(0xFF1A1A1A)
    val DividerLight = Color(0xFF2A2A2A)
    
    // ============================================
    // 阴影和辉光
    // ============================================
    val ShadowLight = Color(0x20000000)
    val ShadowMedium = Color(0x40000000)
    val ShadowHeavy = Color(0x80000000)
    
    val GlowCyberBlue = Color(0x40 00BFFF)
    val GlowMatrixGreen = Color(0x4000FF00)
    val GlowWarningRed = Color(0x40FF4500)
    
    // ============================================
    // 覆盖层
    // ============================================
    val OverlayLight = Color(0x10FFFFFF)
    val OverlayMedium = Color(0x20FFFFFF)
    val OverlayHeavy = Color(0x40FFFFFF)
    
    val ScrimLight = Color(0x40000000)
    val ScrimMedium = Color(0x80000000)
    val ScrimHeavy = Color(0xCC000000)
}

/**
 * 暗色主题配色 - 高质感版本
 */
private val DarkColorSchemePremium = darkColorScheme(
    primary = GeekColorsPremium.CyberBlue,
    onPrimary = GeekColorsPremium.PureBlack,
    primaryContainer = GeekColorsPremium.DarkGray,
    onPrimaryContainer = GeekColorsPremium.TextPrimary,
    
    secondary = GeekColorsPremium.MatrixGreen,
    onSecondary = GeekColorsPremium.PureBlack,
    secondaryContainer = GeekColorsPremium.MediumGray,
    onSecondaryContainer = GeekColorsPremium.TextSecondary,
    
    tertiary = GeekColorsPremium.PurpleHaze,
    onTertiary = GeekColorsPremium.PureBlack,
    tertiaryContainer = GeekColorsPremium.LightGray,
    onTertiaryContainer = GeekColorsPremium.TextTertiary,
    
    error = GeekColorsPremium.WarningRed,
    onError = GeekColorsPremium.PureWhite,
    errorContainer = GeekColorsPremium.WarningRedDark,
    onErrorContainer = GeekColorsPremium.WarningRedLight,
    
    background = GeekColorsPremium.PureBlack,
    onBackground = GeekColorsPremium.TextPrimary,
    
    surface = GeekColorsPremium.SurfacePrimary,
    onSurface = GeekColorsPremium.TextPrimary,
    surfaceVariant = GeekColorsPremium.SurfaceSecondary,
    onSurfaceVariant = GeekColorsPremium.TextSecondary,
    surfaceTint = GeekColorsPremium.CyberBlue,
    
    inverseSurface = GeekColorsPremium.PureWhite,
    inverseOnSurface = GeekColorsPremium.PureBlack,
    inversePrimary = GeekColorsPremium.CyberBlueDark,
    
    outline = GeekColorsPremium.BorderPrimary,
    outlineVariant = GeekColorsPremium.BorderSecondary,
    
    scrim = GeekColorsPremium.ScrimMedium
)

/**
 * 高质感极客主题
 */
@Composable
fun GeekThemePremium(
    darkTheme: Boolean = true,
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    val colorScheme = DarkColorSchemePremium
    
    MaterialTheme(
        colorScheme = colorScheme,
        typography = GeekTypographyScheme,
        content = content
    )
}

/**
 * 扩展函数 - 获取状态颜色（高质感版本）
 */
fun getStatusColorPremium(status: String): Color {
    return when (status.lowercase()) {
        "online", "connected" -> GeekColorsPremium.StatusOnline
        "idle" -> GeekColorsPremium.StatusIdle
        "working", "processing", "busy" -> GeekColorsPremium.StatusWorking
        "success", "completed", "done" -> GeekColorsPremium.StatusSuccess
        "warning", "caution" -> GeekColorsPremium.StatusWarning
        "error", "failed" -> GeekColorsPremium.StatusError
        "offline", "disconnected" -> GeekColorsPremium.StatusOffline
        else -> GeekColorsPremium.StatusUnknown
    }
}

/**
 * 扩展函数 - 获取语法高亮颜色（高质感版本）
 */
fun getSyntaxColorPremium(type: String): Color {
    return when (type.lowercase()) {
        "user", "input" -> GeekColorsPremium.TextPrimary
        "system", "info" -> GeekColorsPremium.CyberBlue
        "assistant", "ai" -> GeekColorsPremium.CyberBlueLight
        "error", "exception" -> GeekColorsPremium.WarningRed
        "warning", "alert" -> GeekColorsPremium.CautionYellow
        "success", "ok" -> GeekColorsPremium.MatrixGreen
        "code", "command" -> GeekColorsPremium.PurpleHaze
        "comment", "note" -> GeekColorsPremium.TextTertiary
        "keyword" -> GeekColorsPremium.NeonPink
        "string" -> GeekColorsPremium.MatrixGreenLight
        "number" -> GeekColorsPremium.CautionYellowLight
        else -> GeekColorsPremium.TextSecondary
    }
}

/**
 * 扩展函数 - 获取辉光颜色
 */
fun getGlowColor(baseColor: Color, intensity: Float = 0.5f): Color {
    return baseColor.copy(alpha = intensity)
}
