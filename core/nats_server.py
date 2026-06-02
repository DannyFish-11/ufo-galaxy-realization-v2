"""
core.nats_server — 内置NATS服务器
==================================
PR-NATS-CORE: NATS是核心组件，系统启动时自动启动。
不需要额外部署NATS服务器。
"""
import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("Galaxy.NATSServer")


class EmbeddedNATSServer:
    """内置NATS服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 4222):
        self.host = host
        self.port = port
        self.process = None
        self.data_dir = Path.home() / ".galaxy" / "nats"

    async def start(self) -> bool:
        """启动内置NATS服务器"""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 检查nats-server
        if not shutil.which("nats-server"):
            logger.info("nats-server not found, attempting auto-install...")
            if not await self._install():
                logger.warning("nats-server not available — cross-device bus disabled. "
                               "Install nats-server manually or set GALAXY_NATS_ENABLED=false")
                return False

        # 启动
        try:
            self.process = subprocess.Popen(
                ["nats-server", "--addr", self.host, "--port", str(self.port),
                 "--jetstream", "--store_dir", str(self.data_dir),
                 "--max_memory_store", "256MB", "--max_file_store", "1GB"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

            # 等待启动
            for _ in range(30):
                await asyncio.sleep(0.5)
                if self.process.poll() is not None:
                    stderr = self.process.stderr.read().decode() if self.process.stderr else ""
                    logger.error("NATS server exited: %s", stderr[:200])
                    return False
                # 测试连接
                try:
                    import nats
                    await nats.connect(f"nats://localhost:{self.port}", connect_timeout=1)
                    break
                except Exception:
                    continue
            else:
                logger.error("NATS server failed to start within 15s")
                return False

            os.environ["GALAXY_NATS_URL"] = f"nats://localhost:{self.port}"
            logger.info("Embedded NATS server started on %s:%d", self.host, self.port)
            return True

        except Exception as exc:
            logger.error("Failed to start NATS server: %s", exc)
            return False

    async def _install(self) -> bool:
        """自动安装nats-server"""
        import platform
        system = platform.system().lower()

        try:
            if system == "linux":
                subprocess.run(["sh", "-c", "curl -sf https://get-nats.io | sh"],
                             check=True, timeout=120, capture_output=True, encoding="utf-8", errors="replace")
            elif system == "darwin":
                subprocess.run(["brew", "install", "nats-server"],
                             check=True, timeout=120, capture_output=True, encoding="utf-8", errors="replace")
            elif system == "windows":
                import urllib.request
                nats_dir = Path.home() / ".galaxy" / "bin"
                nats_dir.mkdir(parents=True, exist_ok=True)
                nats_exe = nats_dir / "nats-server.exe"
                url = "https://github.com/nats-io/nats-server/releases/latest/download/nats-server.exe"
                urllib.request.urlretrieve(url, str(nats_exe))
                # 添加到PATH
                os.environ["PATH"] = str(nats_dir) + os.pathsep + os.environ.get("PATH", "")
            return shutil.which("nats-server") is not None
        except Exception as exc:
            logger.error("Auto-install nats-server failed: %s", exc)
            return False

    def stop(self):
        """停止内置NATS服务器"""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
