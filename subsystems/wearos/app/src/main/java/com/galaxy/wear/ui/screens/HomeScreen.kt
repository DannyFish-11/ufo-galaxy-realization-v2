package com.galaxy.wear.ui.screens

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.*
import com.galaxy.wear.Phase

/**
 * HomeScreen — Watch face-inspired main screen
 *
 * Layout (centered, vertical):
 *   GALAXY title
 *   ┌─────────────┐
 *   │  ●  ●  ●    │  ← Phase dots (black/gray/white)
 *   └─────────────┘
 *   [Agent] [Voice] [Settings] ← Action chips
 *   SILENT / LIMINAL / MANIFEST label
 */
@Composable
fun HomeScreen(
    phase: Phase,
    onAgents: () -> Unit,
    onVoice: () -> Unit,
    onSettings: () -> Unit,
) {
    Scaffold(
        vignette = { Vignette(vignettePosition = VignettePosition.TopAndBottom) },
        positionIndicator = { PositionIndicator(scalingLazyListState = rememberScalingLazyListState()) }
    ) {
        ScalingLazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black),
            horizontalAlignment = Alignment.CenterHorizontally,
            state = rememberScalingLazyListState(initialCenterItemIndex = 1),
        ) {
            // GALAXY Title
            item {
                Text(
                    text = "GALAXY",
                    style = MaterialTheme.typography.display3,
                    color = Color(0xFFE0E0E0),
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)
                )
            }

            // Phase indicator dots (the three dots)
            item {
                PhaseIndicatorDots(
                    phase = phase,
                    modifier = Modifier.padding(vertical = 12.dp)
                )
            }

            // Phase status text
            item {
                AnimatedVisibility(
                    visible = true,
                    enter = fadeIn() + slideInVertically(initialOffsetY = { it / 4 }),
                    exit = fadeOut()
                ) {
                    val (label, color) = when (phase) {
                        Phase.SILENT -> Pair("静默", Color(0xFF333333))
                        Phase.LIMINAL -> Pair("临界", Color(0xFF808080))
                        Phase.MANIFEST -> Pair("显现", Color(0xFFE0E0E0))
                    }
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            text = label,
                            style = MaterialTheme.typography.title2,
                            color = color,
                            textAlign = TextAlign.Center
                        )
                        Text(
                            text = phase.name.uppercase(),
                            style = MaterialTheme.typography.caption3,
                            color = color.copy(alpha = 0.6f),
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(top = 2.dp)
                        )
                    }
                }
            }

            // Action chips row
            item {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    modifier = Modifier.padding(top = 16.dp, bottom = 8.dp)
                ) {
                    CompactChip(
                        onClick = onAgents,
                        label = { Text("智能体", style = MaterialTheme.typography.caption2) },
                        icon = {
                            Icon(
                                imageVector = androidx.compose.material.icons.Icons.Default.Android,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp)
                            )
                        },
                        colors = ChipDefaults.primaryChipColors()
                    )
                    CompactChip(
                        onClick = onVoice,
                        label = { Text("语音", style = MaterialTheme.typography.caption2) },
                        icon = {
                            Icon(
                                imageVector = androidx.compose.material.icons.Icons.Default.Mic,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp)
                            )
                        },
                        colors = ChipDefaults.secondaryChipColors()
                    )
                    CompactChip(
                        onClick = onSettings,
                        label = { Text("设置", style = MaterialTheme.typography.caption2) },
                        icon = {
                            Icon(
                                imageVector = androidx.compose.material.icons.Icons.Default.Settings,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp)
                            )
                        },
                        colors = ChipDefaults.secondaryChipColors()
                    )
                }
            }
        }
    }
}

/**
 * Three-phase dot indicator — real-time animated
 */
@Composable
fun PhaseIndicatorDots(phase: Phase, modifier: Modifier = Modifier) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
        modifier = modifier
            .background(Color(0xFF111111), CircleShape)
            .padding(horizontal = 16.dp, vertical = 10.dp)
    ) {
        Phase.values().forEach { p ->
            val isActive = phase == p
            val targetScale = if (isActive) 1.25f else 0.8f
            val targetAlpha = if (isActive) 1.0f else 0.2f

            val scale by animateFloatAsState(
                targetValue = targetScale,
                animationSpec = spring(stiffness = 300f, damping = 15f),
                label = "dot_scale_$p"
            )

            val color = when (p) {
                Phase.SILENT -> if (isActive) Color(0xFF333333) else Color(0xFF1A1A1A)
                Phase.LIMINAL -> if (isActive) Color(0xFF808080) else Color(0xFF333333)
                Phase.MANIFEST -> if (isActive) Color(0xFFE0E0E0) else Color(0xFF444444)
            }

            // LIMINAL pulse animation
            val liminalPulse by rememberInfiniteTransition(label = "liminal_pulse").animateFloat(
                initialValue = 1f,
                targetValue = if (isActive && p == Phase.LIMINAL) 1.6f else 1f,
                animationSpec = infiniteRepeatable(
                    animation = tween(900, easing = EaseInOutCubic),
                    repeatMode = RepeatMode.Reverse
                ),
                label = "liminal_pulse"
            )

            val liminalAlpha by rememberInfiniteTransition(label = "liminal_alpha").animateFloat(
                initialValue = if (isActive && p == Phase.LIMINAL) 0.6f else targetAlpha,
                targetValue = if (isActive && p == Phase.LIMINAL) 1.0f else targetAlpha,
                animationSpec = infiniteRepeatable(
                    animation = tween(900, easing = EaseInOutCubic),
                    repeatMode = RepeatMode.Reverse
                ),
                label = "liminal_alpha"
            )

            Box(
                modifier = Modifier
                    .size(10.dp)
                    .scale(scale * if (isActive && p == Phase.LIMINAL) liminalPulse else 1f)
                    .background(
                        color.copy(
                            alpha = if (isActive && p == Phase.LIMINAL) liminalAlpha else targetAlpha
                        ),
                        CircleShape
                    )
            )
        }
    }
}
