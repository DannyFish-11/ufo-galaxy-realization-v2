# UFO Galaxy 系统 - API配置报告

## 📋 执行摘要

本报告详细记录了UFO Galaxy系统的所有外部API和服务依赖配置。配置文件已创建并保存到指定目录。

---

## 📁 生成的配置文件

| 文件路径 | 说明 | 大小 |
|----------|------|------|
| `/mnt/okcomputer/output/.env.example` | 环境变量配置模板 | 5.7 KB |
| `/mnt/okcomputer/output/docker-compose.yml` | Docker Compose部署配置 | 7.9 KB |
| `/mnt/okcomputer/output/deploy.sh` | 一键部署脚本 | 8.8 KB |
| `/mnt/okcomputer/output/README.md` | 项目说明文档 | 3.4 KB |
| `/mnt/okcomputer/output/docs/API_CONFIGURATION_GUIDE.md` | 详细API配置指南 | 16 KB |
| `/mnt/okcomputer/output/monitoring/prometheus.yml` | Prometheus监控配置 | 1.2 KB |
| `/mnt/okcomputer/output/monitoring/grafana/datasources/prometheus.yml` | Grafana数据源配置 | 0.4 KB |

---

## 🔑 1. LLM API Keys 配置

### 1.1 已配置的API提供商

| 提供商 | 环境变量 | 状态 | 获取地址 |
|--------|----------|------|----------|
| OpenAI | `OPENAI_API_KEY` | ⏳ 待配置 | https://platform.openai.com/api-keys |
| Anthropic | `ANTHROPIC_API_KEY` | ⏳ 待配置 | https://console.anthropic.com/settings/keys |
| Groq | `GROQ_API_KEY` | ⏳ 待配置 | https://console.groq.com/keys |
| 智谱AI | `ZHIPU_API_KEY` | ⏳ 待配置 | https://open.bigmodel.cn/usercenter/apikeys |
| OpenRouter | `OPENROUTER_API_KEY` | ⏳ 待配置 | https://openrouter.ai/keys |
| Google Gemini | `GEMINI_API_KEY` | ⏳ 待配置 | https://aistudio.google.com/app/apikey |
| xAI | `XAI_API_KEY` | ⏳ 待配置 | https://x.ai/api |
| DeepSeek | `DEEPSEEK_API_KEY` | ⏳ 待配置 | https://platform.deepseek.com/api_keys |
| Together AI | `TOGETHER_API_KEY` | ⏳ 待配置 | https://api.together.xyz/settings/api-keys |
| Perplexity | `PERPLEXITY_API_KEY` | ⏳ 待配置 | https://www.perplexity.ai/settings/api |

### 1.2 推荐优先级

1. **高优先级** (必须配置):
   - OpenAI API - 功能最全面，GPT-4系列性能优秀
   - Anthropic Claude - 推理能力强，上下文窗口大
   - Groq - 速度快，性价比高

2. **中优先级** (推荐配置):
   - 智谱AI - 中文场景优化
   - OpenRouter - 统一网关，灵活切换
   - DeepSeek - 代码能力强

3. **可选配置**:
   - Google Gemini - 多模态能力
   - Together AI - 开源模型丰富
   - Perplexity - 实时搜索增强

---

## 🔧 2. 工具API Keys 配置

| 服务 | 环境变量 | 用途 | 获取地址 | 免费额度 |
|------|----------|------|----------|----------|
| Brave Search | `BRAVE_API_KEY` | 网络搜索 | https://api.search.brave.com/app/keys | 2000次/月 |
| OpenWeather | `OPENWEATHER_API_KEY` | 天气查询 | https://home.openweathermap.org/api_keys | 100万次/月 |
| PixVerse | `PIXVERSE_API_KEY` | 视频生成 | https://app.pixverse.ai/api-keys | 需申请 |

---

## 🗄️ 3. 数据库服务配置

### 3.1 Neo4j 图数据库

```yaml
配置项:
  NEO4J_URI: bolt://neo4j:7687
  NEO4J_USER: neo4j
  NEO4J_PASSWORD: neo4j123

端口映射:
  - 7474: HTTP/Web界面
  - 7687: Bolt协议/驱动连接

访问地址:
  - Web UI: http://localhost:7474
  - Bolt: bolt://localhost:7687

默认账号: neo4j / neo4j123
```

### 3.2 Qdrant 向量数据库

```yaml
配置项:
  QDRANT_URL: http://qdrant:6333
  QDRANT_API_KEY: (可选)

端口映射:
  - 6333: REST API
  - 6334: gRPC

访问地址:
  - REST API: http://localhost:6333
  - gRPC: localhost:6334
```

---

## 📦 4. 对象存储配置 (MinIO)

```yaml
配置项:
  MINIO_ENDPOINT: minio:9000
  MINIO_ACCESS_KEY: minioadmin
  MINIO_SECRET_KEY: minioadmin123
  MINIO_BUCKET: ufo-galaxy
  MINIO_USE_SSL: false

端口映射:
  - 9000: API端口
  - 9001: Web Console

访问地址:
  - API: http://localhost:9000
  - Console: http://localhost:9001

默认账号: minioadmin / minioadmin123
```

---

## 🌐 5. WebRTC 配置

```yaml
配置项:
  STUN_SERVERS: stun.l.google.com:19302,stun1.l.google.com:19302
  TURN_SERVER: turn:your-turn-server.com:3478
  TURN_USERNAME: your_turn_username
  TURN_CREDENTIAL: your_turn_password
  EXTERNAL_IP: your_external_ip

端口映射:
  - 3478: TURN/STUN (TCP/UDP)
  - 5349: TURNS (TLS)
  - 49152-65535: 中继端口范围
```

---

## 🤖 6. 本地模型配置

### 6.1 Ollama

```yaml
配置项:
  OLLAMA_URL: http://ollama:11434

端口映射:
  - 11434: API端口

访问地址: http://localhost:11434

推荐模型:
  - llama3.2: Meta Llama 3.2
  - qwen2.5: 阿里通义千问
  - mistral: Mistral AI
  - codellama: 代码专用
```

### 6.2 vLLM

```yaml
配置项:
  VLLM_URL: http://vllm:8000

端口映射:
  - 8000: API端口 (OpenAI兼容)

访问地址: http://localhost:8000
```

---

## 🚀 7. 部署步骤

### 7.1 快速部署 (推荐)

```bash
# 1. 复制环境配置
cp .env.example .env

# 2. 编辑配置文件
nano .env

# 3. 一键部署
./deploy.sh all
```

### 7.2 分步部署

```bash
# 仅部署数据库
docker-compose up -d neo4j qdrant minio redis

# 仅部署监控
docker-compose up -d prometheus grafana jaeger

# 部署Ollama
docker-compose up -d ollama
```

---

## 🧪 8. 测试连通性

### 8.1 数据库服务测试

```bash
# Neo4j
docker exec -it ufo-neo4j cypher-shell -u neo4j -p neo4j123
MATCH (n) RETURN count(n);

# Qdrant
curl http://localhost:6333/healthz

# MinIO
curl http://localhost:9000/minio/health/live

# Redis
docker exec -it ufo-redis redis-cli ping
```

### 8.2 LLM API测试

```bash
# OpenAI
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# Anthropic
curl https://api.anthropic.com/v1/models \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01"

# Groq
curl https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY"
```

---

## 📊 9. 监控服务访问

| 服务 | 地址 | 账号 | 用途 |
|------|------|------|------|
| Grafana | http://localhost:3000 | admin/admin123 | 可视化仪表板 |
| Prometheus | http://localhost:9090 | - | 指标收集 |
| Jaeger | http://localhost:16686 | - | 链路追踪 |

---

## ⚠️ 10. 安全注意事项

1. **API Key安全**:
   - 不要将真实的API Keys提交到Git仓库
   - 使用 `.env` 文件并在 `.gitignore` 中排除
   - 生产环境使用密钥管理服务

2. **数据库安全**:
   - 修改默认密码
   - 限制网络访问
   - 启用SSL/TLS

3. **MinIO安全**:
   - 修改默认访问密钥
   - 启用HTTPS
   - 配置访问策略

---

## 📚 11. 参考文档

- [OpenAI API文档](https://platform.openai.com/docs)
- [Anthropic API文档](https://docs.anthropic.com/)
- [Neo4j文档](https://neo4j.com/docs/)
- [Qdrant文档](https://qdrant.tech/documentation/)
- [MinIO文档](https://min.io/docs/)
- [Ollama文档](https://github.com/ollama/ollama)

---

## ✅ 12. 配置检查清单

- [ ] 复制 `.env.example` 到 `.env`
- [ ] 配置 OpenAI API Key
- [ ] 配置 Anthropic API Key
- [ ] 配置 Groq API Key
- [ ] 配置其他LLM API Keys (可选)
- [ ] 配置工具API Keys (可选)
- [ ] 修改数据库默认密码
- [ ] 修改MinIO默认密钥
- [ ] 配置WebRTC外部IP
- [ ] 运行 `./deploy.sh all` 部署服务
- [ ] 验证所有服务正常运行

---

## 📞 13. 故障排除

### 常见问题

1. **Docker服务无法启动**:
   ```bash
   # 检查Docker状态
   docker ps
   docker-compose logs [service-name]
   ```

2. **端口冲突**:
   ```bash
   # 检查端口占用
   netstat -tlnp | grep [port]
   # 修改docker-compose.yml中的端口映射
   ```

3. **API Key无效**:
   ```bash
   # 验证API Key
   curl -H "Authorization: Bearer $API_KEY" [api-endpoint]
   ```

---

**报告生成时间**: 2024年
**配置文件版本**: v1.0.0
**作者**: UFO Galaxy Deployment Team
