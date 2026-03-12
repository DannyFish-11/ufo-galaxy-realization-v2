# Node_37_LinuxDBus

## 简介

Linux D-Bus 通信节点，通过 dbus-python 与系统服务进行 IPC 通信

## 端口

默认端口：**8037**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, dbus-python>=1.3.2

系统依赖：libdbus-1-dev（Linux）
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8037
```

## 主要 API

- `GET /health - 健康检查（dbus 不可用时返回 degraded）`
- `GET /status - 节点状态`
- `POST /call - 调用 D-Bus 方法（body: {bus_type, service, path, interface, method, args}）`
- `GET /introspect - 内省 D-Bus 对象（query: bus_type, service, path）`
- `POST /signal - 发送 D-Bus 信号`
- `GET /list_names - 列出 D-Bus 服务名称（query: bus_type=session|system）`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8037/health
```
