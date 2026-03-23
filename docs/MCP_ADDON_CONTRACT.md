# MCP Addon Contract

> **PR-004** — Canonical specification for GitHub-installable MCP addon repositories.

## Overview

Any GitHub repository that includes a compliant `mcp_tool.json` manifest at its
root can be installed into Galaxy / OpenClawd using `GitHubInstaller`.  Once
installed, the MCP server is launched via `MCPLoader`, its tools are
automatically injected into the **capability catalog** (`CapabilityRegistry`),
and OpenClawd can discover and call them without manual steps.

---

## `mcp_tool.json` Schema

Place this file at the **root** of your repository.

### Required fields

| Field        | Type              | Description                                                  |
|-------------|-------------------|--------------------------------------------------------------|
| `name`       | `string`          | Unique addon identifier. Must match `[A-Za-z0-9_-]+`.       |
| `entrypoint` | `string` or `list[string]` | How to launch the MCP stdio server (see examples). |

### Optional fields

| Field            | Type              | Default   | Description                                                       |
|-----------------|-------------------|-----------|-------------------------------------------------------------------|
| `schema_version` | `string`          | `"1"`     | Contract schema version. Must be `"1"`.                           |
| `description`    | `string`          | `""`      | Human-readable description of the addon.                          |
| `protocol`       | `string`          | `"mcp"`   | Communication protocol. Only `"mcp"` is supported.               |
| `transport`      | `string`          | `"stdio"` | Transport layer. Only `"stdio"` is supported.                     |
| `dependencies`   | `list[string]`    | `[]`      | Pip package specifiers installed before the server is launched.   |
| `env`            | `dict[str, str]`  | `{}`      | Environment variables injected into the server process.           |
| `capabilities`   | `dict`            | `{}`      | Optional metadata describing provided capabilities (informational).|
| `repository`     | `string`          | `""`      | Source repository URL (informational).                            |
| `author`         | `string`          | `""`      | Maintainer name or e-mail (informational).                        |
| `version`        | `string`          | `""`      | Addon release version, e.g. `"1.2.3"` (informational).           |

### Full example

```json
{
  "schema_version": "1",
  "name": "my-mcp-tool",
  "description": "Searches the web and returns structured results.",
  "protocol": "mcp",
  "transport": "stdio",
  "entrypoint": "server.py",
  "dependencies": ["httpx>=0.27", "pydantic>=2"],
  "env": {
    "SEARCH_API_KEY": ""
  },
  "capabilities": {
    "tools": ["web_search", "fetch_url"]
  },
  "repository": "https://github.com/example/my-mcp-tool",
  "author": "Jane Smith <jane@example.com>",
  "version": "0.3.1"
}
```

### `entrypoint` examples

```json
"entrypoint": "server.py"
```
→ launched as `python server.py`

```json
"entrypoint": ["node", "dist/server.js"]
```
→ launched as `node dist/server.js`

```json
"entrypoint": "bin/mcp-server"
```
→ launched as `bin/mcp-server` (executable)

---

## Validation Rules

Contract validation is performed by
`core.mcp_addon_contract.validate_mcp_addon_contract()`.  All violations are
collected before the error is raised so callers see the complete list.

| Rule | Violation message |
|------|-------------------|
| `name` present and non-empty | `'name' is required and must be a non-empty string` |
| `name` matches `[A-Za-z0-9_-]+` | `'name' must match [A-Za-z0-9_-]+, got …` |
| `entrypoint` present | `'entrypoint' is required` |
| `entrypoint` non-empty string or non-empty list of strings | various |
| `schema_version` == `"1"` | `'schema_version' … is not supported; expected "1"` |
| `protocol` == `"mcp"` when specified | `'protocol' must be "mcp", got …` |
| `transport` in `{"stdio"}` when specified | `'transport' must be one of ['stdio'], got …` |
| `dependencies` is list of strings when specified | `'dependencies' entries must all be strings` |
| `env` is `dict[str, str]` when specified | `'env' keys and values must all be strings` |
| `capabilities` is dict when specified | `'capabilities' must be a dict when present` |

Errors are surfaced as `MCPAddonContractError` (a subclass of `ValueError`)
with `.violations: list[str]` and `.error_code = "MCP_ADDON_CONTRACT_INVALID"`.

---

## Install Flow

```
GitHubInstaller.install(url)
  │
  ├─ 1. Validate GitHub URL + allowlist/blocklist
  ├─ 2. Download + extract repo archive
  ├─ 3. Detect addon type (mcp_tool.json → MCP, skill.json → Skill)
  ├─ 4. Parse mcp_tool.json
  ├─ 5. validate_mcp_addon_contract(manifest)   ← PR-004 enforcement gate
  │       └─ MCPAddonContractError → install aborts, structured error returned
  ├─ 6. Install Python dependencies (pip)
  ├─ 7. _register_mcp_tool(addon_dir, manifest)
  │       ├─ validate_mcp_addon_contract(manifest)   ← second gate in register path
  │       ├─ MCPLoader.load(name, command, env)       ← primary registration
  │       │       └─ on load success: _refresh_capability_registry()
  │       │               └─ CapabilityRegistry.refresh(force=True)
  │       └─ MCPDynamicGateway.register_external_tool()  ← fallback only
  ├─ 8. Record install metadata in manifest.json
  └─ 9. Return {"success": True, "name": …, "type": "mcp", "loader": "MCPLoader", …}
```

---

## Capability Catalog Integration

After a successful install:

1. **`MCPLoader`** registers the server and discovers its tools via the MCP
   `tools/list` RPC call.
2. **`MCPLoader._refresh_capability_registry()`** calls
   `CapabilityRegistry.refresh(force=True)`.
3. **`CapabilityRegistry._load_mcp()`** iterates all loaded MCP servers and
   creates a `CapabilityItem` for each tool, keyed as
   `mcp__{server_id}__{tool_name}`.
4. Each item is validated against `CapabilityContract` before being stored.
5. **`CapabilityResolver`** (the preferred consumer interface) returns these
   items to `OpenClawd` when it calls `collect_tools()`.

OpenClawd therefore discovers MCP tools **immediately** after install without
any restart or manual refresh.

---

## Programmatic Usage

### Install from GitHub

```python
from core.github_installer import github_installer

result = await github_installer.install("https://github.com/example/my-mcp-tool")
if result["success"]:
    print("Installed:", result["name"], "via", result["registration"]["loader"])
else:
    print("Failed:", result["error"])
    print("Violations:", result.get("violations", []))
```

### Validate a manifest directly

```python
from core.mcp_addon_contract import validate_mcp_addon_contract, MCPAddonContractError

try:
    contract = validate_mcp_addon_contract({
        "name": "my-tool",
        "entrypoint": "server.py",
    })
    print(contract.to_dict())
except MCPAddonContractError as exc:
    print("Invalid:", exc.violations)
```

### Check capability catalog after install

```python
from core.agent.capability_registry import get_capability_registry

reg = get_capability_registry()
await reg.refresh(force=True)

mcp_tools = [item for item in reg.list_tools() if item.source == "mcp"]
for tool in mcp_tools:
    print(tool.name, "—", tool.description)
```

---

## Error Reference

| Error / Key | Meaning |
|-------------|---------|
| `MCPAddonContractError` | `mcp_tool.json` failed schema validation |
| `"violations": [...]` | List of all validation rule violations |
| `"error_code": "MCP_ADDON_CONTRACT_INVALID"` | Machine-readable error code |
| `{"success": False, "error": "…", "violations": […]}` | Structured install failure dict |

---

## Compatibility

- **schema_version** `"1"` is the only supported version.  Future schema
  revisions will bump this value and update this document.
- The `allow_future_schema=True` parameter on `validate_mcp_addon_contract`
  accepts newer schema versions with a warning (intended for test
  environments).

---

## See Also

- `core/mcp_addon_contract.py` — Contract dataclass, validation, error types
- `core/github_installer.py` — Install lifecycle
- `core/mcp_loader.py` — MCP server process management
- `core/agent/capability_registry.py` — Capability catalog
- `core/unified/capability_contract.py` — Unified capability descriptor schema
- `core/unified/capability_resolver.py` — Consumer-facing resolver API
