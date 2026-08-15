# Galaxy - AI Agent 知识索引

> 本文件为 AI Agent 提供系统知识索引，每轮对话自动加载。
> 基于 Vercel 研究：被动上下文比主动调用更可靠。

## 系统概述

Galaxy 是一个 L4 级自主性智能系统，支持：
- 跨设备控制（手机、平板、电脑）
- 自然语言驱动
- MCP/Skill 扩展
- 多节点协作

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户交互层                              │
│  WebUI (配置) │ 主 UI (对话) │ 手机 App (控制)              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      系统集成层                              │
│  unified_config.py │ system_integration.py                  │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      核心模块层                              │
│  device_registry │ device_communication │ mcp_loader        │
│  skill_loader │ agent_factory │ api_routes                  │
└─────────────────────────────────────────────────────────────┘
```

## 关键文件索引

### 配置管理
- `core/unified_config.py` - 统一配置管理器
- `config.json` - 主配置文件
- `.env` - 环境变量（API Key）

### 设备管理
- `core/device_registry.py` - 设备注册和发现
- `core/device_communication.py` - 设备通信协议
- `core/device_control_service.py` - 设备控制服务

### 扩展系统
- `core/mcp_loader.py` - MCP 服务器加载器
- `core/skill_loader.py` - 技能加载器
- `core/skill_md_loader.py` - SKILL.md 格式加载器

### Agent 系统
- `core/agent_factory.py` - Agent 工厂
- `core/system_integration.py` - 系统集成层
- `core/agent/execution_planner.py` - 执行规划器（策略选择的唯一决策点）

### 策略选择的三层建议输入（都是 advisory，硬门禁永远优先）
`ExecutionPlanner._pick_strategy()` 按优先级消费三份制导，任何一份都**不能**
覆盖 task_type 映射、显式关键词、或更高优先级的制导：
- `core/cognitive/cognitive_activation_budget.py` - PR-18 认知预算 → 广度制导
- `core/cognitive/memory_bias_layer.py` - PR-19 记忆偏置（POLICY_4：优先级最低）
- `core/cognitive/experience_guidance.py` - 执行经验制导（对象锚定）

> **经验制导为什么是对象锚定的：** 它读 `TaskSummary` 的类型化字段
> （`strategy: str` / `success: bool`），作用域由 BM25 词法排序提供，
> 全程无正则、无 embedding。被它取代的旧实现把这些结构化事实写成散文、
> 向量召回 8 段、再用正则抠回结构——算出的"成功率"分母是相似度采样而非
> 真实执行总数，且直接覆写已选定的策略。
> **决策路径不得从检索到的文本里反解结构。**
> 与 `pattern_miner` 的策略模式挖掘存在职责重叠，边界见
> `EXPERIENCE_GUIDANCE_PATTERN_MINER_BOUNDARY` 哨兵。

### API 层
- `core/api_routes.py` - REST API 和 WebSocket 路由
- `dashboard/backend/main.py` - WebUI 后端

### UI 层
- `enhancements/clients/windows_client/scroll_paper_geek_ui.py` - 主 UI
- `enhancements/clients/windows_client/run_ui.py` - 启动脚本

## 消息协议

### 设备消息格式
```json
{
  "type": "command|response|heartbeat|ack|event|error",
  "action": "操作类型",
  "payload": { "数据" },
  "message_id": "消息ID",
  "timestamp": 时间戳,
  "device_id": "设备ID",
  "correlation_id": "关联请求ID"
}
```

### 消息类型
| 类型 | 用途 |
|------|------|
| command | 发送命令 |
| response | 响应命令 |
| heartbeat | 心跳保活 |
| ack | 确认消息 |
| event | 事件通知 |
| error | 错误报告 |

## API 端点索引

### 设备管理
- `POST /api/v1/devices/register` - 注册设备
- `GET /api/v1/devices` - 列出设备
- `GET /api/v1/devices/discover` - 发现设备
- `DELETE /api/v1/devices/{id}` - 注销设备

### MCP 管理
- `GET /api/v1/protocols/mcp` - 列出服务器
- `POST /api/v1/protocols/mcp/load` - 加载服务器
- `DELETE /api/v1/protocols/mcp/{name}` - 卸载服务器
- `GET /api/v1/protocols/mcp/{name}/tools` - 列出工具
- `POST /api/v1/protocols/mcp/{name}/call` - 调用工具
- `POST /api/v1/protocols/mcp/{name}/reload` - 重载服务器

> 前缀是 `/api/v1/protocols/`，不是 `/api/v1/mcp/`。本节原先写的 `/api/v1/mcp/*`
> 三条**从未存在过** —— 声明它们的 `core/api_loader.py` 是一份未挂载的重复实现
> （定义了 `APIRouter()`，但全仓没有任何 `include_router()` 引用它），已删除。
> 真正提供这些端点的是 `core/routes/protocols.py`，由 `core/api_routes.py` 挂载；
> 两者底层都调用同一个 `core.mcp_loader`。

### 技能管理
- `GET /api/v1/protocols/skills` - 列出技能
- `POST /api/v1/protocols/skills/load` - 加载技能
- `POST /api/v1/protocols/skills/{name}/execute` - 执行技能
- `DELETE /api/v1/protocols/skills/{name}` - 卸载技能
- `POST /api/v1/protocols/skills/{name}/reload` - 重载技能

只读概览另有 `GET /api/v1/system/mcp` 与 `GET /api/v1/system/skills`。

### WebSocket
- `/ws/device/{device_id}` - 设备连接
- `/ws/status` - 状态推送

## 常用操作

### 启动服务
```bash
python main.py                # 启动系统（权威入口）
# 服务编排在 launcher/services.py（GalaxyUnified），由 main.py 在 Phase 4-6 直接 import 调用；它没有自己的 CLI
```

### 运行测试
```bash
python test_system_real.py
```

### 配置 API Key
```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

## 设备能力

### 自动检测的能力
- screen, touch, keyboard
- camera, microphone
- bluetooth, nfc, gps
- accelerometer, gyroscope

### 能力协商
设备注册时自动上报能力，服务端根据能力分配任务。

## 扩展指南

### 添加 MCP 服务器
1. 在 WebUI 中加载 MCP 服务器
2. 或通过 API: `POST /api/v1/protocols/mcp/load`（注意前缀是 `/protocols/`）

### 添加技能
1. 创建 `skills/your_skill/SKILL.md`
2. 系统自动加载

### 添加设备
1. 安装安卓 App
2. 配置服务器地址
3. 连接后自动注册

## 故障排除

### 无法连接服务器
- 检查网络连接
- 检查防火墙设置
- 确认服务器地址正确

### 设备未注册
- 检查 WebSocket 连接状态
- 查看服务端日志
- 重启 App 和服务端

### UI 自动化不工作
- 开启无障碍服务
- 授权悬浮窗权限
- 确保 App 在前台

## 版本信息

- 版本: v2.3.21+
- Python: 3.9+
- Android: 7.0+

## 相关文档

详细文档请参考：
- `README.md` - 项目说明
- `README_V2.md` - V2 版本说明
- `docs/` - 详细文档目录
