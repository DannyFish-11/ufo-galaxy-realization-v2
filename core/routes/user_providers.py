"""core/routes/user_providers.py — 「我的模型服务」的增删改查与自证
=====================================================================

不改仓库就能加一家模型厂商。判据与存储全在 ``core.user_providers``,这里只做
HTTP 外壳 —— 那个模块是唯一权威,这个文件不许自己再判断什么。

  GET    /api/v1/providers/user            列出全部(含状态与失败原因)
  POST   /api/v1/providers/user            新增或修改一条
  DELETE /api/v1/providers/user/{id}       删掉一条(连同它在 vault 里的密钥)
  POST   /api/v1/providers/user/{id}/verify  两步自证：列型号 + 1-token 真试调

## 两个不肯让步的地方

**一、写完就刷新路由器。** 面板上加完一条端点,如果要重启才生效,那这个功能就等
于没做 —— 用户会以为它坏了。写入之后调 ``refresh_llm_router()``,新端点当场进
候选池。

**二、绝不回显密钥。** 响应里没有 ``api_key`` 这个字段,一个字节都不带 ——
连长度也不带(长度也是信息)。要表达"填过没有",用 ``has_key`` 这个布尔。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.user_providers import (
    ProviderIdRejected,
    api_key_for,
    delete_provider,
    get_provider,
    list_providers,
    upsert_provider,
)
from core.user_providers import verify as verify_provider

logger = logging.getLogger("Galaxy.Routes.UserProviders")

router = APIRouter(prefix="/api/v1/providers/user", tags=["user-providers"])


class UserProviderIn(BaseModel):
    id: str
    label: str = ""
    base_url: str
    protocol: str = "openai"
    #: 用户自己列的型号。留空 = 交给网关的 /models 去发现。
    models: List[str] = []
    #: 不传 = 保留原来的密钥(改标签不必重填 Key)。传空串也当作"不改"。
    api_key: Optional[str] = None


def _shape(pid: str) -> Dict[str, Any]:
    """一条端点对外长什么样。``has_key`` 而不是 key —— 见模块开头。"""
    p = get_provider(pid)
    if p is None:  # pragma: no cover - 调用方都是刚写完就取
        raise HTTPException(status_code=404, detail=f"没有叫「{pid}」的端点")
    d = p.to_public()
    d["has_key"] = bool(api_key_for(pid))
    return d


async def _refresh_router() -> None:
    """让新端点当场生效。失败不阻断写入 —— 配置已经存下了,只是这一轮还没热起来。"""
    try:
        from core.multi_llm_router import refresh_llm_router

        await refresh_llm_router()
    except Exception as exc:
        logger.warning("端点已保存，但路由器刷新失败(%s) —— 重启后仍会生效。", type(exc).__name__)


@router.get("")
async def list_user_providers() -> Dict[str, Any]:
    rows = []
    for p in list_providers():
        d = p.to_public()
        d["has_key"] = bool(api_key_for(p.id))
        rows.append(d)
    return {"providers": rows}


@router.post("")
async def create_or_update_user_provider(body: UserProviderIn) -> Dict[str, Any]:
    try:
        p = upsert_provider(
            pid=body.id,
            label=body.label,
            base_url=body.base_url,
            protocol=body.protocol,
            declared_models=body.models,
            api_key=body.api_key,
            added_by="user",
        )
    except ProviderIdRejected as exc:
        # 400 而不是 422:这是判据拒绝,不是请求体格式错。面板直接把这句话显示出来。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _refresh_router()
    return _shape(p.id)


@router.delete("/{pid}")
async def remove_user_provider(pid: str) -> Dict[str, Any]:
    if not delete_provider(pid):
        raise HTTPException(status_code=404, detail=f"没有叫「{pid}」的端点")
    await _refresh_router()
    return {"deleted": pid}


@router.post("/{pid}/verify")
async def verify_user_provider(pid: str) -> Dict[str, Any]:
    """两步自证。**失败也返回 200** —— "没通过"是一个结论,不是一次请求错误。

    用 4xx 表达"你的网关连不上",会让前端把它当成自己调错了接口。
    结论在 ``state`` 与 ``state_reason`` 里。
    """
    try:
        verify_provider(pid)
    except ProviderIdRejected as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _refresh_router()
    return _shape(pid)
