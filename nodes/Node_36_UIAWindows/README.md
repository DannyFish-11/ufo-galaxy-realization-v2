# Node_36_UIAWindows

## 简介

Windows 桌面自动化节点，使用 pyautogui/pygetwindow 实现 GUI 自动化操作

## 端口

默认端口：**8036**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, pyautogui, Pillow, pygetwindow, pyperclip
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8036
```

## 主要 API

- `GET /health`
- `POST /click`
- `POST /double_click`
- `POST /type`
- `POST /hotkey`
- `POST /screenshot`
- `GET /windows`
- `POST /window`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8036/health
```
