package com.ufo.galaxy

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.ufo.galaxy.agent.GalaxyAgentV2
import com.ufo.galaxy.input.NaturalLanguageInputManager
import com.ufo.galaxy.service.FloatingWindowService
import com.ufo.galaxy.ui.theme.GeekThemePremium
import kotlinx.coroutines.launch
import java.util.*

/**
 * UFO³ Galaxy Android Agent - 主活动
 * 
 * 完整集成的 Android APP，作为 Galaxy 系统的移动端节点
 * 
 * 核心功能：
 * 1. 灵动岛 UI - 悬浮窗交互界面
 * 2. 自然语言输入 - 语音和文本
 * 3. Galaxy 系统集成 - 连接到 Galaxy Gateway
 * 4. 自主操纵能力 - AccessibilityService
 * 5. 跨设备协同 - 多设备通信
 * 
 * @author UFO³ Galaxy Enhancement Team
 * @version 2.2
 */
class MainActivity : ComponentActivity() {
    
    // Galaxy Agent 实例
    private lateinit var galaxyAgent: GalaxyAgentV2
    
    // 自然语言输入管理器
    private lateinit var inputManager: NaturalLanguageInputManager
    
    // 权限请求
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.values.all { it }
        if (allGranted) {
            Toast.makeText(this, "✅ 所有权限已授予", Toast.LENGTH_SHORT).show()
            initializeGalaxyAgent()
        } else {
            Toast.makeText(this, "⚠️ 需要所有权限才能正常工作", Toast.LENGTH_LONG).show()
        }
    }
    
    // 语音识别
    private val speechRecognizerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val matches = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            matches?.firstOrNull()?.let { text ->
                handleNaturalLanguageInput(text, isVoice = true)
            }
        }
    }
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        setContent {
            GeekThemePremium {
                MainScreen()
            }
        }
        
        // 初始化自然语言输入管理器
        inputManager = NaturalLanguageInputManager(this)
        inputManager.initialize()
        
        // 设置输入回调
        inputManager.onInputReceived = { input ->
            handleNaturalLanguageInput(input, isVoice = false)
        }
        
        // 请求必要权限
        requestNecessaryPermissions()
    }
    
    /**
     * 主界面 Composable
     */
    @Composable
    fun MainScreen() {
        val scope = rememberCoroutineScope()
        var agentStatus by remember { mutableStateOf("未初始化") }
        var floatingWindowActive by remember { mutableStateOf(false) }
        var inputText by remember { mutableStateOf("") }
        
        // 监听 Agent 状态
        LaunchedEffect(Unit) {
            if (::galaxyAgent.isInitialized) {
                galaxyAgent.status.collect { status ->
                    agentStatus = status
                }
            }
        }
        
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                // 标题
                Text(
                    text = "UFO³ Galaxy",
                    style = MaterialTheme.typography.headlineLarge,
                    color = MaterialTheme.colorScheme.primary
                )
                
                Text(
                    text = "Android Agent v2.2",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                
                Spacer(modifier = Modifier.height(32.dp))
                
                // Agent 状态卡片
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Text(
                            text = "Agent 状态",
                            style = MaterialTheme.typography.titleMedium
                        )
                        Text(
                            text = agentStatus,
                            style = MaterialTheme.typography.bodyLarge,
                            color = when {
                                agentStatus.contains("已连接") -> MaterialTheme.colorScheme.primary
                                agentStatus.contains("错误") -> MaterialTheme.colorScheme.error
                                else -> MaterialTheme.colorScheme.onSurfaceVariant
                            }
                        )
                    }
                }
                
                // 悬浮窗控制
                Button(
                    onClick = {
                        if (floatingWindowActive) {
                            stopFloatingWindow()
                            floatingWindowActive = false
                        } else {
                            if (checkOverlayPermission()) {
                                startFloatingWindow()
                                floatingWindowActive = true
                            } else {
                                requestOverlayPermission()
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(if (floatingWindowActive) "关闭悬浮窗" else "启动悬浮窗")
                }
                
                // 自然语言输入
                OutlinedTextField(
                    value = inputText,
                    onValueChange = { inputText = it },
                    label = { Text("输入指令") },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("例如：打开微信") }
                )
                
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    // 发送文本指令
                    Button(
                        onClick = {
                            if (inputText.isNotBlank()) {
                                handleNaturalLanguageInput(inputText, isVoice = false)
                                inputText = ""
                            }
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("发送")
                    }
                    
                    // 语音输入
                    Button(
                        onClick = { startVoiceRecognition() },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("🎤 语音")
                    }
                }
                
                Spacer(modifier = Modifier.height(16.dp))
                
                // 快捷操作
                Text(
                    text = "快捷操作",
                    style = MaterialTheme.typography.titleMedium
                )
                
                Button(
                    onClick = { openAccessibilitySettings() },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("开启无障碍服务")
                }
                
                Button(
                    onClick = { openAgentSettings() },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Agent 设置")
                }
                
                Spacer(modifier = Modifier.weight(1f))
                
                // 底部信息
                Text(
                    text = "通过自然语言控制您的所有设备",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
    
    /**
     * 请求必要权限
     */
    private fun requestNecessaryPermissions() {
        val permissions = mutableListOf<String>()
        
        // 录音权限（语音输入）
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.RECORD_AUDIO)
        }
        
        // 通知权限（Android 13+）
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                permissions.add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
        
        if (permissions.isNotEmpty()) {
            permissionLauncher.launch(permissions.toTypedArray())
        } else {
            initializeGalaxyAgent()
        }
    }
    
    /**
     * 初始化 Galaxy Agent
     */
    private fun initializeGalaxyAgent() {
        try {
            galaxyAgent = GalaxyAgentV2(applicationContext)
            galaxyAgent.start()
            Toast.makeText(this, "✅ Galaxy Agent 已启动", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "❌ Agent 启动失败: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }
    
    /**
     * 处理自然语言输入
     */
    private fun handleNaturalLanguageInput(text: String, isVoice: Boolean) {
        if (!::galaxyAgent.isInitialized) {
            Toast.makeText(this, "⚠️ Agent 未初始化", Toast.LENGTH_SHORT).show()
            return
        }
        
        Toast.makeText(
            this,
            if (isVoice) "🎤 语音: $text" else "📝 文本: $text",
            Toast.LENGTH_SHORT
        ).show()
        
        // 发送到 Galaxy Gateway
        galaxyAgent.sendCommand(text)
    }
    
    /**
     * 启动语音识别
     */
    private fun startVoiceRecognition() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PROMPT, "请说出您的指令...")
        }
        
        try {
            speechRecognizerLauncher.launch(intent)
        } catch (e: Exception) {
            Toast.makeText(this, "❌ 语音识别不可用", Toast.LENGTH_SHORT).show()
        }
    }
    
    /**
     * 检查悬浮窗权限
     */
    private fun checkOverlayPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Settings.canDrawOverlays(this)
        } else {
            true
        }
    }
    
    /**
     * 请求悬浮窗权限
     */
    private fun requestOverlayPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")
            )
            startActivity(intent)
            Toast.makeText(this, "请授予悬浮窗权限", Toast.LENGTH_LONG).show()
        }
    }
    
    /**
     * 启动悬浮窗服务
     */
    private fun startFloatingWindow() {
        val intent = Intent(this, FloatingWindowService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        Toast.makeText(this, "✅ 悬浮窗已启动", Toast.LENGTH_SHORT).show()
    }
    
    /**
     * 停止悬浮窗服务
     */
    private fun stopFloatingWindow() {
        val intent = Intent(this, FloatingWindowService::class.java)
        stopService(intent)
        Toast.makeText(this, "悬浮窗已关闭", Toast.LENGTH_SHORT).show()
    }
    
    /**
     * 打开无障碍服务设置
     */
    private fun openAccessibilitySettings() {
        val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
        startActivity(intent)
        Toast.makeText(this, "请开启 UFO³ Galaxy 自主操纵服务", Toast.LENGTH_LONG).show()
    }
    
    /**
     * 打开 Agent 设置
     */
    private fun openAgentSettings() {
        // TODO: 实现设置界面
        Toast.makeText(this, "设置功能开发中...", Toast.LENGTH_SHORT).show()
    }
    
    override fun onDestroy() {
        super.onDestroy()
        if (::galaxyAgent.isInitialized) {
            galaxyAgent.stop()
        }
    }
}
