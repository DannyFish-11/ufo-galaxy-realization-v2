"""整份落盘挪出事件循环,而且新的不会被旧的盖掉。

设备每来一帧状态 / 断一次连,有的存储就把**整份**重新编码写盘一次。在事件循环里做,感知帧、音频、对话流都跟着停
(第 17 轮真跑:``android_device_state_store`` 断连时卡住循环 0.6 秒 —— ``json.dump`` 流式写走的是纯 Python 编码器)。

:class:`OffLoopWriter` 只管**在哪儿、按什么顺序**写,不管写什么:

* 调用方在自己的锁里把这一刻的完整内容编成文本(C 编码器,一口气编完),交给 :meth:`OffLoopWriter.submit`;
* 在事件循环里 → 交给工作线程写;不在(脚本、测试、工作线程里)→ 就地写,写完才返回(与原来一样);
* 每次交出去的内容带一个先后号,写的时候比它新的已经写过就不写 —— 工作线程谁先跑完不一定,旧的不会盖掉新的;
* :meth:`OffLoopWriter.drop_pending` 让已经交出去、还没写的都不再写(清盘时用,免得清完又被写回来)。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable

logger = logging.getLogger("Galaxy.PersistOffLoop")


class OffLoopWriter:
    def __init__(self, write: Callable[[str], None], what: str) -> None:
        self._fn = write
        self._what = what
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._issued = 0
        self._written = 0
        self._dropped = 0

    def submit(self, text: str) -> None:
        """把这一份写下去:在事件循环里交给工作线程,不在就地写。永不抛出。"""
        with self._lock:
            self._issued += 1
            seq = self._issued
        try:
            asyncio.get_running_loop().run_in_executor(None, self._write, seq, text)
        except RuntimeError:  # 不在事件循环里,或停机途中执行器已关:就地写
            self._write(seq, text)

    def drop_pending(self) -> None:
        """已经交出去、还没写的都不再写;正在写的那一份等它写完才返回(之后删文件不会被它写回来)。"""
        with self._lock:
            self._dropped = self._issued
        with self._write_lock:
            pass

    def _write(self, seq: int, text: str) -> None:
        with self._write_lock:
            with self._lock:
                if seq <= max(self._written, self._dropped):
                    return  # 更新的一份已经写过了,或者清盘时说了不再写
                self._written = seq
            try:
                self._fn(text)
            except Exception as exc:  # noqa: BLE001 — 落盘失败不反噬调用方;下一次照样写
                logger.warning("%s 没写成: %s", self._what, exc)


__all__ = ["OffLoopWriter"]
