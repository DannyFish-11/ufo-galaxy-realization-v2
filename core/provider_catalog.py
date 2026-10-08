"""面板「模型服务商」目录 —— 每家厂商一张卡片所需的**事实**，一处算出。

## 它治的毛病

旧面板有一份厂商目录（``ModelsTab``：中文名、分组、各家 Key 填哪儿、配没配）。新面板重写时
那个界面被整个删掉，而「全部设置」里只剩 35 行裸环境变量名（``ANTHROPIC_API_KEY`` …），
排在第 12 段、前面隔着三百行别的键 —— 没有厂商名、没有「配了没有」、没有「能不能通」。
人打开设置只看得到「我的模型服务」（自定义端点），就以为各家厂商没法填。

这里把那份目录重建为**后端出事实、面板只画**：

* 厂商清单、型号、默认型号、基础地址、备用 Key 名 —— 全部读 ``PROVIDER_REGISTRY``，不另存一份；
* 参与哪些任务类型的选路 —— 读 ``TASK_ROUTING_PREFERENCES``，不另存一份；
* 本模块自己只存**展示用**的东西：中文名、分组、一句备注。每家都有，由
  ``tests/test_provider_catalog_covers_every_key.py`` 守着：registry 里多一家、或「供应商与密钥」
  里多一个键而没有卡片认领，测试就红 —— 不再出现「后端有它、面板上无处可填」。

## 绝不下发密钥

只给 ``configured``（布尔）与「当前生效的非密钥地址」。长度、前缀、哈希一律不给 ——
这些也是信息。Key 本身仍走既有的 ``POST /api/config``（落 ``runtime/secrets.env``），验证走
``POST /api/v1/models/verify-provider``；这两条路都是现成的，这里不再开第三条写路径。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional

# 展示分组。顺序即面板顺序。
GROUPS: List[Dict[str, str]] = [
    {"id": "intl", "label": "海外厂商"},
    {"id": "cn", "label": "国内厂商"},
    {"id": "aggregate", "label": "聚合与自建"},
    {"id": "local", "label": "本机"},
]

# registry 里每家的展示信息：(中文名, 分组, 一句备注)。型号/地址/Key 名都不在这儿。
_PRESENTATION: Dict[str, tuple] = {
    "openai": ("OpenAI", "intl", "GPT 系列 · 也可填兼容代理/中转的地址"),
    "anthropic": ("Claude（Anthropic）", "intl", "强推理 · 长时程 agent"),
    "google": ("Gemini（Google）", "intl", "多模态 · GEMINI_API_KEY 同样可用"),
    "xai": ("Grok（xAI）", "intl", ""),
    "meta": ("Meta", "intl", "Muse Spark · agentic 多模态"),
    "mistral": ("Mistral", "intl", ""),
    "perplexity": ("Perplexity", "intl", "联网检索 · SONAR_API_KEY 同样可用"),
    "groq": ("Groq", "intl", "极速推理"),
    "agnes": ("Agnes AI", "intl", "全模态 · 免费档"),
    "deepseek": ("DeepSeek", "cn", "推理 · 代码"),
    "qwen": ("通义千问（阿里云百炼）", "cn", "DASHSCOPE_API_KEY 同样可用"),
    "zhipu": ("智谱 GLM", "cn", "按 token 计费 · 海外可换 Z.ai 地址"),
    "zhipu_coding": (
        "智谱 GLM 编码套餐",
        "cn",
        "订阅制 · 仅编码场景 · 与上面的智谱 Key 是两把不同的 Key · 不自动参与选路",
    ),
    "moonshot": ("Kimi（月之暗面）", "cn", "长上下文"),
    "minimax": ("MiniMax", "cn", "长文 · 创意"),
    "step": ("阶跃星辰", "cn", "多模态 · 语音实时"),
    "mimo": ("小米 MiMo", "cn", "快速响应"),
    "openrouter": ("OpenRouter", "aggregate", "多模型聚合路由"),
}

# registry 之外的几类「也要填一个东西」的入口。secret_envs 是密钥，url_envs 是地址（明文），
# router 是它在路由器里的名字（没有 = 不是路由厂商，不报在线状态）。
_EXTRAS: List[Dict[str, Any]] = [
    {
        "id": "ollama",
        "router": "ollama",
        "label": "Ollama（本机主脑）",
        "group": "local",
        "note": "本机跑的模型；选哪个型号在「本机模型」那一档里",
        "secret_envs": [],
        "url_envs": ["OLLAMA_URL"],
    },
    {
        "id": "vllm",
        "label": "本地 vLLM",
        "group": "local",
        "note": "自托管推理服务的地址",
        "secret_envs": [],
        "url_envs": ["LOCAL_VLLM_URL"],
    },
    {
        "id": "oneapi",
        "router": "oneapi",
        "label": "OneAPI 聚合网关",
        "group": "aggregate",
        "note": "聚合在下层，不与直连厂商并列；要同时填地址与 Key",
        "secret_envs": ["ONEAPI_API_KEY"],
        "url_envs": ["ONEAPI_URL"],
    },
    {
        "id": "huggingface",
        "label": "Hugging Face",
        "group": "aggregate",
        "note": "拉取开源模型用的 Token",
        "secret_envs": ["HF_API_TOKEN"],
        "url_envs": [],
    },
    {
        "id": "deepseek_ocr2",
        "label": "识屏 OCR（DeepSeek OCR 2）",
        "group": "aggregate",
        "note": "看图识屏那一步用；默认托管在 Novita，换中转改地址",
        "secret_envs": ["DEEPSEEK_OCR2_API_KEY", "NOVITA_API_KEY"],
        "url_envs": ["DEEPSEEK_OCR2_API_BASE"],
    },
]

# 面板「供应商与密钥」这一类里**不属于任何一张卡片、但仍留在细调页**的键（模型串/开关类）。
# 守卫测试要求：llm 类里每个键，要么被某张卡片认领，要么列在这里 —— 不允许「没人管」。
CATALOG_LEFTOVER_KEYS = frozenset(
    {
        "GALAXY_RESPONSES_PROVIDERS",
        "GEMINI_AUDIO_MODEL",
        "OPENAI_AUDIO_MODEL",
        "OLLAMA_MODEL",  # 本机主脑选哪个型号：在「本机模型」那一档里选，不在厂商卡上
        "DEEPSEEK_OCR2_MODEL",
    }
)

_PLACEHOLDER_HINT = ("sk-YOUR",)


def _is_set(env: Mapping[str, str], name: str) -> bool:
    """与 ``GET /api/config`` 的判据同口径：非空、不是占位串。"""
    from core.credential_vault import PLACEHOLDER_PREFIXES

    val = (env.get(name) or "").strip()
    return bool(val) and not val.lower().startswith(PLACEHOLDER_PREFIXES) and not val.startswith(_PLACEHOLDER_HINT)


def _schema_default(key: str) -> str:
    from core.routes.config_schema_registry import CONFIG_SCHEMA

    return str(CONFIG_SCHEMA.get(key, {}).get("default", "") or "")


def _roles() -> Dict[str, List[str]]:
    """厂商 → 它有资格参与的任务类型（取执行层偏好表，不另存）。"""
    from core.multi_llm_router import TASK_ROUTING_PREFERENCES

    out: Dict[str, List[str]] = {}
    for task, names in TASK_ROUTING_PREFERENCES.items():
        for n in names:
            out.setdefault(n, []).append(task.value)
    return out


def _live(router: Any, name: str) -> Dict[str, Any]:
    """路由器里这家现在的样子。路由器拿不到就如实说 ``None`` —— 不是 False。"""
    if router is None:
        return {"registered": None, "available": None}
    cfg = getattr(router, "providers", {}).get(name)
    if cfg is None:
        return {"registered": False, "available": False}
    try:
        avail = bool(cfg.is_available())
    except Exception:  # noqa: BLE001
        avail = False
    return {"registered": True, "available": avail}


def _registry_card(
    entry: Dict[str, Any], env: Mapping[str, str], roles: Dict[str, List[str]], router: Any
) -> Dict[str, Any]:
    name = entry["name"]
    label, group, note = _PRESENTATION.get(name, (name, "aggregate", ""))
    key_envs = [entry["env_key"], *(entry.get("alt_env") or [])]
    base_env: Optional[str] = entry.get("base_env")
    return {
        "id": name,
        "label": label,
        "group": group,
        "note": note,
        "kind": "registry",
        "key_envs": key_envs,
        # 每个 Key 名各自配没配：别名（GEMINI_API_KEY 等）填过的话，「清除」要能把它也清掉。
        "key_state": {k: _is_set(env, k) for k in key_envs},
        "configured": any(_is_set(env, k) for k in key_envs),
        # 能换地址的（OpenAI 兼容代理/中转、智谱海外 Z.ai）给一个地址输入；留空 = 用 default。
        "url_envs": (
            [{"env": base_env, "value": env.get(base_env) or "", "default": entry.get("base_url", "")}]
            if base_env
            else []
        ),
        "default_model": entry.get("default_model", ""),
        "models": list(entry.get("models") or []),
        "realtime_models": list(entry.get("realtime_models") or []),
        "roles": roles.get(name, []),
        # 没进任何偏好表 = 不自动参与选路（编码套餐就是有意如此），不是漏配。
        "opt_in": name not in roles,
        "live": _live(router, name),
    }


def _extra_card(spec: Dict[str, Any], env: Mapping[str, str], router: Any) -> Dict[str, Any]:
    secrets = list(spec["secret_envs"])
    urls = list(spec["url_envs"])
    if secrets:
        configured = any(_is_set(env, k) for k in secrets)
    else:
        configured = any((env.get(u) or "").strip() for u in urls)
    return {
        "id": spec["id"],
        "label": spec["label"],
        "group": spec["group"],
        "note": spec["note"],
        "kind": "extra",
        "key_envs": secrets,
        "key_state": {k: _is_set(env, k) for k in secrets},
        "configured": configured,
        # 额外入口里的地址键（非密钥）：面板给一个明文输入，值取当前生效的那个。
        "url_envs": [{"env": u, "value": env.get(u) or "", "default": _schema_default(u)} for u in urls],
        "default_model": "",
        "models": [],
        "realtime_models": [],
        "roles": [],
        "opt_in": False,
        # 只有路由器里真有对应名字的（ollama / oneapi）才报在线状态；其余入口不是路由厂商，如实不报。
        "live": _live(router, spec["router"]) if spec.get("router") else {"registered": None, "available": None},
    }


def build_catalog(env: Optional[Mapping[str, str]] = None, router: Any = None) -> Dict[str, Any]:
    """整张目录。纯读：不写环境、不碰网络。"""
    from core.provider_registry import PROVIDER_REGISTRY

    e = env if env is not None else os.environ
    roles = _roles()
    cards: List[Dict[str, Any]] = [_registry_card(x, e, roles, router) for x in PROVIDER_REGISTRY]
    cards += [_extra_card(x, e, router) for x in _EXTRAS]
    return {
        "groups": GROUPS,
        "vendors": cards,
        "configured_count": sum(1 for c in cards if c["configured"]),
        # 卡片已经认领的配置键：面板细调页据此不再重复列一遍。
        "owned_keys": sorted(owned_config_keys()),
    }


def owned_config_keys() -> frozenset:
    """目录卡片认领的全部配置键（Key / 备用 Key / 地址）。"""
    from core.provider_registry import PROVIDER_REGISTRY

    keys = set()
    for entry in PROVIDER_REGISTRY:
        keys.add(entry["env_key"])
        keys.update(entry.get("alt_env") or [])
        if entry.get("base_env"):
            keys.add(entry["base_env"])
    for spec in _EXTRAS:
        keys.update(spec["secret_envs"])
        keys.update(spec["url_envs"])
    return frozenset(keys)
