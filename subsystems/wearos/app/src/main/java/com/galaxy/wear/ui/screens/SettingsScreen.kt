package com.galaxy.wear.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.*
import com.galaxy.wear.GalaxyWearApplication
import com.galaxy.wear.data.AIPConnectionState
import kotlinx.coroutines.launch

/**
 * SettingsScreen — Server config & connection status
 *
 * - Server URL input
 * - Token (obscured)
 * - Connect / Disconnect
 * - Connection state indicator
 */
@Composable
fun SettingsScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as GalaxyWearApplication
    val scope = rememberCoroutineScope()

    val connectionState by app.connectionState.collectAsState()

    var serverUrl by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var isConnecting by remember { mutableStateOf(false) }

    Scaffold(
        vignette = { Vignette(vignettePosition = VignettePosition.TopAndBottom) },
        positionIndicator = { PositionIndicator(scalingLazyListState = rememberScalingLazyListState()) }
    ) {
        ScalingLazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            item {
                Text(
                    text = "设置",
                    style = MaterialTheme.typography.title1,
                    color = MaterialTheme.colors.onBackground,
                    modifier = Modifier.padding(top = 8.dp, bottom = 8.dp)
                )
            }

            // Connection status indicator
            item {
                val (statusColor, statusText) = when (connectionState) {
                    AIPConnectionState.AUTHENTICATED -> Color(0xFFE0E0E0) to "已连接"
                    AIPConnectionState.CONNECTED -> Color(0xFF808080) to "连接中"
                    AIPConnectionState.CONNECTING -> Color(0xFF666666) to "正在连接"
                    AIPConnectionState.ERROR -> Color(0xFFCF6679) to "错误"
                    AIPConnectionState.DISCONNECTED -> Color(0xFF444444) to "未连接"
                }

                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.padding(bottom = 12.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .background(statusColor, androidx.compose.foundation.shape.CircleShape)
                    )
                    Text(
                        text = statusText,
                        style = MaterialTheme.typography.caption2,
                        color = statusColor
                    )
                }
            }

            // Server URL input (simulated with chip for watch)
            item {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = "服务器",
                        style = MaterialTheme.typography.caption3,
                        color = Color(0xFF666666),
                        modifier = Modifier.padding(bottom = 4.dp)
                    )
                    // On a real watch, use a dedicated input screen
                    // Here we show a chip that would open an input dialog
                    Chip(
                        onClick = { /* Open URL input */ },
                        label = {
                            Text(
                                text = serverUrl.ifEmpty { "点击设置服务器地址" },
                                style = MaterialTheme.typography.caption1,
                                maxLines = 1
                            )
                        },
                        colors = ChipDefaults.secondaryChipColors(),
                        modifier = Modifier.fillMaxWidth(0.9f)
                    )
                }
            }

            item { Spacer(modifier = Modifier.height(8.dp)) }

            // Token input
            item {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = "令牌",
                        style = MaterialTheme.typography.caption3,
                        color = Color(0xFF666666),
                        modifier = Modifier.padding(bottom = 4.dp)
                    )
                    Chip(
                        onClick = { /* Open token input */ },
                        label = {
                            Text(
                                text = if (token.isEmpty()) "点击设置 Token" else "••••••••",
                                style = MaterialTheme.typography.caption1
                            )
                        },
                        colors = ChipDefaults.secondaryChipColors(),
                        modifier = Modifier.fillMaxWidth(0.9f)
                    )
                }
            }

            item { Spacer(modifier = Modifier.height(12.dp)) }

            // Connect / Disconnect buttons
            item {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    if (connectionState == AIPConnectionState.DISCONNECTED ||
                        connectionState == AIPConnectionState.ERROR
                    ) {
                        Button(
                            onClick = {
                                if (serverUrl.isNotEmpty() && token.isNotEmpty()) {
                                    isConnecting = true
                                    app.connect(serverUrl, token)
                                    isConnecting = false
                                }
                            },
                            enabled = serverUrl.isNotEmpty() && token.isNotEmpty() && !isConnecting,
                            modifier = Modifier.size(ButtonDefaults.LargeButtonSize)
                        ) {
                            Text("连接", style = MaterialTheme.typography.button)
                        }
                    } else {
                        Button(
                            onClick = {
                                scope.launch {
                                    app.disconnect()
                                }
                            },
                            colors = ButtonDefaults.primaryButtonColors(
                                backgroundColor = Color(0xFF444444)
                            ),
                            modifier = Modifier.size(ButtonDefaults.LargeButtonSize)
                        ) {
                            Text("断开", style = MaterialTheme.typography.button)
                        }
                    }
                }
            }

            // Quick preset URLs
            item {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "快速选择",
                    style = MaterialTheme.typography.caption3,
                    color = Color(0xFF555555),
                    modifier = Modifier.padding(bottom = 4.dp)
                )
            }

            item {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    CompactChip(
                        onClick = { serverUrl = "ws://localhost:7788" },
                        label = { Text("本地", style = MaterialTheme.typography.caption3) }
                    )
                    CompactChip(
                        onClick = { serverUrl = "wss://galaxy.example.com/ws" },
                        label = { Text("远程", style = MaterialTheme.typography.caption3) }
                    )
                }
            }

            item {
                Spacer(modifier = Modifier.height(12.dp))
                CompactChip(
                    onClick = onBack,
                    label = { Text("返回", style = MaterialTheme.typography.caption2) },
                    colors = ChipDefaults.secondaryChipColors()
                )
            }
        }
    }
}
