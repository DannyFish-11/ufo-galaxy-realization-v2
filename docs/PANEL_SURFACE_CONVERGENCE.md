# 面板表层收敛

这份文件记的是**做了什么、代价是什么**，不是设计蓝图。

## 收敛前：五份表层

仓库同时存在五个面向用户的界面实现：

| 表层 | 形态 | 规模 |
|---|---|---|
| `electron/renderer/panel/` | React/Vite 面板 + lumiv WebGL 覆盖层，跑在 Tauri（回退 Electron）壳里 | ~4,000 行 TS |
| `static/api-manager/` | 只有构建产物、没有源码 | 8.6 MB |
| `static/operator-console/` | 731 行原生 JS 轮询页 | 731 行 |
| `windows_client/status_board_v2/` | 终端 ANSI 状态板，`python -m` 手动启动 | 8,618 行 / 22 个模块 |
| `unified_launcher._get_legacy_dashboard_html()` | 内联占位 HTML，**零调用方** | 25 行 |

五份各读各的聚合层。这不是审美问题——`electron/renderer/panel/src/App.tsx`
里那段相位优先级的长注释记录的就是它造成的一次真实故障：面板显示的三态来自
一个跟真实请求生命周期完全不同步的状态源，表现为"直接跳到表达中且卡住不回待机"。

## 收敛后：一份

保留 `electron/renderer/panel/`，其余四份删除。

外壳由 `unified_launcher.start_desktop_shell()` 拉起：优先 Tauri
（`desktop-tauri/`，Rust 主进程 + 系统 WebView2），未构建则回退 Electron
（`electron/`）。两者共用同一份前端。

## 代价：这不是纯粹的去重

前三份是重复或死代码，删掉没有损失。**`status_board_v2` 不是**——它有 React
面板没有对应物的能力，删除它是净减：

| 能力 | 行数 | React 面板 |
|---|---|---|
| `topology_layout` 星座布局 | 867 | ❌ |
| `topology_renderer` 拓扑渲染 | 637 | ❌ |
| `topology_inspector` 节点/关系/就绪/路由巡检 | 1,307 | ❌ |
| `topology_history` 可观测历史 | 1,358 | ❌ |
| `liminal` / `manifest` / `return` / `operational_state` 四个 surface | 775 | ❌ |
| phase / domain / device / metrics | — | ✅（对话、维态、能力、模型四个 tab） |

还有一项**写能力**的损失，更需要注意：

`status_board_v2` 带 `ConfigControlSurface`，能切 provider 开关、设
`native_mm_policy`，写入链路是

```
ConfigControlSurface → ConfigService → ConfigStore → runtime/config.json
                     → HotReloadConfigManager（写成功后热重载）
```

React 面板走的是**另一条**链路：

```
设置页 → POST /api/config → CONFIG_SCHEMA（155 个键）→ .env / runtime/secrets.env
```

两条链路写不同的存储，且 `CONFIG_SCHEMA` 里**既没有 provider 开关键、也没有
`native_mm_policy` 键**。所以这两项写能力不是换了个地方，是暂时没有了。

直接后果（`scripts/check_wiring.py` 会如实报出）：`ConfigService` 的
`set_toggle` / `set_native_mm_policy` / `set_provider_api_key` /
`set_network_url` / `set_android_inference_mode` 五个写方法，在生产代码里失去了
唯一调用方。方法和单元测试都还在，但没有运行期入口能触达。

这一段同样写进了 `core/operational_enablement_audit.py`（`DESKTOP_BOARD_VERDICT`
从 `STATUS_PLUS_BOUNDED_CONTROL` 改为 `STATUS_READ_ONLY_WITH_ENV_CONFIG`），
并由 `tests/test_operational_enablement_audit.py` 钉住不许被悄悄抹平。

### 顺带暴露的一处存量死代码

`check_wiring` 报的其实是 **6** 条，第 6 条性质不同，值得分开说：

`core/desktop_consumption_adapter.py` 的 `readiness_label()` 从来没有被生产代码
调用过（`git grep '\.readiness_label()'` 在删除前只命中一份文档示例和一个测试）。
它此前之所以不被判为未接线，是因为 `check_wiring` **按名字匹配**，而被删的
`status_board_v2/topology_history.py` 里恰好有一个同名属性 `readiness_label`
挡在那里。

所以它不是这次删出来的债，是这次**揭出来的**存量债——删掉那层遮挡之后才显形。
两类都进了 `config/wiring_baseline.json`（该基线是按名字记的，没法区分），
差别记在这里。

## 供给侧完全没动

被删的是**渲染层**。投影端点一条没少：

```
GET /api/v1/projection/runtime
GET /api/v1/projection/runtime-truth
GET /api/v1/projection/desktop-status-board
GET /api/v1/panel/unified · /api/v1/panel/feed
WS  /ws/desktop-presence
```

`contracts/desktop_status_projection.py`、`core/routes/projection.py`、
`desktop_projection/`（阈限空间与显现台状态机）都原样保留。要把拓扑视图重新
做出来，数据是现成的——需要重写的只是渲染。

## 怎么防止它再长回来

- `scripts/validate_runtime.py` 的终局检查：三个已删目录不得存在
- `tests/test_pr9_operator_console.py::TestParallelWebSurfacesStayDeleted`
- `tests/test_pr52_repo_layout.py::TestStatusBoardV2Removed`（同时钉"旧的没了"
  与"新的在"——只钉前者的话，把两个目录一起删掉也能全绿）
- `tests/test_pr48_ui_surface_demotions.py::test_13b_only_one_projection_driven_surface`
  ——册上只允许有一个 `PROJECTION_DRIVEN` 表层

被删的表层没有从册上消失，而是在
`core/ui_surface_authority.py` 与 `core/orchestration_authority/legacy_paths.py`
里改注册为 `DELETED`，并带 `superseded_by="electron.renderer.panel"`。
删除记录本身是资产，抹掉它就等于把这段历史也删了。

## 未做

- **拓扑/可观测视图没有搬进 React 面板**。上面那张表的 ❌ 是当前状态，不是计划。
- **两套配置写入链路没有合并**。provider/routing 维度的写能力要补回来，正确做法
  是把 `ConfigService`（写 `config.json`）与 `CONFIG_SCHEMA`（写 `.env`）合成一套，
  而不是给已删的表层造一个替身。
- 历史设计文档（`docs/TOPOLOGY_*.md`、`docs/OBSERVABILITY_HISTORY.md`、
  `docs/DIAGNOSTICS_INSPECTION_INTERACTION.md` 等）**未改写**。它们是当时的设计
  记录，描述的是那个时点的事实；把它们改成好像从来没存在过，比留着更失真。
  需要知道"现在还有没有"的读者，以本文件为准。
