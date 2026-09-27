#!/bin/bash
# ============================================================
# Connect Galaxy Watch to Headscale Tailnet
# ============================================================
# This script connects your Galaxy Watch 6 Classic LTE to the
# private Headscale tailnet via adb.
#
# Prerequisites:
#   - Watch: Developer Options ON, WiFi ADB ON
#   - PC: adb installed, watch IP known
#   - Server: Headscale running, auth key ready
#
# Usage:
#   ./connect-watch.sh <WATCH_IP> <SERVER_IP> <AUTH_KEY>
# ============================================================

set -e

WATCH_IP=${1:-}
SERVER_IP=${2:-}
AUTH_KEY=${3:-}

if [ -z "$WATCH_IP" ] || [ -z "$SERVER_IP" ] || [ -z "$AUTH_KEY" ]; then
    echo "Usage: $0 <WATCH_IP> <SERVER_IP> <AUTH_KEY>"
    echo ""
    echo "Example:"
    echo "  $0 192.168.1.100 192.168.1.50 mkey-abc123..."
    echo ""
    echo "Get auth key:"
    echo "  cd deploy/headscale && docker compose exec headscale headscale preauthkeys create --user galaxy --reusable --ephemeral"
    exit 1
fi

echo "=== Galaxy Watch Headscale Connection ==="
echo ""
echo "Watch IP:   $WATCH_IP"
echo "Server IP:  $SERVER_IP"
echo "Auth Key:   ${AUTH_KEY:0:10}..."
echo ""

# Step 1: Pair and connect adb
echo "[1/6] Connecting to watch via adb..."
echo "       Make sure watch shows 'Wireless Debugging' screen"
echo ""
read -p "Press Enter to continue..."

echo "       Running: adb pair $WATCH_IP"
adb pair "$WATCH_IP"

# Step 2: Download Tailscale APK if not present
TAILSCALE_APK="tailscale-android.apk"
if [ ! -f "$TAILSCALE_APK" ]; then
    echo ""
    echo "[2/6] Downloading Tailscale Android APK..."
    wget -O "$TAILSCALE_APK" "https://pkgs.tailscale.com/stable/tailscale-android.apk"
else
    echo ""
    echo "[2/6] Tailscale APK already present"
fi

# Step 3: Install Tailscale
echo ""
echo "[3/6] Installing Tailscale on watch..."
adb -s "$WATCH_IP" install -r "$TAILSCALE_APK"

# Step 4: Connect to headscale
echo ""
echo "[4/6] Connecting watch to headscale tailnet..."
adb -s "$WATCH_IP" shell "tailscale up --login-server=http://$SERVER_IP:8080 --authkey=$AUTH_KEY --hostname=galaxy-watch-001 --accept-routes"

# Step 5: Verify
echo ""
echo "[5/6] Verifying connection..."
sleep 5
adb -s "$WATCH_IP" shell "tailscale status"

# Step 6: Show watch Tailscale IP
echo ""
echo "[6/6] Getting watch Tailscale IP..."
WATCH_TS_IP=$(adb -s "$WATCH_IP" shell "tailscale ip -4 2>/dev/null" | tr -d '\r')
echo ""
echo "========================================"
echo "  Galaxy Watch Tailscale IP: $WATCH_TS_IP"
echo "========================================"
echo ""
echo "Watch is now connected to the Galaxy tailnet!"
echo ""
echo "From the V2 Gateway, you can now:"
echo "  - Ping:    tailscale ping galaxy-watch-001"
echo "  - WebSocket: wss://$WATCH_TS_IP:9000/ws/device/<deviceId>"
echo "  - P2P:     Direct via 100.64.0.x (WireGuard)"
echo ""
echo "Your Galaxy Wear app will auto-detect Tailscale"
echo "and connect to the gateway via the WireGuard tunnel."
echo ""
