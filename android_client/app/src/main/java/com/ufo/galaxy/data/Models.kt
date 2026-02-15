package com.ufo.galaxy.data

/**
 * UFO Galaxy Android - 数据模型
 */

/**
 * 应用配置
 */
data class AppConfig(
    val serverUrl: String,
    val apiVersion: String,
    val isDebug: Boolean
)

/**
 * 消息角色
 */
enum class MessageRole {
    USER,
    ASSISTANT,
    SYSTEM
}

/**
 * 聊天消息
 */
data class ChatMessage(
    val id: String,
    val role: MessageRole,
    val content: String,
    val timestamp: Long,
    val metadata: Map<String, Any>? = null
)

/**
 * AIP 消息类型
 */
enum class AIPMessageType {
    TEXT,
    VOICE,
    IMAGE,
    COMMAND,
    STATUS,
    ERROR
}

/**
 * AIP 协议消息
 */
data class AIPMessage(
    val version: String = "2.0",
    val type: AIPMessageType,
    val payload: Any,
    val timestamp: Long = System.currentTimeMillis(),
    val sessionId: String? = null,
    val deviceId: String? = null
)

/**
 * 设备状态
 */
data class DeviceStatus(
    val deviceId: String,
    val deviceName: String,
    val deviceType: String,
    val isOnline: Boolean,
    val lastSeen: Long,
    val capabilities: List<String> = emptyList()
)

/**
 * 任务状态
 */
enum class TaskStatus {
    PENDING,
    RUNNING,
    COMPLETED,
    FAILED,
    CANCELLED
}

/**
 * 任务信息
 */
data class TaskInfo(
    val taskId: String,
    val name: String,
    val description: String,
    val status: TaskStatus,
    val progress: Float = 0f,
    val createdAt: Long,
    val updatedAt: Long,
    val result: Any? = null,
    val error: String? = null
)

/**
 * 连接状态
 */
enum class ConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    RECONNECTING,
    ERROR
}

/**
 * 系统状态
 */
data class SystemState(
    val connectionState: ConnectionState,
    val serverVersion: String? = null,
    val activeNodes: Int = 0,
    val pendingTasks: Int = 0,
    val lastHeartbeat: Long? = null
)
