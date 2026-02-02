package com.ufo.galaxy.ui

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.*
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.*
import androidx.cardview.widget.CardView
import androidx.constraintlayout.widget.ConstraintLayout
import com.ufo.galaxy.R

/**
 * UFO³ Galaxy Android 悬浮窗 - 黑白渐变极客风格
 *
 * 设计理念：
 * - 黑白渐变背景
 * - 极简几何图形
 * - 科技感的动画效果
 * - 可拖动和折叠
 *
 * 作者：Manus AI
 * 日期：2025-01-20
 */
class MinimalistFloatingWindow(private val context: Context) {
    
    private val windowManager: WindowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private lateinit var floatingView: View
    private lateinit var params: WindowManager.LayoutParams
    
    // UI 组件
    private lateinit var mainContainer: CardView
    private lateinit var headerLayout: LinearLayout
    private lateinit var titleText: TextView
    private lateinit var statusIndicator: View
    private lateinit var collapseButton: ImageButton
    private lateinit var closeButton: ImageButton
    private lateinit var inputLayout: LinearLayout
    private lateinit var inputEditText: EditText
    private lateinit var sendButton: Button
    private lateinit var voiceButton: ImageButton
    private lateinit var historyScrollView: ScrollView
    private lateinit var historyTextView: TextView
    
    // 状态
    private var isExpanded = true
    private var isConnected = false
    
    // 拖动相关
    private var initialX = 0
    private var initialY = 0
    private var initialTouchX = 0f
    private var initialTouchY = 0f
    
    init {
        createFloatingWindow()
    }
    
    @SuppressLint("ClickableViewAccessibility")
    private fun createFloatingWindow() {
        // 创建主容器
        floatingView = FrameLayout(context).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
            )
        }
        
        // 创建 CardView（带圆角和阴影）
        mainContainer = CardView(context).apply {
            layoutParams = FrameLayout.LayoutParams(
                dpToPx(320),
                dpToPx(480)
            )
            radius = dpToPx(16).toFloat()
            cardElevation = dpToPx(8).toFloat()
            setCardBackgroundColor(Color.TRANSPARENT)
        }
        
        // 创建内容布局
        val contentLayout = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
            background = createGradientBackground()
        }
        
        // 创建头部
        createHeader(contentLayout)
        
        // 创建输入区域
        createInputArea(contentLayout)
        
        // 创建历史消息区域
        createHistoryArea(contentLayout)
        
        // 创建状态栏
        createStatusBar(contentLayout)
        
        mainContainer.addView(contentLayout)
        (floatingView as FrameLayout).addView(mainContainer)
        
        // 设置窗口参数
        params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = dpToPx(16)
            y = dpToPx(100)
        }
        
        // 添加拖动监听
        setupDragListener()
    }
    
    /**
     * 创建黑白渐变背景
     */
    private fun createGradientBackground(): Drawable {
        return object : Drawable() {
            private val paint = Paint().apply {
                isAntiAlias = true
            }
            
            override fun draw(canvas: Canvas) {
                val bounds = bounds
                
                // 绘制黑白渐变
                val gradient = LinearGradient(
                    0f, 0f,
                    0f, bounds.height().toFloat(),
                    Color.parseColor("#000000"),
                    Color.parseColor("#1a1a1a"),
                    Shader.TileMode.CLAMP
                )
                paint.shader = gradient
                canvas.drawRect(bounds, paint)
                
                // 绘制几何装饰线条
                paint.shader = null
                paint.color = Color.parseColor("#333333")
                paint.strokeWidth = dpToPx(1).toFloat()
                paint.alpha = 100
                
                // 斜线网格
                for (i in 0 until bounds.width() step dpToPx(50)) {
                    canvas.drawLine(
                        i.toFloat(), 0f,
                        (i + dpToPx(100)).toFloat(), dpToPx(100).toFloat(),
                        paint
                    )
                }
                
                // 顶部横线
                paint.color = Color.WHITE
                paint.alpha = 255
                canvas.drawLine(
                    dpToPx(16).toFloat(), dpToPx(60).toFloat(),
                    (bounds.width() - dpToPx(16)).toFloat(), dpToPx(60).toFloat(),
                    paint
                )
            }
            
            override fun setAlpha(alpha: Int) {
                paint.alpha = alpha
            }
            
            override fun setColorFilter(colorFilter: ColorFilter?) {
                paint.colorFilter = colorFilter
            }
            
            override fun getOpacity(): Int = PixelFormat.TRANSLUCENT
        }
    }
    
    /**
     * 创建头部
     */
    private fun createHeader(parent: LinearLayout) {
        headerLayout = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dpToPx(60)
            )
            setPadding(dpToPx(16), dpToPx(16), dpToPx(16), dpToPx(8))
        }
        
        // 状态指示器
        statusIndicator = View(context).apply {
            layoutParams = LinearLayout.LayoutParams(dpToPx(10), dpToPx(10)).apply {
                gravity = Gravity.CENTER_VERTICAL
                marginEnd = dpToPx(8)
            }
            background = createCircleDrawable(Color.RED)
        }
        headerLayout.addView(statusIndicator)
        
        // 标题
        titleText = TextView(context).apply {
            text = "UFO³ GALAXY"
            textSize = 14f
            typeface = Typeface.MONOSPACE
            setTextColor(Color.WHITE)
            layoutParams = LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
            ).apply {
                gravity = Gravity.CENTER_VERTICAL
            }
        }
        headerLayout.addView(titleText)
        
        // 折叠按钮
        collapseButton = ImageButton(context).apply {
            setImageResource(android.R.drawable.arrow_up_float)
            setBackgroundColor(Color.TRANSPARENT)
            layoutParams = LinearLayout.LayoutParams(dpToPx(32), dpToPx(32))
            setOnClickListener { toggleExpand() }
        }
        headerLayout.addView(collapseButton)
        
        // 关闭按钮
        closeButton = ImageButton(context).apply {
            setImageResource(android.R.drawable.ic_menu_close_clear_cancel)
            setBackgroundColor(Color.TRANSPARENT)
            layoutParams = LinearLayout.LayoutParams(dpToPx(32), dpToPx(32))
            setOnClickListener { hide() }
        }
        headerLayout.addView(closeButton)
        
        parent.addView(headerLayout)
    }
    
    /**
     * 创建输入区域
     */
    private fun createInputArea(parent: LinearLayout) {
        inputLayout = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
            setPadding(dpToPx(16), dpToPx(8), dpToPx(16), dpToPx(8))
        }
        
        // 输入提示
        val promptLabel = TextView(context).apply {
            text = "> INPUT COMMAND"
            textSize = 10f
            typeface = Typeface.MONOSPACE
            setTextColor(Color.parseColor("#888888"))
        }
        inputLayout.addView(promptLabel)
        
        // 输入框和按钮容器
        val inputContainer = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        
        // 输入框
        inputEditText = EditText(context).apply {
            hint = "Type your command..."
            textSize = 12f
            typeface = Typeface.MONOSPACE
            setTextColor(Color.WHITE)
            setHintTextColor(Color.parseColor("#555555"))
            setBackgroundColor(Color.parseColor("#1a1a1a"))
            setPadding(dpToPx(12), dpToPx(12), dpToPx(12), dpToPx(12))
            layoutParams = LinearLayout.LayoutParams(
                0,
                dpToPx(48),
                1f
            )
        }
        inputContainer.addView(inputEditText)
        
        // 语音按钮
        voiceButton = ImageButton(context).apply {
            setImageResource(android.R.drawable.ic_btn_speak_now)
            setBackgroundColor(Color.parseColor("#2a2a2a"))
            layoutParams = LinearLayout.LayoutParams(dpToPx(48), dpToPx(48)).apply {
                marginStart = dpToPx(4)
            }
            setOnClickListener { startVoiceInput() }
        }
        inputContainer.addView(voiceButton)
        
        // 发送按钮
        sendButton = Button(context).apply {
            text = ">"
            textSize = 16f
            typeface = Typeface.MONOSPACE
            setTextColor(Color.BLACK)
            setBackgroundColor(Color.WHITE)
            layoutParams = LinearLayout.LayoutParams(dpToPx(48), dpToPx(48)).apply {
                marginStart = dpToPx(4)
            }
            setOnClickListener { sendMessage() }
        }
        inputContainer.addView(sendButton)
        
        inputLayout.addView(inputContainer)
        parent.addView(inputLayout)
    }
    
    /**
     * 创建历史消息区域
     */
    private fun createHistoryArea(parent: LinearLayout) {
        // 历史消息标签
        val historyLabel = TextView(context).apply {
            text = "> MESSAGE HISTORY"
            textSize = 10f
            typeface = Typeface.MONOSPACE
            setTextColor(Color.parseColor("#888888"))
            setPadding(dpToPx(16), dpToPx(8), dpToPx(16), dpToPx(4))
        }
        parent.addView(historyLabel)
        
        // 滚动视图
        historyScrollView = ScrollView(context).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
            setBackgroundColor(Color.parseColor("#0a0a0a"))
        }
        
        // 历史文本
        historyTextView = TextView(context).apply {
            textSize = 10f
            typeface = Typeface.MONOSPACE
            setTextColor(Color.parseColor("#cccccc"))
            setPadding(dpToPx(16), dpToPx(8), dpToPx(16), dpToPx(8))
        }
        historyScrollView.addView(historyTextView)
        parent.addView(historyScrollView)
    }
    
    /**
     * 创建状态栏
     */
    private fun createStatusBar(parent: LinearLayout) {
        val statusBar = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dpToPx(40)
            )
            setBackgroundColor(Color.BLACK)
            setPadding(dpToPx(16), dpToPx(8), dpToPx(16), dpToPx(8))
        }
        
        // 状态文字
        val statusText = TextView(context).apply {
            text = "READY"
            textSize = 9f
            typeface = Typeface.MONOSPACE
            setTextColor(Color.parseColor("#888888"))
            layoutParams = LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
            )
        }
        statusBar.addView(statusText)
        
        parent.addView(statusBar)
    }
    
    /**
     * 设置拖动监听
     */
    @SuppressLint("ClickableViewAccessibility")
    private fun setupDragListener() {
        headerLayout.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = params.x
                    initialY = params.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = initialX + (initialTouchX - event.rawX).toInt()
                    params.y = initialY + (event.rawY - initialTouchY).toInt()
                    windowManager.updateViewLayout(floatingView, params)
                    true
                }
                else -> false
            }
        }
    }
    
    /**
     * 切换展开/折叠
     */
    private fun toggleExpand() {
        isExpanded = !isExpanded
        
        val targetHeight = if (isExpanded) dpToPx(480) else dpToPx(60)
        
        // 简单的高度动画
        mainContainer.layoutParams = (mainContainer.layoutParams as FrameLayout.LayoutParams).apply {
            height = targetHeight
        }
        
        inputLayout.visibility = if (isExpanded) View.VISIBLE else View.GONE
        historyScrollView.visibility = if (isExpanded) View.VISIBLE else View.GONE
        
        windowManager.updateViewLayout(floatingView, params)
    }
    
    /**
     * 发送消息
     */
    private fun sendMessage() {
        val message = inputEditText.text.toString().trim()
        if (message.isEmpty()) return
        
        appendHistory("[USER] $message")
        inputEditText.setText("")
        
        // TODO: 发送到 Galaxy 系统
    }
    
    /**
     * 开始语音输入
     */
    private fun startVoiceInput() {
        // TODO: 实现语音输入
        appendHistory("[SYSTEM] Voice input started...")
    }
    
    /**
     * 添加历史消息
     */
    private fun appendHistory(message: String) {
        historyTextView.append("$message\n")
        historyScrollView.fullScroll(View.FOCUS_DOWN)
    }
    
    /**
     * 更新连接状态
     */
    fun updateConnectionStatus(connected: Boolean) {
        isConnected = connected
        val color = if (connected) Color.GREEN else Color.RED
        statusIndicator.background = createCircleDrawable(color)
    }
    
    /**
     * 显示悬浮窗
     */
    fun show() {
        if (!::floatingView.isInitialized) return
        try {
            windowManager.addView(floatingView, params)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
    
    /**
     * 隐藏悬浮窗
     */
    fun hide() {
        if (!::floatingView.isInitialized) return
        try {
            windowManager.removeView(floatingView)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
    
    /**
     * 创建圆形 Drawable
     */
    private fun createCircleDrawable(color: Int): Drawable {
        return object : Drawable() {
            private val paint = Paint().apply {
                isAntiAlias = true
                this.color = color
            }
            
            override fun draw(canvas: Canvas) {
                val bounds = bounds
                val radius = Math.min(bounds.width(), bounds.height()) / 2f
                canvas.drawCircle(
                    bounds.centerX().toFloat(),
                    bounds.centerY().toFloat(),
                    radius,
                    paint
                )
            }
            
            override fun setAlpha(alpha: Int) {
                paint.alpha = alpha
            }
            
            override fun setColorFilter(colorFilter: ColorFilter?) {
                paint.colorFilter = colorFilter
            }
            
            override fun getOpacity(): Int = PixelFormat.TRANSLUCENT
        }
    }
    
    /**
     * dp 转 px
     */
    private fun dpToPx(dp: Int): Int {
        return (dp * context.resources.displayMetrics.density).toInt()
    }
}
