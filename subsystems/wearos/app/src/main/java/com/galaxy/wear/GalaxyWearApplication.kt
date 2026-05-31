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
