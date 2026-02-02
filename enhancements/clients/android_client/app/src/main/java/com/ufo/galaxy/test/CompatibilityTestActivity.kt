package com.ufo.galaxy.test

import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.ufo.galaxy.R
import com.ufo.galaxy.client.Node50Client
import com.ufo.galaxy.network.TailscaleAdapter
import com.ufo.galaxy.protocol.AIPProtocol
import kotlinx.coroutines.*
import org.json.JSONObject

/**
 * UFO³ Galaxy 兼容性测试工具
 * 
 * 用于测试 Android Agent 与 UFO³ Galaxy 系统的兼容性
 * 
 * 测试内容：
 * 1. Tailscale 网络检测
 * 2. Node 50 自动发现
 * 3. AIP/1.0 协议通信
 * 4. 命令发送和响应
 * 5. 心跳保活
 * 
 * @author Manus AI
 * @version 1.0
 * @date 2026-01-22
 */
class CompatibilityTestActivity : AppCompatActivity() {
    
    private val TAG = "CompatibilityTest"
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    
    private lateinit var tailscaleAdapter: TailscaleAdapter
    private var node50Client: Node50Client? = null
    
    private lateinit var tvLog: TextView
    private lateinit var scrollView: ScrollView
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_compatibility_test)
        
        tailscaleAdapter = TailscaleAdapter(this)
        
        setupUI()
    }
    
    private fun setupUI() {
        tvLog = findViewById(R.id.tv_log)
        scrollView = findViewById(R.id.scroll_view)
        
        findViewById<Button>(R.id.btn_test_tailscale).setOnClickListener {
            testTailscaleNetwork()
        }
        
        findViewById<Button>(R.id.btn_auto_discover).setOnClickListener {
            autoDiscoverNode50()
        }
        
        findViewById<Button>(R.id.btn_test_connection).setOnClickListener {
            testNode50Connection()
        }
        
        findViewById<Button>(R.id.btn_test_protocol).setOnClickListener {
            testAIPProtocol()
        }
        
        findViewById<Button>(R.id.btn_send_command).setOnClickListener {
            sendTestCommand()
        }
        
        findViewById<Button>(R.id.btn_full_test).setOnClickListener {
            runFullCompatibilityTest()
        }
        
        findViewById<Button>(R.id.btn_clear_log).setOnClickListener {
            clearLog()
        }
        
        appendLog("✅ UFO³ Galaxy 兼容性测试工具已启动\n")
        appendLog("📋 请按顺序执行测试，或点击"完整测试"一键运行所有测试\n\n")
    }
    
    /**
     * 测试 1: Tailscale 网络检测
     */
    private fun testTailscaleNetwork() {
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        appendLog("🔍 测试 1: Tailscale 网络检测\n")
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        
        scope.launch {
            try {
                val isInTailscale = tailscaleAdapter.isInTailscaleNetwork()
                
                if (isInTailscale) {
                    appendLog("✅ 检测到 Tailscale 网络\n")
                } else {
                    appendLog("❌ 未检测到 Tailscale 网络\n")
                    appendLog("⚠️  请确保已安装并登录 Tailscale\n")
                }
                
                val diagnostics = tailscaleAdapter.getDiagnostics()
                appendLog("\n📊 网络诊断信息:\n")
                appendLog(diagnostics.toString(2) + "\n")
                
            } catch (e: Exception) {
                appendLog("❌ 测试失败: ${e.message}\n")
                Log.e(TAG, "Tailscale test failed", e)
            }
            
            appendLog("\n")
        }
    }
    
    /**
     * 测试 2: Node 50 自动发现
     */
    private fun autoDiscoverNode50() {
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        appendLog("🔍 测试 2: Node 50 自动发现\n")
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        
        scope.launch {
            try {
                appendLog("🔍 正在扫描 Tailscale 网络...\n")
                
                val node50Url = tailscaleAdapter.autoDiscoverNode50()
                
                if (node50Url != null) {
                    appendLog("✅ 成功发现 Node 50: $node50Url\n")
                    appendLog("💾 地址已自动保存\n")
                } else {
                    appendLog("❌ 未能自动发现 Node 50\n")
                    appendLog("⚠️  请手动配置 Node 50 地址\n")
                }
                
            } catch (e: Exception) {
                appendLog("❌ 测试失败: ${e.message}\n")
                Log.e(TAG, "Auto discover failed", e)
            }
            
            appendLog("\n")
        }
    }
    
    /**
     * 测试 3: Node 50 连接测试
     */
    private fun testNode50Connection() {
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        appendLog("🔍 测试 3: Node 50 连接测试\n")
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        
        scope.launch {
            try {
                val node50Url = tailscaleAdapter.getNode50Url()
                
                if (node50Url == null) {
                    appendLog("❌ 未配置 Node 50 地址\n")
                    appendLog("⚠️  请先运行"自动发现"或手动配置\n")
                    return@launch
                }
                
                appendLog("📡 正在连接: $node50Url\n")
                
                val isConnected = tailscaleAdapter.testConnection()
                
                if (isConnected) {
                    appendLog("✅ Node 50 连接成功\n")
                    
                    val node50Info = tailscaleAdapter.getNode50Info()
                    if (node50Info != null) {
                        appendLog("\n📊 Node 50 信息:\n")
                        appendLog(node50Info.toString(2) + "\n")
                    }
                } else {
                    appendLog("❌ Node 50 连接失败\n")
                    appendLog("⚠️  请检查 Node 50 是否正在运行\n")
                }
                
            } catch (e: Exception) {
                appendLog("❌ 测试失败: ${e.message}\n")
                Log.e(TAG, "Connection test failed", e)
            }
            
            appendLog("\n")
        }
    }
    
    /**
     * 测试 4: AIP/1.0 协议测试
     */
    private fun testAIPProtocol() {
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        appendLog("🔍 测试 4: AIP/1.0 协议测试\n")
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        
        try {
            // 测试消息创建
            appendLog("📝 创建测试消息...\n")
            
            val commandMessage = AIPProtocol.createCommandMessage(
                "测试命令",
                JSONObject().apply {
                    put("test", true)
                }
            )
            
            appendLog("✅ 命令消息创建成功\n")
            appendLog("\n📄 消息内容:\n")
            appendLog(commandMessage.toString(2) + "\n")
            
            // 测试消息验证
            appendLog("\n🔍 验证消息格式...\n")
            val isValid = AIPProtocol.validateMessage(commandMessage)
            
            if (isValid) {
                appendLog("✅ 消息格式验证通过\n")
            } else {
                appendLog("❌ 消息格式验证失败\n")
            }
            
            // 测试消息解析
            appendLog("\n🔍 测试消息解析...\n")
            val messageString = commandMessage.toString()
            val parsedMessage = AIPProtocol.parseMessage(messageString)
            
            if (parsedMessage != null) {
                appendLog("✅ 消息解析成功\n")
                
                val messageType = AIPProtocol.getMessageType(parsedMessage)
                val payload = AIPProtocol.getPayload(parsedMessage)
                val messageId = AIPProtocol.getMessageId(parsedMessage)
                
                appendLog("\n📊 解析结果:\n")
                appendLog("  消息类型: $messageType\n")
                appendLog("  消息 ID: $messageId\n")
                appendLog("  Payload: ${payload?.toString(2)}\n")
            } else {
                appendLog("❌ 消息解析失败\n")
            }
            
        } catch (e: Exception) {
            appendLog("❌ 测试失败: ${e.message}\n")
            Log.e(TAG, "Protocol test failed", e)
        }
        
        appendLog("\n")
    }
    
    /**
     * 测试 5: 发送测试命令
     */
    private fun sendTestCommand() {
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        appendLog("🔍 测试 5: 发送测试命令\n")
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        
        scope.launch {
            try {
                val node50Url = tailscaleAdapter.getNode50Url()
                
                if (node50Url == null) {
                    appendLog("❌ 未配置 Node 50 地址\n")
                    return@launch
                }
                
                appendLog("📡 正在连接到 Node 50...\n")
                
                // 创建 Node50Client
                if (node50Client == null) {
                    node50Client = Node50Client(
                        context = this@CompatibilityTestActivity,
                        node50Url = node50Url,
                        messageHandler = { message ->
                            appendLog("📨 收到响应:\n")
                            appendLog(message.toString(2) + "\n")
                        }
                    )
                }
                
                node50Client?.connect()
                
                // 等待连接建立
                delay(2000)
                
                if (node50Client?.isConnected() == true) {
                    appendLog("✅ WebSocket 连接已建立\n")
                    
                    appendLog("\n📤 发送测试命令...\n")
                    val success = node50Client?.sendCommand("这是一个来自 Android Agent 的测试命令")
                    
                    if (success == true) {
                        appendLog("✅ 命令已发送\n")
                        appendLog("⏳ 等待 Node 50 响应...\n")
                    } else {
                        appendLog("❌ 命令发送失败\n")
                    }
                } else {
                    appendLog("❌ WebSocket 连接失败\n")
                }
                
            } catch (e: Exception) {
                appendLog("❌ 测试失败: ${e.message}\n")
                Log.e(TAG, "Send command test failed", e)
            }
            
            appendLog("\n")
        }
    }
    
    /**
     * 完整兼容性测试
     */
    private fun runFullCompatibilityTest() {
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        appendLog("🚀 开始完整兼容性测试\n")
        appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n")
        
        scope.launch {
            try {
                // 测试 1
                testTailscaleNetwork()
                delay(1000)
                
                // 测试 2
                autoDiscoverNode50()
                delay(2000)
                
                // 测试 3
                testNode50Connection()
                delay(1000)
                
                // 测试 4
                testAIPProtocol()
                delay(1000)
                
                // 测试 5
                sendTestCommand()
                delay(3000)
                
                appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
                appendLog("✅ 完整兼容性测试完成\n")
                appendLog("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
                
            } catch (e: Exception) {
                appendLog("❌ 测试过程中发生异常: ${e.message}\n")
                Log.e(TAG, "Full test failed", e)
            }
        }
    }
    
    /**
     * 清除日志
     */
    private fun clearLog() {
        tvLog.text = ""
    }
    
    /**
     * 追加日志
     */
    private fun appendLog(message: String) {
        runOnUiThread {
            tvLog.append(message)
            scrollView.post {
                scrollView.fullScroll(ScrollView.FOCUS_DOWN)
            }
        }
    }
    
    override fun onDestroy() {
        super.onDestroy()
        node50Client?.disconnect()
        node50Client?.cleanup()
        scope.cancel()
    }
}
