# Galaxy 7×24 小时运行方案

## 问题分析

**目标**: 保证 Galaxy 系统 7×24 小时运行，即使在 Windows 电脑上

**挑战**:
1. 电脑可能休眠/关机
2. 断电后无法自动开机
3. 需要远程唤醒能力

---

## 方案一：纯软件方案 (推荐入门)

### 1. Windows 服务 + 开机自启

```powershell
# 使用 NSSM 将 Galaxy 注册为 Windows 服务
# 下载 NSSM: https://nssm.cc/download

# 安装服务
nssm install Galaxy "C:\Python310\python.exe" "C:\Galaxy\run_galaxy.py"
nssm set Galaxy AppDirectory "C:\Galaxy"
nssm set Galaxy DisplayName "Galaxy L4 AI System"
nssm set Galaxy Description "Galaxy - L4 级自主性智能系统"
nssm set Galaxy Start SERVICE_AUTO_START

# 启动服务
nssm start Galaxy
```

### 2. 阻止电脑休眠

**方案 A: PowerToys Awake (微软官方)**
```
# 安装 PowerToys
winget install Microsoft.PowerToys

# 启用 Awake 模块
# 设置为 "Keep screen on indefinitely"
```

**方案 B: Caffeine (模拟按键)**
```python
# 创建 keep_awake.py
import time
import pyautogui

while True:
    pyautogui.press('shift')
    time.sleep(60)  # 每60秒按一次
```

### 3. BIOS 设置

```
1. Wake-on-LAN (网络唤醒)
   - BIOS → Power Management → Wake-on-LAN → Enable
   
2. Auto Power On (定时开机)
   - BIOS → Power Management → RTC Alarm → Enable
   - 设置每天开机时间
   
3. Power On After Power Loss (断电恢复)
   - BIOS → Power Management → Power On After Power Loss → Enable
```

---

## 方案二：智能插座 + Wake-on-LAN (推荐)

### 硬件需求
- 智能插座 (小米/TP-Link/涂鸦，约 30-50 元)
- 支持远程控制的 App

### 工作原理
```
┌─────────────────────────────────────────────────────────────┐
│                    智能插座唤醒流程                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  手机 App ──→ 智能插座通电 ──→ 电脑开机 ──→ Galaxy 启动     │
│                                                             │
│  详细步骤:                                                  │
│  1. 手机打开智能插座 App                                    │
│  2. 远程打开插座电源                                        │
│  3. 电脑 BIOS 设置通电自动开机                              │
│  4. Windows 自动登录                                        │
│  5. Galaxy 服务自动启动                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 配置步骤

**1. BIOS 设置**
```
Power On After Power Loss = Enable (断电恢复后自动开机)
```

**2. Windows 自动登录**
```
# 运行 netplwiz
# 取消勾选 "要使用本计算机，用户必须输入用户名和密码"
```

**3. Galaxy 开机自启**
```
# 将启动脚本放入启动文件夹
shell:startup
```

---

## 方案三：USB 远程开机设备 (最小体积)

### 1. 向日葵开机棒 C1 Pro
- **价格**: 约 99 元
- **大小**: 约 5cm × 3cm
- **接口**: USB + 网线
- **功能**: 远程开关机、远程桌面

### 2. 小米智能插座 2 (蓝牙网关版)
- **价格**: 约 49 元
- **大小**: 约 5cm × 5cm
- **接口**: 插座
- **功能**: 远程控制、电量统计

### 3. TP-Link 智能插座
- **价格**: 约 39 元
- **大小**: 约 4cm × 4cm
- **功能**: 远程控制、定时

### 4. DIY 方案: ESP32/ESP8266
- **价格**: 约 20-30 元
- **大小**: 约 5cm × 3cm
- **接口**: USB
- **功能**: 自定义远程开机

---

## 方案四：最小硬件方案 (推荐)

### ESP32 USB 远程开机器

**硬件清单**:
| 组件 | 价格 | 说明 |
|------|------|------|
| ESP32 开发板 | 15-25 元 | WiFi 模块 |
| 继电器模块 | 3-5 元 | 控制电源 |
| USB 公头 | 2 元 | 连接电脑 |
| 杜邦线 | 1 元 | 连接线 |
| **总计** | **约 25-35 元** | |

**工作原理**:
```
┌─────────────────────────────────────────────────────────────┐
│                   ESP32 远程开机器                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  手机 App ──→ ESP32 (WiFi) ──→ 继电器 ──→ 短接电源键 ──→ 开机│
│                                                             │
│  或:                                                        │
│                                                             │
│  手机 App ──→ ESP32 (WiFi) ──→ 模拟 USB 唤醒信号 ──→ 开机   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**代码示例 (ESP32)**:
```cpp
#include <WiFi.h>
#include <WebServer.h>

const char* ssid = "YourWiFi";
const char* password = "YourPassword";

WebServer server(80);
const int relayPin = 4;  // 继电器控制引脚

void setup() {
  Serial.begin(115200);
  pinMode(relayPin, OUTPUT);
  digitalWrite(relayPin, HIGH);
  
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
  
  server.on("/power_on", []() {
    // 短接电源键 0.5 秒
    digitalWrite(relayPin, LOW);
    delay(500);
    digitalWrite(relayPin, HIGH);
    server.send(200, "text/plain", "Power ON signal sent");
  });
  
  server.begin();
}

void loop() {
  server.handleClient();
}
```

**使用方式**:
```
手机浏览器访问: http://ESP32-IP/power_on
```

---

## 方案五：树莓派唤醒服务器 (最稳定)

### 硬件需求
- 树莓派 Zero 2 W (约 200 元)
- 或 Orange Pi Zero (约 100 元)

### 工作原理
```
┌─────────────────────────────────────────────────────────────┐
│                   树莓派唤醒服务器                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  树莓派 (7×24 运行)                                         │
│     │                                                       │
│     ├──→ Wake-on-LAN 唤醒电脑                               │
│     ├──→ 监控电脑状态                                       │
│     ├──→ 自动重启服务                                       │
│     └──→ 提供 Web 管理界面                                  │
│                                                             │
│  优势:                                                      │
│  - 树莓派功耗极低 (约 2-3W)                                 │
│  - 可 7×24 运行                                             │
│  - 可监控多台设备                                           │
│  - 可作为 Galaxy 的备用运行环境                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 配置步骤

**1. 树莓派安装 Wake-on-LAN 工具**
```bash
sudo apt install wakeonlan

# 唤醒命令
wakeonlan AA:BB:CC:DD:EE:FF  # 电脑 MAC 地址
```

**2. 创建 Web 界面**
```python
# wake_server.py
from flask import Flask, request
import os

app = Flask(__name__)

MAC_ADDRESS = "AA:BB:CC:DD:EE:FF"  # 电脑 MAC

@app.route("/wake")
def wake():
    os.system(f"wakeonlan {MAC_ADDRESS}")
    return "Wake signal sent!"

@app.route("/status")
def status():
    # 检查电脑是否在线
    response = os.popen(f"ping -c 1 192.168.1.100").read()
    return {"online": "1 received" in response}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

---

## 方案对比

| 方案 | 成本 | 体积 | 稳定性 | 断电恢复 | 推荐度 |
|------|------|------|--------|----------|--------|
| 纯软件 | 0 元 | - | ⭐⭐ | ❌ | ⭐⭐⭐ |
| 智能插座 | 30-50 元 | 小 | ⭐⭐⭐⭐ | ✅ | ⭐⭐⭐⭐⭐ |
| 向日葵开机棒 | 99 元 | 中 | ⭐⭐⭐⭐ | ✅ | ⭐⭐⭐⭐ |
| ESP32 DIY | 25-35 元 | 最小 | ⭐⭐⭐ | ✅ | ⭐⭐⭐⭐ |
| 树莓派 | 100-200 元 | 小 | ⭐⭐⭐⭐⭐ | ✅ | ⭐⭐⭐⭐⭐ |

---

## 推荐方案

### 最简单: 智能插座 + BIOS 设置
```
1. 购买小米智能插座 (约 49 元)
2. BIOS 设置 "Power On After Power Loss"
3. Windows 设置自动登录 + 开机自启
4. 手机 App 远程控制
```

### 最小体积: ESP32 DIY
```
1. 购买 ESP32 开发板 (约 20 元)
2. 连接继电器模块
3. 烧录代码
4. 手机浏览器唤醒
```

### 最稳定: 树莓派
```
1. 购买树莓派 Zero 2 W (约 200 元)
2. 安装 Wake-on-LAN 服务
3. 7×24 运行，监控电脑状态
4. 可作为 Galaxy 备用运行环境
```

---

## 完整配置清单

### Windows 电脑端

```powershell
# 1. BIOS 设置
Power On After Power Loss = Enable
Wake-on-LAN = Enable

# 2. Windows 设置
# 自动登录
netplwiz → 取消密码要求

# 3. 安装 NSSM
winget install NSSM

# 4. 注册 Galaxy 服务
nssm install Galaxy "C:\Python310\python.exe" "C:\Galaxy\run_galaxy.py"
nssm set Galaxy Start SERVICE_AUTO_START
nssm start Galaxy

# 5. 阻止休眠
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

### 智能插座端

```
1. 安装米家 App
2. 添加智能插座
3. 设置场景: 通电后自动开机
4. 远程控制开关
```

---

## 总结

**推荐方案**: 智能插座 + BIOS 设置

**理由**:
1. 成本低 (约 49 元)
2. 体积小 (插座大小)
3. 配置简单
4. 支持断电恢复
5. 手机 App 远程控制

**如果需要更小体积**: ESP32 DIY 方案 (约 25 元)

**如果需要最稳定**: 树莓派方案 (约 200 元)
