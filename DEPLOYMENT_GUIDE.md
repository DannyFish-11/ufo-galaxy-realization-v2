'''
# UFO Galaxy 综合部署指南

**版本**: 1.0
**最后更新**: 2026-02-06
**作者**: Manus AI

---

## 1. 简介

UFO Galaxy 是一个 L4 级自主AI系统，具备物理设备控制、Android 集成和系统级 AI 交互层。本指南将详细介绍如何部署和配置 UFO Galaxy 系统，确保您能够成功启动并运行所有核心功能。

## 2. 系统需求

### 2.1. 硬件需求

| 组件 | 最低要求 |
| --- | --- |
| 处理器 | 4 核 CPU |
| 内存 | 16 GB RAM |
| 存储 | 100 GB SSD |
| GPU | NVIDIA GPU (8GB VRAM)，用于本地AI模型 |

### 2.2. 软件需求

- **操作系统**: Ubuntu 22.04 / Windows 10+ / macOS 12+
- **Python**: 3.8+
- **Docker & Docker Compose**: 用于数据库等外部服务
- **Git**: 用于克隆代码仓库
- **Android Studio**: 用于编译和部署 Android 应用

## 3. API 密钥和环境变量

系统运行需要配置多个外部服务的 API 密钥。您可以通过运行 `python main.py --setup` 启动交互式配置向导来配置它们。下表列出了所有必需和可选的密钥：

| 环境变量 | 服务 | 描述 |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI | 用于访问 GPT 系列模型 |
| `GEMINI_API_KEY` | Google Gemini | 用于访问 Gemini 系列模型 |
| `XAI_API_KEY` | Grok (xAI) | 用于访问 Grok 模型 |
| `PERPLEXITY_API_KEY` | Perplexity | 用于访问 Sonar 模型 |
| `DEEPSEEK_API_KEY` | DeepSeek | 用于访问 DeepSeek 模型 |
| `OPENROUTER_API_KEY` | OpenRouter | 用于访问多种模型的路由服务 |
| `SLACK_TOKEN` | Slack | 用于 Slack 消息收发 |
| `GITHUB_TOKEN` | GitHub | 用于访问 GitHub API |
| `NOTION_API_KEY` | Notion | 用于访问 Notion API |
| `QDRANT_URL` | Qdrant | 向量数据库的 URL |
| `QDRANT_API_KEY` | Qdrant | 向量数据库的 API Key |
| `REDIS_URL` | Redis | Redis 服务的 URL |
| `POSTGRES_URL` | PostgreSQL | PostgreSQL 数据库的 URL |
| `OCTOPRINT_URL` | OctoPrint | 3D 打印机控制服务的 URL |
| `OCTOPRINT_API_KEY` | OctoPrint | 3D 打印机控制服务的 API Key |

## 4. 安装与配置

### 4.1. 克隆代码仓库

```bash
# 服务端
git clone https://github.com/DannyFish-11/ufo-galaxy-realization.git
cd ufo-galaxy-realization

# Android 端
git clone https://github.com/DannyFish-11/ufo-galaxy-android.git
```

### 4.2. 运行配置向导

我们强烈建议使用交互式配置向导来完成初始设置。它会自动检测环境、验证密钥并生成配置文件。

```bash
python main.py --setup
```

向导将引导您完成所有必要步骤。如果您跳过向导，则需要手动创建和编辑 `config/unified_config.json` 文件。

## 5. 启动系统

配置完成后，您可以使用一键启动脚本来运行整个系统。脚本会自动安装所需的 Python 依赖项，并按正确的顺序启动所有 113 个节点。

- **在 Windows 上:**
  ```batch
  start.bat
  ```

- **在 Linux 或 macOS 上:**
  ```bash
  chmod +x start.sh
  ./start.sh
  ```

系统启动后，您可以通过浏览器访问 `http://localhost:8000` 查看状态监控和 Web UI。

## 6. 部署外部服务 (Docker)

为了实现完整功能，特别是知识库和长期记忆，您需要部署 PostgreSQL、Redis 和 Qdrant。我们提供了 `docker-compose.yml` 文件来简化此过程。

```bash
# 在 ufo-galaxy-realization 根目录运行
docker-compose up -d
```

## 7. 构建 Windows 可执行文件

如果您希望将系统打包为单个 Windows 可执行文件，可以使用 `build_exe.py` 脚本。

```bash
python build_exe.py
```

打包过程可能需要几分钟。完成后，您将在 `dist` 目录下找到 `ufo_galaxy.exe`。

## 8. Android 应用部署

1.  使用 Android Studio 打开 `ufo-galaxy-android` 项目。
2.  在 `app/src/main/java/com/ufogalaxy/Constants.kt` 文件中，将 `SERVER_URL` 修改为您的 UFO Galaxy 服务器地址。
3.  连接您的 Android 设备（需开启开发者模式和 USB 调试）。
4.  点击 "Run 'app'" 按钮来编译和安装应用。
5.  启动应用后，根据提示授予无障碍服务和悬浮窗权限。

## 9. 故障排除

- **节点启动失败**: 检查 `logs/` 目录下的节点日志，确认相关 API 密钥是否正确，以及端口是否被占用。
- **Web UI 无法访问**: 确保主服务已成功启动，并检查防火墙设置。
- **Android 应用无法连接**: 确认服务器地址配置正确，并且手机与服务器在同一网络下。

---

**[返回顶部](#ufo-galaxy-综合部署指南)**
'''
