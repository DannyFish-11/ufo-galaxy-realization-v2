"""
Galaxy - CORS 配置
======================

从环境变量读取 CORS 允许的源，替代硬编码 allow_origins=["*"]。

环境变量:
  CORS_ALLOWED_ORIGINS: 逗号分隔的允许源列表
  默认值: http://localhost:3000,http://localhost:8080
"""

import os
from typing import List

_DEFAULT_ORIGINS = "http://localhost:3000,http://localhost:8080"


def get_cors_origins() -> List[str]:
    """获取 CORS 允许的源列表"""
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", _DEFAULT_ORIGINS)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or [_DEFAULT_ORIGINS.split(",")[0]]
