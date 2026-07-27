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
from pathlib import Path

logger = logging.getLogger("Galaxy.NATSServer")


class EmbeddedNATSServer:
    """内置NATS服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 4222):
        self.host = host
        self.port = port
        self.process = None
        self.data_dir = Path.home() / ".lumiv" / "nats"
        # 诚实性修复(所有者 Windows 真机实证):start() 失败时只 return False,
        # 具体原因(如 WinError 4551 被 WDAC 拦截)只进日志,调用方无从得知、
        # 启动横幅照打 ✓。这里把"失败原因 + 专属修复指引"暴露成实例属性,
        # 供 unified_launcher 启动横幅如实降级展示。
        self.last_error: str = ""
        self.last_error_hint: str = ""

    async def start(self) -> bool:
        """启动内置NATS服务器"""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 检查nats-server
        if not shutil.which("nats-server"):
            logger.info("nats-server not found, attempting auto-install...")
            if not await self._install():
                logger.warning(
                    "nats-server not available — cross-device bus disabled. "
                    "Install nats-server manually or set GALAXY_NATS_ENABLED=false"
                )
                self.last_error = "nats-server 未安装且自动安装失败"
                self.last_error_hint = "手动安装 nats-server(https://nats.io)或设 GALAXY_NATS_ENABLED=false 关闭"
                return False

        # 启动
        try:
            # PR-NATS-ARGS: v2.10.x uses JetStream — remove legacy --max_memory_store/--max_file_store flags
            # PR-NATS-PIPE: redirect stdout/stderr to DEVNULL to prevent pipe buffer deadlock
            self.process = subprocess.Popen(
                [
                    "nats-server",
                    "--addr",
                    self.host,
                    "--port",
                    str(self.port),
                    "--jetstream",
                    "--store_dir",
                    str(self.data_dir),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # 等待启动
            for _ in range(30):
                await asyncio.sleep(0.5)
                if self.process.poll() is not None:
                    stderr = self.process.stderr.read().decode() if self.process.stderr else ""
                    logger.error("NATS server exited: %s", stderr[:200])
                    self.last_error = f"nats-server 进程启动后立即退出 {stderr[:200]}".strip()
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
                self.last_error = "nats-server 15 秒内未就绪(端口未接受连接)"
                return False

            os.environ["GALAXY_NATS_URL"] = f"nats://localhost:{self.port}"
            logger.info("Embedded NATS server started on %s:%d", self.host, self.port)
            return True

        except Exception as exc:
            logger.error("Failed to start NATS server: %s", exc)
            # 根因(所有者 Windows 真机日志):Popen 抛 [WinError 4551]"应用程序
            # 控制策略已阻止此文件"—— Windows 智能应用控制(Smart App Control)/
            # WDAC 拦截了未签名的 nats-server.exe,二进制根本没被允许执行。
            # 此前该原因只进日志就 return False,启动横幅仍打 "✓ 消息总线"。
            self.last_error = str(exc) or repr(exc)
            _msg = str(exc)
            if getattr(exc, "winerror", None) == 4551 or "WinError 4551" in _msg or "应用程序控制策略" in _msg:
                _exe = shutil.which("nats-server") or str(Path.home() / ".lumiv" / "bin" / "nats-server.exe")
                self.last_error_hint = (
                    "Windows 智能应用控制(Smart App Control)/WDAC 拦截了未签名的 nats-server.exe。"
                    f"修复:Windows 安全中心 → 应用和浏览器控制 → 允许 {_exe} 运行后重启;"
                    "或单机使用保持 GALAXY_NATS_ENABLED=false(系统自动降级为进程内总线,仅跨设备分发不可用)"
                )
            return False

    async def _install(self) -> bool:
        """自动安装nats-server。

        整个安装体(curl/brew/urllib 下载/解压)都是同步阻塞操作,最长 120s——
        放线程跑,否则启动路径上事件循环冻结,面板/WS 全部假死。
        """
        import asyncio

        return await asyncio.to_thread(self._install_sync)

    def _install_sync(self) -> bool:
        """同步安装体(仅经 _install 的 to_thread 调用)。"""
        import platform

        system = platform.system().lower()

        try:
            if system == "linux":
                subprocess.run(
                    ["sh", "-c", "curl -sf https://get-nats.io | sh"],
                    check=True,
                    timeout=120,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                )
            elif system == "darwin":
                subprocess.run(
                    ["brew", "install", "nats-server"],
                    check=True,
                    timeout=120,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                )
            elif system == "windows":
                import urllib.request

                nats_dir = Path.home() / ".lumiv" / "bin"
                nats_dir.mkdir(parents=True, exist_ok=True)
                nats_exe = nats_dir / "nats-server.exe"
                # PR-NATS-CN: 使用国内镜像源加速下载，支持超时重试
                tag = "v2.10.24"  # 固定已知可用版本，避免API调用
                # 镜像源列表（按优先级）
                mirrors = [
                    "https://mirror.ghproxy.com/https://github.com",  # 2025 verified
                    "https://mirror.ghproxy.com/https://github.com",
                    "https://github.com",  # 直连兜底
                ]
                # 下载zip包
                zip_path = nats_dir / "nats-server.zip"
                downloaded = False
                for mirror in mirrors:
                    url = f"{mirror}/nats-io/nats-server/releases/download/{tag}/nats-server-{tag}-windows-amd64.zip"
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "Galaxy-Installer"})
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            with open(zip_path, "wb") as f:
                                f.write(resp.read())
                        downloaded = True
                        logger.info("nats-server downloaded from %s", mirror)
                        break
                    except Exception as e:
                        logger.debug("Mirror %s failed: %s", mirror, e)
                        continue
                if downloaded:
                    try:
                        import zipfile

                        with zipfile.ZipFile(zip_path, "r") as z:
                            for name in z.namelist():
                                if name.endswith("nats-server.exe"):
                                    z.extract(name, nats_dir)
                                    extracted = nats_dir / name
                                    extracted.rename(nats_exe)
                                    break
                        zip_path.unlink(missing_ok=True)
                    except Exception:
                        # Fallback: direct exe download
                        for mirror in mirrors:
                            url = f"{mirror}/nats-io/nats-server/releases/download/{tag}/nats-server.exe"
                            try:
                                req = urllib.request.Request(url, headers={"User-Agent": "Galaxy-Installer"})
                                with urllib.request.urlopen(req, timeout=15) as resp:
                                    with open(nats_exe, "wb") as f:
                                        f.write(resp.read())
                                logger.info("nats-server.exe downloaded from %s", mirror)
                                break
                            except Exception:
                                continue
                # 添加到PATH
                if nats_exe.exists():
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
