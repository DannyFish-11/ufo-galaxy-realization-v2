package com.ufo.galaxy.autonomy

import android.util.Log
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject

/**
 * 动作执行引擎管理器
 * 
 * 功能：
 * 1. 批量执行动作序列
 * 2. 动作执行的错误处理和重试
 * 3. 动作执行的日志记录
 * 4. 动作执行的状态管理
 * 5. 支持异步和同步执行
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class ActionExecutor {
    
    private val TAG = "ActionExecutor"
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    
    /**
     * 执行单个动作（同步）
     */
    fun executeAction(action: JSONObject): JSONObject {
        val service = AutonomyService.getInstance()
        
        if (service == null) {
            return JSONObject().apply {
                put("status", "error")
                put("message", "自主操纵服务未启用")
            }
        }
        
        Log.d(TAG, "执行动作: ${action.optString("type", "unknown")}")
        
        val result = service.executeAction(action)
        
        Log.d(TAG, "动作结果: ${result.optString("status", "unknown")}")
        
        return result
    }
    
    /**
     * 执行单个动作（异步）
     */
    fun executeActionAsync(
        action: JSONObject,
        onSuccess: (JSONObject) -> Unit,
        onError: (String) -> Unit
    ) {
        scope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    executeAction(action)
                }
                
                if (result.optString("status") == "success") {
                    onSuccess(result)
                } else {
                    onError(result.optString("message", "执行失败"))
                }
                
            } catch (e: Exception) {
                Log.e(TAG, "异步执行动作失败", e)
                onError(e.message ?: "未知错误")
            }
        }
    }
    
    /**
     * 执行动作序列（同步）
     */
    fun executeActionSequence(actions: JSONArray): JSONObject {
        val result = JSONObject()
        val results = JSONArray()
        var successCount = 0
        var failureCount = 0
        
        for (i in 0 until actions.length()) {
            val action = actions.getJSONObject(i)
            val actionResult = executeAction(action)
            
            results.put(actionResult)
            
            if (actionResult.optString("status") == "success") {
                successCount++
            } else {
                failureCount++
                
                // 如果动作失败，检查是否需要中断执行
                if (action.optBoolean("critical", false)) {
                    Log.w(TAG, "关键动作失败，中断执行序列")
                    break
                }
            }
            
            // 动作间延迟
            val delay = action.optInt("delay", 0)
            if (delay > 0) {
                Thread.sleep(delay.toLong())
            }
        }
        
        result.put("status", if (failureCount == 0) "success" else "partial")
        result.put("total", actions.length())
        result.put("success_count", successCount)
        result.put("failure_count", failureCount)
        result.put("results", results)
        
        return result
    }
    
    /**
     * 执行动作序列（异步）
     */
    fun executeActionSequenceAsync(
        actions: JSONArray,
        onProgress: (Int, Int) -> Unit,
        onComplete: (JSONObject) -> Unit
    ) {
        scope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    val results = JSONArray()
                    var successCount = 0
                    var failureCount = 0
                    
                    for (i in 0 until actions.length()) {
                        val action = actions.getJSONObject(i)
                        val actionResult = executeAction(action)
                        
                        results.put(actionResult)
                        
                        if (actionResult.optString("status") == "success") {
                            successCount++
                        } else {
                            failureCount++
                            
                            if (action.optBoolean("critical", false)) {
                                Log.w(TAG, "关键动作失败，中断执行序列")
                                break
                            }
                        }
                        
                        // 报告进度
                        withContext(Dispatchers.Main) {
                            onProgress(i + 1, actions.length())
                        }
                        
                        // 动作间延迟
                        val delay = action.optInt("delay", 0)
                        if (delay > 0) {
                            delay(delay.toLong())
                        }
                    }
                    
                    JSONObject().apply {
                        put("status", if (failureCount == 0) "success" else "partial")
                        put("total", actions.length())
                        put("success_count", successCount)
                        put("failure_count", failureCount)
                        put("results", results)
                    }
                }
                
                onComplete(result)
                
            } catch (e: Exception) {
                Log.e(TAG, "异步执行动作序列失败", e)
                onComplete(JSONObject().apply {
                    put("status", "error")
                    put("message", e.message ?: "未知错误")
                })
            }
        }
    }
    
    /**
     * 执行动作并重试（同步）
     */
    fun executeActionWithRetry(
        action: JSONObject,
        maxRetries: Int = 3,
        retryDelay: Long = 1000
    ): JSONObject {
        var lastResult: JSONObject? = null
        
        for (attempt in 1..maxRetries) {
            Log.d(TAG, "尝试执行动作 (第 $attempt 次)")
            
            val result = executeAction(action)
            
            if (result.optString("status") == "success") {
                return result
            }
            
            lastResult = result
            
            if (attempt < maxRetries) {
                Log.w(TAG, "动作执行失败，${retryDelay}ms 后重试")
                Thread.sleep(retryDelay)
            }
        }
        
        return lastResult ?: JSONObject().apply {
            put("status", "error")
            put("message", "执行失败且重试次数已用尽")
        }
    }
    
    /**
     * 创建点击动作
     */
    fun createTapAction(nodeId: Int? = null, x: Int? = null, y: Int? = null): JSONObject {
        return JSONObject().apply {
            put("type", "tap")
            put("params", JSONObject().apply {
                nodeId?.let { put("node_id", it) }
                x?.let { put("x", it) }
                y?.let { put("y", it) }
            })
        }
    }
    
    /**
     * 创建长按动作
     */
    fun createLongTapAction(nodeId: Int? = null, x: Int? = null, y: Int? = null): JSONObject {
        return JSONObject().apply {
            put("type", "long_tap")
            put("params", JSONObject().apply {
                nodeId?.let { put("node_id", it) }
                x?.let { put("x", it) }
                y?.let { put("y", it) }
            })
        }
    }
    
    /**
     * 创建输入文本动作
     */
    fun createInputTextAction(text: String, nodeId: Int? = null): JSONObject {
        return JSONObject().apply {
            put("type", "input_text")
            put("params", JSONObject().apply {
                put("text", text)
                nodeId?.let { put("node_id", it) }
            })
        }
    }
    
    /**
     * 创建滚动动作
     */
    fun createScrollAction(direction: String, nodeId: Int? = null): JSONObject {
        return JSONObject().apply {
            put("type", "scroll")
            put("params", JSONObject().apply {
                put("direction", direction)
                nodeId?.let { put("node_id", it) }
            })
        }
    }
    
    /**
     * 创建滑动动作
     */
    fun createSwipeAction(x1: Int, y1: Int, x2: Int, y2: Int, duration: Int = 300): JSONObject {
        return JSONObject().apply {
            put("type", "swipe")
            put("params", JSONObject().apply {
                put("x1", x1)
                put("y1", y1)
                put("x2", x2)
                put("y2", y2)
                put("duration", duration)
            })
        }
    }
    
    /**
     * 创建按键动作
     */
    fun createPressKeyAction(key: String): JSONObject {
        return JSONObject().apply {
            put("type", "press_key")
            put("params", JSONObject().apply {
                put("key", key)
            })
        }
    }
    
    /**
     * 创建启动应用动作
     */
    fun createStartAppAction(packageName: String): JSONObject {
        return JSONObject().apply {
            put("type", "start_app")
            put("params", JSONObject().apply {
                put("package_name", packageName)
            })
        }
    }
    
    /**
     * 创建获取 UI 树动作
     */
    fun createGetUITreeAction(): JSONObject {
        return JSONObject().apply {
            put("type", "get_ui_tree")
            put("params", JSONObject())
        }
    }
    
    /**
     * 创建延迟动作
     */
    fun createDelayAction(milliseconds: Int): JSONObject {
        return JSONObject().apply {
            put("type", "delay")
            put("delay", milliseconds)
        }
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        scope.cancel()
    }
}
