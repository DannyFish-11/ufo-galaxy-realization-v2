package com.ufo.galaxy.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.roundToInt

/**
 * UFO³ Galaxy 灵动岛组件
 * 
 * 灵感来源于 iOS Dynamic Island，但采用极简极客风格重新设计。
 * 
 * 三种核心状态：
 * 1. 折叠态 (Collapsed) - 紧凑的药丸形状
 * 2. 概览态 (Compact-Expanded) - 展开显示任务信息
 * 3. 完全展开态 (Fully-Expanded) - 显示完整的极客终端界面
 * 
 * @author Manus AI
 * @date 2026-01-22
 */

/**
 * 灵动岛状态枚举
 */
enum class IslandState {
    COLLAPSED,          // 折叠态
    COMPACT_EXPANDED,   // 概览态
    FULLY_EXPANDED      // 完全展开态
}

/**
 * 系统状态枚举
 */
enum class SystemStatus {
    IDLE,       // 空闲 - 绿色
    WORKING,    // 工作中 - 蓝色
    ERROR,      // 错误 - 红色
    OFFLINE     // 离线 - 灰色
}

/**
 * 灵动岛主组件
 */
@Composable
fun DynamicIsland(
    modifier: Modifier = Modifier,
    initialState: IslandState = IslandState.COLLAPSED,
    systemStatus: SystemStatus = SystemStatus.IDLE,
    currentTask: String? = null,
    taskProgress: Float? = null,
    onStateChange: (IslandState) -> Unit = {},
    onClose: () -> Unit = {}
) {
    var state by remember { mutableStateOf(initialState) }
    var offset by remember { mutableStateOf(Offset(0f, 100f)) }
    
    // 动画配置 - 使用弹性动画
    val springSpec = spring<Float>(
        dampingRatio = Spring.DampingRatioMediumBouncy,
        stiffness = Spring.StiffnessLow
    )
    
    // 宽度动画
    val targetWidth = when (state) {
        IslandState.COLLAPSED -> 120.dp
        IslandState.COMPACT_EXPANDED -> 280.dp
        IslandState.FULLY_EXPANDED -> 360.dp
    }
    val animatedWidth by animateDpAsState(
        targetValue = targetWidth,
        animationSpec = springSpec,
        label = "width"
    )
    
    // 高度动画
    val targetHeight = when (state) {
        IslandState.COLLAPSED -> 40.dp
        IslandState.COMPACT_EXPANDED -> 80.dp
        IslandState.FULLY_EXPANDED -> 600.dp
    }
    val animatedHeight by animateDpAsState(
        targetValue = targetHeight,
        animationSpec = springSpec,
        label = "height"
    )
    
    // 圆角动画
    val targetCornerRadius = when (state) {
        IslandState.COLLAPSED -> 20.dp
        IslandState.COMPACT_EXPANDED -> 20.dp
        IslandState.FULLY_EXPANDED -> 24.dp
    }
    val animatedCornerRadius by animateDpAsState(
        targetValue = targetCornerRadius,
        animationSpec = springSpec,
        label = "cornerRadius"
    )
    
    Box(
        modifier = modifier
            .offset { IntOffset(offset.x.roundToInt(), offset.y.roundToInt()) }
            .size(width = animatedWidth, height = animatedHeight)
            .shadow(
                elevation = 16.dp,
                shape = RoundedCornerShape(animatedCornerRadius),
                clip = false
            )
            .clip(RoundedCornerShape(animatedCornerRadius))
            .background(
                brush = Brush.verticalGradient(
                    colors = listOf(
                        Color(0xFF000000),
                        Color(0xFF1A1A1A)
                    )
                )
            )
            .pointerInput(Unit) {
                detectDragGestures { change, dragAmount ->
                    change.consume()
                    offset = Offset(
                        x = (offset.x + dragAmount.x).coerceIn(0f, size.width.toFloat()),
                        y = (offset.y + dragAmount.y).coerceIn(0f, size.height.toFloat())
                    )
                }
            }
    ) {
        when (state) {
            IslandState.COLLAPSED -> CollapsedContent(
                systemStatus = systemStatus,
                onClick = {
                    state = IslandState.COMPACT_EXPANDED
                    onStateChange(state)
                }
            )
            
            IslandState.COMPACT_EXPANDED -> CompactExpandedContent(
                systemStatus = systemStatus,
                currentTask = currentTask,
                taskProgress = taskProgress,
                onClick = {
                    state = IslandState.FULLY_EXPANDED
                    onStateChange(state)
                },
                onCollapse = {
                    state = IslandState.COLLAPSED
                    onStateChange(state)
                }
            )
            
            IslandState.FULLY_EXPANDED -> FullyExpandedContent(
                onCollapse = {
                    state = IslandState.COMPACT_EXPANDED
                    onStateChange(state)
                },
                onClose = onClose
            )
        }
    }
}

/**
 * 折叠态内容
 */
@Composable
private fun CollapsedContent(
    systemStatus: SystemStatus,
    onClick: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        // 状态指示器 - 呼吸灯效果
        val infiniteTransition = rememberInfiniteTransition(label = "breathing")
        val alpha by infiniteTransition.animateFloat(
            initialValue = 0.3f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                animation = tween(2000, easing = FastOutSlowInEasing),
                repeatMode = RepeatMode.Reverse
            ),
            label = "alpha"
        )
        
        val statusColor = when (systemStatus) {
            SystemStatus.IDLE -> Color(0xFF00FF00)
            SystemStatus.WORKING -> Color(0xFF00BFFF)
            SystemStatus.ERROR -> Color(0xFFFF4500)
            SystemStatus.OFFLINE -> Color(0xFF808080)
        }
        
        Box(
            modifier = Modifier
                .size(16.dp)
                .background(
                    color = statusColor.copy(alpha = alpha),
                    shape = RoundedCornerShape(8.dp)
                )
        )
    }
}

/**
 * 概览态内容
 */
@Composable
private fun CompactExpandedContent(
    systemStatus: SystemStatus,
    currentTask: String?,
    taskProgress: Float?,
    onClick: () -> Unit,
    onCollapse: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .clickable(onClick = onClick)
            .padding(12.dp),
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        // 顶部：状态和任务
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 状态指示器
            val statusColor = when (systemStatus) {
                SystemStatus.IDLE -> Color(0xFF00FF00)
                SystemStatus.WORKING -> Color(0xFF00BFFF)
                SystemStatus.ERROR -> Color(0xFFFF4500)
                SystemStatus.OFFLINE -> Color(0xFF808080)
            }
            
            Box(
                modifier = Modifier
                    .size(10.dp)
                    .background(statusColor, shape = RoundedCornerShape(5.dp))
            )
            
            Spacer(modifier = Modifier.width(8.dp))
            
            // 任务文本
            Text(
                text = currentTask ?: "IDLE",
                color = Color.White,
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f)
            )
        }
        
        // 底部：进度条（如果有）
        taskProgress?.let { progress ->
            LinearProgressIndicator(
                progress = progress,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(3.dp)
                    .clip(RoundedCornerShape(1.5.dp)),
                color = Color(0xFF00BFFF),
                trackColor = Color(0xFF333333)
            )
        }
    }
}

/**
 * 完全展开态内容 - 极客终端界面
 */
@Composable
private fun FullyExpandedContent(
    onCollapse: () -> Unit,
    onClose: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(
                brush = Brush.verticalGradient(
                    colors = listOf(
                        Color(0xFF000000),
                        Color(0xFF0A0A0A),
                        Color(0xFF1A1A1A)
                    )
                )
            )
    ) {
        // 标题栏
        GeekTerminalHeader(
            onCollapse = onCollapse,
            onClose = onClose
        )
        
        // 历史消息区域
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .background(Color(0xFF0A0A0A))
                .padding(16.dp)
        ) {
            Text(
                text = "> SYSTEM READY\n> Waiting for input...",
                color = Color(0xFFCCCCCC),
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace
            )
        }
        
        // 输入区域
        GeekTerminalInput()
        
        // 状态栏
        GeekTerminalStatusBar()
    }
}

/**
 * 极客终端 - 标题栏
 */
@Composable
private fun GeekTerminalHeader(
    onCollapse: () -> Unit,
    onClose: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp)
            .background(Color.Black)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        // 标题
        Text(
            text = "UFO³ GALAXY",
            color = Color.White,
            fontSize = 14.sp,
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.Bold
        )
        
        Row {
            // 折叠按钮
            IconButton(onClick = onCollapse) {
                Text(
                    text = "−",
                    color = Color.White,
                    fontSize = 20.sp
                )
            }
            
            // 关闭按钮
            IconButton(onClick = onClose) {
                Text(
                    text = "×",
                    color = Color.White,
                    fontSize = 20.sp
                )
            }
        }
    }
}

/**
 * 极客终端 - 输入区域
 */
@Composable
private fun GeekTerminalInput() {
    var inputText by remember { mutableStateOf("") }
    
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF1A1A1A))
            .padding(16.dp)
    ) {
        Text(
            text = "> INPUT COMMAND",
            color = Color(0xFF888888),
            fontSize = 9.sp,
            fontFamily = FontFamily.Monospace
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 提示符
            Text(
                text = "$",
                color = Color(0xFF00FF00),
                fontSize = 14.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold
            )
            
            Spacer(modifier = Modifier.width(8.dp))
            
            // 输入框
            TextField(
                value = inputText,
                onValueChange = { inputText = it },
                modifier = Modifier.weight(1f),
                textStyle = LocalTextStyle.current.copy(
                    color = Color.White,
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace
                ),
                placeholder = {
                    Text(
                        text = "Type your command...",
                        color = Color(0xFF555555),
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                },
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color(0xFF0A0A0A),
                    unfocusedContainerColor = Color(0xFF0A0A0A),
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent
                ),
                singleLine = true
            )
            
            Spacer(modifier = Modifier.width(8.dp))
            
            // 发送按钮
            Button(
                onClick = { /* TODO: 发送消息 */ },
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color.White,
                    contentColor = Color.Black
                ),
                modifier = Modifier.size(48.dp),
                contentPadding = PaddingValues(0.dp)
            ) {
                Text(
                    text = ">",
                    fontSize = 16.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

/**
 * 极客终端 - 状态栏
 */
@Composable
private fun GeekTerminalStatusBar() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(40.dp)
            .background(Color.Black)
            .padding(horizontal = 16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = "READY",
            color = Color(0xFF888888),
            fontSize = 9.sp,
            fontFamily = FontFamily.Monospace
        )
        
        Text(
            text = "v2.1",
            color = Color(0xFF888888),
            fontSize = 9.sp,
            fontFamily = FontFamily.Monospace
        )
    }
}
