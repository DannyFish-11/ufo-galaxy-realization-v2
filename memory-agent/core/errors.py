"""统一分层错误:任何一层故障,错误信息必须能指出是哪一层(BUILD_SPEC §0.2-3/5)。"""

from __future__ import annotations


class LayerError(RuntimeError):
    """携带层号(L0-L4)与组件名的运行时错误。"""

    def __init__(self, layer: str, component: str, message: str) -> None:
        self.layer = layer
        self.component = component
        super().__init__(f"[{layer}/{component}] {message}")
