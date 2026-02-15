package com.ufo.galaxy.ui.components

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.abs

/**
 * 书法卷轴式 UI 容器
 * 实现一展一收的写意风格交互
 */
@Composable
fun ScrollPaperContainer(
    isExpanded: Boolean,
    onExpandChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    val configuration = LocalConfiguration.current
    val screenWidth = configuration.screenWidthDp.dp
    val density = LocalDensity.current
    
    // 卷轴宽度动画
    val targetWidth = if (isExpanded) screenWidth else 60.dp
    val animatedWidth by animateDpAsState(
        targetValue = targetWidth,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow
        ),
        label = "scroll_width"
    )
    
    // 透明度动画
    val contentAlpha by animateFloatAsState(
        targetValue = if (isExpanded) 1f else 0f,
        animationSpec = tween(
            durationMillis = if (isExpanded) 400 else 200,
            easing = if (isExpanded) FastOutSlowInEasing else LinearEasing
        ),
        label = "content_alpha"
    )
    
    // 拖动状态
    var dragOffset by remember { mutableFloatStateOf(0f) }
    
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.CenterEnd
    ) {
        // 卷轴主体
        Box(
            modifier = Modifier
                .width(animatedWidth)
                .fillMaxHeight()
                .padding(vertical = 16.dp)
                .shadow(
                    elevation = 8.dp,
                    shape = RoundedCornerShape(
                        topStart = 16.dp,
                        bottomStart = 16.dp
                    )
                )
                .clip(
                    RoundedCornerShape(
                        topStart = 16.dp,
                        bottomStart = 16.dp
                    )
                )
                .background(
                    brush = Brush.horizontalGradient(
                        colors = listOf(
                            Color(0xFFF5F0E6), // 宣纸色
                            Color(0xFFFAF8F3),
                            Color(0xFFF5F0E6)
                        )
                    )
                )
                .pointerInput(Unit) {
                    detectHorizontalDragGestures(
                        onDragStart = { dragOffset = 0f },
                        onDragEnd = {
                            // 根据拖动方向和距离决定展开/收起
                            val threshold = with(density) { 50.dp.toPx() }
                            if (abs(dragOffset) > threshold) {
                                onExpandChange(dragOffset < 0)
                            }
                            dragOffset = 0f
                        },
                        onDragCancel = { dragOffset = 0f },
                        onHorizontalDrag = { _, dragAmount ->
                            dragOffset += dragAmount
                        }
                    )
                }
        ) {
            // 左侧墨迹边缘装饰
            InkEdgeDecoration(
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .width(8.dp)
                    .fillMaxHeight()
            )
            
            // 内容区域
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(start = 12.dp)
            ) {
                if (contentAlpha > 0.01f) {
                    Box(
                        modifier = Modifier.fillMaxSize()
                    ) {
                        content()
                    }
                }
            }
            
            // 收起时的把手指示器
            if (!isExpanded) {
                ScrollHandle(
                    modifier = Modifier.align(Alignment.Center)
                )
            }
        }
    }
}

/**
 * 墨迹边缘装饰
 */
@Composable
private fun InkEdgeDecoration(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.background(
            brush = Brush.horizontalGradient(
                colors = listOf(
                    Color(0xFF2C2C2C),
                    Color(0x802C2C2C),
                    Color.Transparent
                )
            )
        )
    )
}

/**
 * 卷轴把手
 */
@Composable
private fun ScrollHandle(modifier: Modifier = Modifier) {
    // 呼吸动画
    val infiniteTransition = rememberInfiniteTransition(label = "handle_breath")
    val alpha by infiniteTransition.animateFloat(
        initialValue = 0.5f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "handle_alpha"
    )
    
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        // 三条横线指示器
        repeat(3) { index ->
            Box(
                modifier = Modifier
                    .padding(vertical = 3.dp)
                    .width((20 - index * 4).dp)
                    .height(3.dp)
                    .background(
                        color = Color(0xFF2C2C2C).copy(alpha = alpha),
                        shape = RoundedCornerShape(2.dp)
                    )
            )
        }
    }
}

/**
 * 灵动岛指示器
 */
@Composable
fun DynamicIslandIndicator(
    isActive: Boolean,
    modifier: Modifier = Modifier
) {
    val width by animateDpAsState(
        targetValue = if (isActive) 180.dp else 120.dp,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow
        ),
        label = "island_width"
    )
    
    val height by animateDpAsState(
        targetValue = if (isActive) 50.dp else 36.dp,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow
        ),
        label = "island_height"
    )
    
    Box(
        modifier = modifier
            .width(width)
            .height(height)
            .clip(RoundedCornerShape(50))
            .background(Color.Black),
        contentAlignment = Alignment.Center
    ) {
        // 内容
    }
}
