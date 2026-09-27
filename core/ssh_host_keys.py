"""core/ssh_host_keys.py — SSH 连谁,得先确认"对面真是那台机器"。

原来 Node_39 / Node_40 都传 ``known_hosts=None`` —— 那是**关掉**主机校验。局域网里有人
冒充那台电脑(ARP/DNS 欺骗、同名主机抢先应答),我们会照样把用户名密码送过去。
这个模块把那道门补上,做法与 ssh 客户端一致,只是把"要不要信"从终端问答改成落盘 + 明说:

* **第一次见**:记下它的指纹,返回 ``"new"`` 并把指纹交给调用方 —— 由调用方告诉人
  ("第一次连它,指纹是 SHA256:…,如果这不是你那台机器就别继续")。
* **之后**:指纹一致才连。
* **对不上**:抛 :class:`HostKeyMismatch`,**不连**。要么真换了机器/重装了系统
  (那就明确调 :meth:`HostKeyStore.forget` 再连),要么就是有人在中间。

``GALAXY_SSH_STRICT_HOST_KEYS=true`` 时连"第一次见"也拒 —— 指纹必须事先录进来。
适合"机器是固定那几台"的场合。

指纹格式与 ``ssh-keygen -l`` 一致(``SHA256:`` + base64,无补位),方便人拿去对。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from core.atomic_json import atomic_write_json

logger = logging.getLogger("Galaxy.SSHHostKeys")

FILENAME = "ssh_known_hosts.json"


class HostKeyMismatch(Exception):
    """对面的指纹和记下来的不一样 —— 不连。"""

    def __init__(self, host: str, port: int, known: str, seen: str) -> None:
        self.host, self.port, self.known, self.seen = host, port, known, seen
        super().__init__(
            f"{host}:{port} 的主机指纹变了:记下的是 {known},这次是 {seen}。"
            "如果这台机器刚重装或换了,先忘掉旧指纹再连;否则有人在冒充它。"
        )

    @property
    def how_to_fix(self) -> str:
        return f"确认过 {self.host} 确实换了机器/重装了系统,再忘掉它的旧指纹(forget)并重连。"


class HostKeyUnknown(Exception):
    """严格模式下遇到没见过的主机。"""

    def __init__(self, host: str, port: int, seen: str) -> None:
        self.host, self.port, self.seen = host, port, seen
        super().__init__(f"没有 {host}:{port} 的主机指纹记录,严格模式下不连。这次看到的是 {seen}")

    @property
    def how_to_fix(self) -> str:
        return f"在那台机器上执行 ssh-keygen -l -f /etc/ssh/ssh_host_*_key.pub 核对指纹,确认是 {self.seen} 后录进来。"


def strict_mode() -> bool:
    return os.getenv("GALAXY_SSH_STRICT_HOST_KEYS", "false").strip().lower() in ("1", "true", "yes", "on")


def _state_dir() -> str:
    return os.getenv("GALAXY_DATA_DIR", "").strip() or os.path.join(os.getcwd(), "data")


def fingerprint(key: Any) -> str:
    """asyncssh 的 SSHKey → ``SHA256:…``(与 ssh-keygen -l 同一种写法)。"""
    fp = key.get_fingerprint()  # asyncssh 已经给的就是 "SHA256:base64"
    return str(fp)


def key_type_of(key: Any) -> str:
    algo = getattr(key, "algorithm", b"")
    return algo.decode() if isinstance(algo, bytes) else str(algo or "")


class HostKeyStore:
    """``host:port`` → 指纹。小 JSON,原子写。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or os.path.join(_state_dir(), FILENAME)
        self._lock = threading.RLock()
        self._rows: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    # ── 落盘 ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            import json

            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._rows = {k: v for k, v in data.items() if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001 — 读坏了当空处理,但绝不覆盖原文件
            logger.error("主机指纹文件读不出来(%s):%s —— 这次当没有记录,不会覆盖它", self._path, exc)
            self._readonly = True

    def _save(self) -> None:
        if getattr(self, "_readonly", False):
            logger.warning("主机指纹文件此前读失败,本次不写回,避免覆盖")
            return
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            atomic_write_json(self._path, self._rows)
        except Exception as exc:  # noqa: BLE001
            logger.error("主机指纹写盘失败:%s", exc)

    @staticmethod
    def _key(host: str, port: int) -> str:
        return f"{host}:{int(port)}"

    # ── 判定 ──────────────────────────────────────────────────────────────

    def check(self, host: str, port: int, key: Any) -> Tuple[str, str]:
        """返回 ``("new"|"known", 指纹)``。对不上抛 :class:`HostKeyMismatch`。

        ``"new"`` 表示这次**刚记下来** —— 调用方有义务把指纹告诉人。
        """
        fp = fingerprint(key)
        with self._lock:
            self._load()
            k = self._key(host, port)
            row = self._rows.get(k)
            now = time.time()
            if row is None:
                if strict_mode():
                    raise HostKeyUnknown(host, port, fp)
                self._rows[k] = {
                    "fingerprint": fp,
                    "key_type": key_type_of(key),
                    "first_seen": now,
                    "last_seen": now,
                }
                self._save()
                logger.info("第一次连 %s:%s,记下主机指纹 %s", host, port, fp)
                return "new", fp
            if str(row.get("fingerprint") or "") != fp:
                raise HostKeyMismatch(host, port, str(row.get("fingerprint") or ""), fp)
            row["last_seen"] = now
            self._save()
            return "known", fp

    def forget(self, host: str, port: int = 22) -> bool:
        with self._lock:
            self._load()
            return self._rows.pop(self._key(host, port), None) is not None

    def remember(self, host: str, port: int, fp: str, key_type: str = "") -> None:
        """事先录一个指纹(严格模式下先把已知机器录进来)。"""
        with self._lock:
            self._load()
            now = time.time()
            self._rows[self._key(host, port)] = {
                "fingerprint": fp,
                "key_type": key_type,
                "first_seen": now,
                "last_seen": now,
            }
            self._save()

    def known(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            self._load()
            return {k: dict(v) for k, v in self._rows.items()}


_store: Optional[HostKeyStore] = None
_store_lock = threading.Lock()


def get_host_key_store() -> HostKeyStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = HostKeyStore()
        return _store


def reset_host_key_store() -> None:
    """测试用:丢掉进程内的那一份。"""
    global _store
    with _store_lock:
        _store = None


# ── 给 asyncssh 用 ────────────────────────────────────────────────────────────


def verifying_client_factory(store: Optional[HostKeyStore] = None, on_new: Optional[Any] = None) -> Any:
    """造一个 asyncssh ``SSHClient`` 子类:握手时拿主机公钥去 :meth:`HostKeyStore.check`。

    这是 asyncssh 里能拿到**对面真实公钥**的钩子。返回 False 时 asyncssh 自己会把连接
    判为主机校验失败 —— 所以"拒"这件事不靠调用方自觉。

    ``on_new(host, port, fingerprint)`` 在第一次见到某台机器时回调(用来告诉人)。
    """
    import asyncssh

    keeper = store or get_host_key_store()

    class _VerifyingClient(asyncssh.SSHClient):
        #: 握手中记下的判定结果,连上之后调用方可以取
        last_status: Dict[str, Any] = {}

        def validate_host_public_key(self, host: str, addr: str, port: int, key: Any) -> bool:
            try:
                status, fp = keeper.check(host or addr, port, key)
            except (HostKeyMismatch, HostKeyUnknown) as exc:
                logger.error("拒绝连接 %s:%s —— %s", host or addr, port, exc)
                _VerifyingClient.last_status = {"ok": False, "error": str(exc)}
                return False
            _VerifyingClient.last_status = {"ok": True, "status": status, "fingerprint": fp}
            if status == "new" and on_new:
                try:
                    on_new(host or addr, port, fp)
                except Exception as exc:  # noqa: BLE001 — 告知失败不该让连接失败
                    logger.debug("新主机指纹告知失败: %s", exc)
            return True

    return _VerifyingClient


#: 传给 asyncssh 的 ``known_hosts``:三个空表(可信主机键 / 可信 CA / 已吊销)。
#:
#: 这个值是有讲究的,不能随手写:
#: * ``None`` = **完全不校验** —— asyncssh 直接把 ``_trusted_host_keys`` 置为 None,
#:   连 ``validate_host_public_key`` 都不会调。原来的洞就是这个值。
#: * ``b""`` 或 ``()`` 这类**假值** —— asyncssh 会去读 ``~/.ssh/known_hosts``,
#:   等于把判断权交给了本机那个文件,不是我们的指纹库。
#: * 三个空表是**真值**,于是 asyncssh 直接拿它当"可信集合为空",
#:   每一把主机键都会走 ``validate_host_public_key`` —— 正是我们要的那个钩子。
_EMPTY_TRUST: Tuple[list, list, list] = ([], [], [])


def connect_kwargs(store: Optional[HostKeyStore] = None, on_new: Optional[Any] = None) -> Dict[str, Any]:
    """``asyncssh.connect(**connect_kwargs(), …)`` —— 把校验接上的那两个参数。

    校验发生在 ``client_factory`` 的 :meth:`validate_host_public_key` 里,查我们自己的
    指纹库;``known_hosts`` 传三个空表的原因见 :data:`_EMPTY_TRUST`。
    """
    return {"known_hosts": _EMPTY_TRUST, "client_factory": verifying_client_factory(store, on_new)}
