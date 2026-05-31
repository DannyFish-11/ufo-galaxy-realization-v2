package com.galaxy.wear.tile

import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.glance.GlanceId
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.provideContent
import androidx.glance.layout.*
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import androidx.wear.tiles.*
import androidx.wear.tiles.material.*
import androidx.wear.protolayout.*
import androidx.wear.protolayout.material.*
import androidx.wear.protolayout.DimensionBuilders.*
import androidx.wear.protolayout.ModifiersBuilders.*
import com.galaxy.wear.GalaxyWearApplication
import com.galaxy.wear.Phase
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

/**
 * GalaxyTileService — Wear OS Tile (glanceable widget)
 *
 * Shows current phase at a glance on the watch face carousel.
 * Updates every 30 seconds or on phase change.
 */
class GalaxyTileService : androidx.wear.tiles.TileService() {

    override fun onTileRequest(
        requestParams: RequestBuilders.TileRequest
    ): ListenableFuture<TileBuilders.Tile> {
        val app = application as GalaxyWearApplication
        val phase = app.phase.value

        return Futures.immediateFuture(
            TileBuilders.Tile.Builder()
                .setResourcesVersion("1")
                .setFreshnessIntervalMillis(30000) // 30s refresh
                .setTimeline(
                    TimelineBuilders.Timeline.Builder()
                        .addTimelineEntry(
                            TimelineBuilders.TimelineEntry.Builder()
                                .setLayout(
                                    LayoutElementBuilders.Layout.Builder()
                                        .setRoot(buildLayout(phase))
                                        .build()
                                )
                                .build()
                        )
                        .build()
                )
                .build()
        )
    }

    override fun onResourcesRequest(
        requestParams: RequestBuilders.ResourcesRequest
    ): ListenableFuture<ResourceBuilders.Resources> {
        return Futures.immediateFuture(
            ResourceBuilders.Resources.Builder()
                .setVersion("1")
                .build()
        )
    }

    private fun buildLayout(phase: Phase): LayoutElementBuilders.LayoutElement {
        val (dotColor, label) = when (phase) {
            Phase.SILENT -> 0xFF333333 to "静默"
            Phase.LIMINAL -> 0xFF808080 to "临界"
            Phase.MANIFEST -> 0xFFE0E0E0 to "显现"
        }

        return LayoutElementBuilders.Box.Builder()
            .setWidth(expand())
            .setHeight(expand())
            .setModifiers(
                ModifiersBuilders.Modifiers.Builder()
                    .setBackground(
                        ModifiersBuilders.Background.Builder()
                            .setColor(argb(0xFF000000))
                            .build()
                    )
                    .build()
            )
            .addContent(
                LayoutElementBuilders.Column.Builder()
                    .setWidth(wrap())
                    .setHeight(wrap())
                    .setHorizontalAlignment(
                        LayoutElementBuilders.HORIZONTAL_ALIGN_CENTER
                    )
                    .addContent(
                        // Phase dot
                        LayoutElementBuilders.Box.Builder()
                            .setWidth(dp(12f))
                            .setHeight(dp(12f))
                            .setModifiers(
                                ModifiersBuilders.Modifiers.Builder()
                                    .setCorner(
                                        ModifiersBuilders.Corner.Builder()
                                            .setRadius(dp(6f))
                                            .build()
                                    )
                                    .setBackground(
                                        ModifiersBuilders.Background.Builder()
                                            .setColor(argb(dotColor.toInt()))
                                            .build()
                                    )
                                    .build()
                            )
                            .build()
                    )
                    .addContent(
                        LayoutElementBuilders.Spacer.Builder()
                            .setHeight(dp(4f))
                            .build()
                    )
                    .addContent(
                        Text.Builder(this, label)
                            .setTypography(Typography.TYPOGRAPHY_CAPTION1)
                            .setColor(argb(dotColor.toInt()))
                            .build()
                    )
                    .addContent(
                        LayoutElementBuilders.Spacer.Builder()
                            .setHeight(dp(2f))
                            .build()
                    )
                    .addContent(
                        Text.Builder(this, "GALAXY")
                            .setTypography(Typography.TYPOGRAPHY_CAPTION2)
                            .setColor(argb(0xFF555555))
                            .build()
                    )
                    .build()
            )
            .build()
    }
}

/** Helper to create ARGB color */
private fun argb(color: Int): ColorBuilders.Color {
    return ColorBuilders.Color.Builder().setArgb(color).build()
}
