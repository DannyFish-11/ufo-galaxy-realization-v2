"""core/ollama_url_sentinel.py — 静默 URL 哨兵(缺协议头请求的定位器)
=================================================================

**它是什么:** 给 ``httpx`` 的 ``send`` 加一层【只观测、不干预】的薄壳。任何
【缺 ``http://`` / ``https://`` 协议头】的请求 URL —— 也就是那个真机反复出现的
``Request URL is missing an 'http://' or 'https://' protocol`` 的根源 —— 一旦出现,
就把**精确的调用栈(file:line)**记进日志,方便一眼定位是哪一处漏网站点。

**设计约束(务必满足):**

- **零行为影响 / 不影响主进程**:安装、检查、日志全部包在 ``try/except`` 里,任何
  异常都吞掉;请求照常交给原始 ``send`` 执行、原来的异常照常抛出。哨兵只是在旁边
  记一笔,绝不改变任何请求结果,也绝不让哨兵自身把主流程带崩。
- **隐蔽 / 平时不显现**:没问题时**零输出**;只有真的抓到缺协议头 URL 才
  ``logger.warning`` 一次,并且**按调用点去重**——同一处只报一次,不刷屏。
- **幂等**:重复 :func:`install` 只装一次;不会二次包裹。
- **可关**:``GALAXY_URL_SENTINEL=0``(或 false/no/off)即禁用,默认开。
"""
from __future__ import annotations

import logging
import os
import time
import traceback
from collections import deque
from typing import Deque, Dict, List, Set

logger = logging.getLogger("Galaxy.UrlSentinel")

_INSTALLED = False
_seen: Set[str] = set()
# 最近抓到的缺协议头 URL(供面板 DiagnosticsDrawer / 诊断端点展示,让用户看得见、
# 能直接复制)。只留最近 20 条,去重后追加,零锁——GIL 下 deque append 足够安全。
_catches: Deque[Dict[str, str]] = deque(maxlen=20)


def _culprit_frame(frames: List[str]) -> str:
    """从调用栈里挑出【最可能是罪魁】的那一帧:最深的、既不在 httpx 也不在本哨兵
    里的应用代码帧(也就是真正拿着坏 URL 去发请求的那处)。取不到就返回空串。"""
    try:
        for line in reversed(frames):
            # 统一分隔符再匹配:Windows 栈里是 site-packages\httpx\_client.py,
            # 只查 "/httpx/" 会漏排 → 界面上"罪魁"显示成 httpx 内部帧(真机复现)。
            low = line.lower().replace("\\", "/")
            if "/httpx/" in low or "ollama_url_sentinel" in low:
                continue
            # traceback.format_stack 的帧首行形如:  File "xxx.py", line N, in fn
            head = line.strip().splitlines()[0].strip()
            if head.startswith("File "):
                return head  # 形如: File "xxx.py", line N, in fn(原样最可读)
    except Exception:  # noqa: BLE001
        pass
    return ""


def recent_catches() -> List[Dict[str, str]]:
    """返回最近抓到的缺协议头 URL 记录(最新在前),供面板/诊断端点展示。"""
    try:
        return list(reversed(_catches))
    except Exception:  # noqa: BLE001
        return []


def _url_missing_scheme(url) -> bool:
    """URL 是否缺 http(s):// 协议头(任何异常都视为『不是』,绝不误伤主流程)。"""
    try:
        s = str(url)
    except Exception:  # noqa: BLE001
        return False
    return bool(s) and not s.startswith(("http://", "https://"))


def _report(url) -> None:
    """把缺协议头 URL 的调用栈记一条日志(按调用点去重、全程静默兜底)。"""
    try:
        frames = traceback.format_stack()[:-2]  # 去掉哨兵自身两帧
        stack = "".join(frames)
        # 用栈末尾几帧当去重键:同一处只报一次
        key = "\n".join(stack.strip().splitlines()[-6:])
        if key in _seen:
            return
        _seen.add(key)
        # 记进环形缓冲,供面板 DiagnosticsDrawer / 诊断端点展示(让用户看得见、能复制)
        try:
            culprit = _culprit_frame(frames)
            _catches.append({
                "ts": time.strftime("%H:%M:%S"),
                "url": str(url),
                "culprit": culprit,
            })
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "[URL-SENTINEL] 抓到缺协议头的请求 URL: %r —— 这正是 "
            "\"Request URL is missing an 'http://' or 'https://' protocol\" 的根源。"
            "以下调用栈最下方即罪魁 file:line:\n%s",
            str(url),
            stack,
        )
    except Exception:  # noqa: BLE001
        pass


def install() -> None:
    """幂等安装 httpx.send 观测层。任何异常都静默吞掉,绝不影响主进程。"""
    global _INSTALLED
    if _INSTALLED:
        return
    if os.environ.get("GALAXY_URL_SENTINEL", "1").strip().lower() in (
        "0", "false", "no", "off",
    ):
        _INSTALLED = True  # 明确禁用,记为已处理,后续不再尝试
        return
    try:
        import httpx
    except Exception:  # noqa: BLE001
        return  # 没有 httpx 就无从观测,静默退出

    try:
        _orig_sync = httpx.Client.send
        _orig_async = httpx.AsyncClient.send

        # 已被包裹过就不再包(幂等,防二次安装叠加)
        if getattr(_orig_sync, "_galaxy_url_sentinel", False):
            _INSTALLED = True
            return

        def _sync_send(self, request, *args, **kwargs):
            try:
                if _url_missing_scheme(getattr(request, "url", "")):
                    _report(request.url)
            except Exception:  # noqa: BLE001
                pass
            return _orig_sync(self, request, *args, **kwargs)

        async def _async_send(self, request, *args, **kwargs):
            try:
                if _url_missing_scheme(getattr(request, "url", "")):
                    _report(request.url)
            except Exception:  # noqa: BLE001
                pass
            return await _orig_async(self, request, *args, **kwargs)

        _sync_send._galaxy_url_sentinel = True  # type: ignore[attr-defined]
        _async_send._galaxy_url_sentinel = True  # type: ignore[attr-defined]
        httpx.Client.send = _sync_send  # type: ignore[method-assign]
        httpx.AsyncClient.send = _async_send  # type: ignore[method-assign]
        _INSTALLED = True
    except Exception:  # noqa: BLE001
        # 装不上也无所谓,主进程照常运行
        pass
