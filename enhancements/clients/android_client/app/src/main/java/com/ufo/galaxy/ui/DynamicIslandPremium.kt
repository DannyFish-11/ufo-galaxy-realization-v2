package com.ufo.galaxy.ui

import android.content.Context
import android.os.VibrationEffect
import android.os.Vibrator
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * UFO³ Galaxy 灵动岛组件 - 高质感版本
 * 
 * 新增特性：
 * - 毛玻璃效果 (Frosted Glass)
 * - 内发光和外发光
 * - 粒子动画效果
 * - 触觉反馈
 * - 景深效果
 * - 更精致的阴影和高光
 * 
 * @author Manus AI
 * @date 2026-01-22
 */

/**
 * 高质感灵动岛主组件
 */
@Composable
fun DynamicIslandPremium(
    modifier: Modifier = Modifier,
    initialState: IslandState = IslandState.COLLAPSED,
    systemStatus: SystemStatus = SystemStatus.IDLE,
    currentTask: String? = null,
    taskProgress: Float? = null,
    onStateChange: (IslandState) -> Unit = {},
    onClose: () -> Unit = {}
) {
    val context = LocalContext.current
    val vibrator = remember { context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator }
    
    var state by remember { mutableStateOf(initialState) }
    var offset by remember { mutableStateOf(Offset(0f, 100f)) }
    var isPressed by remember { mutableStateOf(false) }
    
    // 触觉反馈函数
    fun performHapticFeedback(type: HapticFeedbackType = HapticFeedbackType.LIGHT) {
        val effect = when (type) {
            HapticFeedbackType.LIGHT -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK)
            HapticFeedbackType.MEDIUM -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK)
            HapticFeedbackType.HEAVY -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_HEAVY_CLICK)
        }
        vibrator.vibrate(effect)
    }
    
    // 动画配置 - 使用更流畅的弹性动画
    val springSpec = spring<Float>(
        dampingRatio = Spring.DampingRatioMediumBouncy,
        stiffness = Spring.StiffnessLow
    )
    
    // 宽度动画
    val targetWidth = when (state) {
        IslandState.COLLAPSED -> 120.dp
        IslandState.COMPACT_EXPANDED -> 300.dp
        IslandState.FULLY_EXPANDED -> 380.dp
    }
    val animatedWidth by animateDpAsState(
        targetValue = targetWidth,
        animationSpec = springSpec,
        label = "width"
    )
    
    // 高度动画
    val targetHeight = when (state) {
        IslandState.COLLAPSED -> 44.dp
        IslandState.COMPACT_EXPANDED -> 88.dp
        IslandState.FULLY_EXPANDED -> 640.dp
    }
    val animatedHeight by animateDpAsState(
        targetValue = targetHeight,
        animationSpec = springSpec,
        label = "height"
    )
    
    // 圆角动画
    val targetCornerRadius = when (state) {
        IslandState.COLLAPSED -> 22.dp
        IslandState.COMPACT_EXPANDED -> 24.dp
        IslandState.FULLY_EXPANDED -> 28.dp
    }
    val animatedCornerRadius by animateDpAsState(
        targetValue = targetCornerRadius,
        animationSpec = springSpec,
        label = "cornerRadius"
    )
    
    // 按压缩放动画
    val scale by animateFloatAsState(
        targetValue = if (isPressed) 0.96f else 1f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessHigh
        ),
        label = "scale"
    )
    
    // 粒子动画
    val particleAnimationProgress = remember { Animatable(0f) }
    LaunchedEffect(state) {
        if (state != IslandState.COLLAPSED) {
            particleAnimationProgress.animateTo(
                targetValue = 1f,
                animationSpec = tween(durationMillis = 800, easing = FastOutSlowInEasing)
            )
        } else {
            particleAnimationProgress.snapTo(0f)
        }
    }
    
    Box(
        modifier = modifier
            .offset { IntOffset(offset.x.roundToInt(), offset.y.roundToInt()) }
            .size(width = animatedWidth, height = animatedHeight)
            .scale(scale)
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = {
                        isPressed = true
                        performHapticFeedback(HapticFeedbackType.LIGHT)
                    },
                    onDragEnd = {
                        isPressed = false
                    },
                    onDrag = { change, dragAmount ->
                        change.consume()
                        offset = Offset(
                            x = (offset.x + dragAmount.x).coerceIn(0f, size.width.toFloat()),
                            y = (offset.y + dragAmount.y).coerceIn(0f, size.height.toFloat())
                        )
                    }
                )
            }
    ) {
        // 外发光层
        Box(
            modifier = Modifier
                .fillMaxSize()
                .blur(16.dp)
                .drawBehind {
                    drawRoundRect(
                        brush = Brush.radialGradient(
                            colors = listOf(
                                Color(0x40FFFFFF),
                                Color.Transparent
                            ),
                            center = Offset(size.width / 2, size.height / 2),
                            radius = size.minDimension / 2
                        ),
                        cornerRadius = CornerRadius(animatedCornerRadius.toPx())
                    )
                }
        )
        
        // 主容器 - 毛玻璃效果
        Box(
            modifier = Modifier
                .fillMaxSize()
                .shadow(
                    elevation = 24.dp,
                    shape = RoundedCornerShape(animatedCornerRadius),
                    clip = false,
                    ambientColor = Color(0x40000000),
                    spotColor = Color(0x80000000)
                )
                .clip(RoundedCornerShape(animatedCornerRadius))
                .background(
                    brush = Brush.verticalGradient(
                        colors = listOf(
                            Color(0xE6000000), // 更高的不透明度
                            Color(0xF0101010),
                            Color(0xF51A1A1A)
                        )
                    )
                )
                .drawBehind {
                    // 内发光效果
                    drawIntoCanvas { canvas ->
                        val paint = Paint().apply {
                            shader = LinearGradientShader(
                                from = Offset(0f, 0f),
                                to = Offset(0f, size.height * 0.3f),
                                colors = listOf(
                                    Color(0x30FFFFFF),
                                    Color.Transparent
                                )
                            )
                        }
                        canvas.drawRoundRect(
                            left = 0f,
                            top = 0f,
                            right = size.width,
                            bottom = size.height,
                            radiusX = animatedCornerRadius.toPx(),
                            radiusY = animatedCornerRadius.toPx(),
                            paint = paint
                        )
                    }
                    
                    // 边框高光
                    drawRoundRect(
                        color = Color(0x20FFFFFF),
                        size = size,
                        cornerRadius = CornerRadius(animatedCornerRadius.toPx()),
                        style = Stroke(width = 1.dp.toPx())
                    )
                }
        ) {
            // 粒子效果层
            if (particleAnimationProgress.value > 0f) {
                Canvas(modifier = Modifier.fillMaxSize()) {
                    drawParticles(
                        progress = particleAnimationProgress.value,
                        systemStatus = systemStatus
                    )
                }
            }
            
            // 内容层
            when (state) {
                IslandState.COLLAPSED -> CollapsedContentPremium(
                    systemStatus = systemStatus,
                    onClick = {
                        performHapticFeedback(HapticFeedbackType.MEDIUM)
                        state = IslandState.COMPACT_EXPANDED
                        onStateChange(state)
                    }
                )
                
                IslandState.COMPACT_EXPANDED -> CompactExpandedContentPremium(
                    systemStatus = systemStatus,
                    currentTask = currentTask,
                    taskProgress = taskProgress,
                    onClick = {
                        performHapticFeedback(HapticFeedbackType.HEAVY)
                        state = IslandState.FULLY_EXPANDED
                        onStateChange(state)
                    },
                    onCollapse = {
                        performHapticFeedback(HapticFeedbackType.LIGHT)
                        state = IslandState.COLLAPSED
                        onStateChange(state)
                    }
                )
                
                IslandState.FULLY_EXPANDED -> FullyExpandedContentPremium(
                    onCollapse = {
                        performHapticFeedback(HapticFeedbackType.MEDIUM)
                        state = IslandState.COMPACT_EXPANDED
                        onStateChange(state)
                    },
                    onClose = {
                        performHapticFeedback(HapticFeedbackType.HEAVY)
                        onClose()
                    }
                )
            }
        }
    }
}

/**
 * 绘制粒子效果
 */
private fun DrawScope.drawParticles(progress: Float, systemStatus: SystemStatus) {
    val particleCount = 20
    val statusColor = when (systemStatus) {
        SystemStatus.IDLE -> Color(0xFF00FF00)
        SystemStatus.WORKING -> Color(0xFF00BFFF)
        SystemStatus.ERROR -> Color(0xFFFF4500)
        SystemStatus.OFFLINE -> Color(0xFF808080)
    }
    
    for (i in 0 until particleCount) {
        val angle = (i.toFloat() / particleCount) * 2 * PI.toFloat()
        val distance = size.minDimension * 0.3f * progress
        val x = size.width / 2 + cos(angle) * distance
        val y = size.height / 2 + sin(angle) * distance
        val alpha = (1f - progress) * 0.6f
        
        drawCircle(
            color = statusColor.copy(alpha = alpha),
            radius = 2.dp.toPx() * (1f - progress * 0.5f),
            center = Offset(x, y)
        )
    }
}

/**
 * 折叠态内容 - 高质感版本
 */
@Composable
private fun CollapsedContentPremium(
    systemStatus: SystemStatus,
    onClick: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .clickable(
                onClick = onClick,
                indication = null,
                interactionSource = remember { MutableInteractionSource() }
            ),
        contentAlignment = Alignment.Center
    ) {
        // 状态指示器 - 呼吸灯效果 + 辉光
        val infiniteTransition = rememberInfiniteTransition(label = "breathing")
        val alpha by infiniteTransition.animateFloat(
            initialValue = 0.4f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(
                animation = tween(2000, easing = FastOutSlowInEasing),
                repeatMode = RepeatMode.Reverse
            ),
            label = "alpha"
        )
        
        val scale by infiniteTransition.animateFloat(
            initialValue = 1f,
            targetValue = 1.15f,
            animationSpec = infiniteRepeatable(
                animation = tween(2000, easing = FastOutSlowInEasing),
                repeatMode = RepeatMode.Reverse
            ),
            label = "scale"
        )
        
        val statusColor = when (systemStatus) {
            SystemStatus.IDLE -> Color(0xFF00FF00)
            SystemStatus.WORKING -> Color(0xFF00BFFF)
            SystemStatus.ERROR -> Color(0xFFFF4500)
            SystemStatus.OFFLINE -> Color(0xFF808080)
        }
        
        // 外层辉光
        Box(
            modifier = Modifier
                .size(32.dp)
                .scale(scale)
                .blur(8.dp)
                .background(
                    color = statusColor.copy(alpha = alpha * 0.5f),
                    shape = RoundedCornerShape(16.dp)
                )
        )
        
        // 内层核心
        Box(
            modifier = Modifier
                .size(18.dp)
                .background(
                    brush = Brush.radialGradient(
                        colors = listOf(
                            statusColor.copy(alpha = alpha),
                            statusColor.copy(alpha = alpha * 0.7f)
                        )
                    ),
                    shape = RoundedCornerShape(9.dp)
                )
                .drawBehind {
                    // 高光点
                    drawCircle(
                        color = Color.White.copy(alpha = alpha * 0.6f),
                        radius = 3.dp.toPx(),
                        center = Offset(size.width * 0.3f, size.height * 0.3f)
                    )
                }
        )
    }
}

/**
 * 概览态内容 - 高质感版本
 */
@Composable
private fun CompactExpandedContentPremium(
    systemStatus: SystemStatus,
    currentTask: String?,
    taskProgress: Float?,
    onClick: () -> Unit,
    onCollapse: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .clickable(
                onClick = onClick,
                indication = null,
                interactionSource = remember { MutableInteractionSource() }
            )
            .padding(16.dp),
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        // 顶部：状态和任务
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 状态指示器 - 带辉光
            val statusColor = when (systemStatus) {
                SystemStatus.IDLE -> Color(0xFF00FF00)
                SystemStatus.WORKING -> Color(0xFF00BFFF)
                SystemStatus.ERROR -> Color(0xFFFF4500)
                SystemStatus.OFFLINE -> Color(0xFF808080)
            }
            
            Box(
                modifier = Modifier
                    .size(12.dp)
                    .blur(4.dp)
                    .background(statusColor.copy(alpha = 0.5f), shape = RoundedCornerShape(6.dp))
            )
            
            Box(
                modifier = Modifier
                    .size(12.dp)
                    .background(statusColor, shape = RoundedCornerShape(6.dp))
            )
            
            Spacer(modifier = Modifier.width(12.dp))
            
            // 任务文本 - 带阴影
            Text(
                text = currentTask ?: "IDLE",
                color = Color.White,
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
                modifier = Modifier
                    .weight(1f)
                    .drawBehind {
                        drawIntoCanvas { canvas ->
                            val paint = Paint().apply {
                                color = Color.Black.copy(alpha = 0.5f)
                            }
                            canvas.drawText(
                                text = currentTask ?: "IDLE",
                                x = 1.dp.toPx(),
                                y = 1.dp.toPx(),
                                paint = paint
                            )
                        }
                    }
            )
        }
        
        Spacer(modifier = Modifier.height(12.dp))
        
        // 底部：进度条（如果有）
        taskProgress?.let { progress ->
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(Color(0xFF1A1A1A))
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(progress)
                        .fillMaxHeight()
                        .background(
                            brush = Brush.horizontalGradient(
                                colors = listOf(
                                    Color(0xFF00BFFF),
                                    Color(0xFF00FFFF)
                                )
                            )
                        )
                        .drawBehind {
                            // 进度条辉光
                            drawRect(
                                brush = Brush.horizontalGradient(
                                    colors = listOf(
                                        Color(0x6000BFFF),
                                        Color(0x6000FFFF)
                                    )
                                ),
                                size = size.copy(height = size.height + 4.dp.toPx()),
                                topLeft = Offset(0f, -2.dp.toPx())
                            )
                        }
                )
            }
        }
    }
}

/**
 * 完全展开态内容 - 高质感版本
 */
@Composable
private fun FullyExpandedContentPremium(
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
                        Color(0xFF050505),
                        Color(0xFF0A0A0A),
                        Color(0xFF1A1A1A)
                    )
                )
            )
    ) {
        // 使用之前定义的组件
        GeekTerminalHeader(onCollapse = onCollapse, onClose = onClose)
        
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
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace
            )
        }
        
        GeekTerminalInput()
        GeekTerminalStatusBar()
    }
}

/**
 * 触觉反馈类型
 */
enum class HapticFeedbackType {
    LIGHT,
    MEDIUM,
    HEAVY
}
