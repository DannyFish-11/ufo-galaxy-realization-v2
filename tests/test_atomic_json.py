"""core.atomic_json 的行为守卫。

重点不是"能写出文件"(那是显然的),而是**失败路径**:序列化炸了以后,
目标文件必须还是完整的旧内容 —— 这正是 open(path,"w") 做不到的那一点。
"""

import json
import os

import pytest

from core.atomic_json import TMP_PREFIX, atomic_write_json


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


def test_write_never_deletes_neighbouring_files(tmp_path):
    """写入函数只写自己那个文件，绝不删除目录里的任何东西。

    初版实现会在每次写入前清扫目录里过期的 .tmp-atomic-*.json —— 那等于给三十多个
    调用点各加了一个删除原语，而它取代的 open(path,"w") 从不删除任何东西。这条测试
    把"写就只是写"钉死，防止那个隐式副作用被重新引入。
    """
    target = tmp_path / "state.json"
    neighbours = [
        tmp_path / f"{TMP_PREFIX}leftover.json",  # 看起来像本模块的临时文件
        tmp_path / "unrelated.json",
        tmp_path / "notes.txt",
    ]
    for p in neighbours:
        p.write_text("{}", encoding="utf-8")
    old = os.path.getmtime(neighbours[0]) - 10 * 60 * 60
    os.utime(neighbours[0], (old, old))  # 即便"过期"也不该被碰

    atomic_write_json(target, {"k": 1})

    for p in neighbours:
        assert p.exists(), f"写入不该删除目录里的其它文件: {p.name}"
