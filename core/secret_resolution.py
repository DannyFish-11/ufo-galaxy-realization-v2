"""按【环境变量名】解析密钥/配置值,走仓库既有的权威顺序。

为什么需要它
------------
本仓库解析一把云端 key 的权威顺序是 **面板/Dashboard → CredentialVault → 环境变量**,
并过滤未编辑的占位符。这套顺序**只长在** ``core/multi_llm_router.py::_get_key()`` 里,
而那个函数是按**内部 provider 短名**(``"deepseek"``)查的,依赖
``_PROVIDER_ENV_KEY_MAP`` 做短名→长名映射。

语音双工层要解析的是 ``GALAXY_REALTIME_API_KEY`` 这种**不属于任何 provider**的键名,
套不进那个入口。于是它当时直接写了 ``os.getenv(...)`` —— 只覆盖第三层,并且**没有过
滤占位符**。后果很具体:``main.py`` 启动时会把 ``.env`` 里的值(含
``your_openai_api_key_here`` 这种未编辑模板)灌进 ``os.environ``,双工层因此会把模板
文字当成真 key,拿去连 ``wss://api.openai.com/v1/realtime``,得到一个 401 —— 而正确
行为是认出"这不是真 key"、安静退回回合制链路。

本模块把那套顺序抽成**按键名**可用的形式,让这类"不属于 provider 的密钥"也能走同一条
权威链路,而不是各处再抄一遍 ``os.getenv``。

刻意不做的事
------------
**不**替代 ``multi_llm_router._get_key()``。那个函数还额外处理短名/长名双查等 provider
特有的历史包袱,把它改掉风险大于收益。本模块与它是**同序不同入口**:一个按 provider
短名,一个按环境变量名。两者的占位符判据共用 ``credential_vault.PLACEHOLDER_PREFIXES``,
不另立一份。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("Galaxy.SecretResolution")


def is_placeholder(value: Optional[str]) -> bool:
    """这个值是不是"未编辑的模板文字"。

    判据复用 ``credential_vault.PLACEHOLDER_PREFIXES``(``your_``/``change_me``/``<``…),
    **不另立一份** —— 两份前缀表一旦漂移,就会出现"路由器认为是占位符、双工层认为是真
    key"这种分裂。
    """
    if not value:
        return True
    try:
        from core.credential_vault import PLACEHOLDER_PREFIXES
    except Exception as exc:  # noqa: BLE001 —— 导入失败不能让调用方崩
        logger.debug("占位符前缀表不可用,退化为仅判空: %s", exc)
        return False
    return str(value).strip().lower().startswith(PLACEHOLDER_PREFIXES)


def _from_panel(key_name: str) -> str:
    """第一层:面板 / Dashboard(经 UnifiedConfig,含 runtime/config.json 与 secrets.env)。"""
    try:
        from core.unified_config import config as _cfg
    except Exception as exc:  # noqa: BLE001
        logger.debug("UnifiedConfig 不可用: %s", exc)
        return ""
    # UnifiedConfig.get() 内部会尝试多种键名变体(原样/小写/大写/点线互换/取末段),
    # 所以这里直接给长名即可,不必自己拼变体。
    for candidate in (f"api_keys.{key_name}", key_name):
        try:
            val = _cfg.get(candidate, "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("读 UnifiedConfig[%s] 失败: %s", candidate, exc)
            continue
        if val and not is_placeholder(str(val)):
            return str(val)
    return ""


def _from_vault(key_name: str) -> str:
    """第二层:CredentialVault(``GALAXY_SECRET_BACKEND=vault`` 时是独立存储)。"""
    try:
        from core.credential_vault import get_vault

        val = get_vault().get_credential(key_name, actor="secret_resolution")
    except Exception as exc:  # noqa: BLE001
        logger.debug("读 CredentialVault[%s] 失败: %s", key_name, exc)
        return ""
    return str(val) if val and not is_placeholder(str(val)) else ""


def _from_env(key_name: str) -> str:
    """第三层:环境变量兜底。

    注意 ``main.py`` 启动时会把 ``runtime/secrets.env`` 与 ``.env`` 灌进 ``os.environ``
    (不覆盖已存在的键),所以这一层实际上也能看到面板保存的值 —— 但**它不过滤占位符**,
    ``.env`` 里未编辑的模板会原样进来。这正是必须在这里判占位符的原因。
    """
    val = os.environ.get(key_name, "")
    return val if val and not is_placeholder(val) else ""


def resolve_secret(*key_names: str) -> str:
    """按权威顺序解析第一个拿得到真值的键名。

    顺序:**面板/Dashboard → CredentialVault → 环境变量**,每层都过滤占位符。

    多个键名按**给定顺序**逐个试完整三层 —— 即"专用键优先于通用键":
    ``resolve_secret("GALAXY_REALTIME_API_KEY", "OPENAI_API_KEY")`` 表示专门为双工配的
    那把优先,没配才退回通用的 OpenAI key。**不是**先在所有键名里试第一层。

    Returns:
        真值;全都拿不到时返回 ``""``(不抛异常 —— 缺配置是预期情形,不是错误)。
    """
    for name in key_names:
        if not name:
            continue
        for layer in (_from_panel, _from_vault, _from_env):
            val = layer(name)
            if val:
                return val
    return ""


def describe_source(key_name: str) -> str:
    """这把 key 是从哪一层拿到的(排查"面板填了却不生效"时用)。

    **只返回层名,绝不返回值本身。**
    """
    if _from_panel(key_name):
        return "panel"
    if _from_vault(key_name):
        return "vault"
    if _from_env(key_name):
        return "env"
    raw = os.environ.get(key_name, "")
    if raw and is_placeholder(raw):
        return "placeholder"
    return "missing"
