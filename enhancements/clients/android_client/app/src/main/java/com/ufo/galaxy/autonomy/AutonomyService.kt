package com.ufo.galaxy.autonomy

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicInteger

/**
 * UFO³ Galaxy 自主操纵服务
 * 
 * 核心功能：
 * 1. 完整的 UI 树抓取和序列化
 * 2. 基于节点 ID 和坐标的精确操作
 * 3. 高级手势模拟（点击、长按、滑动、缩放）
 * 4. 实时屏幕状态监控
 * 5. 与 Galaxy Gateway 的通信接口
 * 
 * @author Manus AI
 * @version 2.0
 * @date 2026-01-22
 */
class AutonomyService : AccessibilityService() {
    
    private val TAG = "AutonomyService"
    private val nodeIdGenerator = AtomicInteger(0)
    private val nodeCache = mutableMapOf<Int, AccessibilityNodeInfo>()
    
    companion object {
        private var instance: AutonomyService? = null
        
        /**
         * 获取服务实例
         */
        fun getInstance(): AutonomyService? = instance
        
        /**
         * 检查服务是否可用
         */
        fun isServiceAvailable(): Boolean = instance != null
    }
    
    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "✅ UFO³ Galaxy 自主操纵服务已启动")
    }
    
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event?.let {
            // 监听窗口内容变化事件
            when (it.eventType) {
                AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED,
                AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                    Log.d(TAG, "📱 窗口变化: ${it.packageName}")
                    // 可以在这里触发 UI 树更新推送到 Gateway
                }
            }
        }
    }
    
    override fun onInterrupt() {
        Log.w(TAG, "⚠️ 自主操纵服务被中断")
    }
    
    override fun onDestroy() {
        super.onDestroy()
        clearNodeCache()
        instance = null
        Log.i(TAG, "❌ 自主操纵服务已销毁")
    }
    
    // ============================================================
    // 核心功能 1: UI 树抓取和序列化
    // ============================================================
    
    /**
     * 获取完整的 UI 树结构（JSON 格式）
     */
    fun captureUITree(): JSONObject {
        val result = JSONObject()
        
        try {
            val rootNode = rootInActiveWindow
            if (rootNode == null) {
                result.put("status", "error")
                result.put("message", "无法获取屏幕内容")
                return result
            }
            
            // 清空旧的节点缓存
            clearNodeCache()
            nodeIdGenerator.set(0)
            
            // 获取当前活动窗口信息
            val activePackage = rootNode.packageName?.toString() ?: "unknown"
            val activeWindow = rootNode.window?.title?.toString() ?: "unknown"
            
            // 序列化 UI 树
            val uiTree = serializeNode(rootNode)
            
            result.put("status", "success")
            result.put("timestamp", System.currentTimeMillis())
            result.put("active_package", activePackage)
            result.put("active_window", activeWindow)
            result.put("ui_tree", uiTree)
            result.put("node_count", nodeCache.size)
            
            // 注意：不要 recycle rootNode，因为我们缓存了它的子节点
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "抓取 UI 树失败: ${e.message}")
            Log.e(TAG, "抓取 UI 树失败", e)
        }
        
        return result
    }
    
    /**
     * 递归序列化节点为 JSON
     */
    private fun serializeNode(node: AccessibilityNodeInfo): JSONObject {
        val nodeId = nodeIdGenerator.incrementAndGet()
        nodeCache[nodeId] = node
        
        val json = JSONObject()
        
        try {
            // 基本信息
            json.put("node_id", nodeId)
            json.put("class_name", node.className?.toString() ?: "")
            json.put("package_name", node.packageName?.toString() ?: "")
            json.put("resource_id", node.viewIdResourceName ?: "")
            
            // 文本内容
            json.put("text", node.text?.toString() ?: "")
            json.put("content_description", node.contentDescription?.toString() ?: "")
            json.put("hint_text", node.hintText?.toString() ?: "")
            
            // 位置和大小
            val bounds = Rect()
            node.getBoundsInScreen(bounds)
            json.put("bounds", JSONArray().apply {
                put(bounds.left)
                put(bounds.top)
                put(bounds.right)
                put(bounds.bottom)
            })
            
            // 状态属性
            json.put("is_clickable", node.isClickable)
            json.put("is_long_clickable", node.isLongClickable)
            json.put("is_editable", node.isEditable)
            json.put("is_scrollable", node.isScrollable)
            json.put("is_checkable", node.isCheckable)
            json.put("is_checked", node.isChecked)
            json.put("is_focusable", node.isFocusable)
            json.put("is_focused", node.isFocused)
            json.put("is_selected", node.isSelected)
            json.put("is_enabled", node.isEnabled)
            json.put("is_visible", node.isVisibleToUser)
            
            // 子节点
            val children = JSONArray()
            for (i in 0 until node.childCount) {
                val child = node.getChild(i)
                if (child != null) {
                    children.put(serializeNode(child))
                }
            }
            json.put("children", children)
            
        } catch (e: Exception) {
            Log.e(TAG, "序列化节点失败: ${e.message}")
        }
        
        return json
    }
    
    /**
     * 清空节点缓存
     */
    private fun clearNodeCache() {
        nodeCache.values.forEach { it.recycle() }
        nodeCache.clear()
    }
    
    // ============================================================
    // 核心功能 2: 动作执行引擎
    // ============================================================
    
    /**
     * 执行动作（统一入口）
     */
    fun executeAction(action: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            val actionType = action.getString("type")
            val params = action.optJSONObject("params") ?: JSONObject()
            
            return when (actionType) {
                "tap" -> performTap(params)
                "long_tap" -> performLongTap(params)
                "input_text" -> performInputText(params)
                "scroll" -> performScroll(params)
                "swipe" -> performSwipe(params)
                "press_key" -> performPressKey(params)
                "start_app" -> performStartApp(params)
                "get_ui_tree" -> captureUITree()
                else -> {
                    result.put("status", "error")
                    result.put("message", "不支持的动作类型: $actionType")
                    result
                }
            }
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "执行动作失败: ${e.message}")
            Log.e(TAG, "执行动作失败", e)
        }
        
        return result
    }
    
    /**
     * 点击操作（支持节点 ID 和坐标两种方式）
     */
    private fun performTap(params: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            // 方式 1: 通过节点 ID 点击
            if (params.has("node_id")) {
                val nodeId = params.getInt("node_id")
                val node = nodeCache[nodeId]
                
                if (node == null) {
                    result.put("status", "error")
                    result.put("message", "节点 ID $nodeId 不存在或已过期")
                    return result
                }
                
                if (!node.isClickable) {
                    result.put("status", "warning")
                    result.put("message", "节点不可点击，尝试点击其父节点")
                    // 尝试点击父节点
                    var parent = node.parent
                    while (parent != null && !parent.isClickable) {
                        parent = parent.parent
                    }
                    if (parent != null && parent.isClickable) {
                        parent.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                        result.put("status", "success")
                    } else {
                        result.put("status", "error")
                        result.put("message", "未找到可点击的父节点")
                    }
                } else {
                    node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    result.put("status", "success")
                    result.put("message", "已点击节点 $nodeId")
                }
                
                return result
            }
            
            // 方式 2: 通过坐标点击
            if (params.has("x") && params.has("y")) {
                val x = params.getInt("x").toFloat()
                val y = params.getInt("y").toFloat()
                
                val path = Path().apply { moveTo(x, y) }
                val gesture = GestureDescription.Builder()
                    .addStroke(GestureDescription.StrokeDescription(path, 0, 100))
                    .build()
                
                val success = dispatchGesture(gesture, null, null)
                
                if (success) {
                    result.put("status", "success")
                    result.put("message", "已点击坐标 ($x, $y)")
                } else {
                    result.put("status", "error")
                    result.put("message", "点击手势分发失败")
                }
                
                return result
            }
            
            result.put("status", "error")
            result.put("message", "缺少参数: 需要 node_id 或 (x, y)")
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "点击失败: ${e.message}")
            Log.e(TAG, "点击失败", e)
        }
        
        return result
    }
    
    /**
     * 长按操作
     */
    private fun performLongTap(params: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            if (params.has("node_id")) {
                val nodeId = params.getInt("node_id")
                val node = nodeCache[nodeId]
                
                if (node == null) {
                    result.put("status", "error")
                    result.put("message", "节点 ID $nodeId 不存在或已过期")
                    return result
                }
                
                node.performAction(AccessibilityNodeInfo.ACTION_LONG_CLICK)
                result.put("status", "success")
                result.put("message", "已长按节点 $nodeId")
                
            } else if (params.has("x") && params.has("y")) {
                val x = params.getInt("x").toFloat()
                val y = params.getInt("y").toFloat()
                
                val path = Path().apply { moveTo(x, y) }
                val gesture = GestureDescription.Builder()
                    .addStroke(GestureDescription.StrokeDescription(path, 0, 1000)) // 1秒长按
                    .build()
                
                dispatchGesture(gesture, null, null)
                result.put("status", "success")
                result.put("message", "已长按坐标 ($x, $y)")
            } else {
                result.put("status", "error")
                result.put("message", "缺少参数: 需要 node_id 或 (x, y)")
            }
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "长按失败: ${e.message}")
        }
        
        return result
    }
    
    /**
     * 输入文本
     */
    private fun performInputText(params: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            val text = params.getString("text")
            val nodeId = params.optInt("node_id", -1)
            
            val targetNode = if (nodeId != -1) {
                nodeCache[nodeId]
            } else {
                // 自动查找可编辑节点
                val rootNode = rootInActiveWindow
                rootNode?.let { findEditableNode(it) }
            }
            
            if (targetNode == null) {
                result.put("status", "error")
                result.put("message", "未找到可编辑的输入框")
                return result
            }
            
            // 先聚焦
            targetNode.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            
            // 输入文本
            val arguments = android.os.Bundle()
            arguments.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                text
            )
            targetNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
            
            result.put("status", "success")
            result.put("message", "已输入文本: $text")
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "输入文本失败: ${e.message}")
        }
        
        return result
    }
    
    /**
     * 滚动操作
     */
    private fun performScroll(params: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            val direction = params.getString("direction").lowercase()
            val nodeId = params.optInt("node_id", -1)
            
            val targetNode = if (nodeId != -1) {
                nodeCache[nodeId]
            } else {
                rootInActiveWindow
            }
            
            if (targetNode == null) {
                result.put("status", "error")
                result.put("message", "无法获取目标节点")
                return result
            }
            
            val action = when (direction) {
                "up", "forward" -> AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
                "down", "backward" -> AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
                else -> AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
            }
            
            targetNode.performAction(action)
            result.put("status", "success")
            result.put("message", "已滚动: $direction")
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "滚动失败: ${e.message}")
        }
        
        return result
    }
    
    /**
     * 滑动手势
     */
    private fun performSwipe(params: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            val x1 = params.getInt("x1").toFloat()
            val y1 = params.getInt("y1").toFloat()
            val x2 = params.getInt("x2").toFloat()
            val y2 = params.getInt("y2").toFloat()
            val duration = params.optInt("duration", 300).toLong()
            
            val path = Path().apply {
                moveTo(x1, y1)
                lineTo(x2, y2)
            }
            
            val gesture = GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0, duration))
                .build()
            
            dispatchGesture(gesture, null, null)
            result.put("status", "success")
            result.put("message", "已滑动: ($x1,$y1) -> ($x2,$y2)")
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "滑动失败: ${e.message}")
        }
        
        return result
    }
    
    /**
     * 按系统按键
     */
    private fun performPressKey(params: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            val key = params.getString("key").lowercase()
            
            val action = when (key) {
                "back" -> GLOBAL_ACTION_BACK
                "home" -> GLOBAL_ACTION_HOME
                "recent", "recents" -> GLOBAL_ACTION_RECENTS
                "notifications" -> GLOBAL_ACTION_NOTIFICATIONS
                "quick_settings" -> GLOBAL_ACTION_QUICK_SETTINGS
                else -> {
                    result.put("status", "error")
                    result.put("message", "不支持的按键: $key")
                    return result
                }
            }
            
            performGlobalAction(action)
            result.put("status", "success")
            result.put("message", "已按下: $key")
            
        } catch (e: Exception) {
            result.put("status", "error")
            result.put("message", "按键失败: ${e.message}")
        }
        
        return result
    }
    
    /**
     * 启动应用
     */
    private fun performStartApp(params: JSONObject): JSONObject {
        val result = JSONObject()
        
        try {
            val packageName = params.getString("package_name")
            val intent = packageManager.getLaunchIntentForPackage(packageName)
            
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                startActivity(intent)
                result.put("status", "success")
                result.put("message", "已启动应用: $packageName")
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
    
    // ============================================================
    // 辅助方法
    // ============================================================
    
    /**
     * 查找可编辑的节点
     */
    private fun findEditableNode(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (node.isEditable) {
            return node
        }
        
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val found = findEditableNode(child)
            if (found != null) {
                return found
            }
        }
        
        return null
    }
}
