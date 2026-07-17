"""core/native_modal.py — B 档原生全模态后端(MiniCPM-o 官方 server)+ 档位联动
=================================================================================

**为什么需要它**:B 档 MiniCPM-o 4.5 模型本身会【听/说】原生,但通过普通 Ollama
的 /api/chat 只能收文字+图片、只吐文字——耳朵嘴巴"传不出来"。要真用出它的原生
听/说,得把它跑在**支持音频 I/O 的官方 server** 上,并把那条通路接进系统的
统一模态协商层(core.modality_capability)。本模块就是这个后端 + 档位联动:

  切到 B 档 → activate():
    1. 确保 MiniCPM-o 官方 server 所需依赖装齐(缺就后台自动装,不阻塞切档);
    2. 探测/等待 server 可达;
    3. 注册【原生说】(speech_output.register_native_speech_backend)
       与【原生听】(供 modality_bridge 转写桥优先用 server 而非 Whisper);
    4. 打开 GALAXY_NATIVE_AUDIO 门控 → 协商层对 B 档判定"听/说=原生"。
  切回 A 档 → deactivate():注销后端、关门控 → 协商层判定"听=ASR桥、说=TTS桥"。

**靠谱保证**:依赖没装齐 / server 不可达 / 任何一步失败 → 一律【如实回落到桥】
(A 档那套 Whisper+TTS),绝不假装原生、绝不哑火、绝不阻断切档。全部网络/安装/
注册均可注入替身,单测不触网、不真装包。
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
from typing import Any, Callable, List, Optional

logger = logging.getLogger("Galaxy.NativeModal")

# MiniCPM-o 官方 server 客户端侧所需依赖(pip 名)。模型权重与重型推理栈由 server
# 端自身持有;这里只列客户端把音频送进/取回所需的包。缺则 activate 时后台补装。
MINICPM_CLIENT_PACKAGES: List[str] = ["httpx", "soundfile", "librosa", "numpy"]

_DEFAULT_SERVER_URL = "http://localhost:32550"


def _server_url() -> str:
    return (os.getenv("GALAXY_MINICPM_SERVER_URL", "") or _DEFAULT_SERVER_URL).strip()


def _module_present(pip_name: str) -> bool:
    # pip 名 → import 名的少量差异
    mod = {"soundfile": "soundfile", "librosa": "librosa", "httpx": "httpx", "numpy": "numpy"}.get(pip_name, pip_name)
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:  # noqa: BLE001
        return False


class MiniCPMNativeBackend:
    """MiniCPM-o 官方 server 的原生听/说适配器。

    Args:
        base_url: server 地址(默认读 GALAXY_MINICPM_SERVER_URL)。
        http_get / http_post: 注入的 HTTP 调用(测试用);None 用 httpx。
        install_fn: 注入的装包函数 (packages:list)->bool(测试用);None 用 pip。
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        http_get: Optional[Callable[..., Any]] = None,
        http_post: Optional[Callable[..., Any]] = None,
        install_fn: Optional[Callable[[List[str]], bool]] = None,
    ) -> None:
        self.base_url = (base_url or _server_url()).rstrip("/")
        self._http_get = http_get
        self._http_post = http_post
        self._install_fn = install_fn

    # ── 依赖 ──────────────────────────────────────────────────────────────
    def deps_missing(self) -> List[str]:
        return [p for p in MINICPM_CLIENT_PACKAGES if not _module_present(p)]

    def ensure_deps(self) -> bool:
        """缺的依赖装上;全在或装成即 True。装包失败不抛,返回 False。"""
        missing = self.deps_missing()
        if not missing:
            return True
        logger.info("B 档原生全模态:补装 MiniCPM 客户端依赖 %s", missing)
        try:
            if self._install_fn is not None:
                ok = bool(self._install_fn(missing))
            else:
                ok = _pip_install(missing)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MiniCPM 依赖安装异常(回落桥): %s", exc)
            return False
        return ok and not self.deps_missing()

    # ── server 可达性 ─────────────────────────────────────────────────────
    def reachable(self, timeout: float = 2.0) -> bool:
        try:
            if self._http_get is not None:
                return bool(self._http_get(f"{self.base_url}/health", timeout=timeout))
            import httpx

            r = httpx.get(f"{self.base_url}/health", timeout=timeout)
            return r.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("MiniCPM server 不可达(%s): %s", self.base_url, exc)
            return False

    # ── 原生说 ────────────────────────────────────────────────────────────
    async def speak(self, text: str, source: str = "") -> bool:
        """把文字交给 server 原生合成并播放/回传音频。成功返回 True。

        server 不可达/报错 → 返回 False(上层 speech_output 会如实告警并——由调用
        契约——不再静默,由 A 档 TTS 兜底逻辑接管)。
        """
        if not (text or "").strip():
            return False
        try:
            if self._http_post is not None:
                return bool(self._http_post(f"{self.base_url}/api/speak", json={"text": text, "source": source}))
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as cli:
                r = await cli.post(f"{self.base_url}/api/speak", json={"text": text, "source": source})
                return r.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.warning("MiniCPM 原生说失败(回落): %s", exc)
            return False

    # ── 原生听 ────────────────────────────────────────────────────────────
    def understand_audio(self, audio_b64: str, *, mime: str = "audio/webm", language: str = "zh") -> Optional[str]:
        """把音频交给 server 原生理解,返回文字(供消费文本的循环用)。

        这是"原生听"落到当前(文本决策)循环上的形态:由全模态模型自己听懂音频,
        而不是 Whisper 转写。不可达/失败返回 None → modality_bridge 会回落 Whisper。
        """
        if not audio_b64:
            return None
        try:
            if self._http_post is not None:
                return self._http_post(
                    f"{self.base_url}/api/understand_audio",
                    json={"audio_b64": audio_b64, "mime": mime, "language": language},
                )
            import httpx

            r = httpx.post(
                f"{self.base_url}/api/understand_audio",
                json={"audio_b64": audio_b64, "mime": mime, "language": language},
                timeout=30.0,
            )
            if r.status_code == 200:
                return (r.json().get("text") or "").strip() or None
            return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("MiniCPM 原生听失败(回落 Whisper): %s", exc)
            return None


def _pip_install(packages: List[str]) -> bool:
    """后台装包(best-effort)。不在事件循环里阻塞——调用方已放到线程里。"""
    import subprocess
    import sys

    try:
        rc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--retries", "2", "--timeout", "60", *packages],
            timeout=1200,
        ).returncode
        return rc == 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("pip 安装 MiniCPM 依赖失败: %s", exc)
        return False


# ── 档位联动协调器 ────────────────────────────────────────────────────────────
_active_backend: Optional[MiniCPMNativeBackend] = None
_activating = False
# 代次令牌:每次 activate/deactivate 自增。后台激活线程只在"自己那一代还有效"时
# 才提交注册——期间若被 deactivate(切回 A 档)抢先,代次已变,线程放弃提交,
# 避免"切回 A 档后,慢半拍的后台线程又把原生装回来"的竞态。
_gen = 0
_lock = threading.Lock()


def is_native_active() -> bool:
    return _active_backend is not None


def get_active_backend() -> Optional[MiniCPMNativeBackend]:
    return _active_backend


def activate(backend: Optional[MiniCPMNativeBackend] = None, *, background: bool = True) -> None:
    """激活 B 档原生后端:确保依赖 → 探测 server → 注册听/说 → 开门控。

    重活(装包/探测)默认放后台线程,不阻塞切档;就绪后才真正注册+开门控——
    没就绪之前协商层仍判"桥",不会出现"门开了但通路是空的"。
    """
    be = backend or MiniCPMNativeBackend()

    def _do(my_gen: int) -> None:
        global _active_backend, _activating
        try:
            if not be.ensure_deps():
                logger.warning("B 档原生:依赖未装齐,回落桥(听=Whisper、说=TTS)")
                return
            if not be.reachable():
                logger.warning(
                    "B 档原生:MiniCPM server(%s)不可达,回落桥。"
                    "启动官方 server 或设 GALAXY_MINICPM_SERVER_URL 后重切 B 档。",
                    be.base_url,
                )
                return
            # 提交前再确认这一代仍有效:期间没被 deactivate/重激活抢先。
            with _lock:
                if my_gen != _gen:
                    logger.info("B 档原生:激活期间已切换代次,放弃提交(避免切回 A 档后又装回原生)")
                    return
            # 就绪 → 注册原生说 + 开门控;原生听由 modality_bridge 主动查 get_active_backend()。
            try:
                from core.speech_output import register_native_speech_backend

                register_native_speech_backend(lambda text, source="": be.speak(text, source))
            except Exception as exc:  # noqa: BLE001
                logger.debug("注册原生说后端失败(仍可只用原生听): %s", exc)
            os.environ["GALAXY_NATIVE_AUDIO"] = "1"
            with _lock:
                _active_backend = be
            logger.info("B 档原生全模态已就绪:听/说走 MiniCPM server(%s)", be.base_url)
        finally:
            _activating = False

    global _activating
    with _lock:
        if _active_backend is not None or _activating:
            return  # 已激活 or 后台激活进行中——别再起一条线程重复装包/探测
        _activating = True
        my_gen = _gen
    if background:
        threading.Thread(target=_do, name="minicpm-activate", args=(my_gen,), daemon=True).start()
    else:
        _do(my_gen)


def deactivate() -> None:
    """切回 A 档:注销原生后端、关门控 → 协商层判定听=ASR桥、说=TTS桥。"""
    global _active_backend, _gen
    with _lock:
        _active_backend = None
        _gen += 1  # 令任何在途的后台激活线程失效(它提交前会发现代次已变)
    try:
        from core.speech_output import register_native_speech_backend

        register_native_speech_backend(None)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        logger.debug("注销原生说后端失败: %s", exc)
    # 只有本模块开的门控才由本模块关(尊重用户手动设的 GALAXY_NATIVE_AUDIO)。
    if os.environ.get("GALAXY_NATIVE_AUDIO") == "1":
        os.environ.pop("GALAXY_NATIVE_AUDIO", None)


def _auto_activation_allowed() -> bool:
    """B 档是否【自动】激活原生后端(会后台装包 + 探测 server)。

    默认允许(生产:切 B 档就装齐打通,正是需求);但在【测试运行期】一律禁止,
    避免 save_tier('B') 的单测触发真实后台 pip 安装。GALAXY_NATIVE_MODAL_AUTO=0
    可显式关闭自动激活(仍可手动 activate)。
    """
    if os.getenv("GALAXY_NATIVE_MODAL_AUTO", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("GALAXY_ENV", "").strip().lower() == "test":
        return False
    return True


def on_tier_changed(key: str, *, background: bool = True) -> None:
    """由 model_catalog.save_tier 调用:B 档激活原生后端、其它档注销。best-effort。"""
    try:
        if (key or "").strip().upper() == "B":
            if _auto_activation_allowed():
                activate(background=background)
        else:
            deactivate()  # 注销很轻(无装包),任何时候都执行,确保切回 A 档干净回落桥
    except Exception as exc:  # noqa: BLE001 — 档位联动绝不能拖垮切档
        logger.debug("on_tier_changed 处理异常(不影响切档): %s", exc)


NATIVE_MODAL_AUTHORITY: str = (
    "NATIVE_MODAL_V1: core/native_modal.py | B 档 MiniCPM-o 官方 server 原生听/说后端 + "
    "档位联动. 切 B→activate(依赖自动装+server 探测+注册听/说+开 GALAXY_NATIVE_AUDIO); "
    "切 A→deactivate. 任何一步失败一律如实回落桥(Whisper/TTS),绝不假装原生."
)

__all__ = [
    "MiniCPMNativeBackend",
    "MINICPM_CLIENT_PACKAGES",
    "activate",
    "deactivate",
    "on_tier_changed",
    "is_native_active",
    "get_active_backend",
    "NATIVE_MODAL_AUTHORITY",
]
