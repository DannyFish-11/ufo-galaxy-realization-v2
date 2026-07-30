#!/usr/bin/env python3
"""云端 API 全链路核验:面板填的 → 路由器读到的 → 上游真实认账的,是不是同一批。

为什么需要这个脚本
------------------
「面板亮绿标说已配置,路由器却根本不读它」这类不一致在本仓库出现过不止一次
(见 PR #1543 修的 SONAR_API_KEY)。而型号字符串写错的后果同样是静默的:注册成功、
选路成功,直到真正发起请求才 404。这两类问题都**只能靠对着上游实测**才能发现,
静态检查看不出来。

本脚本把三层对齐一次查清:

1. **静态层**(``--offline`` 即可,不需要网络)
   面板 schema(``CONFIG_SCHEMA``)、面板「模型」tab 的输入框清单(``ModelsTab.tsx``)、
   密钥落盘名单(``_SECRET_MODEL_KEYS``)、路由器的 ``PROVIDER_REGISTRY`` —— 四份清单
   互相之间有没有漂移。
2. **密钥解析层**
   走**路由器自己的** ``_get_key()``(Dashboard/面板 → CredentialVault → 环境变量,
   并过滤占位符),而不是另写一遍 ``os.getenv``。这样这一步验的就是生产路径本身:
   面板里填的那把 key,路由器到底拿不拿得到。
3. **上游实测层**(需要网络)
   拿真 key 打各家**官方** ``/models`` 端点,把上游认账的型号清单与
   ``PROVIDER_REGISTRY`` 里写的逐个比对。registry 里有、上游没有的型号会被单独列出 ——
   那就是将来会 404 的那些。

安全
----
**绝不打印任何密钥值。** 只输出"是否已配置 / 长度 / 是否占位符"。也不把 key 写进
任何文件或日志。

用法
----
    python scripts/verify_provider_apis.py --offline      # 只做静态对齐检查
    python scripts/verify_provider_apis.py                # 静态 + 上游实测
    python scripts/verify_provider_apis.py --only moonshot,deepseek
    python scripts/verify_provider_apis.py --json         # 机器可读

退出码:0 全部通过;1 发现问题(便于挂进 CI 或 pre-push)。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MODELS_TAB = REPO_ROOT / "electron/renderer/panel/src/components/ModelsTab.tsx"

#: 各家取型号清单的方式。绝大多数是 OpenAI 兼容的 GET {base_url}/models + Bearer;
#: Anthropic 用自己的鉴权头,单独一条。
_ANTHROPIC_HEADERS = {"anthropic-version": "2023-06-01"}


def _panel_keys() -> set:
    """面板「模型」tab 里真实存在输入框的那些 key。"""
    if not MODELS_TAB.exists():
        return set()
    src = MODELS_TAB.read_text(encoding="utf-8")
    return set(re.findall(r"\b(?:key|extraKey)\s*:\s*'([A-Z][A-Z0-9_]*)'", src))


def _mask(value: str) -> str:
    """只描述,不泄露。"""
    from core.credential_vault import PLACEHOLDER_PREFIXES

    if not value:
        return "未配置"
    if value.lower().startswith(PLACEHOLDER_PREFIXES):
        return f"占位符(len={len(value)})"
    return f"已配置(len={len(value)})"


def static_audit() -> Tuple[List[str], Dict[str, Any]]:
    """四份清单的互相对齐。返回 (问题列表, 明细)。"""
    from core.multi_llm_router import PROVIDER_REGISTRY
    from core.routes.config import _SECRET_MODEL_KEYS, CONFIG_SCHEMA

    problems: List[str] = []
    panel = _panel_keys()

    def env_keys(spec: Dict[str, Any]) -> List[str]:
        ks = [spec.get("env_key")]
        alt = spec.get("alt_env")
        if isinstance(alt, str):
            ks.append(alt)
        elif isinstance(alt, (list, tuple)):
            ks.extend(alt)
        return [k for k in ks if k]

    for spec in PROVIDER_REGISTRY:
        name = spec["name"]
        for k in env_keys(spec):
            if k not in CONFIG_SCHEMA:
                problems.append(f"{name}: {k} 不在 CONFIG_SCHEMA —— 面板存不进去(POST /api/config 会 400)")
            if k.endswith("_API_KEY") and k not in _SECRET_MODEL_KEYS:
                problems.append(f"{name}: {k} 不在 _SECRET_MODEL_KEYS —— 会被【明文】写进 .env")
        primary = spec.get("env_key")
        if primary and panel and primary not in panel:
            problems.append(f"{name}: {primary} 在面板「模型」tab 里没有输入框 —— 用户没法填")

    detail = {
        "registry_providers": len(PROVIDER_REGISTRY),
        "config_schema_keys": len(CONFIG_SCHEMA),
        "secret_keys": len(_SECRET_MODEL_KEYS),
        "panel_input_keys": len(panel),
    }
    return problems, detail


def _fetch_models(base_url: str, api_key: str, *, protocol: Optional[str], timeout: float) -> Tuple[str, Any]:
    """打上游 /models。返回 (状态描述, 型号列表或错误文本)。"""
    url = base_url.rstrip("/") + "/models"
    if protocol == "anthropic":
        headers = {"x-api-key": api_key, **_ANTHROPIC_HEADERS}
    else:
        headers = {"Authorization": f"Bearer {api_key}"}
    headers["User-Agent"] = "galaxy-provider-verify"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read(400).decode("utf-8", "replace").replace("\n", " ")
        return f"HTTP {exc.code}", body[:200]
    except Exception as exc:  # noqa: BLE001 —— 网络/DNS/代理各种异常一律如实报出
        return "连接失败", f"{type(exc).__name__}: {str(exc)[:200]}"
    # OpenAI 兼容与 Anthropic 都是 {"data": [{"id": ...}, ...]}
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return "响应无法解析", json.dumps(payload)[:200]
    ids = [it.get("id") for it in items if isinstance(it, dict) and it.get("id")]
    return "OK", sorted(ids)


def live_probe(only: Optional[set], timeout: float) -> Tuple[List[str], List[Dict[str, Any]]]:
    """对每家已配置 key 的 provider 打官方 /models,并与 registry 比对型号。"""
    from core.multi_llm_router import PROVIDER_REGISTRY, get_llm_router

    router = get_llm_router()
    problems: List[str] = []
    rows: List[Dict[str, Any]] = []

    for spec in PROVIDER_REGISTRY:
        name = spec["name"]
        if only and name not in only:
            continue
        # 关键:走【路由器自己的】解析链路,而不是另写一遍 os.getenv。
        # 这样这一步验的就是"面板里填的那把 key,生产代码到底拿不拿得到"。
        try:
            api_key = router._get_key(name) or ""
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: 解析 key 时异常 {type(exc).__name__}: {exc}")
            api_key = ""
        row: Dict[str, Any] = {"provider": name, "key": _mask(api_key), "declared": spec.get("models") or []}
        if not api_key or "占位符" in row["key"]:
            row["status"] = "跳过(无有效 key)"
            rows.append(row)
            continue
        status, result = _fetch_models(spec["base_url"], api_key, protocol=spec.get("protocol"), timeout=timeout)
        row["status"] = status
        if status != "OK":
            row["error"] = result
            problems.append(f"{name}: {status} —— {result}")
            rows.append(row)
            continue
        upstream = set(result)
        row["upstream_count"] = len(upstream)
        missing = [m for m in row["declared"] if m not in upstream]
        row["missing_upstream"] = missing
        if missing:
            problems.append(
                f"{name}: registry 里这些型号上游不认(实际调用会 404): {missing}"
                f" —— 上游示例: {sorted(upstream)[:6]}"
            )
        rows.append(row)
    return problems, rows


def main() -> int:
    ap = argparse.ArgumentParser(description="云端 API 全链路核验(面板 → 路由器 → 上游)")
    ap.add_argument("--offline", action="store_true", help="只做静态对齐检查,不联网")
    ap.add_argument("--only", default="", help="只查这几家(逗号分隔的 provider 名)")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None

    static_problems, detail = static_audit()
    live_problems: List[str] = []
    rows: List[Dict[str, Any]] = []
    if not args.offline:
        live_problems, rows = live_probe(only, args.timeout)

    if args.json:
        print(
            json.dumps(
                {
                    "static": {"problems": static_problems, "detail": detail},
                    "live": {"problems": live_problems, "rows": rows},
                    "ok": not (static_problems or live_problems),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not (static_problems or live_problems) else 1

    print("═" * 78)
    print("静态对齐(面板 schema / 面板输入框 / 密钥名单 / 路由器 registry)")
    print("═" * 78)
    print(
        f"  registry {detail['registry_providers']} 家 · CONFIG_SCHEMA {detail['config_schema_keys']} 键 · "
        f"密钥名单 {detail['secret_keys']} · 面板输入框 {detail['panel_input_keys']}"
    )
    if static_problems:
        for p in static_problems:
            print(f"  ❌ {p}")
    else:
        print("  ✅ 四份清单无漂移")

    if args.offline:
        print("\n(--offline:未做上游实测。型号字符串是否被上游认账【只能联网才能验】。)")
        return 1 if static_problems else 0

    print()
    print("═" * 78)
    print("上游实测(key 经路由器自己的 Dashboard → Vault → env 链路解析)")
    print("═" * 78)
    for r in rows:
        line = f"  {r['provider']:12} {r['key']:20} {r['status']}"
        if r.get("upstream_count") is not None:
            line += f"  上游 {r['upstream_count']} 个型号"
        print(line)
        if r.get("error"):
            print(f"               ↳ {r['error']}")
        if r.get("missing_upstream"):
            print(f"               ↳ ❌ 上游不认: {r['missing_upstream']}")
    ok = not (static_problems or live_problems)
    print()
    print("✅ 全链路贯通" if ok else f"❌ 发现 {len(static_problems) + len(live_problems)} 个问题")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
