package com.ufo.galaxy.client

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import com.ufo.galaxy.agent.GalaxyAgent

class MainActivity : AppCompatActivity() {
    
    private val TAG = "MainActivity"
    private lateinit var galaxyAgent: GalaxyAgent
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        Log.i(TAG, "🚀 UFO³ Galaxy Android Agent 启动中...")
        
        // 初始化 Galaxy Agent
        galaxyAgent = GalaxyAgent.getInstance(this)
        
        // TODO: 从配置文件或用户输入获取 Gateway URL
        // 这里使用默认值，实际部署时需要修改为您的 Windows 电脑的 Tailscale IP
        val gatewayUrl = "ws://192.168.1.100:8000/ws/agent"
        
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
    
    override fun onDestroy() {
        super.onDestroy()
        // 注意：这里不要调用 galaxyAgent.cleanup()
        // 因为 Agent 需要在后台持续运行
    }
}
