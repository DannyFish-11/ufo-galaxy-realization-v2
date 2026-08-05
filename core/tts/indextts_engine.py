"""core.tts.indextts_engine — IndexTTS2 零样本克隆 + 情绪控制(可选引擎)
==========================================================================

**定位:** B 站 IndexSpeech 开源的工业级零样本 TTS(github.com/index-tts/index-tts)。
给一段参考音频即可复刻音色,且音色与情绪解耦(可"这个人的声音+另一种情绪")。
**质量/表现力档,不是低延迟档**:自回归大模型,纯 CPU 合成一句要数秒到数十秒,
远慢于 kokoro/edge——所以它**不进默认回退链**,只在用户显式
``GALAXY_TTS_ENGINE=indextts`` 时启用(运行期失败仍会 demote 回默认链,
绝不整段静默)。适合:旁白/有声内容/情绪演绎;实时对话请留在 edge/kokoro。

依赖与模型(都不随仓库分发,按需自装):
  - ``pip install indextts``(或按官方 README: git clone + uv sync)
  - 模型权重 ~几 GB:HuggingFace ``IndexTeam/IndexTTS-2``(支持 HF_ENDPOINT 镜像)
    存放 models/indextts2/(GALAXY_INDEXTTS_DIR 可改)。体积大,后台自动拉取
    **默认关闭**(GALAXY_INDEXTTS_AUTOFETCH=1 显式打开)。

音色/情绪(README 官方口径):
  - GALAXY_INDEXTTS_REF_AUDIO   参考音频 wav 路径(必填——零样本克隆的音色来源)
  - GALAXY_INDEXTTS_EMO_AUDIO   可选:情绪参考音频(方式 A)
  - GALAXY_INDEXTTS_EMO_TEXT    可选:独立情绪文本描述(方式 D,与台词解耦)
  - GALAXY_INDEXTTS_EMO_ALPHA   情绪强度(默认 0.6,官方建议值)
  - GALAXY_INDEXTTS_USE_EMO_TEXT=1  由台词语义自动推断情绪(方式 C)
  - GALAXY_INDEXTTS_FP16=1      显存紧张时启用 fp16(GPU 场景)

合成放 asyncio.to_thread(重推理,不占事件循环);播放/打断继承 EdgeTTSEngine。
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from .edge_tts_engine import EdgeTTSEngine

logger = logging.getLogger("Galaxy.TTS.IndexTTS")

_HF_REPO = "IndexTeam/IndexTTS-2"

_fetch_lock = threading.Lock()
_fetch_started = False


def _model_dir() -> Path:
    # 空串必须回落到默认值:面板把输入框清空后写回的是 ``GALAXY_INDEXTTS_DIR=``,
    # get 的默认参数对空串不生效,会得到 Path("")。同 kokoro_engine._model_dir()。
    return Path(os.environ.get("GALAXY_INDEXTTS_DIR", "").strip() or "models/indextts2")


def _ref_audio() -> str:
    return os.environ.get("GALAXY_INDEXTTS_REF_AUDIO", "").strip()


def model_files_present() -> bool:
    """以 config.yaml 为就绪哨兵(官方 checkpoints 布局的锚点文件)。"""
    return (_model_dir() / "config.yaml").exists()


def kick_background_fetch() -> None:
    """后台拉取模型(幂等,至多一次)。**默认关闭**——权重数 GB,不做静默大下载;
    GALAXY_INDEXTTS_AUTOFETCH=1 显式开启(支持 HF_ENDPOINT 国内镜像)。"""
    global _fetch_started
    if os.environ.get("GALAXY_INDEXTTS_AUTOFETCH", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return
    with _fetch_lock:
        if _fetch_started or model_files_present():
            return
        _fetch_started = True

    def _fetch() -> None:
        try:
            from huggingface_hub import snapshot_download

            d = _model_dir()
            d.mkdir(parents=True, exist_ok=True)
            logger.info("IndexTTS-2 模型后台拉取中(数 GB,首次较久): %s", _HF_REPO)
            snapshot_download(repo_id=_HF_REPO, local_dir=str(d))
            logger.info("IndexTTS-2 模型就绪(%s)——下次语音引擎选择/重启后启用", d)
        except Exception as exc:  # noqa: BLE001
            logger.info("IndexTTS-2 模型拉取失败(下次启动再试): %s", exc)

    threading.Thread(target=_fetch, name="indextts-fetch", daemon=True).start()


class IndexTTSEngine(EdgeTTSEngine):
    """IndexTTS2 零样本克隆引擎(播放/打断继承 EdgeTTSEngine)。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tts: Optional[Any] = None

    def available(self) -> bool:
        """包可导入 + 模型就位 + 参考音频已配置且存在,三者齐备才可用。"""
        try:
            import indextts  # noqa: F401
        except Exception:
            logger.info("IndexTTS 包未安装(pip install indextts / 官方 uv sync)")
            return False
        if not model_files_present():
            kick_background_fetch()
            logger.info(
                "IndexTTS-2 模型未就位(%s);设 GALAXY_INDEXTTS_AUTOFETCH=1 "
                "可后台拉取,或手动 hf download %s --local-dir=%s",
                _model_dir(),
                _HF_REPO,
                _model_dir(),
            )
            return False
        ref = _ref_audio()
        if not ref or not os.path.exists(ref):
            logger.warning(
                "IndexTTS 需要参考音频做零样本克隆:请设 GALAXY_INDEXTTS_REF_AUDIO " "指向一段目标音色的 wav(当前: %r)",
                ref,
            )
            return False
        return True

    def _ensure_loaded(self) -> Any:
        if self._tts is None:
            d = str(_model_dir())
            use_fp16 = os.environ.get("GALAXY_INDEXTTS_FP16", "0").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            try:
                # IndexTTS2(主线,情感+时长控制)
                from indextts.infer_v2 import IndexTTS2

                self._tts = IndexTTS2(
                    cfg_path=os.path.join(d, "config.yaml"),
                    model_dir=d,
                    use_fp16=use_fp16,
                )
                logger.info("IndexTTS2 引擎已加载(model_dir=%s, fp16=%s)", d, use_fp16)
            except ImportError:
                # 旧版包只有 v1 入口——降级加载,不带情绪参数
                from indextts.infer import IndexTTS

                self._tts = IndexTTS(cfg_path=os.path.join(d, "config.yaml"), model_dir=d)
                logger.info("IndexTTS(v1) 引擎已加载——情绪控制参数将被忽略")
        return self._tts

    def _emotion_kwargs(self) -> dict:
        """按 README 四种方式组装情绪参数;未配置则空(纯克隆)。"""
        kw: dict = {}
        emo_audio = os.environ.get("GALAXY_INDEXTTS_EMO_AUDIO", "").strip()
        if emo_audio and os.path.exists(emo_audio):
            kw["emo_audio_prompt"] = emo_audio
        emo_text = os.environ.get("GALAXY_INDEXTTS_EMO_TEXT", "").strip()
        if emo_text:
            kw["emo_text"] = emo_text
            kw["use_emo_text"] = True
        elif os.environ.get("GALAXY_INDEXTTS_USE_EMO_TEXT", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            kw["use_emo_text"] = True  # 由台词语义自动推断
        try:
            kw["emo_alpha"] = float(os.environ.get("GALAXY_INDEXTTS_EMO_ALPHA", "0.6"))
        except (TypeError, ValueError):
            kw["emo_alpha"] = 0.6
        return kw

    async def synthesize(
        self,
        text: str,
        output_path: Optional[str] = None,
        voice: Optional[str] = None,  # 接口兼容;IndexTTS 的"音色"来自参考音频
        rate: Optional[str] = None,  # 接口兼容
    ) -> str:
        def _run() -> str:
            tts = self._ensure_loaded()
            path = output_path
            if not path:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                path = tmp.name
            kwargs = {
                "spk_audio_prompt": _ref_audio(),
                "text": text,
                "output_path": path,
                "verbose": False,
                **self._emotion_kwargs(),
            }
            try:
                tts.infer(**kwargs)
            except TypeError:
                # 版本间签名漂移(v1 无情绪参数/字段更名):退到最小参数集,
                # 宁可丢情绪也要出声。
                logger.debug("IndexTTS infer 签名不匹配,退最小参数集重试")
                try:
                    tts.infer(
                        spk_audio_prompt=_ref_audio(),
                        text=text,
                        output_path=path,
                    )
                except TypeError:
                    # v1 位置参数形态: infer(voice, text, output_path)
                    tts.infer(_ref_audio(), text, path)
            return path

        # 自回归大模型推理,重 CPU/GPU,放线程,绝不占事件循环。
        path = await asyncio.to_thread(_run)
        logger.debug("IndexTTS synthesized: '%s...' → %s", text[:30], path)
        return path
