"""用户自己声明的模型端点 —— 不改仓库就能加一家。

## 这个文件解决什么

在它之前,加一家模型厂商只有一条路:改 ``core/provider_registry.py``。也就是说
**每加一个端点都要动仓库、跑一遍 CI、再发一次版**。对"我公司内网有个 one-api
网关"这种再普通不过的需求,这个代价是荒谬的。

唯一的例外是 OneAPI:``multi_llm_router`` 里有一个**写死的动态槽位**,读
``ONEAPI_URL``/``ONEAPI_API_KEY``,打 ``/v1/models``,把网关后面的型号全注册进来。
那条路已经证明这件事做得成 —— 它只是被钉死成"只能有一个"。

这个模块把那个槽位泛化成 N 个。

## 为什么不直接塞进 PROVIDER_REGISTRY

那张表的价值有一半在核实出处的注释里:哪个型号什么时候发布、价格从哪查到的、
哪个查不到一手来源所以**故意**没登记。它还配着一道门,不准出现编造的型号串。

用户条目混进去,这两样同时失效:注释无从写起(我们不知道用户的网关有什么),
门也失去意义(用户填的就是"未经核实"的)。

所以分成两层,永不合并:

* ``provider_registry``  —— 我们核实过、知道其脾气的直连厂商。静态,进仓库。
* 这个模块              —— 用户/agent 声明的端点。动态,进 ``runtime/``,不进仓库。

这与仓库既有的 OneAPI 架构定位是同一条线(见 ``core/oneapi_system_position.py``):
聚合器永远是下层,不与直连厂商并列。

## 「确保自己生效」——两步,缺一不可

用户填完地址和 Key,系统必须能回答"这玩意儿到底能不能用",而不是让人等到真正
对话失败才知道。所以 :func:`verify` 做两步:

1. **列型号** ``GET {base_url}/models`` —— 拿得到就知道网关认哪些型号。
2. **真试调** 拿第一个型号发一次 ``max_tokens=1`` 的请求 —— 证明它真的**会答**,
   而不只是**会列**。

只列不试是不够的:一堆网关的 ``/models`` 是静态清单,Key 过期照样列得出来。

三种状态是三件不同的事,不准抹平:

* ``live``       —— 两步都过,型号表来自网关本身
* ``declared``   —— 网关不开放 ``/models``(有意的也常见),但用户自己列了型号,
                   且试调过了
* ``unverified`` —— 没过,并且 ``state_reason`` 说明**卡在哪一步**

## 安全

* **密钥不进这个文件。** 只存一个 vault 键名,值在 ``CredentialVault`` 里。
  这份 JSON 落在 ``runtime/``,备份/日志/截图都可能带走它。
* **绝不打印上游响应体。** 多家的鉴权失败响应会把收到的 Key 原样写在 message
  里,而"响应体里可能有什么"由上游决定、无法穷举。诊断只用 HTTP 状态码。
  这条规矩是 ``scripts/verify_provider_apis.py`` 已经踩过的坑,照抄。
* **id 不准与直连厂商重名。** 否则一个叫 ``openai`` 的用户条目会把真 OpenAI 顶掉,
  而"我的请求到底发去哪了"从此说不清 —— 那正是 ``core/endpoint_admission.py``
  开头警告的那条窃取路径。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("Galaxy.UserProviders")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORE_FILE = PROJECT_ROOT / "runtime" / "user_providers.json"

#: id 的形状。限死成小写短标识符有两个理由:它会成为路由里的 provider 名(要能
#: 当字典键、当日志字段),而且要能安全地拼进 vault 键名 —— 允许斜杠或 ``..``
#: 就等于把存储路径交给输入。
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

#: 这些名字被系统自己占着,用户条目不准用。前 18 个是直连厂商,后三个是
#: 路由器里另有特殊发现逻辑的槽位(本地 Ollama / HF 本地 / OneAPI)。
_RESERVED_EXTRA = ("ollama", "hf_local", "oneapi", "local", "default")

#: 目前只认这两种协议。填别的会被拒 —— **不猜**:一个我们没实现适配器的协议
#: 收下来,只会在真发请求时炸,那正是本仓最怕的失败形状。
SUPPORTED_PROTOCOLS = ("openai", "anthropic")

#: 试调的超时。比 verify_provider_apis.py 的稍宽:用户网关常在内网/中转后面。
_PROBE_TIMEOUT_S = 12.0

STATE_LIVE = "live"
STATE_DECLARED = "declared"
STATE_UNVERIFIED = "unverified"


@dataclass
class UserProvider:
    """一条用户声明的端点。**这个 dataclass 不含密钥** —— 见模块开头的安全一节。"""

    id: str
    label: str
    base_url: str
    protocol: str = "openai"
    #: 用户自己列的型号。空 = 交给 ``/models`` 去发现。
    declared_models: List[str] = field(default_factory=list)
    #: 上一次从网关问到的型号。空 = **没问出来**,不是"网关是空的"。
    discovered_models: List[str] = field(default_factory=list)
    added_by: str = "user"
    added_at: float = 0.0
    state: str = STATE_UNVERIFIED
    #: 没过的时候卡在哪一步。过了的时候留空。
    state_reason: str = "还没验证过"
    verified_at: Optional[float] = None

    def models(self) -> List[str]:
        """这条端点当前认哪些型号 —— 问到的优先,其次是用户自己列的。"""
        return list(self.discovered_models or self.declared_models)

    def to_public(self) -> Dict[str, Any]:
        d = asdict(self)
        d["models"] = self.models()
        return d


def _reserved_ids() -> Tuple[str, ...]:
    """被占用的 id。直连厂商那部分现从 registry 取,不另存一份。"""
    try:
        from core.provider_registry import PROVIDER_REGISTRY

        taken = tuple(str(s.get("name", "")) for s in PROVIDER_REGISTRY if s.get("name"))
    except Exception:  # pragma: no cover - registry 不可用时仍要挡住那三个特殊槽位
        taken = ()
    return taken + _RESERVED_EXTRA


class ProviderIdRejected(ValueError):
    """id 不合法或已被占用。带上人话解释,面板直接显示这句。"""


def validate_id(pid: str) -> str:
    pid = (pid or "").strip().lower()
    if not _ID_RE.match(pid):
        raise ProviderIdRejected("名字只能用小写字母、数字、下划线和连字符，1–32 个字符，且要以字母或数字开头")
    if pid in _reserved_ids():
        raise ProviderIdRejected(
            f"「{pid}」这个名字被系统占着了 —— 它要么是内置的直连厂商，要么是本地/聚合器的专用槽位。"
            "换一个名字；顶掉它会让「我的请求到底发去哪了」说不清。"
        )
    return pid


def _normalize_base_url(url: str) -> str:
    """去掉末尾斜杠。**不猜要不要补 /v1** —— 各家网关的前缀不一样,猜错就是 404。"""
    return (url or "").strip().rstrip("/")


def vault_key_for(pid: str) -> str:
    """这条端点的密钥在 vault 里叫什么。**唯一定义处**,存和取都走这里。"""
    return f"user_provider_{pid}"


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
def _read_raw() -> List[Dict[str, Any]]:
    if not STORE_FILE.exists():
        return []
    try:
        data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        # 读不出来跟"一条都没有"是两件事。返回空表会让用户以为自己配的端点凭空
        # 消失了,所以这里必须大声。
        logger.error(
            "runtime/user_providers.json 读不出来(%s):这一轮当作没有用户端点，但它们并没有被删掉。", type(exc).__name__
        )
        return []
    return data.get("providers", []) if isinstance(data, dict) else []


def _write_raw(rows: List[Dict[str, Any]]) -> None:
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "providers": rows}
    tmp = STORE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_FILE)  # 原子替换:写到一半断电不会留下半个文件


def list_providers() -> List[UserProvider]:
    out: List[UserProvider] = []
    for row in _read_raw():
        try:
            known = {f for f in UserProvider.__dataclass_fields__}
            out.append(UserProvider(**{k: v for k, v in row.items() if k in known}))
        except Exception:
            logger.warning("跳过一条读不懂的用户端点记录(id=%s)", row.get("id"))
    return out


def normalize_id(pid: str) -> str:
    """按查找口径把 id 归一。**写入与查找必须用同一把尺子。**

    :func:`validate_id` 会把输入转小写(``MyGW`` → ``mygw``)。如果查找这一侧照
    原样匹配,用 ``MyGW`` 建出来的端点就再也删不掉、验不了 —— 面板上按同一个
    名字点删除返回 404,像是这条端点鬼上身。这不是理论问题:面板的删除和验证
    都把 URL 里那一段直接传下来。
    """
    return (pid or "").strip().lower()


def get_provider(pid: str) -> Optional[UserProvider]:
    pid = normalize_id(pid)
    for p in list_providers():
        if p.id == pid:
            return p
    return None


def upsert_provider(
    *,
    pid: str,
    label: str,
    base_url: str,
    protocol: str = "openai",
    declared_models: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    added_by: str = "user",
) -> UserProvider:
    """新增或改一条。``api_key`` 给了就写进 vault;不给就保留原来的。

    新增/改完之后状态一律回到 ``unverified`` —— 地址或密钥变了,上一次的验证
    结论就不再作数。让它继续显示 ``live`` 是最坏的一种谎。
    """
    pid = validate_id(pid)
    protocol = (protocol or "openai").strip().lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ProviderIdRejected(f"暂时只支持这些协议：{'、'.join(SUPPORTED_PROTOCOLS)}。填的是「{protocol}」")
    base = _normalize_base_url(base_url)
    if not base.startswith(("http://", "https://")):
        raise ProviderIdRejected("地址要以 http:// 或 https:// 开头")

    if api_key is not None and api_key.strip():
        from core.credential_vault import get_vault

        get_vault().set_credential(vault_key_for(pid), api_key.strip())

    existing = get_provider(pid)
    row = UserProvider(
        id=pid,
        label=(label or pid).strip(),
        base_url=base,
        protocol=protocol,
        declared_models=[m.strip() for m in (declared_models or []) if m.strip()],
        discovered_models=[],
        added_by=added_by if existing is None else existing.added_by,
        added_at=existing.added_at if existing else time.time(),
        state=STATE_UNVERIFIED,
        state_reason="配置刚改过，还没重新验证",
        verified_at=None,
    )
    rows = [asdict(p) for p in list_providers() if p.id != pid]
    rows.append(asdict(row))
    _write_raw(rows)
    return row


def delete_provider(pid: str) -> bool:
    pid = normalize_id(pid)
    before = list_providers()
    rows = [asdict(p) for p in before if p.id != pid]
    if len(rows) == len(before):
        return False
    _write_raw(rows)
    try:
        from core.credential_vault import get_vault

        get_vault().delete_credential(vault_key_for(pid))
    except Exception as exc:  # pragma: no cover - 删条目已成功,密钥残留不该反悔
        logger.warning("端点 %s 已删除，但它的密钥没能从 vault 里清掉(%s)", pid, type(exc).__name__)
    return True


def api_key_for(pid: str) -> str:
    from core.credential_vault import get_vault

    return get_vault().get_credential(vault_key_for(normalize_id(pid))) or ""


# ---------------------------------------------------------------------------
# 两步自证
# ---------------------------------------------------------------------------
def _headers(protocol: str, api_key: str) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if not api_key:
        # 无鉴权的自托管服务把 Key 留空。此时**不能**照发 "Bearer " ——
        # httpx 会在发出前抛 LocalProtocolError,报错还长得像网络问题。
        # (与 OpenAIAdapter 里同一个坑,同一个处理。)
        return h
    if protocol == "anthropic":
        h["x-api-key"] = api_key
        h["anthropic-version"] = "2023-06-01"
    else:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _discover(p: UserProvider, api_key: str) -> Tuple[List[str], str]:
    """第一步:问网关认哪些型号。返回 (型号表, 失败说明)。

    失败说明只带 HTTP 状态码或异常类型名 —— **不带响应体**,见模块开头。
    """
    url = f"{p.base_url}/models"
    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT_S) as client:
            resp = client.get(url, headers=_headers(p.protocol, api_key))
    except Exception as exc:
        return [], f"连不上（{type(exc).__name__}）"
    if resp.status_code != 200:
        return [], f"列型号被拒（HTTP {resp.status_code}）"
    try:
        data = resp.json()
    except Exception:
        return [], "列型号返回的不是 JSON"
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], "列型号返回里没有 data 数组"
    ids = [m["id"] for m in items if isinstance(m, dict) and isinstance(m.get("id"), str)]
    return ids, ""


def _probe(p: UserProvider, api_key: str, model: str) -> str:
    """第二步:拿这个型号发一次 1-token 试调。返回空串代表过了。

    只列不试是不够的 —— 一堆网关的 /models 是静态清单,Key 过期照样列得出来。
    """
    if p.protocol == "anthropic":
        url = f"{p.base_url}/messages"
        body: Dict[str, Any] = {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    else:
        url = f"{p.base_url}/chat/completions"
        body = {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT_S) as client:
            resp = client.post(url, headers=_headers(p.protocol, api_key), json=body)
    except Exception as exc:
        return f"试调连不上（{type(exc).__name__}）"
    if resp.status_code >= 400:
        return f"试调被拒（HTTP {resp.status_code}，型号 {model}）"
    return ""


def verify(pid: str) -> UserProvider:
    """两步自证,并把结论写回存储。**不抛异常** —— 失败也是一种结论。"""
    pid = normalize_id(pid)
    p = get_provider(pid)
    if p is None:
        raise ProviderIdRejected(f"没有叫「{pid}」的端点")

    api_key = api_key_for(pid)
    discovered, why = _discover(p, api_key)

    candidates = discovered or p.declared_models
    if not candidates:
        p.state = STATE_UNVERIFIED
        p.discovered_models = []
        p.state_reason = (
            f"一个型号都问不出来：{why or '网关返回了空清单'}。"
            "要么检查地址和 Key，要么在「型号」里自己列几个 —— 有些网关有意不开放 /models。"
        )
        p.verified_at = time.time()
        _persist_one(p)
        return p

    failure = _probe(p, api_key, candidates[0])
    p.discovered_models = discovered
    p.verified_at = time.time()
    if failure:
        p.state = STATE_UNVERIFIED
        p.state_reason = failure
    else:
        p.state = STATE_LIVE if discovered else STATE_DECLARED
        p.state_reason = ""
    _persist_one(p)
    return p


def _persist_one(p: UserProvider) -> None:
    rows = [asdict(x) for x in list_providers() if x.id != p.id]
    rows.append(asdict(p))
    _write_raw(rows)


def routable_providers() -> List[UserProvider]:
    """能参与选路的那些 —— **只有验过的**。

    没验过就注册,等于把一个可能根本不通的端点放进候选池;选中它,失败发生在真发
    请求那一刻,而用户看到的只是"它怎么不回话"。宁可这一家暂时不在,也不要它诈尸。
    """
    return [p for p in list_providers() if p.state in (STATE_LIVE, STATE_DECLARED) and p.models()]
