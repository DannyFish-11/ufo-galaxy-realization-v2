"""tests/test_node_80_degrades_without_redis.py
================================================

**缺一个可选的外部服务，不该让整个记忆节点起不来。**

修复前
------
``Node_80_MemorySystem`` 的 ``ShortTermMemory.connect()`` 是::

    except Exception as e:
        logger.error(...)
        if not OFFLINE_MODE:
            raise

单机上没起 Redis 容器、``OFFLINE_MODE`` 也没设(默认 false)时，整个节点::

    redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379
    ERROR:    Application startup failed. Exiting.

实测把 125 个节点逐个拉起来时，它是**唯一**一个因为缺外部服务而死的 —— 其余
124 个在零容器状态下都起得来。

为什么这是缺陷而不是设计
------------------------
全仓的约定写在 ``core/cache.py`` 里，白纸黑字::

    # Redis 在桌面单机模式是可选项:连不上会安静降级到内存缓存
    logger.info("Redis 未连接(降级到内存缓存,桌面单机属正常): %s", e)

``core/vector_backend.py``(退到 ``_LocalKeywordBackend``)、``core/nats_bus.py``
(退到进程内分发)也都是这个路子。只有这一个节点反着来。

而且代价不成比例:这个节点还提供长期记忆(MemOS)、用户画像(SQLite)、向量检索
(Chroma)——**三者都不依赖 Redis**。为了一个可降级的子能力，把另外三个也带走。

判据
----
1. 没有 Redis 时，节点要起得来，而且 ``/health`` 要**如实说**自己降级了。
   第二条同样重要:原来那行 ``"redis_available": ...client is not None`` 在降级后
   照样是 True(进程内替身也非 None)——那叫谎报，运维看这一栏就是为了区分
   "跨进程共享" 和 "重启即失忆"。
2. 短期记忆在降级后**仍然可用**(存得进、取得回)。只让节点"起来"但功能全 503，
   等于把硬失败换成了软失败。
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE_MAIN = REPO_ROOT / "nodes" / "Node_80_MemorySystem" / "main.py"


def _load_node_module():
    """按文件路径加载节点模块 —— 不依赖 sys.path 顺序。"""
    spec = importlib.util.spec_from_file_location(
        "Node_80_MemorySystem_main", NODE_MAIN, submodule_search_locations=[str(NODE_MAIN.parent)]
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def node():
    if not NODE_MAIN.exists():
        pytest.skip("Node_80 不在")
    try:
        return _load_node_module()
    except Exception as exc:  # 依赖不全时不要把它算成本条测试的失败
        pytest.skip(f"Node_80 依赖不全，无法加载:{exc}")


# ── 1. 连不上 Redis 不许抛 ──────────────────────────────────────────────────


async def test_connect_never_raises_when_redis_is_unreachable(node):
    """指向一个必然连不上的地址 —— ``connect()`` 必须安静降级。"""
    stm = node.ShortTermMemory("redis://127.0.0.1:1/", "test:", 60)

    await stm.connect()  # 修复前这里会抛 ConnectionError

    assert stm.backend == "memory", f"没有降级到内存，backend={stm.backend}"
    assert stm.client is not None, "降级了却没有可用的后端 —— 短期记忆会全线 503"
    assert stm.degrade_reason, "降级了却说不出原因"


async def test_degraded_backend_is_reported_honestly(node):
    """``backend`` 必须说实话 —— 这是"谎报 Redis 可用"那条的机器判据。"""
    stm = node.ShortTermMemory("redis://127.0.0.1:1/", "test:", 60)
    await stm.connect()

    # 修复前 /health 用的是 `client is not None`；降级后它同样为 True。
    assert (stm.backend == "redis") is False, "降级后仍然自称 redis"


# ── 2. 降级之后功能还得在 ────────────────────────────────────────────────────


async def test_short_term_memory_still_works_after_degrading(node):
    """存得进、取得回。只"起得来"但功能全 503 = 把硬失败换成软失败。"""
    stm = node.ShortTermMemory("redis://127.0.0.1:1/", "t:", 60)
    await stm.connect()

    await stm.save("sess-1", "第一句")
    await stm.save("sess-1", "第二句")
    got = await stm.recall("sess-1", limit=10)

    assert [m.content for m in got] == ["第一句", "第二句"], f"取回的内容不对:{got}"


async def test_conversation_round_trip_after_degrading(node):
    """对话存取也要通 —— 它走的是 rpush/lrange/expire 那条链。"""
    stm = node.ShortTermMemory("redis://127.0.0.1:1/", "t2:", 60)
    await stm.connect()

    msgs = [
        node.ConversationMessage(role="user", content="你好"),
        node.ConversationMessage(role="assistant", content="你好呀"),
    ]
    assert await stm.save_conversation("c-1", msgs) is True
    back = await stm.get_conversation("c-1", limit=10)

    assert [m.role for m in back] == ["user", "assistant"]
    assert [m.content for m in back] == ["你好", "你好呀"]


# ── 3. 进程内替身要真的复刻 Redis 的语义 ────────────────────────────────────


async def test_in_process_store_matches_redis_list_semantics(node):
    """``lrange`` 的负下标与闭区间语义要对 —— 错了会静默少取/多取几条。"""
    s = node._InProcessListStore()
    for v in ("a", "b", "c", "d"):
        await s.rpush("k", v)

    assert await s.lrange("k", 0, -1) == ["a", "b", "c", "d"], "全量取"
    assert await s.lrange("k", -2, -1) == ["c", "d"], "取最后两条(recall 就是这么用的)"
    assert await s.lrange("k", 0, 1) == ["a", "b"], "闭区间:0..1 是两条不是一条"
    assert await s.lrange("missing", 0, -1) == [], "不存在的键返回空表，不是报错"


async def test_in_process_store_honours_expiry(node):
    """``expire`` 得真的过期 —— 短期记忆的整个意义就是"会过期"。"""
    s = node._InProcessListStore()
    await s.rpush("k", "v")
    await s.expire("k", 0)  # 立刻过期

    assert await s.lrange("k", 0, -1) == [], "设了 0 秒过期却还取得到"


async def test_in_process_store_delete(node):
    s = node._InProcessListStore()
    await s.rpush("k", "v")

    assert await s.delete("k") == 1
    assert await s.delete("k") == 0, "删不存在的键应返回 0，不是报错"
    assert await s.lrange("k", 0, -1) == []
