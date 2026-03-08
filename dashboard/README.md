# Galaxy Dashboard

可视化管理界面 - 监控、管理和控制整个 Galaxy 系统

## 功能特性

### 1. 系统概览
- 总节点数统计
- 运行/停止/错误节点数
- 系统健康率
- 实时状态更新

### 2. 节点管理
- 节点状态监控
- 节点健康检查
- 节点重启控制
- 节点详情查看

### 3. 日志查看
- 实时日志流
- 日志级别过滤
- 日志搜索
- 日志导出

### 4. 任务管理
- 任务创建和编排
- 任务执行状态
- 任务历史记录

### 5. 记忆系统
- 对话历史查看
- 记忆统计
- 用户画像

## 快速开始

### 1. 启动后端

```bash
cd dashboard/backend
pip install -r requirements.txt
python main.py
```

后端将在 `http://localhost:8080` 启动。

### 2. 访问前端

直接在浏览器中打开：
```
http://localhost:8080/
```

前端 `index.html` 由后端静态文件路由直接提供服务，无需单独的 HTTP 服务器。

> 如果仅需本地预览，也可通过简单 HTTP 服务器：
> ```bash
> cd dashboard/frontend/public
> python -m http.server 8081
> ```
> 然后访问 `http://localhost:8081`（此模式下 API 调用需后端同时运行）。

### 3. 构建 TypeScript 前端（可选）

TypeScript 源码位于 `dashboard/frontend/ts/`，编译产物输出到 `dist/`。

```bash
cd dashboard/frontend
npm install       # 安装依赖（vue、axios、typescript 等）
npm run build     # 编译 TypeScript
```

## WebSocket 实时连接

后端 WebSocket 端点：`ws://localhost:8080/ws`

前端 TypeScript 客户端示例（`dashboard/frontend/ts/api.ts`）：

```typescript
import { GalaxyAPI } from './api';

const api = new GalaxyAPI('http://localhost:8080');
api.connectWebSocket((msg) => {
  console.log('WS message:', msg);
});
api.sendWSMessage({ type: 'ping' });
```

## 配置

### 环境变量

```bash
# 节点基础 URL
NODE_BASE_URL=http://localhost

# 节点端口起始值
NODE_PORT_START=8000

# 日志级别
LOG_LEVEL=INFO
```

## API 文档

### 系统信息
```
GET /api/v1/system/info
GET /api/v1/ascii
```

### 设备管理
```
GET  /api/v1/devices              # 获取设备列表
POST /api/v1/devices/register     # 注册设备
POST /api/v1/devices/{id}/command # 发送设备命令
```

### Agent 管理
```
GET /api/v1/agents                # 获取 Agent 列表
GET /api/v1/llm/providers         # 获取 LLM 提供商列表
```

### 聊天
```
POST /api/v1/chat                 # 统一聊天入口
POST /api/v1/dashboard/chat       # 仪表盘聊天（与上同功能）
```

### 多设备并行执行
```
POST /api/v1/execute/parallel     # 并行执行多设备命令
```

### WebSocket 实时更新
```
WS /ws
```

消息格式：
```json
{ "type": "ping" }                         // 心跳
{ "type": "chat", "content": "你好" }      // 发送聊天
{ "type": "chat_response", "content": "..." } // 聊天回复（服务端推送）
{ "type": "status_update", "data": {} }    // 状态更新（服务端推送）
```

## 技术栈

### 后端
- FastAPI - Web 框架（端口 8080）
- httpx - HTTP 客户端
- WebSocket - 实时通信

### 前端
- Vue 3 - 前端框架（CDN 加载）
- Tailwind CSS - UI 样式（CDN 加载）
- Axios - HTTP 客户端（CDN 加载）
- TypeScript - 类型安全客户端（`ts/` 目录）

## 开发

### 添加新功能

1. 在 `backend/main.py` 添加 API 端点
2. 在 `frontend/ts/types.ts` 更新类型定义
3. 在 `frontend/ts/api.ts` 更新客户端方法
4. 在 `frontend/public/index.html` 添加 UI 组件
5. 测试并提交

### 调试

后端日志：
```bash
tail -f dashboard.log
```

前端调试：
- 打开浏览器开发者工具
- 查看 Console 和 Network 标签

## 部署

### Docker 部署

```bash
# 构建镜像
docker build -t galaxy-dashboard .

# 运行容器
docker run -d -p 8080:8080 galaxy-dashboard
```

### 生产环境

```bash
# 使用 Gunicorn + Uvicorn workers
gunicorn -w 4 -k uvicorn.workers.UvicornWorker dashboard.backend.main:app --bind 0.0.0.0:8080
```

## 故障排查

### 节点无法连接
1. 检查节点是否启动
2. 检查端口是否正确
3. 检查防火墙设置

### WebSocket 断开
1. 检查网络连接
2. 检查后端日志
3. 刷新页面重新连接

## 许可证

MIT License

