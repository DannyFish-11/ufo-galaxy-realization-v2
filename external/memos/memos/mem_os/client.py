"""
ClientMOS — Memory Operating System 客户端

提供对 MOSCore 的高层封装，简化外部调用者对记忆系统的访问。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ClientMOS:
    """
    Memory Operating System 客户端。

    封装 MOSCore 的常用操作，提供简洁的 API 给外部集成方使用。

    Example:
        >>> client = ClientMOS(user_id="user1")
        >>> client.chat("你好")
        >>> client.add_memory("今天学习了 Python")
        >>> results = client.search("Python 学习")
    """

    def __init__(self, user_id: str = "default", session_id: str = "", config: Optional[Dict[str, Any]] = None):
        self.user_id = user_id
        self.session_id = session_id or f"{user_id}_session"
        self._config = config or {}
        self._core = None
        self._initialized = False

    def _ensure_core(self):
        """延迟初始化 MOSCore"""
        if self._core is not None:
            return
        try:
            from memos.configs.mem_os import MOSConfig
            from memos.mem_os.core import MOSCore

            mos_config = MOSConfig(
                user_id=self.user_id,
                session_id=self.session_id,
                **self._config,
            )
            self._core = MOSCore(config=mos_config)
            self._initialized = True
            logger.info(f"ClientMOS 初始化成功: user={self.user_id}, session={self.session_id}")
        except Exception as e:
            logger.warning(f"ClientMOS 初始化失败 (MOS 依赖可能未安装): {e}")
            self._core = None
            self._initialized = False

    @property
    def is_available(self) -> bool:
        """检查 MOS 核心是否可用"""
        if not self._initialized:
            self._ensure_core()
        return self._initialized and self._core is not None

    def chat(self, message: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """
        与 MOS 进行对话。

        Args:
            message: 用户消息
            history: 对话历史 (可选)

        Returns:
            包含 response 的字典
        """
        self._ensure_core()
        if not self._core:
            return {"success": False, "error": "MOS core not available", "response": ""}

        try:
            chat_history = []
            if history:
                for item in history:
                    chat_history.append({"role": item.get("role", "user"), "content": item.get("content", "")})
            chat_history.append({"role": "user", "content": message})

            result = self._core.chat(messages=chat_history)
            return {"success": True, "response": result}
        except Exception as e:
            logger.error(f"ClientMOS.chat 失败: {e}")
            return {"success": False, "error": str(e), "response": ""}

    def add_memory(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        添加一条记忆。

        Args:
            content: 记忆内容
            metadata: 额外元数据

        Returns:
            操作结果
        """
        self._ensure_core()
        if not self._core:
            return {"success": False, "error": "MOS core not available"}

        try:
            result = self._core.add(content=content, metadata=metadata or {})
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"ClientMOS.add_memory 失败: {e}")
            return {"success": False, "error": str(e)}

    def search(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """
        搜索记忆。

        Args:
            query: 搜索查询
            top_k: 返回结果数量

        Returns:
            搜索结果
        """
        self._ensure_core()
        if not self._core:
            return {"success": False, "error": "MOS core not available", "results": []}

        try:
            results = self._core.search(query=query, top_k=top_k)
            return {"success": True, "results": results}
        except Exception as e:
            logger.error(f"ClientMOS.search 失败: {e}")
            return {"success": False, "error": str(e), "results": []}

    def get_summary(self) -> Dict[str, Any]:
        """获取当前会话摘要"""
        self._ensure_core()
        if not self._core:
            return {"success": False, "error": "MOS core not available"}

        try:
            summary = self._core.get_summary() if hasattr(self._core, "get_summary") else "No summary available"
            return {"success": True, "summary": summary}
        except Exception as e:
            logger.error(f"ClientMOS.get_summary 失败: {e}")
            return {"success": False, "error": str(e)}

    def clear_session(self) -> Dict[str, Any]:
        """清除当前会话数据"""
        self._ensure_core()
        if not self._core:
            return {"success": False, "error": "MOS core not available"}

        try:
            if hasattr(self._core, "clear_session"):
                self._core.clear_session()
            return {"success": True}
        except Exception as e:
            logger.error(f"ClientMOS.clear_session 失败: {e}")
            return {"success": False, "error": str(e)}
