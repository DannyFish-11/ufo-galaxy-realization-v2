"""
core/routes/perception.py
=========================
桌面端连续感知接收路由（摄像头 / 麦克风 / 屏幕 / 系统播放声）。

电脑端 Electron 壳用 getUserMedia 采集帧后 POST 到这里：
- POST /api/perception/desktop/frame    —— 存最新摄像头/屏幕帧（隐蔽上下文）
- POST /api/perception/desktop/audio    —— 存最新麦克风音频片段
- POST /api/perception/desktop/system_audio      —— 存最新系统播放声片段
- GET  /api/perception/desktop/system_audio/probe —— 本机能否回环采集 + 不能的原因
- POST /api/perception/desktop/analyze  —— 「现在看一下」：把帧原生送模型分析
- GET  /api/perception/desktop/status   —— 存储/新鲜度诊断

系统播放声这一路**只能在电脑端本机采集**：getUserMedia 只给输入设备，拿不到系统
输出；getDisplayMedia 要每次手动选窗口、跨浏览器支持残缺，做不成常驻感知。所以它
走 WASAPI loopback（Windows）/ PulseAudio .monitor（Linux），见
``core/multimodal/system_audio_ingest.py``。这是能力差异，不是性能优化。

frame/audio 只更新进程内 DesktopPerceptionStore，由 OpenClawd.process() 在下一次
真实请求时按 TTL 取用、作为原生多模态上下文注入（模型真正「看到」摄像头）。
analyze 则复用 Android vision 已验证的 runtime-shell 多模态路径，立即出分析。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Routes.Perception")


class DesktopFrame(BaseModel):
    image_base64: str = Field(description="Base64 编码的图像帧（建议 JPEG，≤1MB）")
    mime: str = Field(default="image/jpeg")
    source: str = Field(default="desktop_camera", description="desktop_camera / desktop_screen")
    screen: Optional[Dict[str, Any]] = None


class DesktopAudio(BaseModel):
    audio_base64: str = Field(description="Base64 编码的音频片段")
    mime: str = Field(default="audio/webm")


class DesktopAnalyze(BaseModel):
    image_base64: str = ""
    mime: str = "image/jpeg"
    prompt: str = ""
    source: str = "desktop_camera"
    session_id: str = ""


class DesktopListen(BaseModel):
    audio_base64: str = ""
    mime: str = "audio/webm"
    prompt: str = ""


def _internal_error(where: str, exc: Exception) -> Dict[str, Any]:
    """内部错误的统一回法:细节只进服务端日志,不回给调用方。

    直接把 ``str(exc)`` 回出去会泄露文件路径、模块名等实现细节(CodeQL 的
    "Information exposure through an exception")。这里回一个稳定的 ``error_code``
    让客户端能分支处理,真正的堆栈用 ``exc_info=True`` 留在日志里 —— 排查能力不打折,
    但不经由 HTTP 响应外泄。
    """
    logger.error("桌面感知接口内部错误 [%s]: %s", where, exc, exc_info=True)
    return {"success": False, "error": "内部错误,请查看服务端日志", "error_code": where}


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create desktop perception ingest routes."""
    router = APIRouter(prefix="/api/perception/desktop", tags=["perception"])

    @router.post("/frame")
    async def ingest_frame(frame: DesktopFrame):
        """接收最新摄像头/屏幕帧 → 存入 DesktopPerceptionStore（不立即调模型）。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store

            store = get_desktop_perception_store()
            # 隐私暂停期间 update_frame 会拒收。若照旧回 stored="frame",采集端
            # 会以为帧已存进去而继续按原节奏推送 —— 必须如实告知它被丢弃了,
            # 客户端才能据此降低推送频率或提示用户"感知已暂停"。
            if store.paused:
                return {
                    "success": False,
                    "stored": None,
                    "privacy_paused": True,
                    "reason": "感知已被隐私暂停,本帧未被接收",
                }
            store.update_frame(
                frame.image_base64,
                mime=frame.mime,
                source=frame.source,
                screen=frame.screen,
            )
            return {"success": True, "stored": "frame"}
        except Exception as exc:  # noqa: BLE001
            logger.debug("frame ingest failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @router.post("/audio")
    async def ingest_audio(audio: DesktopAudio):
        """接收最新麦克风音频片段 → 存入 DesktopPerceptionStore。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store

            store = get_desktop_perception_store()
            if store.paused:  # 同 /frame:拒收要如实上报,不能假装存了
                return {
                    "success": False,
                    "stored": None,
                    "privacy_paused": True,
                    "reason": "感知已被隐私暂停,本段音频未被接收",
                }
            store.update_audio(audio.audio_base64, mime=audio.mime)
            return {"success": True, "stored": "audio"}
        except Exception as exc:  # noqa: BLE001
            logger.debug("audio ingest failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @router.post("/system_audio")
    async def ingest_system_audio(audio: DesktopAudio):
        """接收最新【系统播放声】片段(扬声器输出的回环采集)→ 存入独立槽位。

        与 /audio 分开是因为语义不同:麦克风是"用户说了什么",系统声是"用户此刻在
        听什么"。混进同一槽会互相覆盖,而且模型再也分不出这段声音是人说的还是屏幕
        里放的 —— 那恰恰是它最需要区分的一件事。
        """
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store

            store = get_desktop_perception_store()
            if store.paused:  # 同 /frame:拒收要如实上报,不能假装存了
                return {
                    "success": False,
                    "stored": None,
                    "privacy_paused": True,
                    "reason": "感知已被隐私暂停,本段系统播放声未被接收",
                }
            store.update_system_audio(audio.audio_base64, mime=audio.mime)
            return {"success": True, "stored": "system_audio"}
        except Exception as exc:  # noqa: BLE001
            return _internal_error("system_audio_ingest", exc)

    @router.get("/system_audio/probe")
    async def probe_system_audio():
        """本机能否做系统播放声采集,以及不能的话**为什么**。

        采集端(电脑端壳)先问这里再决定是否启动回环采集线程;不可用时 reason_text
        是一句可直接展示给用户的修复指引,而不是静默的 false。
        """
        try:
            from core.multimodal.system_audio_ingest import probe

            return {"success": True, **probe()}
        except Exception as exc:  # noqa: BLE001
            return {**_internal_error("system_audio_probe", exc), "available": False}

    @router.get("/audio/echo_cancellation")
    async def echo_cancellation_status():
        """回声消除与回环采集的实时状态。

        这条接口存在的理由是**可观测性**:AEC 在没有参考信号时会静默走旁通 ——
        不报错、不打日志、回声照旧。光看现象根本分不清"AEC 没装上"、"回环采集没起来"、
        还是"装上了但还没收敛"。这里把三者分开摊出来:

        - ``capture.running`` / ``capture.unavailable_reason`` —— 参考信号有没有源头;
        - ``aec.blocks_bypassed`` + ``last_bypass_reason`` —— 有没有在旁通,为什么;
        - ``aec.erle_db`` —— 真实抑制了多少 dB。这是唯一的硬指标,>6dB 才算在起作用。
        """
        out: Dict[str, Any] = {"success": True}
        try:
            from core.multimodal.acoustic_echo_canceller import get_echo_canceller

            out["aec"] = get_echo_canceller().snapshot()
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取 AEC 状态失败: %s", exc)
            out["aec"] = {"available": False}
        try:
            from core.multimodal.system_audio_capture_service import (
                get_system_audio_capture,
            )

            out["capture"] = get_system_audio_capture().status()
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取回环采集状态失败: %s", exc)
            out["capture"] = {"running": False}
        return out

    @router.get("/status")
    async def perception_status():
        """返回桌面感知存储的新鲜度/计数诊断。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store

            return {"success": True, "store": get_desktop_perception_store().status()}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    # ── 隐私急停 ──────────────────────────────────────────────────────────
    #
    # 一个调用立刻切断全部桌面感知,不经配置文件、不需重启。对应桌宠"双击暂停"
    # 那类交互:用户要的是"立刻别看了",而不是"改个配置等它生效"。
    #
    # 闸门落在 DesktopPerceptionStore(唯一进出口),因此这两个端点一按,
    # ambient 循环、computer_use_loop、session_memory_facade、
    # multimodal/ingest_runtime 四个消费方同时失明,没有绕行路径。

    @router.post("/privacy/pause")
    async def privacy_pause(reason: str = "user"):
        """立即暂停感知:拒收后续帧/音频,并清空已缓存内容。幂等。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store

            status = get_desktop_perception_store().pause(reason=reason)
            return {
                "success": True,
                "privacy": status,
                "note": "已停止采集并清空缓存;四个消费方(环境循环/电脑操作/会话记忆/多模态注入)同时失明",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("隐私暂停失败", exc_info=True)
            return {
                "success": False,
                "error": "内部错误,请查看服务端日志",
                "error_code": "privacy_pause",
                "detail": type(exc).__name__,
            }

    @router.post("/privacy/resume")
    async def privacy_resume(reason: str = "user"):
        """恢复感知。世代号自增,消费方会据此重置帧差门控。幂等。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store

            status = get_desktop_perception_store().resume(reason=reason)
            return {"success": True, "privacy": status}
        except Exception as exc:  # noqa: BLE001
            logger.error("隐私恢复失败", exc_info=True)
            return {
                "success": False,
                "error": "内部错误,请查看服务端日志",
                "error_code": "privacy_resume",
                "detail": type(exc).__name__,
            }

    @router.get("/privacy")
    async def privacy_state():
        """当前隐私状态(供面板/桌宠显示"感知已暂停"及被拒计数)。"""
        try:
            from core.perception.desktop_perception_store import get_desktop_perception_store

            return {"success": True, "privacy": get_desktop_perception_store().privacy_status()}
        except Exception as exc:  # noqa: BLE001
            logger.error("读取隐私状态失败", exc_info=True)
            return {
                "success": False,
                "error": "内部错误,请查看服务端日志",
                "error_code": "privacy_state",
                "detail": type(exc).__name__,
            }

    @router.post("/analyze")
    async def analyze_now(req: DesktopAnalyze):
        """「现在看一下」：把当前帧（或存储里的最新帧）原生送模型分析。

        复用 Android vision 已验证的 runtime-shell 多模态路径：构建
        MultiModalContext → DesktopPresenceRuntime.handle_request → 原生送模型。
        """
        image_b64 = req.image_base64
        mime = req.mime or "image/jpeg"
        source = req.source or "desktop_camera"
        # 未带图则取存储里的最新帧（摄像头或屏幕，取更新的那张）
        if not image_b64:
            try:
                from core.perception.desktop_perception_store import get_desktop_perception_store

                _b64, _mime, _src = get_desktop_perception_store().latest_frame_snapshot()
                if _b64:
                    image_b64, mime, source = _b64, _mime, _src
            except Exception as exc:  # noqa: BLE001
                logger.debug("store snapshot failed: %s", exc)
        if not image_b64:
            return {"success": False, "error": "no_frame_available"}

        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime
            from core.schemas.multimodal import MultiModalContext, MultiModalImage

            mm_context = MultiModalContext(
                images=[MultiModalImage(mime=mime, data=image_b64, source=source)],
                screen={"source": "desktop"},
                metadata={"source": "desktop_perception_analyze"},
            )
            runtime = get_desktop_presence_runtime()
            prompt = req.prompt or "描述一下你现在通过桌面摄像头/屏幕看到的内容。"
            session_id = req.session_id or "desktop_perception"
            result = await runtime.handle_request(
                message=prompt,
                source="desktop_vision",
                device_id=None,
                session_id=session_id,
                user_id="desktop",
                multimodal_context=mm_context,
                entry_mode="local",
            )
            return {
                "success": bool(result.get("success", True)),
                "runtime_session_id": result.get("runtime_session_id"),
                "response": result.get("response", ""),
                "multimodal_route": result.get("multimodal_route_decision", {}),
                "source": "runtime_shell_multimodal",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("desktop analyze failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @router.post("/listen")
    async def listen_now(req: DesktopListen):
        """「现在听一下」：把当前音频（或存储里的最新音频）原生送音频能力模型理解。

        复用 AudioPipeline 的原生音频通路（Gemini inline_data / OpenAI input_audio），
        返回模型对这段音频的理解/转写文本。需配置 GEMINI/GOOGLE 或 OPENAI key。
        """
        audio_b64 = req.audio_base64
        mime = req.mime or "audio/webm"
        if not audio_b64:
            try:
                from core.perception.desktop_perception_store import get_desktop_perception_store

                _store = get_desktop_perception_store()
                with _store._lock:  # noqa: SLF001 — 读快照
                    audio_b64 = _store._audio_b64 or ""
                    mime = _store._audio_mime
            except Exception as exc:  # noqa: BLE001
                logger.debug("store audio snapshot failed: %s", exc)
        if not audio_b64:
            return {"success": False, "error": "no_audio_available"}
        try:
            from core.audio_pipeline import get_audio_pipeline

            result = await get_audio_pipeline().understand(
                audio_b64,
                mime=mime,
                prompt=req.prompt or "",
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("desktop listen failed: %s", exc)
            return {"success": False, "error": str(exc)}

    return router
