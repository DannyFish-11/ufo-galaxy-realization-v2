# Node_16_Email

邮件服务节点，支持 SMTP 发送邮件、HTML 模板、附件和批量发送功能。

## 端口
8016

## 环境变量
- `SMTP_HOST`: SMTP 服务器（默认 smtp.gmail.com）
- `SMTP_PORT`: SMTP 端口（默认 587）
- `SMTP_USER`: 用户名/邮箱（必填）
- `SMTP_PASSWORD`: 密码/应用密码（必填）
- `SMTP_TLS`: 启用 TLS（默认 true）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /send` - 发送邮件
- `POST /send-template` - 发送模板邮件
- `GET /templates` - 列出可用模板
