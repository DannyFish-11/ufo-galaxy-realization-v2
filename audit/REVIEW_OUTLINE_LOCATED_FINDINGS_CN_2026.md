# 审查大纲问题定位报告（B 级 + P 级 + 双仓清单）

本文档把《UFO Galaxy V2 第一次与第二次审查问题完整合并总大纲》里列出的 B1–B22、
P1–P20，以及《Galaxy 双仓系统现状清单》里的"还没弄完"条目，逐条**在当前代码里定位**。

**审查基线**
- `ufo-galaxy-realization-v2` @ `c4a7949`（main 合并点）
- `ufo-galaxy-android` @ `c149d62`
- `galaxy-wearos` @ `9fe2a12`

**方法**：静态代码定位（grep / 文件读取）。所有"仍存在"结论都附带 `文件:行号` 证据。
未经真机运行验证的条目明确标注**需要运行验证**，不冒充已确认。

---

## 零、执行摘要

| 分类 | 已修复 | 部分修复 | 仍存在 | 需运行验证 |
|---|---|---|---|---|
| B 级（22 项） | 6 | 7 | 8 | 1 |
| P 级（20 项） | 2 | 6 | 12 | 0 |
| 双仓清单（10 项） | 5 | 3 | 2 | 0 |

**最高优先级的 5 个实证问题**（全部有确切行号，全部仍存在）：

1. **B17 感知资源永不释放** — `electron/renderer/perception-capture.js` 全文没有任何
   `getTracks()` / `.stop()`。摄像头和麦克风一旦开启就到进程退出为止。
2. **B4 Compose 硬编码 Mongo 凭据** — `docker-compose.yml:44` 的
   `mongodb://mongoadmin:mongoadmin123@mongodb:27017` **不可通过环境变量覆盖**。
3. **B9 远程脚本直接执行** — `core/nats_server.py:133`、`core/local_brain_manager.py:853`
   实际执行 `sh -c "curl ... | sh"`。
4. **B10 npm 依赖零锁定** — 仓库中**不存在任何 `package-lock.json`**。
5. **P13/双仓-Operator UI** — 后端有 32 个 `/api/v1/operator/*` 端点，
   Electron 面板消费其中 **0 个**。

---

## 一、B 级问题定位

### B1 配置写入接口认证绕过 — **部分修复**

- 证据：`galaxy_gateway/middleware.py:23-27` `_AUTH_EXEMPT_PATHS`
  包含 `"/api/v1/config"`，**不区分 HTTP 方法**——该路径下的任何方法都跳过鉴权。
- 证据：`core/routes/config.py:17` `router = APIRouter(prefix="/api/config")`，
  该组**没有** `Depends(require_auth)`；`core/routes/config.py:808` 注释自述
  "POST /api/config 在本开放路由组"。
- 已修复的部分：读写对称性已处理（`core/routes/config.py:806-811` 说明 GET 角标端点
  已从 system 组迁入同一开放组，消除了"写得进、读不出"）。
- 尚未解决：
  1. `/api/v1/config` 的豁免是**路径级而非方法级**；
  2. `POST /api/config` 只靠全局 `BearerAuthMiddleware` 兜底，而
     `core/auth.py:70-76` `is_auth_enabled()` **默认 False**。桌面默认部署下
     配置写入端点完全开放。
- 修复要求：豁免表改为 `(path, method)` 元组，只豁免 GET；写端点加显式
  `Depends(require_auth)`，不依赖全局中间件的开关状态。

### B2 桌面感知接口未认证 — **仍存在**

- 证据：`core/routes/perception.py:75` 起，`/api/perception/desktop/frame`、
  `/audio`、`/system_audio`、`/analyze`、`/status` **全部没有任何 auth 依赖**。
- 触发条件：`GALAXY_AUTH_ENABLED` 未设（默认 false，`core/auth.py:70`）时，
  任何能连到 9000 端口的进程都可以投递伪造摄像头帧、触发 `/analyze` 的模型调用。
- 影响：伪造感知上下文 → 影响主体决策；`/analyze` 可被用作免费模型调用放大器。
- 修复要求：感知路由组加 `Depends(require_auth)`；`/analyze` 单独限流。

### B3 Node_122_Shell 命令执行面 — **部分修复**

- 已有防护：`nodes/Node_122_Shell/main.py:133-157` `_is_command_safe()`
  实现了黑名单（`BLOCKED_COMMANDS`，行 53-65）+ shell 模式下的元字符拒绝
  （`_DANGEROUS_SHELL_PATTERNS`，行 67-69）。
  `execute()`（行 168）与 `execute_background()`（行 333）都调用了它。
- 仍存在：
  1. **黑名单是子串匹配**，`main.py:143-145`。`rm -rf /` 挡得住，`rm  -rf /*`
     （双空格）、`rm -fr /` 挡不住。
  2. **没有可执行文件白名单** —— 只有黑名单，属于枚举坏值。
  3. `main.py:200`、`main.py:353` 仍是 `create_subprocess_shell`，
     防线完全落在字符串校验上。
- 修复要求：改为白名单驱动（允许的 argv[0] 集合）+ 默认 `create_subprocess_exec`，
  `shell=True` 路径需显式配置开关才可用。

### B4 Compose 硬编码 MongoDB 连接信息 — **仍存在（高危）**

- 证据：`docker-compose.yml:44`
  ```
  - MONGODB_URI=mongodb://mongoadmin:mongoadmin123@mongodb:27017
  ```
  与同文件 `:126` 的 `MONGODB_URI=${MONGODB_URI:-mongodb://mongodb:27017}` 对比可见：
  **第 44 行没有 `${...:-}` 包装，用户无法覆盖**。
- 影响：凭据进入镜像环境、进入 `docker inspect`、进入日志；改密码需要改代码。
- 修复要求：改为 `${MONGODB_URI:?MONGODB_URI must be set}`，凭据从 `.env` 注入。

### B5 弱默认凭据 — **仍存在**

`docker-compose.yml` 全部弱默认值清单：

| 行 | 变量 | 弱默认值 |
|---|---|---|
| 107 / 155 / 311 | `NEO4J_PASSWORD` / `NEO4J_AUTH` | `neo4j123` |
| 122 / 249 | `MINIO_SECRET_KEY` / `MINIO_ROOT_PASSWORD` | `minioadmin123` |
| 121 / 248 | `MINIO_ACCESS_KEY` / `MINIO_ROOT_USER` | `minioadmin` |
| 217 / 225 | `TURN_PASSWORD` / `--user` | `galaxy123` |
| 272 | `ONEAPI_SESSION_SECRET` | `galaxy-secret` |
| 370 | `POSTGRES_PASSWORD` | `temporal`（**连 `${}` 都没有，硬编码**） |
| 453 | `MONGO_INITDB_ROOT_PASSWORD` | `mongoadmin123` |

- 修复要求：全部改成 `${VAR:?}`（无默认值即启动失败），或在 `unified_launcher`
  首次启动时生成随机密码写入 `.env`。

### B6 认证豁免路由过宽 — **部分修复**

- 证据：`galaxy_gateway/middleware.py:23-27`：
  ```python
  _AUTH_EXEMPT_PATHS = {
      "/health", "/health/live", "/health/ready", "/health/nats",
      "/api/v1/health", "/api/v1/config",
      "/metrics", "/docs", "/openapi.json",
  }
  ```
- 仍存在的过宽项：
  - `/api/v1/config` —— 配置面，见 B1。
  - `/metrics` —— Prometheus 指标暴露内部拓扑、设备数、任务量。
  - `/docs` + `/openapi.json` —— 生产模式下向未认证方泄漏完整 API 面。
- 已修复的部分：`middleware.py:181-190` 已有"启用鉴权但无 token 则一律 401"的
  fail-safe；`:198-204` 用 `hmac.compare_digest` 做常数时间比较。
- 修复要求：`/metrics`、`/docs`、`/openapi.json` 在 `GALAXY_MODE=production` 下移出豁免表。

### B7 凭据 / 服务连接信息日志泄漏 — **部分修复**

- 现状：全仓只有**一个**脱敏助手 —— `galaxy_gateway/android/handlers/auth.py:41` 的
  `_mask()`，且仅用于 Android 认证握手。
  `core/`、`galaxy_gateway/` 下**没有任何通用的 URL 凭据脱敏函数**
  （已搜 `def redact` / `def mask_` / `sanitize_url`，无命中）。
- 与 B4 叠加：`docker-compose.yml:44` 把带密码的 URI 放进环境变量，
  任何 `logger.info("... %s", os.environ["MONGODB_URI"])` 式写法都会直接落盘。
- 已修复的部分：`core/nats_server.py` 的日志（行 93、166、222）只打
  host/port 与镜像地址，未打带凭据的完整 URL。
- 修复要求：新增 `core/log_redaction.py` 提供 `redact_url()`，
  在 logging 层加 `Filter` 统一兜底，而不是逐个调用点改。

### B8 `shell=True` / `create_subprocess_shell` — **部分修复**

活跃代码中的残留：

| 文件:行 | 形式 | 说明 |
|---|---|---|
| `windows_service/tray_icon.py:340` | `subprocess.Popen(["npm","start"], shell=True)` | argv 是列表但配 `shell=True`，Windows 上语义混乱 |
| `nodes/Node_122_Shell/main.py:200` | `create_subprocess_shell` | 见 B3 |
| `nodes/Node_122_Shell/main.py:353` | `create_subprocess_shell` | 后台执行路径 |
| `core/nats_server.py:133` | `["sh","-c","curl -sf https://get-nats.io \| sh"]` | 见 B9 |
| `core/local_brain_manager.py:853` | `["sh","-c","curl -fsSL https://ollama.com/install.sh \| sh"]` | 见 B9 |
| `external/microsoft_ufo/.../shell_client.py:47` | `shell=True` | vendored 第三方，不在本仓治理范围但在依赖树内 |

- 已修复的部分：`nodes/Node_36_UIAWindows/ufo_deep_integration.py:535,548` 已显式改造为
  非 shell 启动；`nodes/Node_117_OpenCode/core/opencode_engine.py:279-280` 已注释说明
  拒绝 `curl|bash + shell=True` 组合。

### B9 `curl | bash` 供应链风险 — **仍存在（高危）**

**真正会执行的两处**（其余是文档/README 里的安装提示，风险等级不同）：

- `core/nats_server.py:133`：
  ```python
  ["sh", "-c", "curl -sf https://get-nats.io | sh"]
  ```
- `core/local_brain_manager.py:853`：
  ```python
  ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]
  ```

- 影响：远端脚本内容变化即等于本机 RCE；无摘要校验、无版本钉住。
- **对照组**：同文件 `core/nats_server.py:218` 对 zip 下载路径**已经做了**
  `sha256` 校验（"nats-server sha256 校验通过(官方 SHA256SUMS)"）。
  说明团队已有正确做法，只是 `curl|sh` 这条捷径没被一并收口。
- 修复要求：删除 `curl|sh` 分支，统一走已有的"下载 + SHA256SUMS 校验 + 解压"路径；
  Ollama 同理，或改为只提示用户手动安装。

### B10 依赖版本锁定 — **部分修复**

- **Python：部分锁定。** `requirements.txt` 84 条依赖中大量使用 `>=` 下界
  （`fastapi>=0.109.0`、`uvicorn[standard]>=0.27.0`、`openai>=1.0.0`、
  `anthropic>=0.7.0` 等）。仓库另有 `requirements-lock.txt` 与
  `requirements.hash.txt`（128 KB，含哈希），但 `install.sh` / `start.sh` 走的是
  哪一份需要确认。
- **npm：完全未锁定（仍存在）。** 仓库中**不存在任何 `package-lock.json`**：
  - `package.json`（根）— 无 lock
  - `electron/package.json` — 无 lock
  - `electron/renderer/panel/package.json` — 无 lock

  任何一次 `npm install` 都可能拉进不同的传递依赖树。
- 修复要求：提交三份 `package-lock.json`，CI 用 `npm ci` 而非 `npm install`；
  Python 侧明确"安装入口只读 lock 文件"。

### B11 Electron CSP 过宽 — **已修复**

- 证据：`electron/main.js:463-497` 已实现 dev/prod 双 CSP，通过
  `session.defaultSession.webRequest.onHeadersReceived` 注入。
- prod CSP（`:479-489`）：`default-src 'self'`、`script-src 'self'`（**无 `unsafe-eval`**）、
  `object-src 'none'`、`base-uri 'none'`、`frame-ancestors 'none'`。
- 残留（可接受）：`style-src 'self' 'unsafe-inline'` —— React 内联样式所需，
  且 `script-src` 已收紧，XSS 提权路径有限。
- dev CSP（`:467-477`）额外放开 `http://localhost:* ws://localhost:*`，
  但受 `app.isPackaged` 门控（`:492`），不会进生产。

### B12 Electron IPC 输入校验 — **部分修复**

- 已修复：
  - `electron/main.js:379-383, 769-772` `webPreferences` 正确：
    `nodeIntegration: false`、`contextIsolation: true`、`webSecurity: true`、
    `allowRunningInsecureContent: false`。
  - `galaxy:set-config`（`:1219-1231`）已做类型校验：拒绝非对象/数组、
    拒绝空键、值类型限定为 string/number/boolean。
  - `galaxy:test-runtime`（`:994-995`）用 `['docker','podman'].includes()` 白名单。
- 仍存在：
  - **`galaxy:set-config` 没有键白名单** —— 只校验类型，不校验键名是否属于
    `CONFIG_SCHEMA`。任意键会被透传到后端 `POST /api/config`，
    键治理完全依赖后端（`core/routes/config.py`）。
  - `_runRuntimeBridge`（`:972-991`）通过 `spawnSync(python, ['-c', SCRIPT, action, JSON])`
    把渲染层数据当 argv 传进内联 Python 脚本。当前 action 受白名单保护，
    但这是一条"渲染层 → 主进程 → Python 解释器"的通道，属于设计风险。
- 修复要求：`set-config` 加键白名单（与后端 `CONFIG_SCHEMA` 同源生成）。

### B13 配置文件原子写入 / 权限 / 并发 — **部分修复**

- 已修复（`core/atomic_json.py:53-118`）：
  - 同目录 `mkstemp` + `os.replace`，跨文件系统问题已避免（`:83-85` 注释明确）；
  - `fsync` 默认开启（`:101-102`）；
  - 序列化异常在临时文件阶段抛出，目标文件零字节未动；
  - `finally` 清理碎片（`:106-113`）；
  - **写入函数不再清扫目录**（`:1-12` 的长注释说明这是刻意回退的能力扩张，
    对应 commit `fae57b1`）—— 这是一个正确的修复决策。
- 仍存在：
  1. **没有显式权限设置**。文件模式隐式继承 `tempfile.mkstemp` 的 0600。
     结果对密钥文件是安全的，但：(a) 会**静默改变**已存在文件的权限；
     (b) 属于"碰巧正确"而非"契约保证"，无测试锁定。
  2. **没有进程间锁**。多进程并发写同一路径时，`os.replace` 保证单次写的原子性，
     但"读-改-写"序列会丢更新（后写覆盖先写）。桌面场景下
     `main.py` 与 Electron 主进程可能同时写配置。
- 修复要求：显式 `os.chmod(tmp, 0o600)` 并加测试；读-改-写路径引入文件锁。

### B14 `.env` 加载 / import 副作用 — **部分修复**

- **本仓已修复（做得很好）**：`main.py:20-31, 89-95, 128-151` 明确把
  `.env` 加载、stdout 重配、HF 端点设置全部关进 `if __name__ == "__main__"` 守卫，
  并写明理由（"`import main` 不产生任何全局副作用"）。
  有对应测试 `tests/test_entrypoint_import_has_no_env_side_effects.py`。
- **vendored 依赖仍污染（仍存在）**：`external/memos/` 下多处**模块级**
  `load_dotenv()`：
  - `external/memos/src/memos/log.py:27` — `load_dotenv()`
  - `external/memos/src/memos/api/config.py:26` — `load_dotenv(override=True)` ← **override**
  - `external/memos/src/memos/api/start_api.py:23` — `load_dotenv(override=True)`
  - `external/memos/src/memos/api/mcp_serve.py:15` — `load_dotenv()`

  只要任一模块被 import，就会把 `.env` 灌入 `os.environ`，
  `override=True` 甚至会**覆盖已有环境变量** —— 这会绕过 `main.py` 精心设计的守卫。
- 修复要求：确认 `external/memos` 是否进入运行时 import 图；若是，
  加 import 隔离或 fork 掉这几行。

### B15 Docker/Podman 运行时选择 — **部分修复**

- 已修复：`core/container_runtime.py` 提供了完整抽象 ——
  `_RUNTIMES = ("docker","podman")`（`:39`）、推荐 podman（`:43`）、
  统一 compose 命令解析（`:483-540`，处理 `docker compose` / `docker-compose` /
  `podman compose` / `podman-compose` 四种形态）、跨平台安装建议（`:193-236`）。
  `unified_launcher.py:933-1013` 走这套抽象。
- 仍存在：`unified_launcher.py:2336, 2391, 2392` **硬编码 `docker compose`** 字符串：
  ```
  "docker compose -f deploy/compose/full.yml --profile full up -d"
  "docker compose -f deploy/compose/full.yml --profile full ps"
  "docker compose -f deploy/compose/full.yml --profile full down"
  ```
  这是第二条未走抽象的路径，podman 用户拿到的是错误命令。
- 另：`unified_launcher.py:2354` 的注释"检测 docker/docker compose 是否可用"
  也印证这条分支只认 docker。
- 修复要求：这三处改用 `container_runtime.compose_base()`。

### B16 stop.sh / PID / 进程清理 — **部分修复**

- 已修复：`stop.sh:34-38` 已修正历史 bug（注释自述旧的
  `pkill -f "python.*galaxy_gateway"` **从来没杀掉过后端**），
  改为按仓库绝对路径限定 `pkill -f "python.*${_repo_dir}/main\.py"`，避免误杀他人项目。
- 仍存在：
  1. **PID 文件未做归属校验**（`stop.sh:21-30`）：
     ```bash
     kill $(cat .backend.pid) 2>/dev/null
     ```
     不检查该 PID 当前是否仍是 Galaxy 进程。PID 复用时会杀掉无关进程。
  2. **`&&`/`||` 优先级 bug**（`stop.sh:35-37`）：
     ```bash
     pkill -f A && ok "..." || pkill -f B && ok "..." || true
     ```
     Shell 从左到右求值为 `(((A && ok) || B) && ok) || true`。
     第一条 pkill 成功时，`ok "Backend process killed"` 会**打印两次**；
     且第二条 pkill 的执行条件与直觉不符。
  3. **没有 Windows 对应物**：只有 `start.bat`，没有 `stop.bat`。
- 修复要求：PID 文件配合 `/proc/<pid>/cmdline`（或 `ps -p`）校验命令行再 kill；
  `&&/||` 链改成显式 `if`。

### B17 感知设备 / MediaStream 资源释放 — **仍存在（高危，隐私）**

- 证据：`electron/renderer/perception-capture.js` 中：
  - `:64` `getUserMedia({video:...})` — 摄像头
  - `:85` `getDisplayMedia({video:...})` — 屏幕
  - `:96` `getUserMedia({audio:true})` — 麦克风
- **全文没有任何 `getTracks()`、`.stop()`、`beforeunload` 清理钩子**
  （已全文 grep，零命中）。
- 影响：三条 MediaStream 一旦开启，直到渲染进程退出才释放。
  即使用户通过 `/api/perception/desktop/pause`（`core/routes/perception.py:217`）
  暂停感知，**后端只是拒收帧，前端摄像头指示灯依然亮着、麦克风依然在采**。
  这是"用户以为已关闭、实际仍在采集"的隐私falsehood。
- 修复要求：
  1. 保存 stream 引用，提供 `stopAll()` 遍历 `getTracks().forEach(t => t.stop())`；
  2. 隐私暂停时前端同步调用 `stopAll()`，而非只让后端丢帧；
  3. 注册 `window.addEventListener('beforeunload', stopAll)`。

### B18 日志文件句柄 / Windows 文件锁 — **仍存在**

- 证据：`unified_launcher.py` 三处 `open(..., "ab")`，**全仓零 `.close()`**
  （已 grep `logf.close` / `_elog.close` / `_tlog.close`，零命中）：
  - `:993` `logf = open(log_dir / "docker.log", "ab")`
  - `:1161` `_elog = open(_log_dir / "electron.log", "ab")`
  - `:1259` `_tlog = open(_log_dir / "electron.log", "ab")`
- 对照：`launch_desktop.py:468-479` **做对了** —— 打开、传给 Popen、
  挂到 `_proc._stdout_handle` 保活，失败路径 `:479` 显式 `close()`。
- 影响：Windows 上句柄持有 = 文件锁，日志轮转/删除失败；
  `:1161` 与 `:1259` 打开**同一个** `electron.log`，两个句柄各自持有追加位置。
- 修复要求：改用 `with` 或在进程退出路径显式关闭；两条 electron 路径共用一个句柄。

### B19 测试污染 / 单例污染 / 工作区污染 — **需要运行验证**

- 静态可见：`tests/` 下至少 8 个文件含文件写入操作
  （`test_first_run_experience_fixes.py`、`test_env_empty_values_and_electron_intact.py`、
  `test_phase0_env_check_secrets_banner.py` 等）。
- 已有正向证据：`tests/test_entrypoint_import_has_no_env_side_effects.py` 专门锁定
  B14 的 import 副作用契约，说明该风险已被识别并有回归保护。
- **无法静态判定**这些写入是否都落在 `tmp_path` fixture 内。
- 验证方法：
  ```bash
  git status --porcelain > /tmp/before.txt
  python -m pytest tests/ -x -q
  git status --porcelain > /tmp/after.txt
  diff /tmp/before.txt /tmp/after.txt   # 必须为空
  ```

### B20 CI / 复杂度门 / 供应链门 — **部分修复**

- 已有 12 条 workflow：`ci.yml`、`codeql.yml`、`supply-chain.yml`、
  `guardrails.yml`、`governance_gate_enforcement.yml`、`node-governance.yml`、
  `system_acceptance.yml`、`dual_repo_integration.yml`、
  `dual_repo_reality_audit.yml`、`dual_runtime_cross_repo_regression.yml`、
  `fresh_integrated_code_audit.yml`、`operational_enablement_audit.yml`。
- **仍存在的缺口：`ci.yml` 里没有任何前端构建步骤。**
  grep `panel|vite|npm|node` 在 `ci.yml` 中的命中全部是 Grafana dashboard JSON 校验
  （`:104-123`）和 Python 路径列举（`:495-514`），**没有 `npm ci`、没有 `npm run build`**。
- 直接后果 → 见 B22 / P14：`dist/` 是随仓分发的构建产物，
  但**没有任何 CI 门保证它与 `src/` 一致**。

### B21 文档 / 端口 / 快捷键 / Provider 配置漂移 — **已修复（端口部分）**

- 端口一致性核对通过：
  - `README.md:38, 114, 119, 303, 334` → 9000
  - `electron/main.js:111` `return 9000`（默认值）
  - `electron/main.js:95` 优先读 `GALAXY_GATEWAY_PORT` / `PORT`
  - `electron/main.js:118` `GATEWAY_BASE` 由解析结果拼接，未硬编码
- 未发现端口漂移。快捷键/Provider/模型清单的漂移需要逐份文档比对，
  本轮未展开（不在高优先级路径上）。

### B22 Panel 构建产物与生产加载一致性 — **部分修复**

- **已修复的坑（重要）**：`.gitignore:16-21` 显式放行
  `electron/renderer/panel/src/lib/**`。注释记录了原因 ——
  Python 的 `lib/` 忽略规则曾误伤面板前端的 `src/lib/`，
  导致 `api.ts`（SSE 客户端）**从未进过仓库，克隆方只能用预编译 dist、
  无法从源码构建面板**。现已修复：`git ls-files` 确认 `src/lib/api.ts`
  与 `src/lib/presenceSocket.ts` 均已入库，26 个 src 文件与磁盘完全一致。
- **已修复的坑（第二个）**：`dist/index.html` 与 `index.html` 的注释记录了
  另一个历史 bug —— Vite 入口曾误指向已构建的 `assets/*.js`，
  导致"每次构建只是复制旧产物、源码改动永远不生效"。现已修正：
  源 `index.html` 指向 `/src/main.tsx`。
- **仍存在**：
  1. **没有一致性门**（见 B20）。`dist/assets/main-Z6NyW_wA.js` 是入库的固定哈希产物，
     任何人改了 `src/` 而忘记重建，Electron
     （`electron/main.js:740-776` 优先 `loadFile(dist/index.html)`）
     加载的仍是旧产物，且 CI 不会报错。
  2. 抽样比对（`保存中`/`已配置`/`未配置`/`诊断`/`已连接`/`未就绪` 六个 UI 字面量）
     在 dist 包中**均命中**，说明当前 dist **不是明显过期**的。
     但这只是抽样，不构成证明。
- 修复要求：CI 增加 `npm ci && npm run build`，然后 `git diff --exit-code dist/`。

---

## 二、P 级问题定位

### P1 多个启动入口重复实现核心启动逻辑 — **仍存在**

四个入口，共 5877 行：

| 入口 | 行数 | 职责自述 |
|---|---|---|
| `main.py` | 1149 | `:178` 自述为权威入口，`unified_launcher` 是 **subordinate** |
| `unified_launcher.py` | 2512 | 实际的编排实现体 |
| `launch_desktop.py` | 766 | `:27` 自述 "Phase 2: 启动 Gateway (python main.py)" |
| `system_manager.py` | 661 | 第四套 |

- `launch_desktop.py:471-472` 把 `python main.py` 拉起为**子进程**，
  同时 `:488-541` 自己还有 Electron 启动路径、`:543-599` 还有 Tauri 路径。

### P2 权威边界不清 — **部分修复**

- 已有正向证据：`main.py:178-193` 明确声明
  "`unified_launcher.py` is a **subordinate** launcher component"，
  且有 `entrypoint_role_contract.py`（`main.py:269` import）试图形式化角色契约。
- 仍存在：`launch_desktop.py` 不在该契约的表述里，它既调用 `main.py`
  又自带 shell 启动逻辑，角色是"第三方协调者"还是"兼容壳"没有定义。

### P3 Electron 与 Python 启动器存在第二套后端生命周期 — **仍存在（确证）**

- `electron/main.js:947-950`：
  ```js
  ipcMain.handle('galaxy:start-backend', async () => {
      const res = await ensureGatewayOnline(true);
  ```
- `electron/main.js:281` 里 `ensureGatewayOnline` 自己 spawn 后端并注入
  `GALAXY_GATEWAY_PORT` / `PORT`。
- 于是同一套后端有**四个**可能的拉起者：`main.py`、`unified_launcher`、
  `launch_desktop.py`、Electron 主进程。
- 已有缓解：`launch_desktop.py:491-494` 的 `PR-ELECTRON-DEDUP` 注释说明已加共享锁
  避免重复拉 Electron；`electron/main.js:262-271` 已处理"端口被占但 /health 正常"的情况。
  **这些是打补丁，不是消除第二套生命周期。**

### P4 启动参数 / 模式语义不一致 — **仍存在**

`main.py:1015-1031` 与 `launch_desktop.py:613-628` 的参数集**几乎不相交**：

| main.py | launch_desktop.py |
|---|---|
| `--setup` | `--check` |
| `--host` / `--port` / `-p` | `--backend` / `--frontend` |
| `--model` / `--select-model` | `--docker` |
| `-v` / `--verbose` | `--debug` |
| `--autostart` / `--autostart-remove` | `--skip-check` / `--skip-model-download` |
| — | `--no-interactive` / `--list-models` |

- `--verbose` vs `--debug`、`--model`（两边都有但取值域不同：
  `main.py:1022` 是自由字符串，`launch_desktop.py:621` 是
  `choices=list(AVAILABLE_MODELS.keys())`）——同名不同义。

### P5 没有唯一的 StartupOrchestrator — **仍存在**

- 存在 `core/system_orchestrator.SystemOrchestrator`（`main.py:419` import），
  但它是被 `main.py` 调用的组件，不是所有入口的收敛点：
  `launch_desktop.py` 与 `electron/main.js` 都绕过它。

### P6 / P7 没有统一 StartupPlan / 启动状态模型 — **仍存在**

- 未找到集中的 StartupPlan 数据结构；启动阶段以 `unified_launcher.py` 内
  "Phase N" 的过程式代码表达（如 `:1711` 提到的 Phase 顺序）。
- 状态以 `electron/main.js` 的 `backendStatusSnapshot()`（`:943`）、
  `core/projection/runtime_truth_compiler.py`、
  `core/operational_readiness_surface.py` 等多份并存。

### P8 / P15 Panel / Overlay / Electron / 后端状态源分裂 — **仍存在**

- Panel 走 IPC 缓存（`electron/main.js:1203-1211` 的 `configCache` / `settingsCache`）
  + REST；Overlay 走 `electron/renderer/app.js`；
  后端权威在 `core/routes/*`。三者无共同状态模型。

### P9 端口 / URL 多真相源 — **部分修复**

- 已收敛的部分：`electron/main.js:91-118` 把端口解析集中到 `resolveGatewayPort()`，
  `GATEWAY_BASE` 单点拼接，CSP（`:470,482`）也复用同一常量 —— 这条链是干净的。
- 仍存在：`launch_desktop.py:472` 独立传 `--host GATEWAY_HOST --port gateway_port`，
  与 Electron 的解析逻辑无共享来源。

### P10 容器 / 网关 / Electron 生命周期未统一 — **仍存在**

- 见 B15（compose 命令两套）、P3（后端拉起四套）、B18（Electron 日志两个句柄）。

### P11 进程归属 / 外部进程复用规则 — **部分修复**

- 已有规则：`electron/main.js:262-271` 处理"端口已占用但 `/health` 正常 → 复用"。
- 仍存在：`stop.sh` 没有对应的"这个 PID 是不是我起的"判定（见 B16.1），
  即启动侧有复用规则、停止侧没有归属规则，不对称。

### P12 停止 / 重启 / 异常退出清理 — **仍存在**

- 见 B16（PID 归属、`&&/||` bug、无 `stop.bat`）与 B18（句柄不释放）。
- `launch_desktop.py:536` 与 `:598` 用
  `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` 起 Electron/Tauri ——
  detached 进程在父进程异常退出后**不会被清理**，且不在任何 PID 文件里。

### P13 Panel 尚未成为统一控制面 — **仍存在（确证，重点）**

- 后端 `core/routes/operator.py` 提供 **32 个**端点，包括：
  `/api/v1/readiness`（`:643`）、`/api/v1/operator/snapshot`（`:289`）、
  `/api/v1/operator/devices/ecosystem`（`:944`）、
  `/api/v1/operator/devices/execution-events`（`:1074`）、
  `/api/v1/operator/devices/dispatch-readiness`（`:1871`）、
  `/api/v1/operator/flows`（`:670`）、`/api/v1/operator/action`（`:1179`）……
- 面板实际消费的端点（从 `src/lib/api.ts` + `src/hooks/*.ts` + `src/components/*.tsx` 提取）：
  ```
  /api/config, /api/config/all, /api/config/probe
  /api/perception/desktop/status
  /api/v1/chat/stream
  /api/v1/connectors[/{svc}/authorize|credentials|disconnect]
  /api/v1/mesh/worker/toggle
  /api/v1/models/{catalog,latency-probe,status,tier,verify-provider}
  /api/v1/nodes/roster, /api/v1/nodes/{n}/{action}
  /api/v1/sessions/{id}
  ```
- **交集为空。面板消费的 operator 端点数量 = 0。**
- 结论：控制面能力在后端已经建成，但没有任何 UI 消费它。
  这同时确证了双仓清单的 "Operator 统一可视化控制台 UI 未完成"。

### P14 Panel src / dist / Electron 实际加载一致性门 — **仍存在**

- 见 B20（CI 无前端构建）+ B22（dist 入库但无校验）。
- `electron/main.js:740` 注释"优先加载 Vite 构建产物 (dist/)"，`:776` `loadFile(panelPath)`
  —— 生产加载的确实是 dist，因此 dist 过期 = 用户看到旧界面且无人报警。

### P16 配置 / 端口 / 状态 / 生命周期重复造轮子 — **仍存在**

- 配置：`core/routes/config.py`（`CONFIG_SCHEMA`）、
  `electron/main.js` 的 `configCache`/`settingsCache`、
  `core/config_store`（`main.py:513`）三份。
- 见 P9 / P10。

### P17 重试 / 退避 / 熔断未统一 — **仍存在**

- 全仓 **17 个**非测试模块各自实现 backoff/retry：
  `core/reliability_contract/retry_policy.py`（看起来是意图中的统一实现）、
  `core/llm/failover.py`、`core/unified/connection_manager.py`、
  `core/connection_manager.py`（**与前者重名不同路径**）、
  `core/task_graph_runtime.py`、`core/task_graph.py`、`core/command_router.py`、
  `core/tool_guardian.py`、`core/galaxy_federation.py`、`core/ha_bridge.py`、
  `core/openclawd.py`、`core/desktop_presence_runtime.py`、
  `core/continuum/temporal_engine.py`、`core/orchestration/lifecycle.py`、
  `core/canonical_task.py`、`core/schemas/execution_failure.py`、
  `core/unified/error_mapper.py`
- 另有前端第三套：`electron/main.js` 的 `fetchWithRetry` +
  `CONFIG_FETCH_BUDGET_MS`/`CONFIG_FETCH_ATTEMPT_TIMEOUT_MS`（`:1120, 1276-1278`）。
- 注意 `:1278` 的注释："= 78000ms 今日实际值；main.js 改动后渲染层兜底常量需同步更新"
  —— **自述存在手工同步的常量漂移风险**，正是统一化缺失的直接症状。

### P18 既有功能完整保留矩阵 — **仍存在**

- `audit/completion_matrix.json` 存在（11 KB），但它是审计产物，
  不是 CI 强制的回归矩阵。

### P19 测试未覆盖真实生产启动链路 — **仍存在**

- `ci.yml` 无前端构建（B20）→ 生产加载路径（Electron → dist）零覆盖。
- 未发现端到端的"`start.sh` → 后端就绪 → Electron 加载 dist → 面板拿到数据"冒烟测试。

### P20 缺少 Windows / 安装器 / 容器 / Electron 验收门 — **仍存在**

- Windows：有 `install_windows.ps1`、`install_taskscheduler.ps1`、`start.bat`，
  但**没有 `stop.bat`**（B16.3），且 CI 未见 Windows runner 矩阵。
- Electron：无构建/加载验收门（B20/P14）。

---

## 三、《Galaxy 双仓系统现状清单》逐条核对

### P0 级三条 —— **实际都已闭环，清单已过期**

#### 1. `DEVICE_STATE_SNAPSHOT` wire ingress — **已修复**

| 侧 | 证据 |
|---|---|
| 协议定义 (V2) | `galaxy_gateway/protocol/aip_v3.py:392` `DEVICE_STATE_SNAPSHOT = "device_state_snapshot"` |
| 协议定义 (Android) | `shared-protocol/.../MsgType.kt:151` 同值 |
| **V2 入向注册** | `galaxy_gateway/android_bridge.py:1113` `self._message_handlers[MessageType.DEVICE_STATE_SNAPSHOT] = _wrap(handle_device_state_snapshot)` |
| V2 handler | `galaxy_gateway/android/handlers/device_state_snapshot.py`（14.6 KB） |
| V2 存储 | `core/android_device_state_store.py` |
| **Android 发射** | `GalaxyConnectionService.kt:5722-5727` 构造 `AipMessage(type = MsgType.DEVICE_STATE_SNAPSHOT, ...)` → `:5728` `transportManager.sendJson(...)` |
| Android 触发点 | `GalaxyConnectionService.kt:4790-4795` 文档：服务启动基线 + WS 重连恢复 |
| 归一化 | `galaxy_gateway/protocol/normalized_ingress_event.py`、`websocket_handler.py:183` |
| REST 出口 | `core/routes/operator.py:944` `/api/v1/operator/devices/ecosystem`、`:1021` `/{device_id}` |
| 另有第二发射点 | `service/handler/StateHandler.kt:236` |

#### 2. `DEVICE_EXECUTION_EVENT` wire ingress — **已修复**

| 侧 | 证据 |
|---|---|
| V2 入向注册 | `galaxy_gateway/android_bridge.py:1114` |
| V2 handler | `handlers/device_state_snapshot.py` 的 `handle_device_execution_event` |
| Android 发射函数 | `GalaxyWebSocketClient.kt:2793` `fun sendDeviceExecutionEvent(payload)` → `:2800` `type = MsgType.DEVICE_EXECUTION_EVENT` |
| Android 调用点 | `GalaxyConnectionService.kt:1017` `webSocketClient.sendDeviceExecutionEvent(closedLoopPayload)` |
| 离线补偿 | `OfflineQueue` 的 `QUEUEABLE_TYPES` 含 `device_execution_event` |
| REST 出口 | `core/routes/operator.py:1074` `/api/v1/operator/devices/execution-events` |

#### 3. readiness / governance / acceptance / strategy 报告结构化摄取 — **已修复**

| 报告类型 | 协议 | 结构化摄取目标 |
|---|---|---|
| `device_readiness_report` | `aip_v3.py:378` | `android_evaluator_artifact_ingress`（`handlers/generic.py:36`） |
| `device_governance_report` | `aip_v3.py:379` | 同上（`generic.py:37`） |
| `device_strategy_report` | `aip_v3.py:381` | 同上（`generic.py:38`） |
| `device_acceptance_report` | — | `core/android_acceptance_evidence_store.ingest_device_acceptance_report`（`handlers/acceptance_report.py:8, 36`） |

- 映射表 `handlers/evaluator_artifact_report.py:16-18` 把三类报告映射为
  `readiness` / `governance` / `strategy` 三种 evaluator kind。
- `galaxy_gateway/android/runtime_ws_profile.py:95-125` 为三者各自声明了
  `normalization_kind`。
- **结论：不再是"日志转发"，已入结构化存储。**

### P1 级两条

#### 4. Operator 统一可视化控制台 UI — **仍存在（确证）**

见 P13：后端 32 个 operator 端点，面板消费 0 个。

#### 5. 就绪矩阵 / 运行时状态 REST 暴露 — **已修复**

`core/routes/operator.py` 已暴露：
- `/api/v1/readiness`（`:643`）
- `/api/v1/operator/snapshot`（`:289`）
- `/api/v1/operator/devices/{device_id}/dispatch-readiness`（`:1817`）
- `/api/v1/operator/devices/dispatch-readiness`（`:1871`）
- `/api/v1/operator/board/operable-truth`（`:1514`）
- `/api/v1/ports`（`:908`）、`/api/v1/operator/{llm,nats,heartbeat}`（`:744, 804, 850`）
- 9 个 `/api/v1/operator/inspect/*` 深挖端点（`:340-545`）

#### 6. `hybrid_execute` 已声明但未实现 — **部分修复（半边通）**

- **Android 侧已实现**：
  - `app/src/main/java/com/ufo/galaxy/runtime/HybridExecuteFullCoordinator.kt:47` `class HybridExecuteFullCoordinator`
  - 已接线：`GalaxyConnectionService.kt:266-268` `by lazy { HybridExecuteFullCoordinator(...) }`
  - `HybridParticipantCapability.kt:44` 标注 `HYBRID_EXECUTE_FULL | AVAILABLE`
- **V2 侧仍是死槽**：
  - `galaxy_gateway/protocol/aip_v3.py:313` 只有 `HYBRID_EXECUTE = "hybrid_execute"` 常量声明
    （注释标为 `V2_INTERNAL: 混合执行 (Phase 3)`）
  - **`android_bridge._message_handlers` 里没有 `MessageType.HYBRID_EXECUTE` 条目**
  - **V2 代码里没有任何一处把 `"hybrid_execute"` 写上 wire**
    （已 grep 全部非测试 `.py`，除枚举定义外零命中）
  - `core/routes/hybrid.py:58` 的 `POST /api/v1/hybrid/execute` 走的是**本地**
    `core.hybrid_executor.get_hybrid_arbiter()`（A2A→GUI→VLM 三级降级），
    **与跨设备协议路径无关**
- **结论**：Android 建好了接收端，V2 从不发送。清单说"未实现"不准确，
  准确说法是"**Android 单边实现，V2 侧未接线，跨设备混合执行不可达**"。
- 修复要求：二选一 ——
  (a) V2 注册 handler + 在 `hybrid_arbiter` 降级链里加"派发到 Android"分支；
  (b) 正式退役：从 `aip_v3.py` 删除三个常量，Android 侧同步移除。

### P2 级四条

#### 7. Android 本地推理依赖未闭合（llama.cpp / NCNN）— **仍存在（设计决策已明确）**

- `app/build.gradle:260-278` 详细说明了原因：
  ```
  // 不通过 Gradle 依赖引入：llama.cpp(ggerganov)与 ncnn(nihui)都是 C++/CMake
  //   implementation 'com.github.ggerganov:llama.cpp:b4833'
  //   implementation 'com.github.nihui:ncnn-android-vulkan:20240410'
  // 这两条坐标【永远无法解析】(JitPack 对 llama.cpp 返回 not-found ...)
  // 走 System.loadLibrary("llama"/"ncnn") + external fun 动态链接
  //   app/src/main/jniLibs/{arm64-v8a,armeabi-v7a,x86_64}/libllama.so、libncnn.so
  ```
- **实际状态**：`app/src/main/jniLibs/` 下**只有 `README.md`，没有任何 `.so`**。
- `app/build.gradle` 中**没有 `externalNativeBuild` / `ndkVersion` / `CMakeLists`**
  —— 即没有从源码构建 `.so` 的通路。
- 影响：`NativeInferenceLoader`（`runtime/NativeInferenceLoader.kt`）的
  `System.loadLibrary` 必然失败 → 本地推理走降级路径。
  这也是 `DEVICE_STATE_SNAPSHOT` 里 `active_runtime_type` / `warmup_result` 字段的实际来源。
- 说明：这**不是 bug 而是已知的分发缺口**（构建者需自行编译放入），
  但它直接决定"clone 后零门槛即用"不成立。

#### 8. Android 模型 SHA-256 仍为 null — **部分修复（TOFU 已落地，静态钉不存在）**

- 静态常量仍是 null：
  ```kotlin
  // ModelAssetManager.kt:114-115
  val VLM_SHA256: String? = null        // populated via persistComputedChecksum after first download
  val VLM_MMPROJ_SHA256: String? = null
  ```
- **已实现 TOFU（Trust On First Use）机制**：
  - `ModelAssetManager.kt:424-441` `persistComputedChecksum(modelId)` 首次下载后计算并落盘
  - `:452-470` `loadPersistedChecksums()` 启动时回读并应用到 registry
  - `:466` 有格式校验 `Regex("[0-9a-fA-F]{64}")`
  - `:30` 注释："强制校验,防止后续损坏或篡改。TOFU 窗口仅存在于首次下载。"
  - commit `f6f942d` 补齐了 GalaxyConnectionService/UFOGalaxyApplication 两处下载点的持久化
- **残留风险**：首次下载窗口内**无任何完整性保证**。
  中间人在首次下载时投毒 → 毒化摘要被持久化 → 后续每次校验都"通过"。
- 修复要求：把真实 SHA-256 硬编码进 `VLM_SHA256` / `VLM_MMPROJ_SHA256`，
  TOFU 只作为未知模型的兜底。

#### 9. 多设备并发协同编排闭环 — **部分修复**

- 已有：`core/multi_device_coordination_authority.py`、
  `handlers/goal_execution.py`（82 KB，含 `handle_parallel_subtask`）、
  `handlers/mesh_lifecycle.py`、`handlers/mesh_topology.py`、
  `handlers/peer_exchange.py`、`core/routes/operator.py:1268` `/api/v1/operator/dispatch`
- 未确认：并发编排的**回归验证**。需要运行验证。

#### 10. clone 后"零门槛即用" — **仍存在**

阻塞项（全部有上文证据）：
- Android 本地推理需自行编译 `.so`（第 7 条）
- npm 无 lock 文件，`npm install` 结果不可复现（B10）
- `docker-compose.yml` 弱默认凭据，直接起会带着 `minioadmin123` 跑（B5）
- `curl | sh` 安装路径依赖外网可达（B9）
- 面板 dist 与 src 无一致性保证（B22）

---

## 四、修复优先级建议

### 立即（安全 / 隐私，全部单文件小改动）

| 编号 | 位置 | 动作 |
|---|---|---|
| B17 | `electron/renderer/perception-capture.js` | 加 `stopAll()` + `beforeunload` + 隐私暂停时同步停轨 |
| B4 | `docker-compose.yml:44` | 改 `${MONGODB_URI:?}` |
| B5 | `docker-compose.yml` 7 处 | 弱默认改 `${VAR:?}` |
| B9 | `core/nats_server.py:133`、`core/local_brain_manager.py:853` | 删 `curl\|sh`，复用同文件 `:218` 已有的 SHA256 校验路径 |
| B2 | `core/routes/perception.py:75` | 路由组加 `Depends(require_auth)` |
| B1/B6 | `galaxy_gateway/middleware.py:23` | 豁免表改 (path, method)；prod 下移出 `/metrics` `/docs` |

### 短期（工程闭环）

| 编号 | 动作 |
|---|---|
| B10 | 提交 3 份 `package-lock.json`，CI 改 `npm ci` |
| B20/B22/P14 | `ci.yml` 加 `npm ci && npm run build && git diff --exit-code dist/` |
| B18 | `unified_launcher.py:993,1161,1259` 三个句柄显式关闭 |
| B16 | `stop.sh` PID 归属校验 + 修 `&&/||` 优先级 + 补 `stop.bat` |
| B15 | `unified_launcher.py:2336,2391,2392` 改用 `container_runtime.compose_base()` |
| B14 | 确认 `external/memos` 是否在 import 图内；是则隔离 |

### 中期（架构）

| 编号 | 动作 |
|---|---|
| P13 | 面板接入 `/api/v1/operator/*`（32 个端点已就绪，纯前端工作） |
| 双仓-6 | `hybrid_execute` 二选一：V2 接线 or 正式退役 |
| 双仓-8 | 钉死模型 SHA-256，TOFU 降为兜底 |
| P1–P5 | 收敛入口：`launch_desktop.py` 退化为 `main.py` 的薄 wrapper |
| P17 | 统一到 `core/reliability_contract/retry_policy.py`，消除 17 份实现 |
| 双仓-7 | 提供预编译 `.so` 或 `externalNativeBuild` 通路 |

---

## 五、需要运行验证的条目

以下结论静态代码无法给出，必须实机验证：

1. **B19 测试污染**：
   ```bash
   git status --porcelain > /tmp/a; python -m pytest tests/ -q; git status --porcelain > /tmp/b; diff /tmp/a /tmp/b
   ```
2. **B22 dist 是否真的与 src 一致**：
   ```bash
   cd electron/renderer/panel && npm ci && npm run build && git diff --stat dist/
   ```
3. **B17 摄像头指示灯**：隐私暂停后观察硬件指示灯是否熄灭（预期：不熄灭）。
4. **B13 并发写配置**：两个进程同时 POST `/api/config` 不同键，验证是否丢更新。
5. **双仓-9 多设备并发编排**：两台真机同时接入，派发并行子任务，验证结果合并。
6. **B10 npm 可复现性**：不同时间两次 `npm install`，比对 `node_modules` 依赖树。

---

## 六、结论

**大纲中的 42 项（B22 + P20）与双仓清单 10 项，本轮全部完成定位。**

三点需要修正原始判断的地方：

1. **双仓清单的 P0 三条（`DEVICE_STATE_SNAPSHOT` / `DEVICE_EXECUTION_EVENT` 入向、
   报告结构化摄取）实际都已闭环**，清单已过期。Android→V2 的状态投影是通的。

2. **`hybrid_execute` 的描述需要修正**：不是"双侧未实现"，而是
   **Android 已完整实现、V2 侧从未接线**，属于单边死路而非双边空缺。

3. **P0 的真实瓶颈不在协议层，在展示层**：后端 32 个 operator 端点全部就绪，
   面板消费 0 个。这是当前"系统能力已建成但用户看不到"的最大落差。

最需要立刻处理的是 **B17（摄像头/麦克风永不释放）** ——
它是唯一一个"用户以为已关闭、实际仍在采集"的问题，性质与其他缺陷不同。
