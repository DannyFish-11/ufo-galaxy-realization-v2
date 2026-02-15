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
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class AIPClient(
    private val deviceId: String,
    private val node50Url: String,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO)
) {
    private val TAG = "AIPClient"
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var webSocket: WebSocket? = null
    private var reconnectJob: Job? = null

    private val wsListener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            Log.i(TAG, "Connection established to Node 50.")
            this@AIPClient.webSocket = webSocket
            reconnectJob?.cancel()
            sendRegistration()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            Log.d(TAG, "Received message: $text")
            handleAIPMessage(text)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            Log.w(TAG, "Connection closing: $code / $reason")
            this@AIPClient.webSocket = null
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            Log.e(TAG, "Connection failed: ${t.message}", t)
            this@AIPClient.webSocket = null
            startReconnectLoop()
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            Log.i(TAG, "Connection closed: $code / $reason")
            this@AIPClient.webSocket = null
            startReconnectLoop()
        }
    }

    fun connect() {
        val wsUrl = "$node50Url/ws/ufo3/$deviceId"
        val request = Request.Builder().url(wsUrl).build()
        Log.i(TAG, "Connecting to $wsUrl...")
        client.newWebSocket(request, wsListener)
    }

    fun disconnect() {
        reconnectJob?.cancel()
        webSocket?.close(1000, "Client disconnect requested")
        webSocket = null
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
                    break // 已连接，退出重连循环
                }
            }
        }
    }

    fun sendAIPMessage(messageType: String, payload: JSONObject) {
        val message = JSONObject().apply {
            put("protocol", "AIP/1.0")
            put("type", messageType)
            put("source_node", deviceId)
            put("target_node", "Node_50_Transformer")
            put("timestamp", System.currentTimeMillis() / 1000)
            put("payload", payload)
        }.toString()

        webSocket?.send(message) ?: Log.e(TAG, "WebSocket is null. Message not sent: $messageType")
    }

    private fun sendRegistration() {
        val payload = JSONObject().apply {
            put("device_type", "Android_Agent")
            put("capabilities", listOf("location", "camera", "sensor_data", "automation"))
        }
        sendAIPMessage("registration", payload)
        Log.i(TAG, "Registration message sent.")
    }

    private fun handleAIPMessage(text: String) {
        try {
            val data = JSONObject(text)
            val msgType = data.getString("type")
            val payload = data.getJSONObject("payload")

            when (msgType) {
                "command" -> {
                    val command = payload.getString("command")
                    val params = payload.optJSONObject("params") ?: JSONObject()
                    Log.i(TAG, "Executing command: $command with params: $params")
                    
                    // 模拟执行 Android 上的操作
                    val resultPayload = JSONObject().apply {
                        put("command", command)
                        put("status", "success")
                        put("details", "Command $command executed on Android.")
                    }
                    
                    // 实际应用中，这里会调用本地服务或广播执行具体操作
                    // ... execute_android_action(command, params) ...

                    sendAIPMessage("command_result", resultPayload)
                }
                "status_request" -> {
                    // 模拟发送 Android 状态
                    val statusPayload = JSONObject().apply {
                        put("battery_level", 85)
                        put("location", "Lat: 34.0522, Lon: -118.2437")
                        put("is_charging", false)
                    }
                    sendAIPMessage("status_update", statusPayload)
                }
                else -> Log.w(TAG, "Unhandled message type: $msgType")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error handling AIP message: ${e.message}", e)
        }
    }
}
