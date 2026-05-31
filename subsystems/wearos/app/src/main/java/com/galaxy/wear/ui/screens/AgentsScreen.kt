package com.galaxy.wear.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.*

/**
 * AgentsScreen — Available Galaxy agents list
 *
 * Shows connected agents with status. Tapping an agent
 * sends a focus command via AIP.
 */
@Composable
fun AgentsScreen(onBack: () -> Unit) {
    val agents = remember {
        listOf(
            AgentItem("主控", " coordinating", true),
            AgentItem("语音", " voice", true),
            AgentItem("家居", " smarthome", false),
            AgentItem("记忆", " memory", true),
            AgentItem("视觉", " vision", false),
        )
    }

    Scaffold(
        vignette = { Vignette(vignettePosition = VignettePosition.TopAndBottom) },
        positionIndicator = { PositionIndicator(scalingLazyListState = rememberScalingLazyListState()) }
    ) {
        ScalingLazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            item {
                Text(
                    text = "智能体",
                    style = MaterialTheme.typography.title1,
                    color = MaterialTheme.colors.onBackground,
                    modifier = Modifier.padding(top = 8.dp, bottom = 8.dp)
                )
            }

            items(agents.size) { index ->
                val agent = agents[index]
                AgentChip(agent = agent, onClick = {
                    // Send focus command via AIP
                })
            }

            item {
                Button(
                    onClick = onBack,
                    modifier = Modifier.padding(top = 12.dp)
                ) {
                    Text("返回", style = MaterialTheme.typography.button)
                }
            }
        }
    }
}

@Composable
private fun AgentChip(agent: AgentItem, onClick: () -> Unit) {
    Chip(
        onClick = onClick,
        label = {
            Text(
                agent.name,
                style = MaterialTheme.typography.body2,
                maxLines = 1
            )
        },
        secondaryLabel = {
            Text(
                if (agent.online) "在线" else "离线",
                style = MaterialTheme.typography.caption3,
                color = if (agent.online) Color(0xFF808080) else Color(0xFF444444)
            )
        },
        icon = {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(
                        if (agent.online) Color(0xFF808080) else Color(0xFF333333),
                        androidx.compose.foundation.shape.CircleShape
                    )
            )
        },
        colors = if (agent.online)
            ChipDefaults.primaryChipColors()
        else
            ChipDefaults.secondaryChipColors(),
        modifier = Modifier
            .fillMaxWidth(0.9f)
            .padding(vertical = 2.dp)
    )
}

private data class AgentItem(
    val name: String,
    val type: String,
    val online: Boolean,
)
