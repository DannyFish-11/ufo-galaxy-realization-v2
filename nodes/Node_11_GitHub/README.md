# Node 11 - GitHub

FastAPI HTTP server providing GitHub REST API v3 integration for the Galaxy system.

## Port
`8011`

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | **Yes** | GitHub Personal Access Token |
| `GITHUB_DEFAULT_OWNER` | No | Default GitHub user/org for requests |
| `GITHUB_DEFAULT_REPO` | No | Default repository name for requests |

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | Status + rate limit info |
| POST | `/repos/info` | Get repository info |
| GET | `/repos/list?owner=...` | List repositories for a user/org |
| POST | `/issues/list` | List issues |
| POST | `/issues/create` | Create an issue |
| POST | `/issues/update` | Update an issue |
| POST | `/pulls/list` | List pull requests |
| POST | `/pulls/create` | Create a pull request |
| POST | `/commits/list` | List commits |
| GET | `/rate-limit` | Check GitHub API rate limit |

## Request Bodies

### POST /repos/info
```json
{"owner": "octocat", "repo": "Hello-World"}
```

### POST /issues/list
```json
{"owner": "octocat", "repo": "Hello-World", "state": "open", "labels": "bug", "limit": 30}
```

### POST /issues/create
```json
{"title": "Bug report", "body": "Description", "labels": ["bug"]}
```

### POST /issues/update
```json
{"issue_number": 42, "state": "closed"}
```

### POST /pulls/create
```json
{"title": "My PR", "body": "Description", "head": "feature-branch", "base": "main"}
```

### POST /commits/list
```json
{"sha": "main", "limit": 20}
```

## Running

```bash
pip install -r requirements.txt
GITHUB_TOKEN=ghp_xxx python main.py
```

If `GITHUB_TOKEN` is not set, all API endpoints return `503`.
