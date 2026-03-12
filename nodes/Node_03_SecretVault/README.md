# Node_03_SecretVault

密钥保险箱节点，提供敏感配置的安全存储、读取和管理功能。

## 端口
8003

## 环境变量
- `VAULT_ENCRYPTION_KEY`: 加密密钥（可选）
- `VAULT_FILE_PATH`: 存储文件路径（默认内存模式）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /secrets` - 存储密钥
- `GET /secrets/{key}` - 读取密钥
- `DELETE /secrets/{key}` - 删除密钥
- `GET /secrets` - 列出所有密钥名（不含值）
