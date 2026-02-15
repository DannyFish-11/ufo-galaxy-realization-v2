package com.ufo.galaxy.client

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * 增强版 AIP 客户端
 * 
 * 新增功能：
 * 1. 支持微软 Galaxy 的消息格式
 * 2. 自动消息格式转换（AIP/1.0 <-> Microsoft AIP）
 * 3. 增强的能力声明
 * 4. 支持 MCP 工具注册
 */
class EnhancedAIPClient(
    private val deviceId: String,
    private val galaxyUrl: String,  // 微软 Galaxy 的 WebSocket 地址
    private val context: android.content.Context,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO)
) {
    private val commandExecutor = AndroidCommandExecutor(context)
    private val TAG = "EnhancedAIPClient"
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var webSocket: WebSocket? = null
    private var reconnectJob: Job? = null
    private var isRegistered = false

    // 消息类型映射：我们的格式 -> 微软格式
    private val typeMapping = mapOf(
        "registration" to "REGISTER",
        "command" to "TASK",
        "command_result" to "COMMAND_RESULTS",
        "status_update" to "TASK_END",
        "heartbeat" to "HEARTBEAT"
    )

    // 消息类型映射：微软格式 -> 我们的格式
    private val reversTypeMapping = mapOf(
        "REGISTER" to "registration",
        "TASK" to "command",
        "COMMAND" to "command",
        "COMMAND_RESULTS" to "command_result",
        "TASK_END" to "status_update",
        "HEARTBEAT" to "heartbeat"
    )

    private val wsListener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            Log.i(TAG, "Connected to Microsoft UFO Galaxy.")
            this@EnhancedAIPClient.webSocket = webSocket
            reconnectJob?.cancel()
            sendEnhancedRegistration()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            Log.d(TAG, "Received message: $text")
            handleMicrosoftAIPMessage(text)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            Log.w(TAG, "Connection closing: $code / $reason")
            this@EnhancedAIPClient.webSocket = null
            isRegistered = false
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            Log.e(TAG, "Connection failed: ${t.message}", t)
            this@EnhancedAIPClient.webSocket = null
            isRegistered = false
            startReconnectLoop()
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            Log.i(TAG, "Connection closed: $code / $reason")
            this@EnhancedAIPClient.webSocket = null
            isRegistered = false
            startReconnectLoop()
        }
    }

    fun connect() {
        val wsUrl = "$galaxyUrl/ws/device/$deviceId"
        val request = Request.Builder().url(wsUrl).build()
        Log.i(TAG, "Connecting to Microsoft Galaxy at $wsUrl...")
        client.newWebSocket(request, wsListener)
    }

    fun disconnect() {
        reconnectJob?.cancel()
        webSocket?.close(1000, "Client disconnect requested")
        webSocket = null
        isRegistered = false
    }

    private fun startReconnectLoop() {
        if (reconnectJob?.isActive == true) return
        
        reconnectJob = scope.launch {
            while (isActive) {
                Log.i(TAG, "Attempting to reconnect in 5 seconds...")
                delay(5000)
                if (webSocket == null) {
                    connect()
                } else {
                    break
                }
            }
        }
    }

    /**
     * 发送增强的注册消息（符合微软 Galaxy 的 AgentProfile 格式）
     */
    private fun sendEnhancedRegistration() {
        val microsoftMessage = JSONObject().apply {
            put("message_type", "REGISTER")
            put("agent_id", deviceId)
            put("session_id", null)
            put("payload", JSONObject().apply {
                put("platform", "android")
                put("os_version", android.os.Build.VERSION.RELEASE)
                put("hardware", JSONObject().apply {
                    put("manufacturer", android.os.Build.MANUFACTURER)
                    put("model", android.os.Build.MODEL)
                    put("device", android.os.Build.DEVICE)
                })
                put("tools", JSONArray().apply {
                    // Android 特有能力
                    put("location")
                    put("camera")
                    put("sensor_data")
                    put("automation")
                    put("notification")
                    put("sms")
                    put("phone_call")
                    put("contacts")
                    put("calendar")
                    // 增强能力
                    put("voice_input")
                    put("screen_capture")
                    put("app_control")
                })
                put("capabilities", JSONObject().apply {
                    put("nlu", false)  // Android 端不做 NLU，交给 Galaxy
                    put("hardware_control", true)
                    put("sensor_access", true)
                    put("network_access", true)
                    put("ui_automation", true)
                })
            })
        }.toString()

        webSocket?.send(microsoftMessage) ?: Log.e(TAG, "WebSocket is null. Registration failed.")
        Log.i(TAG, "Enhanced registration message sent to Microsoft Galaxy.")
    }

    /**
     * 将我们的 AIP/1.0 消息转换为微软 AIP 格式
     */
    private fun convertToMicrosoftAIP(ourMessage: JSONObject): JSONObject {
        val messageType = typeMapping[ourMessage.getString("type")] ?: "TASK"
        
        return JSONObject().apply {
            put("message_type", messageType)
            put("agent_id", ourMessage.optString("source_node", deviceId))
            put("session_id", ourMessage.optLong("timestamp", System.currentTimeMillis()))
            put("payload", ourMessage.getJSONObject("payload"))
        }
    }

    /**
     * 将微软 AIP 消息转换为我们的 AIP/1.0 格式
     */
    private fun convertFromMicrosoftAIP(microsoftMessage: JSONObject): JSONObject {
        val messageType = reversTypeMapping[microsoftMessage.getString("message_type")] ?: "command"
        
        return JSONObject().apply {
            put("protocol", "AIP/1.0")
            put("type", messageType)
            put("source_node", microsoftMessage.optString("agent_id", "Galaxy"))
            put("target_node", deviceId)
            put("timestamp", microsoftMessage.optLong("session_id", System.currentTimeMillis()) / 1000)
            put("payload", microsoftMessage.getJSONObject("payload"))
        }
    }

    /**
     * 处理来自微软 Galaxy 的消息
     */
    private fun handleMicrosoftAIPMessage(text: String) {
        try {
            val microsoftMessage = JSONObject(text)
            
            // 转换为我们的格式
            val ourMessage = convertFromMicrosoftAIP(microsoftMessage)
            
            // 处理消息
            val msgType = ourMessage.getString("type")
            val payload = ourMessage.getJSONObject("payload")

            when (msgType) {
                "command" -> {
                    val command = payload.optString("command", payload.optString("action"))
                    val params = payload.optJSONObject("params") ?: JSONObject()
                    Log.i(TAG, "Executing command from Galaxy: $command")
                    
                    // 执行命令
                    val result = executeAndroidCommand(command, params)
                    
                    // 发送结果（转换为微软格式）
                    sendCommandResult(command, result)
                }
                "heartbeat" -> {
                    // 响应心跳
                    sendHeartbeat()
                }
                else -> Log.w(TAG, "Unhandled message type: $msgType")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error handling Microsoft AIP message: ${e.message}", e)
        }
    }

    /**
     * 执行 Android 命令
     */
    private fun executeAndroidCommand(command: String, params: JSONObject): JSONObject {
        return commandExecutor.executeCommand(command, params)
    }

    /**
     * 发送命令执行结果
     */
    private fun sendCommandResult(command: String, result: JSONObject) {
        val ourMessage = JSONObject().apply {
            put("protocol", "AIP/1.0")
            put("type", "command_result")
            put("source_node", deviceId)
            put("target_node", "Galaxy")
            put("timestamp", System.currentTimeMillis() / 1000)
            put("payload", result)
        }
        
        // 转换为微软格式
        val microsoftMessage = convertToMicrosoftAIP(ourMessage)
        
        webSocket?.send(microsoftMessage.toString()) ?: Log.e(TAG, "WebSocket is null. Result not sent.")
    }

    /**
     * 发送心跳
     */
    private fun sendHeartbeat() {
        val microsoftMessage = JSONObject().apply {
            put("message_type", "HEARTBEAT")
            put("agent_id", deviceId)
            put("session_id", System.currentTimeMillis())
            put("payload", JSONObject().apply {
                put("status", "online")
                put("timestamp", System.currentTimeMillis() / 1000)
            })
        }.toString()
        
        webSocket?.send(microsoftMessage) ?: Log.e(TAG, "WebSocket is null. Heartbeat not sent.")
    }

    /**
     * 发送自定义消息（自动转换格式）
     */
    fun sendMessage(messageType: String, payload: JSONObject) {
        val ourMessage = JSONObject().apply {
            put("protocol", "AIP/1.0")
            put("type", messageType)
            put("source_node", deviceId)
            put("target_node", "Galaxy")
            put("timestamp", System.currentTimeMillis() / 1000)
            put("payload", payload)
        }
        
        // 转换为微软格式
        val microsoftMessage = convertToMicrosoftAIP(ourMessage)
        
        webSocket?.send(microsoftMessage.toString()) ?: Log.e(TAG, "WebSocket is null. Message not sent.")
    }
}
