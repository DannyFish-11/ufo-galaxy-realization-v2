# Node_66_ConfigManager

配置管理服务节点，负责集中管理系统配置项的读取、更新与持久化。

## 端口
8066

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /configs` - 列出所有配置
- `POST /config/load` - 加载配置文件
- `GET /config/{key}` - 获取配置项
- `POST /config/set` - 设置配置项
