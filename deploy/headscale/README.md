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

### 4. Wear OS watch — **cannot join the tailnet directly**

> ⚠️ This section previously said to `adb install` the Tailscale APK on the watch.
> **That does not work**: Wear OS ships the VPN-consent activity as an empty stub
> (`com.google.android.wearable.frameworkpackagestubs/.Stubs$VpnStub`), so any app
> built on Android's `VpnService` — Tailscale included — crashes on launch. Reported
> on exactly this device (Galaxy Watch 6 Classic):
> [tailscale/tailscale#12177](https://github.com/tailscale/tailscale/issues/12177).
> This is a platform limitation, not something a newer Tailscale build fixes.

The watch reaches the gateway over the **internal network only**, by one of:

| Situation | Path | Status |
|---|---|---|
| Same Wi-Fi as the gateway | mDNS discovery → `ws://<lan-ip>:9000/ws/device/<id>` | works today |
| Direct path not working | relay through the phone (Wear Data Layer) | fallback, planned |
| Out (watch alone, or with phone nearby) | the watch app embeds Tailscale in **userspace** mode (`tsnet`, no `VpnService`) and joins the tailnet as its own node → direct WireGuard to the gateway | **built** — see below |

The public Funnel entry is **off by default** (`GALAXY_TS_FUNNEL=0`); devices talk
over the internal network only. Set `GALAXY_TS_FUNNEL=1` only if you deliberately
want the gateway reachable from the public internet.

#### How the watch joins (no typing on the watch)

The watch app ships a small userspace tailnet process (`galaxy-wearos/tailnet/`).
It needs a headscale pre-auth key **once**; the gateway hands one over during
pairing, so nothing is typed on the watch:

1. On the headscale host, create an API key for the gateway:
   ```bash
   docker exec headscale headscale apikeys create --expiration 365d
   ```
2. Give the gateway three settings (panel → network, or `.env`):
   | Setting | Value |
   |---|---|
   | `GALAXY_HEADSCALE_URL` | this headscale server, e.g. `https://hs.example.com` |
   | `GALAXY_HEADSCALE_API_KEY` | the key from step 1 (stored as a secret) |
   | `GALAXY_HEADSCALE_USER` | `galaxy` (default, as created by `init.sh`) |
3. Pair the watch as usual. The pairing response carries a **single-use,
   10-minute, non-ephemeral** pre-auth key; the watch joins with it and from
   then on reconnects with its own stored node identity.

If a key can't be issued (settings missing, API key rejected, headscale down),
pairing still succeeds — home Wi-Fi keeps working — and the response says why
(`tailnet_join_unavailable`). `GET /api/v1/pair/paths` shows the same under
`watch_tailnet`.

**The watch must be able to reach this headscale server from outside** (it is
the rendezvous point: it tells the watch and the gateway where to find each
other; data then flows directly between them, or via the embedded DERP relay —
still end-to-end encrypted — when NAT hole punching fails). A headscale that is
only reachable on your home LAN works at home but not outdoors.

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

Tailnet devices (phone, desktop) connect to the gateway's Tailscale IP:
```
ws://100.64.0.1:9000/ws/device/<deviceId>
```

**`ws://`, not `wss://`.** The WireGuard tunnel already encrypts and authenticates
the traffic end-to-end. `wss://` to a bare IP has no workable certificate (public
CAs don't issue certs for IPs; Tailscale/headscale certs are for MagicDNS names),
and the gateway runs without TLS unless `GALAXY_TLS_CERT` + `GALAXY_TLS_KEY` are
set — so a hardcoded `wss://` here was a guaranteed handshake failure. The scheme
the gateway hands out now follows its actual TLS config (`core/gateway_tls.py`).

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

### Watch can't connect

The watch is not a tailnet member (see section 4). Check instead:
- it's on the same Wi-Fi as the gateway, and the gateway's mDNS announcer is on
  (`GALAXY_MDNS` not set to `0`);
- `GET /api/v1/pair/paths` on the gateway — it lists every path and why a down
  one is down.

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
