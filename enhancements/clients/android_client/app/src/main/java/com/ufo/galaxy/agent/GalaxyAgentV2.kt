package com.ufo.galaxy.agent

import android.content.Context
import android.util.Log
import com.ufo.galaxy.autonomy.AutonomyManager
import com.ufo.galaxy.client.Node50Client
import com.ufo.galaxy.executor.TaskExecutor
import com.ufo.galaxy.network.TailscaleAdapter
import com.ufo.galaxy.protocol.AIPProtocol
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject

/**
 * Galaxy Agent V2
 * 
 * UFO³ Galaxy Android Agent 的主控制器（第二版）
 * 集成了完整的任务执行能力
 * 
 * 功能：
 * - 连接到 Node 50
 * - 接收和执行任务
 * - 返回执行结果
 * - 跨设备协同
 * 
 * @author Manus AI
 * @version 2.0
 * @date 2026-01-22
 */
class GalaxyAgentV2(private val context: Context) {
    
    private val TAG = "GalaxyAgentV2"
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    
    private val tailscaleAdapter = TailscaleAdapter(context)
    private val autonomyManager = AutonomyManager(context)
    private val taskExecutor = TaskExecutor(context, autonomyManager)
    
    private var node50Client: Node50Client? = null
    
    @Volatile
    private var isRunning = false
    
    // 状态流
    private val _status = MutableStateFlow("未启动")
    val status: StateFlow<String> = _status
    
    /**
     * 启动 Agent
     */
    fun start() {
        if (isRunning) {
            Log.w(TAG, "Agent 已经在运行中")
            return
        }
        
        Log.i(TAG, "🚀 启动 UFO³ Galaxy Android Agent V2")
        isRunning = true
        _status.value = "正在启动..."
        
        scope.launch {
            try {
                // 1. 自适应配置
                Log.i(TAG, "🔧 开始自适应配置...")
                _status.value = "正在配置网络..."
                val configured = tailscaleAdapter.autoConfig()
                
                if (!configured) {
                    Log.w(TAG, "⚠️ 自适应配置失败，请手动配置")
                    _status.value = "配置失败"
                    return@launch
                }
                _status.value = "网络配置完成"
                
                // 2. 获取 Node 50 URL
                val node50Url = tailscaleAdapter.getNode50Url()
                if (node50Url == null) {
                    Log.e(TAG, "❌ 无法获取 Node 50 地址")
                    _status.value = "错误: 未找到 Node 50"
                    return@launch
                }
                _status.value = "找到 Node 50: $node50Url"
                
                Log.i(TAG, "✅ Node 50 地址: $node50Url")
                
                // 3. 创建 Node50Client
                node50Client = Node50Client(
                    context = context,
                    node50Url = node50Url,
                    messageHandler = ::handleMessage
                )
                
                // 4. 连接到 Node 50
                _status.value = "正在连接..."
                node50Client?.connect()
                
                _status.value = "✅ 已连接到 Galaxy 系统"
                Log.i(TAG, "✅ UFO³ Galaxy Android Agent V2 启动完成")
                
            } catch (e: Exception) {
                Log.e(TAG, "❌ Agent 启动失败", e)
                _status.value = "错误: ${e.message}"
                isRunning = false
            }
        }
    }
    
    /**
     * 停止 Agent
     */
    fun stop() {
        Log.i(TAG, "🛑 停止 UFO³ Galaxy Android Agent V2")
        
        isRunning = false
        node50Client?.disconnect()
        node50Client?.cleanup()
        node50Client = null
        _status.value = "已停止"
        
        Log.i(TAG, "✅ Agent 已停止")
    }
    
    /**
     * 处理来自 Node 50 的消息
     */
    private fun handleMessage(message: JSONObject) {
        scope.launch {
            try {
                val messageType = AIPProtocol.getMessageType(message)
                val messageId = AIPProtocol.getMessageId(message)
                
                Log.i(TAG, "📨 收到消息: type=$messageType, id=$messageId")
                
                when (messageType) {
                    AIPProtocol.MessageType.COMMAND -> {
                        // 执行任务
                        handleTaskCommand(message)
                    }
                    
                    AIPProtocol.MessageType.RESPONSE -> {
                        // 处理响应
                        handleResponse(message)
                    }
                    
                    AIPProtocol.MessageType.STATUS -> {
                        // 处理状态查询
                        handleStatusQuery(message)
                    }
                    
                    else -> {
                        Log.w(TAG, "⚠️ 未知消息类型: $messageType")
                    }
                }
                
            } catch (e: Exception) {
                Log.e(TAG, "❌ 消息处理失败", e)
            }
        }
    }
    
    /**
     * 处理任务命令
     */
    private suspend fun handleTaskCommand(message: JSONObject) {
        withContext(Dispatchers.Default) {
            try {
                val messageId = AIPProtocol.getMessageId(message) ?: "unknown"
                
                Log.i(TAG, "🎯 开始执行任务: $messageId")
                
                // 执行任务
                val result = taskExecutor.executeTask(message)
                
                // 发送响应
                val responseMessage = AIPProtocol.createResponseMessage(messageId, result)
                node50Client?.sendMessage(responseMessage)
                
                Log.i(TAG, "✅ 任务执行完成并已回传结果")
                
            } catch (e: Exception) {
                Log.e(TAG, "❌ 任务执行失败", e)
                
                // 发送错误响应
                val messageId = AIPProtocol.getMessageId(message) ?: "unknown"
                val errorMessage = AIPProtocol.createErrorMessage(
                    messageId,
                    "任务执行失败: ${e.message}"
                )
                node50Client?.sendMessage(errorMessage)
            }
        }
    }
    
    /**
     * 处理响应
     */
    private fun handleResponse(message: JSONObject) {
        val payload = AIPProtocol.getPayload(message)
        Log.i(TAG, "📬 收到响应: ${payload?.toString(2)}")
        
        // 根据响应类型进行处理
        // 例如：注册成功、任务接收确认等
    }
    
    /**
     * 处理状态查询
     */
    private suspend fun handleStatusQuery(message: JSONObject) {
        withContext(Dispatchers.Default) {
            try {
                val messageId = AIPProtocol.getMessageId(message) ?: "unknown"
                
                // 收集 Agent 状态
                val status = JSONObject().apply {
                    put("agent_id", AIPProtocol.CLIENT_ID)
                    put("running", isRunning)
                    put("connected", node50Client?.isConnected() ?: false)
                    put("registered", node50Client?.isRegistered() ?: false)
                    put("autonomy_enabled", autonomyManager.isEnabled())
                    put("device_info", AIPProtocol.getDeviceInfo())
                    put("capabilities", AIPProtocol.getCapabilities())
                    put("timestamp", System.currentTimeMillis())
                }
                
                // 发送状态响应
                val responseMessage = AIPProtocol.createResponseMessage(messageId, status)
                node50Client?.sendMessage(responseMessage)
                
                Log.i(TAG, "✅ 状态已上报")
                
            } catch (e: Exception) {
                Log.e(TAG, "❌ 状态查询处理失败", e)
            }
        }
    }
    
    /**
     * 发送命令到 Node 50
     */
    fun sendCommand(command: String): Boolean {
        if (!isRunning) {
            Log.w(TAG, "⚠️ Agent 未运行")
            return false
        }
        
        return node50Client?.sendCommand(command) ?: false
    }
    
    /**
     * 获取 Agent 状态
     */
    fun getStatus(): JSONObject {
        return JSONObject().apply {
            put("running", isRunning)
            put("connected", node50Client?.isConnected() ?: false)
            put("registered", node50Client?.isRegistered() ?: false)
            put("node50_url", tailscaleAdapter.getNode50Url())
        }
    }
    
    /**
     * 健康检查
     */
    suspend fun healthCheck(): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                if (!isRunning) {
                    return@withContext false
                }
                
                // 检查 Node 50 连接
                val node50Healthy = node50Client?.checkHealth() ?: false
                
                // 检查 Autonomy 服务
                val autonomyHealthy = autonomyManager.isEnabled()
                
                node50Healthy && autonomyHealthy
                
            } catch (e: Exception) {
                Log.e(TAG, "❌ 健康检查失败", e)
                false
            }
        }
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        stop()
        taskExecutor.cleanup()
        autonomyManager.cleanup()
        scope.cancel()
    }
}
