# Node_90_MultimodalVision

多模态视觉理解服务节点，提供屏幕截图分析、OCR、UI 元素定位等视觉能力。

## 端口
8090

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /capture_screen` - 截取屏幕
- `POST /ocr` - 文字识别
- `POST /find_element` - 定位 UI 元素
- `POST /analyze_screen` - 屏幕内容分析
- `POST /find_text` - 查找文本位置
- `POST /find_template` - 模板匹配
