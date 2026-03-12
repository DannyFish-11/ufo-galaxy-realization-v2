"""
Node 78: DataValidator - JSON Schema & Pydantic data validation service
"""
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_78_DataValidator")
except Exception:
    PORT = int(os.getenv("PORT", "8078"))

STRICT_MODE = os.getenv("VALIDATOR_STRICT_MODE", "false").lower() == "true"

try:
    import jsonschema
    from jsonschema import validate as js_validate, Draft7Validator
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    jsonschema = None
    JSONSCHEMA_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 78 - DataValidator", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now()

# ---------------------------------------------------------------------------
# In-memory schema registry
# ---------------------------------------------------------------------------

_schemas: Dict[str, Dict[str, Any]] = {}
_validation_stats = {"total": 0, "passed": 0, "failed": 0}


# ---------------------------------------------------------------------------
# Built-in validation rules (pure Python, no jsonschema required)
# ---------------------------------------------------------------------------

_BUILTIN_RULES = {
    "not_empty": lambda v: v is not None and v != "" and v != [] and v != {},
    "is_string": lambda v: isinstance(v, str),
    "is_number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "is_boolean": lambda v: isinstance(v, bool),
    "is_list": lambda v: isinstance(v, list),
    "is_dict": lambda v: isinstance(v, dict),
    "is_email": lambda v: isinstance(v, str) and "@" in v and "." in v.split("@")[-1],
    "is_url": lambda v: isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")),
    "is_positive": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0,
    "is_non_negative": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0,
}


def _validate_against_schema(data: Any, schema: Dict[str, Any]) -> List[str]:
    """Validate data against a JSON schema. Returns list of error messages."""
    if not JSONSCHEMA_AVAILABLE:
        return ["jsonschema package not installed. Install with: pip install jsonschema"]
    errors = []
    validator = Draft7Validator(schema)
    for err in validator.iter_errors(data):
        errors.append(f"{'.'.join(str(p) for p in err.absolute_path) or 'root'}: {err.message}")
    return errors


def _apply_rules(data: Any, rules: List[str]) -> List[str]:
    """Apply built-in rules to data. Returns list of error messages."""
    errors = []
    for rule in rules:
        fn = _BUILTIN_RULES.get(rule)
        if fn is None:
            errors.append(f"Unknown rule: {rule}")
            continue
        if not fn(data):
            errors.append(f"Failed rule: {rule}")
    return errors


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ValidateRequest(BaseModel):
    data: Any
    schema_name: Optional[str] = None
    json_schema: Optional[Dict[str, Any]] = None
    rules: List[str] = []


class SchemaCreateRequest(BaseModel):
    name: str
    json_schema: Dict[str, Any]
    description: str = ""


class BatchValidateRequest(BaseModel):
    items: List[Any]
    schema_name: Optional[str] = None
    json_schema: Optional[Dict[str, Any]] = None
    rules: List[str] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "78",
        "name": "DataValidator",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    return {
        "status": "running",
        "node_id": "78",
        "name": "DataValidator",
        "uptime_seconds": round(uptime, 2),
        "configuration": {
            "strict_mode": STRICT_MODE,
            "jsonschema_available": JSONSCHEMA_AVAILABLE,
        },
        "metrics": {
            "schemas_registered": len(_schemas),
            "validations_total": _validation_stats["total"],
            "validations_passed": _validation_stats["passed"],
            "validations_failed": _validation_stats["failed"],
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/validate")
async def validate(request: ValidateRequest):
    """Validate data against a schema and/or built-in rules."""
    _validation_stats["total"] += 1
    errors = []

    # Resolve schema
    schema = request.json_schema
    if not schema and request.schema_name:
        stored = _schemas.get(request.schema_name)
        if not stored:
            raise HTTPException(status_code=404, detail=f"Schema '{request.schema_name}' not found")
        schema = stored["schema"]

    # JSON Schema validation
    if schema:
        errors.extend(_validate_against_schema(request.data, schema))

    # Built-in rule validation
    if request.rules:
        errors.extend(_apply_rules(request.data, request.rules))

    valid = len(errors) == 0
    if valid:
        _validation_stats["passed"] += 1
    else:
        _validation_stats["failed"] += 1

    return {
        "success": True,
        "valid": valid,
        "errors": errors,
        "error_count": len(errors),
    }


@app.get("/schema")
async def list_schemas():
    """List all registered schemas."""
    summaries = [
        {"name": name, "description": s["description"], "created_at": s["created_at"]}
        for name, s in _schemas.items()
    ]
    return {"success": True, "schemas": summaries, "total": len(summaries)}


@app.post("/schema")
async def create_schema(request: SchemaCreateRequest):
    """Register a new JSON schema."""
    if JSONSCHEMA_AVAILABLE:
        try:
            Draft7Validator.check_schema(request.json_schema)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON schema: {e}")

    _schemas[request.name] = {
        "name": request.name,
        "schema": request.json_schema,
        "description": request.description,
        "created_at": datetime.now().isoformat(),
    }
    return {"success": True, "name": request.name, "message": "Schema registered"}


@app.get("/schema/{name}")
async def get_schema(name: str):
    """Get a specific schema by name."""
    schema = _schemas.get(name)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema '{name}' not found")
    return {"success": True, "schema": schema}


@app.delete("/schema/{name}")
async def delete_schema(name: str):
    """Delete a schema."""
    if name not in _schemas:
        raise HTTPException(status_code=404, detail=f"Schema '{name}' not found")
    del _schemas[name]
    return {"success": True, "name": name, "message": "Schema deleted"}


@app.get("/rules")
async def list_rules():
    """List all built-in validation rules."""
    return {"success": True, "rules": list(_BUILTIN_RULES.keys())}


@app.post("/batch/validate")
async def batch_validate(request: BatchValidateRequest):
    """Validate a batch of items against a schema and/or rules."""
    # Resolve schema once
    schema = request.json_schema
    if not schema and request.schema_name:
        stored = _schemas.get(request.schema_name)
        if not stored:
            raise HTTPException(status_code=404, detail=f"Schema '{request.schema_name}' not found")
        schema = stored["schema"]

    results = []
    passed = 0
    failed = 0
    for i, item in enumerate(request.items):
        _validation_stats["total"] += 1
        errors = []
        if schema:
            errors.extend(_validate_against_schema(item, schema))
        if request.rules:
            errors.extend(_apply_rules(item, request.rules))
        valid = len(errors) == 0
        if valid:
            passed += 1
            _validation_stats["passed"] += 1
        else:
            failed += 1
            _validation_stats["failed"] += 1
        results.append({"index": i, "valid": valid, "errors": errors})

    return {
        "success": True,
        "total": len(request.items),
        "passed": passed,
        "failed": failed,
        "results": results,
    }


@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "validate":
        return await validate(ValidateRequest(**params))
    elif tool == "list_schemas":
        return await list_schemas()
    elif tool == "create_schema":
        return await create_schema(SchemaCreateRequest(**params))
    elif tool == "get_schema":
        return await get_schema(params.get("name", ""))
    elif tool == "delete_schema":
        return await delete_schema(params.get("name", ""))
    elif tool == "list_rules":
        return await list_rules()
    elif tool == "batch_validate":
        return await batch_validate(BatchValidateRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
