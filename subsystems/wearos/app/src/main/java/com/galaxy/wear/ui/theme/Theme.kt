package com.galaxy.wear.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material.Colors
import androidx.wear.compose.material.MaterialTheme

/**
 * Galaxy Wear OS Theme
 *
 * Dark monochrome palette matching Desktop/Android v38:
 *   SILENT  → #000000
 *   LIMINAL → #808080
 *   MANIFEST → #E0E0E0
 */
private val GalaxyColorPalette = Colors(
    primary = Color(0xFFE0E0E0),           // White (MANIFEST)
    primaryVariant = Color(0xFF808080),     // Gray (LIMINAL)
    secondary = Color(0xFF808080),
    background = Color.Black,
    surface = Color(0xFF111111),
    error = Color(0xFFCF6679),
    onPrimary = Color.Black,
    onSecondary = Color.Black,
    onBackground = Color(0xFFE0E0E0),
    onSurface = Color(0xFFE0E0E0),
    onError = Color.Black,
)

@Composable
fun GalaxyWearTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colors = GalaxyColorPalette,
        typography = GalaxyTypography,
        content = content
    )
}
