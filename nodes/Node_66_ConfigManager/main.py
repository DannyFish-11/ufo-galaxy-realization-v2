# -*- coding: utf-8 -*-

"""
Node_66_ConfigManager: 配置管理服务 (FastAPI)

管理系统配置文件，支持 JSON / YAML / INI 格式。
提供动态加载、访问、修改和保存配置的 REST API。
"""

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None

try:
    import configparser
except ImportError:
    configparser = None

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ---------------------------------------------------------------------------
# Port / CORS config (optional dependencies)
# ---------------------------------------------------------------------------

try:
    from core.port_config import get_service_port
    PORT = get_service_port("node_66") or 8066
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8066"))

try:
    from nodes.common.cors_config import get_cors_origins
    CORS_ORIGINS = get_cors_origins()
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    CORS_ORIGINS = ["*"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

KB_CONFIG_PATH = os.getenv("KB_CONFIG_PATH", "")
CONFIG_DIR = os.getenv("CONFIG_DIR", "./configs")

logging.basicConfig(
    level=logging.INFO,
    format="[Node_66] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Node_66_ConfigManager")

# ---------------------------------------------------------------------------
# Enums & Service
# ---------------------------------------------------------------------------

class ServiceStatus(Enum):
    STOPPED   = "stopped"
    RUNNING   = "running"
    DEGRADED  = "degraded"
    ERROR     = "error"


class ConfigFormat(Enum):
    JSON    = "json"
    YAML    = "yaml"
    INI     = "ini"
    UNKNOWN = "unknown"


@dataclass
class AppConfig:
    service_name: str = "Node_66_ConfigManager"
    version: str = "1.0.0"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8066
    supported_formats: list = field(default_factory=lambda: ["json", "yaml", "ini"])


class ConfigManagerService:
    """配置管理主服务"""

    def __init__(self, default_config: AppConfig = None):
        self.node_name = "Node_66_ConfigManager"
        self._app_config = default_config or AppConfig()
        self._status = ServiceStatus.STOPPED
        self._config_data: Dict[str, Any] = {}
        self._last_file_path: Optional[str] = None
        self._setup_logging()
        self._check_dependencies()
        self._status = ServiceStatus.RUNNING
        logger.info(f"{self.node_name} 服务初始化完成")

    def _setup_logging(self):
        self.logger = logging.getLogger(self.node_name)
        self.logger.setLevel(self._app_config.log_level.upper())

    def _check_dependencies(self):
        if "yaml" in self._app_config.supported_formats and yaml is None:
            self.logger.warning("PyYAML 未安装，YAML 格式不可用")
            self._app_config.supported_formats.remove("yaml")
        if "ini" in self._app_config.supported_formats and configparser is None:
            self.logger.warning("configparser 未找到，INI 格式不可用")
            self._app_config.supported_formats.remove("ini")

    def _detect_format(self, file_path: str) -> ConfigFormat:
        ext = os.path.splitext(file_path)[1].lower().strip(".")
        return {
            "json": ConfigFormat.JSON,
            "yaml": ConfigFormat.YAML,
            "yml":  ConfigFormat.YAML,
            "ini":  ConfigFormat.INI,
        }.get(ext, ConfigFormat.UNKNOWN)

    # -- parse helpers -------------------------------------------------------

    def _parse_json(self, content: str) -> Dict[str, Any]:
        return json.loads(content)

    def _parse_yaml(self, content: str) -> Dict[str, Any]:
        if yaml:
            return yaml.safe_load(content) or {}
        raise RuntimeError("PyYAML 未安装")

    def _parse_ini(self, content: str) -> Dict[str, Any]:
        if configparser:
            parser = configparser.ConfigParser()
            parser.read_string(content)
            return {s: dict(parser.items(s)) for s in parser.sections()}
        raise RuntimeError("configparser 不可用")

    # -- core operations -----------------------------------------------------

    def load_config(self, file_path: str) -> bool:
        """从文件加载配置"""
        fmt = self._detect_format(file_path)
        if fmt == ConfigFormat.UNKNOWN:
            raise ValueError(f"不支持的配置格式: {file_path}")
        if fmt.value not in self._app_config.supported_formats:
            raise ValueError(f"{fmt.value} 格式缺少依赖库")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        parser = getattr(self, f"_parse_{fmt.value}")
        self._config_data = parser(content)
        self._last_file_path = file_path
        logger.info(f"已从 '{file_path}' 加载配置")
        return True

    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点分隔嵌套键）"""
        try:
            value = self._config_data
            for k in key.split("."):
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def set_config(self, key: str, value: Any):
        """设置配置值（支持点分隔嵌套键，自动创建中间节点）"""
        keys = key.split(".")
        d = self._config_data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    def delete_config(self, key: str) -> bool:
        """删除配置键"""
        keys = key.split(".")
        d = self._config_data
        for k in keys[:-1]:
            if k not in d:
                return False
            d = d[k]
        if keys[-1] in d:
            del d[keys[-1]]
            return True
        return False

    def save_config(self, file_path: str, fmt: str = "json"):
        """保存配置到文件"""
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        if fmt == "json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self._config_data, f, indent=2, ensure_ascii=False)
        elif fmt == "yaml":
            if yaml is None:
                raise RuntimeError("PyYAML 未安装")
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(self._config_data, f, allow_unicode=True)
        else:
            raise ValueError(f"不支持的保存格式: {fmt}")
        logger.info(f"配置已保存到 '{file_path}'")

    def reload_config(self) -> bool:
        """从上次加载的文件重新加载"""
        if not self._last_file_path:
            raise RuntimeError("尚未加载过任何配置文件")
        return self.load_config(self._last_file_path)

    def list_keys(self) -> List[str]:
        """列出所有顶层配置键"""
        return list(self._config_data.keys())

    def export_all(self) -> Dict[str, Any]:
        return dict(self._config_data)

    @property
    def status(self) -> str:
        return self._status.value


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class LoadConfigRequest(BaseModel):
    path: str
    format: Optional[str] = None  # auto-detect if omitted

class SetConfigRequest(BaseModel):
    key: str
    value: Any

class SaveConfigRequest(BaseModel):
    path: str
    format: str = "json"

class MCPCallRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

service = ConfigManagerService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Node_66_ConfigManager FastAPI 启动")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    yield
    logger.info("Node_66_ConfigManager FastAPI 关闭")

app = FastAPI(
    title="Node_66_ConfigManager",
    description="配置管理服务 API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- routes ------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "node": "Node_66_ConfigManager", "timestamp": datetime.utcnow().isoformat()}


@app.get("/status")
def status():
    return {
        "status": service.status,
        "node": "Node_66_ConfigManager",
        "supported_formats": service._app_config.supported_formats,
        "loaded_keys_count": len(service._config_data),
        "last_file": service._last_file_path,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/configs")
def list_configs():
    """列出所有已加载的配置键"""
    return {"keys": service.list_keys(), "count": len(service._config_data)}


@app.post("/config/load")
def load_config(req: LoadConfigRequest):
    """从文件加载配置"""
    try:
        service.load_config(req.path)
        return {"success": True, "path": req.path, "keys": service.list_keys()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件不存在: {req.path}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/config/{key:path}")
def get_config(key: str):
    """获取配置值"""
    value = service.get_config(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"配置键不存在: {key}")
    return {"key": key, "value": value}


@app.post("/config/set")
def set_config(req: SetConfigRequest):
    """设置配置值"""
    try:
        service.set_config(req.key, req.value)
        return {"success": True, "key": req.key, "value": req.value}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/config/{key:path}")
def delete_config(key: str):
    """删除配置键"""
    deleted = service.delete_config(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"配置键不存在: {key}")
    return {"success": True, "key": key}


@app.post("/config/save")
def save_config(req: SaveConfigRequest):
    """保存配置到文件"""
    try:
        service.save_config(req.path, req.format)
        return {"success": True, "path": req.path, "format": req.format}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/config/reload")
def reload_config():
    """从磁盘重新加载配置"""
    try:
        service.reload_config()
        return {"success": True, "path": service._last_file_path, "keys": service.list_keys()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/config/export")
def export_config():
    """导出全部配置为 JSON"""
    return {"config": service.export_all(), "count": len(service._config_data)}


@app.post("/mcp/call")
def mcp_call(req: MCPCallRequest):
    """MCP 工具调用分发"""
    dispatch = {
        "load_config":   lambda p: {"result": service.load_config(p["path"])},
        "get_config":    lambda p: {"result": service.get_config(p["key"], p.get("default"))},
        "set_config":    lambda p: service.set_config(p["key"], p["value"]) or {"result": "ok"},
        "delete_config": lambda p: {"result": service.delete_config(p["key"])},
        "list_configs":  lambda p: {"result": service.list_keys()},
        "export_config": lambda p: {"result": service.export_all()},
        "save_config":   lambda p: service.save_config(p["path"], p.get("format", "json")) or {"result": "ok"},
        "reload_config": lambda p: {"result": service.reload_config()},
    }
    handler = dispatch.get(req.tool)
    if handler is None:
        raise HTTPException(status_code=404, detail=f"未知工具: {req.tool}")
    try:
        return handler(req.params)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
