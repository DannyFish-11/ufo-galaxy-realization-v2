package com.galaxy.wear.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.wear.compose.material.*
import com.galaxy.wear.GalaxyWearApplication
import kotlinx.coroutines.launch

/**
 * VoiceScreen — Push-to-talk voice interface
 *
 * Hold the center button to record, release to send.
 * Visualizes audio amplitude with animated rings.
 */
@Composable
fun VoiceScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as GalaxyWearApplication
    val scope = rememberCoroutineScope()

    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
                    == PackageManager.PERMISSION_GRANTED
        )
    }

    var isRecording by remember { mutableStateOf(false) }
    var transcript by remember { mutableStateOf("") }
    var isSending by remember { mutableStateOf(false) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasPermission = granted
    }

    Scaffold(
        vignette = { Vignette(vignettePosition = VignettePosition.TopAndBottom) }
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black)
                .padding(horizontal = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            // Title
            Text(
                text = "语音",
                style = MaterialTheme.typography.title1,
                color = MaterialTheme.colors.onBackground,
                modifier = Modifier.padding(bottom = 16.dp)
            )

            if (!hasPermission) {
                Text(
                    text = "需要麦克风权限",
                    style = MaterialTheme.typography.body2,
                    color = Color(0xFF808080),
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(bottom = 12.dp)
                )
                Button(
                    onClick = { permissionLauncher.launch(Manifest.permission.RECORD_AUDIO) }
                ) {
                    Text("授权", style = MaterialTheme.typography.button)
                }
            } else {
                // Recording button with animated rings
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier.size(80.dp)
                ) {
                    // Outer ring animation when recording
                    if (isRecording) {
                        val infiniteTransition = rememberInfiniteTransition(label = "record_ring")
                        val scale by infiniteTransition.animateFloat(
                            initialValue = 1f,
                            targetValue = 1.5f,
                            animationSpec = infiniteRepeatable(
                                animation = tween(800, easing = EaseOutCubic),
                                repeatMode = RepeatMode.Restart
                            ),
                            label = "ring_scale"
                        )
                        val alpha by infiniteTransition.animateFloat(
                            initialValue = 0.6f,
                            targetValue = 0f,
                            animationSpec = infiniteRepeatable(
                                animation = tween(800, easing = EaseOutCubic),
                                repeatMode = RepeatMode.Restart
                            ),
                            label = "ring_alpha"
                        )

                        Box(
                            modifier = Modifier
                                .size(64.dp)
                                .scale(scale)
                                .background(
                                    Color(0xFF808080).copy(alpha = alpha),
                                    CircleShape
                                )
                        )
                    }

                    // Main button
                    Button(
                        onClick = { /* handled by press */ },
                        modifier = Modifier.size(56.dp),
                        colors = ButtonDefaults.primaryButtonColors(
                            backgroundColor = if (isRecording)
                                Color(0xFF808080) else Color(0xFF333333)
                        )
                    ) {
                        Text(
                            text = if (isRecording) "●" else "🎤",
                            style = MaterialTheme.typography.display3
                        )
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Status text
                Text(
                    text = when {
                        isRecording -> "聆听中..."
                        isSending -> "发送中..."
                        transcript.isNotEmpty() -> "\"$transcript\""
                        else -> "按住说话"
                    },
                    style = MaterialTheme.typography.body2,
                    color = when {
                        isRecording -> Color(0xFF808080)
                        else -> Color(0xFF666666)
                    },
                    textAlign = TextAlign.Center,
                    maxLines = 2
                )

                if (transcript.isNotEmpty() && !isSending) {
                    Spacer(modifier = Modifier.height(8.dp))
                    CompactChip(
                        onClick = {
                            scope.launch {
                                isSending = true
                                try {
                                    app.aipClient.sendVoiceQuery(transcript)
                                    transcript = ""
                                } catch (_: Exception) {
                                    transcript = "发送失败"
                                } finally {
                                    isSending = false
                                }
                            }
                        },
                        label = { Text("重新发送", style = MaterialTheme.typography.caption2) }
                    )
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Back button
            CompactChip(
                onClick = onBack,
                label = { Text("返回", style = MaterialTheme.typography.caption2) },
                colors = ChipDefaults.secondaryChipColors()
            )
        }
    }
}
