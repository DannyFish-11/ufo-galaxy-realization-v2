"""
Galaxy - 跨设备统一会话管理器
================================

实现"任意设备对话同一个智能体"的核心：
- 会话与 user_id 绑定，多设备共享同一会话
- 会话历史持久化（内存 + JSON 文件）
- 新设备加入时自动同步历史
- WebSocket 广播会话更新到所有关联设备

用法:
    from core.session_manager import get_session_manager

    sm = get_session_manager()
    session = sm.get_or_create_session(user_id="user_001", device_id="phone_01")
    sm.add_message(session.id, "user", "打开微信", device_id="phone_01")
    history = sm.get_history(session.id, max_turns=20)
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.atomic_json import atomic_write_json

logger = logging.getLogger("Galaxy.SessionManager")

# 持久化路径
_SESSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "sessions.json",
)
# 每个会话的证据链(evidence chain)以 append-only JSONL 落在此目录下，<session_id>.evidence.jsonl
_EVIDENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "sessions",
)


# ─────────────────────────── 证据链 / 血缘 ───────────────────────────
# 借鉴「把 Session 当证据载体」的思路：一次运行里真正有价值的不是最终答复，而是
# 「工作如何一步步推进」的可回放证据——派发决策、主脑选型理由、工具调用入参/结果、
# 否决与重试、分叉。这些都作为带 (id, parent_id, trace_id) 的 EvidenceChunk 落进 Session，
# 串成一张 chunk 级的有向链；Session 之间又能 fork/detach 成会话级血缘图。


class EvidenceKind:
    """证据 chunk 的类别（字符串常量，便于过滤/检索）。"""

    MESSAGE = "message"  # 一条对话消息
    DISPATCH = "dispatch"  # 一次派发/路由决策（canonical dispatch slot 评估）
    MODEL_SELECTION = "model_selection"  # 主脑选型（候选/硬件/最终理由）
    TOOL_CALL = "tool_call"  # 一次工具调用（name/参数/结果/状态）
    VERDICT = "verdict"  # 一次校验/审查（通过/否决+理由）
    RETRY = "retry"  # 一条失败/重试路径
    FORK = "fork"  # 本会话被分叉出一个子会话
    BRANCH_ROOT = "branch_root"  # 子会话的起点（指回父链）
    NOTE = "note"  # 自由注记


@dataclass
class EvidenceChunk:
    """证据链上的一个节点。

    chunk 级血缘：``parent_id`` 默认指向同会话上一条 chunk，形成一条链；fork 时可显式指定
    父 chunk 以表达分叉。``trace_id`` 用于跨子系统(working_memory / ToolCallRecord 等)关联。
    """

    id: str
    session_id: str
    kind: str
    actor: str = ""  # 产生者：planner / coder / dispatch / selector / tool:<name> ...
    parent_id: str = ""  # 同会话上一 chunk（或显式分叉父）
    trace_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "kind": self.kind,
            "actor": self.actor,
            "parent_id": self.parent_id,
            "trace_id": self.trace_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "EvidenceChunk":
        return cls(
            id=d.get("id", ""),
            session_id=d.get("session_id", ""),
            kind=d.get("kind", EvidenceKind.NOTE),
            actor=d.get("actor", ""),
            parent_id=d.get("parent_id", ""),
            trace_id=d.get("trace_id", ""),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", time.time()),
        )


@dataclass
class SessionMessage:
    """会话中的一条消息"""

    role: str  # user / assistant / system
    content: str
    device_id: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "SessionMessage":
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            device_id=d.get("device_id", ""),
            timestamp=d.get("timestamp", time.time()),
            metadata=d.get("metadata", {}),
        )


@dataclass
class Session:
    """统一会话（ConversationSession 语义层）"""

    id: str
    user_id: str
    devices: List[str] = field(default_factory=list)
    active_device: str = ""
    history: List[SessionMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # ── 血缘 / 证据链 ──
    parent_id: str = ""  # 由哪个会话 fork 而来（detach 后清空）
    root_id: str = ""  # 血缘根会话（detach 会成为新根）
    branch_label: str = ""  # 分支标签，便于人读
    forked_from_chunk: str = ""  # fork 发生时父会话的 chunk id（分叉点）
    evidence: List[EvidenceChunk] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.root_id:
            self.root_id = self.id

    @property
    def conversation_session_id(self) -> str:
        """Canonical alias for conversation/history continuity semantics."""
        return self.id

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "devices": self.devices,
            "active_device": self.active_device,
            "history": [m.to_dict() for m in self.history],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "parent_id": self.parent_id,
            "root_id": self.root_id,
            "branch_label": self.branch_label,
            "forked_from_chunk": self.forked_from_chunk,
            "evidence": [c.to_dict() for c in self.evidence],
        }

    def to_summary(self) -> Dict:
        """轻量摘要（不含完整历史）"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "devices": self.devices,
            "active_device": self.active_device,
            "message_count": len(self.history),
            "evidence_count": len(self.evidence),
            "parent_id": self.parent_id,
            "root_id": self.root_id,
            "branch_label": self.branch_label,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Session":
        return cls(
            id=d["id"],
            user_id=d["user_id"],
            devices=d.get("devices", []),
            active_device=d.get("active_device", ""),
            history=[SessionMessage.from_dict(m) for m in d.get("history", [])],
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            metadata=d.get("metadata", {}),
            parent_id=d.get("parent_id", ""),
            root_id=d.get("root_id", "") or d["id"],
            branch_label=d.get("branch_label", ""),
            forked_from_chunk=d.get("forked_from_chunk", ""),
            evidence=[EvidenceChunk.from_dict(c) for c in d.get("evidence", [])],
        )


class SessionManager:
    """
    跨设备统一会话管理器

    核心设计:
    - 同一个 user_id 默认共享一个活跃会话
    - 任意设备加入会话后立即获得完整历史
    - 会话更新时通过回调通知所有关联设备
    """

    MAX_HISTORY = 200  # 每个会话最大消息数
    MAX_SESSIONS = 100  # 最大会话数
    MAX_EVIDENCE = 1000  # 每个会话最多在内存保留的证据 chunk 数（JSONL 文件不截断）

    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        # user_id → active session_id 映射
        self._user_active_session: Dict[str, str] = {}
        # 别名映射:设备本地/离线生成的 session_id → 归一化的 canonical 会话主线。
        # 跨设备统一上下文的核心:手机离线时自建一条本地会话线,重连后经
        # /api/v1/sessions/reconcile 把它「认领」到桌面的用户主线上——之后该本地
        # session_id 的所有轮次(在线 goal_execution / 离线补录)都落进同一条主线。
        self._session_aliases: Dict[str, str] = {}
        # 会话更新回调（用于 WebSocket 广播）
        self._on_update_callback = None
        self._lock = asyncio.Lock()
        # 证据链是同步、可被任意(同步/异步)调用方写入的快路径，用独立的线程锁保护，
        # 不与上面的 asyncio.Lock 纠缠（避免在同步上下文里 await）。
        self._evidence_lock = threading.Lock()
        self._load_state()
        logger.info("SessionManager 已初始化")

    def set_update_callback(self, callback):
        """设置会话更新回调（用于 WebSocket 广播）"""
        self._on_update_callback = callback

    # ═══════════════════ 会话生命周期 ═══════════════════

    def _create_session_locked(self, user_id: str, device_id: str = "") -> Session:
        """create_session 的持锁内核——调用方必须已持有 self._lock。

        asyncio.Lock 不可重入:get_or_create_session 持锁期间再 await
        create_session() 拿同一把锁会【死锁】(真机表现:首次会话创建的
        调用方永远挂起)。持锁内核抽出来供两条路径共用。
        """
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        devices = [device_id] if device_id else []
        session = Session(
            id=session_id,
            user_id=user_id,
            devices=devices,
            active_device=device_id,
        )
        self._sessions[session_id] = session
        self._user_active_session[user_id] = session_id
        self._persist_state()
        logger.info(f"会话已创建: {session_id} (user={user_id}, device={device_id})")
        return session

    async def create_session(self, user_id: str, device_id: str = "") -> Session:
        """创建新会话"""
        async with self._lock:
            return self._create_session_locked(user_id, device_id)

    async def ensure_session(
        self,
        session_id: str,
        user_id: str = "",
        device_id: str = "",
    ) -> Session:
        """确保指定 ID 的会话存在，并将设备加入该会话。"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                owner = user_id or f"session::{session_id}"
                devices = [device_id] if device_id else []
                session = Session(
                    id=session_id,
                    user_id=owner,
                    devices=devices,
                    active_device=device_id,
                )
                self._sessions[session_id] = session
                if owner:
                    self._user_active_session[owner] = session_id
                self._persist_state()
                logger.info(
                    "会话已确保存在: %s (user=%s, device=%s)",
                    session_id,
                    owner,
                    device_id,
                )
                return session

            if user_id:
                self._user_active_session[user_id] = session_id
            if device_id and device_id not in session.devices:
                session.devices.append(device_id)
            if device_id:
                session.active_device = device_id
            session.updated_at = time.time()
            self._persist_state()
            return session

    async def get_or_create_session(self, user_id: str, device_id: str = "") -> Session:
        """
        获取用户的活跃会话，如果不存在则创建。
        设备自动加入会话。
        """
        async with self._lock:
            session_id = self._user_active_session.get(user_id)
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                # 确保设备已加入
                if device_id and device_id not in session.devices:
                    session.devices.append(device_id)
                    logger.info(f"设备 {device_id} 已加入会话 {session_id}")
                if device_id:
                    session.active_device = device_id
                return session

            # 已持有 self._lock:不能 await create_session()(同一把非重入锁,
            # 会死锁)——走持锁内核。
            return self._create_session_locked(user_id, device_id)

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self._sessions.get(session_id)

    # ── 同步生命周期（供 sync 调用方使用，逻辑与上面 async 版一致）──
    # 背景：异步版用 asyncio.Lock 串行化协程；但有些 sync 调用方（如
    # core.session_identity.build_canonical_session_identity）无法 await。它们此前直接调
    # 异步方法 → 协程被丢弃、会话其实从未创建/确保（甚至 .conversation_session_id 取在协程上
    # 报 AttributeError）。这里提供等价的同步入口，用 _evidence_lock（线程锁）保护，与
    # record_evidence 的同步写入路径一致。

    def ensure_session_sync(self, session_id: str, user_id: str = "", device_id: str = "") -> Session:
        """ensure_session 的同步版本（语义一致）。"""
        with self._evidence_lock:
            session = self._sessions.get(session_id)
            if session is None:
                owner = user_id or f"session::{session_id}"
                session = Session(
                    id=session_id,
                    user_id=owner,
                    devices=[device_id] if device_id else [],
                    active_device=device_id,
                )
                self._sessions[session_id] = session
                if owner:
                    self._user_active_session[owner] = session_id
                self._persist_state()
                return session
            if user_id:
                self._user_active_session[user_id] = session_id
            if device_id and device_id not in session.devices:
                session.devices.append(device_id)
            if device_id:
                session.active_device = device_id
            session.updated_at = time.time()
            self._persist_state()
            return session

    def get_or_create_session_sync(self, user_id: str, device_id: str = "") -> Session:
        """get_or_create_session 的同步版本（语义一致）。"""
        with self._evidence_lock:
            session_id = self._user_active_session.get(user_id)
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                if device_id and device_id not in session.devices:
                    session.devices.append(device_id)
                if device_id:
                    session.active_device = device_id
                return session
            new_id = f"session_{uuid.uuid4().hex[:12]}"
            session = Session(
                id=new_id,
                user_id=user_id,
                devices=[device_id] if device_id else [],
                active_device=device_id,
            )
            self._sessions[new_id] = session
            self._user_active_session[user_id] = new_id
            self._persist_state()
            return session

    # ── 别名/对账（跨设备统一上下文主线）──
    # 一个设备本地(常见于离线)自建的 session_id,重连后通过 reconcile 被「认领」到
    # 用户的 canonical 主线上。resolve 把任意入参解析成主线 id;register 记录映射。
    # 都用 _evidence_lock(线程锁)保护,可被同步/异步调用方安全调用。

    def resolve_session_alias(self, session_id: str) -> str:
        """把设备本地/离线 session_id 沿别名链解析到 canonical 主线 id。

        无别名则原样返回。带深度上限的环路防护(别名闭环时返回当前解析结果,不死循环)。
        """
        if not session_id:
            return session_id
        seen = {session_id}
        cur = session_id
        for _ in range(16):  # 深度上限:防止别名成环导致死循环
            nxt = self._session_aliases.get(cur)
            if not nxt or nxt == cur or nxt in seen:
                break
            seen.add(nxt)
            cur = nxt
        return cur

    def register_session_alias(self, alias_id: str, canonical_id: str) -> bool:
        """记录 ``alias_id → canonical_id`` 别名。返回是否实际写入。

        拒绝自指与会引入环路的映射(canonical 已经解析回 alias 自身)。持久化。
        """
        if not alias_id or not canonical_id or alias_id == canonical_id:
            return False
        with self._evidence_lock:
            # 环路防护:若把 canonical 解析回来会落到 alias_id,则该映射成环,拒绝。
            probe = canonical_id
            for _ in range(16):
                if probe == alias_id:
                    logger.warning("拒绝会成环的会话别名: %s → %s", alias_id, canonical_id)
                    return False
                nxt = self._session_aliases.get(probe)
                if not nxt or nxt == probe:
                    break
                probe = nxt
            self._session_aliases[alias_id] = canonical_id
            self._persist_state()
            logger.info("会话别名已登记: %s → %s", alias_id, canonical_id)
            return True

    async def join_session(self, session_id: str, device_id: str) -> bool:
        """设备加入已有会话"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            if device_id not in session.devices:
                session.devices.append(device_id)
            session.active_device = device_id
            session.updated_at = time.time()
            self._persist_state()
            logger.info(f"设备 {device_id} 加入会话 {session_id}")
            return True

    def list_sessions(self, user_id: Optional[str] = None) -> List[Dict]:
        """列出会话（可按 user_id 过滤）"""
        sessions = self._sessions.values()
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        return [s.to_summary() for s in sessions]

    def get_primary_session_id(
        self,
        *,
        exclude_prefixes: tuple = ("ambient", "control", "worker", "session::"),
    ) -> str:
        """最近活跃的**真实对话**会话 id(排除 ambient/control/worker 等系统桶)。

        供 ambient 自发委托「续到用户正在进行的对话主线」上用——让自发动作共享真实
        上下文,而非跑在一次性隔离会话里。没有任何真实会话时返回 ""。
        """
        best_id, best_ts = "", -1.0
        for sid, s in self._sessions.items():
            if any(sid.startswith(p) for p in exclude_prefixes):
                continue
            ts = getattr(s, "updated_at", 0.0) or 0.0
            if ts > best_ts:
                best_ts, best_id = ts, sid
        return best_id

    def list_device_sessions(self, device_id: str) -> List[Dict]:
        """列出设备参与的所有会话"""
        return [s.to_summary() for s in self._sessions.values() if device_id in s.devices]

    # ═══════════════════ 消息管理 ═══════════════════

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        device_id: str = "",
        metadata: Optional[Dict] = None,
    ) -> bool:
        """添加消息到会话"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            msg = SessionMessage(
                role=role,
                content=content,
                device_id=device_id,
                metadata=metadata or {},
            )
            session.history.append(msg)
            session.updated_at = time.time()
            if device_id:
                session.active_device = device_id

            # 历史超限时截断
            if len(session.history) > self.MAX_HISTORY:
                session.history = session.history[-self.MAX_HISTORY :]

            self._persist_state()

            # 通知所有关联设备
            if self._on_update_callback:
                try:
                    self._on_update_callback(session_id, msg.to_dict(), session.devices)
                except Exception as e:
                    logger.debug(f"会话更新回调失败: {e}")

        # 每条消息同时落一个 message 证据 chunk（在 asyncio 锁外，用证据自身的线程锁）。
        self.record_evidence(
            session_id,
            EvidenceKind.MESSAGE,
            actor=role,
            payload={"role": role, "device_id": device_id, "content": content},
            trace_id=(metadata or {}).get("trace_id", ""),
        )
        return True

    def get_history(self, session_id: str, max_turns: int = 20) -> List[Dict]:
        """获取会话历史（格式兼容 LLM messages）"""
        session = self._sessions.get(session_id)
        if not session:
            return []
        messages = session.history[-max_turns:]
        return [{"role": m.role, "content": m.content} for m in messages]

    def get_full_history(self, session_id: str) -> List[Dict]:
        """获取完整历史（含设备和时间戳）"""
        session = self._sessions.get(session_id)
        if not session:
            return []
        return [m.to_dict() for m in session.history]

    def clear_history(self, session_id: str) -> bool:
        """清空会话的对话历史(保留会话身份/设备关系)。

        融合(域3)后轮次唯一属主是本类——"清除上下文"必须清这里
        (此前 ConversationMemory.clear_session 只清它自己的副本)。
        """
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.history.clear()
        session.updated_at = time.time()
        self._persist_state()
        logger.info("会话历史已清空: %s", session_id)
        return True

    # ═══════════════════ 证据链 / 血缘 ═══════════════════

    @staticmethod
    def _evidence_path(session_id: str) -> str:
        return os.path.join(_EVIDENCE_DIR, f"{session_id}.evidence.jsonl")

    def record_evidence(
        self,
        session_id: str,
        kind: str,
        actor: str = "",
        payload: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
        parent_id: Optional[str] = None,
    ) -> str:
        """追加一个证据 chunk，返回其 id（同步，可在任意上下文调用；best-effort 不抛错）。

        ``parent_id`` 缺省时自动指向本会话上一条 chunk，形成一条链；fork 时可显式指定。
        chunk 立即 append 到 <session_id>.evidence.jsonl（append-only、便宜、断电可回放）。
        """
        try:
            with self._evidence_lock:
                session = self._sessions.get(session_id)
                if session is None:
                    return ""
                if parent_id is None:
                    parent_id = session.evidence[-1].id if session.evidence else ""
                chunk = EvidenceChunk(
                    id=f"ev_{uuid.uuid4().hex[:12]}",
                    session_id=session_id,
                    kind=kind,
                    actor=actor,
                    parent_id=parent_id or "",
                    trace_id=trace_id or "",
                    payload=payload or {},
                )
                session.evidence.append(chunk)
                # 内存截断（JSONL 文件保留全量，仍可回放）
                if len(session.evidence) > self.MAX_EVIDENCE:
                    session.evidence = session.evidence[-self.MAX_EVIDENCE :]
                session.updated_at = chunk.timestamp
                self._append_evidence_jsonl(chunk)
            return chunk.id
        except Exception as e:  # noqa: BLE001 —— 证据采集绝不能影响主流程
            logger.debug("record_evidence 失败(已忽略): %s", e)
            return ""

    def _append_evidence_jsonl(self, chunk: EvidenceChunk) -> None:
        try:
            os.makedirs(_EVIDENCE_DIR, exist_ok=True)
            with open(self._evidence_path(chunk.session_id), "a", encoding="utf-8") as f:
                f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001
            logger.debug("证据 JSONL 追加失败(已忽略): %s", e)

    # ── 给三类关键来源的便捷记录器（薄封装，统一 actor/kind/payload 形状）──

    def record_dispatch(
        self,
        session_id: str,
        decision: str,
        *,
        reason: str = "",
        target: str = "",
        legality: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
        actor: str = "dispatch",
    ) -> str:
        """记录一次派发/路由决策（canonical dispatch slot 评估的结论）。"""
        return self.record_evidence(
            session_id,
            EvidenceKind.DISPATCH,
            actor=actor,
            payload={"decision": decision, "reason": reason, "target": target, "legality": legality or {}},
            trace_id=trace_id,
        )

    def record_model_selection(
        self,
        session_id: str,
        chosen: str,
        *,
        reason: str = "",
        hardware: str = "",
        candidates: Optional[List[str]] = None,
        source: str = "",
        trace_id: str = "",
        actor: str = "selector",
    ) -> str:
        """记录主脑选型（最终模型 + 候选 + 硬件 + 理由）。"""
        return self.record_evidence(
            session_id,
            EvidenceKind.MODEL_SELECTION,
            actor=actor,
            payload={
                "chosen": chosen,
                "reason": reason,
                "hardware": hardware,
                "candidates": candidates or [],
                "source": source,
            },
            trace_id=trace_id,
        )

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        *,
        arguments: Optional[Dict] = None,
        result: Any = None,
        status: str = "ok",
        error: str = "",
        latency_ms: Optional[float] = None,
        trace_id: str = "",
    ) -> str:
        """记录一次工具调用（入参 / 结果 / 状态 / 时延）。"""
        return self.record_evidence(
            session_id,
            EvidenceKind.TOOL_CALL,
            actor=f"tool:{tool_name}",
            payload={
                "tool": tool_name,
                "arguments": arguments or {},
                "result": result,
                "status": status,
                "error": error,
                "latency_ms": latency_ms,
            },
            trace_id=trace_id,
        )

    def record_verdict(
        self,
        session_id: str,
        approved: bool,
        *,
        reason: str = "",
        reviewer: str = "reviewer",
        trace_id: str = "",
    ) -> str:
        """记录一次校验/审查（通过或否决 + 理由）。"""
        return self.record_evidence(
            session_id,
            EvidenceKind.VERDICT,
            actor=reviewer,
            payload={"approved": bool(approved), "reason": reason},
            trace_id=trace_id,
        )

    def get_evidence(self, session_id: str, kind: Optional[str] = None, limit: int = 0) -> List[Dict]:
        """读取会话证据链（可按 kind 过滤、limit 取最近 N 条）。"""
        session = self._sessions.get(session_id)
        if not session:
            return []
        chunks = session.evidence
        if kind:
            chunks = [c for c in chunks if c.kind == kind]
        if limit and limit > 0:
            chunks = chunks[-limit:]
        return [c.to_dict() for c in chunks]

    # ── 会话级血缘：fork / detach / lineage ──

    async def fork_session(
        self,
        session_id: str,
        branch_label: str = "",
        *,
        copy_history: bool = True,
        detach: bool = False,
    ) -> Optional[Session]:
        """从一个会话分叉出子会话（用于「校验否决→换条路重来」「并行探索多分支」）。

        - copy_history=True：子会话继承父会话当前历史快照（独立副本，互不影响）。
        - detach=True：切断父链（parent_id 清空、自成血缘根），子会话完全独立。
        返回新建的子会话；父会话不存在则返回 None。
        """
        async with self._lock:
            parent = self._sessions.get(session_id)
            if parent is None:
                return None
            new_id = f"session_{uuid.uuid4().hex[:12]}"
            hist: List[SessionMessage] = (
                [SessionMessage.from_dict(m.to_dict()) for m in parent.history] if copy_history else []
            )
            fork_point = parent.evidence[-1].id if parent.evidence else ""
            child = Session(
                id=new_id,
                user_id=parent.user_id,
                devices=list(parent.devices),
                active_device=parent.active_device,
                history=hist,
                metadata=dict(parent.metadata),
                parent_id="" if detach else parent.id,
                root_id=new_id if detach else (parent.root_id or parent.id),
                branch_label=branch_label or f"fork-of-{parent.id[:8]}",
                forked_from_chunk=fork_point,
            )
            self._sessions[new_id] = child
            self._persist_state()
        # 双向留痕：父会话记一条 fork，子会话记一条 branch_root（指回分叉点）。
        self.record_evidence(
            session_id,
            EvidenceKind.FORK,
            actor="lineage",
            payload={"child_id": new_id, "branch_label": child.branch_label, "detached": bool(detach)},
        )
        self.record_evidence(
            new_id,
            EvidenceKind.BRANCH_ROOT,
            actor="lineage",
            payload={
                "parent_id": "" if detach else session_id,
                "forked_from_chunk": fork_point,
                "detached": bool(detach),
            },
            parent_id="",
        )
        logger.info("会话已分叉: %s → %s (label=%s, detach=%s)", session_id, new_id, child.branch_label, detach)
        return child

    async def detach_session(self, session_id: str) -> bool:
        """切断某会话与其父会话的血缘链（自成新根）。"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.parent_id = ""
            session.root_id = session_id
            session.updated_at = time.time()
            self._persist_state()
        self.record_evidence(session_id, EvidenceKind.NOTE, actor="lineage", payload={"event": "detach"})
        return True

    def get_lineage(self, session_id: str) -> List[Dict]:
        """返回从血缘根到本会话的路径（每项是一个 to_summary），便于追溯「哪条分支」。"""
        chain: List[Dict] = []
        seen = set()
        cur = self._sessions.get(session_id)
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            chain.append(cur.to_summary())
            if not cur.parent_id:
                break
            cur = self._sessions.get(cur.parent_id)
        chain.reverse()  # 根 → 叶
        return chain

    def export_jsonl(
        self,
        session_id: str,
        path: Optional[str] = None,
        *,
        include_lineage: bool = True,
    ) -> str:
        """把会话证据链导出成 JSONL（可回放的「证据档案」），返回写出的文件路径。

        include_lineage=True 时把祖先会话的证据按时间合并进来，得到一条贯穿整个血缘的链。
        每行一个 JSON 对象（_type=session_header / evidence）。
        """
        session = self._sessions.get(session_id)
        if session is None:
            return ""
        # 收集本会话(+祖先)的所有 chunk
        session_ids: List[str] = [session_id]
        if include_lineage:
            seen = set()
            cur = session
            while cur is not None and cur.id not in seen:
                seen.add(cur.id)
                if cur.id not in session_ids:
                    session_ids.append(cur.id)
                cur = self._sessions.get(cur.parent_id) if cur.parent_id else None
        rows: List[Dict] = []
        for sid in session_ids:
            s = self._sessions.get(sid)
            if not s:
                continue
            rows.append({"_type": "session_header", **s.to_summary()})
            for c in s.evidence:
                rows.append({"_type": "evidence", **c.to_dict()})
        rows.sort(
            key=lambda r: (0 if r["_type"] == "session_header" else 1, r.get("timestamp", r.get("created_at", 0)))
        )
        out_path = path or self._evidence_path(f"{session_id}.export")
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001
            logger.warning("证据档案导出失败: %s", e)
            return ""
        return out_path

    # ═══════════════════ 持久化 ═══════════════════

    def _persist_state(self):
        """持久化会话到 JSON 文件"""
        try:
            os.makedirs(os.path.dirname(_SESSION_FILE), exist_ok=True)
            data = {
                "sessions": {sid: s.to_dict() for sid, s in self._sessions.items()},
                "user_active_session": self._user_active_session,
                "session_aliases": self._session_aliases,
            }
            atomic_write_json(_SESSION_FILE, data, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"会话持久化失败: {e}")

    def _load_state(self):
        """从 JSON 文件恢复会话"""
        if not os.path.exists(_SESSION_FILE):
            return
        try:
            with open(_SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sid, sdata in data.get("sessions", {}).items():
                self._sessions[sid] = Session.from_dict(sdata)
            self._user_active_session = data.get("user_active_session", {})
            self._session_aliases = data.get("session_aliases", {}) or {}
            logger.info(f"已恢复 {len(self._sessions)} 个会话")
        except Exception as e:
            logger.warning(f"会话恢复失败: {e}")


# ═══════════════════ 单例 ═══════════════════

_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def record_evidence(session_id: str, kind: str, **kwargs) -> str:
    """模块级便捷入口：任意子系统一行落证据，绝不因采集失败影响主流程。

    用法： ``from core.session_manager import record_evidence, EvidenceKind``
          ``record_evidence(sid, EvidenceKind.TOOL_CALL, actor="tool:shell", payload={...})``
    """
    if not session_id:
        return ""
    try:
        return get_session_manager().record_evidence(session_id, kind, **kwargs)
    except Exception:  # noqa: BLE001
        return ""
