package com.ufo.galaxy.speech

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale

/**
 * 语音输入状态
 */
sealed class SpeechState {
    object Idle : SpeechState()
    object Listening : SpeechState()
    object Processing : SpeechState()
    data class Result(val text: String) : SpeechState()
    data class Error(val message: String) : SpeechState()
}

/**
 * 语音输入管理器
 * 封装 Android SpeechRecognizer，提供简洁的语音识别接口
 */
class SpeechInputManager(private val context: Context) {
    
    companion object {
        private const val TAG = "SpeechInputManager"
    }
    
    private var speechRecognizer: SpeechRecognizer? = null
    private var isInitialized = false
    
    private val _state = MutableStateFlow<SpeechState>(SpeechState.Idle)
    val state: StateFlow<SpeechState> = _state.asStateFlow()
    
    private val _partialResult = MutableStateFlow("")
    val partialResult: StateFlow<String> = _partialResult.asStateFlow()
    
    // 回调
    var onResult: ((String) -> Unit)? = null
    var onError: ((String) -> Unit)? = null
    var onPartialResult: ((String) -> Unit)? = null
    
    /**
     * 初始化语音识别器
     */
    fun initialize(): Boolean {
        if (isInitialized) return true
        
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            Log.e(TAG, "设备不支持语音识别")
            return false
        }
        
        try {
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
                setRecognitionListener(createRecognitionListener())
            }
            isInitialized = true
            Log.i(TAG, "语音识别器初始化成功")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "初始化语音识别器失败", e)
            return false
        }
    }
    
    /**
     * 开始语音识别
     */
    fun startListening(language: String = "zh-CN") {
        if (!isInitialized) {
            if (!initialize()) {
                _state.value = SpeechState.Error("语音识别不可用")
                onError?.invoke("语音识别不可用")
                return
            }
        }
        
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, language)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, language)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1500L)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1000L)
        }
        
        try {
            speechRecognizer?.startListening(intent)
            _state.value = SpeechState.Listening
            _partialResult.value = ""
            Log.i(TAG, "开始语音识别")
        } catch (e: Exception) {
            Log.e(TAG, "启动语音识别失败", e)
            _state.value = SpeechState.Error("启动失败: ${e.message}")
            onError?.invoke("启动失败: ${e.message}")
        }
    }
    
    /**
     * 停止语音识别
     */
    fun stopListening() {
        try {
            speechRecognizer?.stopListening()
            Log.i(TAG, "停止语音识别")
        } catch (e: Exception) {
            Log.e(TAG, "停止语音识别失败", e)
        }
    }
    
    /**
     * 取消语音识别
     */
    fun cancel() {
        try {
            speechRecognizer?.cancel()
            _state.value = SpeechState.Idle
            _partialResult.value = ""
            Log.i(TAG, "取消语音识别")
        } catch (e: Exception) {
            Log.e(TAG, "取消语音识别失败", e)
        }
    }
    
    /**
     * 释放资源
     */
    fun release() {
        try {
            speechRecognizer?.destroy()
            speechRecognizer = null
            isInitialized = false
            Log.i(TAG, "语音识别器已释放")
        } catch (e: Exception) {
            Log.e(TAG, "释放语音识别器失败", e)
        }
    }
    
    /**
     * 创建识别监听器
     */
    private fun createRecognitionListener(): RecognitionListener {
        return object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {
                Log.d(TAG, "准备就绪，请说话")
                _state.value = SpeechState.Listening
            }
            
            override fun onBeginningOfSpeech() {
                Log.d(TAG, "检测到语音开始")
            }
            
            override fun onRmsChanged(rmsdB: Float) {
                // 音量变化，可用于显示音量指示器
            }
            
            override fun onBufferReceived(buffer: ByteArray?) {
                // 音频缓冲
            }
            
            override fun onEndOfSpeech() {
                Log.d(TAG, "语音结束")
                _state.value = SpeechState.Processing
            }
            
            override fun onError(error: Int) {
                val errorMessage = getErrorMessage(error)
                Log.e(TAG, "识别错误: $errorMessage (code: $error)")
                _state.value = SpeechState.Error(errorMessage)
                onError?.invoke(errorMessage)
            }
            
            override fun onResults(results: Bundle?) {
                val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                val result = matches?.firstOrNull() ?: ""
                
                Log.i(TAG, "识别结果: $result")
                _state.value = SpeechState.Result(result)
                onResult?.invoke(result)
            }
            
            override fun onPartialResults(partialResults: Bundle?) {
                val matches = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                val partial = matches?.firstOrNull() ?: ""
                
                if (partial.isNotEmpty()) {
                    Log.d(TAG, "部分结果: $partial")
                    _partialResult.value = partial
                    onPartialResult?.invoke(partial)
                }
            }
            
            override fun onEvent(eventType: Int, params: Bundle?) {
                Log.d(TAG, "事件: $eventType")
            }
        }
    }
    
    /**
     * 获取错误消息
     */
    private fun getErrorMessage(errorCode: Int): String {
        return when (errorCode) {
            SpeechRecognizer.ERROR_AUDIO -> "音频录制错误"
            SpeechRecognizer.ERROR_CLIENT -> "客户端错误"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "权限不足"
            SpeechRecognizer.ERROR_NETWORK -> "网络错误"
            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "网络超时"
            SpeechRecognizer.ERROR_NO_MATCH -> "未识别到语音"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "识别器忙"
            SpeechRecognizer.ERROR_SERVER -> "服务器错误"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "语音超时"
            else -> "未知错误 ($errorCode)"
        }
    }
    
    /**
     * 检查语音识别是否可用
     */
    fun isAvailable(): Boolean {
        return SpeechRecognizer.isRecognitionAvailable(context)
    }
    
    /**
     * 获取支持的语言列表
     */
    fun getSupportedLanguages(): List<Locale> {
        return listOf(
            Locale.SIMPLIFIED_CHINESE,
            Locale.TRADITIONAL_CHINESE,
            Locale.ENGLISH,
            Locale.US,
            Locale.UK,
            Locale.JAPANESE,
            Locale.KOREAN
        )
    }
}
