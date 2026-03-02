package com.ufo.galaxy.client

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import com.ufo.galaxy.agent.GalaxyAgent
import java.util.Properties

class MainActivity : AppCompatActivity() {

    private val TAG = "MainActivity"
    private lateinit var galaxyAgent: GalaxyAgent

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        Log.i(TAG, "🚀 UFO³ Galaxy Android Agent 启动中...")

        // 初始化 Galaxy Agent
        galaxyAgent = GalaxyAgent.getInstance(this)

        // 从 assets/config.properties 读取 Gateway URL
        val gatewayUrl = loadGatewayUrl()

        galaxyAgent.initialize(gatewayUrl)
        galaxyAgent.start()

        // 启动悬浮窗服务
        val intent = Intent(this, FloatingWindowService::class.java)
        startService(intent)

        Log.i(TAG, "✅ UFO³ Galaxy Android Agent 已启动")
        Log.i(TAG, "   Agent ID: ${galaxyAgent.getStatus().optString("agent_id")}")
        Log.i(TAG, "   Gateway URL: $gatewayUrl")

        // 关闭主 Activity（悬浮窗和 Agent 会保持运行）
        finish()
    }

    /**
     * 从 assets/config.properties 读取 Gateway WebSocket URL
     * 如果读取失败则返回默认值
     */
    private fun loadGatewayUrl(): String {
        val defaultUrl = "ws://192.168.1.100:8000/ws/agent"
        return try {
            val props = Properties()
            assets.open("config.properties").use { props.load(it) }
            val url = props.getProperty("galaxy.gateway.url", defaultUrl)
            if (url.isBlank() || url.contains("x.x.x")) {
                Log.w(TAG, "⚠️ config.properties 中的 Gateway URL 未配置: $url, 使用默认值")
                defaultUrl
            } else {
                Log.i(TAG, "从 config.properties 读取 Gateway URL: $url")
                url
            }
        } catch (e: Exception) {
            Log.w(TAG, "读取 config.properties 失败, 使用默认 URL", e)
            defaultUrl
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        // 注意：这里不要调用 galaxyAgent.cleanup()
        // 因为 Agent 需要在后台持续运行
    }
}
