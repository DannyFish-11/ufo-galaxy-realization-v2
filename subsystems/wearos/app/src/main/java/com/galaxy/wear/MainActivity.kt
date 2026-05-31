package com.galaxy.wear

import android.os.Bundle
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
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.navigation.NavHostController
import androidx.wear.compose.material.*
import androidx.wear.compose.navigation.SwipeDismissableNavHost
import androidx.wear.compose.navigation.composable
import androidx.wear.compose.navigation.rememberSwipeDismissableNavController
import com.galaxy.wear.ui.screens.AgentsScreen
import com.galaxy.wear.ui.screens.HomeScreen
import com.galaxy.wear.ui.screens.SettingsScreen
import com.galaxy.wear.ui.screens.VoiceScreen
import com.galaxy.wear.ui.theme.GalaxyWearTheme

/**
 * Main Wear OS Activity — Galaxy Watch Entry Point
 *
 * Navigation:
 *   home → agents → voice → settings
 * All screens follow Wear OS circular design guidelines.
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)

        setTheme(android.R.style.Theme_DeviceDefault)

        setContent {
            GalaxyWearTheme {
                val navController = rememberSwipeDismissableNavController()
                val app = application as GalaxyWearApplication
                val phase by app.phase.collectAsState()

                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(Color.Black)
                ) {
                    SwipeDismissableNavHost(
                        navController = navController,
                        startDestination = "home",
                        modifier = Modifier.fillMaxSize()
                    ) {
                        composable("home") {
                            HomeScreen(
                                phase = phase,
                                onAgents = { navController.navigate("agents") },
                                onVoice = { navController.navigate("voice") },
                                onSettings = { navController.navigate("settings") },
                            )
                        }
                        composable("agents") {
                            AgentsScreen(
                                onBack = { navController.popBackStack() }
                            )
                        }
                        composable("voice") {
                            VoiceScreen(
                                onBack = { navController.popBackStack() }
                            )
                        }
                        composable("settings") {
                            SettingsScreen(
                                onBack = { navController.popBackStack() }
                            )
                        }
                    }
                }
            }
        }
    }
}
