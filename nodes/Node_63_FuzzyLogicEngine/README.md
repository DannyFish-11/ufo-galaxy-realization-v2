# Node 63 - Fuzzy Logic Engine

Fuzzy logic inference engine supporting Mamdani and Sugeno inference methods with triangular, trapezoidal, and Gaussian membership functions.

## Port
Default port: **8163**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_ID` | `63` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `POST` | `/define_set` | Define a fuzzy membership set |
| `POST` | `/define_rule` | Define a fuzzy inference rule |
| `POST` | `/infer` | Run fuzzy inference |
| `POST` | `/mamdani` | Mamdani fuzzy inference |
| `POST` | `/sugeno` | Sugeno fuzzy inference |
| `POST` | `/defuzz` | Defuzzification |
| `GET` | `/sets` | List defined fuzzy sets |
| `GET` | `/rules` | List defined rules |
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
docker build -t galaxy-node-63-fuzzylogicengine .
docker run -p 8163:8163 galaxy-node-63-fuzzylogicengine
```
