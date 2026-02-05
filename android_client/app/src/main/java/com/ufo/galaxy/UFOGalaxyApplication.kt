package com.ufo.galaxy

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.util.Log
import com.ufo.galaxy.data.AppConfig
import com.ufo.galaxy.network.GalaxyWebSocketClient

/**
 * UFO Galaxy Android Application
 * 应用程序入口，负责全局初始化
 */
class UFOGalaxyApplication : Application() {
    
    companion object {
        private const val TAG = "UFOGalaxyApp"
        
        // 通知渠道 ID
        const val CHANNEL_SERVICE = "ufo_galaxy_service"
        const val CHANNEL_MESSAGES = "ufo_galaxy_messages"
        const val CHANNEL_ALERTS = "ufo_galaxy_alerts"
        
        // 全局实例
        lateinit var instance: UFOGalaxyApplication
            private set
        
        // 全局 WebSocket 客户端
        lateinit var webSocketClient: GalaxyWebSocketClient
            private set
        
        // 全局配置
        lateinit var appConfig: AppConfig
            private set
    }
    
    override fun onCreate() {
        super.onCreate()
        instance = this
        
        Log.i(TAG, "UFO Galaxy Application 启动")
        
        // 初始化配置
        initConfig()
        
        // 创建通知渠道
        createNotificationChannels()
        
        // 初始化 WebSocket 客户端
        initWebSocketClient()
        
        Log.i(TAG, "UFO Galaxy Application 初始化完成")
    }
    
    /**
     * 初始化配置
     */
    private fun initConfig() {
        appConfig = AppConfig(
            serverUrl = BuildConfig.GALAXY_SERVER_URL,
            apiVersion = BuildConfig.API_VERSION,
            isDebug = BuildConfig.DEBUG
        )
        Log.d(TAG, "配置已加载: serverUrl=${appConfig.serverUrl}")
    }
    
    /**
     * 创建通知渠道
     */
    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            
            // 服务通知渠道
            val serviceChannel = NotificationChannel(
                CHANNEL_SERVICE,
                "Galaxy 服务",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "UFO Galaxy 后台服务通知"
                setShowBadge(false)
            }
            
            // 消息通知渠道
            val messageChannel = NotificationChannel(
                CHANNEL_MESSAGES,
                "消息通知",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = "来自 Galaxy 的消息通知"
                enableVibration(true)
            }
            
            // 警报通知渠道
            val alertChannel = NotificationChannel(
                CHANNEL_ALERTS,
                "重要警报",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "重要的系统警报"
                enableVibration(true)
                enableLights(true)
            }
            
            notificationManager.createNotificationChannels(
                listOf(serviceChannel, messageChannel, alertChannel)
            )
            
            Log.d(TAG, "通知渠道已创建")
        }
    }
    
    /**
     * 初始化 WebSocket 客户端
     */
    private fun initWebSocketClient() {
        webSocketClient = GalaxyWebSocketClient(appConfig.serverUrl)
        Log.d(TAG, "WebSocket 客户端已初始化")
    }
    
    /**
     * 获取 WebSocket 客户端
     */
    fun getWebSocket(): GalaxyWebSocketClient = webSocketClient
    
    /**
     * 获取配置
     */
    fun getConfig(): AppConfig = appConfig
}
