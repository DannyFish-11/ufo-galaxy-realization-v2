package com.ufo.galaxy.network

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.ufo.galaxy.data.AIPMessage
import com.ufo.galaxy.data.AIPMessageType
import kotlinx.coroutines.*
import okhttp3.*
import java.util.concurrent.TimeUnit

/**
 * Galaxy WebSocket 客户端
 * 负责与 Galaxy 服务器的实时通信
 */
class GalaxyWebSocketClient(
    private val serverUrl: String
) {
    companion object {
        private const val TAG = "GalaxyWebSocket"
        private const val RECONNECT_DELAY_MS = 5000L
        private const val HEARTBEAT_INTERVAL_MS = 30000L
        private const val MAX_RECONNECT_ATTEMPTS = 5
    }
    
    /**
     * WebSocket 监听器接口
     */
    interface Listener {
        fun onConnected()
        fun onDisconnected()
        fun onMessage(message: String)
        fun onError(error: String)
    }
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()
    
    private val gson = Gson()
    private var webSocket: WebSocket? = null
    private var listener: Listener? = null
    private var isConnected = false
    private var reconnectAttempts = 0
    private var heartbeatJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    /**
     * 设置监听器
     */
    fun setListener(listener: Listener) {
        this.listener = listener
    }
    
    /**
     * 连接到服务器
     */
    fun connect() {
        if (isConnected) {
            Log.d(TAG, "已连接，跳过")
            return
        }
        
        Log.i(TAG, "连接到服务器: $serverUrl")
        
        val request = Request.Builder()
            .url(serverUrl)
            .build()
        
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket 已打开")
                isConnected = true
                reconnectAttempts = 0
                listener?.onConnected()
                startHeartbeat()
                
                // 发送握手消息
                sendHandshake()
            }
            
            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "收到消息: ${text.take(100)}...")
                handleMessage(text)
            }
            
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket 正在关闭: $code - $reason")
                webSocket.close(1000, null)
            }
            
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket 已关闭: $code - $reason")
                isConnected = false
                stopHeartbeat()
                listener?.onDisconnected()
                
                // 尝试重连
                if (code != 1000) {
                    scheduleReconnect()
                }
            }
            
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket 失败: ${t.message}", t)
                isConnected = false
                stopHeartbeat()
                listener?.onError(t.message ?: "连接失败")
                
                // 尝试重连
                scheduleReconnect()
            }
        })
    }
    
    /**
     * 断开连接
     */
    fun disconnect() {
        Log.i(TAG, "断开连接")
        stopHeartbeat()
        webSocket?.close(1000, "用户断开")
        webSocket = null
        isConnected = false
    }
    
    /**
     * 发送文本消息
     */
    fun send(text: String): Boolean {
        if (!isConnected) {
            Log.w(TAG, "未连接，无法发送")
            return false
        }
        
        val message = AIPMessage(
            type = AIPMessageType.TEXT,
            payload = mapOf("content" to text)
        )
        
        return sendAIPMessage(message)
    }
    
    /**
     * 发送 AIP 消息
     */
    fun sendAIPMessage(message: AIPMessage): Boolean {
        if (!isConnected) {
            Log.w(TAG, "未连接，无法发送")
            return false
        }
        
        val json = gson.toJson(message)
        Log.d(TAG, "发送消息: ${json.take(100)}...")
        
        return webSocket?.send(json) ?: false
    }
    
    /**
     * 发送握手消息
     */
    private fun sendHandshake() {
        val handshake = JsonObject().apply {
            addProperty("type", "handshake")
            addProperty("version", "2.0")
            addProperty("platform", "android")
            addProperty("device_id", android.os.Build.MODEL)
        }
        
        webSocket?.send(gson.toJson(handshake))
    }
    
    /**
     * 处理收到的消息
     */
    private fun handleMessage(text: String) {
        try {
            val json = gson.fromJson(text, JsonObject::class.java)
            
            when (json.get("type")?.asString) {
                "heartbeat_ack" -> {
                    Log.d(TAG, "收到心跳响应")
                }
                "response" -> {
                    val content = json.getAsJsonObject("payload")
                        ?.get("content")?.asString ?: text
                    listener?.onMessage(content)
                }
                "error" -> {
                    val error = json.get("message")?.asString ?: "未知错误"
                    listener?.onError(error)
                }
                else -> {
                    // 默认作为文本消息处理
                    val content = json.getAsJsonObject("payload")
                        ?.get("content")?.asString ?: text
                    listener?.onMessage(content)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "解析消息失败", e)
            // 作为纯文本处理
            listener?.onMessage(text)
        }
    }
    
    /**
     * 启动心跳
     */
    private fun startHeartbeat() {
        heartbeatJob = scope.launch {
            while (isActive && isConnected) {
                delay(HEARTBEAT_INTERVAL_MS)
                sendHeartbeat()
            }
        }
    }
    
    /**
     * 停止心跳
     */
    private fun stopHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = null
    }
    
    /**
     * 发送心跳
     */
    private fun sendHeartbeat() {
        val heartbeat = JsonObject().apply {
            addProperty("type", "heartbeat")
            addProperty("timestamp", System.currentTimeMillis())
        }
        
        webSocket?.send(gson.toJson(heartbeat))
    }
    
    /**
     * 安排重连
     */
    private fun scheduleReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            Log.w(TAG, "达到最大重连次数")
            listener?.onError("无法连接到服务器")
            return
        }
        
        reconnectAttempts++
        Log.i(TAG, "将在 ${RECONNECT_DELAY_MS}ms 后重连 (尝试 $reconnectAttempts/$MAX_RECONNECT_ATTEMPTS)")
        
        scope.launch {
            delay(RECONNECT_DELAY_MS)
            connect()
        }
    }
    
    /**
     * 是否已连接
     */
    fun isConnected(): Boolean = isConnected
}
