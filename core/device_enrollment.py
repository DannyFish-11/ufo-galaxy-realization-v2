"""
core/device_enrollment.py — 设备入伙(配对/发放)协调器 + 智能体准入(P3-1 阶段二)
==============================================================================

在阶段一"每设备 token 注册表"(core/device_token_registry.py)之上,补上**配对流程
与准入判断**:新设备发来"入伙请求",经**智能体预判 + 你终裁**批准后,才调用注册表
发放它专属的 token(推回给设备)。核心设计取向(与所有者对齐):

- **别处批准(device-authorization grant)**:新设备零输入——它只管发请求(带自己的
  指纹),你在**已信任的桌面/手机**上批准。批准动作不在新设备上做。
- **智能体这一道判断**:请求到达时先过一个**策略钩子**(智能体预判,给出建议 verdict:
  approve/deny/None),但**最终 approve/deny 是显式的**(HITL 终裁)。默认无策略 = 纯
  HITL(全部 pending 等你拍板)。
- **配对码(可选)**:桌面可生成一个短时效配对码,给"有摄像头/键盘"的设备扫/输,作为
  更强的信任信号(code_verified),策略可据此自动建议批准;无码也能走"别处批准"。
- **不做账号**:信任挂在设备上,不引入用户账户。

本模块只管"请求生命周期 + 发放决策",不碰 WS 注册/mesh enroll(那是网关的职责);
它把 token 交出去,由端点/网关决定何时把设备放进 mesh(准入之后)。纯内存 + 可注入
registry,完全可单测。
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.device_token_registry import DeviceTokenRegistry, get_device_token_registry

logger = logging.getLogger("Galaxy.DeviceEnrollment")

# 状态
PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"
EXPIRED = "expired"
CLAIMED = "claimed"  # 已批准且设备已领走 token

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉易混字符 I/O/0/1


def _gen_pairing_code(n: int = 6) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(n))


@dataclass
class EnrollmentRequest:
    request_id: str
    device_id: str
    device_type: Optional[str] = None
    name: Optional[str] = None
    fingerprint: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    status: str = PENDING
    code_verified: bool = False  # 是否携带了有效配对码(更强信任信号)
    suggested_verdict: Optional[str] = None  # 智能体预判(非绑定):approve/deny/None
    decided_at: Optional[float] = None
    deny_reason: Optional[str] = None
    # 批准后暂存的明文 token(仅供设备 claim 一次),claim 后清空
    _token: Optional[str] = None

    def public_view(self) -> Dict[str, Any]:
        """给批准/管理界面看的视图,绝不含 token。"""
        return {
            "request_id": self.request_id,
            "device_id": self.device_id,
            "device_type": self.device_type,
            "name": self.name,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "status": self.status,
            "code_verified": self.code_verified,
            "suggested_verdict": self.suggested_verdict,
            "decided_at": self.decided_at,
            "deny_reason": self.deny_reason,
        }


# 策略钩子:智能体预判。输入请求,返回建议 verdict(approve/deny/None=不表态)。非绑定。
AdmissionPolicy = Callable[[EnrollmentRequest], Optional[str]]


class DeviceEnrollmentCoordinator:
    def __init__(
        self,
        registry: Optional[DeviceTokenRegistry] = None,
        *,
        code_ttl: float = 300.0,
        request_ttl: float = 600.0,
        claim_ttl: float = 300.0,
        terminal_retention: float = 120.0,
        max_requests: int = 4096,
        policy: Optional[AdmissionPolicy] = None,
    ) -> None:
        self._registry = registry or get_device_token_registry()
        self._code_ttl = code_ttl
        self._request_ttl = request_ttl
        # 批准后【领取窗口】:超过 claim_ttl 仍未 claim,则作废该请求并清掉暂存明文
        # token——request_id 是"一次性、短时效"能力凭据,批准却无人领取不应永久可领。
        self._claim_ttl = claim_ttl
        # 终态(EXPIRED/DENIED/CLAIMED)保留窗口:留一小段供设备 /status 读到结果,过后清除,
        # 避免 _requests 无限堆积(/enroll 无鉴权,否则是内存 DoS)。
        self._terminal_retention = terminal_retention
        # 硬上限(洪泛兜底):超过则按"终态优先、最旧优先"逐出,绝不无界增长。
        self._max_requests = max_requests
        self._policy = policy
        self._lock = threading.RLock()
        self._codes: Dict[str, float] = {}  # code -> expiry_at(用完即删)
        self._requests: Dict[str, EnrollmentRequest] = {}

    # ── 配对码(桌面侧,可选) ────────────────────────────────────────────
    def create_pairing_code(self, ttl: Optional[float] = None) -> Dict[str, Any]:
        """桌面生成一个短时效配对码(可展示为二维码/文本),供设备携带作为信任信号。"""
        code = _gen_pairing_code()
        with self._lock:
            self._codes[code] = time.time() + (ttl if ttl is not None else self._code_ttl)
        return {"code": code, "expires_in": ttl if ttl is not None else self._code_ttl}

    def _consume_code(self, code: Optional[str]) -> bool:
        """校验并消费配对码(一次性)。无码/无效返回 False,不阻断请求(只是不加信任)。"""
        if not code:
            return False
        with self._lock:
            exp = self._codes.get(code)
            if exp is None or time.time() > exp:
                self._codes.pop(code, None)
                return False
            del self._codes[code]  # 一次性
            return True

    # ── 入伙请求 ────────────────────────────────────────────────────────
    def submit_enrollment(
        self,
        device_id: str,
        *,
        device_type: Optional[str] = None,
        name: Optional[str] = None,
        fingerprint: Optional[Dict[str, Any]] = None,
        pairing_code: Optional[str] = None,
    ) -> EnrollmentRequest:
        """新设备提交入伙请求。生成 pending 请求,过一遍策略钩子(智能体预判),等终裁。"""
        if not device_id or not str(device_id).strip():
            raise ValueError("device_id 不能为空")
        self._expire_locked_free()
        req = EnrollmentRequest(
            request_id=uuid.uuid4().hex,
            device_id=str(device_id).strip(),
            device_type=device_type,
            name=name,
            fingerprint=fingerprint or {},
            code_verified=self._consume_code(pairing_code),
        )
        # 智能体预判(非绑定):失败不影响流程,保持 pending 等 HITL。
        if self._policy is not None:
            try:
                v = self._policy(req)
                if v in (APPROVED, DENIED, "approve", "deny"):
                    req.suggested_verdict = "approve" if v in (APPROVED, "approve") else "deny"
            except Exception as exc:  # noqa: BLE001
                logger.debug("准入策略预判失败(忽略,转 HITL): %s", exc)
        with self._lock:
            self._requests[req.request_id] = req
        logger.info(
            "入伙请求: request_id=%s device_id=%s type=%s code_verified=%s 建议=%s",
            req.request_id,
            req.device_id,
            device_type,
            req.code_verified,
            req.suggested_verdict,
        )
        return req

    def pending(self) -> List[Dict[str, Any]]:
        """列出待终裁的请求(供桌面/手机批准界面),不含 token。"""
        self._expire_locked_free()
        with self._lock:
            return [r.public_view() for r in self._requests.values() if r.status == PENDING]

    def get(self, request_id: str) -> Optional[Dict[str, Any]]:
        self._expire_locked_free()
        with self._lock:
            r = self._requests.get(request_id)
            return r.public_view() if r else None

    # ── 终裁 ────────────────────────────────────────────────────────────
    def approve(self, request_id: str) -> Optional[str]:
        """批准(HITL 终裁):经注册表发放专属 token 并暂存,返回明文 token(供推回设备)。"""
        self._expire_locked_free()  # 先扫过期:绝不批准一个已超 request_ttl 的陈旧请求(TOCTOU)
        with self._lock:
            r = self._requests.get(request_id)
            if r is None or r.status != PENDING:
                return None
            token = self._registry.issue(r.device_id, device_type=r.device_type, name=r.name)
            r.status = APPROVED
            r.decided_at = time.time()
            r._token = token
        logger.info("入伙已批准: request_id=%s device_id=%s", request_id, r.device_id)
        return token

    def deny(self, request_id: str, reason: Optional[str] = None) -> bool:
        self._expire_locked_free()
        with self._lock:
            r = self._requests.get(request_id)
            if r is None or r.status != PENDING:
                return False
            r.status = DENIED
            r.decided_at = time.time()
            r.deny_reason = reason
        logger.info("入伙已拒绝: request_id=%s reason=%s", request_id, reason)
        return True

    def claim(self, request_id: str) -> Optional[str]:
        """设备侧领取 token:仅当已批准且未领过,返回一次明文 token,随后清空转 CLAIMED。

        领取前先跑一次过期清理:批准后超过 claim_ttl 未领的请求已被作废(EXPIRED),
        这里就取不到 token —— 确保"过期领取窗口"在 claim 热路径上也权威生效。
        """
        self._expire_locked_free()
        with self._lock:
            r = self._requests.get(request_id)
            if r is None or r.status != APPROVED or r._token is None:
                return None
            tok = r._token
            r._token = None
            r.status = CLAIMED
            return tok

    # ── 过期清理 ────────────────────────────────────────────────────────
    def _expire_locked_free(self) -> None:
        now = time.time()
        with self._lock:
            for code, exp in list(self._codes.items()):
                if now > exp:
                    del self._codes[code]
            for rid, r in list(self._requests.items()):
                if r.status == PENDING and (now - r.created_at) > self._request_ttl:
                    r.status = EXPIRED
                    r.decided_at = now
                # 批准但迟迟未领:超过领取窗口即作废,并清掉暂存明文 token(防止
                # 一次性能力凭据永久可领;不吊销注册表记录,以免误伤该设备其它有效 token)。
                elif r.status == APPROVED and r.decided_at is not None and (now - r.decided_at) > self._claim_ttl:
                    r.status = EXPIRED
                    r._token = None
            # 清除超过保留窗口的终态记录:防止 _requests 无限堆积(无鉴权 /enroll 的内存 DoS)。
            _terminal = (EXPIRED, DENIED, CLAIMED)
            for rid, r in list(self._requests.items()):
                if r.status in _terminal:
                    ref = r.decided_at if r.decided_at is not None else r.created_at
                    if (now - ref) > self._terminal_retention:
                        del self._requests[rid]
            # 硬上限兜底(洪泛):超上限则逐出——终态优先、最旧优先。
            if len(self._requests) > self._max_requests:
                ordered = sorted(
                    self._requests.items(),
                    key=lambda kv: (kv[1].status == PENDING, kv[1].created_at),
                )
                for rid, _r in ordered[: len(self._requests) - self._max_requests]:
                    del self._requests[rid]


# ── 进程级单例 ────────────────────────────────────────────────────────────
_coordinator: Optional[DeviceEnrollmentCoordinator] = None
_coord_lock = threading.Lock()


def get_enrollment_coordinator() -> DeviceEnrollmentCoordinator:
    global _coordinator
    if _coordinator is None:
        with _coord_lock:
            if _coordinator is None:
                _coordinator = DeviceEnrollmentCoordinator()
    return _coordinator
