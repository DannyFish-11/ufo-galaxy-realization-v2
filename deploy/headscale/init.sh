#!/usr/bin/env bash
# ============================================================
# Galaxy 自建 tailnet —— 一次性初始化
# ============================================================
# 在 docker compose up -d 之后跑一次。它做三件事:
#   1. 在 headscale 上建用户 galaxy(已存在就跳过);
#   2. 生成一把给网关用的 API key;
#   3. 把 headscale 地址与 API key 写进网关配置
#      (.env 与 runtime/secrets.env —— 网关启动时读这两个文件,面板设置页也是存到这里)。
#
# 之后重启网关:这台电脑会自动加入 tailnet;手表配对时会自动拿到一次性进网钥匙。
# 不需要再给任何设备手工发钥匙。
#
# 用法:
#   ./init.sh                  # headscale 与网关在同一台机器上
#   ./init.sh --print-only     # headscale 在另一台机器(比如 VPS)上:只打印,
#                              # 你把打印出来的两项填到网关那台机器的面板「网络与端口」里
#
# 测试/非 docker 部署可用 HS_CMD 指定 headscale 命令,例如
#   HS_CMD="headscale -c /etc/headscale/config.yaml" ./init.sh
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
HS="${HS_CMD:-docker compose -f $HERE/docker-compose.yml exec -T headscale headscale}"
CONFIG="${HS_CONFIG_FILE:-$HERE/config.yaml}"
USER_NAME="${GALAXY_HEADSCALE_USER:-galaxy}"
PRINT_ONLY=0
[ "${1:-}" = "--print-only" ] && PRINT_ONLY=1

# ── 0. server_url 必须改过 ─────────────────────────────────────────
SERVER_URL="$(sed -n 's/^server_url:[[:space:]]*//p' "$CONFIG" | head -1 | tr -d '"'"'"' ')"
if [ -z "$SERVER_URL" ] || echo "$SERVER_URL" | grep -q "example.com"; then
  echo "✗ config.yaml 里的 server_url 还是示例值($SERVER_URL)。"
  echo "  改成设备能从外网访问到的地址(https://你的域名),同时改 tls_letsencrypt_hostname,"
  echo "  然后 docker compose up -d,再跑本脚本。"
  exit 1
fi

echo "=== Galaxy 自建 tailnet 初始化 ==="
echo "headscale: $SERVER_URL"

# ── 1. 等 headscale 就绪 ────────────────────────────────────────────
printf "[1/3] 等 headscale 就绪"
for _ in $(seq 60); do
  if $HS health >/dev/null 2>&1 || $HS users list >/dev/null 2>&1; then echo " ✓"; break; fi
  printf "."; sleep 2
done
$HS users list >/dev/null 2>&1 || { echo; echo "✗ 连不上 headscale:docker compose logs headscale 看看原因"; exit 1; }

# ── 2. 用户 ────────────────────────────────────────────────────────
if $HS users list -o json 2>/dev/null | grep -q "\"name\": *\"$USER_NAME\""; then
  echo "[2/3] 用户 $USER_NAME 已存在"
else
  $HS users create "$USER_NAME" >/dev/null
  echo "[2/3] 已建用户 $USER_NAME"
fi

# ── 3. 给网关的 API key ─────────────────────────────────────────────
API_KEY="$($HS apikeys create --expiration 365d 2>/dev/null | tail -1 | tr -d '[:space:]')"
[ -n "$API_KEY" ] || { echo "✗ 没能生成 API key"; exit 1; }
echo "[3/3] 已生成网关用的 API key(365 天有效)"

if [ "$PRINT_ONLY" = 1 ]; then
  cat <<MSG

把下面两项填到网关那台机器的面板 → 设置 → 网络与端口(填完重启网关):
  GALAXY_HEADSCALE_URL      = $SERVER_URL
  GALAXY_HEADSCALE_API_KEY  = $API_KEY
MSG
  exit 0
fi

# 写进网关配置:地址进 .env,密钥进 runtime/secrets.env(与面板保存的去处一致)。
# 已有同名项就替换,不重复追加。
upsert() {  # $1=文件 $2=键 $3=值
  local f="$1" k="$2" v="$3"
  mkdir -p "$(dirname "$f")"; touch "$f"
  if grep -q "^$k=" "$f"; then
    local tmp; tmp="$(mktemp)"
    grep -v "^$k=" "$f" > "$tmp"; cat "$tmp" > "$f"; rm -f "$tmp"
  fi
  printf '%s=%s\n' "$k" "$v" >> "$f"
}
upsert "$REPO_ROOT/.env" GALAXY_HEADSCALE_URL "$SERVER_URL"
upsert "$REPO_ROOT/.env" GALAXY_HEADSCALE_USER "$USER_NAME"
upsert "$REPO_ROOT/runtime/secrets.env" GALAXY_HEADSCALE_API_KEY "$API_KEY"
chmod 600 "$REPO_ROOT/runtime/secrets.env"

cat <<MSG

✓ 已写入网关配置:
    .env                  GALAXY_HEADSCALE_URL=$SERVER_URL
    runtime/secrets.env   GALAXY_HEADSCALE_API_KEY=(已保存,不回显)

下一步:
  1. 这台电脑装好 Tailscale 客户端(https://tailscale.com/download),然后重启网关
     —— 网关启动时会让这台电脑自动加入 tailnet(面板 → 设备 可以看到)。
  2. 手表:正常配对即可,配对时自动拿到一次性进网钥匙。
  3. 手机 / 笔记本:面板里"加入设备"生成一次性钥匙,在它们的 Tailscale App 里填。
MSG
