# Node 60 - Reinforcement Learning Engine

Q-learning and policy gradient reinforcement learning agent for adaptive decision-making.

## Port
Default port: **8160**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RL_LEARNING_RATE` | `0.01` | Learning rate for Q-learning updates |
| `RL_DISCOUNT_FACTOR` | `0.99` | Discount factor (gamma) for future rewards |
| `RL_EPSILON` | `0.1` | Epsilon for epsilon-greedy exploration |
| `NODE_ID` | `60` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `POST` | `/train` | Train agent on an episode |
| `POST` | `/predict` | Get action prediction for a state |
| `POST` | `/reset` | Reset agent state |
| `POST` | `/episode` | Run a complete training episode |
| `GET` | `/stats` | Training statistics |
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
docker build -t galaxy-node-60-reinforcementlearning .
docker run -p 8160:8160 galaxy-node-60-reinforcementlearning
```
