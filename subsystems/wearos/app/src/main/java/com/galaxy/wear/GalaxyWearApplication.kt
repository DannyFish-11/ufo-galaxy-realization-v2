package com.galaxy.wear

import android.app.Application
import android.util.Log
import com.galaxy.wear.data.AIPClient
import com.galaxy.wear.data.AIPConnectionState
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Galaxy Wear OS Application
 *
 * Singleton entry point. Manages the AIP v3 WebSocket connection
 * and global coroutine scope for the watch.
 *
 * Thread-safety: All mutable state accessed via Main dispatcher.
 */
class GalaxyWearApplication : Application() {

    companion object {
        const val TAG = "GalaxyWear"
    }

    private val _phase = MutableStateFlow(Phase.SILENT)
    val phase: StateFlow<Phase> = _phase.asStateFlow()

    private val _connectionState = MutableStateFlow(AIPConnectionState.DISCONNECTED)
    val connectionState: StateFlow<AIPConnectionState> = _connectionState.asStateFlow()

    lateinit var aipClient: AIPClient
        private set

    private val appScope = CoroutineScope(
        SupervisorJob() + Dispatchers.Main.immediate + CoroutineExceptionHandler { _, exc ->
            Log.e(TAG, "Uncaught coroutine error: ${exc.message}", exc)
        }
    )

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "Galaxy Wear OS starting...")

        aipClient = AIPClient(
            context = this,
            scope = appScope
        )

        // Observe connection state → phase mapping
        appScope.launch {
            try {
                aipClient.connectionState.collect { state ->
                    _connectionState.value = state
                    val newPhase = when (state) {
                        AIPConnectionState.CONNECTED -> Phase.LIMINAL
                        AIPConnectionState.AUTHENTICATED -> Phase.MANIFEST
                        else -> {
                            // Only fall back to SILENT if we were previously active
                            if (_phase.value == Phase.MANIFEST || _phase.value == Phase.LIMINAL) {
                                Log.i(TAG, "AIP disconnected — falling back to SILENT")
                                Phase.SILENT
                            } else {
                                _phase.value // Keep current
                            }
                        }
                    }
                    if (newPhase != _phase.value) {
                        _phase.value = newPhase
                        Log.i(TAG, "Phase transition: $newPhase (from $state)")
                    }
                }
            } catch (e: CancellationException) {
                Log.d(TAG, "Phase observer cancelled")
            } catch (e: Exception) {
                Log.e(TAG, "Phase observer crashed: ${e.message}")
            }
        }

        // LIQUID-ISLAND: 收集灵动岛消息
        appScope.launch {
            try {
                aipClient.messages.collect { msg ->
                    when (msg) {
                        is AIPMessage.LiquidEvent -> handleLiquidEvent(msg)
                        else -> {} // Ignore other types
                    }
                }
            } catch (e: CancellationException) {
                Log.d(TAG, "Liquid event observer cancelled")
            } catch (e: Exception) {
                Log.e(TAG, "Liquid event observer crashed: ${e.message}")
            }
        }
    }

    private fun handleLiquidEvent(event: AIPMessage.LiquidEvent) {
        Log.i(TAG, "LiquidIsland: msg=${event.msgType} content=${event.content}")
        when (event.msgType) {
            "phase_change" -> {
                val toPhase = event.content["to_phase"]?.jsonPrimitive?.content
                if (toPhase != null) {
                    _phase.value = when (toPhase.lowercase()) {
                        "manifest" -> Phase.MANIFEST
                        "liminal" -> Phase.LIMINAL
                        else -> Phase.SILENT
                    }
                }
            }
            "task_done" -> {
                // 任务完成：光环跳动 + 马达反馈
                val deviceName = event.content["device_name"]?.jsonPrimitive?.content ?: "设备"
                Log.i(TAG, "LiquidIsland: task done on $deviceName")
                // TODO: trigger halo pulse + haptic feedback
            }
            "task_progress" -> {
                // 任务进度：更新显示 "2/3 完成"
                val completed = event.content["completed"]?.jsonPrimitive?.int ?: 0
                val total = event.content["total"]?.jsonPrimitive?.int ?: 0
                Log.i(TAG, "LiquidIsland: progress $completed/$total")
                // TODO: update progress indicator
            }
            "text_result" -> {
                // 文本结果（如天气查询）：显示在表盘上
                val text = event.content["text"]?.jsonPrimitive?.content ?: ""
                Log.i(TAG, "LiquidIsland: text result: $text")
                // TODO: display text on watch face temporarily
            }
        }
    }

    fun connect(serverUrl: String, token: String) {
        // Prevent concurrent connect calls
        if (_connectionState.value == AIPConnectionState.CONNECTING) {
            Log.w(TAG, "Connection already in progress")
            return
        }
        appScope.launch {
            try {
                aipClient.connect(serverUrl, token)
            } catch (e: CancellationException) {
                Log.d(TAG, "Connect cancelled")
            } catch (e: Exception) {
                Log.e(TAG, "Failed to connect: ${e.message}")
            }
        }
    }

    fun disconnect() {
        appScope.launch {
            try {
                aipClient.disconnect()
            } catch (e: Exception) {
                Log.w(TAG, "Disconnect error: ${e.message}")
            }
        }
    }

    override fun onTerminate() {
        appScope.cancel()
        super.onTerminate()
    }
}

/** Three-phase lifecycle (matches Desktop/Android) */
enum class Phase {
    SILENT,    // Black — disconnected / standby
    LIMINAL,   // Gray — connecting / waiting
    MANIFEST   // White — fully operational
}
