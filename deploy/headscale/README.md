# Headscale — Galaxy Private Tailnet

Self-hosted Tailscale control server for Galaxy devices. Provides secure WireGuard mesh network for all your devices (gateway, watch, phone, desktop).

## Architecture

```
                    Internet
                        |
         +--------------+--------------+
         |                             |
    [Headscale]                    [V2 Gateway]
    Control Server                   (Galaxy)
    :8080                            :9000
    172.25.0.0/16                    172.20.0.0/16
         |                             |
    +----+----+              +---------+---------+
    |         |              |                   |
100.64.0.1  100.64.0.10  100.64.0.20       100.64.0.30
 (Gateway)  (Watch)       (Phone)          (Desktop)
            [LTE/WiFi]    [WiFi]           [Anywhere]
```

## Quick Start

### 1. Start Headscale

```bash
cd deploy/headscale
docker compose up -d
```

### 2. Initialize (create user + auth key)

```bash
# Make scripts executable (git does not preserve permissions)
chmod +x init.sh connect-watch.sh

./init.sh
```

Save the auth key — you'll need it for all devices.

### 3. Connect V2 Gateway (host machine)

```bash
# Install tailscale if not already installed
# https://tailscale.com/download

# Connect to your headscale server
tailscale up \
  --login-server=http://localhost:8080 \
  --authkey=<AUTH_KEY_FROM_INIT> \
  --hostname=gateway \
  --accept-routes
```

The gateway will get IP `100.64.0.1`.

### 4. Connect Wear OS Watch (Galaxy Watch 6 Classic LTE)

**Method A: adb sideload Tailscale APK**

```bash
# 1. Download Tailscale Android APK
wget https://pkgs.tailscale.com/stable/tailscale-android.apk

# 2. Enable WiFi ADB on watch
#    Settings > Developer Options > Wireless Debugging

# 3. Connect adb
adb pair <WATCH_IP>:<PORT>
adb connect <WATCH_IP>:<PORT>

# 4. Install Tailscale
adb install tailscale-android.apk

# 5. Login with auth key (via adb shell)
adb shell tailscale up \
  --login-server=http://<YOUR_SERVER_IP>:8080 \
  --authkey=<AUTH_KEY> \
  --hostname=galaxy-watch-001 \
  --accept-routes
```

**Method B: Your Galaxy Wear app auto-connects**

Your `TailscaleManager` code already detects `tailscale` binary and auto-discovers the gateway. After installing Tailscale APK via adb, your app will automatically find the gateway at `100.64.0.1` through `TailscaleAdapter`.

### 5. Connect Android Phone

```bash
tailscale up \
  --login-server=http://<YOUR_SERVER_IP>:8080 \
  --authkey=<AUTH_KEY> \
  --hostname=galaxy-phone-001
```

### 6. Verify

```bash
# On any connected device
tailscale status

# Should show:
# 100.64.0.1  gateway         linux   active; direct <IP>:41641, tx 1234 rx 567
# 100.64.0.10 galaxy-watch-001 android active; relay <server>, tx 100 rx 200
# 100.64.0.20 galaxy-phone-001 android active; direct <IP>:41641, tx 500 rx 800
```

## Integration with V2 Gateway

### Your existing TailscaleManager auto-discovers

Your `core/tailscale_manager.py` already:
- Runs `tailscale status --json` every 30 seconds
- Detects 100.64.0.x IPs
- Emits STATE_EVENT AIP v3 messages on state changes
- Provides `get_network_priority()` → `["tailscale", "lan", "internet"]`

### TailscaleP2PAdapter for direct device communication

Your `core/adapters/tailscale_p2p_adapter.py`:
- Opens TCP connections directly to 100.64.0.x IPs
- Bypasses the Galaxy Gateway relay entirely
- ~5-20ms latency via WireGuard P2P
- Falls back to DERP relay if direct connection fails

### WebSocket via Tailscale

Your watch connects WebSocket directly to gateway's Tailscale IP:
```
wss://100.64.0.1:9000/ws/device/<deviceId>
```

This goes through WireGuard tunnel, encrypted end-to-end, zero latency overhead.

## Device IP Allocation

| IP Range | Device Type | Example |
|----------|------------|---------|
| 100.64.0.1 | V2 Gateway | gateway |
| 100.64.0.10-19 | Wear OS Watches | galaxy-watch-001 (100.64.0.10) |
| 100.64.0.20-29 | Android Phones | galaxy-phone-001 (100.64.0.20) |
| 100.64.0.30-39 | Desktops | galaxy-desktop-001 (100.64.0.30) |

## Management

### Web UI
```
http://localhost:3001
```

### CLI Commands
```bash
cd deploy/headscale

# List all devices
docker compose exec headscale headscale nodes list

# List users
docker compose exec headscale headscale users list

# Generate new auth key
docker compose exec headscale headscale preauthkeys create --user galaxy --reusable --ephemeral

# View node details
docker compose exec headscale headscale nodes list -o json

# Delete a node
docker compose exec headscale headscale nodes delete -i <NODE_ID>

# Route management (for subnet router)
docker compose exec headscale headscale routes list
docker compose exec headscale headscale routes enable -i <ROUTE_ID>
```

## Connecting Galaxy + Headscale Networks

To allow Galaxy services (172.20.0.0/16) to reach Tailscale devices (100.64.0.0/10):

```bash
cd deploy/headscale

# Start the subnet router
docker compose -f docker-compose.yml -f network-bridge.yml up -d tailscale-router

# Set auth key for router
docker compose exec tailscale-router tailscale up \
  --login-server=http://headscale:8080 \
  --authkey=<AUTH_KEY> \
  --advertise-routes=172.20.0.0/16 \
  --hostname=gateway-router

# Enable the route in headscale
docker compose exec headscale headscale routes list
docker compose exec headscale headscale routes enable -i <ROUTE_ID>
```

## Security Notes

- Change ACL policy in `acl.hujson` for production
- Use HTTPS for headscale server (with reverse proxy)
- Rotate auth keys regularly
- Ephemeral keys auto-expire (good for watches)
- Reusable keys can be used for multiple devices

## Troubleshooting

### Watch can't connect to headscale
```bash
# Check if tailscale is running on watch
adb shell tailscale status

# If not, check network
adb shell ping <YOUR_SERVER_IP>

# Re-login
adb shell tailscale up --login-server=http://<IP>:8080 --authkey=<KEY>
```

### Gateway can't see watch
```bash
# On gateway
tailscale ping galaxy-watch-001

# Check if direct connection or relay
tailscale status

# If relay, check UDP port 41641 is open on both sides
```

### P2P adapter connection refused
```bash
# Check if P2P server is listening on watch
adb shell netstat -tlnp | grep 19721

# Check firewall on watch
adb shell iptables -L | grep 19721
```
