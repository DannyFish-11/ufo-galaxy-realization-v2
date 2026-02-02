package com.ufo.galaxy.agent

import android.content.Context
import android.util.Log
import com.ufo.galaxy.autonomy.AutonomyManager
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

/**
 * Galaxy Agent 消息处理器和任务调度器
 * 
 * 功能：
 * 1. 处理来自 Galaxy Gateway 的各种消息
 * 2. 任务队列管理和调度
 * 3. 任务执行状态跟踪
 * 4. 结果回传到 Gateway
 * 5. 错误处理和重试机制
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class AgentMessageHandler(
    private val context: Context,
    private val agentWebSocket: AgentWebSocket
) {
    
    private val TAG = "AgentMessageHandler"
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    
    private val autonomyManager = AutonomyManager.getInstance(context)
    private val taskQueue = ConcurrentHashMap<String, TaskInfo>()
    
    /**
     * 任务信息
     */
    data class TaskInfo(
        val taskId: String,
        val type: String,
        val payload: JSONObject,
        val startTime: Long,
        var status: String = "pending",
        var result: JSONObject? = null
    )
    
    /**
     * 处理收到的消息
     */
    fun handleMessage(message: JSONObject) {
        try {
            val messageType = message.getString("type")
            Log.d(TAG, "处理消息类型: $messageType")
            
            when (messageType) {
                // 任务执行相关
                "task_execute" -> handleTaskExecute(message)
                "task_cancel" -> handleTaskCancel(message)
                "task_status_query" -> handleTaskStatusQuery(message)
                
                // Agent 控制相关
                "agent_ping" -> handleAgentPing(message)
                "agent_config_update" -> handleAgentConfigUpdate(message)
                "agent_restart" -> handleAgentRestart(message)
                
                // UI 自动化相关
                "ui_tree_request" -> handleUITreeRequest(message)
                "action_execute" -> handleActionExecute(message)
                "action_sequence_execute" -> handleActionSequenceExecute(message)
                
                // 系统控制相关
                "app_start" -> handleAppStart(message)
                "app_stop" -> handleAppStop(message)
                "system_command" -> handleSystemCommand(message)
                
                else -> {
                    Log.w(TAG, "未知消息类型: $messageType")
                    sendErrorResponse(message, "不支持的消息类型: $messageType")
                }
            }
            
        } catch (e: Exception) {
            Log.e(TAG, "处理消息失败", e)
            sendErrorResponse(message, "处理消息异常: ${e.message}")
        }
    }
    
    /**
     * 处理任务执行请求
     */
    private fun handleTaskExecute(message: JSONObject) {
        val taskId = message.getString("task_id")
        val taskType = message.getString("task_type")
        val payload = message.getJSONObject("payload")
        
        Log.i(TAG, "收到任务: $taskId, 类型: $taskType")
        
        // 创建任务信息
        val taskInfo = TaskInfo(
            taskId = taskId,
            type = taskType,
            payload = payload,
            startTime = System.currentTimeMillis()
        )
        
        taskQueue[taskId] = taskInfo
        
        // 异步执行任务
        scope.launch {
            try {
                taskInfo.status = "running"
                
                val result = when (taskType) {
                    "ui_automation" -> executeUIAutomation(payload)
                    "app_control" -> executeAppControl(payload)
                    "system_control" -> executeSystemControl(payload)
                    "data_collection" -> executeDataCollection(payload)
                    else -> JSONObject().apply {
                        put("status", "error")
                        put("message", "不支持的任务类型: $taskType")
                    }
                }
                
                taskInfo.status = if (result.optString("status") == "success") "completed" else "failed"
                taskInfo.result = result
                
                // 回传结果
                sendTaskResult(taskId, result)
                
            } catch (e: Exception) {
                Log.e(TAG, "任务执行失败: $taskId", e)
                taskInfo.status = "failed"
                taskInfo.result = JSONObject().apply {
                    put("status", "error")
                    put("message", e.message ?: "未知错误")
                }
                sendTaskResult(taskId, taskInfo.result!!)
            }
        }
        
        // 立即回复任务已接收
        sendTaskAck(taskId)
    }
    
    /**
     * 执行 UI 自动化任务
     */
    private suspend fun executeUIAutomation(payload: JSONObject): JSONObject {
        return withContext(Dispatchers.IO) {
            val actions = payload.getJSONArray("actions")
            autonomyManager.executeActionSequence(actions)
        }
    }
    
    /**
     * 执行应用控制任务
     */
    private suspend fun executeAppControl(payload: JSONObject): JSONObject {
        return withContext(Dispatchers.IO) {
            val action = payload.getString("action")
            val packageName = payload.optString("package_name", "")
            
            when (action) {
                "start" -> {
                    val startAction = JSONObject().apply {
                        put("type", "start_app")
                        put("params", JSONObject().apply {
                            put("package_name", packageName)
                        })
                    }
                    autonomyManager.executeAction(startAction)
                }
                "stop" -> {
                    // TODO: 实现应用停止功能
                    JSONObject().apply {
                        put("status", "error")
                        put("message", "应用停止功能尚未实现")
                    }
                }
                else -> JSONObject().apply {
                    put("status", "error")
                    put("message", "不支持的应用控制动作: $action")
                }
            }
        }
    }
    
    /**
     * 执行系统控制任务
     */
    private suspend fun executeSystemControl(payload: JSONObject): JSONObject {
        return withContext(Dispatchers.IO) {
            val command = payload.getString("command")
            
            val action = JSONObject().apply {
                put("type", "press_key")
                put("params", JSONObject().apply {
                    put("key", command)
                })
            }
            
            autonomyManager.executeAction(action)
        }
    }
    
    /**
     * 执行数据收集任务
     */
    private suspend fun executeDataCollection(payload: JSONObject): JSONObject {
        return withContext(Dispatchers.IO) {
            val dataType = payload.getString("data_type")
            
            when (dataType) {
                "ui_tree" -> autonomyManager.captureUITree()
                "device_info" -> getDeviceInfo()
                "app_list" -> getInstalledApps()
                else -> JSONObject().apply {
                    put("status", "error")
                    put("message", "不支持的数据类型: $dataType")
                }
            }
        }
    }
    
    /**
     * 获取设备信息
     */
    private fun getDeviceInfo(): JSONObject {
        return JSONObject().apply {
            put("status", "success")
            put("data", JSONObject().apply {
                put("manufacturer", android.os.Build.MANUFACTURER)
                put("model", android.os.Build.MODEL)
                put("android_version", android.os.Build.VERSION.RELEASE)
                put("sdk_version", android.os.Build.VERSION.SDK_INT)
            })
        }
    }
    
    /**
     * 获取已安装应用列表
     */
    private fun getInstalledApps(): JSONObject {
        return try {
            val pm = context.packageManager
            val packages = pm.getInstalledApplications(0)
            
            val appList = JSONArray()
            packages.forEach { app ->
                appList.put(JSONObject().apply {
                    put("package_name", app.packageName)
                    put("app_name", pm.getApplicationLabel(app).toString())
                })
            }
            
            JSONObject().apply {
                put("status", "success")
                put("data", JSONObject().apply {
                    put("apps", appList)
                    put("count", appList.length())
                })
            }
        } catch (e: Exception) {
            JSONObject().apply {
                put("status", "error")
                put("message", "获取应用列表失败: ${e.message}")
            }
        }
    }
    
    /**
     * 处理任务取消请求
     */
    private fun handleTaskCancel(message: JSONObject) {
        val taskId = message.getString("task_id")
        val task = taskQueue[taskId]
        
        if (task != null) {
            task.status = "cancelled"
            Log.i(TAG, "任务已取消: $taskId")
            sendResponse(message, JSONObject().apply {
                put("status", "success")
                put("message", "任务已取消")
            })
        } else {
            sendErrorResponse(message, "任务不存在: $taskId")
        }
    }
    
    /**
     * 处理任务状态查询
     */
    private fun handleTaskStatusQuery(message: JSONObject) {
        val taskId = message.getString("task_id")
        val task = taskQueue[taskId]
        
        if (task != null) {
            sendResponse(message, JSONObject().apply {
                put("status", "success")
                put("task_status", task.status)
                put("task_type", task.type)
                put("start_time", task.startTime)
                task.result?.let { put("result", it) }
            })
        } else {
            sendErrorResponse(message, "任务不存在: $taskId")
        }
    }
    
    /**
     * 处理 Agent Ping
     */
    private fun handleAgentPing(message: JSONObject) {
        sendResponse(message, JSONObject().apply {
            put("status", "success")
            put("message", "pong")
            put("timestamp", System.currentTimeMillis())
        })
    }
    
    /**
     * 处理 Agent 配置更新
     */
    private fun handleAgentConfigUpdate(message: JSONObject) {
        // TODO: 实现配置更新逻辑
        sendResponse(message, JSONObject().apply {
            put("status", "success")
            put("message", "配置更新功能尚未实现")
        })
    }
    
    /**
     * 处理 Agent 重启
     */
    private fun handleAgentRestart(message: JSONObject) {
        // TODO: 实现 Agent 重启逻辑
        sendResponse(message, JSONObject().apply {
            put("status", "success")
            put("message", "Agent 重启功能尚未实现")
        })
    }
    
    /**
     * 处理 UI 树请求
     */
    private fun handleUITreeRequest(message: JSONObject) {
        scope.launch {
            val uiTree = withContext(Dispatchers.IO) {
                autonomyManager.captureUITree()
            }
            sendResponse(message, uiTree)
        }
    }
    
    /**
     * 处理动作执行
     */
    private fun handleActionExecute(message: JSONObject) {
        scope.launch {
            val action = message.getJSONObject("action")
            val result = withContext(Dispatchers.IO) {
                autonomyManager.executeAction(action)
            }
            sendResponse(message, result)
        }
    }
    
    /**
     * 处理动作序列执行
     */
    private fun handleActionSequenceExecute(message: JSONObject) {
        scope.launch {
            val actions = message.getJSONArray("actions")
            val result = withContext(Dispatchers.IO) {
                autonomyManager.executeActionSequence(actions)
            }
            sendResponse(message, result)
        }
    }
    
    /**
     * 处理应用启动
     */
    private fun handleAppStart(message: JSONObject) {
        val packageName = message.getString("package_name")
        val action = JSONObject().apply {
            put("type", "start_app")
            put("params", JSONObject().apply {
                put("package_name", packageName)
            })
        }
        
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                autonomyManager.executeAction(action)
            }
            sendResponse(message, result)
        }
    }
    
    /**
     * 处理应用停止
     */
    private fun handleAppStop(message: JSONObject) {
        sendErrorResponse(message, "应用停止功能尚未实现")
    }
    
    /**
     * 处理系统命令
     */
    private fun handleSystemCommand(message: JSONObject) {
        val command = message.getString("command")
        val action = JSONObject().apply {
            put("type", "press_key")
            put("params", JSONObject().apply {
                put("key", command)
            })
        }
        
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                autonomyManager.executeAction(action)
            }
            sendResponse(message, result)
        }
    }
    
    /**
     * 发送任务确认
     */
    private fun sendTaskAck(taskId: String) {
        val ack = JSONObject().apply {
            put("type", "task_ack")
            put("task_id", taskId)
            put("timestamp", System.currentTimeMillis())
        }
        agentWebSocket.sendMessage(ack)
    }
    
    /**
     * 发送任务结果
     */
    private fun sendTaskResult(taskId: String, result: JSONObject) {
        val response = JSONObject().apply {
            put("type", "task_result")
            put("task_id", taskId)
            put("result", result)
            put("timestamp", System.currentTimeMillis())
        }
        agentWebSocket.sendMessage(response)
    }
    
    /**
     * 发送响应
     */
    private fun sendResponse(originalMessage: JSONObject, response: JSONObject) {
        val messageId = originalMessage.optString("message_id", "")
        val reply = JSONObject().apply {
            put("type", "response")
            if (messageId.isNotEmpty()) {
                put("reply_to", messageId)
            }
            put("data", response)
            put("timestamp", System.currentTimeMillis())
        }
        agentWebSocket.sendMessage(reply)
    }
    
    /**
     * 发送错误响应
     */
    private fun sendErrorResponse(originalMessage: JSONObject, errorMessage: String) {
        sendResponse(originalMessage, JSONObject().apply {
            put("status", "error")
            put("message", errorMessage)
        })
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        scope.cancel()
        taskQueue.clear()
    }
}
