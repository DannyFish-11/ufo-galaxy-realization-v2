# Node_45_DesktopAuto

## 简介

桌面自动化节点，使用 pyautogui 实现跨平台鼠标、键盘和屏幕截图操作

## 端口

默认端口：**8045**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, pyautogui, Pillow
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8045
```

## 主要 API

- `GET /health`
- `POST /click`
- `POST /double_click`
- `POST /type`
- `POST /hotkey`
- `POST /press`
- `POST /move`
- `GET /screenshot`
- `GET /position`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8045/health
```
