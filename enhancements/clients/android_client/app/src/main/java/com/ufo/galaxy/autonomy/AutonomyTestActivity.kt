package com.ufo.galaxy.autonomy

import android.os.Bundle
import android.widget.Toast
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
 * 自主操纵功能测试界面
 * 
 * 用于测试和演示自主操纵功能
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class AutonomyTestActivity : AppCompatActivity() {
    
    private lateinit var autonomyManager: AutonomyManager
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        autonomyManager = AutonomyManager.getInstance(this)
        
        setContentView(ComposeView(this).apply {
            setContent {
                AutonomyTestScreen(autonomyManager)
            }
        })
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AutonomyTestScreen(autonomyManager: AutonomyManager) {
    val scope = rememberCoroutineScope()
    var testResult by remember { mutableStateOf("等待测试...") }
    var uiTreeText by remember { mutableStateOf("") }
    
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("自主操纵功能测试") }
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
            // 服务状态
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = if (autonomyManager.isAccessibilityServiceEnabled()) 
                        MaterialTheme.colorScheme.primaryContainer 
                    else 
                        MaterialTheme.colorScheme.errorContainer
                )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "服务状态",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = if (autonomyManager.isAccessibilityServiceEnabled()) 
                            "✅ 无障碍服务已启用" 
                        else 
                            "❌ 无障碍服务未启用",
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 操作按钮
            Button(
                onClick = { autonomyManager.openAccessibilitySettings() },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("打开无障碍设置")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    scope.launch {
                        val result = autonomyManager.runDiagnostics()
                        testResult = result.toString(2)
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("运行诊断测试")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    scope.launch {
                        val uiTree = autonomyManager.captureUITree()
                        if (uiTree.optString("status") == "success") {
                            uiTreeText = UITreeVisualizer.toReadableText(uiTree)
                        } else {
                            uiTreeText = "抓取失败: ${uiTree.optString("message")}"
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("抓取当前 UI 树")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    autonomyManager.startUITreePush(5000)
                    testResult = "已启动 UI 树自动推送"
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("启动 UI 树推送")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    autonomyManager.stopUITreePush()
                    testResult = "已停止 UI 树自动推送"
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("停止 UI 树推送")
            }
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Button(
                onClick = {
                    scope.launch {
                        // 测试点击操作
                        val action = JSONObject().apply {
                            put("type", "press_key")
                            put("params", JSONObject().apply {
                                put("key", "back")
                            })
                        }
                        val result = autonomyManager.executeAction(action)
                        testResult = result.toString(2)
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("测试按返回键")
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            
            // 测试结果
            Card(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "测试结果",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = testResult,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
            
            if (uiTreeText.isNotEmpty()) {
                Spacer(modifier = Modifier.height(16.dp))
                
                Card(
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "UI 树结构",
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = uiTreeText,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
        }
    }
}
