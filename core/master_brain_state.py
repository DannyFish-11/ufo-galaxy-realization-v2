"""主脑状态文件放哪里。

此前缺省落在系统临时目录（``tempfile.gettempdir()``）：不认 ``GALAXY_DATA_DIR``（本仓所有持久化点的约定），
系统清理临时目录或换个用户跑，worker 拓扑与没做完的任务记录就读不到。现在缺省落 ``$GALAXY_DATA_DIR``
（没设则仓库 ``data/``）；``GALAXY_MASTER_BRAIN_STATE_PATH`` 显式指定的仍然优先。
旧位置（系统临时目录）的文件不再读取：它本来就是随系统清理的临时状态，而共享的临时目录里别人的旧文件不该被拿来续跑。
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_FILE_NAME = "galaxy_master_brain_state.json"


def default_state_path() -> Path:
    """显式指定 > ``$GALAXY_DATA_DIR/galaxy_master_brain_state.json``。"""
    explicit = str(os.getenv("GALAXY_MASTER_BRAIN_STATE_PATH", "")).strip()
    if explicit:
        return Path(explicit)
    data_dir = str(os.getenv("GALAXY_DATA_DIR", "")).strip() or str(Path(__file__).resolve().parent.parent / "data")
    return Path(data_dir) / STATE_FILE_NAME
