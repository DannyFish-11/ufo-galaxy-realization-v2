"""galaxy_gateway/android/device_naming.py — 设备登记时在名册里叫什么。"""

from __future__ import annotations

from typing import Any, Dict


def registration_name(message: Dict[str, Any], device_id: str, utype: Any) -> str:
    """设备在名册里叫什么 —— 模型在设备整体卡里看到的就是它。

    依次:帧里的 ``name`` / ``device_name``(顶层或 payload;手表报 ``device_name``)→ 配对时起的名字
    (``/api/v1/pair/claim`` 的 ``name``,手机的登记帧不带名字)→ 型号 → 设备 id(不按平台起一个泛称)。此前只认 ``name``,
    报了 ``device_name="OPPO Watch 3"`` 的手表在名册里叫「Android Device」(真机实测)。
    """
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    for value in (message.get("name"), message.get("device_name"), payload.get("device_name"), payload.get("name")):
        if str(value or "").strip():
            return str(value).strip()
    try:
        from core.peer_trust import get_peer_trust_book

        rec = get_peer_trust_book().get(device_id)
        if rec is not None and rec.name and rec.name != device_id:
            return rec.name
    except Exception:  # noqa: BLE001 — 只是取个名字
        pass
    if str(message.get("model") or "").strip():
        return str(message["model"]).strip()
    return device_id
