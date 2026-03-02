package com.ufo.galaxy.agent

import android.content.Context
import android.util.Log
import com.ufo.galaxy.autonomy.AutonomyManager
import kotlinx.coroutines.*
import org.json.JSONObject

/**
 * UFO³ Galaxy Agent 主控制器
 * 
 * 这是 Android 设备作为 Galaxy 系统 Agent 节点的统一入口和管理中心。
 * 
 * 核心职责：
 * 1. 管理 Agent 的完整生命周期（注册、连接、运行、注销）
 * 2. 协调各个子模块（注册、WebSocket、消息处理、自主操纵）
 * 3. 提供统一的对外 API 接口
 * 4. 自适应和自配置能力
 * 5. 状态监控和健康检查
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class GalaxyAgent private constructor(private val context: Context) {
    
    private val TAG = "GalaxyAgent"
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    
    // 核心组件
    private val agentRegistry = AgentRegistry.getInstance(context)
    private val autonomyManager = AutonomyManager.getInstance(context)
    private lateinit var agentWebSocket: AgentWebSocket
    private lateinit var messageHandler: AgentMessageHandler
    
    // 配置
    private var gatewayUrl = "ws://192.168.1.100:8000/ws/agent" // 默认值，需要配置
    
    // 状态
    @Volatile
    private var isInitialized = false
    
    @Volatile
    private var isRunning = false
    
    companion object {
        @Volatile
        private var instance: GalaxyAgent? = null
        
        /**
         * 获取 GalaxyAgent 单例
         */
        fun getInstance(context: Context): GalaxyAgent {
            return instance ?: synchronized(this) {
                instance ?: GalaxyAgent(context.applicationContext).also { instance = it }
            }
        }
    }
    
    /**
     * 初始化 Agent
     */
    fun initialize(gatewayUrl: String? = null) {
        if (isInitialized) {
            Log.w(TAG, "Agent 已初始化，跳过")
            return
        }
        
        Log.i(TAG, "🚀 正在初始化 UFO³ Galaxy Agent...")
        
        // 更新 Gateway URL
        gatewayUrl?.let { this.gatewayUrl = it }
        
        // 初始化消息处理器（先于 WebSocket，因为 WS 需要引用它）
        // 使用延迟初始化避免循环依赖
        val tempHandler = { message: JSONObject ->
            if (::messageHandler.isInitialized) messageHandler.handleMessage(message)
        }

        // 初始化 WebSocket
        agentWebSocket = AgentWebSocket(
            gatewayUrl = this.gatewayUrl,
            agentRegistry = agentRegistry,
            messageHandler = tempHandler,
            onConnectedCallback = { sendRegistration() },
            onRegistrationResponse = { response -> handleRegistrationResponse(response) }
        )

        messageHandler = AgentMessageHandler(context, agentWebSocket)
        
        isInitialized = true
        Log.i(TAG, "✅ UFO³ Galaxy Agent 初始化完成")
        Log.i(TAG, "   Agent ID: ${agentRegistry.getAgentId()}")
        Log.i(TAG, "   Device ID: ${agentRegistry.getDeviceId()}")
        Log.i(TAG, "   Gateway URL: ${this.gatewayUrl}")
    }
    
    /**
     * 启动 Agent
     *
     * 流程: 连接 WebSocket → onOpen 发送 register 消息 → 服务端回 response → 标记已注册
     * 注册走 WebSocket (AIP/1.0)，而非 HTTP，因为服务端 websocket_handler.py
     * 的 handle_register() 就是处理 WS 消息。
     */
    fun start() {
        if (!isInitialized) {
            Log.e(TAG, "❌ Agent 未初始化，请先调用 initialize()")
            return
        }

        if (isRunning) {
            Log.w(TAG, "Agent 已在运行中")
            return
        }

        Log.i(TAG, "🚀 正在启动 UFO³ Galaxy Agent...")

        scope.launch {
            try {
                // 步骤 1: 检查无障碍服务
                if (!autonomyManager.isAccessibilityServiceEnabled()) {
                    Log.w(TAG, "⚠️ 无障碍服务未启用，部分功能将受限")
                }

                // 步骤 2: 建立 WebSocket 连接
                // 注册会在 WebSocket onOpen 回调中自动进行
                Log.i(TAG, "🔗 正在连接到 Galaxy Gateway...")
                agentWebSocket.connect()

                isRunning = true
                Log.i(TAG, "✅ UFO³ Galaxy Agent 已启动")

            } catch (e: Exception) {
                Log.e(TAG, "❌ Agent 启动失败", e)
            }
        }
    }
    
    /**
     * 停止 Agent
     */
    fun stop() {
        if (!isRunning) {
            Log.w(TAG, "Agent 未运行")
            return
        }
        
        Log.i(TAG, "🛑 正在停止 UFO³ Galaxy Agent...")
        
        // 断开 WebSocket 连接
        agentWebSocket.disconnect()
        
        isRunning = false
        Log.i(TAG, "✅ UFO³ Galaxy Agent 已停止")
    }
    
    /**
     * 重启 Agent
     */
    fun restart() {
        Log.i(TAG, "🔄 正在重启 UFO³ Galaxy Agent...")
        stop()
        delay(1000)
        start()
    }
    
    /**
     * 通过 WebSocket 向 Gateway 注册 (由 AgentWebSocket onOpen 回调触发)
     *
     * 发送 AIP/1.0 register 消息，服务端 websocket_handler.py handle_register()
     * 会返回 type=response 的确认。AgentWebSocket 收到后调 handleRegistrationResponse。
     */
    internal fun sendRegistration() {
        val registrationRequest = agentRegistry.generateRegistrationRequest()
        Log.i(TAG, "📤 通过 WebSocket 发送注册请求: ${registrationRequest.toString(2)}")
        agentWebSocket.sendMessage(registrationRequest)
    }

    /**
     * 处理服务端注册响应
     */
    internal fun handleRegistrationResponse(response: JSONObject) {
        val success = agentRegistry.handleRegistrationResponse(response)
        if (success) {
            Log.i(TAG, "✅ Agent 注册成功")
        } else {
            Log.e(TAG, "❌ Agent 注册失败")
        }
    }
    
    /**
     * 延迟函数（用于重启）
     */
    private suspend fun delay(ms: Long) {
        kotlinx.coroutines.delay(ms)
    }
    
    /**
     * 注销 Agent
     */
    fun unregister() {
        Log.i(TAG, "📝 正在注销 Agent...")
        
        stop()
        agentRegistry.unregister()
        
        Log.i(TAG, "✅ Agent 已注销")
    }
    
    /**
     * 配置 Gateway URL
     */
    fun setGatewayUrl(url: String) {
        this.gatewayUrl = url
        Log.i(TAG, "Gateway URL 已更新: $url")
    }
    
    /**
     * 获取 Agent 状态
     */
    fun getStatus(): JSONObject {
        return JSONObject().apply {
            put("is_initialized", isInitialized)
            put("is_running", isRunning)
            put("is_registered", agentRegistry.isRegistered())
            put("is_connected", if (isInitialized) agentWebSocket.isConnected() else false)
            put("accessibility_enabled", autonomyManager.isAccessibilityServiceEnabled())
            put("agent_id", agentRegistry.getAgentId())
            put("device_id", agentRegistry.getDeviceId())
            put("gateway_url", gatewayUrl)
        }
    }
    
    /**
     * 运行健康检查
     */
    fun runHealthCheck(): JSONObject {
        val result = JSONObject()
        val checks = org.json.JSONArray()
        
        // 检查 1: 初始化状态
        checks.put(JSONObject().apply {
            put("name", "初始化状态")
            put("status", if (isInitialized) "✅ 已初始化" else "❌ 未初始化")
            put("passed", isInitialized)
        })
        
        // 检查 2: 注册状态
        checks.put(JSONObject().apply {
            put("name", "注册状态")
            put("status", if (agentRegistry.isRegistered()) "✅ 已注册" else "❌ 未注册")
            put("passed", agentRegistry.isRegistered())
        })
        
        // 检查 3: WebSocket 连接
        val isConnected = if (isInitialized) agentWebSocket.isConnected() else false
        checks.put(JSONObject().apply {
            put("name", "WebSocket 连接")
            put("status", if (isConnected) "✅ 已连接" else "❌ 未连接")
            put("passed", isConnected)
        })
        
        // 检查 4: 无障碍服务
        val accessibilityEnabled = autonomyManager.isAccessibilityServiceEnabled()
        checks.put(JSONObject().apply {
            put("name", "无障碍服务")
            put("status", if (accessibilityEnabled) "✅ 已启用" else "❌ 未启用")
            put("passed", accessibilityEnabled)
        })
        
        // 检查 5: 自主操纵能力
        val autonomyDiagnostics = autonomyManager.runDiagnostics()
        checks.put(JSONObject().apply {
            put("name", "自主操纵能力")
            put("status", if (autonomyDiagnostics.optString("status") == "success") "✅ 正常" else "❌ 异常")
            put("passed", autonomyDiagnostics.optString("status") == "success")
            put("details", autonomyDiagnostics)
        })
        
        // 计算总体健康状态
        var passedCount = 0
        for (i in 0 until checks.length()) {
            if (checks.getJSONObject(i).optBoolean("passed", false)) {
                passedCount++
            }
        }
        
        result.put("status", if (passedCount == checks.length()) "healthy" else "unhealthy")
        result.put("passed_checks", passedCount)
        result.put("total_checks", checks.length())
        result.put("checks", checks)
        result.put("timestamp", System.currentTimeMillis())
        
        return result
    }
    
    /**
     * 发送消息到 Gateway
     */
    fun sendMessage(message: JSONObject): Boolean {
        if (!isInitialized || !isRunning) {
            Log.w(TAG, "Agent 未运行，无法发送消息")
            return false
        }
        
        return agentWebSocket.sendMessage(message)
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        Log.i(TAG, "🧹 正在清理 Agent 资源...")
        
        stop()
        
        if (isInitialized) {
            messageHandler.cleanup()
            agentWebSocket.cleanup()
            autonomyManager.cleanup()
        }
        
        scope.cancel()
        isInitialized = false
        
        Log.i(TAG, "✅ Agent 资源已清理")
    }
}
