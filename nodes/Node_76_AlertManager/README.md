# Node 76 - Alert Manager

Alert management with multi-channel notifications via SMTP email, Slack webhooks, and custom webhooks.

## Port
Default port: **8076**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | `` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USER` | `` | SMTP username |
| `SMTP_PASSWORD` | `` | SMTP password |
| `SMTP_FROM` | `` | Sender email address |
| `SLACK_WEBHOOK_URL` | `` | Slack webhook URL for notifications |
| `WEBHOOK_URL` | `` | Generic webhook URL |
| `NODE_ID` | `76` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `GET` | `/alerts` | List all alerts |
| `POST` | `/alert/create` | Create a new alert |
| `GET` | `/alert/{id}` | Get alert by ID |
| `DELETE` | `/alert/{id}` | Delete alert |
| `POST` | `/alert/{id}/resolve` | Resolve an alert |
| `POST` | `/alert/{id}/silence` | Silence an alert |
| `GET` | `/rules` | List notification rules |
| `POST` | `/rules` | Create notification rule |
| `POST` | `/notify` | Send notification |
| `POST` | `/mcp/call` | MCP tool dispatch |

## Dependencies

See `requirements.txt` for full dependency list.

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker:

```bash
docker build -t galaxy-node-76-alertmanager .
docker run -p 8076:8076 galaxy-node-76-alertmanager
```
