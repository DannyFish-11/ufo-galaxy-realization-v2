"""进程从自己的记录里推出来、写进环境变量的值，「保存设置」不把它钉进 ``.env``。

「保存设置」把登记表里每个键的 ``os.environ`` 现值写进 ``.env``；经 ``core.derived_env.export`` 写的值会被认出来、换回人配的。
第 6 轮全量测试里一条测试串味（tier D 的驻留量从 18000 掉到 8800）顺藤摸出：``core/model_catalog.py`` 把档位 / 主脑 /
感知位直接写进 ``os.environ``，``core/model_selection.py``、``core/container_runtime.py`` 也有几处这样写。这几个键都在登记表里，
而 ``load_tier()`` 让环境变量压过记录 —— 选过一次档位之后随手点一次「保存设置」，它就成了「强制档位」，之后在面板上换的档位
一重启就被打回去。容器运行时同理（选择记在 ``.galaxy_runtime``，环境变量压过它）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_RAW = re.compile(r"^\s*os\.environ\[\s*[\"']([A-Z0-9_]+)[\"']\s*\]\s*=(?!=)")


def test_no_registered_key_is_written_raw_into_the_environment():
    from core.routes.config import CONFIG_SCHEMA

    offenders = []
    for path in [*(REPO / "core").rglob("*.py"), *(REPO / "launcher").rglob("*.py"), REPO / "main.py"]:
        rel = path.relative_to(REPO).as_posix()
        if rel == "core/derived_env.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = _RAW.search(line)
            if m and m.group(1) in CONFIG_SCHEMA:
                offenders.append(f"{rel}:{n} {m.group(1)}")
    assert not offenders, "登记表里的键被直接写进 os.environ（「保存设置」会把它钉成人配的）：" + ", ".join(offenders)


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    import core.derived_env as de
    import core.model_catalog as mc

    monkeypatch.setattr(de, "_ORIGINAL", {})
    monkeypatch.setattr(de, "_EXPORTED", {})
    monkeypatch.setattr(mc, "_STATE_FILE", tmp_path / "model_state.json")
    for key in ("GALAXY_MODEL_TIER", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    return mc


def test_a_tier_picked_in_the_panel_is_not_pinned_by_a_later_save(fresh):
    import os

    from core.derived_env import value_to_save

    fresh.save_tier("B")
    assert os.environ["GALAXY_MODEL_TIER"] == "B", "这一次运行照样要用上"
    assert (
        value_to_save("GALAXY_MODEL_TIER", os.environ["GALAXY_MODEL_TIER"]) == ""
    ), "「保存设置」把选过的档位钉成了强制档位"
    assert value_to_save("OLLAMA_MODEL", os.environ["OLLAMA_MODEL"]) == "", "主脑同理"


def test_what_the_person_configured_is_kept(fresh, monkeypatch):
    import os

    from core.derived_env import value_to_save

    monkeypatch.setenv("GALAXY_MODEL_TIER", "A")  # 人在 .env 里强制了 A
    fresh.save_tier("B")
    assert value_to_save("GALAXY_MODEL_TIER", os.environ["GALAXY_MODEL_TIER"]) == "A", "人配的强制档位要原样写回"
