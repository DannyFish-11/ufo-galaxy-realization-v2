"""core/routes/island.py — 灵动岛上的卡片(:mod:`core.island_cards`)。

端点
----
  GET    /api/v1/presence/island          此刻岛上有哪些卡(排好先后;覆盖层平时走 WS ``type="island"`` 帧,这条给排查和面板用)
  DELETE /api/v1/presence/island/{id}     撤掉一张(岛上点「知道了」):后端也撤,重连时的补发里就不会再有它

只返回类型化的短字段。两条都要令牌:卡片里有设备名、桌面操作的结论。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from core.auth import require_auth


def register(router: APIRouter) -> None:
    @router.get("/api/v1/presence/island", dependencies=[Depends(require_auth)])
    async def island_cards() -> Dict[str, Any]:
        from core.island_cards import get_island_cards

        return get_island_cards().frame()["payload"]

    @router.delete("/api/v1/presence/island/{card_id}", dependencies=[Depends(require_auth)])
    async def dismiss_island_card(card_id: str) -> Dict[str, Any]:
        from core.island_cards import get_island_cards

        if not get_island_cards().remove(card_id):
            raise HTTPException(status_code=404, detail="岛上没有这张卡(可能已经过期)")
        return {"removed": card_id}


__all__ = ["register"]
