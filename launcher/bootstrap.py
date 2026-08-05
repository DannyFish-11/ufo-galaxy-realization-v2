"""
launcher/bootstrap.py — Config bootstrap, system enums, and entrypoint utilities.

Responsibilities:
- SystemState and ServiceType enums
- SystemConfig dataclass (env/config loading, port resolution)
- _write_entrypoint: persist runtime/entrypoint.json for client discovery
- print_status / print_section display helpers (thin wrappers over core.ascii_art)

This module has no dependency on other launcher sub-modules so that it can be
imported first without circular-import risk.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Optional

# Project root is two levels up from this file (launcher/ → project root)
PROJECT_ROOT = Path(__file__).parent.parent.absolute()

logger = logging.getLogger("Galaxy")

# ---------------------------------------------------------------------------
# Display helpers — thin wrappers over the canonical core.ascii_art API
# ---------------------------------------------------------------------------

from core.ascii_art import print_section_header, print_status_row


def print_status(message: str, status: str = "info") -> None:
    """Print a single-line status message (no value column)."""
    print_status_row(message, status=status)


def print_section(title: str) -> None:
    """Print a section header."""
    print_section_header(title)


# ---------------------------------------------------------------------------
# System-state and service-type enums
# ---------------------------------------------------------------------------


class SystemState(Enum):
    """系统状态"""

    INITIALIZING = auto()
    LOADING_CONFIG = auto()
    STARTING_CORE = auto()
    STARTING_NODES = auto()
    STARTING_L4 = auto()
    STARTING_UI = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    ERROR = auto()


class ServiceType(Enum):
    """服务类型"""

    CORE = "core"  # 核心服务
    NODE = "node"  # 节点
    L4 = "l4"  # L4 增强
    API = "api"  # API 服务
    UI = "ui"  # UI 服务


# ---------------------------------------------------------------------------
# Runtime entrypoint writer
# ---------------------------------------------------------------------------


def _write_entrypoint(host: str, port: int) -> None:
    """向 runtime/entrypoint.json 写入当前 API 入口，供客户端读取。

    文件格式::

        {
            "api_base": "http://localhost:9000",
            "written_at": "2026-01-01T00:00:00Z"
        }

    - ``api_base``：客户端应连接的完整 URL 前缀（不含路径）。
    - ``written_at``：ISO-8601 UTC 时间戳，仅用于调试，客户端可忽略。

    每次启动均会覆盖写入；目录不存在时自动创建。
    ``host`` 为 ``0.0.0.0`` / 空字符串时，写入 ``localhost``（客户端可用地址）。
    """
    runtime_dir = PROJECT_ROOT / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    effective_host = "localhost" if host in ("0.0.0.0", "") else host
    payload = {
        "api_base": f"http://{effective_host}:{port}",
        "ws": f"ws://{effective_host}:{port}/ws",
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # 三端(手机/手表/桌面)发现网关的关键：除 localhost 外，写出【局域网 IP】与
    # 【Tailscale IP】的完整地址。手机/手表读本文件后:本地走 lan,异地走 tailscale,
    # 立刻连上,无需手填 IP。地址探测全 best-effort,失败不影响其余字段。
    lan_ip = _detect_lan_ip()
    if lan_ip:
        payload["lan"] = f"http://{lan_ip}:{port}"
        payload["lan_ws"] = f"ws://{lan_ip}:{port}/ws"
    ts_ip = _detect_tailscale_ip()
    if ts_ip:
        payload["tailscale"] = f"http://{ts_ip}:{port}"
        payload["tailscale_ws"] = f"ws://{ts_ip}:{port}/ws"
        # 异地优先走 Tailscale(加密 mesh + 对等中继加速)。
        payload["preferred"] = f"http://{ts_ip}:{port}"
    entrypoint_file = runtime_dir / "entrypoint.json"
    entrypoint_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def _detect_lan_ip() -> str:
    """探测本机【局域网】IP(best-effort)。用 UDP connect 技巧，不实际发包。"""
    import socket

    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("223.5.5.5", 80))  # 阿里 DNS，仅用于让 OS 选出出口网卡 IP
        ip = s.getsockname()[0]
        # 排除回环 / Tailscale 段(100.64/10)，只要真实 LAN
        if ip and not ip.startswith("127.") and not ip.startswith("100."):
            return ip
    except Exception:
        pass
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass
    return ""


def _detect_tailscale_ip() -> str:
    """探测本机 Tailscale IP(best-effort)。优先用已初始化的 TailscaleManager 单例，
    否则回退 ``tailscale ip -4``。拿不到返回空串。"""
    try:
        from core.tailscale_manager import TailscaleManager

        ip = TailscaleManager().get_tailscale_ip()
        if ip:
            return ip
    except Exception:
        pass
    try:
        import shutil
        import subprocess

        if shutil.which("tailscale"):
            r = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# System configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class SystemConfig:
    """系统配置"""

    # API keys
    openai_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    xai_api_key: str = ""
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""

    # Database
    database_url: str = ""
    redis_url: str = ""
    qdrant_url: str = ""

    # Service ports (defaults resolved from PortConfig / config/unified_ports.yaml)
    host: str = "0.0.0.0"
    web_ui_port: int = 9000
    device_api_port: int = 8766
    ufo_api_port: int = 8767

    def __post_init__(self) -> None:
        """从 PortConfig 加载端口默认值（如果可用）

        端口来源优先级（高→低）：
          1. 环境变量 GALAXY_UNIFIED_LAUNCHER_PORT / GALAXY_DEVICE_API_PORT / GALAXY_UFO_API_PORT
          2. config/unified_ports.yaml（统一端口事实来源）
          3. 内置硬编码默认值（9000 / 8766 / 8767）
        """
        try:
            from core.port_config import get_service_port

            self.web_ui_port = get_service_port("unified_launcher")
            self.device_api_port = get_service_port("device_api")
            self.ufo_api_port = get_service_port("ufo_api")
        except Exception:
            pass

    # Startup flags
    enable_l4: bool = True
    enable_nodes: bool = True
    enable_web_ui: bool = True
    enable_device_api: bool = True
    minimal_mode: bool = False

    @classmethod
    def load_from_env(cls) -> "SystemConfig":
        """从统一配置管理器加载配置（.env / config.json / config/unified_ports.yaml）"""
        instance = cls()

        try:
            from core.unified.config_manager import get_unified_config_manager  # noqa: PLC0415

            mgr = get_unified_config_manager()

            def _get_key(unified_key: str, env_key: str) -> str:
                v = mgr.get(unified_key) or mgr.get(unified_key.upper()) or os.environ.get(env_key, "")
                return v or ""

            instance.openai_api_key = _get_key("openai_api_key", "OPENAI_API_KEY")
            instance.gemini_api_key = _get_key("gemini_api_key", "GEMINI_API_KEY")
            instance.openrouter_api_key = _get_key("openrouter_api_key", "OPENROUTER_API_KEY")
            instance.xai_api_key = _get_key("xai_api_key", "XAI_API_KEY")
            instance.deepseek_api_key = _get_key("deepseek_api_key", "DEEPSEEK_API_KEY")
            instance.anthropic_api_key = _get_key("anthropic_api_key", "ANTHROPIC_API_KEY")
            instance.database_url = _get_key("database_url", "DATABASE_URL")
            instance.redis_url = _get_key("redis_url", "REDIS_URL")
            instance.qdrant_url = _get_key("qdrant_url", "QDRANT_URL")

            logger.info(
                "SystemConfig loaded via UnifiedConfigManager",
                extra={"event": "config_loaded", "source": "UnifiedConfigManager"},
            )
        except Exception as exc:
            logger.warning(
                "UnifiedConfigManager not available, falling back to direct .env and " "environment variable read: %s",
                exc,
            )
            env_file = PROJECT_ROOT / ".env"
            if env_file.exists():
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            os.environ[key.strip()] = value.strip()
            else:
                logger.warning(".env file not found. Copy .env.example to .env and configure: " "cp .env.example .env")
            instance.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
            instance.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
            instance.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
            instance.xai_api_key = os.environ.get("XAI_API_KEY", "")
            instance.deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            instance.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            instance.database_url = os.environ.get("DATABASE_URL", "")
            instance.redis_url = os.environ.get("REDIS_URL", "")
            instance.qdrant_url = os.environ.get("QDRANT_URL", "")

        return instance

    def _get_tailscale_ip(self) -> Optional[str]:
        """获取 Tailscale IPv4 地址"""
        try:
            import shutil

            tailscale_bin = shutil.which("tailscale")
            if not tailscale_bin:
                return None
            result = subprocess.run(
                [tailscale_bin, "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def has_llm_api(self) -> bool:
        """检查是否有可用的 LLM API"""
        return any(
            [
                self.openai_api_key,
                self.gemini_api_key,
                self.openrouter_api_key,
                self.xai_api_key,
                self.deepseek_api_key,
                self.anthropic_api_key,
            ]
        )

    def get_status_dict(self) -> Dict[str, Any]:
        """获取状态字典"""
        return {
            "llm_apis": {
                "openai": bool(self.openai_api_key),
                "gemini": bool(self.gemini_api_key),
                "openrouter": bool(self.openrouter_api_key),
                "xai": bool(self.xai_api_key),
                "deepseek": bool(self.deepseek_api_key),
                "anthropic": bool(self.anthropic_api_key),
            },
            "database": {
                "postgresql": bool(self.database_url),
                "redis": bool(self.redis_url),
                "qdrant": bool(self.qdrant_url),
            },
            "services": {
                "web_ui": self.enable_web_ui,
                "device_api": self.enable_device_api,
                "l4_enabled": self.enable_l4,
            },
            "network": {
                "tailscale_ip": self._get_tailscale_ip(),
            },
        }
