package com.ufo.galaxy.client

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.lifecycleScope
import com.ufo.galaxy.api.GalaxyApiClient
import com.ufo.galaxy.ui.DynamicIsland
import com.ufo.galaxy.ui.IslandState
import com.ufo.galaxy.ui.SystemStatus
import com.ufo.galaxy.ui.theme.GeekTheme
import kotlinx.coroutines.launch

/**
 * UFO³ Galaxy 安卓端主 Activity (Jetpack Compose 版本)
 * 
 * 功能：
 * - 初始化 Galaxy API 客户端
 * - 显示灵动岛 UI
 * - 处理系统状态和消息
 * - 管理节点订阅
 * 
 * @author Manus AI
 * @date 2026-01-22
 */
class MainActivityCompose : ComponentActivity() {
    
    private lateinit var apiClient: GalaxyApiClient
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // 初始化 API 客户端
        apiClient = GalaxyApiClient(
            baseUrl = "http://100.123.215.126:8888",
            apiKey = null // 如果需要认证，在这里设置
        )
        apiClient.initialize()
        
        setContent {
            GeekTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = Color.Transparent
                ) {
                    GalaxyApp(apiClient = apiClient)
                }
            }
        }
    }
    
    override fun onDestroy() {
        super.onDestroy()
        apiClient.close()
    }
}

/**
 * Galaxy 应用主界面
 */
@Composable
fun GalaxyApp(apiClient: GalaxyApiClient) {
    // 观察连接状态
    val connectionState by apiClient.connectionState.collectAsState()
    
    // 观察消息
    val messages = remember { mutableStateListOf<String>() }
    LaunchedEffect(Unit) {
        apiClient.messages.collect { message ->
            when (message) {
                is com.ufo.galaxy.api.GalaxyMessage.ChatMessage -> {
                    messages.add("[${message.role.uppercase()}] ${message.content}")
                }
                is com.ufo.galaxy.api.GalaxyMessage.SystemMessage -> {
                    messages.add("[SYSTEM] ${message.content}")
                }
                is com.ufo.galaxy.api.GalaxyMessage.NotificationMessage -> {
                    messages.add("[NOTIFICATION] ${message.title}: ${message.body}")
                }
                is com.ufo.galaxy.api.GalaxyMessage.ErrorMessage -> {
                    messages.add("[ERROR] ${message.error}")
                }
            }
        }
    }
    
    // 观察节点状态
    val nodeStatus by apiClient.nodeStatus.collectAsState()
    
    // 系统状态
    val systemStatus = when (connectionState) {
        GalaxyApiClient.ConnectionState.CONNECTED -> SystemStatus.IDLE
        GalaxyApiClient.ConnectionState.CONNECTING -> SystemStatus.WORKING
        GalaxyApiClient.ConnectionState.ERROR -> SystemStatus.ERROR
        GalaxyApiClient.ConnectionState.DISCONNECTED -> SystemStatus.OFFLINE
    }
    
    // 当前任务
    val currentTask = when (connectionState) {
        GalaxyApiClient.ConnectionState.CONNECTED -> "CONNECTED"
        GalaxyApiClient.ConnectionState.CONNECTING -> "CONNECTING..."
        GalaxyApiClient.ConnectionState.ERROR -> "CONNECTION ERROR"
        GalaxyApiClient.ConnectionState.DISCONNECTED -> "OFFLINE"
    }
    
    // 显示灵动岛
    DynamicIsland(
        initialState = IslandState.COLLAPSED,
        systemStatus = systemStatus,
        currentTask = currentTask,
        taskProgress = null,
        onStateChange = { newState ->
            // 处理状态变化
            when (newState) {
                IslandState.FULLY_EXPANDED -> {
                    // 订阅核心节点
                    apiClient.subscribeToNode("node_01")
                    apiClient.subscribeToNode("node_67")
                }
                else -> {}
            }
        },
        onClose = {
            // 关闭应用
            // finish()
        }
    )
}
