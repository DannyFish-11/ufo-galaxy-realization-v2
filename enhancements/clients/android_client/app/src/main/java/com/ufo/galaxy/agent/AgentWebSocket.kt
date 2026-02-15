package com.ufo.galaxy.agent

import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Galaxy Agent WebSocket 长连接管理器
 * 
 * 功能：
 * 1. 建立和维护与 Galaxy Gateway 的 WebSocket 长连接
 * 2. 自动重连机制
 * 3. 心跳保活（每 30 秒发送一次心跳）
 * 4. 消息发送和接收
 * 5. 连接状态管理
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class AgentWebSocket(
    private val gatewayUrl: String,
    private val agentRegistry: AgentRegistry,
    private val messageHandler: (JSONObject) -> Unit
) {
    
    private val TAG = "AgentWebSocket"
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    private var webSocket: WebSocket? = null
    private var heartbeatJob: Job? = null
    private var reconnectJob: Job? = null
    
    private val okHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .pingInterval(20, TimeUnit.SECONDS) // OkHttp 自动 ping
        .build()
    
    @Volatile
    private var isConnected = false
    
    @Volatile
    private var isConnecting = false
    
    @Volatile
    private var shouldReconnect = true
    
    private var reconnectAttempts = 0
    private val maxReconnectAttempts = 10
    private val reconnectDelays = listOf(1000L, 2000L, 5000L, 10000L, 30000L) // 递增延迟
    
    /**
     * 连接到 Gateway
     */
    fun connect() {
        if (isConnected || isConnecting) {
            Log.w(TAG, "已连接或正在连接中，跳过")
            return
        }
        
        isConnecting = true
        shouldReconnect = true
        reconnectAttempts = 0
        
        Log.i(TAG, "开始连接到 Galaxy Gateway: $gatewayUrl")
        
        val request = Request.Builder()
            .url(gatewayUrl)
            .addHeader("X-Agent-ID", agentRegistry.getAgentId())
            .addHeader("X-Agent-Token", agentRegistry.getAgentToken() ?: "")
            .build()
        
        webSocket = okHttpClient.newWebSocket(request, webSocketListener)
    }
    
    /**
     * 断开连接
     */
    fun disconnect() {
        Log.i(TAG, "主动断开连接")
        shouldReconnect = false
        stopHeartbeat()
        stopReconnect()
        
        webSocket?.close(1000, "Client disconnect")
        webSocket = null
        isConnected = false
        isConnecting = false
    }
    
    /**
     * 发送消息
     */
    fun sendMessage(message: JSONObject): Boolean {
        if (!isConnected) {
            Log.w(TAG, "未连接，无法发送消息")
            return false
        }
        
        return try {
            val success = webSocket?.send(message.toString()) ?: false
            if (success) {
                Log.d(TAG, "消息已发送: ${message.optString("type", "unknown")}")
            } else {
                Log.w(TAG, "消息发送失败")
            }
            success
        } catch (e: Exception) {
            Log.e(TAG, "发送消息异常", e)
            false
        }
    }
    
    /**
     * 发送心跳
     */
    private fun sendHeartbeat() {
        val heartbeat = agentRegistry.generateHeartbeatData()
        sendMessage(heartbeat)
        agentRegistry.updateHeartbeat()
    }
    
    /**
     * 启动心跳
     */
    private fun startHeartbeat() {
        stopHeartbeat()
        
        heartbeatJob = scope.launch {
            while (isActive && isConnected) {
                try {
                    sendHeartbeat()
                    delay(30000) // 每 30 秒一次心跳
                } catch (e: Exception) {
                    Log.e(TAG, "心跳发送异常", e)
                }
            }
        }
        
        Log.i(TAG, "✅ 心跳已启动")
    }
    
    /**
     * 停止心跳
     */
    private fun stopHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = null
    }
    
    /**
     * 尝试重连
     */
    private fun scheduleReconnect() {
        if (!shouldReconnect) {
            Log.i(TAG, "不需要重连")
            return
        }
        
        if (reconnectAttempts >= maxReconnectAttempts) {
            Log.e(TAG, "❌ 重连次数已达上限 ($maxReconnectAttempts)，停止重连")
            return
        }
        
        stopReconnect()
        
        val delayIndex = minOf(reconnectAttempts, reconnectDelays.size - 1)
        val delay = reconnectDelays[delayIndex]
        
        reconnectAttempts++
        Log.i(TAG, "将在 ${delay}ms 后进行第 $reconnectAttempts 次重连...")
        
        reconnectJob = scope.launch {
            delay(delay)
            if (shouldReconnect && !isConnected) {
                isConnecting = false
                connect()
            }
        }
    }
    
    /**
     * 停止重连
     */
    private fun stopReconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
    }
    
    /**
     * 检查是否已连接
     */
    fun isConnected(): Boolean = isConnected
    
    /**
     * 清理资源
     */
    fun cleanup() {
        disconnect()
        scope.cancel()
        okHttpClient.dispatcher.executorService.shutdown()
        okHttpClient.connectionPool.evictAll()
    }
    
    /**
     * WebSocket 监听器
     */
    private val webSocketListener = object : WebSocketListener() {
        
        override fun onOpen(webSocket: WebSocket, response: Response) {
            Log.i(TAG, "✅ WebSocket 连接已建立")
            isConnected = true
            isConnecting = false
            reconnectAttempts = 0
            
            // 启动心跳
            startHeartbeat()
            
            // 发送初始心跳
            sendHeartbeat()
        }
        
        override fun onMessage(webSocket: WebSocket, text: String) {
            Log.d(TAG, "📨 收到消息: ${text.take(100)}...")
            
            try {
                val message = JSONObject(text)
                
                // 在主线程处理消息
                scope.launch(Dispatchers.Main) {
                    messageHandler(message)
                }
                
            } catch (e: Exception) {
                Log.e(TAG, "解析消息失败", e)
            }
        }
        
        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            Log.w(TAG, "⚠️ WebSocket 正在关闭: code=$code, reason=$reason")
            webSocket.close(1000, null)
        }
        
        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            Log.w(TAG, "❌ WebSocket 已关闭: code=$code, reason=$reason")
            isConnected = false
            isConnecting = false
            stopHeartbeat()
            
            // 尝试重连
            if (shouldReconnect) {
                scheduleReconnect()
            }
        }
        
        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            Log.e(TAG, "❌ WebSocket 连接失败: ${t.message}", t)
            isConnected = false
            isConnecting = false
            stopHeartbeat()
            
            // 尝试重连
            if (shouldReconnect) {
                scheduleReconnect()
            }
        }
    }
}
