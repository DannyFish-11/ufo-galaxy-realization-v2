"""core/memory_thread.py —— 这次对话,接的是哪一条记忆

它在修什么
----------
2026-08-29 查「每 3 天折一张记忆卡片」的原料时发现:这个仓库的记忆分六层,
**五层已经是连续的**(身份、语义/知识、任务、三态),只有对话那一层不是 ——
每开一次新对话就自成一套,和别的 AI 产品一样。

而机制早就在了。``Session`` 自带全套血缘并且落盘::

    parent_id          由哪个会话 fork 而来
    root_id            血缘根 —— **这就是「一套连续的记忆」**
    branch_label
    forked_from_chunk

缺的只有两件:

1. ``Session.__post_init__`` 里 ``if not self.root_id: self.root_id = self.id``
   —— 新会话默认自成一根;
2. ``fork_session()`` 全仓只有一个生产调用方(并行分支),**从没人用它表达
   「这次接着上次」**。

所以这里补的不是一套新的记忆系统,是**一条判据**:什么时候算接着上次。

为什么判据要单独成一个模块
--------------------------
``SessionManager`` 里有**四处**在构造 ``Session``(异步 create、异步 ensure、
同步 ensure、同步 get_or_create)。判据写在其中任何一处,另外三处就会漂 ——
而漂了之后表现是「有些对话接上了、有些没接上」,没有人会立刻发现。

一个判断只能有一个权威。这个模块就是那个权威;四处都调它。

按人划根,不按设备
------------------
按设备切根与这个产品的立命之本冲突 —— 跨设备连续本身就是 ``RuntimeDomain``
那一整维在做的事,记忆却按设备劈开,说不通。至于「根会越来越大」:记忆卡片
正是这件事的解法,老窗口折成卡,不需要全量在线。

**认不出人的时候,不能硬接。**
------------------------------
``SessionManager`` 的 owner 有三种来源:

* 真实 ``user_id`` —— 认得出人;
* ``device::<id>`` —— 认不出人,但认得出设备。同一台设备上的对话仍是同一条线,
  这是当前能拿到的最好身份;
* ``session::<id>`` —— **这是拿会话自己的 id 现编的 owner**,每个会话一个,
  它根本不标识任何人。

第三种绝不能用来接线。用它接的话,判据看起来一直在工作(每次都「新建一根」),
实际上它从来没有能力接上任何东西 —— 而这正是本仓反复栽的那个坑:
看起来接上了,其实没有。所以这里把它显式判掉,并在 basis 里说明原因。

每一次判定都留下 basis
----------------------
接上了/没接上,以及**为什么**,记进会话元数据。记忆卡片据此能如实说明这条线
是怎么连起来的;排查「为什么这次没接上」时也不用靠猜。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

#: 这个模块是「对话接哪条记忆」的唯一权威。
MEMORY_THREAD_AUTHORITY: str = "MEMORY_THREAD::OWNER_SCOPED_ROOT_CONTINUATION_V1"

#: 拿会话 id 现编的 owner 前缀 —— 它不标识任何人,不能用来接线。见模块头。
NON_IDENTIFYING_OWNER_PREFIXES: Tuple[str, ...] = ("session::",)

#: 判定依据的取值域。
THREAD_BASES: Tuple[str, ...] = (
    "continued",
    "continued_root_only",
    "new_root_requested",
    "no_prior",
    "owner_not_identifying",
)

BASIS_MEANS: Dict[str, str] = {
    "continued": "接上了上一条会话所在的那套记忆。",
    "continued_root_only": (
        "接上了那套记忆,但**上一条会话本身已经不在了** —— 根记得住,链断了一环。"
        "SessionManager 现在不淘汰会话(MAX_SESSIONS 声明了却没有任何地方执行它),"
        "所以这一档平时不该出现;它出现就说明有人开始淘汰会话了。"
    ),
    "new_root_requested": "调用方显式要求另起一根 —— 人主动说「开个新的」。",
    "no_prior": "这个 owner 名下还没有过会话,这是它的第一条。",
    "owner_not_identifying": (
        "owner 是拿会话自己的 id 现编的,它不标识任何人,因此无从接起 —— "
        "这不是「没有上一条」,是「不知道上一条是谁的」。"
    ),
}


@dataclass(frozen=True)
class ThreadDecision:
    """一次「接哪条记忆」的判定。"""

    root_id: str
    """这条会话所属的记忆根。空串 = 由调用方用会话自己的 id 当根。"""

    parent_id: str
    """上一条会话。空串 = 这是根本身。"""

    basis: str
    """为什么是这个结果,见 :data:`THREAD_BASES`。"""

    @property
    def continued(self) -> bool:
        """接上了没有 —— 两档都算接上,区别只在链上缺不缺那一环。"""
        return self.basis in ("continued", "continued_root_only")

    def to_metadata(self) -> Dict[str, str]:
        """记进会话元数据的那一份 —— 让「怎么连起来的」在事后仍可查。"""
        return {
            "memory_thread_basis": self.basis,
            "memory_thread_root": self.root_id,
            "memory_thread_parent": self.parent_id,
            "memory_thread_authority": MEMORY_THREAD_AUTHORITY,
        }


def is_identifying_owner(owner: str) -> bool:
    """这个 owner 标识得了「人」吗。

    ``session::<id>`` 一类是拿会话自己的 id 现编的,每个会话一个 —— 它不标识
    任何人,用它接线等于永远接不上,而且看起来一直在工作。
    """
    o = str(owner or "").strip()
    if not o:
        return False
    return not o.startswith(NON_IDENTIFYING_OWNER_PREFIXES)


def resolve_thread(
    owner: str,
    previous_session: Optional[Any],
    *,
    new_root: bool = False,
    remembered_root: str = "",
) -> ThreadDecision:
    """判定这次新会话该接到哪条记忆上。

    Args:
        owner: 会话属主(真实 user_id、``device::<id>``、或 ``session::<id>``)。
        previous_session: 该 owner 名下**上一条**会话对象(需带 ``id`` 与
            ``root_id`` 属性);没有就传 ``None``。
        new_root: 调用方显式要求另起一根。
        remembered_root: 该 owner 上一次落在哪条记忆上 —— **在会话对象本身已经
            不在了的时候兜底**。``SessionManager`` 现在不淘汰会话,但
            ``MAX_SESSIONS = 100`` 这个意图摆在那儿;哪天有人真去实现它,没有这条
            兜底的话记忆会在淘汰发生的那一刻无声地断回一堆岛,而且没有任何东西会报错。

    这个函数不碰任何存储,纯输入输出 —— 它由 ``SessionManager`` 的四处构造点
    共同调用,自己不能反向依赖它们。
    """
    if new_root:
        return ThreadDecision(root_id="", parent_id="", basis="new_root_requested")

    if not is_identifying_owner(owner):
        # 认不出人就不硬接。把这一档与「没有上一条」分开,是因为它们要人做的事不同:
        # 前者是「这条路根本没有身份可依」,后者是「这确实是第一条」。
        return ThreadDecision(root_id="", parent_id="", basis="owner_not_identifying")

    if previous_session is None:
        if remembered_root:
            # 会话对象没了但根记得住:接上根,链上少一环,如实标成另一档。
            return ThreadDecision(root_id=remembered_root, parent_id="", basis="continued_root_only")
        return ThreadDecision(root_id="", parent_id="", basis="no_prior")

    prev_id = str(getattr(previous_session, "id", "") or "")
    prev_root = str(getattr(previous_session, "root_id", "") or "") or prev_id
    if not prev_id or not prev_root:
        # 上一条会话残缺(反序列化坏了之类)。宁可另起一根,也不要挂到一个空根上 ——
        # 空根会把后来的每一条都吸进去,合成一团谁也说不清的东西。
        if remembered_root:
            return ThreadDecision(root_id=remembered_root, parent_id="", basis="continued_root_only")
        return ThreadDecision(root_id="", parent_id="", basis="no_prior")

    return ThreadDecision(root_id=prev_root, parent_id=prev_id, basis="continued")
