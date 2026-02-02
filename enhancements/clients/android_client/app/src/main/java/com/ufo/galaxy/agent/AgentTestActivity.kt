package com.ufo.galaxy.agent

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Galaxy Agent 集成测试界面
 * 
 * 用于测试和验证 Agent 的完整功能
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class AgentTestActivity : AppCompatActivity() {
    
    private lateinit var galaxyAgent: GalaxyAgent
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        galaxyAgent = GalaxyAgent.getInstance(this)
        
        setContentView(ComposeView(this).apply {
            setContent {
                AgentTestScreen(galaxyAgent)
            }
        })
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentTestScreen(galaxyAgent: GalaxyAgent) {
    val scope = rememberCoroutineScope()
    var statusText by remember { mutableStateOf("等待测试...") }
    var healthCheckResult by remember { mutableStateOf("") }
    
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Galaxy Agent 集成测试") }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState())
        ) {
            // Agent 状态卡片
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer
                )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "Agent 状态",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    val status = galaxyAgent.getStatus()
                    Text(
                        text = """
                            初始化: ${if (status.optBoolean("is_initialized")) "✅" else "❌"}
                            运行中: ${if (status.optBoolean("is_running")) "✅" else "❌"}
                            已注册: ${if (status.optBoolean("is_registered")) "✅" else "❌"}
                            已连接: ${if (status.optBoolean("is_connected")) "✅" else "❌"}
                            无障碍: ${if (status.optBoolean("accessibility_enabled")) "✅" else "❌"}
                            
                            Agent ID: ${status.optString("agent_id")}
                            Device ID: ${status.optString("device_id")}
                        """.trimIndent(),
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 控制按钮
            Button(
                onClick = {
                    scope.launch {
                        val gatewayUrl = "ws://192.168.1.100:8000/ws/agent"
                        galaxyAgent.initialize(gatewayUrl)
                        statusText = "Agent 已初始化\nGateway: $gatewayUrl"
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("初始化 Agent")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    scope.launch {
                        galaxyAgent.start()
                        statusText = "Agent 已启动"
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("启动 Agent")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    scope.launch {
                        galaxyAgent.stop()
                        statusText = "Agent 已停止"
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("停止 Agent")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    scope.launch {
                        val healthCheck = galaxyAgent.runHealthCheck()
                        healthCheckResult = healthCheck.toString(2)
                        statusText = "健康检查完成\n通过: ${healthCheck.optInt("passed_checks")}/${healthCheck.optInt("total_checks")}"
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("运行健康检查")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    scope.launch {
                        val message = JSONObject().apply {
                            put("type", "test_message")
                            put("content", "Hello from Android Agent!")
                            put("timestamp", System.currentTimeMillis())
                        }
                        val sent = galaxyAgent.sendMessage(message)
                        statusText = if (sent) "测试消息已发送" else "发送失败（未连接）"
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("发送测试消息")
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 状态文本
            Card(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "操作结果",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = statusText,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
            
            if (healthCheckResult.isNotEmpty()) {
                Spacer(modifier = Modifier.height(16.dp))
                
                Card(
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "健康检查结果",
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = healthCheckResult,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
        }
    }
}
