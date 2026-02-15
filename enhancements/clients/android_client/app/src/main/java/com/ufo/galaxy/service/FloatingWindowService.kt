package com.ufo.galaxy.service

import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.view.Gravity
import android.view.LayoutInflater
import android.view.WindowManager
import android.widget.FrameLayout
import androidx.compose.ui.platform.ComposeView
import com.ufo.galaxy.ui.DynamicIslandPremium
import com.ufo.galaxy.ui.theme.GeekThemePremium

/**
 * 悬浮窗服务
 * 
 * 提供灵动岛风格的悬浮窗界面，作为用户与 Galaxy 系统交互的主要入口
 * 
 * 功能：
 * - 灵动岛 UI
 * - 语音和文本输入
 * - 状态显示
 * - 触觉反馈
 * 
 * @author Manus AI
 * @version 2.0
 * @date 2026-01-22
 */
class FloatingWindowService : Service() {
    
    private lateinit var windowManager: WindowManager
    private var floatingView: FrameLayout? = null
    
    companion object {
        private const val TAG = "FloatingWindowService"
    }
    
    override fun onBind(intent: Intent?): IBinder? {
        return null
    }
    
    override fun onCreate() {
        super.onCreate()
        
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        createFloatingWindow()
    }
    
    /**
     * 创建悬浮窗
     */
    private fun createFloatingWindow() {
        // 创建悬浮窗布局
        floatingView = FrameLayout(this).apply {
            // 添加 Compose View
            val composeView = ComposeView(context).apply {
                setContent {
                    GeekThemePremium {
                        DynamicIslandPremium(
                            onVoiceInput = { handleVoiceInput() },
                            onTextInput = { text -> handleTextInput(text) },
                            onClose = { stopSelf() }
                        )
                    }
                }
            }
            addView(composeView)
        }
        
        // 设置悬浮窗参数
        val params = WindowManager.LayoutParams().apply {
            width = WindowManager.LayoutParams.WRAP_CONTENT
            height = WindowManager.LayoutParams.WRAP_CONTENT
            type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            }
            flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
            format = PixelFormat.TRANSLUCENT
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = 50 // 距离顶部 50dp
        }
        
        // 添加悬浮窗到窗口管理器
        windowManager.addView(floatingView, params)
    }
    
    /**
     * 处理语音输入
     */
    private fun handleVoiceInput() {
        // 启动语音识别
        // 这里可以通过广播或其他方式通知 MainActivity
        val intent = Intent("com.ufo.galaxy.ACTION_VOICE_INPUT")
        sendBroadcast(intent)
    }
    
    /**
     * 处理文本输入
     */
    private fun handleTextInput(text: String) {
        // 发送文本到 Galaxy 系统
        val intent = Intent("com.ufo.galaxy.ACTION_TEXT_INPUT").apply {
            putExtra("text", text)
        }
        sendBroadcast(intent)
    }
    
    override fun onDestroy() {
        super.onDestroy()
        
        // 移除悬浮窗
        floatingView?.let {
            windowManager.removeView(it)
        }
        floatingView = null
    }
}
