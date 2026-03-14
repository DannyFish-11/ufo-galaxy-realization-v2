# GitHub MCP/Skill Auto-Installer

Galaxy supports installing MCP tool servers and Skill plugins directly from
public or private GitHub repositories. Once installed, the tool or skill is
immediately registered and available for use by OpenClawd in the current and
all future sessions.

---

## Quick Start

### 1. Configure your GitHub token (optional but recommended)

Set `GITHUB_TOKEN` in your `.env` file or via the Dashboard **Settings** page:

```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxx
```

> ⚠️ **Security**: Never paste your token into chat. Always configure it via
> `.env` or the Dashboard. The installer explicitly refuses tokens from chat
> input.

Without a token, anonymous GitHub API access is used (60 requests/hour rate
limit). With a token, the limit rises to 5,000 req/h.

### 2. Install an addon via OpenClawd (chat)

You can ask OpenClawd directly:

```
Install the MCP tool from https://github.com/my-org/my-mcp-tool
```

OpenClawd will call the `github__install` built-in tool automatically.

Alternatively, use the JSON tool call format:

```json
{
  "tool": "github__install",
  "arguments": {
    "url": "https://github.com/my-org/my-mcp-tool",
    "ref": "main"
  }
}
```

### 3. Install via REST API

```http
POST /api/v1/github/install
Content-Type: application/json

{
  "url": "https://github.com/my-org/my-skill",
  "ref": "v1.2.0",
  "type": "skill",
  "dry_run": false
}
```

---

## Addon Manifest Contracts

### MCP Tool — `mcp_tool.json`

Place this file at the **root** of your GitHub repository:

```json
{
  "name": "my-tool",
  "description": "Short description shown to the LLM",
  "entrypoint": "server.py",
  "dependencies": ["requests", "httpx"],
  "env": {
    "MY_API_KEY": ""
  },
  "schema": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Search query" }
    },
    "required": ["query"]
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | ✅ | Unique tool identifier (used as MCP server ID) |
| `entrypoint` | ✅ | Startup file — `.py` (runs with Python) or `.js` (runs with Node) or a list `["node", "server.js"]` |
| `description` | — | Description shown to the LLM in tool schema |
| `dependencies` | — | Python package names or paths to install via `pip` |
| `env` | — | Environment variables to inject when starting the server |
| `schema` | — | JSON Schema for the tool's input; forwarded to LLM |

The entrypoint must implement the **stdio JSON-RPC MCP protocol**
(see [Model Context Protocol Spec](https://github.com/modelcontextprotocol/specification)).

### Skill — `skill.json`

Place this file at the **root** of your GitHub repository:

```json
{
  "name": "my-skill",
  "description": "What this skill does",
  "version": "1.0.0",
  "entrypoint": "handler.py",
  "dependencies": ["requests"],
  "parameters": [
    {
      "name": "query",
      "type": "string",
      "description": "Input query",
      "required": true
    }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | ✅ | Unique skill ID |
| `entrypoint` | ✅ | Python file containing `async def execute(**kwargs)` |
| `description` | — | Shown to the LLM |
| `version` | — | Semantic version string |
| `dependencies` | — | Python packages to install |
| `parameters` | — | Parameter schema list |

The entrypoint module must expose `async def execute(**kwargs) -> dict`.

---

## OpenClawd Built-in Tools

The following tools are always available in OpenClawd without any configuration:

| Tool | Description |
|------|-------------|
| `github__install` | Install MCP tool or Skill from GitHub URL |
| `github__uninstall` | Uninstall addon by name |
| `github__list` | List all installed GitHub addons |
| `github__status` | Show installer status (token, counts, dir) |

### `github__install`

```json
{
  "url": "https://github.com/owner/repo",
  "ref": "main",
  "type": "mcp",
  "dry_run": false
}
```

Arguments:
- `url` (**required**): GitHub HTTPS URL
- `ref`: Branch, tag, or commit SHA
- `type`: `"mcp"` | `"skill"` — auto-detected from manifest if omitted
- `dry_run`: `true` to validate URL without installing

### `github__uninstall`

```json
{ "name": "my-tool" }
```

### `github__list` / `github__status`

No arguments required.

---

## REST API Reference

All endpoints are available at the Galaxy core API server and the Dashboard
backend independently.

### `POST /api/v1/github/install`

Install an addon from GitHub.

**Request:**
```json
{
  "url": "https://github.com/owner/repo",
  "ref": "v1.0.0",
  "type": "mcp",
  "dry_run": false
}
```

**Response (success):**
```json
{
  "success": true,
  "name": "my-tool",
  "type": "mcp",
  "owner": "owner",
  "repo": "repo",
  "ref": "v1.0.0",
  "commit": "abc123def456...",
  "install_path": "data/github_addons/owner/repo/v1.0.0",
  "checksum": "sha256:...",
  "registration": { "success": true, "via": "mcp_loader" }
}
```

**Response (error):**
```json
{
  "success": false,
  "error": "Invalid GitHub HTTPS URL: ..."
}
```

### `POST /api/v1/github/uninstall`

```json
{ "name": "my-tool" }
```

### `GET /api/v1/github/list`

Returns all installed addons.

### `GET /api/v1/github/status`

```json
{
  "success": true,
  "token_configured": true,
  "install_dir": "data/github_addons",
  "allowlist": [],
  "blocklist": [],
  "total_installed": 3,
  "mcp_tools": 2,
  "skills": 1
}
```

---

## Security Configuration

### Allowlist

Only permit specific repositories:

```env
GITHUB_ALLOWLIST=my-org/*,trusted-user/mcp-*
```

Pattern syntax uses Unix shell glob (`fnmatch`). `owner/repo` format.
Leave empty to allow all repos.

### Blocklist

Block specific repositories (applied after allowlist):

```env
GITHUB_BLOCKLIST=untrusted-user/*,suspicious/repo
```

### Install Directory

Override the default `data/github_addons/` directory:

```env
GITHUB_INSTALL_DIR=/secure/path/to/addons
```

---

## Manifest File Location

Installed addon metadata is stored at:

```
data/github_addons/manifest.json
```

Each entry records: `name`, `type`, `owner`, `repo`, `ref`, `commit`,
`installed_at`, `install_path`, `checksum`, `tool_manifest`.

---

## Troubleshooting

### Token not configured

```
GITHUB_TOKEN not set — using anonymous access (60 req/h rate limit).
```

Set `GITHUB_TOKEN` in `.env` or Dashboard Settings. Never provide it in chat.

### Invalid URL

```
{"success": false, "error": "Invalid GitHub HTTPS URL: ..."}
```

Only HTTPS GitHub URLs are accepted. SSH URLs (`git@github.com:...`) are not
supported.

### Rate limit exceeded

```
{"success": false, "error": "HTTP 403 ..."}
```

Provide a `GITHUB_TOKEN` with appropriate repository access.

### Addon not found after install

Ensure the installed tool was registered: check `GET /api/v1/github/list`
and confirm `registration.success == true`. If the MCP server process failed
to start, check Galaxy logs for the server error.

---

## Example: Installing a Public MCP Tool

```bash
curl -X POST http://localhost:8000/api/v1/github/install \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/my-org/weather-mcp", "type": "mcp"}'
```

After installation, OpenClawd can immediately use:

```
Check the weather in Tokyo using the weather tool
```

OpenClawd will see the new `mcp__weather-mcp__get_weather` tool in its
function-calling schema and dispatch it transparently.
