package com.ufo.galaxy.autonomy

import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.util.Log
// import com.ufo.galaxy.api.GalaxyApiClient - 已移除
import kotlinx.coroutines.*
import org.json.JSONObject

/**
 * 自主操纵管理器
 * 
 * 功能：
 * 1. 管理 AutonomyService 的生命周期
 * 2. 与 Galaxy Gateway 通信
 * 3. 处理来自 Gateway 的操作指令
 * 4. 定期推送 UI 树到 Gateway
 * 5. 提供统一的 API 接口
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class AutonomyManager(private val context: Context) {
    
    private val TAG = "AutonomyManager"
    private val actionExecutor = ActionExecutor()
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private var uiTreePushJob: Job? = null
    
    companion object {
        @Volatile
        private var instance: AutonomyManager? = null
        
        fun getInstance(context: Context): AutonomyManager {
            return instance ?: synchronized(this) {
                instance ?: AutonomyManager(context.applicationContext).also { instance = it }
            }
        }
    }
    
    /**
     * 检查自主操纵能力是否已启用
     */
    fun isEnabled(): Boolean {
        val service = AutonomyService.getInstance()
        return service != null && AutonomyService.isServiceAvailable()
    }
    
    /**
     * 打开无障碍服务设置页面
     */
    fun openAccessibilitySettings() {
        try {
            val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "打开无障碍设置失败", e)
        }
    }
    
    /**
     * 获取当前 UI 树
     */
    suspend fun getUITree(): String {
        return withContext(Dispatchers.IO) {
            val service = AutonomyService.getInstance()
            
            if (service == null) {
                return@withContext "错误: 自主操纵服务未启用"
            }
            
            val uiTree = service.captureUITree()
            return@withContext uiTree.toString(2)
        }
    }
    
    /**
     * 执行单个动作
     */
    fun executeAction(action: JSONObject): JSONObject {
        return actionExecutor.executeAction(action)
    }
    
    /**
     * 执行动作序列
     */
    fun executeActionSequence(actions: org.json.JSONArray): JSONObject {
        return actionExecutor.executeActionSequence(actions)
    }
    
    /**
     * 点击指定文本的元素
     */
    suspend fun clickByText(text: String): String {
        return withContext(Dispatchers.IO) {
            val action = JSONObject().apply {
                put("type", "click")
                put("text", text)
            }
            val result = executeAction(action)
            return@withContext result.optString("message", "执行完成")
        }
    }
    
    /**
     * 输入文本
     */
    suspend fun inputText(text: String): String {
        return withContext(Dispatchers.IO) {
            val action = JSONObject().apply {
                put("type", "input")
                put("text", text)
            }
            val result = executeAction(action)
            return@withContext result.optString("message", "执行完成")
        }
    }
    
    /**
     * 打开应用
     */
    suspend fun openApp(packageName: String): String {
        return withContext(Dispatchers.IO) {
            try {
                val intent = context.packageManager.getLaunchIntentForPackage(packageName)
                if (intent != null) {
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    context.startActivity(intent)
                    return@withContext "已打开应用: $packageName"
                } else {
                    return@withContext "错误: 未找到应用 $packageName"
                }
            } catch (e: Exception) {
                return@withContext "错误: ${e.message}"
            }
        }
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        scope.cancel()
        Log.i(TAG, "✅ 资源已清理")
    }
    
    /**
     * 启动自动 UI 树推送（定期推送到 Gateway）
     */
    fun startUITreePush(intervalMs: Long = 5000) {
        stopUITreePush()
        
        uiTreePushJob = scope.launch {
            while (isActive) {
                try {
                    if (isAccessibilityServiceEnabled()) {
                        val uiTree = captureUITree()
                        
                        if (uiTree.optString("status") == "success") {
                            // 推送到 Gateway
                            pushUITreeToGateway(uiTree)
                        }
                    }
                    
                    delay(intervalMs)
                    
                } catch (e: Exception) {
                    Log.e(TAG, "UI 树推送失败", e)
                    delay(intervalMs)
                }
            }
        }
        
        Log.i(TAG, "✅ 已启动 UI 树自动推送，间隔: ${intervalMs}ms")
    }
    
    /**
     * 停止自动 UI 树推送
     */
    fun stopUITreePush() {
        uiTreePushJob?.cancel()
        uiTreePushJob = null
        Log.i(TAG, "❌ 已停止 UI 树自动推送")
    }
    
    /**
     * 推送 UI 树到 Gateway
     */
    private suspend fun pushUITreeToGateway(uiTree: JSONObject) {
        withContext(Dispatchers.IO) {
            try {
                val payload = JSONObject().apply {
                    put("type", "ui_tree_update")
                    put("device_type", "android")
                    put("device_id", getDeviceId())
                    put("data", uiTree)
                }
                
                // 通过 GalaxyApiClient 发送
                val apiClient = GalaxyApiClient.getInstance(context)
                val response = apiClient.sendMessage(payload.toString())
                
                Log.d(TAG, "UI 树推送成功: ${response.optString("status")}")
                
            } catch (e: Exception) {
                Log.e(TAG, "推送 UI 树到 Gateway 失败", e)
            }
        }
    }
    
    /**
     * 处理来自 Gateway 的指令
     */
    fun handleGatewayCommand(command: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            val commandType = command.getString("type")
            
            when (commandType) {
                "execute_action" -> {
                    val action = command.getJSONObject("action")
                    return executeAction(action)
                }
                
                "execute_sequence" -> {
                    val actions = command.getJSONArray("actions")
                    return executeActionSequence(actions)
                }
                
                "get_ui_tree" -> {
                    return captureUITree()
                }
                
                "start_ui_push" -> {
                    val interval = command.optLong("interval", 5000)
                    startUITreePush(interval)
                    result.put("status", "success")
                    result.put("message", "已启动 UI 树推送")
                }
                
                "stop_ui_push" -> {
                    stopUITreePush()
                    result.put("status", "success")
                    result.put("message", "已停止 UI 树推送")
                }
                
                else -> {
                    result.put("status", "error")
                    result.put("message", "不支持的指令类型: $commandType")
                }
            }
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "处理指令失败: ${e.message}")
            Log.e(TAG, "处理 Gateway 指令失败", e)
        }
        
        return result
    }
    
    /**
     * 测试自主操纵功能
     */
    fun runDiagnostics(): JSONObject {
        val result = JSONObject()
        val checks = org.json.JSONArray()
        
        // 检查 1: 无障碍服务状态
        checks.put(JSONObject().apply {
            put("name", "无障碍服务")
            put("status", if (isAccessibilityServiceEnabled()) "✅ 已启用" else "❌ 未启用")
        })
        
        // 检查 2: UI 树抓取
        val uiTree = captureUITree()
        checks.put(JSONObject().apply {
            put("name", "UI 树抓取")
            put("status", if (uiTree.optString("status") == "success") "✅ 正常" else "❌ 失败")
            put("node_count", uiTree.optInt("node_count", 0))
        })
        
        // 检查 3: 动作执行器
        checks.put(JSONObject().apply {
            put("name", "动作执行器")
            put("status", "✅ 已初始化")
        })
        
        // 检查 4: Gateway 连接
        val apiClient = GalaxyApiClient.getInstance(context)
        checks.put(JSONObject().apply {
            put("name", "Gateway 连接")
            put("status", if (apiClient.isConnected()) "✅ 已连接" else "❌ 未连接")
        })
        
        result.put("status", "success")
        result.put("checks", checks)
        result.put("timestamp", System.currentTimeMillis())
        
        return result
    }
    
    /**
     * 获取设备 ID
     */
    private fun getDeviceId(): String {
        return try {
            Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
        } catch (e: Exception) {
            "unknown"
        }
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        stopUITreePush()
        actionExecutor.cleanup()
        scope.cancel()
    }
}
