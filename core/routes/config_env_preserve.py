"""面板「保存设置」整体重写 ``.env`` 时，原样带回登记表之外的行。

## 被修的问题

写 ``.env`` 的那个函数只遍历登记表（``CONFIG_SCHEMA``）里的键。可 ``.env.example`` 里有一百个键不在登记表里
—— compose 必填的数据库口令（``TEMPORAL_DB_PASSWORD`` / ``POSTGRES_PASSWORD`` / ``MONGO_ROOT_PASSWORD``…）、
各服务端口、``HF_ENDPOINT`` 镜像地址、``PICKLE_SECRET_KEY``、``BRAVE_API_KEY``、``TURN_*`` …… 用户手写在 ``.env``
里的这些行，**在面板上点一次保存就整行消失了**，下次启动悄悄回到代码默认值。症状是一串互不相干的：
``--docker-full`` 报 "TEMPORAL_DB_PASSWORD is missing"、镜像站失效、``.env`` 覆盖度对不上。

现在：登记表管的键照旧由登记表写（值取环境现值）；**别的行一个字不动地带回来**，放在文件末尾。
已经收进密钥库（``runtime/secrets.env``）的键不带回，免得明文重新泄露进 ``.env``。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List

logger = logging.getLogger("Galaxy.Config")

_HEADER = "# --- 其他（面板不管这些键，保存时原样保留）---\n"


def foreign_env_lines(env_path: Path, known_keys: Iterable[str], skip_keys: Iterable[str] = ()) -> List[str]:
    """``env_path`` 里键不在 ``known_keys``、也不在 ``skip_keys`` 的 ``KEY=value`` 行（原样）。

    同一个键写了多次取最后一次（dotenv 也是后者生效）。读不动文件就当没有 —— 保存不该因此失败。
    """
    try:
        text = Path(env_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("读不动旧的 .env（%s）：别的手写行这次带不回来：%s", env_path, exc)
        return []
    known = set(known_keys) | set(skip_keys)
    kept: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if key and key not in known:
            kept[key] = line
    if not kept:
        return []
    return [_HEADER + "\n".join(kept.values()) + "\n"]
