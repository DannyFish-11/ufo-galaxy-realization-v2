package com.ufo.galaxy.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ufo.galaxy.service.FloatingWindowService
import com.ufo.galaxy.service.GalaxyConnectionService
import com.ufo.galaxy.ui.components.ChatScreen
import com.ufo.galaxy.ui.components.ScrollPaperContainer
import com.ufo.galaxy.ui.theme.UFOGalaxyTheme
import com.ufo.galaxy.ui.viewmodel.MainViewModel

/**
 * UFO Galaxy Android - 主 Activity
 * 实现书法卷轴式 UI 和系统级 AI 交互
 */
class MainActivity : ComponentActivity() {
    
    companion object {
        private const val TAG = "MainActivity"
    }
    
    private val viewModel: MainViewModel by lazy { MainViewModel() }
    
    // 权限请求
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.all { it.value }
        if (allGranted) {
            Log.d(TAG, "所有权限已授予")
            startServices()
        } else {
            Log.w(TAG, "部分权限被拒绝")
            Toast.makeText(this, "部分功能可能受限", Toast.LENGTH_SHORT).show()
        }
    }
    
    // 悬浮窗权限请求
    private val overlayPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        if (Settings.canDrawOverlays(this)) {
            Log.d(TAG, "悬浮窗权限已授予")
            startFloatingService()
        } else {
            Log.w(TAG, "悬浮窗权限被拒绝")
            Toast.makeText(this, "灵动岛功能需要悬浮窗权限", Toast.LENGTH_SHORT).show()
        }
    }
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        Log.i(TAG, "MainActivity 创建")
        
        // 请求权限
        requestPermissions()
        
        // 设置 Compose UI
        setContent {
            UFOGalaxyTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MainScreen(viewModel = viewModel)
                }
            }
        }
    }
    
    override fun onResume() {
        super.onResume()
        viewModel.onResume()
    }
    
    override fun onPause() {
        super.onPause()
        viewModel.onPause()
    }
    
    /**
     * 请求必要权限
     */
    private fun requestPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.INTERNET,
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.CAMERA
        )
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            permissions.add(Manifest.permission.BLUETOOTH_CONNECT)
            permissions.add(Manifest.permission.BLUETOOTH_SCAN)
        }
        
        permissionLauncher.launch(permissions.toTypedArray())
    }
    
    /**
     * 请求悬浮窗权限
     */
    private fun requestOverlayPermission() {
        if (!Settings.canDrawOverlays(this)) {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")
            )
            overlayPermissionLauncher.launch(intent)
        } else {
            startFloatingService()
        }
    }
    
    /**
     * 启动服务
     */
    private fun startServices() {
        // 启动 Galaxy 连接服务
        val connectionIntent = Intent(this, GalaxyConnectionService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(connectionIntent)
        } else {
            startService(connectionIntent)
        }
        
        // 请求悬浮窗权限并启动悬浮窗服务
        requestOverlayPermission()
    }
    
    /**
     * 启动悬浮窗服务
     */
    private fun startFloatingService() {
        val floatingIntent = Intent(this, FloatingWindowService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(floatingIntent)
        } else {
            startService(floatingIntent)
        }
    }
}

/**
 * 主屏幕 Composable
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(viewModel: MainViewModel = viewModel()) {
    val uiState by viewModel.uiState.collectAsState()
    
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("UFO Galaxy") },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer
                )
            )
        }
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            // 书法卷轴容器
            ScrollPaperContainer(
                isExpanded = uiState.isScrollExpanded,
                onExpandChange = { viewModel.toggleScroll() },
                modifier = Modifier.fillMaxSize()
            ) {
                // 聊天界面
                ChatScreen(
                    messages = uiState.messages,
                    inputText = uiState.inputText,
                    isLoading = uiState.isLoading,
                    onInputChange = { viewModel.updateInput(it) },
                    onSend = { viewModel.sendMessage() },
                    onVoiceInput = { viewModel.startVoiceInput() },
                    modifier = Modifier.fillMaxSize()
                )
            }
        }
    }
}
