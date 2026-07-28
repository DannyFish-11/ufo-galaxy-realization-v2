"""core.hf_endpoint — HuggingFace 下载源快速健康探测与择优
==========================================================

根因(所有者 Windows 真机日志实证):HF_ENDPOINT 被无条件默认成 hf-mirror.com,
该镜像不可达时 huggingface_hub 对**每个文件**先 HEAD(3s 超时)再指数退避重试
5 次;kokoro(2 个文件)+ faster-whisper(多个文件)叠加,控制台被
"Retrying in Ns [Retry x/5]" 刷屏、启动被拖住数分钟——而这一切只为了一个
"源根本不通"的事实。

本模块把"源通不通"收敛为**一次**进程级探测(≤2s/候选):

- 候选仅限两个公共端点 hf-mirror.com / huggingface.co,按当前 HF_ENDPOINT
  偏好排序,谁先通用谁(择优);探测结果写回 os.environ["HF_ENDPOINT"]。
- 用户显式配了**自建/自定义**镜像(不在上述两者之列)→ 尊重、不做失败转移,
  只探测它本身的可达性。
- 全部不可达 → 返回 ""(调用方跳过预取/只用本地缓存,快速失败懒加载降级),
  并负缓存 5 分钟,期间任何调用方都不再发起网络探测——彻底消灭重试刷屏。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger("Galaxy.HFEndpoint")

# 两个公共端点:允许互为备选(择优);其余端点视为用户自建镜像,尊重不切换。
_PUBLIC_ENDPOINTS = ("https://hf-mirror.com", "https://huggingface.co")
_NEG_CACHE_TTL = 300.0  # 全不可达的负缓存(秒):5 分钟内不再重复探测/刷日志

_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "endpoint": None}  # endpoint: str(可达) / ""(全不可达) / None(未探测)


def _probe(base: str, timeout: float) -> bool:
    """单个端点连通性探测:HEAD 根路径,timeout 秒内有任何 HTTP 响应即算可达。"""
    try:
        req = urllib.request.Request(base, method="HEAD", headers={"User-Agent": "Galaxy-Probe"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        # 403/405 等也说明 TCP/TLS/HTTP 全通 —— 只测连通性,不测语义。
        return True
    except Exception:
        return False


def _candidates() -> list:
    """按偏好排出待探测端点。"""
    if os.environ.get("GALAXY_HF_MIRROR", "1").strip().lower() in ("0", "false", "no", "off"):
        # 显式关镜像 → 只认官方域名(尊重用户,不再回落镜像)。
        return ["https://huggingface.co"]
    current = (
        os.environ.get("HF_ENDPOINT", "").strip()
        or os.environ.get("GALAXY_HF_ENDPOINT", "").strip()
        or _PUBLIC_ENDPOINTS[0]
    ).rstrip("/")
    if current not in _PUBLIC_ENDPOINTS:
        # 自建/自定义镜像:尊重配置,只探测它自己,不做失败转移。
        return [current]
    # 公共端点:当前偏好在前,另一个公共端点作备选(择优)。
    return [current] + [e for e in _PUBLIC_ENDPOINTS if e != current]


def pick_endpoint(timeout: float = 2.0, force: bool = False) -> str:
    """返回一个**探测可达**的 HF 下载端点;全不可达返回 ""。

    进程级缓存:可达结果缓存整个进程生命周期(下载源在一次启动内不抖动);
    不可达结果负缓存 ``_NEG_CACHE_TTL`` 秒,避免每个调用方都重复付探测成本。
    选中的端点会写回 ``os.environ["HF_ENDPOINT"]``,让 huggingface_hub /
    faster-whisper 等所有下游库统一生效。
    """
    with _lock:
        cached = _cache["endpoint"]
        if not force and cached is not None:
            if cached:  # 可达结果:进程内一直有效
                return cached
            if time.monotonic() - _cache["ts"] < _NEG_CACHE_TTL:  # 负缓存未过期
                return ""
        cands = _candidates()
        for ep in cands:
            if _probe(ep, timeout):
                if ep != cands[0]:
                    logger.warning(
                        "HF 下载源 %s 不可达,已自动切换到 %s(%.0fs 内探测择优)",
                        cands[0], ep, timeout,
                    )
                os.environ["HF_ENDPOINT"] = ep
                _cache.update(ts=time.monotonic(), endpoint=ep)
                return ep
        # 全不可达:一次性告警 + 负缓存,调用方据此跳过预取/走本地缓存,
        # 绝不再让 huggingface_hub 的 5 次指数重试 × N 个文件刷屏。
        logger.warning(
            "HF 下载源均不可达(%s),%d 分钟内跳过模型下载/预取,只用本地缓存;"
            "网络恢复后自动重试(可设 HF_ENDPOINT 指向可达镜像)",
            " / ".join(cands), int(_NEG_CACHE_TTL // 60),
        )
        _cache.update(ts=time.monotonic(), endpoint="")
        return ""


def endpoint_reachable(timeout: float = 2.0) -> bool:
    """是否存在可达的 HF 下载端点(带缓存,见 pick_endpoint)。"""
    return bool(pick_endpoint(timeout=timeout))
