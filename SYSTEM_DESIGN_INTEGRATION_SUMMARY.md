# System Design Integration Summary — 系统设计整合摘要

> 统一主体架构的规范说明见
> [docs/UNIFIED_SUBJECT_ARCHITECTURE.md](docs/UNIFIED_SUBJECT_ARCHITECTURE.md)。

## 统一主体 (Unified Subject)

系统的主体由两层构成且仅有一个主体：

- **DesktopPresenceRuntime** — 运行时外壳（runtime shell）：拥有三态生命周期
  （silent → liminal → manifest → silent）、生成规范关联 ID `runtime_session_id`、
  承载桌面原生多模态感知入口（`MultimodalIngressBus`）。
- **OpenClawd** — 主体认知核心（subject core）：认知、决策与执行策略。

## 集成要点

1. **入口纪律 (PR-01)** — `main.py` 是唯一主入口，`unified_launcher.py` 为子入口；
   所有兼容面（gateway chat、legacy dashboard、`scripts/launcher_v2.py`）显式降级为非主入口。
2. **设备 ingress 纪律 (PR-25)** — WebSocket 设备接入的唯一规范路径是
   `/ws/device/{device_id}`；`/ws/android*`、`/ws/ufo3/*` 为兼容面，全部汇聚到同一处理器。
3. **拓扑单一视图 (PR-8)** — NATS fabric、网关底座、设备连通性信号统一吸收进
   `core/network_topology_runtime.py`，渲染器/规划器/叙事面只读取该运行时的快照。
4. **域治理 (PR-5)** — 设备域（身份/在场）与节点域（执行/分发）职责由
   `core/device_node_domain_governance.py` 划界，桥接层不得折叠两域。
5. **L4 增强循环** — `core/galaxy_main_loop_l4_enhanced.py` 作为后台增强层运行，
   不进入 per-request 主链。
