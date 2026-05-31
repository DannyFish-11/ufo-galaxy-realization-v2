package com.galaxy.wear.data

import android.content.Context
import android.util.Log
import com.galaxy.wear.GalaxyWearApplication
import io.ktor.client.*
import io.ktor.client.engine.okhttp.*
import io.ktor.client.plugins.*
import io.ktor.client.plugins.contentnegotiation.*
import io.ktor.client.plugins.logging.*
import io.ktor.client.plugins.websocket.*
import io.ktor.serialization.kotlinx.json.*
import io.ktor.websocket.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*
import kotlin.coroutines.cancellation.CancellationException

/**
 * AIP v3 WebSocket Client (Wear OS variant)
 *
 * Fixes from audit:
 * - Thread-safe connect/disconnect with Mutex
 * - Proper cancellation propagation
 * - Reconnect loop with state validation
 * - Resource cleanup on all paths
 * - Graceful heartbeat shutdown
 */
class AIPClient(
    private val context: Context,
    private val scope: CoroutineScope,
) {
    private val client = HttpClient(OkHttp) {
        install(WebSockets)
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        install(Logging) {
            logger = Logger.DEFAULT
            level = LogLevel.INFO
        }
        install(HttpTimeout) {
            requestTimeoutMillis = 15000
            connectTimeoutMillis = 10000
        }
    }

    private var _session: DefaultClientWebSocketSession? = null
    private var heartbeatJob: Job? = null
    private var reconnectJob: Job? = null
    private var messageId = 0
    private val connectMutex = Mutex()
    private var isDisposed = false

    private val _connectionState = MutableStateFlow(AIPConnectionState.DISCONNECTED)
    val connectionState: StateFlow<AIPConnectionState> = _connectionState.asStateFlow()

    private val _messages = MutableSharedFlow<AIPMessage>(extraBufferCapacity = 64)
    val messages: SharedFlow<AIPMessage> = _messages.asSharedFlow()

    private var serverUrl: String = ""
    private var token: String = ""

    // -----------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------

    suspend fun connect(url: String, authToken: String) {
        connectMutex.withLock {
            if (isDisposed) {
                Log.w(GalaxyWearApplication.TAG, "AIPClient already disposed")
                return
            }

            // Guard against concurrent connect
            if (_connectionState.value == AIPConnectionState.CONNECTED ||
                _connectionState.value == AIPConnectionState.AUTHENTICATED ||
                _connectionState.value == AIPConnectionState.CONNECTING
            ) {
                Log.d(GalaxyWearApplication.TAG, "Connection already in progress or established")
                return
            }

            serverUrl = url
            token = authToken
            _connectionState.value = AIPConnectionState.CONNECTING
        }

        try {
            val wsUrl = if (url.startsWith("http")) {
                url.replace("http://", "ws://").replace("https://", "wss://")
            } else url

            client.webSession({ url(wsUrl) }) {
                connectMutex.withLock {
                    if (isDisposed || !_connectionState.value.isTerminal) {
                        _session = this
                        _connectionState.value = AIPConnectionState.CONNECTED
                    }
                }
                if (isDisposed) return@webSession

                Log.i(GalaxyWearApplication.TAG, "WebSocket connected: $wsUrl")

                // Send AUTH
                try {
                    sendSerialized(AIPMessage.Auth(token = token))
                } catch (e: Exception) {
                    Log.e(GalaxyWearApplication.TAG, "Auth send failed: ${e.message}")
                    return@webSession
                }

                // Listen for messages
                try {
                    for (frame in incoming) {
                        if (isDisposed) break
                        when (frame) {
                            is Frame.Text -> handleMessage(frame.readText())
                            is Frame.Close -> {
                                val reason = frame.readReason()
                                Log.w(GalaxyWearApplication.TAG, "WebSocket closed: ${reason?.message}")
                                break
                            }
                            is Frame.Ping -> outgoing.send(Frame.Pong(frame.data))
                            else -> {} // Ignore binary, pong
                        }
                    }
                } catch (e: CancellationException) {
                    Log.d(GalaxyWearApplication.TAG, "WebSocket receive cancelled")
                    throw e
                } catch (e: Exception) {
                    Log.e(GalaxyWearApplication.TAG, "WebSocket receive error: ${e.message}")
                }
            }
        } catch (e: CancellationException) {
            Log.d(GalaxyWearApplication.TAG, "Connection cancelled")
            throw e
        } catch (e: Exception) {
            Log.e(GalaxyWearApplication.TAG, "WebSocket error: ${e.message}")
            val current = _connectionState.value
            if (current != AIPConnectionState.DISCONNECTED) {
                _connectionState.value = AIPConnectionState.ERROR
            }
            scheduleReconnect()
        } finally {
            heartbeatJob?.cancel()
            connectMutex.withLock {
                _session = null
                val current = _connectionState.value
                if (current == AIPConnectionState.CONNECTED ||
                    current == AIPConnectionState.AUTHENTICATED ||
                    current == AIPConnectionState.CONNECTING
                ) {
                    _connectionState.value = AIPConnectionState.DISCONNECTED
                }
            }
        }
    }

    suspend fun disconnect() {
        connectMutex.withLock {
            isDisposed = true
            reconnectJob?.cancel()
            heartbeatJob?.cancel()
            _session?.close()
            _session = null
            _connectionState.value = AIPConnectionState.DISCONNECTED
        }
    }

    fun dispose() {
        // Non-blocking dispose for Activity.onDestroy
        reconnectJob?.cancel()
        heartbeatJob?.cancel()
        scope.launch {
            disconnect()
        }
    }

    // -----------------------------------------------------------------
    // Messaging
    // -----------------------------------------------------------------

    suspend fun sendCommand(command: String, payload: JsonObject? = null) {
        val msg = AIPMessage.Command(
            id = ++messageId,
            command = command,
            payload = payload
        )
        sendJson(msg)
    }

    suspend fun sendVoiceQuery(transcript: String) {
        sendCommand("voice_query", buildJsonObject {
            put("text", transcript)
            put("source", "wear_os")
        })
    }

    suspend fun sendPhaseReport(phase: String) {
        sendCommand("phase_report", buildJsonObject {
            put("phase", phase)
            put("device", "wear_os")
        })
    }

    // -----------------------------------------------------------------
    // Internal
    // -----------------------------------------------------------------

    private fun handleMessage(raw: String) {
        try {
            val json = Json.parseToJsonElement(raw).jsonObject
            val type = json["type"]?.jsonPrimitive?.content ?: "unknown"

            when (type) {
                "auth_ok" -> {
                    _connectionState.value = AIPConnectionState.AUTHENTICATED
                    startHeartbeat()
                }
                "auth_failed" -> {
                    Log.e(GalaxyWearApplication.TAG, "Authentication failed")
                    _connectionState.value = AIPConnectionState.ERROR
                }
                "auth_invalid" -> {
                    Log.e(GalaxyWearApplication.TAG, "Auth token invalid")
                    _connectionState.value = AIPConnectionState.ERROR
                }
                "command_result" -> {
                    _messages.tryEmit(AIPMessage.Result(
                        id = json["id"]?.jsonPrimitive?.int ?: 0,
                        success = json["success"]?.jsonPrimitive?.boolean ?: false,
                        data = json["data"]
                    ))
                }
                "event" -> {
                    _messages.tryEmit(AIPMessage.Event(
                        event = json["event"]?.jsonPrimitive?.content ?: "",
                        data = json["data"] ?: JsonObject(emptyMap())
                    ))
                }
                "pong" -> { /* Heartbeat response, ignore */ }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w(GalaxyWearApplication.TAG, "Failed to parse message: ${e.message}")
        }
    }

    private fun startHeartbeat() {
        // Cancel existing first
        heartbeatJob?.cancel()
        heartbeatJob = scope.launch {
            while (isActive && !isDisposed) {
                delay(30000) // 30s heartbeat
                if (!isActive || isDisposed) break
                try {
                    val session = _session
                    if (session == null || session.outgoing.isClosedForSend) {
                        Log.w(GalaxyWearApplication.TAG, "Heartbeat: session closed, stopping")
                        break
                    }
                    val pingMsg = Json.encodeToString(AIPMessage.serializer(), AIPMessage.Ping(id = ++messageId))
                    session.outgoing.send(Frame.Text(pingMsg))
                } catch (e: CancellationException) {
                    break
                } catch (e: Exception) {
                    Log.w(GalaxyWearApplication.TAG, "Heartbeat failed: ${e.message}")
                    break
                }
            }
        }
    }

    private fun scheduleReconnect() {
        // Don't schedule if disposed or already reconnecting
        if (isDisposed) return
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            delay(5000)
            if (isDisposed) return@launch
            val current = _connectionState.value
            if (current != AIPConnectionState.AUTHENTICATED && current != AIPConnectionState.CONNECTING) {
                Log.i(GalaxyWearApplication.TAG, "Attempting reconnect...")
                try {
                    connect(serverUrl, token)
                } catch (e: CancellationException) {
                    // Normal shutdown
                } catch (e: Exception) {
                    Log.e(GalaxyWearApplication.TAG, "Reconnect failed: ${e.message}")
                }
            }
        }
    }

    private suspend fun sendJson(msg: AIPMessage) {
        val session = _session
            ?: throw IllegalStateException("WebSocket not connected")
        if (session.outgoing.isClosedForSend) {
            throw IllegalStateException("WebSocket outgoing channel closed")
        }
        val json = Json.encodeToString(AIPMessage.serializer(), msg)
        session.outgoing.send(Frame.Text(json))
    }
}

// -----------------------------------------------------------------
// Data types
// -----------------------------------------------------------------

enum class AIPConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    AUTHENTICATED,
    ERROR;

    val isTerminal: Boolean
        get() = this == DISCONNECTED || this == ERROR
}

@kotlinx.serialization.Serializable
sealed class AIPMessage {
    abstract val type: String

    @kotlinx.serialization.Serializable
    data class Auth(val token: String) : AIPMessage() {
        override val type = "auth"
    }

    @kotlinx.serialization.Serializable
    data class Command(
        val id: Int,
        val command: String,
        val payload: JsonObject? = null
    ) : AIPMessage() {
        override val type = "command"
    }

    @kotlinx.serialization.Serializable
    data class Ping(val id: Int) : AIPMessage() {
        override val type = "ping"
    }

    @kotlinx.serialization.Serializable
    data class Result(
        val id: Int,
        val success: Boolean,
        val data: JsonElement? = null
    ) : AIPMessage() {
        override val type = "result"
    }

    @kotlinx.serialization.Serializable
    data class Event(
        val event: String,
        val data: JsonObject
    ) : AIPMessage() {
        override val type = "event"
    }
}
