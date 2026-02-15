# UFO³ Galaxy Dashboard

可视化管理界面 - 监控、管理和控制整个 UFO³ Galaxy 系统

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

后端将在 `http://localhost:3000` 启动

### 2. 访问前端

直接在浏览器中打开：
```
dashboard/frontend/public/index.html
```

或者使用简单的 HTTP 服务器：
```bash
cd dashboard/frontend/public
python -m http.server 8080
```

然后访问 `http://localhost:8080`

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

### 节点端口映射

Dashboard 会自动计算节点端口：
- Node 00: 8000
- Node 01: 8001
- Node 79: 8079
- Node 80: 8080
- Node 81: 8081
- ...

## API 文档

### 系统概览
```
GET /api/overview
```

### 节点管理
```
GET /api/nodes              # 获取所有节点
GET /api/nodes/{id}         # 获取单个节点
POST /api/nodes/{id}/restart # 重启节点
```

### 日志查看
```
GET /api/logs?limit=100
```

### 任务管理
```
GET /api/tasks              # 获取任务列表
POST /api/tasks             # 创建任务
```

### WebSocket 实时更新
```
WS /ws
```

## 技术栈

### 后端
- FastAPI - Web 框架
- httpx - HTTP 客户端
- WebSocket - 实时通信

### 前端
- Vue 3 - 前端框架
- Tailwind CSS - UI 样式
- Axios - HTTP 客户端

## 截图

### 系统概览
![Overview](screenshots/overview.png)

### 节点状态
![Nodes](screenshots/nodes.png)

### 日志查看
![Logs](screenshots/logs.png)

## 开发

### 添加新功能

1. 在 `backend/main.py` 添加 API 端点
2. 在 `frontend/public/index.html` 添加 UI 组件
3. 测试并提交

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
docker build -t ufo-galaxy-dashboard .

# 运行容器
docker run -d -p 3000:3000 ufo-galaxy-dashboard
```

### 生产环境

```bash
# 使用 Gunicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.main:app
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
