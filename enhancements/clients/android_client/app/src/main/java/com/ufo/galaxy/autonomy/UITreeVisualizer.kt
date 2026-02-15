package com.ufo.galaxy.autonomy

import android.graphics.Rect
import org.json.JSONArray
import org.json.JSONObject

/**
 * UI 树可视化和调试工具
 * 
 * 功能：
 * 1. 将 JSON 格式的 UI 树转换为易读的文本格式
 * 2. 生成 UI 树的 Markdown 文档
 * 3. 提供节点查找和过滤功能
 * 4. 生成 UI 树统计信息
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
object UITreeVisualizer {
    
    /**
     * 将 UI 树转换为易读的文本格式
     */
    fun toReadableText(uiTree: JSONObject): String {
        val builder = StringBuilder()
        builder.append("=".repeat(60)).append("\n")
        builder.append("UI 树结构\n")
        builder.append("=".repeat(60)).append("\n\n")
        
        if (uiTree.has("active_package")) {
            builder.append("📱 应用包名: ${uiTree.getString("active_package")}\n")
        }
        if (uiTree.has("active_window")) {
            builder.append("🪟 窗口标题: ${uiTree.getString("active_window")}\n")
        }
        if (uiTree.has("node_count")) {
            builder.append("🔢 节点总数: ${uiTree.getInt("node_count")}\n")
        }
        builder.append("\n")
        
        if (uiTree.has("ui_tree")) {
            val rootNode = uiTree.getJSONObject("ui_tree")
            builder.append(nodeToText(rootNode, 0))
        }
        
        return builder.toString()
    }
    
    /**
     * 递归将节点转换为文本（带缩进）
     */
    private fun nodeToText(node: JSONObject, level: Int): String {
        val builder = StringBuilder()
        val indent = "  ".repeat(level)
        
        // 节点基本信息
        val nodeId = node.optInt("node_id", -1)
        val className = node.optString("class_name", "").split(".").lastOrNull() ?: ""
        val text = node.optString("text", "")
        val contentDesc = node.optString("content_description", "")
        val resourceId = node.optString("resource_id", "").split("/").lastOrNull() ?: ""
        
        // 构建节点描述
        builder.append("$indent[$nodeId] $className")
        
        if (resourceId.isNotEmpty()) {
            builder.append(" #$resourceId")
        }
        
        if (text.isNotEmpty()) {
            builder.append(" \"$text\"")
        } else if (contentDesc.isNotEmpty()) {
            builder.append(" [$contentDesc]")
        }
        
        // 状态标记
        val states = mutableListOf<String>()
        if (node.optBoolean("is_clickable", false)) states.add("可点击")
        if (node.optBoolean("is_editable", false)) states.add("可编辑")
        if (node.optBoolean("is_scrollable", false)) states.add("可滚动")
        if (node.optBoolean("is_checked", false)) states.add("已选中")
        
        if (states.isNotEmpty()) {
            builder.append(" (${states.joinToString(", ")})")
        }
        
        // 位置信息
        if (node.has("bounds")) {
            val bounds = node.getJSONArray("bounds")
            builder.append(" [${bounds.getInt(0)},${bounds.getInt(1)}-${bounds.getInt(2)},${bounds.getInt(3)}]")
        }
        
        builder.append("\n")
        
        // 递归处理子节点
        if (node.has("children")) {
            val children = node.getJSONArray("children")
            for (i in 0 until children.length()) {
                builder.append(nodeToText(children.getJSONObject(i), level + 1))
            }
        }
        
        return builder.toString()
    }
    
    /**
     * 生成 UI 树的 Markdown 文档
     */
    fun toMarkdown(uiTree: JSONObject): String {
        val builder = StringBuilder()
        
        builder.append("# UI 树分析报告\n\n")
        
        // 基本信息
        builder.append("## 基本信息\n\n")
        builder.append("| 属性 | 值 |\n")
        builder.append("|------|----|\n")
        
        if (uiTree.has("active_package")) {
            builder.append("| 应用包名 | `${uiTree.getString("active_package")}` |\n")
        }
        if (uiTree.has("active_window")) {
            builder.append("| 窗口标题 | ${uiTree.getString("active_window")} |\n")
        }
        if (uiTree.has("node_count")) {
            builder.append("| 节点总数 | ${uiTree.getInt("node_count")} |\n")
        }
        if (uiTree.has("timestamp")) {
            val timestamp = uiTree.getLong("timestamp")
            builder.append("| 抓取时间 | ${java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss").format(timestamp)} |\n")
        }
        
        builder.append("\n")
        
        // 统计信息
        if (uiTree.has("ui_tree")) {
            val stats = generateStatistics(uiTree.getJSONObject("ui_tree"))
            builder.append("## 统计信息\n\n")
            builder.append("| 类型 | 数量 |\n")
            builder.append("|------|------|\n")
            builder.append("| 可点击元素 | ${stats["clickable"]} |\n")
            builder.append("| 可编辑元素 | ${stats["editable"]} |\n")
            builder.append("| 可滚动元素 | ${stats["scrollable"]} |\n")
            builder.append("| 文本元素 | ${stats["text"]} |\n")
            builder.append("| 图片元素 | ${stats["image"]} |\n")
            builder.append("| 按钮元素 | ${stats["button"]} |\n")
            builder.append("\n")
        }
        
        // UI 树结构
        builder.append("## UI 树结构\n\n")
        builder.append("```\n")
        if (uiTree.has("ui_tree")) {
            builder.append(nodeToText(uiTree.getJSONObject("ui_tree"), 0))
        }
        builder.append("```\n")
        
        return builder.toString()
    }
    
    /**
     * 生成 UI 树统计信息
     */
    private fun generateStatistics(node: JSONObject): Map<String, Int> {
        val stats = mutableMapOf(
            "clickable" to 0,
            "editable" to 0,
            "scrollable" to 0,
            "text" to 0,
            "image" to 0,
            "button" to 0
        )
        
        collectStatistics(node, stats)
        
        return stats
    }
    
    /**
     * 递归收集统计信息
     */
    private fun collectStatistics(node: JSONObject, stats: MutableMap<String, Int>) {
        // 统计当前节点
        if (node.optBoolean("is_clickable", false)) {
            stats["clickable"] = stats["clickable"]!! + 1
        }
        if (node.optBoolean("is_editable", false)) {
            stats["editable"] = stats["editable"]!! + 1
        }
        if (node.optBoolean("is_scrollable", false)) {
            stats["scrollable"] = stats["scrollable"]!! + 1
        }
        
        val text = node.optString("text", "")
        if (text.isNotEmpty()) {
            stats["text"] = stats["text"]!! + 1
        }
        
        val className = node.optString("class_name", "").lowercase()
        if (className.contains("image") || className.contains("icon")) {
            stats["image"] = stats["image"]!! + 1
        }
        if (className.contains("button")) {
            stats["button"] = stats["button"]!! + 1
        }
        
        // 递归处理子节点
        if (node.has("children")) {
            val children = node.getJSONArray("children")
            for (i in 0 until children.length()) {
                collectStatistics(children.getJSONObject(i), stats)
            }
        }
    }
    
    /**
     * 查找包含指定文本的节点
     */
    fun findNodesByText(uiTree: JSONObject, searchText: String): List<JSONObject> {
        val results = mutableListOf<JSONObject>()
        
        if (uiTree.has("ui_tree")) {
            searchNodesByText(uiTree.getJSONObject("ui_tree"), searchText, results)
        }
        
        return results
    }
    
    /**
     * 递归搜索节点
     */
    private fun searchNodesByText(node: JSONObject, searchText: String, results: MutableList<JSONObject>) {
        val text = node.optString("text", "")
        val contentDesc = node.optString("content_description", "")
        
        if (text.contains(searchText, ignoreCase = true) || 
            contentDesc.contains(searchText, ignoreCase = true)) {
            results.add(node)
        }
        
        // 递归搜索子节点
        if (node.has("children")) {
            val children = node.getJSONArray("children")
            for (i in 0 until children.length()) {
                searchNodesByText(children.getJSONObject(i), searchText, results)
            }
        }
    }
    
    /**
     * 查找指定类型的所有节点
     */
    fun findNodesByType(uiTree: JSONObject, nodeType: String): List<JSONObject> {
        val results = mutableListOf<JSONObject>()
        
        if (uiTree.has("ui_tree")) {
            searchNodesByType(uiTree.getJSONObject("ui_tree"), nodeType, results)
        }
        
        return results
    }
    
    /**
     * 递归搜索指定类型的节点
     */
    private fun searchNodesByType(node: JSONObject, nodeType: String, results: MutableList<JSONObject>) {
        when (nodeType.lowercase()) {
            "clickable" -> if (node.optBoolean("is_clickable", false)) results.add(node)
            "editable" -> if (node.optBoolean("is_editable", false)) results.add(node)
            "scrollable" -> if (node.optBoolean("is_scrollable", false)) results.add(node)
            "button" -> {
                val className = node.optString("class_name", "").lowercase()
                if (className.contains("button")) results.add(node)
            }
            "text" -> {
                val text = node.optString("text", "")
                if (text.isNotEmpty()) results.add(node)
            }
        }
        
        // 递归搜索子节点
        if (node.has("children")) {
            val children = node.getJSONArray("children")
            for (i in 0 until children.length()) {
                searchNodesByType(children.getJSONObject(i), nodeType, results)
            }
        }
    }
    
    /**
     * 根据节点 ID 查找节点
     */
    fun findNodeById(uiTree: JSONObject, nodeId: Int): JSONObject? {
        if (uiTree.has("ui_tree")) {
            return searchNodeById(uiTree.getJSONObject("ui_tree"), nodeId)
        }
        return null
    }
    
    /**
     * 递归搜索指定 ID 的节点
     */
    private fun searchNodeById(node: JSONObject, nodeId: Int): JSONObject? {
        if (node.optInt("node_id", -1) == nodeId) {
            return node
        }
        
        // 递归搜索子节点
        if (node.has("children")) {
            val children = node.getJSONArray("children")
            for (i in 0 until children.length()) {
                val found = searchNodeById(children.getJSONObject(i), nodeId)
                if (found != null) return found
            }
        }
        
        return null
    }
}
