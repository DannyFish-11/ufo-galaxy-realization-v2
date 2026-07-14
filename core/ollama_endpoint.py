"""core/ollama_endpoint.py — Ollama 服务地址解析(唯一属主)
===========================================================

**为什么需要它:**

历史上 ollama 的 base_url 在十几处各自解析,每处都要自己处理两个坑:

1. **空值绕过默认**:``.env`` 里 ``OLLAMA_URL=``(空字符串,``.env.example`` 生成的
   默认就是空)会让 ``os.environ.get("OLLAMA_URL", "http://localhost:11434")`` 返回
   ``""`` —— 而不是默认值(默认值只在 key 完全不存在时生效)。空串一路穿透到
   httpx,请求时炸 ``InvalidURL: Request URL is missing an 'http://' or 'https://'
   protocol``。

2. **缺协议头**:用户在面板只填 ``localhost:11434``(无 ``http://``),同样炸。

十几处各写各的兜底 = 多套标准,只要有一处漏了或将来被误改回 ``.get(默认)``,
那条报错就复活。这个模块把解析收口成【一扇门】:所有取 ollama 地址的地方都
调 :func:`resolve_ollama_base_url`,保证永远拿到带协议头、非空的合法 URL。
"""

from __future__ import annotations

import os
from typing import Optional

OLLAMA_DEFAULT_URL = "http://localhost:11434"


def normalize_ollama_url(raw: Optional[str]) -> str:
    """把任意 ollama 地址输入归一为合法 URL(空/缺协议头/垃圾值都兜底)。

    - 空 / None / 纯空白  → ``http://localhost:11434``
    - ``localhost:11434`` → ``http://localhost:11434``(补协议头)
    - ``http(s)://...``   → 原样(去尾部斜杠)
    - **垃圾值**(含空白符、或以 ``#`` 开头)→ 默认地址。真机根因:python-dotenv
      会把「``OLLAMA_URL=   # e.g. http://...``」这种【空值+行内注释】整段注释当成
      值('# e.g. http://localhost:11434'),此前本函数给它补协议头后变成
      ``http://# e.g. ...``——以 http:// 开头骗过全部 startswith 检查,httpx 却把
      # 后全解析成 fragment、host 为空,最终发出缺协议头请求。URL 里不可能有
      裸空格、也不可能以 # 开头,一律判垃圾回落默认。
    """
    val = (raw or "").strip()
    if not val or val.startswith("#") or any(ch.isspace() for ch in val):
        return OLLAMA_DEFAULT_URL
    if not val.startswith(("http://", "https://")):
        val = f"http://{val}"
    return val.rstrip("/")


def resolve_ollama_base_url(dashboard_value: Optional[str] = None) -> str:
    """解析当前应使用的 ollama base_url(唯一入口)。

    优先级:显式传入(如 Dashboard/UnifiedConfig 的值)> 环境变量 OLLAMA_URL >
    默认 http://localhost:11434。任一层为空都继续兜底,绝不返回空或无协议头的值。
    """
    for candidate in (dashboard_value, os.environ.get("OLLAMA_URL", "")):
        if candidate and str(candidate).strip():
            return normalize_ollama_url(str(candidate))
    return OLLAMA_DEFAULT_URL
