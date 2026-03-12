# Node_27_SmartHome

智能家居控制服务节点，通过 Home Assistant REST API 提供设备控制、场景触发等功能，并内置 in-memory 设备注册表作为回退。

## 端口
8027

## 环境变量
- `HOME_ASSISTANT_URL`: Home Assistant 地址（如 `http://homeassistant.local:8123`）
- `HOME_ASSISTANT_TOKEN`: HA 长期访问令牌
- `TUYA_API_KEY`: Tuya API Key（可选）
- `TUYA_API_SECRET`: Tuya API Secret（可选）
- `TUYA_REGION`: Tuya 区域（默认 `cn`）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /devices` - 列出所有已知设备
- `POST /devices/register` - 注册设备
- `POST /devices/control` - 控制设备
- `GET /devices/{device_id}` - 获取设备详情
- `GET /scenes` - 列出场景
- `POST /scenes/trigger` - 触发场景
- `POST /ha/call` - 直接调用 Home Assistant 服务
- `GET /ha/states` - 获取 Home Assistant 实体状态

## 工作模式

1. **Home Assistant 模式**：配置 `HOME_ASSISTANT_URL` 和 `HOME_ASSISTANT_TOKEN` 后，设备控制和场景触发会通过 HA REST API 执行。
2. **In-Memory 模式**：未配置 HA 时，设备注册和控制状态保存在内存中，作为开发/测试回退。
