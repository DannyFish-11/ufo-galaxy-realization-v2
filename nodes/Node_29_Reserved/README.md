# Node 29 - Extension Registry

Port: **8029**

HTTP-based extension/hook system where other nodes can register callback URLs and receive event notifications.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NODE_29_NAME` | `ExtensionRegistry` | Display name |
| `MAX_HOOK_RETRIES` | `3` | Number of delivery retries per extension |

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | Node stats |
| POST | `/extensions/register` | Register extension with callback URL |
| DELETE | `/extensions/{name}` | Unregister extension |
| GET | `/extensions` | List all extensions |
| GET | `/extensions/{name}` | Get extension details |
| POST | `/events/dispatch` | Dispatch event to all subscribed extensions |
| POST | `/events/dispatch/{event_type}` | Shorthand event dispatch |
| GET | `/events/history` | Recent event history (default limit=50) |
| POST | `/extensions/ping` | Ping extension callback URL |

## Extension Registration

```json
POST /extensions/register
{
  "name": "MyService",
  "version": "1.0.0",
  "callback_url": "http://localhost:9000/events",
  "events": ["user.created", "order.placed"]
}
```

Leave `events` as `[]` to subscribe to all events.

## Event Dispatch

```json
POST /events/dispatch
{
  "event_type": "user.created",
  "payload": {"user_id": 42, "email": "user@example.com"}
}
```

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```
