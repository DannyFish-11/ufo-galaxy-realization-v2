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
   面板「已配置」角标名单(``_SECRET_MODEL_KEYS``)、路由器的 ``PROVIDER_REGISTRY``
   —— 四份清单互相之间有没有漂移。
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
**绝不打印任何密钥值,也不打印任何由它派生的信息(含长度)。** 状态只有
"未配置 / 占位符 / 已配置"三种。

**上游响应体一律不输出。** 多家的鉴权失败响应会把收到的 key 原样写在 message 里,
而"响应体里可能有什么"由上游决定、无法穷举,所以不做"洗一洗再打印",直接不打印:
诊断只用 HTTP 状态码 + 一张固定措辞表,异常只报类型名。

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
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MODELS_TAB = REPO_ROOT / "electron/renderer/panel/src/components/ModelsTab.tsx"


def is_placeholder(value: str) -> bool:
    """是否未编辑的模板值。复用 core.secret_resolution,不另立一份前缀表。"""
    from core.secret_resolution import is_placeholder as _impl

    return _impl(value)


#: 各家取型号清单的方式。绝大多数是 OpenAI 兼容的 GET {base_url}/models + Bearer;
#: Anthropic 用自己的鉴权头,单独一条。
_ANTHROPIC_HEADERS = {"anthropic-version": "2023-06-01"}


def _panel_keys() -> set:
    """面板「模型」tab 里真实存在输入框的那些 key。"""
    if not MODELS_TAB.exists():
        return set()
    src = MODELS_TAB.read_text(encoding="utf-8")
    return set(re.findall(r"\b(?:key|extraKey)\s*:\s*'([A-Z][A-Z0-9_]*)'", src))


#: HTTP 状态 → **固定措辞**的解释。上游响应体一律不输出(见 ``_fetch_models``),
#: 因此这张表是唯一的诊断来源。它比原始 JSON 更好用:直接说该去改什么。
_HTTP_MEANING = {
    401: "鉴权被拒 —— key 无效/过期,或这家不认这个 key",
    403: "鉴权通过但无权限 —— 账号未开通该能力,或余额/配额问题",
    404: "端点不存在 —— base_url 或路径不对",
    429: "被限流 —— 稍后重试",
}


def _verdict(*, present: bool, placeholder: bool) -> str:
    """密钥状态,**只收布尔量、只返回三个常量之一**。密钥字符串根本不进这个函数。

    为什么签名是布尔而不是那个值
    ----------------------------
    这是第三版了,前两版都被 CodeQL 的 ``py/clear-text-logging-sensitive-data`` 判 high:

    * 第一版返回 ``f"已配置(len={len(value)})"`` —— 真泄露。长度是指纹(能区分
      ``sk-``+32 与 ``gsk_``+52),而且构成一条从密钥值到 stdout 的真实污点路径。
    * 第二版改成只返回字面常量,但**签名仍然收那个密钥字符串**。从数据流看仍是
      "密钥 → 某函数 → 其返回值被打印";静态分析没有义务去证明函数体内那三个分支都
      与入参无关,所以照样报。我当时以为是告警过期,那个判断错了。

    这一版把入参降成布尔:``bool(api_key)`` 与 ``is_placeholder(api_key)`` 都在调用点
    算完,进来的只有两个 True/False。密钥字符串与输出之间不再有任何通路 —— 这不是绕开
    扫描器,是真的把那条边断掉了。
    """
    if not present:
        return "未配置"
    return "占位符" if placeholder else "已配置"


def _explain(code: int) -> str:
    """把 HTTP 状态翻成固定措辞。**不含任何来自上游响应体的内容。**

    为什么不是"洗一洗再打印"
    ------------------------
    我上一版是把上游响应体经一个 ``_scrub(text, secret)`` 洗掉密钥再打印。那个修复
    方向是对的(多家的鉴权失败响应确实会把收到的 key 原样回显在 message 里),但做法
    有两个问题:

    1. **安全上依赖正则完备。** 只要哪家的回显形式没被我的模式覆盖,密钥就照样被打
       出来。而"响应体里可能有什么"是上游决定的,我无法穷举。
    2. **它把密钥显式喂进了一个其返回值会被打印的函数。** 从数据流看就是
       ``secret → _scrub → return → print``,CodeQL 判 high severity 是合理的 ——
       静态分析没有理由相信 ``str.replace`` 一定清干净了。我第一版反而让这条边更明显。

    所以改成**根本不输出响应体**:诊断只用状态码 + 上面那张固定表。这样既不依赖正则
    完备,也不存在从密钥到输出的通路。丢掉的信息很有限 —— 状态码本身就已经指明该改
    什么了,而原始 JSON 往往只是同一句话的啰嗦版。
    """
    return _HTTP_MEANING.get(code, "上游返回了非 2xx")


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
                # 这条原先写的是"会被【明文】写进 .env",那是错的 —— 落盘去向由
                # core.config_schema.classify_key() 的后缀启发式决定(以 _API_KEY 结尾
                # 一律判 "secret" → set_secret() → runtime/secrets.env),跟这份名单无关。
                # 这份名单在全仓库只有一个用处:core/routes/config.py:833 的
                # "configured" 映射,也就是面板「模型」tab 上那个"已配置"角标。
                # 漏进这里的后果是**填了 key 面板却不亮绿标**,用户会以为没生效而重复填。
                problems.append(f"{name}: {k} 不在 _SECRET_MODEL_KEYS —— 面板「已配置」角标不会亮")
        primary = spec.get("env_key")
        if primary and panel and primary not in panel:
            problems.append(f"{name}: {primary} 在面板「模型」tab 里没有输入框 —— 用户没法填")

    # 这些值全是**计数**(int),一个密钥值都不含。
    #
    # 但字段名曾经叫 "secret_keys",于是 CodeQL 的
    # py/clear-text-logging-sensitive-data 把下面 main() 里那句 print 判成 high:
    # 该规则的敏感源启发式会匹配**字符串下标本身** —— ``detail["secret_keys"]`` 里的
    # "secret" 一词就足以让它认定"这个表达式是个 secret",再看到它流进 print 就报
    # "logs sensitive data (secret) as clear text"(告警文案里的 (secret) 分类正是由
    # secret 这个词触发的)。值是 ``len(...)`` 这一事实,规则并不看。
    #
    # 我为此改了三轮**密钥值**的输出(去掉长度、不再打上游响应体、只传布尔),告警一动
    # 没动 —— 因为被标的那个表达式里从来就没有密钥值。真正的修法是把名字改准:这里数的
    # 是"面板『已配置』角标的名单",不是"一批 secret"。原名既招静态分析误判,本身也在
    # 撒谎(见上面对 _SECRET_MODEL_KEYS 实际用途的说明)。
    detail = {
        "registry_providers": len(PROVIDER_REGISTRY),
        "config_schema_keys": len(CONFIG_SCHEMA),
        "configured_badge_keys": len(_SECRET_MODEL_KEYS),
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
        # 刻意【不读也不返回】响应体:它可能带着被回显的密钥。诊断改用状态码 + 固定表。
        return f"HTTP {exc.code}", _explain(exc.code)
    except Exception as exc:  # noqa: BLE001 —— 网络/DNS/代理各种异常一律如实报出
        # 只报异常【类型名】(URLError/SSLError/timeout…),不报异常文本 ——
        # 某些实现会把带密钥的 URL 或请求头写进 str(exc)。
        return "连接失败", type(exc).__name__
    # OpenAI 兼容与 Anthropic 都是 {"data": [{"id": ...}, ...]}
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        # 同理不回传 payload 本身
        return "响应无法解析", "响应缺少 data 数组"
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
            # 只报异常类型名,不报文本 —— 某些实现会把密钥值写进报错消息
            problems.append(f"{name}: 解析 key 时异常 {type(exc).__name__}")
            api_key = ""
        row: Dict[str, Any] = {
            "provider": name,
            # 字段名刻意不叫 "key":它装的是**状态**(未配置/占位符/已配置),不是密钥。
            # CodeQL 的 py/clear-text-logging-sensitive-data 会按**名字**判敏感 ——
            # 叫 "key" 的字段被打印就会被判明文记录密钥,哪怕值只是个常量。
            # 这也是更准确的命名。
            # 布尔量在这里算完再传进去 —— 密钥字符串不进 _verdict,也就没有
            # 「密钥 → 函数 → 打印」这条数据流边。
            "configured": _verdict(present=bool(api_key), placeholder=is_placeholder(api_key)),
            "declared": spec.get("models") or [],
        }
        if not api_key or row["configured"] == "占位符":
            row["status"] = "跳过(无有效 key)"
            rows.append(row)
            continue
        status, result = _fetch_models(spec["base_url"], api_key, protocol=spec.get("protocol"), timeout=timeout)
        row["status"] = status
        if status != "OK":
            # result 此时已是【固定措辞】(见 _explain / 异常类型名),不含任何上游响应体
            row["error"] = str(result)
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
        f"已配置角标名单 {detail['configured_badge_keys']} · 面板输入框 {detail['panel_input_keys']}"
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
        line = f"  {r['provider']:12} {r['configured']:20} {r['status']}"
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
