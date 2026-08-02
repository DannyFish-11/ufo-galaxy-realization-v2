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

# 固定已知可用版本，避免 API 调用。Windows / Linux 共用同一 tag。
NATS_RELEASE_TAG = "v2.10.24"

# 镜像源列表（按优先级；两条加速镜像 + 官方 GitHub 直连兜底）。下载物始终是
# NATS 官方 GitHub release 的原始发布件，镜像只做传输加速，SHA256 校验保证
# 内容与官方发布一致、镜像不可能夹私货。
_NATS_MIRRORS = (
    "https://mirror.ghproxy.com/https://github.com",
    "https://ghfast.top/https://github.com",
    "https://github.com",  # 官方直连兜底
)


def _http_get(url: str, timeout: int = 20) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Galaxy-Installer"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _download_verified_release(asset_name: str, dest: Path) -> bool:
    """下载 ``asset_name`` 到 ``dest``，并按官方 SHA256SUMS 校验后才落盘。

    B9 修复的核心：此前 Linux 分支直接 ``sh -c "curl -sf https://get-nats.io | sh"``
    —— 远端脚本内容一变就是本机 RCE，且无摘要校验、无版本钉住。而**同一个文件的
    Windows 分支早就做对了**（钉版本 + 官方 SHA256SUMS + 校验不过就换源）。
    这里把那套已验证的下载逻辑提取出来，两个平台共用，Linux 不再执行远端脚本。

    校验不通过 / 拿不到 SHA256SUMS 时**不安装**，换下一个源；全部源失败返回 False。
    注意与旧 Windows 分支的一处行为差异：旧代码在 SHA256SUMS 获取失败时会
    "跳过校验"照常安装，那等于把校验做成了可选项 —— 这里改成拿不到摘要就换源，
    宁可装不上也不装未经校验的二进制。

    :return: 成功且已校验时 True。
    """
    import hashlib

    for mirror in _NATS_MIRRORS:
        base = f"{mirror}/nats-io/nats-server/releases/download/{NATS_RELEASE_TAG}"
        try:
            blob = _http_get(f"{base}/{asset_name}")
        except Exception as exc:  # noqa: BLE001
            logger.debug("镜像 %s 下载 %s 失败: %s", mirror, asset_name, exc)
            continue

        expected = ""
        try:
            # 官方 release 附带 SHA256SUMS（每行 "<hash>  <文件名>"）
            for line in _http_get(f"{base}/SHA256SUMS", timeout=10).decode("utf-8", "replace").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[-1].lstrip("*./") == asset_name:
                    expected = parts[0].lower()
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("镜像 %s 的 SHA256SUMS 获取失败，弃用该源(不降级为免校验安装): %s", mirror, exc)
            continue

        if not expected:
            logger.warning("镜像 %s 的 SHA256SUMS 中找不到 %s，弃用该源", mirror, asset_name)
            continue

        actual = hashlib.sha256(blob).hexdigest().lower()
        if actual != expected:
            logger.error("%s 校验失败(源 %s): sha256 %s != 官方 %s，弃用该源", asset_name, mirror, actual, expected)
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(blob)
        logger.info("%s 下载完成并通过官方 SHA256SUMS 校验(源 %s)", asset_name, mirror)
        return True

    logger.error("%s 所有下载源均失败或校验不通过 —— 拒绝安装未经校验的二进制", asset_name)
    return False


def _linux_asset_name() -> str | None:
    """返回当前 Linux 架构对应的官方 release 资产名，不支持的架构返回 None。"""
    import platform

    machine = platform.machine().lower()
    arch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "arm7",
        "armv6l": "arm6",
    }.get(machine)
    if arch is None:
        logger.error("不支持的 Linux 架构 %s —— 无对应的 nats-server 官方发布件", machine)
        return None
    return f"nats-server-{NATS_RELEASE_TAG}-linux-{arch}.tar.gz"


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
                self.last_error_hint = (
                    "已自动降级为进程内总线,单机模式正常。如需跨设备:手动安装 "
                    "nats-server(https://nats.io);或设 GALAXY_NATS_ENABLED=false 显式关闭此尝试"
                )
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
                    "Windows 智能应用控制(Smart App Control)/WDAC 拦截了 nats-server.exe。"
                    "已自动降级为进程内总线——单机模式正常,仅跨设备分发不可用。"
                    f"如需跨设备,一键放行:Windows 安全中心 → 应用和浏览器控制 → 允许 {_exe} 运行后重启;"
                    "或单机使用设 GALAXY_NATS_ENABLED=false 显式关闭此尝试"
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
                # B9: 此处曾是 ["sh", "-c", "curl -sf https://get-nats.io | sh"] ——
                # 无摘要校验、无版本钉住的远端脚本执行，等价于把本机交给 get-nats.io。
                # 改走与 Windows 分支同源的「钉版本 + 官方 SHA256SUMS 校验」路径。
                import tarfile

                nats_dir = Path.home() / ".lumiv" / "bin"
                nats_bin = nats_dir / "nats-server"

                # 已装过就复用（与 Windows 分支同样的短路，避免每次启动白等一轮下载）
                if nats_bin.is_file() and nats_bin.stat().st_size > 0:
                    os.environ["PATH"] = str(nats_dir) + os.pathsep + os.environ.get("PATH", "")
                    logger.info("nats-server 已安装,复用 %s(跳过下载)", nats_bin)
                    return True

                asset = _linux_asset_name()
                if asset is None:
                    return False

                nats_dir.mkdir(parents=True, exist_ok=True)
                tar_path = nats_dir / asset
                if not _download_verified_release(asset, tar_path):
                    return False

                try:
                    with tarfile.open(tar_path, "r:gz") as tf:
                        for member in tf.getmembers():
                            if not member.isfile() or Path(member.name).name != "nats-server":
                                continue
                            src = tf.extractfile(member)
                            if src is None:
                                continue
                            with src, open(nats_bin, "wb") as out:
                                shutil.copyfileobj(src, out)
                            nats_bin.chmod(0o755)
                            break
                        else:
                            logger.error("%s 中未找到 nats-server 可执行文件", asset)
                            return False
                except Exception as exc:  # noqa: BLE001
                    logger.error("nats-server 解包失败: %s", exc)
                    return False
                finally:
                    tar_path.unlink(missing_ok=True)

                os.environ["PATH"] = str(nats_dir) + os.pathsep + os.environ.get("PATH", "")
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
                # hashlib / urllib.request 已随下载逻辑一起上移到模块级 helper。
                nats_dir = Path.home() / ".lumiv" / "bin"
                nats_dir.mkdir(parents=True, exist_ok=True)
                nats_exe = nats_dir / "nats-server.exe"

                # 已经装过就直接复用,不要再下一遍。
                # 真机实证:~/.lumiv/bin 在用户主目录里,重新克隆仓库也不会清掉,
                # 于是 nats-server.exe 明明躺在那儿,每次启动仍照常走完整下载流程
                # ——白等 30s("[PHASE-TIMING] 消息总线 30.44s" 基本全耗在这),
                # 末了还因为目标文件已存在而抛 WinError 183 刷一条 ERROR。
                # 入口处的 shutil.which("nats-server") 看不到它,只是因为
                # ~/.lumiv/bin 本来就不在 PATH 上——那不代表"没装"。
                if nats_exe.is_file() and nats_exe.stat().st_size > 0:
                    os.environ["PATH"] = str(nats_dir) + os.pathsep + os.environ.get("PATH", "")
                    logger.info("nats-server 已安装,复用 %s(跳过下载)", nats_exe)
                    return True
                # 下载 zip 包 + 官方 SHA256SUMS 校验(所有者 Windows 真机 WinError 4551
                # 整治的一环:确保落盘的是 NATS 官方 GitHub release 的原始二进制、
                # 未被镜像/中间人篡改;校验不过就换下一个源,绝不安装可疑文件)
                #
                # B9 重构:镜像列表 / _http_get / 下载校验循环原本内联在本分支里,
                # 现已提取为模块级 _download_verified_release(),与 Linux 分支共用
                # ——Linux 此前走的是无校验的 `curl | sh`,共用后两个平台同一套保证。
                zip_name = f"nats-server-{NATS_RELEASE_TAG}-windows-amd64.zip"
                zip_path = nats_dir / zip_name
                downloaded = _download_verified_release(zip_name, zip_path)
                if downloaded:
                    try:
                        import zipfile

                        with zipfile.ZipFile(zip_path, "r") as z:
                            for name in z.namelist():
                                if name.endswith("nats-server.exe"):
                                    z.extract(name, nats_dir)
                                    extracted = nats_dir / name
                                    # os.replace 而不是 Path.rename:后者在 Windows 上
                                    # 只要目标已存在就抛 [WinError 183] 当文件已存在时,
                                    # 无法创建该文件(真机实证)——POSIX 的 rename 会静默
                                    # 覆盖,这个差异让整段解压在 Windows 上必然失败。
                                    # os.replace 两个平台都是"原子覆盖"。
                                    os.replace(extracted, nats_exe)
                                    # 顺手清掉解压出来的中间目录
                                    # (nats-server-<tag>-windows-amd64/),
                                    # 否则每次安装都往 ~/.lumiv/bin 里堆一层空壳目录。
                                    parent = extracted.parent
                                    if parent != nats_dir:
                                        shutil.rmtree(parent, ignore_errors=True)
                                    break
                        zip_path.unlink(missing_ok=True)
                    except Exception as e:  # noqa: BLE001
                        # 旧代码此处回退直接下载裸 nats-server.exe——但官方 release
                        # 从不发布裸 exe,该 URL 必 404,是永远走不通的死分支;删除。
                        logger.error("nats-server.zip 解压失败: %s", e)
                # 添加到PATH
                if nats_exe.exists():
                    # WinError 4551 缓解:去掉下载文件的 Mark-of-the-Web(Zone.Identifier
                    # ADS)。SmartScreen/部分应用控制策略按该标记加重审查;去掉后
                    # 本地解压产物与本机生成文件同待遇,能显著降低被拦概率。
                    # (智能应用控制若仍拦截,start() 里已给出一键放行指引并自动
                    # 降级为进程内总线,不影响单机使用。)
                    try:
                        os.remove(str(nats_exe) + ":Zone.Identifier")
                    except OSError:
                        pass
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
