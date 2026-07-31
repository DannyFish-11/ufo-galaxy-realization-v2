"""core.atomic_json 的行为守卫。

重点不是"能写出文件"(那是显然的),而是**失败路径**:序列化炸了以后,
目标文件必须还是完整的旧内容 —— 这正是 open(path,"w") 做不到的那一点。
"""

import json
import os

import pytest

from core.atomic_json import TMP_PREFIX, atomic_write_json, sweep_stale_tmp_files


def test_writes_readable_json(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"a": 1, "中文": "值"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "中文": "值"}


def test_creates_missing_parent_directory(tmp_path):
    target = tmp_path / "nested" / "deep" / "state.json"
    atomic_write_json(target, {"ok": True})

    assert target.is_file()


def test_failed_serialization_leaves_old_content_intact(tmp_path):
    """核心保证:写失败不能把旧值弄丢。"""
    target = tmp_path / "state.json"
    atomic_write_json(target, {"generation": 1})

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"generation": 2, "bad": Unserializable()})

    # 旧内容必须原封不动 —— open(path,"w") 在这里会留下一个空文件。
    assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 1}


def test_failed_serialization_leaves_no_tmp_debris(tmp_path):
    target = tmp_path / "state.json"

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": Unserializable()})

    debris = [n for n in os.listdir(tmp_path) if n.startswith(TMP_PREFIX)]
    assert debris == [], f"失败后残留了临时文件: {debris}"


def test_overwrite_is_complete_not_appended(tmp_path):
    """替换而非追加:新内容短于旧内容时不能留下旧内容的尾巴。"""
    target = tmp_path / "state.json"
    atomic_write_json(target, {"padding": "x" * 500})
    atomic_write_json(target, {"k": 1})

    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}


def test_sweep_removes_only_stale_tmp_files(tmp_path):
    fresh = tmp_path / f"{TMP_PREFIX}fresh.json"
    stale = tmp_path / f"{TMP_PREFIX}stale.json"
    unrelated = tmp_path / "keep-me.json"
    for p in (fresh, stale, unrelated):
        p.write_text("{}", encoding="utf-8")

    # 把 stale 的 mtime 推到很久以前
    old = os.path.getmtime(stale) - 10 * 60 * 60
    os.utime(stale, (old, old))

    sweep_stale_tmp_files(str(tmp_path))

    assert fresh.exists(), "未过期的临时文件不该被清掉"
    assert not stale.exists(), "过期的临时文件应被清掉"
    assert unrelated.exists(), "非临时文件绝不能被碰"
