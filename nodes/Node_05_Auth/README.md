# Node_05_Auth

认证授权中心，提供 JWT 令牌生成、验证和用户权限管理功能。

## 端口
8005

## 环境变量
- `JWT_SECRET`: JWT 签名密钥

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /auth/login` - 登录获取 Token
- `POST /auth/verify` - 验证 Token
- `POST /auth/refresh` - 刷新 Token
