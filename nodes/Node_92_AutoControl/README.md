# Node_92_AutoControl

统一自动操控接口服务节点，提供鼠标点击、键盘输入、滚动等桌面自动化操作。

## 端口
8092

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /click` - 鼠标点击
- `POST /input` - 键盘输入
- `POST /scroll` - 滚动操作
- `POST /press_key` - 按键操作
- `POST /hotkey` - 快捷键操作
