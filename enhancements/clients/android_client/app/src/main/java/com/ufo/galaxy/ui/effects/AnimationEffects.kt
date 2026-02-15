package com.ufo.galaxy.ui.effects

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import kotlin.math.*
import kotlin.random.Random

/**
 * UFO³ Galaxy 高级动画效果工具类
 * 
 * 提供各种精致的动画效果：
 * - 扫描线效果
 * - 能量波纹
 * - 矩阵雨
 * - 星空粒子
 * - 数据流动画
 * 
 * @author Manus AI
 * @date 2026-01-22
 */

/**
 * 扫描线效果
 * 模拟 CRT 显示器的扫描线
 */
@Composable
fun ScanlineEffect(
    modifier: Modifier = Modifier,
    lineSpacing: Float = 4f,
    lineOpacity: Float = 0.08f,
    animationSpeed: Float = 1f
) {
    val infiniteTransition = rememberInfiniteTransition(label = "scanline")
    val offset by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = lineSpacing * 2,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = (1000 / animationSpeed).toInt(),
                easing = LinearEasing
            ),
            repeatMode = RepeatMode.Restart
        ),
        label = "scanlineOffset"
    )
    
    Canvas(modifier = modifier.fillMaxSize()) {
        val lineCount = (size.height / lineSpacing).toInt() + 2
        for (i in 0 until lineCount) {
            val y = (i * lineSpacing + offset) % size.height
            drawLine(
                color = Color.Black.copy(alpha = lineOpacity),
                start = Offset(0f, y),
                end = Offset(size.width, y),
                strokeWidth = 1f
            )
        }
    }
}

/**
 * 能量波纹效果
 * 从中心向外扩散的能量波
 */
@Composable
fun EnergyRippleEffect(
    modifier: Modifier = Modifier,
    color: Color = Color(0xFF00BFFF),
    maxRadius: Float = 200f,
    duration: Int = 2000
) {
    val infiniteTransition = rememberInfiniteTransition(label = "ripple")
    val progress by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = duration, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "rippleProgress"
    )
    
    Canvas(modifier = modifier.fillMaxSize()) {
        val centerX = size.width / 2
        val centerY = size.height / 2
        
        // 绘制多个波纹
        for (i in 0 until 3) {
            val phaseOffset = i * 0.33f
            val currentProgress = ((progress + phaseOffset) % 1f)
            val radius = maxRadius * currentProgress
            val alpha = (1f - currentProgress) * 0.5f
            
            drawCircle(
                color = color.copy(alpha = alpha),
                radius = radius,
                center = Offset(centerX, centerY),
                style = Stroke(width = 2f)
            )
        }
    }
}

/**
 * 矩阵雨效果
 * 经典的 Matrix 风格数字雨
 */
@Composable
fun MatrixRainEffect(
    modifier: Modifier = Modifier,
    color: Color = Color(0xFF00FF00),
    columnCount: Int = 20,
    speed: Float = 1f
) {
    val columns = remember {
        List(columnCount) {
            MatrixColumn(
                position = Random.nextFloat(),
                speed = 0.01f + Random.nextFloat() * 0.02f,
                length = 5 + Random.nextInt(10)
            )
        }
    }
    
    val infiniteTransition = rememberInfiniteTransition(label = "matrix")
    val time by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1000f,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = (10000 / speed).toInt(),
                easing = LinearEasing
            ),
            repeatMode = RepeatMode.Restart
        ),
        label = "matrixTime"
    )
    
    Canvas(modifier = modifier.fillMaxSize()) {
        val columnWidth = size.width / columnCount
        val charHeight = 16f
        
        columns.forEachIndexed { index, column ->
            val x = index * columnWidth + columnWidth / 2
            var currentPos = (column.position + time * column.speed) % 1f
            
            for (i in 0 until column.length) {
                val y = currentPos * size.height + i * charHeight
                if (y > 0 && y < size.height) {
                    val alpha = (1f - i.toFloat() / column.length) * 0.8f
                    drawCircle(
                        color = color.copy(alpha = alpha),
                        radius = 2f,
                        center = Offset(x, y)
                    )
                }
            }
        }
    }
}

/**
 * 星空粒子效果
 * 模拟深空中的星星闪烁
 */
@Composable
fun StarfieldEffect(
    modifier: Modifier = Modifier,
    starCount: Int = 100,
    speed: Float = 1f
) {
    val stars = remember {
        List(starCount) {
            Star(
                x = Random.nextFloat(),
                y = Random.nextFloat(),
                size = 0.5f + Random.nextFloat() * 2f,
                twinkleSpeed = 0.5f + Random.nextFloat() * 1.5f,
                twinklePhase = Random.nextFloat() * 2 * PI.toFloat()
            )
        }
    }
    
    val infiniteTransition = rememberInfiniteTransition(label = "starfield")
    val time by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 2 * PI.toFloat(),
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = (3000 / speed).toInt(),
                easing = LinearEasing
            ),
            repeatMode = RepeatMode.Restart
        ),
        label = "starfieldTime"
    )
    
    Canvas(modifier = modifier.fillMaxSize()) {
        stars.forEach { star ->
            val x = star.x * size.width
            val y = star.y * size.height
            val twinkle = (sin(time * star.twinkleSpeed + star.twinklePhase) + 1f) / 2f
            val alpha = 0.3f + twinkle * 0.7f
            
            drawCircle(
                color = Color.White.copy(alpha = alpha),
                radius = star.size,
                center = Offset(x, y)
            )
        }
    }
}

/**
 * 数据流动画
 * 模拟数据在电路中流动
 */
@Composable
fun DataFlowEffect(
    modifier: Modifier = Modifier,
    color: Color = Color(0xFF00BFFF),
    pathCount: Int = 5,
    speed: Float = 1f
) {
    val paths = remember {
        List(pathCount) {
            DataPath(
                startX = Random.nextFloat(),
                startY = Random.nextFloat(),
                endX = Random.nextFloat(),
                endY = Random.nextFloat(),
                speed = 0.5f + Random.nextFloat() * 1f
            )
        }
    }
    
    val infiniteTransition = rememberInfiniteTransition(label = "dataflow")
    val progress by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = (2000 / speed).toInt(),
                easing = LinearEasing
            ),
            repeatMode = RepeatMode.Restart
        ),
        label = "dataflowProgress"
    )
    
    Canvas(modifier = modifier.fillMaxSize()) {
        paths.forEach { dataPath ->
            val currentProgress = (progress * dataPath.speed) % 1f
            val startX = dataPath.startX * size.width
            val startY = dataPath.startY * size.height
            val endX = dataPath.endX * size.width
            val endY = dataPath.endY * size.height
            
            // 绘制路径
            drawLine(
                color = color.copy(alpha = 0.1f),
                start = Offset(startX, startY),
                end = Offset(endX, endY),
                strokeWidth = 1f
            )
            
            // 绘制流动的数据点
            val currentX = startX + (endX - startX) * currentProgress
            val currentY = startY + (endY - startY) * currentProgress
            
            // 数据点带拖尾效果
            for (i in 0 until 5) {
                val trailProgress = (currentProgress - i * 0.05f).coerceAtLeast(0f)
                val trailX = startX + (endX - startX) * trailProgress
                val trailY = startY + (endY - startY) * trailProgress
                val alpha = (1f - i * 0.2f) * 0.8f
                
                drawCircle(
                    color = color.copy(alpha = alpha),
                    radius = 3f - i * 0.5f,
                    center = Offset(trailX, trailY)
                )
            }
        }
    }
}

/**
 * 辉光脉冲效果
 * 用于按钮和重要元素的强调
 */
@Composable
fun GlowPulseEffect(
    modifier: Modifier = Modifier,
    color: Color = Color(0xFF00BFFF),
    intensity: Float = 1f,
    speed: Float = 1f
) {
    val infiniteTransition = rememberInfiniteTransition(label = "glow")
    val scale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 1.3f,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = (1500 / speed).toInt(),
                easing = FastOutSlowInEasing
            ),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glowScale"
    )
    
    val alpha by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 0.8f,
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = (1500 / speed).toInt(),
                easing = FastOutSlowInEasing
            ),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glowAlpha"
    )
    
    Canvas(modifier = modifier.fillMaxSize()) {
        val centerX = size.width / 2
        val centerY = size.height / 2
        val maxRadius = size.minDimension / 2
        
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(
                    color.copy(alpha = alpha * intensity),
                    Color.Transparent
                ),
                center = Offset(centerX, centerY),
                radius = maxRadius * scale
            ),
            radius = maxRadius * scale,
            center = Offset(centerX, centerY)
        )
    }
}

// ============================================
// 数据类
// ============================================

/**
 * 矩阵雨列
 */
private data class MatrixColumn(
    val position: Float,
    val speed: Float,
    val length: Int
)

/**
 * 星星
 */
private data class Star(
    val x: Float,
    val y: Float,
    val size: Float,
    val twinkleSpeed: Float,
    val twinklePhase: Float
)

/**
 * 数据路径
 */
private data class DataPath(
    val startX: Float,
    val startY: Float,
    val endX: Float,
    val endY: Float,
    val speed: Float
)
