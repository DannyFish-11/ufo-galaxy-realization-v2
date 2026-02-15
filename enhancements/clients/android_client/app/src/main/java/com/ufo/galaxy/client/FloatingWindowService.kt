package com.ufo.galaxy.client

import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.speech.RecognizerIntent
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.Toast
import androidx.activity.result.ActivityResultLauncher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Locale

class FloatingWindowService : Service() {

    private lateinit var windowManager: WindowManager
    private lateinit var floatingView: View
    private lateinit var aipClient: EnhancedAIPClient
    private val scope = CoroutineScope(Dispatchers.Main)
    
    // UI 组件
    private lateinit var micButton: ImageView
    private lateinit var textInputLayout: LinearLayout
    private lateinit var textInput: EditText
    private lateinit var sendButton: ImageView
    private lateinit var expandButton: ImageView
    
    // 状态
    private var isExpanded = false
    private var initialX = 0
    private var initialY = 0
    private var initialTouchX = 0f
    private var initialTouchY = 0f

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }

    override fun onCreate() {
        super.onCreate()
        
        // 初始化 AIP 客户端
        val deviceId = "android_${android.os.Build.MODEL.replace(" ", "_")}_${System.currentTimeMillis()}"
        val galaxyUrl = "ws://100.123.215.126:8050"  // Windows PC 的 Node 50
        aipClient = EnhancedAIPClient(deviceId, galaxyUrl, applicationContext, scope)
        aipClient.connect()

        // 创建悬浮窗
        setupFloatingWindow()
    }

    private fun setupFloatingWindow() {
        floatingView = LayoutInflater.from(this).inflate(R.layout.floating_widget, null)

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        )

        params.gravity = Gravity.TOP or Gravity.END
        params.x = 20
        params.y = 100

        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        windowManager.addView(floatingView, params)

        // 初始化 UI 组件
        micButton = floatingView.findViewById(R.id.mic_button)
        textInputLayout = floatingView.findViewById(R.id.text_input_layout)
        textInput = floatingView.findViewById(R.id.text_input)
        sendButton = floatingView.findViewById(R.id.send_button)
        expandButton = floatingView.findViewById(R.id.expand_button)

        // 设置点击事件
        setupClickListeners()
        
        // 设置拖动事件
        setupDragListener(params)
    }

    private fun setupClickListeners() {
        // 语音输入按钮
        micButton.setOnClickListener {
            startVoiceRecognition()
        }

        // 展开/收起按钮
        expandButton.setOnClickListener {
            toggleExpand()
        }

        // 发送按钮
        sendButton.setOnClickListener {
            val text = textInput.text.toString().trim()
            if (text.isNotEmpty()) {
                sendCommandToGalaxy(text)
                textInput.text.clear()
            } else {
                Toast.makeText(this, "请输入命令", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun setupDragListener(params: WindowManager.LayoutParams) {
        floatingView.setOnTouchListener { view, event ->
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

    private fun toggleExpand() {
        isExpanded = !isExpanded
        if (isExpanded) {
            textInputLayout.visibility = View.VISIBLE
            expandButton.rotation = 180f
        } else {
            textInputLayout.visibility = View.GONE
            expandButton.rotation = 0f
        }
    }

    private fun startVoiceRecognition() {
        try {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                putExtra(RecognizerIntent.EXTRA_PROMPT, "说出您的命令...")
            }
            
            // 由于 Service 中无法直接启动 Activity，这里使用 Toast 提示
            // 实际应用中应该使用 SpeechRecognizer API
            Toast.makeText(this, "语音识别启动中...", Toast.LENGTH_SHORT).show()
            
            // TODO: 实现 SpeechRecognizer API
            // 这里应该使用 SpeechRecognizer 而不是 startActivityForResult
            
        } catch (e: Exception) {
            Toast.makeText(this, "语音识别不可用: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    /**
     * 发送命令到 Galaxy 主控
     */
    private fun sendCommandToGalaxy(command: String) {
        scope.launch {
            try {
                val payload = JSONObject().apply {
                    put("command", command)
                    put("source", "android_voice")
                    put("timestamp", System.currentTimeMillis() / 1000)
                    put("device_info", JSONObject().apply {
                        put("manufacturer", android.os.Build.MANUFACTURER)
                        put("model", android.os.Build.MODEL)
                        put("os_version", android.os.Build.VERSION.RELEASE)
                    })
                }
                
                aipClient.sendMessage("command", payload)
                Toast.makeText(this@FloatingWindowService, "命令已发送: $command", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@FloatingWindowService, "发送失败: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        aipClient.disconnect()
        if (::floatingView.isInitialized) {
            windowManager.removeView(floatingView)
        }
    }
}
