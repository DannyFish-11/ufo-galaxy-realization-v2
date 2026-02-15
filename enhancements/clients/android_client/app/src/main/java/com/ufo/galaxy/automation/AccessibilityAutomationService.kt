package com.ufo.galaxy.automation

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

/**
 * Android Accessibility 自动化服务
 * 
 * 功能：
 * 1. 自动化操作 Android 应用（点击、输入、滑动等）
 * 2. 读取屏幕内容
 * 3. 监听应用事件
 * 4. 执行来自 Galaxy 的 UI 自动化命令
 */
class AccessibilityAutomationService : AccessibilityService() {
    
    private val TAG = "AccessibilityAutomation"
    
    companion object {
        private var instance: AccessibilityAutomationService? = null
        
        fun getInstance(): AccessibilityAutomationService? = instance
        
        /**
         * 执行 UI 自动化命令
         */
        fun executeCommand(command: JSONObject): JSONObject {
            val result = JSONObject()
            val service = getInstance()
            
            if (service == null) {
                result.put("status", "error")
                result.put("message", "Accessibility 服务未启用")
                return result
            }
            
            val action = command.getString("action")
            val parameters = command.optJSONObject("parameters") ?: JSONObject()
            
            return when (action) {
                "open_app" -> service.openApp(parameters.getString("package_name"))
                "click" -> service.clickByText(parameters.getString("text"))
                "input" -> service.inputText(parameters.getString("text"))
                "scroll" -> service.scroll(parameters.getString("direction"))
                "back" -> service.pressBack()
                "home" -> service.pressHome()
                "recent" -> service.pressRecent()
                "get_screen_content" -> service.getScreenContent()
                else -> {
                    result.put("status", "error")
                    result.put("message", "不支持的动作: $action")
                    result
                }
            }
        }
    }
    
    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "Accessibility 服务已连接")
    }
    
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // 监听应用事件（可选）
        event?.let {
            Log.d(TAG, "事件: ${it.eventType}, 包名: ${it.packageName}")
        }
    }
    
    override fun onInterrupt() {
        Log.w(TAG, "Accessibility 服务被中断")
    }
    
    override fun onDestroy() {
        super.onDestroy()
        instance = null
        Log.i(TAG, "Accessibility 服务已销毁")
    }
    
    /**
     * 打开应用
     */
    private fun openApp(packageName: String): JSONObject {
        val result = JSONObject()
        try {
            val intent = packageManager.getLaunchIntentForPackage(packageName)
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                startActivity(intent)
                result.put("status", "success")
                result.put("message", "应用 $packageName 已启动")
            } else {
                result.put("status", "error")
                result.put("message", "未找到应用: $packageName")
            }
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "启动应用失败: ${e.message}")
        }
        return result
    }
    
    /**
     * 根据文本点击元素
     */
    private fun clickByText(text: String): JSONObject {
        val result = JSONObject()
        try {
            val rootNode = rootInActiveWindow
            if (rootNode == null) {
                result.put("status", "error")
                result.put("message", "无法获取屏幕内容")
                return result
            }
            
            val targetNode = findNodeByText(rootNode, text)
            if (targetNode != null) {
                targetNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                result.put("status", "success")
                result.put("message", "已点击: $text")
            } else {
                result.put("status", "error")
                result.put("message", "未找到元素: $text")
            }
            
            rootNode.recycle()
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "点击失败: ${e.message}")
        }
        return result
    }
    
    /**
     * 输入文本
     */
    private fun inputText(text: String): JSONObject {
        val result = JSONObject()
        try {
            val rootNode = rootInActiveWindow
            if (rootNode == null) {
                result.put("status", "error")
                result.put("message", "无法获取屏幕内容")
                return result
            }
            
            // 查找可编辑的输入框
            val editableNode = findEditableNode(rootNode)
            if (editableNode != null) {
                // 先点击输入框获取焦点
                editableNode.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                
                // 输入文本
                val arguments = android.os.Bundle()
                arguments.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    text
                )
                editableNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
                
                result.put("status", "success")
                result.put("message", "已输入: $text")
            } else {
                result.put("status", "error")
                result.put("message", "未找到可编辑的输入框")
            }
            
            rootNode.recycle()
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "输入失败: ${e.message}")
        }
        return result
    }
    
    /**
     * 滑动屏幕
     */
    private fun scroll(direction: String): JSONObject {
        val result = JSONObject()
        try {
            val rootNode = rootInActiveWindow
            if (rootNode == null) {
                result.put("status", "error")
                result.put("message", "无法获取屏幕内容")
                return result
            }
            
            val action = when (direction.lowercase()) {
                "up" -> AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
                "down" -> AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
                else -> AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
            }
            
            rootNode.performAction(action)
            result.put("status", "success")
            result.put("message", "已滑动: $direction")
            
            rootNode.recycle()
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "滑动失败: ${e.message}")
        }
        return result
    }
    
    /**
     * 按返回键
     */
    private fun pressBack(): JSONObject {
        val result = JSONObject()
        try {
            performGlobalAction(GLOBAL_ACTION_BACK)
            result.put("status", "success")
            result.put("message", "已按返回键")
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "按返回键失败: ${e.message}")
        }
        return result
    }
    
    /**
     * 按 Home 键
     */
    private fun pressHome(): JSONObject {
        val result = JSONObject()
        try {
            performGlobalAction(GLOBAL_ACTION_HOME)
            result.put("status", "success")
            result.put("message", "已按 Home 键")
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "按 Home 键失败: ${e.message}")
        }
        return result
    }
    
    /**
     * 按最近任务键
     */
    private fun pressRecent(): JSONObject {
        val result = JSONObject()
        try {
            performGlobalAction(GLOBAL_ACTION_RECENTS)
            result.put("status", "success")
            result.put("message", "已按最近任务键")
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "按最近任务键失败: ${e.message}")
        }
        return result
    }
    
    /**
     * 获取屏幕内容
     */
    private fun getScreenContent(): JSONObject {
        val result = JSONObject()
        try {
            val rootNode = rootInActiveWindow
            if (rootNode == null) {
                result.put("status", "error")
                result.put("message", "无法获取屏幕内容")
                return result
            }
            
            val content = extractNodeText(rootNode)
            result.put("status", "success")
            result.put("content", content)
            
            rootNode.recycle()
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "获取屏幕内容失败: ${e.message}")
        }
        return result
    }
    
    /**
     * 根据文本查找节点
     */
    private fun findNodeByText(node: AccessibilityNodeInfo, text: String): AccessibilityNodeInfo? {
        // 检查当前节点
        if (node.text?.toString()?.contains(text, ignoreCase = true) == true ||
            node.contentDescription?.toString()?.contains(text, ignoreCase = true) == true) {
            return node
        }
        
        // 递归检查子节点
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val found = findNodeByText(child, text)
            if (found != null) {
                return found
            }
            child.recycle()
        }
        
        return null
    }
    
    /**
     * 查找可编辑的节点
     */
    private fun findEditableNode(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        // 检查当前节点是否可编辑
        if (node.isEditable) {
            return node
        }
        
        // 递归检查子节点
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val found = findEditableNode(child)
            if (found != null) {
                return found
            }
            child.recycle()
        }
        
        return null
    }
    
    /**
     * 提取节点文本
     */
    private fun extractNodeText(node: AccessibilityNodeInfo): String {
        val builder = StringBuilder()
        
        // 添加当前节点的文本
        node.text?.let { builder.append(it).append(" ") }
        node.contentDescription?.let { builder.append(it).append(" ") }
        
        // 递归提取子节点文本
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            builder.append(extractNodeText(child))
            child.recycle()
        }
        
        return builder.toString()
    }
}
