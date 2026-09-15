# 节点 HTTP 面的安全契约

每个节点都自带一个 FastAPI 服务。这份文档说清楚：一次请求打到节点上，要过哪几道门、
各道门回答什么问题、失败往哪个方向倒。

新增节点时照这份做，就不会漏；漏了的话 `tests/test_all_node_http_surfaces_require_auth.py`
会变红。

## 三道门，各回答一个问题

| 门 | 回答的问题 | 实现 | 失败码 |
|---|---|---|---|
| ① 身份认证 | **你是谁** | `nodes/common/node_auth.py` → `core/auth.py` | 401 |
| ② 动作权限 | **这个动作被声明允许了吗** | `nodes/common/action_gate.py` → `core/node_action_permissions.py` | 403 |
| ③ 人确认 | **这一次这么用对不对** | `core/interaction/pending_decision_registry.py` | 拒绝执行 |

三道是**与**的关系，各管一事，谁也不能替谁：

- 只有 ①，等于"认得出你是谁，然后随你做什么"；
- 只有 ②，等于"谁都可以，但只能做白名单里的事"；
- ①② 都有而没有 ③，对通用解释器（PowerShell、`/script`）仍然不够 ——
  白名单能判"这个 cmdlet 允许吗"，判不了"这一次这么用对不对"。

③ 目前只装在 `Node_122_Shell` 上（PowerShell 与 `/script`），因为只有那里出现了
"允许的原语 + 任意内容"的组合。

## 失败方向：节点面一律 fail-closed

`core/node_invocation.py` 里这两道门在**自身出故障**时是放行的（记一条 warning 然后继续）。
那在**统一执行器**那条路上合理：它前面还有治理资格门、后面还有 HITL，权限门只是三层里的一层。

**HTTP 这条路上一层都没有。** 所以方向相反：

- 鉴权模块导不进来 → `503`，不服务；
- 权限目录读不进来 → `503`，不执行（注意 `_load_permissions()` 读失败返回**空表**，
  而空表会让 `evaluate_action_permission` 把节点判成"未声明" → legacy **放行**。
  那个默认值是给还没收编的 100+ 个节点用的，不是给一个已经声明了动作的节点用的）。

## 豁免：只有存活探针

```
/health
/healthz
/readyz
/health/live
```

以上仅限 `GET` 与 `HEAD`。

`deploy/compose/full.yml` 里 126 个 healthcheck 就是 `curl -sf .../health` —— 裸 curl，
不带任何令牌。把存活探针也要求鉴权，结果是容器永远 unhealthy、反复重启，比它想防的问题更糟。
这些路径也不暴露能力：只报告状态，不动手。

**`/status` 与 `/tools` 不豁免。** 它们同样不动手，但会把节点的能力面摊给未认证方看。
动作权限闸放它们过是另一回事（那道闸管的是"能不能做"）。

## 令牌从哪来

`core/auth.py` 的零配置自签令牌，落在 `$GALAXY_DATA_DIR/`。compose 里 `galaxy-data`
是各容器共享的卷，所以同一部署天然共用一个令牌，**不需要任何配置**。
显式配了 `GALAXY_API_TOKEN` / `GALAXY_API_TOKENS` 时优先用它们。

## 内部调用方必须带身份

节点面接上鉴权之后，仓内直接打节点端点的调用方要跟着带令牌，否则会在自己的系统里被 401 ——
安全没加上多少，先把功能打断了。

```python
from core.internal_auth import internal_headers_for

resp = await client.post(url, json=payload, headers=internal_headers_for(url))
```

**按目标地址取 header，不要在客户端构造处无条件挂上。** 仓里同一个 httpx 客户端既打节点、
也打 OpenAI / GitHub；无条件挂 `Authorization` 等于把内部令牌送给第三方 —— 那不是加固，
是凭据外泄。`internal_headers_for()` 对外部地址返回空字典；认不出来的主机按外部处理。

## 开关

| 变量 | 作用 | 默认 |
|---|---|---|
| `GALAXY_AUTH_ENABLED` | 全局鉴权总开关 | **on**（`GALAXY_MODE=production` 强制 on） |
| `GALAXY_NODE_AUTH=off` | 只关节点面 | on |
| `GALAXY_PERM_STRICT=1` | 未声明动作白名单的节点一律拒绝 | off |
| `GALAXY_SHELL_UNATTENDED=1` | 跳过人确认（**声明"这台机器上没人把关"**） | off |

`GALAXY_NODE_AUTH=off` 是给"确实不想要"的部署留的，不是给"还没想好"的。

## 关于 `0.0.0.0`

节点在容器内绑 `0.0.0.0` 是**正确的** —— 容器要接受来自同一 bridge 网络上其他容器的连接，
绑 `127.0.0.1` 会让节点间调用全部不可达。

真正的暴露面是 `deploy/compose/full.yml` 里的 `ports:` 发布到宿主机。那是部署决定：
不需要从宿主机直接访问的节点，把 `ports:` 去掉即可，服务间调用照常走内部网络。

## 新增节点时要做的

1. `install_node_auth(app, "Node_XX_Name")` —— 紧跟在 `app = FastAPI(...)` 之后；
2. 会动手的节点：在 `scripts/gen_node_catalog.py` 的 `_ACTION_PERMISSIONS` 里声明动作白名单
   （**不要**直接改 `config/node_catalog.json`，那是生成产物，下次重新生成会被抹掉），
   然后每条会动手的路由调一次 `_require("<动作名>")`；
3. 路由名 ≠ 动作名（`/type` ↔ `type_text`、`/key` ↔ `press_key`），映射要显式写出来。

守卫在 `tests/test_all_node_http_surfaces_require_auth.py` 与
`tests/test_node_http_surfaces_are_gated.py`。

## 在真实环境里验一遍

CI 和单测都跑在进程内(TestClient 走 ASGI transport,不经真实 socket、不跑 uvicorn 的
HTTP 解析、不跑 lifespan)。要确认"容器起来之后到底行不行",得真起进程:

```bash
python3 scripts/live_node_security_check.py                 # 默认那几个敏感节点
python3 scripts/live_node_security_check.py Node_06_Filesystem
```

它用 uvicorn 把节点起在真实端口上,用真实 HTTP 客户端逐条核对本文档的契约:
`/health` 免认证、无令牌 401、错令牌 401、对令牌放行。任一条不符就非零退出。

依赖 `uvicorn` 与 `httpx`;缺了会直接说,不会假装跳过。
