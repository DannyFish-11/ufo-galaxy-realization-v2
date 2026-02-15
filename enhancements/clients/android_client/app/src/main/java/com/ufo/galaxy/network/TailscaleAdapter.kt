package com.ufo.galaxy.network

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.net.InetAddress
import java.util.concurrent.TimeUnit

/**
 * Tailscale 网络适配器
 * 
 * UFO³ Galaxy 系统使用 Tailscale VPN 实现跨设备通信
 * 这个适配器负责：
 * - 自动检测 Tailscale 网络
 * - 发现 Node 50 的 IP 地址
 * - 配置网络连接
 * - 提供自适应和自配置能力
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class TailscaleAdapter(private val context: Context) {
    
    private val TAG = "TailscaleAdapter"
    private val prefs: SharedPreferences = context.getSharedPreferences("ufo_galaxy_config", Context.MODE_PRIVATE)
    
    private val okHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()
    
    companion object {
        const val PREF_NODE50_IP = "node50_ip"
        const val PREF_NODE50_PORT = "node50_port"
        const val DEFAULT_NODE50_PORT = 8050
        
        // Tailscale IP 范围: 100.64.0.0/10
        const val TAILSCALE_IP_PREFIX = "100."
    }
    
    /**
     * 获取 Node 50 的 URL
     */
    fun getNode50Url(): String? {
        val ip = prefs.getString(PREF_NODE50_IP, null)
        val port = prefs.getInt(PREF_NODE50_PORT, DEFAULT_NODE50_PORT)
        
        return if (ip != null) {
            "http://$ip:$port"
        } else {
            null
        }
    }
    
    /**
     * 设置 Node 50 的 IP 和端口
     */
    fun setNode50Address(ip: String, port: Int = DEFAULT_NODE50_PORT) {
        prefs.edit().apply {
            putString(PREF_NODE50_IP, ip)
            putInt(PREF_NODE50_PORT, port)
            apply()
        }
        Log.i(TAG, "✅ Node 50 地址已保存: $ip:$port")
    }
    
    /**
     * 清除保存的 Node 50 地址
     */
    fun clearNode50Address() {
        prefs.edit().apply {
            remove(PREF_NODE50_IP)
            remove(PREF_NODE50_PORT)
            apply()
        }
        Log.i(TAG, "🗑️ Node 50 地址已清除")
    }
    
    /**
     * 检查是否在 Tailscale 网络中
     */
    suspend fun isInTailscaleNetwork(): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                // 检查本地 IP 是否在 Tailscale 范围内
                val localAddresses = InetAddress.getAllByName(InetAddress.getLocalHost().hostName)
                val hasTailscaleIP = localAddresses.any { 
                    it.hostAddress?.startsWith(TAILSCALE_IP_PREFIX) == true
                }
                
                Log.i(TAG, if (hasTailscaleIP) "✅ 检测到 Tailscale 网络" else "⚠️ 未检测到 Tailscale 网络")
                hasTailscaleIP
                
            } catch (e: Exception) {
                Log.e(TAG, "❌ Tailscale 网络检测失败", e)
                false
            }
        }
    }
    
    /**
     * 自动发现 Node 50
     * 
     * 尝试常见的 Tailscale IP 段，检测 Node 50 的健康端点
     */
    suspend fun autoDiscoverNode50(): String? {
        return withContext(Dispatchers.IO) {
            Log.i(TAG, "🔍 正在自动发现 Node 50...")
            
            // 如果已经保存了地址，先尝试验证
            val savedUrl = getNode50Url()
            if (savedUrl != null && checkNode50Health(savedUrl)) {
                Log.i(TAG, "✅ 使用已保存的 Node 50 地址: $savedUrl")
                return@withContext savedUrl
            }
            
            // 尝试常见的 Tailscale IP 段
            val commonIPs = listOf(
                "100.64.0.1",   // 通常是第一个设备
                "100.64.0.2",
                "100.64.0.3",
                "100.64.0.4",
                "100.64.0.5",
                "100.100.100.100",  // 常见的自定义 IP
                "100.101.102.103"
            )
            
            for (ip in commonIPs) {
                val url = "http://$ip:$DEFAULT_NODE50_PORT"
                Log.d(TAG, "🔍 尝试: $url")
                
                if (checkNode50Health(url)) {
                    Log.i(TAG, "✅ 发现 Node 50: $url")
                    setNode50Address(ip, DEFAULT_NODE50_PORT)
                    return@withContext url
                }
            }
            
            Log.w(TAG, "❌ 未能自动发现 Node 50")
            null
        }
    }
    
    /**
     * 检查 Node 50 健康状态
     */
    private suspend fun checkNode50Health(url: String): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val request = Request.Builder()
                    .url("$url/health")
                    .get()
                    .build()
                
                val response = okHttpClient.newCall(request).execute()
                val isHealthy = response.isSuccessful
                
                if (isHealthy) {
                    Log.d(TAG, "✅ Node 50 健康检查通过: $url")
                } else {
                    Log.d(TAG, "❌ Node 50 健康检查失败: $url (HTTP ${response.code})")
                }
                
                isHealthy
            } catch (e: Exception) {
                Log.d(TAG, "❌ Node 50 健康检查异常: $url (${e.message})")
                false
            }
        }
    }
    
    /**
     * 获取 Node 50 信息
     */
    suspend fun getNode50Info(): JSONObject? {
        val url = getNode50Url() ?: return null
        
        return withContext(Dispatchers.IO) {
            try {
                val request = Request.Builder()
                    .url(url)
                    .get()
                    .build()
                
                val response = okHttpClient.newCall(request).execute()
                if (response.isSuccessful) {
                    val body = response.body?.string()
                    if (body != null) {
                        JSONObject(body)
                    } else {
                        null
                    }
                } else {
                    null
                }
            } catch (e: Exception) {
                Log.e(TAG, "❌ 获取 Node 50 信息失败", e)
                null
            }
        }
    }
    
    /**
     * 测试网络连接
     */
    suspend fun testConnection(): Boolean {
        val url = getNode50Url()
        if (url == null) {
            Log.w(TAG, "⚠️ 未配置 Node 50 地址")
            return false
        }
        
        return checkNode50Health(url)
    }
    
    /**
     * 获取网络诊断信息
     */
    suspend fun getDiagnostics(): JSONObject {
        return withContext(Dispatchers.IO) {
            val diagnostics = JSONObject()
            
            try {
                // Tailscale 网络状态
                diagnostics.put("in_tailscale_network", isInTailscaleNetwork())
                
                // Node 50 配置
                val node50Url = getNode50Url()
                diagnostics.put("node50_configured", node50Url != null)
                diagnostics.put("node50_url", node50Url ?: "not_configured")
                
                // 连接测试
                if (node50Url != null) {
                    diagnostics.put("node50_reachable", checkNode50Health(node50Url))
                    
                    // Node 50 信息
                    val node50Info = getNode50Info()
                    if (node50Info != null) {
                        diagnostics.put("node50_info", node50Info)
                    }
                } else {
                    diagnostics.put("node50_reachable", false)
                }
                
                // 本地 IP 地址
                val localAddresses = InetAddress.getAllByName(InetAddress.getLocalHost().hostName)
                val ipList = org.json.JSONArray()
                localAddresses.forEach { addr ->
                    ipList.put(addr.hostAddress)
                }
                diagnostics.put("local_ips", ipList)
                
            } catch (e: Exception) {
                diagnostics.put("error", e.message)
            }
            
            diagnostics
        }
    }
    
    /**
     * 自适应配置
     * 
     * 根据网络环境自动配置连接
     */
    suspend fun autoConfig(): Boolean {
        Log.i(TAG, "🔧 开始自适应配置...")
        
        // 1. 检查 Tailscale 网络
        if (!isInTailscaleNetwork()) {
            Log.w(TAG, "⚠️ 未检测到 Tailscale 网络，请确保已安装并登录 Tailscale")
            return false
        }
        
        // 2. 自动发现 Node 50
        val node50Url = autoDiscoverNode50()
        if (node50Url == null) {
            Log.w(TAG, "⚠️ 无法自动发现 Node 50，请手动配置")
            return false
        }
        
        // 3. 验证连接
        if (!testConnection()) {
            Log.w(TAG, "⚠️ Node 50 连接验证失败")
            return false
        }
        
        Log.i(TAG, "✅ 自适应配置完成: $node50Url")
        return true
    }
}
