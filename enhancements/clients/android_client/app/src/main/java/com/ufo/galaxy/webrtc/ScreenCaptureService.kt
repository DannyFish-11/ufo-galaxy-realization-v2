package com.ufo.galaxy.webrtc

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.util.Log
import android.view.Surface
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*
import org.json.JSONObject
import java.nio.ByteBuffer

/**
 * WebRTC 屏幕采集服务
 * 
 * 功能：
 * 1. 使用 MediaProjection API 采集屏幕内容
 * 2. 使用 MediaCodec 进行 H.264 编码
 * 3. 通过 WebSocket 发送编码后的视频流
 * 4. 支持动态调整分辨率和帧率
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class ScreenCaptureService : Service() {
    
    private val TAG = "ScreenCaptureService"
    private val NOTIFICATION_ID = 1001
    private val CHANNEL_ID = "screen_capture_channel"
    
    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var mediaCodec: MediaCodec? = null
    private var encoderSurface: Surface? = null
    
    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())
    private var encodingJob: Job? = null
    
    // 配置参数
    private var screenWidth = 1280
    private var screenHeight = 720
    private var screenDpi = 320
    private var frameRate = 30
    private var bitRate = 2000000 // 2 Mbps
    
    companion {
        const val ACTION_START = "com.ufo.galaxy.webrtc.START_CAPTURE"
        const val ACTION_STOP = "com.ufo.galaxy.webrtc.STOP_CAPTURE"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_DATA = "data"
        const val EXTRA_WIDTH = "width"
        const val EXTRA_HEIGHT = "height"
        const val EXTRA_FPS = "fps"
        
        @Volatile
        private var instance: ScreenCaptureService? = null
        
        fun getInstance(): ScreenCaptureService? = instance
        
        fun isRunning(): Boolean = instance != null
    }
    
    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannel()
        Log.i(TAG, "ScreenCaptureService created")
    }
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, -1)
                val data = intent.getParcelableExtra<Intent>(EXTRA_DATA)
                screenWidth = intent.getIntExtra(EXTRA_WIDTH, 1280)
                screenHeight = intent.getIntExtra(EXTRA_HEIGHT, 720)
                frameRate = intent.getIntExtra(EXTRA_FPS, 30)
                
                if (resultCode != -1 && data != null) {
                    startForeground(NOTIFICATION_ID, createNotification())
                    startScreenCapture(resultCode, data)
                }
            }
            ACTION_STOP -> {
                stopScreenCapture()
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }
    
    override fun onBind(intent: Intent?): IBinder? = null
    
    override fun onDestroy() {
        super.onDestroy()
        stopScreenCapture()
        instance = null
        scope.cancel()
        Log.i(TAG, "ScreenCaptureService destroyed")
    }
    
    /**
     * 创建通知渠道 (Android 8.0+)
     */
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "屏幕采集服务",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "WebRTC 屏幕采集正在运行"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }
    
    /**
     * 创建前台服务通知
     */
    private fun createNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("UFO³ Galaxy")
            .setContentText("屏幕采集中...")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }
    
    /**
     * 开始屏幕采集
     */
    private fun startScreenCapture(resultCode: Int, data: Intent) {
        try {
            // 1. 初始化 MediaProjection
            val projectionManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            mediaProjection = projectionManager.getMediaProjection(resultCode, data)
            
            if (mediaProjection == null) {
                Log.e(TAG, "Failed to create MediaProjection")
                return
            }
            
            // 2. 初始化 MediaCodec (H.264 编码器)
            val format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, screenWidth, screenHeight).apply {
                setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
                setInteger(MediaFormat.KEY_BIT_RATE, bitRate)
                setInteger(MediaFormat.KEY_FRAME_RATE, frameRate)
                setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2) // 每 2 秒一个 I 帧
            }
            
            mediaCodec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC).apply {
                configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                encoderSurface = createInputSurface()
                start()
            }
            
            // 3. 创建 VirtualDisplay
            virtualDisplay = mediaProjection?.createVirtualDisplay(
                "ScreenCapture",
                screenWidth,
                screenHeight,
                screenDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                encoderSurface,
                null,
                null
            )
            
            // 4. 开始编码循环
            startEncoding()
            
            Log.i(TAG, "Screen capture started: ${screenWidth}x${screenHeight}@${frameRate}fps")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start screen capture", e)
            stopScreenCapture()
        }
    }
    
    /**
     * 停止屏幕采集
     */
    private fun stopScreenCapture() {
        encodingJob?.cancel()
        encodingJob = null
        
        virtualDisplay?.release()
        virtualDisplay = null
        
        encoderSurface?.release()
        encoderSurface = null
        
        try {
            mediaCodec?.stop()
            mediaCodec?.release()
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping MediaCodec", e)
        }
        mediaCodec = null
        
        mediaProjection?.stop()
        mediaProjection = null
        
        Log.i(TAG, "Screen capture stopped")
    }
    
    /**
     * 开始编码循环
     */
    private fun startEncoding() {
        encodingJob = scope.launch {
            val bufferInfo = MediaCodec.BufferInfo()
            val timeoutUs = 10000L // 10ms
            
            while (isActive) {
                try {
                    val codec = mediaCodec ?: break
                    
                    // 获取编码后的数据
                    val outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, timeoutUs)
                    
                    when {
                        outputBufferIndex >= 0 -> {
                            val outputBuffer = codec.getOutputBuffer(outputBufferIndex)
                            if (outputBuffer != null && bufferInfo.size > 0) {
                                // 将编码后的数据发送到 WebRTC 或 WebSocket
                                sendEncodedData(outputBuffer, bufferInfo)
                            }
                            codec.releaseOutputBuffer(outputBufferIndex, false)
                        }
                        outputBufferIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                            val newFormat = codec.outputFormat
                            Log.i(TAG, "Output format changed: $newFormat")
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Encoding error", e)
                    break
                }
            }
        }
    }
    
    /**
     * 发送编码后的数据
     * TODO: 集成 WebRTC 或 WebSocket 发送逻辑
     */
    private fun sendEncodedData(buffer: ByteBuffer, bufferInfo: MediaCodec.BufferInfo) {
        // 这里需要将编码后的 H.264 数据通过 WebRTC 或 WebSocket 发送到 PC 端
        // 当前版本仅记录日志
        Log.d(TAG, "Encoded frame: size=${bufferInfo.size}, pts=${bufferInfo.presentationTimeUs}, flags=${bufferInfo.flags}")
        
        // TODO: 实现 WebSocket 发送
        // val data = ByteArray(bufferInfo.size)
        // buffer.get(data)
        // webSocketClient.send(data)
    }
}
