# Galaxy - Windows 使用指南

## 快速开始

### 1. 安装

双击运行 `windows/install.bat`

或手动安装：
```powershell
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
pip install pystray pillow

# 复制配置文件
copy .env.example .env
```

### 2. 配置

编辑 `.env` 文件，填入你的 API Key：
```
# 推荐使用 OneAPI 统一网关
ONEAPI_URL=http://localhost:3000
ONEAPI_API_KEY=your-oneapi-key

# 或单独配置
OPENAI_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-xxx
```

### 3. 启动

**方式一：快速启动**
```
双击 windows/quick_start.bat
```

**方式二：托盘模式**
```
双击 windows/start_galaxy.bat
```
启动后会在右下角托盘区显示图标

**方式三：命令行**
```powershell
venv\Scripts\activate
python run_galaxy.py
```

---

## 系统托盘

启动后，右下角托盘区会显示 Galaxy 图标：

| 图标颜色 | 状态 |
|----------|------|
| 🟢 青色 | 运行中 |
| 🟡 黄色 | 部分异常 |
| 🔴 红色 | 已停止 |
| ⚪ 灰色 | 待机中 |

### 右键菜单

- 打开控制面板
- 打开配置
- 打开 API 文档
- 重启服务
- 停止服务
- 开机自启动
- 退出

---

## 开机自启动

### 自动配置

运行 `windows/install.bat` 会自动配置开机自启动

### 手动配置

**方式一：启动文件夹**
```
Win+R → shell:startup
创建 Galaxy 快捷方式
```

**方式二：注册表**
```powershell
# 添加自启动项
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Galaxy /t REG_SZ /d "C:\Galaxy\windows\start_galaxy.bat"
```

---

## 访问地址

启动后访问：

| 界面 | 地址 |
|------|------|
| 控制面板 | http://localhost:8080 |
| 配置中心 | http://localhost:8080/config |
| 设备管理 | http://localhost:8080/devices |
| 记忆中心 | http://localhost:8080/memory |
| AI 路由 | http://localhost:8080/router |
| API Key | http://localhost:8080/api-keys |
| API 文档 | http://localhost:8080/docs |

---

## 待机模式

Galaxy 支持电脑待机：

1. 电脑待机时，Galaxy 服务暂停
2. 电脑唤醒后，Galaxy 自动恢复
3. 托盘图标会显示待机状态

### 配置待机

```powershell
# 允许网络唤醒
powercfg /setacvalueindex scheme_current sub_sleep hibernatetout 0

# 禁止休眠
powercfg /hibernate off
```

---

## 远程访问

### 使用 Tailscale

1. 安装 Tailscale: https://tailscale.com
2. 登录并连接网络
3. 获取 Tailscale IP: `tailscale ip`
4. 手机/平板访问: `http://[Tailscale-IP]:8080`

### 配置 Galaxy 使用 Tailscale

编辑 `.env`:
```
TAILSCALE_ENABLED=true
TAILSCALE_DOMAIN=your-machine-name
```

---

## 常见问题

### Q: 托盘图标不显示？

安装依赖：
```powershell
pip install pystray pillow
```

### Q: 端口被占用？

修改 `.env`:
```
WEB_UI_PORT=8081
```

### Q: 服务无法启动？

检查日志：
```powershell
type logs\galaxy.log
```

### Q: 如何卸载？

```powershell
# 删除自启动项
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Galaxy

# 删除虚拟环境
rmdir /s venv
```

---

## 文件结构

```
windows/
├── install.bat        # 安装脚本
├── quick_start.bat    # 快速启动
├── start_galaxy.bat   # 托盘启动
└── galaxy_tray.py     # 托盘程序
```
