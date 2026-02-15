package com.ufo.galaxy.ui.feedback

import android.content.Context
import android.media.AudioAttributes
import android.media.SoundPool
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.annotation.RawRes

/**
 * UFO³ Galaxy 触觉反馈和音效管理器
 * 
 * 提供统一的触觉反馈和音效接口，提升用户交互体验。
 * 
 * 功能：
 * - 多种触觉反馈模式（轻、中、重、自定义）
 * - 音效播放和管理
 * - 自适应不同 Android 版本
 * - 性能优化和资源管理
 * 
 * @author Manus AI
 * @date 2026-01-22
 */
class FeedbackManager(private val context: Context) {
    
    private val vibrator: Vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        val vibratorManager = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
        vibratorManager.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    }
    
    private val soundPool: SoundPool = SoundPool.Builder()
        .setMaxStreams(5)
        .setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
        )
        .build()
    
    private val soundCache = mutableMapOf<SoundType, Int>()
    
    // 设置
    var isHapticEnabled = true
    var isSoundEnabled = true
    var hapticIntensity = 1.0f // 0.0 - 1.0
    var soundVolume = 0.5f // 0.0 - 1.0
    
    /**
     * 触觉反馈类型
     */
    enum class HapticType {
        TICK,           // 轻微的 tick，用于滚动、选择
        CLICK,          // 标准点击
        HEAVY_CLICK,    // 重点击，用于重要操作
        DOUBLE_CLICK,   // 双击
        SUCCESS,        // 成功反馈
        WARNING,        // 警告反馈
        ERROR,          // 错误反馈
        LONG_PRESS,     // 长按
        REJECT          // 拒绝操作
    }
    
    /**
     * 音效类型
     */
    enum class SoundType {
        TAP,            // 轻触
        CLICK,          // 点击
        EXPAND,         // 展开
        COLLAPSE,       // 折叠
        SUCCESS,        // 成功
        ERROR,          // 错误
        NOTIFICATION,   // 通知
        SEND,           // 发送
        RECEIVE,        // 接收
        SWIPE           // 滑动
    }
    
    /**
     * 执行触觉反馈
     */
    fun performHaptic(type: HapticType) {
        if (!isHapticEnabled || !vibrator.hasVibrator()) return
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val effect = when (type) {
                HapticType.TICK -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK)
                HapticType.CLICK -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK)
                HapticType.HEAVY_CLICK -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_HEAVY_CLICK)
                HapticType.DOUBLE_CLICK -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_DOUBLE_CLICK)
                HapticType.SUCCESS -> createSuccessPattern()
                HapticType.WARNING -> createWarningPattern()
                HapticType.ERROR -> createErrorPattern()
                HapticType.LONG_PRESS -> createLongPressPattern()
                HapticType.REJECT -> createRejectPattern()
            }
            vibrator.vibrate(effect)
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val duration = when (type) {
                HapticType.TICK -> 10L
                HapticType.CLICK -> 20L
                HapticType.HEAVY_CLICK -> 40L
                HapticType.DOUBLE_CLICK -> 20L
                HapticType.SUCCESS, HapticType.WARNING, HapticType.ERROR -> 30L
                HapticType.LONG_PRESS -> 50L
                HapticType.REJECT -> 25L
            }
            val amplitude = (255 * hapticIntensity).toInt().coerceIn(1, 255)
            vibrator.vibrate(VibrationEffect.createOneShot(duration, amplitude))
        } else {
            @Suppress("DEPRECATION")
            val duration = when (type) {
                HapticType.TICK -> 10L
                HapticType.CLICK -> 20L
                HapticType.HEAVY_CLICK -> 40L
                HapticType.DOUBLE_CLICK -> 20L
                HapticType.SUCCESS, HapticType.WARNING, HapticType.ERROR -> 30L
                HapticType.LONG_PRESS -> 50L
                HapticType.REJECT -> 25L
            }
            vibrator.vibrate(duration)
        }
    }
    
    /**
     * 播放音效
     */
    fun playSound(type: SoundType) {
        if (!isSoundEnabled) return
        
        val soundId = soundCache[type] ?: return
        soundPool.play(soundId, soundVolume, soundVolume, 1, 0, 1.0f)
    }
    
    /**
     * 加载音效资源
     */
    fun loadSound(type: SoundType, @RawRes resId: Int) {
        val soundId = soundPool.load(context, resId, 1)
        soundCache[type] = soundId
    }
    
    /**
     * 组合反馈（触觉 + 音效）
     */
    fun performCombinedFeedback(hapticType: HapticType, soundType: SoundType) {
        performHaptic(hapticType)
        playSound(soundType)
    }
    
    /**
     * 释放资源
     */
    fun release() {
        soundPool.release()
        soundCache.clear()
    }
    
    // ============================================
    // 私有方法 - 创建自定义振动模式
    // ============================================
    
    private fun createSuccessPattern(): VibrationEffect {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            VibrationEffect.createWaveform(
                longArrayOf(0, 50, 50, 50),
                intArrayOf(0, 150, 0, 200),
                -1
            )
        } else {
            VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE)
        }
    }
    
    private fun createWarningPattern(): VibrationEffect {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            VibrationEffect.createWaveform(
                longArrayOf(0, 100, 100, 100),
                intArrayOf(0, 180, 0, 180),
                -1
            )
        } else {
            VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE)
        }
    }
    
    private fun createErrorPattern(): VibrationEffect {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            VibrationEffect.createWaveform(
                longArrayOf(0, 80, 40, 80, 40, 80),
                intArrayOf(0, 255, 0, 255, 0, 255),
                -1
            )
        } else {
            VibrationEffect.createOneShot(80, VibrationEffect.DEFAULT_AMPLITUDE)
        }
    }
    
    private fun createLongPressPattern(): VibrationEffect {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            VibrationEffect.createWaveform(
                longArrayOf(0, 500),
                intArrayOf(0, 200),
                -1
            )
        } else {
            VibrationEffect.createOneShot(500, VibrationEffect.DEFAULT_AMPLITUDE)
        }
    }
    
    private fun createRejectPattern(): VibrationEffect {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            VibrationEffect.createWaveform(
                longArrayOf(0, 30, 30, 30),
                intArrayOf(0, 200, 0, 200),
                -1
            )
        } else {
            VibrationEffect.createOneShot(30, VibrationEffect.DEFAULT_AMPLITUDE)
        }
    }
}

/**
 * Compose 扩展函数 - 便捷的反馈调用
 */
@androidx.compose.runtime.Composable
fun rememberFeedbackManager(): FeedbackManager {
    val context = androidx.compose.ui.platform.LocalContext.current
    return androidx.compose.runtime.remember { FeedbackManager(context) }
}
