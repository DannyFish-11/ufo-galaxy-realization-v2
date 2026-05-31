package com.galaxy.wear

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.speech.RecognizerIntent
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.*
import com.galaxy.wear.ui.theme.GalaxyWearTheme
import kotlinx.coroutines.launch

/**
 * Dedicated voice command activity.
 *
 * Triggered via:
 *   "Hey Galaxy, <command>" (if voice model registered)
 *   or hardware button long-press.
 */
class VoiceActivity : ComponentActivity() {

    companion object {
        const val REQUEST_SPEECH = 1001
    }

    private var transcript by mutableStateOf("")
    private var isListening by mutableStateOf(false)
    private var isProcessing by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            GalaxyWearTheme {
                VoiceCommandScreen()
            }
        }

        // Auto-start listening
        startListening()
    }

    @Composable
    private fun VoiceCommandScreen() {
        val scope = rememberCoroutineScope()
        val app = application as GalaxyWearApplication

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black),
            contentAlignment = Alignment.Center
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
                modifier = Modifier.padding(16.dp)
            ) {
                // Animated mic indicator
                if (isListening) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(48.dp),
                        indicatorColor = MaterialTheme.colors.primary,
                        trackColor = Color.DarkGray,
                        strokeWidth = 4.dp
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "聆听中...",
                        style = MaterialTheme.typography.body2,
                        color = Color.LightGray,
                        textAlign = TextAlign.Center
                    )
                } else if (isProcessing) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(36.dp),
                        indicatorColor = Color(0xFF808080),
                        strokeWidth = 3.dp
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "处理中...",
                        style = MaterialTheme.typography.body2,
                        color = Color.Gray
                    )
                } else if (transcript.isNotEmpty()) {
                    Text(
                        text = "\"$transcript\"",
                        style = MaterialTheme.typography.body1,
                        color = Color.White,
                        textAlign = TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "已发送",
                        style = MaterialTheme.typography.caption3,
                        color = Color(0xFF808080)
                    )
                }

                // Phase indicator dots (mini)
                Spacer(modifier = Modifier.height(16.dp))
                PhaseDots(phase = app.phase.collectAsState().value)
            }
        }
    }

    @Composable
    private fun PhaseDots(phase: Phase) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Phase.values().forEach { p ->
                val color = when (p) {
                    Phase.SILENT -> if (phase == p) Color(0xFF333333) else Color(0xFF111111)
                    Phase.LIMINAL -> if (phase == p) Color(0xFF808080) else Color(0xFF222222)
                    Phase.MANIFEST -> if (phase == p) Color(0xFFE0E0E0) else Color(0xFF222222)
                }
                Box(
                    modifier = Modifier
                        .size(6.dp)
                        .background(color, androidx.compose.foundation.shape.CircleShape)
                )
            }
        }
    }

    private fun startListening() {
        isListening = true
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
        }
        try {
            startActivityForResult(intent, REQUEST_SPEECH)
        } catch (e: Exception) {
            Log.e(GalaxyWearApplication.TAG, "Speech recognition not available")
            isListening = false
            transcript = "语音识别不可用"
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_SPEECH && resultCode == Activity.RESULT_OK) {
            val results = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            transcript = results?.firstOrNull() ?: ""
            isListening = false

            if (transcript.isNotEmpty()) {
                isProcessing = true
                val app = application as GalaxyWearApplication
                // Send to Galaxy via AIP
                kotlinx.coroutines.MainScope().launch {
                    try {
                        app.aipClient.sendVoiceQuery(transcript)
                        isProcessing = false
                    } catch (e: Exception) {
                        Log.e(GalaxyWearApplication.TAG, "Send failed: ${e.message}")
                        isProcessing = false
                        transcript = "发送失败"
                    }
                }
            }
        } else {
            isListening = false
            transcript = "未识别"
        }
    }
}
