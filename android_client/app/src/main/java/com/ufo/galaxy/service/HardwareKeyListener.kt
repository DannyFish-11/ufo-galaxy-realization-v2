package com.ufo.galaxy.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.util.Log
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import com.ufo.galaxy.ui.MainActivity

/**
 * 硬件按键监听服务
 * 通过 AccessibilityService 监听音量键等物理按键
 * 
 * 使用方法:
 * 1. 在 AndroidManifest.xml 中注册此服务
 * 2. 用户需要在系统设置中启用此无障碍服务
 * 3. 服务启用后，双击音量下键可唤醒 UFO Galaxy
 */
class HardwareKeyListener : AccessibilityService() {
    
    companion object {
        private const val TAG = "HardwareKeyListener"
        
        // 双击检测参数
        private const val DOUBLE_CLICK_INTERVAL = 500L  // 双击间隔（毫秒）
        private const val TRIPLE_CLICK_INTERVAL = 800L  // 三击间隔（毫秒）
        
        // 触发模式
        var triggerMode = TriggerMode.DOUBLE_VOLUME_DOWN
    }
    
    // 按键时间记录
    private var lastVolumeDownTime = 0L
    private var volumeDownClickCount = 0
    
    private var lastVolumeUpTime = 0L
    private var volumeUpClickCount = 0
    
    override fun onServiceConnected() {
        super.onServiceConnected()
        Log.i(TAG, "硬件按键监听服务已连接")
        
        // 配置服务
        serviceInfo = serviceInfo.apply {
            flags = flags or AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
        }
    }
    
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // 不需要处理无障碍事件
    }
    
    override fun onInterrupt() {
        Log.w(TAG, "服务被中断")
    }
    
    override fun onKeyEvent(event: KeyEvent?): Boolean {
        if (event == null) return false
        
        // 只处理按键按下事件
        if (event.action != KeyEvent.ACTION_DOWN) return false
        
        when (event.keyCode) {
            KeyEvent.KEYCODE_VOLUME_DOWN -> {
                return handleVolumeDown()
            }
            KeyEvent.KEYCODE_VOLUME_UP -> {
                return handleVolumeUp()
            }
        }
        
        return false
    }
    
    /**
     * 处理音量下键
     */
    private fun handleVolumeDown(): Boolean {
        val currentTime = System.currentTimeMillis()
        
        // 检查是否在双击间隔内
        if (currentTime - lastVolumeDownTime < DOUBLE_CLICK_INTERVAL) {
            volumeDownClickCount++
        } else {
            volumeDownClickCount = 1
        }
        lastVolumeDownTime = currentTime
        
        Log.d(TAG, "音量下键点击次数: $volumeDownClickCount")
        
        // 根据触发模式检查
        when (triggerMode) {
            TriggerMode.DOUBLE_VOLUME_DOWN -> {
                if (volumeDownClickCount >= 2) {
                    triggerWakeUp()
                    volumeDownClickCount = 0
                    return true  // 消费事件
                }
            }
            TriggerMode.TRIPLE_VOLUME_DOWN -> {
                if (volumeDownClickCount >= 3) {
                    triggerWakeUp()
                    volumeDownClickCount = 0
                    return true
                }
            }
            else -> {}
        }
        
        return false  // 不消费事件，让系统处理音量调节
    }
    
    /**
     * 处理音量上键
     */
    private fun handleVolumeUp(): Boolean {
        val currentTime = System.currentTimeMillis()
        
        if (currentTime - lastVolumeUpTime < DOUBLE_CLICK_INTERVAL) {
            volumeUpClickCount++
        } else {
            volumeUpClickCount = 1
        }
        lastVolumeUpTime = currentTime
        
        Log.d(TAG, "音量上键点击次数: $volumeUpClickCount")
        
        when (triggerMode) {
            TriggerMode.DOUBLE_VOLUME_UP -> {
                if (volumeUpClickCount >= 2) {
                    triggerWakeUp()
                    volumeUpClickCount = 0
                    return true
                }
            }
            TriggerMode.TRIPLE_VOLUME_UP -> {
                if (volumeUpClickCount >= 3) {
                    triggerWakeUp()
                    volumeUpClickCount = 0
                    return true
                }
            }
            else -> {}
        }
        
        return false
    }
    
    /**
     * 触发唤醒
     */
    private fun triggerWakeUp() {
        Log.i(TAG, "触发 UFO Galaxy 唤醒")
        
        // 发送广播通知
        val intent = Intent(ACTION_WAKE_UP).apply {
            setPackage(packageName)
        }
        sendBroadcast(intent)
        
        // 启动主界面
        val activityIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or 
                    Intent.FLAG_ACTIVITY_SINGLE_TOP or
                    Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_TRIGGERED_BY, "hardware_key")
        }
        startActivity(activityIntent)
    }
    
    override fun onDestroy() {
        super.onDestroy()
        Log.i(TAG, "硬件按键监听服务已销毁")
    }
}

/**
 * 触发模式
 */
enum class TriggerMode {
    DOUBLE_VOLUME_DOWN,   // 双击音量下
    TRIPLE_VOLUME_DOWN,   // 三击音量下
    DOUBLE_VOLUME_UP,     // 双击音量上
    TRIPLE_VOLUME_UP,     // 三击音量上
    VOLUME_UP_DOWN,       // 音量上+下组合
    DISABLED              // 禁用
}

// 广播 Action
const val ACTION_WAKE_UP = "com.ufo.galaxy.ACTION_WAKE_UP"
const val EXTRA_TRIGGERED_BY = "triggered_by"
