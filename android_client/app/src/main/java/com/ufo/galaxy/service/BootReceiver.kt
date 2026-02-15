package com.ufo.galaxy.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log

/**
 * 开机启动接收器
 * 在设备启动时自动启动 Galaxy 服务
 */
class BootReceiver : BroadcastReceiver() {
    
    companion object {
        private const val TAG = "BootReceiver"
    }
    
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == "android.intent.action.QUICKBOOT_POWERON") {
            
            Log.i(TAG, "设备启动完成，启动 Galaxy 服务")
            
            // 启动连接服务
            val serviceIntent = Intent(context, GalaxyConnectionService::class.java)
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent)
            } else {
                context.startService(serviceIntent)
            }
        }
    }
}

/**
 * 硬件按键接收器
 * 监听媒体按键用于唤醒
 */
class HardwareKeyReceiver : BroadcastReceiver() {
    
    companion object {
        private const val TAG = "HardwareKeyReceiver"
    }
    
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_MEDIA_BUTTON) {
            Log.d(TAG, "收到媒体按键事件")
            // TODO: 处理硬件按键唤醒
        }
    }
}
