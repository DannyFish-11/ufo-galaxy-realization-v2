package com.ufo.galaxy.agent

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.provider.Settings
import android.util.Log
import org.json.JSONObject
import java.util.UUID

/**
 * Galaxy Agent 注册和身份认证管理器
 * 
 * 功能：
 * 1. 生成和管理唯一的 Agent ID
 * 2. 向 Galaxy Gateway 注册设备为 Agent
 * 3. 管理 Agent 的身份认证 Token
 * 4. 维护 Agent 的元数据信息
 * 5. 处理 Agent 的注销和重新注册
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class AgentRegistry(private val context: Context) {
    
    private val TAG = "AgentRegistry"
    private val prefs: SharedPreferences = context.getSharedPreferences(
        "galaxy_agent_registry",
        Context.MODE_PRIVATE
    )
    
    companion object {
        private const val KEY_AGENT_ID = "agent_id"
        private const val KEY_AGENT_TOKEN = "agent_token"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_REGISTRATION_TIME = "registration_time"
        private const val KEY_LAST_HEARTBEAT = "last_heartbeat"
        private const val KEY_IS_REGISTERED = "is_registered"
        
        @Volatile
        private var instance: AgentRegistry? = null
        
        fun getInstance(context: Context): AgentRegistry {
            return instance ?: synchronized(this) {
                instance ?: AgentRegistry(context.applicationContext).also { instance = it }
            }
        }
    }
    
    /**
     * 获取或生成 Agent ID
     */
    fun getAgentId(): String {
        var agentId = prefs.getString(KEY_AGENT_ID, null)
        
        if (agentId == null) {
            // 生成新的 Agent ID: android-{device_id}-{uuid}
            val deviceId = getDeviceId()
            val uuid = UUID.randomUUID().toString().substring(0, 8)
            agentId = "android-$deviceId-$uuid"
            
            prefs.edit().putString(KEY_AGENT_ID, agentId).apply()
            Log.i(TAG, "生成新的 Agent ID: $agentId")
        }
        
        return agentId
    }
    
    /**
     * 获取设备 ID
     */
    fun getDeviceId(): String {
        var deviceId = prefs.getString(KEY_DEVICE_ID, null)
        
        if (deviceId == null) {
            deviceId = try {
                Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
            } catch (e: Exception) {
                UUID.randomUUID().toString()
            }
            
            prefs.edit().putString(KEY_DEVICE_ID, deviceId).apply()
        }
        
        return deviceId
    }
    
    /**
     * 获取 Agent Token
     */
    fun getAgentToken(): String? {
        return prefs.getString(KEY_AGENT_TOKEN, null)
    }
    
    /**
     * 保存 Agent Token
     */
    fun saveAgentToken(token: String) {
        prefs.edit().putString(KEY_AGENT_TOKEN, token).apply()
        Log.i(TAG, "已保存 Agent Token")
    }
    
    /**
     * 检查是否已注册
     */
    fun isRegistered(): Boolean {
        return prefs.getBoolean(KEY_IS_REGISTERED, false) && getAgentToken() != null
    }
    
    /**
     * 标记为已注册
     */
    fun markAsRegistered() {
        prefs.edit()
            .putBoolean(KEY_IS_REGISTERED, true)
            .putLong(KEY_REGISTRATION_TIME, System.currentTimeMillis())
            .apply()
        Log.i(TAG, "Agent 已标记为已注册")
    }
    
    /**
     * 更新心跳时间
     */
    fun updateHeartbeat() {
        prefs.edit()
            .putLong(KEY_LAST_HEARTBEAT, System.currentTimeMillis())
            .apply()
    }
    
    /**
     * 获取上次心跳时间
     */
    fun getLastHeartbeat(): Long {
        return prefs.getLong(KEY_LAST_HEARTBEAT, 0)
    }
    
    /**
     * 生成注册请求数据
     */
    fun generateRegistrationRequest(): JSONObject {
        return JSONObject().apply {
            put("type", "agent_register")
            put("agent_id", getAgentId())
            put("device_id", getDeviceId())
            put("platform", "android")
            put("device_info", getDeviceInfo())
            put("capabilities", getAgentCapabilities())
            put("timestamp", System.currentTimeMillis())
        }
    }
    
    /**
     * 获取设备信息
     */
    private fun getDeviceInfo(): JSONObject {
        return JSONObject().apply {
            put("manufacturer", Build.MANUFACTURER)
            put("model", Build.MODEL)
            put("brand", Build.BRAND)
            put("device", Build.DEVICE)
            put("android_version", Build.VERSION.RELEASE)
            put("sdk_version", Build.VERSION.SDK_INT)
            put("app_version", getAppVersion())
        }
    }
    
    /**
     * 获取 Agent 能力列表
     */
    private fun getAgentCapabilities(): org.json.JSONArray {
        return org.json.JSONArray().apply {
            put("ui_automation")      // UI 自动化操作
            put("screen_capture")     // 屏幕内容抓取
            put("app_control")        // 应用控制（启动、关闭等）
            put("system_control")     // 系统控制（按键、通知等）
            put("text_input")         // 文本输入
            put("gesture_simulation") // 手势模拟
            put("voice_input")        // 语音输入（如果支持）
            put("location_access")    // 位置访问（如果授权）
            put("camera_access")      // 相机访问（如果授权）
        }
    }
    
    /**
     * 获取应用版本
     */
    private fun getAppVersion(): String {
        return try {
            val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
            packageInfo.versionName ?: "unknown"
        } catch (e: Exception) {
            "unknown"
        }
    }
    
    /**
     * 生成心跳数据
     */
    fun generateHeartbeatData(): JSONObject {
        return JSONObject().apply {
            put("type", "agent_heartbeat")
            put("agent_id", getAgentId())
            put("token", getAgentToken())
            put("status", "online")
            put("timestamp", System.currentTimeMillis())
            put("stats", getAgentStats())
        }
    }
    
    /**
     * 获取 Agent 统计信息
     */
    private fun getAgentStats(): JSONObject {
        return JSONObject().apply {
            put("uptime", System.currentTimeMillis() - prefs.getLong(KEY_REGISTRATION_TIME, 0))
            put("last_heartbeat", getLastHeartbeat())
            put("memory_usage", getMemoryUsage())
            put("battery_level", getBatteryLevel())
        }
    }
    
    /**
     * 获取内存使用情况
     */
    private fun getMemoryUsage(): JSONObject {
        val runtime = Runtime.getRuntime()
        return JSONObject().apply {
            put("total", runtime.totalMemory())
            put("free", runtime.freeMemory())
            put("used", runtime.totalMemory() - runtime.freeMemory())
            put("max", runtime.maxMemory())
        }
    }
    
    /**
     * 获取电池电量
     */
    private fun getBatteryLevel(): Int {
        return try {
            val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as android.os.BatteryManager
            batteryManager.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY)
        } catch (e: Exception) {
            -1
        }
    }
    
    /**
     * 处理注册响应
     */
    fun handleRegistrationResponse(response: JSONObject): Boolean {
        return try {
            val status = response.getString("status")
            
            if (status == "success") {
                val token = response.optString("token", null)
                if (token != null) {
                    saveAgentToken(token)
                    markAsRegistered()
                    Log.i(TAG, "✅ Agent 注册成功: ${getAgentId()}")
                    true
                } else {
                    Log.e(TAG, "❌ 注册响应缺少 token")
                    false
                }
            } else {
                val message = response.optString("message", "未知错误")
                Log.e(TAG, "❌ Agent 注册失败: $message")
                false
            }
            
        } catch (e: Exception) {
            Log.e(TAG, "❌ 处理注册响应失败", e)
            false
        }
    }
    
    /**
     * 注销 Agent
     */
    fun unregister() {
        prefs.edit()
            .remove(KEY_AGENT_TOKEN)
            .putBoolean(KEY_IS_REGISTERED, false)
            .apply()
        Log.i(TAG, "Agent 已注销")
    }
    
    /**
     * 清除所有数据（用于重置）
     */
    fun clearAll() {
        prefs.edit().clear().apply()
        Log.i(TAG, "Agent 注册数据已清除")
    }
    
    /**
     * 获取 Agent 摘要信息
     */
    fun getAgentSummary(): JSONObject {
        return JSONObject().apply {
            put("agent_id", getAgentId())
            put("device_id", getDeviceId())
            put("is_registered", isRegistered())
            put("has_token", getAgentToken() != null)
            put("registration_time", prefs.getLong(KEY_REGISTRATION_TIME, 0))
            put("last_heartbeat", getLastHeartbeat())
        }
    }
}
