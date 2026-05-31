package com.galaxy.wear.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.galaxy.wear.GalaxyWearApplication
import com.galaxy.wear.MainActivity
import com.galaxy.wear.Phase
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * GalaxyWearService — Foreground service for persistent AIP connection
 *
 * Runs continuously in the background to:
 * - Maintain AIP v3 WebSocket
 * - Push phase state to Galaxy
 * - Receive push notifications from Galaxy
 * - Handle voice command wake-ups
 */
class GalaxyWearService : LifecycleService() {

    companion object {
        const val CHANNEL_ID = "galaxy_wear"
        const val NOTIFICATION_ID = 1
        const val ACTION_DISCONNECT = "com.galaxy.wear.DISCONNECT"
        const val TAG = "GalaxyWearService"
    }

    private val binder = LocalBinder()
    @Volatile
    private var isRunning = false

    inner class LocalBinder : Binder() {
        fun getService(): GalaxyWearService = this@GalaxyWearService
    }

    override fun onBind(intent: Intent): IBinder {
        super.onBind(intent)
        return binder
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)

        if (intent?.action == ACTION_DISCONNECT) {
            Log.i(TAG, "Disconnect requested via notification")
            val app = application as GalaxyWearApplication
            app.disconnect()
            stopGracefully()
            return START_NOT_STICKY
        }

        if (!isRunning) {
            isRunning = true
            startForeground()
            observePhaseChanges()
        }

        return START_STICKY
    }

    private fun stopGracefully() {
        isRunning = false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
        stopSelf()
    }

    // ------------------------------------------------------------------

    private fun startForeground() {
        val disconnectIntent = Intent(this, GalaxyWearService::class.java).apply {
            action = ACTION_DISCONNECT
        }
        val disconnectPending = PendingIntent.getService(
            this, 0, disconnectIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val openIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val openPending = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Galaxy")
            .setContentText("手表智能体运行中")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(openPending)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "断开", disconnectPending)
            .setOngoing(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(
                    NOTIFICATION_ID, notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                )
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start foreground: ${e.message}")
        }
    }

    private fun observePhaseChanges() {
        val app = application as GalaxyWearApplication

        lifecycleScope.launch {
            try {
                app.phase.collectLatest { phase ->
                    if (!isRunning) return@collectLatest

                    val phaseText = when (phase) {
                        Phase.SILENT -> "静默"
                        Phase.LIMINAL -> "临界"
                        Phase.MANIFEST -> "显现"
                    }
                    updateNotification("Galaxy — $phaseText")

                    // Push phase report to Galaxy (best-effort)
                    try {
                        app.aipClient.sendPhaseReport(phase.name.lowercase())
                    } catch (e: CancellationException) {
                        // Normal during shutdown
                    } catch (e: Exception) {
                        Log.w(TAG, "Phase report failed: ${e.message}")
                    }
                }
            } catch (e: CancellationException) {
                Log.d(TAG, "Phase observer cancelled")
            } catch (e: Exception) {
                Log.e(TAG, "Phase observer crashed: ${e.message}")
            }
        }
    }

    private fun updateNotification(text: String) {
        if (!