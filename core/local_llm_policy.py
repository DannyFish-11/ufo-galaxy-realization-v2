"""本机模型(Ollama)的超时规矩:**慢不是故障**。

所有者 Windows 真机日志(无独显,gemma4:e2b 软件推理)::

    15:27:52 | WARNING | Timeout from ollama (attempt 1/3), retrying in 1.0s

云端适配器那套「超时就重发」放在本机模型上是反的:

* 本机模型超时几乎总是因为它**还在算** —— CPU 上把一万多 token 的提示预填一遍就要一两分钟 ——
  不是网络丢包;原先的读期限是 60 秒,一段长提示还没开始出字就到点了;
* 重发 = 把同一段提示再排进 Ollama 的队列**从头算一遍**。上一份还没算完(Ollama 不知道我们已经
  放弃了),负载翻倍,下一次只会更慢。流式那条路超时后再退回非流式,是同一件事。

所以本机这一家:连接给短期限(连不上就是 Ollama 没起来,快点说出来),读给长期限(在算就等它算完),
超时**不重发**、也不换一条路再算一遍。云端各家照旧(``BaseProviderAdapter``)。
"""

from __future__ import annotations

from typing import Any

import httpx

#: 本机模型一次回答最长等多久(秒)。软件推理下长提示光预填就要一两分钟,再加生成。
READ_TIMEOUT_S = 300.0
#: 连不上就是没起来 —— 不用等。
CONNECT_TIMEOUT_S = 5.0


def local_timeout(configured: float) -> httpx.Timeout:
    """读期限取配置值与 ``READ_TIMEOUT_S`` 里大的那个;连接期限短。"""
    read = max(float(configured or 0.0), READ_TIMEOUT_S)
    return httpx.Timeout(connect=CONNECT_TIMEOUT_S, read=read, write=60.0, pool=10.0)


class LocalModelTimeouts:
    """混进本机模型的适配器(放在 ``BaseProviderAdapter`` 前面):长读期限、超时不重发。"""

    RETRY_ON_TIMEOUT = False
    config: Any
    _client: Any

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=local_timeout(self.config.timeout))
        return self._client
