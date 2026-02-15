package com.ufo.galaxy.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.util.Log
import android.view.*
import android.widget.FrameLayout
import androidx.core.app.NotificationCompat
import com.ufo.galaxy.R
import com.ufo.galaxy.UFOGalaxyApplication
import com.ufo.galaxy.ui.MainActivity

/**
 * 悬浮窗服务
 * 实现灵动岛式的悬浮交互界面
 */
class FloatingWindowService : Service() {
    
    companion object {
        private const val TAG = "FloatingWindowService"
        private const val NOTIFICATION_ID = 1002
    }
    
    private lateinit var windowManager: WindowManager
    private var floatingView: View? = null
    private var isExpanded = false
    
    // 悬浮窗参数
    private val layoutParams: WindowManager.LayoutParams by lazy {
        WindowManager.LayoutParams().apply {
            type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            }
            format = PixelFormat.TRANSLUCENT
            flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            width = dpToPx(120)
            height = dpToPx(36)
            y = dpToPx(50)
        }
    }
    
    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "悬浮窗服务创建")
        
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        createFloatingView()
    }
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.i(TAG, "悬浮窗服务启动")
        
        // 启动前台服务
        startForeground(NOTIFICATION_ID, createNotification())
        
        // 显示悬浮窗
        showFloatingView()
        
        return START_STICKY
    }
    
    override fun onBind(intent: Intent?): IBinder? = null
    
    override fun onDestroy() {
        super.onDestroy()
        Log.i(TAG, "悬浮窗服务销毁")
        removeFloatingView()
    }
    
    /**
     * 创建悬浮视图
     */
    private fun createFloatingView() {
        floatingView = FrameLayout(this).apply {
            // 灵动岛样式
            setBackgroundResource(R.drawable.dynamic_island_bg)
            
            // 触摸监听
            setOnTouchListener(FloatingTouchListener())
            
            // 点击监听
            setOnClickListener {
                toggleExpand()
            }
            
            // 长按监听
            setOnLongClickListener {
                openMainActivity()
                true
            }
        }
    }
    
    /**
     * 显示悬浮视图
     */
    private fun showFloatingView() {
        try {
            floatingView?.let {
                if (it.parent == null) {
                    windowManager.addView(it, layoutParams)
                    Log.d(TAG, "悬浮窗已显示")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "显示悬浮窗失败", e)
        }
    }
    
    /**
     * 移除悬浮视图
     */
    private fun removeFloatingView() {
        try {
            floatingView?.let {
                if (it.parent != null) {
                    windowManager.removeView(it)
                    Log.d(TAG, "悬浮窗已移除")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "移除悬浮窗失败", e)
        }
    }
    
    /**
     * 切换展开状态
     */
    private fun toggleExpand() {
        isExpanded = !isExpanded
        
        // 动画更新大小
        val targetWidth = if (isExpanded) dpToPx(280) else dpToPx(120)
        val targetHeight = if (isExpanded) dpToPx(160) else dpToPx(36)
        
        // 简单动画（实际应使用 ValueAnimator）
        layoutParams.width = targetWidth
        layoutParams.height = targetHeight
        
        try {
            windowManager.updateViewLayout(floatingView, layoutParams)
        } catch (e: Exception) {
            Log.e(TAG, "更新悬浮窗失败", e)
        }
        
        Log.d(TAG, "悬浮窗展开状态: $isExpanded")
    }
    
    /**
     * 打开主 Activity
     */
    private fun openMainActivity() {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        startActivity(intent)
    }
    
    /**
     * 创建通知
     */
    private fun createNotification(): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        
        return NotificationCompat.Builder(this, UFOGalaxyApplication.CHANNEL_SERVICE)
            .setContentTitle("UFO Galaxy")
            .setContentText("灵动岛已启用")
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .build()
    }
    
    /**
     * dp 转 px
     */
    private fun dpToPx(dp: Int): Int {
        return (dp * resources.displayMetrics.density).toInt()
    }
    
    /**
     * 悬浮窗触摸监听器
     */
    private inner class FloatingTouchListener : View.OnTouchListener {
        private var initialX = 0
        private var initialY = 0
        private var initialTouchX = 0f
        private var initialTouchY = 0f
        
        override fun onTouch(v: View, event: MotionEvent): Boolean {
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = layoutParams.x
                    initialY = layoutParams.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    return false
                }
                MotionEvent.ACTION_MOVE -> {
                    layoutParams.x = initialX + (event.rawX - initialTouchX).toInt()
                    layoutParams.y = initialY + (event.rawY - initialTouchY).toInt()
                    
                    try {
                        windowManager.updateViewLayout(floatingView, layoutParams)
                    } catch (e: Exception) {
                        Log.e(TAG, "移动悬浮窗失败", e)
                    }
                    return true
                }
            }
            return false
        }
    }
}
