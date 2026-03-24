# Node 71 - Multi-Device Coordination

Multi-device coordination and task distribution service. Manages device registration, task scheduling, group broadcasts, and parallel execution across registered runtime devices.

> **Architecture note (PR-7):** Node_71 is an orchestration/coordination consumer. The canonical device source of truth is the UnifiedDeviceManager (UDM). Node_71 ingests the canonical device projection via `canonical_device_view_adapter` for local scheduling; it does not write back to UDM.

## Port
Default port: **8071**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_PORT` | `8071` | Listening port |
| `NODE_ID` | `71` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `POST` | `/devices` | Register a device |
| `GET` | `/devices` | List registered devices |
| `GET` | `/devices/{device_id}` | Get device details |
| `POST` | `/devices/{device_id}/heartbeat` | Record device heartbeat |
| `DELETE` | `/devices/{device_id}` | Unregister a device |
| `POST` | `/tasks` | Submit a task for distribution |
| `GET` | `/tasks` | List tasks |
| `GET` | `/tasks/{task_id}` | Get task status |
| `POST` | `/tasks/{task_id}/execute` | Execute a task on a device |
| `POST` | `/tasks/{task_id}/cancel` | Cancel a task |
| `POST` | `/groups` | Create a device group |
| `POST` | `/groups/{group_id}/broadcast` | Broadcast a command to a group |
| `POST` | `/execute/parallel` | Execute a task in parallel across devices |
| `POST` | `/execute/all` | Execute a task on all registered devices |

## Dependencies

See `requirements.txt` for full dependency list.

Depends on:
- `Node_01_OneAPI` — model inference backend

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker:

```bash
docker build -t galaxy-node-71-multidevicecoordination .
docker run -p 8071:8071 galaxy-node-71-multidevicecoordination
```

## Governance

`startup_policy: optional` — started if available; startup failure does not abort the system.
Promote to `active` after passing integration tests and health-check review (see `docs/NODE_ACTIVE_MANIFEST.md`).
