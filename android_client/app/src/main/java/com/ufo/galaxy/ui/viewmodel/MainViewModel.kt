package com.ufo.galaxy.ui.viewmodel

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ufo.galaxy.UFOGalaxyApplication
import com.ufo.galaxy.data.ChatMessage
import com.ufo.galaxy.data.MessageRole
import com.ufo.galaxy.network.GalaxyWebSocketClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * 主界面 UI 状态
 */
data class MainUiState(
    val messages: List<ChatMessage> = emptyList(),
    val inputText: String = "",
    val isLoading: Boolean = false,
    val isScrollExpanded: Boolean = true,
    val isConnected: Boolean = false,
    val error: String? = null
)

/**
 * 主界面 ViewModel
 * 管理聊天状态和与 Galaxy 服务器的通信
 */
class MainViewModel : ViewModel() {
    
    companion object {
        private const val TAG = "MainViewModel"
    }
    
    private val _uiState = MutableStateFlow(MainUiState())
    val uiState: StateFlow<MainUiState> = _uiState.asStateFlow()
    
    private val webSocketClient: GalaxyWebSocketClient
        get() = UFOGalaxyApplication.webSocketClient
    
    init {
        Log.d(TAG, "MainViewModel 初始化")
        setupWebSocketListener()
        addWelcomeMessage()
    }
    
    /**
     * 设置 WebSocket 监听器
     */
    private fun setupWebSocketListener() {
        webSocketClient.setListener(object : GalaxyWebSocketClient.Listener {
            override fun onConnected() {
                Log.d(TAG, "WebSocket 已连接")
                _uiState.update { it.copy(isConnected = true, error = null) }
            }
            
            override fun onDisconnected() {
                Log.d(TAG, "WebSocket 已断开")
                _uiState.update { it.copy(isConnected = false) }
            }
            
            override fun onMessage(message: String) {
                Log.d(TAG, "收到消息: $message")
                handleServerMessage(message)
            }
            
            override fun onError(error: String) {
                Log.e(TAG, "WebSocket 错误: $error")
                _uiState.update { it.copy(error = error, isLoading = false) }
            }
        })
    }
    
    /**
     * 添加欢迎消息
     */
    private fun addWelcomeMessage() {
        val welcomeMessage = ChatMessage(
            id = UUID.randomUUID().toString(),
            role = MessageRole.ASSISTANT,
            content = "你好！我是 UFO Galaxy 智能助手。\n\n我可以帮助你：\n• 控制智能设备\n• 执行自动化任务\n• 回答问题和提供建议\n\n有什么我可以帮助你的吗？",
            timestamp = System.currentTimeMillis()
        )
        _uiState.update { it.copy(messages = listOf(welcomeMessage)) }
    }
    
    /**
     * 处理服务器消息
     */
    private fun handleServerMessage(message: String) {
        viewModelScope.launch {
            try {
                // 解析服务器响应
                val assistantMessage = ChatMessage(
                    id = UUID.randomUUID().toString(),
                    role = MessageRole.ASSISTANT,
                    content = message,
                    timestamp = System.currentTimeMillis()
                )
                
                _uiState.update { state ->
                    state.copy(
                        messages = state.messages + assistantMessage,
                        isLoading = false
                    )
                }
            } catch (e: Exception) {
                Log.e(TAG, "处理消息失败", e)
                _uiState.update { it.copy(error = e.message, isLoading = false) }
            }
        }
    }
    
    /**
     * 更新输入文本
     */
    fun updateInput(text: String) {
        _uiState.update { it.copy(inputText = text) }
    }
    
    /**
     * 发送消息
     */
    fun sendMessage() {
        val text = _uiState.value.inputText.trim()
        if (text.isEmpty()) return
        
        Log.d(TAG, "发送消息: $text")
        
        // 添加用户消息
        val userMessage = ChatMessage(
            id = UUID.randomUUID().toString(),
            role = MessageRole.USER,
            content = text,
            timestamp = System.currentTimeMillis()
        )
        
        _uiState.update { state ->
            state.copy(
                messages = state.messages + userMessage,
                inputText = "",
                isLoading = true
            )
        }
        
        // 发送到服务器
        viewModelScope.launch {
            try {
                webSocketClient.send(text)
            } catch (e: Exception) {
                Log.e(TAG, "发送消息失败", e)
                _uiState.update { it.copy(error = e.message, isLoading = false) }
            }
        }
    }
    
    /**
     * 开始语音输入
     */
    fun startVoiceInput() {
        Log.d(TAG, "开始语音输入")
        // TODO: 实现语音识别
    }
    
    /**
     * 切换卷轴展开状态
     */
    fun toggleScroll() {
        _uiState.update { it.copy(isScrollExpanded = !it.isScrollExpanded) }
    }
    
    /**
     * Activity onResume 时调用
     */
    fun onResume() {
        Log.d(TAG, "onResume - 尝试连接 WebSocket")
        viewModelScope.launch {
            webSocketClient.connect()
        }
    }
    
    /**
     * Activity onPause 时调用
     */
    fun onPause() {
        Log.d(TAG, "onPause")
        // 保持连接，不断开
    }
    
    override fun onCleared() {
        super.onCleared()
        Log.d(TAG, "MainViewModel 销毁")
    }
}
