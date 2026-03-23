# Skill Package Contract

> **PR-005** — Canonical specification for GitHub-installable Skill addon repositories.

## Overview

Any GitHub repository that includes a compliant `skill.json` manifest at its
root can be installed into Galaxy / OpenClawd using `GitHubInstaller`.  Once
installed, the Skill is loaded via `SkillLoader`, its capabilities are
automatically injected into the **capability catalog** (`CapabilityRegistry`),
and OpenClawd can discover and call them without manual steps.

---

## `skill.json` Schema

Place this file at the **root** of your repository.

### Required fields

| Field              | Type     | Description                                                                       |
|--------------------|----------|-----------------------------------------------------------------------------------|
| `id`               | `string` | Unique skill identifier.  Must match `[A-Za-z0-9_-]+`.                           |
| `name`             | `string` | Human-readable display name.  Must be non-empty.                                 |
| `handler_file`     | `string` | Relative path to the Python file containing the handler, e.g. `"handler.py"`.   |
| `handler_function` | `string` | Name of the callable inside `handler_file`, e.g. `"execute"`.                   |

### Optional fields

| Field            | Type           | Default     | Description                                                              |
|------------------|----------------|-------------|--------------------------------------------------------------------------|
| `schema_version` | `string`       | `"1"`       | Contract schema version.  Must be `"1"`.                                 |
| `description`    | `string`       | `""`        | Human-readable description of what the skill does.                       |
| `version`        | `string`       | `"1.0.0"`   | Skill release version (informational; distinct from `schema_version`).   |
| `parameters`     | `list[object]` | `[]`        | Parameter schema (see format below).                                     |
| `dependencies`   | `list[string]` | `[]`        | Pip package specifiers installed before the skill is first executed.     |
| `permissions`    | `list[string]` | `[]`        | Capability permission strings (informational; consumed by the catalog).  |
| `tags`           | `list[string]` | `[]`        | Taxonomy tags for capability resolver categorisation.                    |
| `repository`     | `string`       | `""`        | Source repository URL (informational).                                   |
| `author`         | `string`       | `""`        | Maintainer name or email (informational).                                |

### `parameters` entry format

Each entry in the `parameters` list must be a JSON object with at minimum a
`name` key.  Additional keys are optional:

| Key           | Type      | Description                              |
|---------------|-----------|------------------------------------------|
| `name`        | `string`  | **Required.** Parameter identifier.     |
| `type`        | `string`  | Parameter type hint (e.g. `"string"`).  |
| `description` | `string`  | Human-readable description.             |
| `required`    | `boolean` | Whether the parameter is mandatory.     |
| `default`     | any       | Default value when not provided.        |

### Full example

```json
{
  "schema_version": "1",
  "id": "web-search",
  "name": "Web Search",
  "description": "Search the web and return structured results.",
  "version": "0.3.1",
  "handler_file": "handler.py",
  "handler_function": "execute",
  "parameters": [
    {
      "name": "query",
      "type": "string",
      "description": "Search query string",
      "required": true
    },
    {
      "name": "max_results",
      "type": "integer",
      "description": "Maximum number of results to return",
      "required": false,
      "default": 5
    }
  ],
  "dependencies": ["httpx>=0.27", "pydantic>=2"],
  "permissions": ["internet"],
  "tags": ["search", "web", "productivity"],
  "repository": "https://github.com/example/web-search-skill",
  "author": "Jane Smith <jane@example.com>"
}
```

### `handler_file` / `handler_function` conventions

The `handler_file` is loaded as a Python module.  The `handler_function` is
called with the skill's input parameters as keyword arguments.  The callable
may be either a regular function or an `async def`:

```python
# handler.py
async def execute(query: str, max_results: int = 5) -> dict:
    """Perform a web search and return results."""
    ...
    return {"results": [...]}
```

---

## Validation Rules

Contract validation is performed by
`core.skill_package_contract.validate_skill_package_contract()`.  All
violations are collected before the error is raised so callers see the complete
list.

| Rule | Violation message |
|------|-------------------|
| `id` present and non-empty | `'id' is required and must be a non-empty string` |
| `id` matches `[A-Za-z0-9_-]+` | `'id' must match [A-Za-z0-9_-]+, got …` |
| `name` present and non-empty | `'name' is required and must be a non-empty string` |
| `handler_file` present and non-empty | `'handler_file' is required and must be a non-empty string` |
| `handler_function` present and non-empty | `'handler_function' is required and must be a non-empty string` |
| `schema_version` == `"1"` | `'schema_version' … is not supported; expected "1"` |
| `parameters` is list when specified | `'parameters' must be a list of objects when present` |
| each parameter entry is a dict with `name` | `'parameters[N]' must be a dict …` / `'parameters[N].name' is required …` |
| `dependencies` is list of strings when specified | `'dependencies' entries must all be strings` |
| `permissions` is list of strings when specified | `'permissions' entries must all be strings` |
| `tags` is list of strings when specified | `'tags' entries must all be strings` |

---

## Install Flow

```
User / API call
    │
    ▼
GitHubInstaller.install("https://github.com/owner/repo")
    │
    ├─ 1. Validate GitHub URL & check allow/block lists
    ├─ 2. Fetch / archive-download into data/github_addons/owner/repo/ref/
    ├─ 3. Detect addon type (skill.json present → "skill")
    ├─ 4. Read skill.json
    ├─ 5. Install Python dependencies (pip, per-addon venv)
    └─ 6. _register_skill(addon_dir, skill_manifest)
              │
              ├─ validate_skill_package_contract(skill_manifest)  ← PR-005 gate
              │       └─ raises SkillPackageContractError on violation
              │
              └─ SkillLoader.load(addon_dir)
                      │
                      ├─ validate_skill_package_contract(skill.json)  ← second gate
                      ├─ Load handler_file module
                      ├─ Create SkillInstance
                      ├─ _inject_skill_to_registry(skill_id)      ← capability catalog
                      └─ _refresh_capability_registry(skill_id)   ← fire-and-forget refresh
```

---

## Validation Enforcement Points

There are **two** enforcement points for the contract, ensuring that Skills are
always valid regardless of the install path:

1. **`GitHubInstaller._register_skill()`** — validates the raw manifest dict
   *before* calling `SkillLoader`.  Invalid packages are rejected immediately
   with a structured error; `SkillLoader` is never called.

2. **`SkillLoader.load()`** — re-validates `skill.json` from disk *before*
   creating a `SkillInstance`.  This ensures that Skills installed by any path
   (not just the GitHub installer) also pass the contract gate.

---

## Capability Catalog Integration

After a successful install, the Skill is automatically visible in the
capability catalog:

```
SkillLoader.load()
    └─ _inject_skill_to_registry(skill_id)
            └─ CapabilityRegistry.inject_skill(...)   ← immediate availability

    └─ _refresh_capability_registry(skill_id, "load")  ← async, best-effort
            └─ CapabilityRegistry.refresh(force=True)
```

OpenClawd queries the capability catalog at dispatch time.  The injected Skill
capability is immediately available — no restart required.

The Skill appears in the catalog with:
- **source**: `"skill"`
- **source_id**: the `id` from `skill.json`
- **name**: `"skill__<id>"`
- **description**: `[Skill] <description>`
- **parameters**: derived from `handler_file` module's MCP tool schema

---

## How Skill Packages Become Callable Capabilities

```
skill.json           →  SkillPackageContract (validated)
                     →  SkillInstance (loaded by SkillLoader)
                     →  CapabilityItem in CapabilityRegistry  (source="skill")
                     →  CapabilityContract (CapabilityResolver)
                     →  OpenClawd._dispatch_tool_call("skill__<id>", ...)
                     →  SkillRegistry.call(skill_name, inputs)
```

The chain guarantees that:
- Every callable Skill has passed the `skill.json` contract gate.
- Every capability entry in the registry has a valid `CapabilityContract`.
- OpenClawd can discover and invoke Skills via the standard tool-call path.

---

## Python API

```python
from core.skill_package_contract import (
    SkillPackageContract,
    SkillPackageContractError,
    validate_skill_package_contract,
    is_valid_skill_package_contract,
    build_skill_package_contract_summary,
)

# Validate a raw dict (e.g. parsed skill.json)
try:
    contract = validate_skill_package_contract(raw_manifest)
    print(contract.id, contract.handler_file, contract.handler_function)
except SkillPackageContractError as exc:
    print("Invalid:", exc.violations)

# Quick boolean check
ok = is_valid_skill_package_contract(raw_manifest)

# Observability summary
summary = build_skill_package_contract_summary(contract)
```

---

## Error Handling

All validation errors are returned as structured dicts in the API response:

```json
{
  "success": false,
  "error": "skill.json contract validation failed: [\"'handler_file' is required...\"]",
  "violations": ["'handler_file' is required and must be a non-empty string"],
  "error_code": "SKILL_PACKAGE_CONTRACT_INVALID"
}
```

`error_code` is always `"SKILL_PACKAGE_CONTRACT_INVALID"` for contract
violations.

---

## Related Documents

- [MCP Addon Contract](MCP_ADDON_CONTRACT.md) — equivalent contract for MCP server addons (PR-004)
- [GitHub Addons](GITHUB_ADDONS.md) — general GitHub addon install guide
- `core/skill_package_contract.py` — contract implementation
- `core/skill_loader.py` — SkillLoader (contract enforcement point 2)
- `core/github_installer.py` — GitHubInstaller (contract enforcement point 1)
- `core/agent/capability_registry.py` — capability catalog
