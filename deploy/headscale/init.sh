#!/bin/bash
# ============================================================
# Headscale Initialization Script
# ============================================================
# Run once after `docker compose up -d` to create user and
# generate pre-auth keys for devices.
#
# Usage:
#   cd deploy/headscale
#   docker compose up -d
#   ./init.sh
# ============================================================

set -e

HS="docker compose exec headscale headscale"

echo "=== Galaxy Headscale Initialization ==="
echo ""

# Wait for headscale to be ready
echo "[1/5] Waiting for headscale to be ready..."
until docker compose exec headscale wget -qO- http://localhost:8080/health > /dev/null 2>&1; do
  sleep 2
done
echo "      Headscale is ready!"

# Create galaxy user (tailnet)
echo ""
echo "[2/5] Creating galaxy user..."
$HS users create galaxy 2>/dev/null || echo "      User 'galaxy' already exists"

# Create reusable auth key for devices
echo ""
echo "[3/5] Generating reusable auth key..."
AUTHKEY=$($HS preauthkeys create --user galaxy --reusable --ephemeral 2>/dev/null | grep -o 'mkey-[a-f0-9]*' || true)

if [ -z "$AUTHKEY" ]; then
  # Try alternative format
  AUTHKEY=$($HS preauthkeys create --user galaxy --reusable --ephemeral 2>&1 | tail -1 | tr -d ' \t')
fi

echo ""
echo "========================================"
echo "  AUTH KEY FOR DEVICES:"
echo ""
echo "  $AUTHKEY"
echo ""
echo "========================================"

# List existing keys
echo ""
echo "[4/5] Listing pre-auth keys..."
$HS preauthkeys list --user galaxy 2>/dev/null || true

# Show status
echo ""
echo "[5/5] Headscale status:"
echo ""
echo "  Control Server: http://localhost:8080"
echo "  Web UI:         http://localhost:3001"
echo "  User:           galaxy"
echo "  Auth Key:       $AUTHKEY"
echo ""
echo "=== Save the auth key above! ==="
echo ""
echo "Device connection commands:"
echo ""
echo "  # V2 Gateway (server side):"
echo "  tailscale up --login-server=http://localhost:8080 --authkey=$AUTHKEY --hostname=gateway"
echo ""
echo "  # Wear OS Watch (via adb):"
echo "  adb shell tailscale up --login-server=http://<YOUR_SERVER_IP>:8080 --authkey=$AUTHKEY --hostname=galaxy-watch-001"
echo ""
echo "  # Android Phone:"
echo "  tailscale up --login-server=http://<YOUR_SERVER_IP>:8080 --authkey=$AUTHKEY --hostname=galaxy-phone-001"
echo ""
echo "=== Galaxy Network Map ==="
echo "  Gateway (V2):  100.64.0.1"
echo "  Watch range:   100.64.0.10-100.64.0.19"
echo "  Phone range:   100.64.0.20-100.64.0.29"
echo "  Desktop range: 100.64.0.30-100.64.0.39"
echo ""
