package com.ufo.galaxy.api

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * UFO³ Galaxy API 客户端
 * 
 * 负责与 Galaxy Gateway 进行通信，支持：
 * - HTTP REST API 调用
 * - WebSocket 实时通信
 * - 节点推送和订阅
 * - 智能路由和负载均衡
 * 
 * @author Manus AI
 * @date 2026-01-22
 */
class GalaxyApiClient(
    private val baseUrl: String = "http://100.123.215.126:8888",
    private val apiKey: String? = null
) {
    
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()
    
    private var webSocket: WebSocket? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    
    // 连接状态流
    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()
    
    // 消息流
    private val _messages = MutableSharedFlow<GalaxyMessage>()
    val messages: SharedFlow<GalaxyMessage> = _messages.asSharedFlow()
    
    // 节点状态流
    private val _nodeStatus = MutableStateFlow<Map<String, NodeStatus>>(emptyMap())
    val nodeStatus: StateFlow<Map<String, NodeStatus>> = _nodeStatus.asStateFlow()
    
    /**
     * 连接状态枚举
     */
    enum class ConnectionState {
        DISCONNECTED,
        CONNECTING,
        CONNECTED,
        ERROR
    }
    
    /**
     * 初始化客户端
     */
    fun initialize() {
        scope.launch {
            connectWebSocket()
        }
    }
    
    /**
     * 连接 WebSocket
     */
    private fun connectWebSocket() {
        _connectionState.value = ConnectionState.CONNECTING
        
        val request = Request.Builder()
            .url("$baseUrl/ws")
            .apply {
                apiKey?.let { addHeader("Authorization", "Bearer $it") }
            }
            .build()
        
        webSocket = httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                _connectionState.value = ConnectionState.CONNECTED
                scope.launch {
                    _messages.emit(GalaxyMessage.SystemMessage("WebSocket 连接已建立"))
                }
            }
            
            override fun onMessage(webSocket: WebSocket, text: String) {
                scope.launch {
                    handleWebSocketMessage(text)
                }
            }
            
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                _connectionState.value = ConnectionState.ERROR
                scope.launch {
                    _messages.emit(GalaxyMessage.ErrorMessage("连接失败: ${t.message}"))
                }
                
                // 5秒后重连
                scope.launch {
                    delay(5000)
                    connectWebSocket()
                }
            }
            
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                _connectionState.value = ConnectionState.DISCONNECTED
            }
        })
    }
    
    /**
     * 处理 WebSocket 消息
     */
    private suspend fun handleWebSocketMessage(text: String) {
        try {
            val json = JSONObject(text)
            val type = json.optString("type")
            
            when (type) {
                "node_status" -> {
                    val nodeId = json.optString("node_id")
                    val status = json.optString("status")
                    val data = json.optJSONObject("data")
                    
                    val currentStatus = _nodeStatus.value.toMutableMap()
                    currentStatus[nodeId] = NodeStatus(
                        nodeId = nodeId,
                        status = status,
                        lastUpdate = System.currentTimeMillis(),
                        data = data?.toString()
                    )
                    _nodeStatus.value = currentStatus
                }
                
                "message" -> {
                    val content = json.optString("content")
                    val role = json.optString("role", "assistant")
                    _messages.emit(GalaxyMessage.ChatMessage(role, content))
                }
                
                "notification" -> {
                    val title = json.optString("title")
                    val body = json.optString("body")
                    _messages.emit(GalaxyMessage.NotificationMessage(title, body))
                }
                
                "error" -> {
                    val error = json.optString("error")
                    _messages.emit(GalaxyMessage.ErrorMessage(error))
                }
            }
        } catch (e: Exception) {
            _messages.emit(GalaxyMessage.ErrorMessage("解析消息失败: ${e.message}"))
        }
    }
    
    /**
     * 发送聊天消息
     */
    suspend fun sendChatMessage(
        message: String,
        model: String = "auto",
        provider: String? = null
    ): Result<ChatResponse> = withContext(Dispatchers.IO) {
        try {
            val json = JSONObject().apply {
                put("messages", JSONArray().apply {
                    put(JSONObject().apply {
                        put("role", "user")
                        put("content", message)
                    })
                })
                put("model", model)
                provider?.let { put("provider", it) }
            }
            
            val requestBody = json.toString()
                .toRequestBody("application/json".toMediaType())
            
            val request = Request.Builder()
                .url("$baseUrl/api/llm/chat")
                .post(requestBody)
                .apply {
                    apiKey?.let { addHeader("Authorization", "Bearer $it") }
                }
                .build()
            
            val response = httpClient.newCall(request).execute()
            val responseBody = response.body?.string() ?: ""
            
            if (response.isSuccessful) {
                val responseJson = JSONObject(responseBody)
                val choices = responseJson.getJSONArray("choices")
                val firstChoice = choices.getJSONObject(0)
                val messageObj = firstChoice.getJSONObject("message")
                val content = messageObj.getString("content")
                val usedProvider = responseJson.optString("provider", "unknown")
                
                Result.success(ChatResponse(
                    content = content,
                    provider = usedProvider,
                    model = model
                ))
            } else {
                Result.failure(Exception("API 调用失败: ${response.code} - $responseBody"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 调用指定节点
     */
    suspend fun invokeNode(
        nodeId: String,
        method: String,
        params: Map<String, Any>
    ): Result<JSONObject> = withContext(Dispatchers.IO) {
        try {
            val json = JSONObject().apply {
                put("method", method)
                put("params", JSONObject(params))
            }
            
            val requestBody = json.toString()
                .toRequestBody("application/json".toMediaType())
            
            val request = Request.Builder()
                .url("$baseUrl/api/node/$nodeId/invoke")
                .post(requestBody)
                .apply {
                    apiKey?.let { addHeader("Authorization", "Bearer $it") }
                }
                .build()
            
            val response = httpClient.newCall(request).execute()
            val responseBody = response.body?.string() ?: ""
            
            if (response.isSuccessful) {
                Result.success(JSONObject(responseBody))
            } else {
                Result.failure(Exception("节点调用失败: ${response.code} - $responseBody"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 获取系统健康状态
     */
    suspend fun getHealthStatus(): Result<HealthStatus> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseUrl/health")
                .get()
                .build()
            
            val response = httpClient.newCall(request).execute()
            val responseBody = response.body?.string() ?: ""
            
            if (response.isSuccessful) {
                val json = JSONObject(responseBody)
                Result.success(HealthStatus(
                    status = json.optString("status", "unknown"),
                    version = json.optString("version", "unknown"),
                    uptime = json.optLong("uptime", 0),
                    providers = json.optJSONObject("providers")?.let { providersJson ->
                        providersJson.keys().asSequence().associateWith { key ->
                            providersJson.getString(key)
                        }
                    } ?: emptyMap()
                ))
            } else {
                Result.failure(Exception("健康检查失败: ${response.code}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 订阅节点状态更新
     */
    fun subscribeToNode(nodeId: String) {
        webSocket?.send(JSONObject().apply {
            put("type", "subscribe")
            put("node_id", nodeId)
        }.toString())
    }
    
    /**
     * 取消订阅节点
     */
    fun unsubscribeFromNode(nodeId: String) {
        webSocket?.send(JSONObject().apply {
            put("type", "unsubscribe")
            put("node_id", nodeId)
        }.toString())
    }
    
    /**
     * 关闭客户端
     */
    fun close() {
        webSocket?.close(1000, "Client closing")
        scope.cancel()
    }
}

/**
 * Galaxy 消息类型
 */
sealed class GalaxyMessage {
    data class ChatMessage(val role: String, val content: String) : GalaxyMessage()
    data class SystemMessage(val content: String) : GalaxyMessage()
    data class NotificationMessage(val title: String, val body: String) : GalaxyMessage()
    data class ErrorMessage(val error: String) : GalaxyMessage()
}

/**
 * 聊天响应
 */
data class ChatResponse(
    val content: String,
    val provider: String,
    val model: String
)

/**
 * 节点状态
 */
data class NodeStatus(
    val nodeId: String,
    val status: String,
    val lastUpdate: Long,
    val data: String?
)

/**
 * 健康状态
 */
data class HealthStatus(
    val status: String,
    val version: String,
    val uptime: Long,
    val providers: Map<String, String>
)
