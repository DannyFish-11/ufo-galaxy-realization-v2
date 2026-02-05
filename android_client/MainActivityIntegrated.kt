package com.ufo.galaxy

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ufo.galaxy.ui.theme.GeekTheme
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject
import java.util.*

/**
 * UFO Galaxy Android客户端主Activity
 * 集成WebSocket通信和L4主循环
 */
class MainActivity : ComponentActivity() {
    
    companion object {
        private const val TAG = "UFOGalaxy"
        private const val WS_URL = "ws://your-server:8080/ws"
        private const val HTTP_URL = "http://your-server:8080/api"
    }
    
    private lateinit var webSocketManager: WebSocketManager
    private lateinit var galaxyApiClient: GalaxyApiClient
    
    // 状态管理
    private val _uiState = MutableStateFlow(UiState())
    val uiState: StateFlow<UiState> = _uiState
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // 初始化WebSocket管理器
        webSocketManager = WebSocketManager(WS_URL)
        
        // 初始化API客户端
        galaxyApiClient = GalaxyApiClient(HTTP_URL)
        
        // 连接到服务器
        connectToServer()
        
        setContent {
            GeekTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    GalaxyApp(
                        uiState = uiState.collectAsState().value,
                        onCommandSubmit = { command ->
                            onCommandSubmitted(command)
                        },
                        onTaskClick = { taskId ->
                            onTaskSelected(taskId)
                        }
                    )
                }
            }
        }
    }
    
    /**
     * 连接到服务器（WebSocket + HTTP）
     */
    private fun connectToServer() {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                // 连接WebSocket
                webSocketManager.connect(
                    onMessage = { message ->
                        handleServerMessage(message)
                    },
                    onError = { error ->
                        Log.e(TAG, "WebSocket错误: $error")
                        updateStatus("连接错误: $error")
                    }
                )
                
                updateStatus("已连接到服务器")
            } catch (e: Exception) {
                Log.e(TAG, "连接失败: ${e.message}")
                updateStatus("连接失败")
            }
        }
    }
    
    /**
     * 命令提交回调（UI → L4 集成点）
     * 当用户输入命令并提交时调用
     */
    private fun onCommandSubmitted(command: String) {
        if (command.isBlank()) return
        
        Log.d(TAG, "用户提交命令: $command")
        
        // 解析用户意图
        val intent = parseUserIntent(command)
        
        // 添加到消息列表
        addMessage(Message(
            id = UUID.randomUUID().toString(),
            content = command,
            isUser = true,
            timestamp = System.currentTimeMillis()
        ))
        
        // 发送到服务器
        CoroutineScope(Dispatchers.IO).launch {
            try {
                // 方法1: 通过WebSocket发送
                val message = JSONObject().apply {
                    put("type", "goal_submit")
                    put("description", command)
                    put("intent", JSONObject().apply {
                        put("type", intent.intentType)
                        put("confidence", intent.confidence)
                    })
                    put("timestamp", System.currentTimeMillis())
                }
                
                webSocketManager.send(message.toString())
                
                // 方法2: 通过HTTP发送（备选）
                // val response = galaxyApiClient.submitGoal(command, intent)
                
                withContext(Dispatchers.Main) {
                    updateStatus("目标已提交")
                }
                
            } catch (e: Exception) {
                Log.e(TAG, "发送失败: ${e.message}")
                withContext(Dispatchers.Main) {
                    addMessage(Message(
                        id = UUID.randomUUID().toString(),
                        content = "发送失败: ${e.message}",
                        isUser = false,
                        isError = true,
                        timestamp = System.currentTimeMillis()
                    ))
                }
            }
        }
    }
    
    /**
     * 解析用户意图
     */
    private fun parseUserIntent(command: String): UserIntent {
        val intent = UserIntent(
            rawCommand = command,
            intentType = "unknown",
            entities = emptyList(),
            confidence = 0.0f
        )
        
        val commandLower = command.toLowerCase()
        
        return when {
            commandLower.containsAny(listOf("搜索", "查找", "search", "find")) ->
                intent.copy(intentType = "search", confidence = 0.8f)
            commandLower.containsAny(listOf("打开", "启动", "open", "start")) ->
                intent.copy(intentType = "open_application", confidence = 0.8f)
            commandLower.containsAny(listOf("创建", "新建", "create", "new")) ->
                intent.copy(intentType = "create", confidence = 0.7f)
            commandLower.containsAny(listOf("删除", "移除", "delete", "remove")) ->
                intent.copy(intentType = "delete", confidence = 0.7f)
            commandLower.containsAny(listOf("查询", "询问", "query", "ask")) ->
                intent.copy(intentType = "query", confidence = 0.75f)
            else ->
                intent.copy(intentType = "general_task", confidence = 0.5f)
        }
    }
    
    /**
     * 处理服务器消息（L4 → UI 集成点）
     */
    private fun handleServerMessage(message: String) {
        try {
            val json = JSONObject(message)
            val eventType = json.optString("event_type")
            val data = json.optJSONObject("data")
            
            Log.d(TAG, "收到服务器消息: $eventType")
            
            when (eventType) {
                "GOAL_DECOMPOSITION_STARTED" -> {
                    val goalDesc = data?.optString("goal_description", "") ?: ""
                    updateStatus("正在分解目标: $goalDesc")
                }
                
                "GOAL_DECOMPOSITION_COMPLETED" -> {
                    val subtasks = data?.optJSONArray("subtasks")
                    val count = data?.optInt("subtask_count", 0) ?: 0
                    updateStatus("目标分解完成: $count 个子任务")
                    
                    // 显示子任务列表
                    addMessage(Message(
                        id = UUID.randomUUID().toString(),
                        content = "已分解为 $count 个子任务",
                        isUser = false,
                        timestamp = System.currentTimeMillis()
                    ))
                }
                
                "PLAN_GENERATION_STARTED" -> {
                    updateStatus("正在生成执行计划...")
                }
                
                "PLAN_GENERATION_COMPLETED" -> {
                    val actions = data?.optJSONArray("actions")
                    val count = data?.optInt("action_count", 0) ?: 0
                    updateStatus("计划生成完成: $count 个动作")
                }
                
                "ACTION_EXECUTION_STARTED" -> {
                    val actionId = data?.optString("action_id", "") ?: ""
                    val command = data?.optString("action_command", "") ?: ""
                    updateStatus("执行动作: $command")
                }
                
                "ACTION_EXECUTION_PROGRESS" -> {
                    val progress = data?.optDouble("progress", 0.0) ?: 0.0
                    val msg = data?.optString("message", "") ?: ""
                    updateProgress(progress.toFloat())
                }
                
                "ACTION_EXECUTION_COMPLETED" -> {
                    val success = data?.optBoolean("success", false) ?: false
                    updateProgress(if (success) 1.0f else 0.0f)
                }
                
                "TASK_COMPLETED" -> {
                    val goalDesc = data?.optString("goal_description", "") ?: ""
                    val success = data?.optBoolean("success", false) ?: false
                    val summary = data?.optJSONObject("summary")
                    
                    updateStatus("任务完成: ${if (success) "成功" else "失败"}")
                    
                    addMessage(Message(
                        id = UUID.randomUUID().toString(),
                        content = "任务完成: $goalDesc\n结果: ${if (success) "✅ 成功" else "❌ 失败"}",
                        isUser = false,
                        timestamp = System.currentTimeMillis()
                    ))
                }
                
                "ERROR_OCCURRED" -> {
                    val errorMsg = data?.optString("error_message", "") ?: ""
                    updateStatus("错误: $errorMsg")
                    
                    addMessage(Message(
                        id = UUID.randomUUID().toString(),
                        content = "❌ 错误: $errorMsg",
                        isUser = false,
                        isError = true,
                        timestamp = System.currentTimeMillis()
                    ))
                }
                
                else -> {
                    Log.d(TAG, "未知事件类型: $eventType")
                }
            }
            
        } catch (e: Exception) {
            Log.e(TAG, "处理消息失败: ${e.message}")
        }
    }
    
    private fun onTaskSelected(taskId: String) {
        Log.d(TAG, "选择任务: $taskId")
        // 显示任务详情
    }
    
    private fun addMessage(message: Message) {
        val currentMessages = _uiState.value.messages.toMutableList()
        currentMessages.add(message)
        _uiState.value = _uiState.value.copy(messages = currentMessages)
    }
    
    private fun updateStatus(status: String) {
        _uiState.value = _uiState.value.copy(status = status)
    }
    
    private fun updateProgress(progress: Float) {
        _uiState.value = _uiState.value.copy(progress = progress)
    }
    
    override fun onDestroy() {
        super.onDestroy()
        webSocketManager.disconnect()
    }
}

/**
 * WebSocket管理器
 */
class WebSocketManager(private val url: String) {
    
    private var webSocket: okhttp3.WebSocket? = null
    private val client = okhttp3.OkHttpClient()
    
    fun connect(
        onMessage: (String) -> Unit,
        onError: (String) -> Unit
    ) {
        val request = okhttp3.Request.Builder()
            .url(url)
            .build()
        
        val listener = object : okhttp3.WebSocketListener() {
            override fun onOpen(webSocket: okhttp3.WebSocket, response: okhttp3.Response) {
                Log.d("WebSocket", "连接已打开")
            }
            
            override fun onMessage(webSocket: okhttp3.WebSocket, text: String) {
                onMessage(text)
            }
            
            override fun onFailure(webSocket: okhttp3.WebSocket, t: Throwable, response: okhttp3.Response?) {
                onError(t.message ?: "未知错误")
            }
            
            override fun onClosing(webSocket: okhttp3.WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }
        }
        
        webSocket = client.newWebSocket(request, listener)
    }
    
    fun send(message: String) {
        webSocket?.send(message)
    }
    
    fun disconnect() {
        webSocket?.close(1000, "客户端断开")
    }
}

/**
 * Galaxy API客户端
 */
class GalaxyApiClient(private val baseUrl: String) {
    
    private val client = okhttp3.OkHttpClient()
    
    suspend fun submitGoal(command: String, intent: UserIntent): String {
        val json = JSONObject().apply {
            put("description", command)
            put("intent_type", intent.intentType)
            put("confidence", intent.confidence)
        }
        
        val request = okhttp3.Request.Builder()
            .url("$baseUrl/goals")
            .post(
                okhttp3.RequestBody.create(
                    okhttp3.MediaType.parse("application/json"),
                    json.toString()
                )
            )
            .build()
        
        val response = client.newCall(request).execute()
        return response.body()?.string() ?: ""
    }
    
    suspend fun getStatus(): String {
        val request = okhttp3.Request.Builder()
            .url("$baseUrl/status")
            .get()
            .build()
        
        val response = client.newCall(request).execute()
        return response.body()?.string() ?: ""
    }
}

/**
 * UI状态数据类
 */
data class UiState(
    val messages: List<Message> = emptyList(),
    val tasks: List<Task> = emptyList(),
    val status: String = "就绪",
    val progress: Float = 0.0f,
    val isConnected: Boolean = false
)

/**
 * 消息数据类
 */
data class Message(
    val id: String,
    val content: String,
    val isUser: Boolean,
    val isError: Boolean = false,
    val timestamp: Long
)

/**
 * 任务数据类
 */
data class Task(
    val id: String,
    val description: String,
    val status: TaskStatus,
    val progress: Float = 0.0f
)

/**
 * 任务状态枚举
 */
enum class TaskStatus {
    PENDING,
    DECOMPOSING,
    PLANNING,
    EXECUTING,
    COMPLETED,
    ERROR
}

/**
 * 用户意图数据类
 */
data class UserIntent(
    val rawCommand: String,
    val intentType: String,
    val entities: List<String>,
    val confidence: Float
)

/**
 * 字符串扩展函数
 */
fun String.containsAny(keywords: List<String>): Boolean {
    return keywords.any { this.contains(it) }
}

/**
 * Galaxy应用UI
 */
@Composable
fun GalaxyApp(
    uiState: UiState,
    onCommandSubmit: (String) -> Unit,
    onTaskClick: (String) -> Unit
) {
    var inputText by remember { mutableStateOf(TextFieldValue("")) }
    
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF1A1A2E))
            .padding(16.dp)
    ) {
        // 标题
        Text(
            text = "UFO Galaxy",
            style = TextStyle(
                fontSize = 28.sp,
                color = Color.White,
                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold
            ),
            modifier = Modifier.align(Alignment.CenterHorizontally)
        )
        
        // 状态栏
        Text(
            text = "● ${uiState.status}",
            style = TextStyle(
                fontSize = 12.sp,
                color = Color(0xFF4ECCA3)
            ),
            modifier = Modifier.align(Alignment.CenterHorizontally)
        )
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 进度条
        if (uiState.progress > 0) {
            LinearProgressIndicator(
                progress = uiState.progress,
                modifier = Modifier.fillMaxWidth(),
                color = Color(0xFFE94560)
            )
            Spacer(modifier = Modifier.height(8.dp))
        }
        
        // 消息列表
        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            reverseLayout = true
        ) {
            items(uiState.messages.reversed()) { message ->
                MessageItem(message)
                Spacer(modifier = Modifier.height(8.dp))
            }
        }
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 输入区域
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            BasicTextField(
                value = inputText,
                onValueChange = { inputText = it },
                modifier = Modifier
                    .weight(1f)
                    .background(
                        Color(0xFF16213E),
                        RoundedCornerShape(24.dp)
                    )
                    .padding(horizontal = 20.dp, vertical = 12.dp),
                textStyle = TextStyle(
                    fontSize = 16.sp,
                    color = Color.White
                ),
                decorationBox = { innerTextField ->
                    if (inputText.text.isEmpty()) {
                        Text(
                            text = "输入指令或问题...",
                            style = TextStyle(
                                fontSize = 16.sp,
                                color = Color.Gray
                            )
                        )
                    }
                    innerTextField()
                }
            )
            
            Spacer(modifier = Modifier.width(8.dp))
            
            IconButton(
                onClick = {
                    if (inputText.text.isNotBlank()) {
                        onCommandSubmit(inputText.text)
                        inputText = TextFieldValue("")
                    }
                },
                modifier = Modifier
                    .size(48.dp)
                    .background(Color(0xFFE94560), RoundedCornerShape(24.dp))
            ) {
                Icon(
                    imageVector = Icons.Default.Send,
                    contentDescription = "发送",
                    tint = Color.White
                )
            }
        }
    }
}

/**
 * 消息项组件
 */
@Composable
fun MessageItem(message: Message) {
    val backgroundColor = when {
        message.isError -> Color(0xFFE94560)
        message.isUser -> Color(0xFF0F3460)
        else -> Color(0xFF16213E)
    }
    
    val alignment = if (message.isUser) Alignment.End else Alignment.Start
    
    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = alignment
    ) {
        Text(
            text = message.content,
            style = TextStyle(
                fontSize = 14.sp,
                color = Color.White
            ),
            modifier = Modifier
                .background(backgroundColor, RoundedCornerShape(16.dp))
                .padding(12.dp)
                .widthIn(max = 280.dp)
        )
    }
}
