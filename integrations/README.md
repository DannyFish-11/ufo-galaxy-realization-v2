# Home Assistant Integration

## Quick Start

1. Create a long-lived access token in Home Assistant:
   **Profile → Long-Lived Access Tokens → Create Token**

2. Set environment variables:
   ```bash
   export HOME_ASSISTANT_URL=http://your-ha:8123
   export HOME_ASSISTANT_TOKEN=your_token_here
   ```

3. Galaxy auto-discovers on MANIFEST startup, or call manually:
   ```python
   from integrations.home_assistant import init_integration
   gateway = await init_integration()
   ```

## Architecture

```
DesktopPresenceRuntime
    └── Node_27_Smarthome
            └── init_integration()
                    ├── HAConnector      ← WebSocket + REST
                    ├── EntityDiscovery  ← Auto-discovery
                    └── SmartHomeGateway ← Unified API
```

## Supported Entity Types

| Domain | Galaxy Class | Control | Query |
|--------|-------------|---------|-------|
| light | light | turn_on/off, brightness | state, brightness |
| switch | switch | turn_on/off | state |
| climate | climate | set_temperature | temp, mode, humidity |
| media_player | media_player | play/pause/volume | state, track |
| sensor | sensor | — | value |
| cover | cover | open/close | position |
| fan | fan | turn_on/off, speed | state |
| lock | lock | lock/unlock | state |
| vacuum | vacuum | start/stop/dock | state, battery |
| scene | scene | turn_on | — |

## Natural Language Commands

Voice commands are automatically routed when Galaxy detects smart home intent:

- "开灯" / "关灯" → light.turn_on / light.turn_off
- "把温度调到 26 度" → climate.set_temperature
- "播放音乐" → media_player.media_play
- "打开窗帘" → cover.open_cover

## API Reference

```python
# List all entities
gateway.list_entities()
gateway.list_entities(area="living_room", domain="light")

# Find by name
gateway.find_by_name("客厅灯")

# Control
gateway.turn_on("light.living_room")
gateway.set_brightness("light.living_room", brightness_pct=80)
gateway.set_temperature("climate.bedroom", temperature=26.0)

# Direct service call
gateway.call_service("light", "turn_on", target={"entity_id": "light.living_room"})

# NL handler
result = await gateway.handle_command("开灯", "客厅")
# → "已开灯「客厅灯」"
```
