package com.ufo.galaxy.protocol

import android.os.Build
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.*

/**
 * AIP/1.0 (Agent Interaction Protocol) 协议实现
 * 
 * 这是 UFO³ Galaxy 系统的标准通信协议
 * 所有节点和客户端之间通过 AIP/1.0 协议进行通信
 * 
 * 消息格式：
 * {
 *   "protocol": "AIP/1.0",
 *   "message_id": "android-client_1737336000123",
 *   "timestamp": "2025-01-20T12:00:00Z",
 *   "from": "Android_Client",
 *   "to": "Node_50",
 *   "type": "command|response|heartbeat|register",
 *   "payload": { ... }
 * }
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
object AIPProtocol {
    
    const val VERSION = "AIP/1.0"
    const val CLIENT_ID = "Android_Client"
    const val NODE_50_ID = "Node_50"
    
    private val dateFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }
    
    /**
     * 消息类型
     */
    object MessageType {
        const val COMMAND = "command"
        const val RESPONSE = "response"
        const val HEARTBEAT = "heartbeat"
        const val REGISTER = "register"
        const val STATUS = "status"
        const val ERROR = "error"
    }
    
    /**
     * 生成消息 ID
     */
    fun generateMessageId(): String {
        return "${CLIENT_ID.lowercase()}_${System.currentTimeMillis()}"
    }
    
    /**
     * 获取当前 UTC 时间戳
     */
    fun getCurrentTimestamp(): String {
        return dateFormat.format(Date())
    }
    
    /**
     * 创建 AIP/1.0 消息
     */
    fun createMessage(
        to: String,
        type: String,
        payload: JSONObject
    ): JSONObject {
        return JSONObject().apply {
            put("protocol", VERSION)
            put("message_id", generateMessageId())
            put("timestamp", getCurrentTimestamp())
            put("from", CLIENT_ID)
            put("to", to)
            put("type", type)
            put("payload", payload)
        }
    }
    
    /**
     * 创建命令消息
     */
    fun createCommandMessage(
        command: String,
        context: JSONObject? = null
    ): JSONObject {
        val payload = JSONObject().apply {
            put("command", command)
            if (context != null) {
                put("context", context)
            } else {
                put("context", createDefaultContext())
            }
        }
        
        return createMessage(NODE_50_ID, MessageType.COMMAND, payload)
    }
    
    /**
     * 创建注册消息
     */
    fun createRegisterMessage(
        deviceInfo: JSONObject,
        capabilities: org.json.JSONArray
    ): JSONObject {
        val payload = JSONObject().apply {
            put("client_type", "android")
            put("client_id", CLIENT_ID)
            put("device_info", deviceInfo)
            put("capabilities", capabilities)
        }
        
        return createMessage(NODE_50_ID, MessageType.REGISTER, payload)
    }
    
    /**
     * 创建心跳消息
     */
    fun createHeartbeatMessage(
        status: String = "online"
    ): JSONObject {
        val payload = JSONObject().apply {
            put("status", status)
            put("client_id", CLIENT_ID)
        }
        
        return createMessage(NODE_50_ID, MessageType.HEARTBEAT, payload)
    }
    
    /**
     * 创建响应消息
     */
    fun createResponseMessage(
        originalMessageId: String,
        result: JSONObject
    ): JSONObject {
        val payload = JSONObject().apply {
            put("original_message_id", originalMessageId)
            put("result", result)
        }
        
        return createMessage(NODE_50_ID, MessageType.RESPONSE, payload)
    }
    
    /**
     * 创建错误消息
     */
    fun createErrorMessage(
        originalMessageId: String,
        errorMessage: String,
        errorCode: String? = null
    ): JSONObject {
        val payload = JSONObject().apply {
            put("original_message_id", originalMessageId)
            put("error_message", errorMessage)
            if (errorCode != null) {
                put("error_code", errorCode)
            }
        }
        
        return createMessage(NODE_50_ID, MessageType.ERROR, payload)
    }
    
    /**
     * 创建状态消息
     */
    fun createStatusMessage(
        status: JSONObject
    ): JSONObject {
        return createMessage(NODE_50_ID, MessageType.STATUS, status)
    }
    
    /**
     * 创建默认上下文
     */
    private fun createDefaultContext(): JSONObject {
        return JSONObject().apply {
            put("platform", "android")
            put("client_id", CLIENT_ID)
            put("device_model", Build.MODEL)
            put("android_version", Build.VERSION.RELEASE)
        }
    }
    
    /**
     * 获取设备信息
     */
    fun getDeviceInfo(): JSONObject {
        return JSONObject().apply {
            put("manufacturer", Build.MANUFACTURER)
            put("model", Build.MODEL)
            put("brand", Build.BRAND)
            put("device", Build.DEVICE)
            put("android_version", Build.VERSION.RELEASE)
            put("sdk_version", Build.VERSION.SDK_INT)
            put("board", Build.BOARD)
            put("hardware", Build.HARDWARE)
        }
    }
    
    /**
     * 获取客户端能力列表
     */
    fun getCapabilities(): org.json.JSONArray {
        return org.json.JSONArray().apply {
            put("ui_automation")      // UI 自动化
            put("screen_capture")     // 屏幕抓取
            put("app_control")        // 应用控制
            put("system_control")     // 系统控制
            put("text_input")         // 文本输入
            put("gesture_simulation") // 手势模拟
            put("voice_input")        // 语音输入
            put("natural_language")   // 自然语言理解
        }
    }
    
    /**
     * 验证消息格式
     */
    fun validateMessage(message: JSONObject): Boolean {
        return try {
            message.has("protocol") &&
            message.getString("protocol") == VERSION &&
            message.has("message_id") &&
            message.has("timestamp") &&
            message.has("from") &&
            message.has("to") &&
            message.has("type") &&
            message.has("payload")
        } catch (e: Exception) {
            false
        }
    }
    
    /**
     * 解析消息
     */
    fun parseMessage(messageString: String): JSONObject? {
        return try {
            val message = JSONObject(messageString)
            if (validateMessage(message)) {
                message
            } else {
                null
            }
        } catch (e: Exception) {
            null
        }
    }
    
    /**
     * 提取消息类型
     */
    fun getMessageType(message: JSONObject): String? {
        return try {
            message.getString("type")
        } catch (e: Exception) {
            null
        }
    }
    
    /**
     * 提取消息 Payload
     */
    fun getPayload(message: JSONObject): JSONObject? {
        return try {
            message.getJSONObject("payload")
        } catch (e: Exception) {
            null
        }
    }
    
    /**
     * 提取消息 ID
     */
    fun getMessageId(message: JSONObject): String? {
        return try {
            message.getString("message_id")
        } catch (e: Exception) {
            null
        }
    }
    
    /**
     * 提取发送者
     */
    fun getFrom(message: JSONObject): String? {
        return try {
            message.getString("from")
        } catch (e: Exception) {
            null
        }
    }
}
