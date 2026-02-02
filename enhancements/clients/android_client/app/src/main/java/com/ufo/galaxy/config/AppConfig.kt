package com.ufo.galaxy.config

import android.content.Context
import java.util.Properties

/**
 * 应用配置读取工具类
 * 
 * 从 assets/config.properties 文件中读取配置
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
object AppConfig {
    
    private val properties = Properties()
    
    fun loadConfig(context: Context) {
        try {
            context.assets.open("config.properties").use { inputStream ->
                properties.load(inputStream)
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
    
    fun getString(key: String, defaultValue: String = ""): String {
        return properties.getProperty(key, defaultValue)
    }
    
    fun getInt(key: String, defaultValue: Int = 0): Int {
        return properties.getProperty(key)?.toIntOrNull() ?: defaultValue
    }
    
    fun getLong(key: String, defaultValue: Long = 0L): Long {
        return properties.getProperty(key)?.toLongOrNull() ?: defaultValue
    }
    
    fun getBoolean(key: String, defaultValue: Boolean = false): Boolean {
        return properties.getProperty(key)?.toBoolean() ?: defaultValue
    }
}
