# UFO Galaxy L4 级自主性智能系统部署指南

## 系统概述

UFO Galaxy L4 是一个完全自主的智能系统，具备以下能力：

- ✅ **自主发现工具和资源** - 自动扫描环境中的编程语言、IDE、数据库等
- ✅ **自主编写代码** - 根据需求生成代码、测试、修复并部署
- ✅ **自主设定和分解目标** - 将高层次目标分解为可执行的子任务
- ✅ **跨设备协同** - 控制安卓手机、无人机、3D打印机、量子计算机
- ✅ **自我学习和优化** - 从执行中学习，持续改进性能

---

## 部署步骤

### 1. 克隆仓库

```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-realization.git
cd ufo-galaxy-realization
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置系统

编辑配置文件：

```bash
nano config/l4_config.json
```

关键配置项：

```json
{
  "system": {
    "enable_l4": true
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 8765
  },
  "devices": {
    "android": {"enabled": true},
    "drone": {"enabled": true},
    "printer_3d": {"enabled": true},
    "quantum": {"enabled": true}
  }
}
```

### 4. 启动系统

#### 方式一：手动启动

```bash
python3 start_l4.py
```

#### 方式二：systemd 服务（开机自启动）

```bash
# 复制服务文件
sudo cp deployment/ufo-galaxy-l4.service /etc/systemd/system/

# 重新加载 systemd
sudo systemctl daemon-reload

# 启用服务
sudo systemctl enable ufo-galaxy-l4.service

# 启动服务
sudo systemctl start ufo-galaxy-l4.service

# 查看状态
sudo systemctl status ufo-galaxy-l4.service

# 查看日志
sudo journalctl -u ufo-galaxy-l4.service -f
```

#### 方式三：Docker（推荐用于生产环境）

```bash
# 构建镜像
docker build -t ufo-galaxy-l4 -f Dockerfile.l4 .

# 运行容器
docker run -d \
  --name ufo-galaxy-l4 \
  --restart always \
  -p 8765:8765 \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/logs:/app/logs \
  ufo-galaxy-l4
```

---

## 验证部署

### 1. 检查系统状态

```bash
curl http://localhost:8765/status
```

预期输出：

```json
{
  "running": true,
  "state": "IDLE",
  "cycle_count": 10,
  "performance_level": "good"
}
```

### 2. 提交测试目标

```bash
curl -X POST http://localhost:8765/goal \
  -H "Content-Type: application/json" \
  -d '{
    "description": "了解量子计算的最新进展",
    "type": "information_gathering"
  }'
```

### 3. 查看日志

```bash
tail -f logs/galaxy_l4.log
```

---

## 连接安卓端

### 1. 安卓端配置

在安卓端 `WebSocketClient.kt` 中设置服务器地址：

```kotlin
private val serverUrl = "ws://服务器IP:8765/android"
```

### 2. 发送设备注册消息

```kotlin
val registerMsg = AIPMessageV3.DeviceRegister(
    deviceId = getDeviceId(),
    deviceType = DeviceType.ANDROID_PHONE,
    capabilities = listOf("gui_control", "voice_input", "accessibility")
)
webSocket.send(Gson().toJson(registerMsg))
```

### 3. 验证连接

在服务端日志中应该看到：

```
INFO - 安卓设备已注册: device_xxx
```

---

## 控制物理设备

### 无人机控制

系统会自动调用 `Node_43_MAVLink` 节点：

```python
# 自然语言输入
"让无人机起飞到 10 米高度"

# 系统自动执行
1. 目标分解 → "连接无人机" + "解锁" + "起飞"
2. 规划 → 调用 Node_43_MAVLink
3. 执行 → mavlink.connect() → mavlink.arm() → mavlink.takeoff(10)
```

### 3D 打印机控制

系统会自动调用 `Node_49_OctoPrint` 节点：

```python
# 自然语言输入
"用 3D 打印机打印 model.stl"

# 系统自动执行
1. 目标分解 → "上传文件" + "开始打印"
2. 规划 → 调用 Node_49_OctoPrint
3. 执行 → octoprint.upload() → octoprint.print_start()
```

---

## 性能优化

### 1. 调整循环间隔

编辑 `config/l4_config.json`：

```json
{
  "main_loop": {
    "cycle_interval": 1.0  // 更快的响应
  }
}
```

### 2. 启用并发执行

```json
{
  "main_loop": {
    "max_concurrent_tasks": 20  // 增加并发数
  }
}
```

### 3. 优化资源利用

```json
{
  "reasoning": {
    "world_model_max_entities": 50000  // 增加实体数量
  }
}
```

---

## 监控和维护

### 1. 健康检查

```bash
curl http://localhost:8765/health
```

### 2. 查看性能指标

```bash
curl http://localhost:8765/metrics
```

### 3. 重启服务

```bash
sudo systemctl restart ufo-galaxy-l4.service
```

### 4. 查看错误日志

```bash
grep ERROR logs/galaxy_l4.log
```

---

## 故障排除

### 问题 1：系统无法启动

**解决方案**：

```bash
# 检查依赖
pip install -r requirements.txt

# 检查配置文件
python3 -m json.tool config/l4_config.json

# 查看详细日志
python3 start_l4.py
```

### 问题 2：无法连接安卓端

**解决方案**：

```bash
# 检查防火墙
sudo ufw allow 8765

# 检查端口占用
netstat -tuln | grep 8765

# 测试 WebSocket 连接
wscat -c ws://localhost:8765/android
```

### 问题 3：性能下降

**解决方案**：

```bash
# 查看资源使用
top -p $(pgrep -f start_l4.py)

# 清理旧日志
find logs/ -name "*.log" -mtime +7 -delete

# 重启服务
sudo systemctl restart ufo-galaxy-l4.service
```

---

## 高级功能

### 1. 自主编程

系统可以根据需求自动生成代码：

```python
# 自然语言输入
"创建一个节点，用于读取 CSV 文件并计算平均值"

# 系统自动执行
1. 分析需求 → 确定需要 pandas 库
2. 生成代码 → 创建 Node_XXX_CSVAnalyzer
3. 测试代码 → 在沙箱中执行
4. 部署节点 → 注册到系统
```

### 2. 自主学习

系统会从每次执行中学习：

- 记录成功和失败的模式
- 识别常见错误
- 自动优化执行策略
- 调整资源分配

### 3. 元认知

系统会定期自我反思：

- 评估性能（成功率、时长、资源利用率）
- 识别优势和劣势
- 生成改进建议
- 自动调整策略

---

## 安全建议

1. **限制网络访问**：只允许信任的设备连接
2. **启用身份验证**：为 WebSocket 连接添加 token 验证
3. **沙箱隔离**：自主编程功能使用 Docker 沙箱
4. **日志审计**：定期检查系统日志
5. **资源限制**：设置 CPU 和内存限制

---

## 支持

- GitHub: https://github.com/DannyFish-11/ufo-galaxy-realization
- Issues: https://github.com/DannyFish-11/ufo-galaxy-realization/issues
