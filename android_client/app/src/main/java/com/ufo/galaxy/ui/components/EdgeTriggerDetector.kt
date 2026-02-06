package com.ufo.galaxy.ui.components

import android.content.Context
import android.graphics.PixelFormat
import android.os.Build
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import kotlin.math.abs

/**
 * 右侧边缘滑动唤醒检测器
 * 在屏幕右侧边缘创建一个透明的触摸区域，检测从右向左的滑动手势
 */
class EdgeTriggerDetector(
    private val context: Context,
    private val onTrigger: () -> Unit
) {
    companion object {
        private const val TAG = "EdgeTriggerDetector"
        private const val EDGE_WIDTH_DP = 20  // 边缘触发区域宽度
        private const val MIN_SWIPE_DISTANCE_DP = 50  // 最小滑动距离
        private const val MAX_SWIPE_TIME_MS = 500  // 最大滑动时间
    }
    
    private val windowManager: WindowManager = 
        context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    
    private var edgeView: View? = null
    private var isAttached = false
    
    // 触摸状态
    private var startX = 0f
    private var startY = 0f
    private var startTime = 0L
    
    /**
     * 启动边缘检测
     */
    fun start() {
        if (isAttached) return
        
        try {
            createEdgeView()
            attachEdgeView()
            isAttached = true
            Log.i(TAG, "边缘检测已启动")
        } catch (e: Exception) {
            Log.e(TAG, "启动边缘检测失败", e)
        }
    }
    
    /**
     * 停止边缘检测
     */
    fun stop() {
        if (!isAttached) return
        
        try {
            detachEdgeView()
            isAttached = false
            Log.i(TAG, "边缘检测已停止")
        } catch (e: Exception) {
            Log.e(TAG, "停止边缘检测失败", e)
        }
    }
    
    /**
     * 创建边缘触摸视图
     */
    private fun createEdgeView() {
        edgeView = View(context).apply {
            // 完全透明
            alpha = 0f
            
            // 触摸监听
            setOnTouchListener { _, event ->
                handleTouch(event)
            }
        }
    }
    
    /**
     * 附加边缘视图到窗口
     */
    private fun attachEdgeView() {
        val params = WindowManager.LayoutParams().apply {
            type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_SYSTEM_ALERT
            }
            format = PixelFormat.TRANSLUCENT
            flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                    WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH
            
            // 右侧边缘
            gravity = Gravity.END or Gravity.FILL_VERTICAL
            width = dpToPx(EDGE_WIDTH_DP)
            height = WindowManager.LayoutParams.MATCH_PARENT
            x = 0
        }
        
        windowManager.addView(edgeView, params)
    }
    
    /**
     * 从窗口移除边缘视图
     */
    private fun detachEdgeView() {
        edgeView?.let {
            if (it.parent != null) {
                windowManager.removeView(it)
            }
        }
        edgeView = null
    }
    
    /**
     * 处理触摸事件
     */
    private fun handleTouch(event: MotionEvent): Boolean {
        when (event.action) {
            MotionEvent.ACTION_DOWN -> {
                startX = event.rawX
                startY = event.rawY
                startTime = System.currentTimeMillis()
                Log.d(TAG, "触摸开始: x=$startX, y=$startY")
                return true
            }
            
            MotionEvent.ACTION_MOVE -> {
                // 可以添加视觉反馈
                return true
            }
            
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                val endX = event.rawX
                val endY = event.rawY
                val endTime = System.currentTimeMillis()
                
                val deltaX = startX - endX  // 从右向左为正
                val deltaY = abs(endY - startY)
                val deltaTime = endTime - startTime
                
                Log.d(TAG, "触摸结束: deltaX=$deltaX, deltaY=$deltaY, deltaTime=$deltaTime")
                
                // 检查是否是有效的从右向左滑动
                val minDistance = dpToPx(MIN_SWIPE_DISTANCE_DP)
                if (deltaX > minDistance && 
                    deltaY < deltaX * 0.5f &&  // 垂直移动不超过水平移动的一半
                    deltaTime < MAX_SWIPE_TIME_MS) {
                    
                    Log.i(TAG, "检测到有效的边缘滑动，触发唤醒")
                    onTrigger()
                }
                return true
            }
        }
        return false
    }
    
    /**
     * dp 转 px
     */
    private fun dpToPx(dp: Int): Int {
        return (dp * context.resources.displayMetrics.density).toInt()
    }
}

/**
 * 边缘触发状态
 */
enum class EdgeTriggerState {
    IDLE,       // 空闲
    DETECTING,  // 检测中
    TRIGGERED   // 已触发
}
