# 自建 tailnet(Headscale)—— 从克隆到用起来

你的电脑、手表、手机组成一张**只属于你**的内网。不管在家(同一个 Wi-Fi)还是出门
(手表自己的流量),设备之间都走这张网直连电脑上的网关与智能体,不经过任何公网入口。

## 它是什么、不是什么

| 部件 | 做什么 | 数据经过它吗 |
|---|---|---|
| **Headscale**(本目录) | 会合点:告诉设备"对方现在在哪" | ❌ 只交换地址 |
| **内置 DERP 中继** | 两边都在难打洞的 NAT 后面时兜底转发 | ✅ 但端到端加密,它看不到内容 |
| **网关**(这台电脑) | 智能体所在;自动加入 tailnet,并给手表发进网钥匙 | —— |

绝大多数时候设备之间是**直连**的(打洞成功),中继只是兜底。

### 一个硬前提

**Headscale 必须能从外网访问。** 它是出门在外的手表找到你电脑的唯一办法;只在家里
局域网可达的话,在家一切正常,出门就连不上。两种常见放法:

- **一台有域名的 VPS**(推荐):最省事,家里网络怎么变都不影响;
- **家里的电脑**:需要路由器把 80/443/3478(UDP)转发到这台电脑,再配一个 DDNS 域名。

## 步骤

### 1. 改两个地址

`config.yaml` 里:

```yaml
server_url: https://hs.你的域名.com
tls_letsencrypt_hostname: hs.你的域名.com
```

证书由 Headscale 自动向 Let's Encrypt 申请(需要 80、443 端口能从外网访问)。
已经有 Caddy/Nginx 做 TLS 的,按 `config.yaml` 里的注释改成反向代理模式。

### 2. 启动

```bash
cd deploy/headscale
docker compose up -d
```

需要放通的端口:`443/tcp`、`80/tcp`、`3478/udp`。

### 3. 初始化(一次)

```bash
./init.sh
```

它会:建用户 `galaxy` → 生成网关用的 API key → **把地址和 key 直接写进网关配置**
(`.env` 与 `runtime/secrets.env`,和面板保存设置是同一个去处)。

Headscale 在另一台机器(比如 VPS)上时用 `./init.sh --print-only`,它只打印两项,
你把它们填到网关那台电脑的**面板 → 设置 → 网络与端口**:

| 设置 | 值 |
|---|---|
| `GALAXY_HEADSCALE_URL` | `https://hs.你的域名.com` |
| `GALAXY_HEADSCALE_API_KEY` | init.sh 打印的那串(按密钥保存,不明文落盘) |
| `GALAXY_HEADSCALE_USER` | `galaxy`(默认,一般不用动) |
| `GALAXY_HEADSCALE_AUTOJOIN` | 开(默认) |

### 4. 电脑加入 —— 自动

这台电脑装好 [Tailscale 客户端](https://tailscale.com/download),**重启网关**即可。
网关启动时发现"配了 Headscale、自己还没加入",就给自己签一把一次性钥匙并执行
`tailscale up --login-server=...`。

| 情况 | 网关怎么做 |
|---|---|
| 已经在这个 tailnet 里 | 什么都不做 |
| 已经登录在别的控制服务器(比如官方 Tailscale) | **不动它**,在状态里说明 |
| 没装 Tailscale 客户端 | 提示去哪装 |
| 权限不够(Linux 上 `tailscale up` 通常要 root) | 给出一条带钥匙的命令,`sudo` 执行一次即可(钥匙 10 分钟内有效) |

也可以随时在面板里触发:`POST /api/v1/tailnet/join-this-computer`。
状态看:`GET /api/v1/tailnet/status`。

### 5. 设备加入

- **手表**:正常配对就行。配对时网关自动发一把**一次性、10 分钟有效**的钥匙,
  手表里的 tailnet 进程用它加入,之后凭自己的身份重连。手表上什么都不用输。
  (手表装不了 Tailscale App —— Wear OS 把 VPN 授权做成了空壳;所以手表 App 里内置了
  一个不需要 VPN 授权的 tailnet 进程,见 galaxy-wearos 仓 `tailnet/`。)
- **手机 / 笔记本**(装 Tailscale 官方 App 的设备):面板里生成一次性钥匙
  (`POST /api/v1/tailnet/join-key`,`device_kind` 填 `android` / `ios` / `linux` / `macos` / `windows`),
  它会给出 App 里怎么填,或者一条可直接执行的命令。

## 设备列表 = 一张表

面板的设备列表(`GET /api/v1/devices`)里,每台设备多一栏 `tailnet`:
它在内网里的地址、在不在线。Headscale 里有、但不属于任何已配对设备的机器
(比如你另外加的笔记本)单列在 `tailnet.tailnet_only`。

怎么认出"这个节点就是这块手表":配对时网关记下给它签的是哪把钥匙,Headscale 的节点
带着它是凭哪把钥匙加入的 —— 一一对应。

**在面板里移除一台设备,会同时把它踢出 tailnet。** 手表丢了,移除它,它就再也连不进
你的内网了。

## 访问规则(可选)

默认不配规则 = 你 tailnet 里的设备互相可达(全是你自己的设备)。要收紧,比如
"手表只能访问网关的 9000 端口",见 `acl.hujson` 里的示例,再把 `config.yaml` 末尾的
`policy` 两行取消注释。改完可以先检查:

```bash
docker compose exec headscale headscale policy check --file /etc/headscale/acl.hujson
```

## 常用命令

```bash
docker compose exec headscale headscale nodes list        # 有哪些机器
docker compose exec headscale headscale nodes delete -i N # 踢掉一台
docker compose exec headscale headscale apikeys list      # 网关用的 API key
docker compose logs -f headscale
```

## 排障

- **面板设备列表里 tailnet 一栏是空的**:看 `GET /api/v1/tailnet/status` 的
  `reason` 与 `how_to_fix`;`api_key_rejected` 就重新跑 `./init.sh`。
- **手表在家能连、出门连不上**:先确认手机流量下能打开 `https://hs.你的域名.com/health`;
  打不开就是 Headscale 没暴露到外网。
- **设备之间一直走中继(慢)**:检查 `3478/udp` 是否放通。

## 为什么是这样配的

- **版本钉在 0.29.4**:网关用到的 REST 接口(按用户 id 建钥匙、节点上带着加入所用的
  钥匙)在 0.26 之后才是现在的形状;`latest` 会在上游升级时悄悄变样。网关对 0.26 以前
  按用户名建钥匙的旧接口也做了兼容。
- **中继用 Headscale 自带的**,默认不依赖 Tailscale 公司的中继服务器。
- **DNS 不接管**:加入 tailnet 不会改掉这台电脑自己的 DNS。
- **去掉了** 旧的 `connect-watch.sh`(它教人往手表上装 Tailscale,装不了)、
  `network-bridge.yml`(子网路由方案,电脑直接加入 tailnet 之后不再需要)、
  第三方 Web UI 与单独的 derper 容器(面板的设备列表现在就能看节点)。
