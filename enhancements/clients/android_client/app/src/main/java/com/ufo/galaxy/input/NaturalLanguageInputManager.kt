package com.ufo.galaxy.input

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * 自然语言输入管理器
 * 
 * 支持语音和文本输入，作为用户与 Galaxy 系统交互的主要方式
 * 
 * 功能：
 * - 语音识别（Speech Recognition）
 * - 文本输入
 * - 输入历史记录
 * - 输入状态管理
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class NaturalLanguageInputManager(private val context: Context) {
    
    companion object {
        private const val TAG = "NLInputManager"
        private const val MAX_HISTORY_SIZE = 100
    }
    
    // 语音识别器
    private var speechRecognizer: SpeechRecognizer? = null
    
    // 输入状态
    private val _inputState = MutableStateFlow<InputState>(InputState.Idle)
    val inputState: StateFlow<InputState> = _inputState
    
    // 识别结果
    private val _recognitionResult = MutableStateFlow<String?>(null)
    val recognitionResult: StateFlow<String?> = _recognitionResult
    
    // 输入历史
    private val inputHistory = mutableListOf<InputRecord>()
    
    // 输入回调
    var onInputReceived: ((String) -> Unit)? = null
    
    /**
     * 输入状态
     */
    sealed class InputState {
        object Idle : InputState()
        object Listening : InputState()
        object Processing : InputState()
        data class Error(val message: String) : InputState()
    }
    
    /**
     * 输入记录
     */
    data class InputRecord(
        val input: String,
        val type: InputType,
        val timestamp: Long
    )
    
    /**
     * 输入类型
     */
    enum class InputType {
        VOICE,
        TEXT
    }
    
    /**
     * 初始化语音识别器
     */
    fun initialize() {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            Log.w(TAG, "⚠️ 语音识别不可用")
            return
        }
        
        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(recognitionListener)
        }
        
        Log.i(TAG, "✅ 自然语言输入管理器初始化完成")
    }
    
    /**
     * 开始语音识别
     */
    fun startVoiceInput() {
        if (speechRecognizer == null) {
            Log.w(TAG, "⚠️ 语音识别器未初始化")
            _inputState.value = InputState.Error("语音识别器未初始化")
            return
        }
        
        if (_inputState.value is InputState.Listening) {
            Log.w(TAG, "⚠️ 正在进行语音识别")
            return
        }
        
        Log.i(TAG, "🎤 开始语音识别")
        _inputState.value = InputState.Listening
        
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        }
        
        try {
            speechRecognizer?.startListening(intent)
        } catch (e: Exception) {
            Log.e(TAG, "❌ 启动语音识别失败", e)
            _inputState.value = InputState.Error("启动语音识别失败: ${e.message}")
        }
    }
    
    /**
     * 停止语音识别
     */
    fun stopVoiceInput() {
        Log.i(TAG, "🛑 停止语音识别")
        speechRecognizer?.stopListening()
        _inputState.value = InputState.Idle
    }
    
    /**
     * 取消语音识别
     */
    fun cancelVoiceInput() {
        Log.i(TAG, "❌ 取消语音识别")
        speechRecognizer?.cancel()
        _inputState.value = InputState.Idle
    }
    
    /**
     * 处理文本输入
     */
    fun processTextInput(text: String) {
        if (text.isBlank()) {
            Log.w(TAG, "⚠️ 输入文本为空")
            return
        }
        
        Log.i(TAG, "📝 处理文本输入: $text")
        _inputState.value = InputState.Processing
        
        // 添加到历史记录
        addToHistory(text, InputType.TEXT)
        
        // 触发回调
        onInputReceived?.invoke(text)
        
        _inputState.value = InputState.Idle
    }
    
    /**
     * 添加到历史记录
     */
    private fun addToHistory(input: String, type: InputType) {
        val record = InputRecord(
            input = input,
            type = type,
            timestamp = System.currentTimeMillis()
        )
        
        inputHistory.add(0, record)
        
        // 限制历史记录大小
        if (inputHistory.size > MAX_HISTORY_SIZE) {
            inputHistory.removeAt(inputHistory.size - 1)
        }
    }
    
    /**
     * 获取输入历史
     */
    fun getHistory(): List<InputRecord> {
        return inputHistory.toList()
    }
    
    /**
     * 清空历史记录
     */
    fun clearHistory() {
        inputHistory.clear()
        Log.i(TAG, "🗑️ 历史记录已清空")
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        speechRecognizer?.destroy()
        speechRecognizer = null
        Log.i(TAG, "✅ 资源已清理")
    }
    
    /**
     * 语音识别监听器
     */
    private val recognitionListener = object : RecognitionListener {
        
        override fun onReadyForSpeech(params: Bundle?) {
            Log.d(TAG, "🎤 准备接收语音")
        }
        
        override fun onBeginningOfSpeech() {
            Log.d(TAG, "🎤 开始说话")
        }
        
        override fun onRmsChanged(rmsdB: Float) {
            // 音量变化，可用于显示音量波形
        }
        
        override fun onBufferReceived(buffer: ByteArray?) {
            // 接收到音频缓冲区
        }
        
        override fun onEndOfSpeech() {
            Log.d(TAG, "🎤 说话结束")
            _inputState.value = InputState.Processing
        }
        
        override fun onError(error: Int) {
            val errorMessage = when (error) {
                SpeechRecognizer.ERROR_AUDIO -> "音频错误"
                SpeechRecognizer.ERROR_CLIENT -> "客户端错误"
                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "权限不足"
                SpeechRecognizer.ERROR_NETWORK -> "网络错误"
                SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "网络超时"
                SpeechRecognizer.ERROR_NO_MATCH -> "无匹配结果"
                SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "识别器忙碌"
                SpeechRecognizer.ERROR_SERVER -> "服务器错误"
                SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "语音超时"
                else -> "未知错误"
            }
            
            Log.e(TAG, "❌ 语音识别错误: $errorMessage (code=$error)")
            _inputState.value = InputState.Error(errorMessage)
        }
        
        override fun onResults(results: Bundle?) {
            val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            
            if (matches.isNullOrEmpty()) {
                Log.w(TAG, "⚠️ 未识别到语音")
                _inputState.value = InputState.Idle
                return
            }
            
            val recognizedText = matches[0]
            Log.i(TAG, "✅ 识别结果: $recognizedText")
            
            _recognitionResult.value = recognizedText
            
            // 添加到历史记录
            addToHistory(recognizedText, InputType.VOICE)
            
            // 触发回调
            onInputReceived?.invoke(recognizedText)
            
            _inputState.value = InputState.Idle
        }
        
        override fun onPartialResults(partialResults: Bundle?) {
            val matches = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            
            if (!matches.isNullOrEmpty()) {
                val partialText = matches[0]
                Log.d(TAG, "📝 部分结果: $partialText")
                _recognitionResult.value = partialText
            }
        }
        
        override fun onEvent(eventType: Int, params: Bundle?) {
            // 其他事件
        }
    }
}
