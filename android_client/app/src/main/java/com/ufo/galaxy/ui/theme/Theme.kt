package com.ufo.galaxy.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

// 书法卷轴风格配色
private val LightColorScheme = lightColorScheme(
    primary = Color(0xFF2C2C2C),           // 墨色
    onPrimary = Color.White,
    primaryContainer = Color(0xFFF5F0E6),   // 宣纸色
    onPrimaryContainer = Color(0xFF2C2C2C),
    secondary = Color(0xFF8B4513),          // 朱砂色
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFFAE6D5),
    onSecondaryContainer = Color(0xFF5D2E0A),
    tertiary = Color(0xFF4A6741),           // 青绿色
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFCCE8C5),
    onTertiaryContainer = Color(0xFF0F2D0A),
    background = Color(0xFFFFFBF8),         // 米白色
    onBackground = Color(0xFF1C1B1F),
    surface = Color(0xFFFFFBF8),
    onSurface = Color(0xFF1C1B1F),
    surfaceVariant = Color(0xFFF5F0E6),
    onSurfaceVariant = Color(0xFF49454F),
    error = Color(0xFFBA1A1A),
    onError = Color.White,
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    outline = Color(0xFF79747E),
    outlineVariant = Color(0xFFCAC4D0)
)

private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFFD4C5B0),            // 淡墨色
    onPrimary = Color(0xFF1C1C1C),
    primaryContainer = Color(0xFF3D3D3D),
    onPrimaryContainer = Color(0xFFE8E0D5),
    secondary = Color(0xFFFFB68A),          // 淡朱砂色
    onSecondary = Color(0xFF4A2800),
    secondaryContainer = Color(0xFF6A3C00),
    onSecondaryContainer = Color(0xFFFFDCC5),
    tertiary = Color(0xFFB0CFAA),           // 淡青绿色
    onTertiary = Color(0xFF1D361A),
    tertiaryContainer = Color(0xFF344D2F),
    onTertiaryContainer = Color(0xFFCCEBC5),
    background = Color(0xFF1C1B1F),
    onBackground = Color(0xFFE6E1E5),
    surface = Color(0xFF1C1B1F),
    onSurface = Color(0xFFE6E1E5),
    surfaceVariant = Color(0xFF49454F),
    onSurfaceVariant = Color(0xFFCAC4D0),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    outline = Color(0xFF938F99),
    outlineVariant = Color(0xFF49454F)
)

/**
 * UFO Galaxy 主题
 */
@Composable
fun UFOGalaxyTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context)
            else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }
    
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colorScheme.background.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !darkTheme
        }
    }
    
    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
