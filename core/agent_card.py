"""core/agent_card.py — 可分享的智能体名片(配对凭证)

解决什么
--------
此前设备接入只有 ``AIP_TOKEN``(一把共享令牌),而
``galaxy_gateway/routes/websocket.py`` 的入口登记表里自己写着
``device_cert 未实现(诚实化)``。也就是说:**没有任何"把一台设备的身份 + 能力 +
端点打包成一份可传递凭证"的东西**。配对只能靠人工把令牌和地址抄过去。

AgentCard 就是这份凭证:一段自描述、防篡改、可放进二维码或直接口述的短文本。

与既有设施的关系(刻意复用,不另起一套)
--------------------------------------
签名**直接复用** ``core.capability_token`` 的 Mesh 主密钥与 HMAC-SHA256 例程
(``_mesh_secret`` / ``_sign``),不引入第二套密钥体系:

* 单属主 Mesh 里签发方 = 验证方,HMAC 足够,且零额外依赖 ——
  这与 capability_token.py:15-17 已经写下的选型判断一致;
* 复用同一把密钥意味着**换密钥即同时吊销所有名片和令牌**,不会出现
  "令牌换了但名片还认"的半吊销状态。

将来若要支持**多属主**(别人的智能体接进来),再按 capability_token 里已经写明的
路线切 ed25519 公钥体系 —— 那时 ``AgentCard.issuer`` 字段就是放 DID 的地方,
本模块的链接格式不必改。

两种配对方式(对齐"扫码 / 命令"两条路)
--------------------------------------
1. **链接**:``galaxy://pair?c=<payload>&s=<sig>`` —— 可直接渲染成二维码扫码;
2. **短码**:6 位人类可读配对码(去掉易混字符),可口述、可手输,
   由 :class:`PairingCodeRegistry` 在内存中短时保管,默认 10 分钟过期。

短码存在的理由:二维码需要一块屏幕和一个摄像头,而终端/SSH 场景两者都没有。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from core.capability_token import _b64d, _b64e, _sign  # 复用同一把 Mesh 主密钥

logger = logging.getLogger("Galaxy.AgentCard")

#: 配对链接 scheme。用自有 scheme 而不是 http,避免被当成可点击的外链误导用户。
CARD_SCHEME = "galaxy"
CARD_HOST = "pair"

#: 名片默认有效期(秒)。名片是**配对凭证**不是长效授权,短一点更安全;
#: 真正的长效授权由 capability_token 签发。
DEFAULT_CARD_TTL_S = 24 * 3600.0

#: 短码字符集:去掉 0/O/1/I/L 等易混字符,便于口述与手输。
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
DEFAULT_CODE_TTL_S = 600.0


@dataclass
class AgentCard:
    """一台设备/智能体的自描述名片。"""

    device_id: str
    name: str = ""
    device_type: str = "unknown"
    capabilities: List[str] = field(default_factory=list)
    #: 传输端点,如 {"websocket": "ws://10.0.0.5:9000/ws/device/<id>"}
    endpoints: Dict[str, str] = field(default_factory=dict)
    #: 签发者标识。单属主 Mesh 下就是本机 device_id;将来多属主时放 DID。
    issuer: str = ""
    issued_at: float = 0.0
    expires_at: float = 0.0
    #: 防重放随机串
    nonce: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def is_expired(self, now: Optional[float] = None) -> bool:
        if not self.expires_at:
            return False
        return (now if now is not None else time.time()) > self.expires_at


def _payload_b64(card: AgentCard) -> str:
    # sort_keys + 紧凑分隔符:同一张名片必须序列化成同一串,否则签名无法复验
    raw = json.dumps(card.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _b64e(raw.encode("utf-8"))


def create_agent_card(
    device_id: str,
    *,
    name: str = "",
    device_type: str = "unknown",
    capabilities: Optional[List[str]] = None,
    endpoints: Optional[Dict[str, str]] = None,
    issuer: str = "",
    ttl_s: float = DEFAULT_CARD_TTL_S,
    now: Optional[float] = None,
) -> AgentCard:
    """签发一张名片(未签名;签名在 to_link/to_token 时施加)。"""
    t = now if now is not None else time.time()
    return AgentCard(
        device_id=str(device_id),
        name=str(name or device_id),
        device_type=str(device_type or "unknown"),
        capabilities=[str(c) for c in (capabilities or [])],
        endpoints={str(k): str(v) for k, v in (endpoints or {}).items()},
        issuer=str(issuer or device_id),
        issued_at=t,
        expires_at=t + float(ttl_s) if ttl_s else 0.0,
        nonce=secrets.token_hex(8),
    )


def to_link(card: AgentCard) -> str:
    """名片 → 可扫码/可粘贴的配对链接。"""
    payload = _payload_b64(card)
    return f"{CARD_SCHEME}://{CARD_HOST}?" + urlencode({"c": payload, "s": _sign(payload)})


@dataclass(frozen=True)
class CardVerdict:
    """名片校验结论。``card`` 仅在 valid 时有值。"""

    valid: bool
    reason: str = ""
    card: Optional[AgentCard] = None


def from_link(link: str, *, now: Optional[float] = None) -> CardVerdict:
    """解析并**校验**配对链接。签名不符或已过期一律判无效。

    绝不在校验失败时返回半个 card —— 调用方一旦拿到 card 就会据此登记设备,
    返回"内容对但签名错"的名片等于把伪造名片放进了信任链。
    """
    try:
        parsed = urlparse(str(link).strip())
    except Exception as exc:  # noqa: BLE001
        # reason 会被配对接口原样回给调用方,因此不能带异常文本
        # (CodeQL: Information exposure through an exception)。细节只进日志。
        logger.debug("配对链接解析失败: %s", exc, exc_info=True)
        return CardVerdict(False, "链接格式无法解析")
    if parsed.scheme != CARD_SCHEME or (parsed.netloc or parsed.path.strip("/")) != CARD_HOST:
        return CardVerdict(False, f"不是配对链接(期望 {CARD_SCHEME}://{CARD_HOST})")
    q = parse_qs(parsed.query)
    payload = (q.get("c") or [""])[0]
    sig = (q.get("s") or [""])[0]
    if not payload or not sig:
        return CardVerdict(False, "链接缺少 c/s 参数")
    # 用 secrets.compare_digest 做定时安全比较,避免按字节比较泄漏签名前缀
    if not secrets.compare_digest(_sign(payload), sig):
        return CardVerdict(False, "签名校验失败(名片被篡改,或签发方与本机主密钥不同)")
    try:
        data = json.loads(_b64d(payload).decode("utf-8"))
        card = AgentCard(
            device_id=str(data.get("device_id", "")),
            name=str(data.get("name", "") or ""),
            device_type=str(data.get("device_type", "unknown") or "unknown"),
            capabilities=[str(c) for c in (data.get("capabilities") or [])],
            endpoints={str(k): str(v) for k, v in (data.get("endpoints") or {}).items()},
            issuer=str(data.get("issuer", "") or ""),
            issued_at=float(data.get("issued_at", 0.0) or 0.0),
            expires_at=float(data.get("expires_at", 0.0) or 0.0),
            nonce=str(data.get("nonce", "") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        # 同上:不把异常文本带进对外 reason
        logger.debug("名片内容解码失败: %s", exc, exc_info=True)
        return CardVerdict(False, "名片内容损坏")
    if not card.device_id:
        return CardVerdict(False, "名片缺少 device_id")
    if card.is_expired(now):
        return CardVerdict(False, "名片已过期,请让对方重新出示")
    return CardVerdict(True, "", card)


# ── 短码配对(无摄像头场景)────────────────────────────────────────────────
@dataclass
class _CodeEntry:
    link: str
    expires_at: float


#: 同时有效的短码上限。超出后按签发顺序淘汰最旧的。
#:
#: 必须有上限:``GET /api/v1/pair/card`` 每调用一次就签发一个 10 分钟有效的短码,
#: 只清过期、不限总数的话,任何反复拉取名片的客户端(或轮询的面板)都会让这张表
#: 持续膨胀 —— 实测连续签发 5000 次即积压 5000 条。这与仓库里 IPBlockList、
#: 学习引擎模式表所修的是同一类无界集合问题。
MAX_ACTIVE_PAIRING_CODES = 256


class PairingCodeRegistry:
    """短码 → 配对链接 的短时映射(仅内存,进程重启即失效)。

    刻意不落盘:短码是**一次性、分钟级**的引导凭证,落盘只会延长它的暴露窗口。
    容量有上限(见 MAX_ACTIVE_PAIRING_CODES),满了按签发顺序淘汰最旧的。
    """

    def __init__(self, max_active: int = MAX_ACTIVE_PAIRING_CODES) -> None:
        self._lock = threading.RLock()
        # OrderedDict:按插入顺序维护,便于满容量时 FIFO 淘汰最旧的一条
        self._codes: "OrderedDict[str, _CodeEntry]" = OrderedDict()
        self._max_active = max(1, int(max_active))
        #: 因容量上限被挤掉的短码数(诊断用:证明淘汰真的在发生)
        self.evicted = 0

    def _sweep_unlocked(self, now: float) -> None:
        for code in [c for c, e in self._codes.items() if e.expires_at <= now]:
            self._codes.pop(code, None)

    def _enforce_cap_unlocked(self) -> None:
        """先清过期,仍超容量则淘汰最旧的。

        被淘汰的短码随即失效 —— 这是刻意的:短码是引导凭证,宁可让用户重新拉一次
        名片,也不能让这张表无界增长。
        """
        while len(self._codes) > self._max_active:
            self._codes.popitem(last=False)
            self.evicted += 1

    def issue(self, link: str, *, ttl_s: float = DEFAULT_CODE_TTL_S, now: Optional[float] = None) -> Tuple[str, float]:
        t = now if now is not None else time.time()
        with self._lock:
            self._sweep_unlocked(t)
            for _ in range(64):  # 极小概率碰撞,重试即可
                code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
                if code not in self._codes:
                    expires = t + float(ttl_s)
                    self._codes[code] = _CodeEntry(link=link, expires_at=expires)
                    self._enforce_cap_unlocked()
                    return code, expires
            raise RuntimeError("配对短码生成失败:连续 64 次碰撞")

    def resolve(self, code: str, *, consume: bool = True, now: Optional[float] = None) -> Optional[str]:
        """短码 → 链接。默认**用后即焚**(consume=True)。"""
        t = now if now is not None else time.time()
        key = str(code).strip().upper()
        with self._lock:
            self._sweep_unlocked(t)
            entry = self._codes.get(key)
            if entry is None:
                return None
            if consume:
                self._codes.pop(key, None)
            return entry.link

    def active_count(self) -> int:
        with self._lock:
            self._sweep_unlocked(time.time())
            return len(self._codes)


_registry_lock = threading.Lock()
_registry: Optional[PairingCodeRegistry] = None


def get_pairing_code_registry() -> PairingCodeRegistry:
    global _registry
    if _registry is not None:
        return _registry
    with _registry_lock:
        if _registry is None:
            _registry = PairingCodeRegistry()
    return _registry


def reset_pairing_code_registry() -> None:
    """测试用。"""
    global _registry
    with _registry_lock:
        _registry = None


# ── 本机名片 ──────────────────────────────────────────────────────────────
def local_device_id() -> str:
    """本机在 Mesh 中的标识。优先环境变量,其次主机名。"""
    for key in ("GALAXY_DEVICE_ID", "GALAXY_NODE_ID"):
        v = os.getenv(key, "").strip()
        if v:
            return v
    try:
        import socket

        return socket.gethostname() or "galaxy-local"
    except Exception:  # noqa: BLE001
        return "galaxy-local"


def build_local_card(
    *,
    capabilities: Optional[List[str]] = None,
    endpoints: Optional[Dict[str, str]] = None,
    ttl_s: float = DEFAULT_CARD_TTL_S,
) -> AgentCard:
    """构造本机名片。端点未显式给出时,按实际监听端口推导 websocket 入口。

    端口取自 ``core.electron_launch_guard.resolve_gateway_port()`` —— 那是本仓库
    既有的"网关实际监听端口"权威解析(env → port_config → 默认 9000),
    不在这里另写一份端口推导逻辑。
    """
    did = local_device_id()
    eps = dict(endpoints or {})
    if not eps:
        try:
            from core.electron_launch_guard import resolve_gateway_port

            port = resolve_gateway_port()
        except Exception as exc:  # noqa: BLE001
            logger.warning("名片端点推导:网关端口解析失败(%s),端点留空", exc)
            port = 0
        if port:
            eps["websocket"] = f"ws://{_local_ip()}:{port}/ws/device/{did}"
    return create_agent_card(
        did,
        name=os.getenv("GALAXY_DEVICE_NAME", "").strip() or did,
        device_type=os.getenv("GALAXY_DEVICE_TYPE", "").strip() or "unknown",
        capabilities=capabilities or [],
        endpoints=eps,
        issuer=did,
        ttl_s=ttl_s,
    )


def _local_ip() -> str:
    """取本机在局域网中的出口 IP;失败退回 127.0.0.1。"""
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # 不发包,只为让内核选路
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("本机 IP 探测失败,退回 127.0.0.1: %s", exc)
        return "127.0.0.1"
