"""
atomic_write_json 的文件权限契约（B13）
=======================================

``core.atomic_json.atomic_write_json`` 服务的调用点里包含 ``SECRETVAULT_FILE`` /
``AUTH_USERS_FILE`` 这类凭据文件。它落盘的权限**必须**是 0600。

在本测试出现之前，0600 是"碰巧"得来的：``tempfile.mkstemp`` 建出来的临时文件本就是
0600，``os.replace`` 把这个模式带到了目标文件上。没有任何地方声明过这是意图，
也没有任何测试会在实现换成 ``NamedTemporaryFile`` / 裸 ``open()``（默认 0644）时
报警 —— 那会是一次静默的权限放宽。

本文件把这条契约钉死。仅在 POSIX 上有意义：Windows 没有 st_mode 的 rwx 语义，
相关用例会跳过。
"""

import json
import os
import stat
import sys

import pytest

from core.atomic_json import atomic_write_json

_POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="Windows 无 POSIX 权限位语义")


def _mode(path) -> int:
    """返回文件的权限位（去掉文件类型位）。"""
    return stat.S_IMODE(os.stat(path).st_mode)


@_POSIX_ONLY
def test_new_file_is_created_private(tmp_path):
    """新建文件必须是 0600 —— 同组/其他用户不可读。"""
    target = tmp_path / "vault.json"
    atomic_write_json(target, {"api_key": "s3cr3t"})

    assert target.is_file()
    assert _mode(target) == 0o600, f"落盘权限应为 0600，实际 {oct(_mode(target))}"


@_POSIX_ONLY
def test_existing_world_readable_file_is_tightened(tmp_path):
    """已存在的宽权限文件，写入后应被收紧到 0600。

    方向性选择：本函数服务的是配置与凭据文件，收紧是想要的。确有共享读需求的
    调用点应当在写入后自行放宽，而不是让写入函数默认放宽。
    """
    target = tmp_path / "config.json"
    target.write_text("{}", encoding="utf-8")
    os.chmod(target, 0o644)
    assert _mode(target) == 0o644  # 前置条件

    atomic_write_json(target, {"k": "v"})

    assert _mode(target) == 0o600, f"写入后应收紧为 0600，实际 {oct(_mode(target))}"


@_POSIX_ONLY
def test_no_group_or_other_bits_ever_set(tmp_path):
    """更直白的表述：group / other 三组位必须全灭。"""
    target = tmp_path / "secrets.json"
    atomic_write_json(target, {"token": "abc"})

    mode = _mode(target)
    forbidden = (
        stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH
    )
    assert mode & forbidden == 0, f"不该有任何 group/other 权限位，实际 {oct(mode)}"


def test_content_is_still_written_correctly(tmp_path):
    """权限改动不能影响写入内容本身（跨平台）。"""
    target = tmp_path / "payload.json"
    payload = {"中文": "值", "n": 1, "nested": {"a": [1, 2, 3]}}

    atomic_write_json(target, payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_no_temp_fragments_left_behind(tmp_path):
    """成功写入后目录里不该残留临时文件（跨平台）。"""
    target = tmp_path / "x.json"
    atomic_write_json(target, {"a": 1})

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "x.json"]
    assert leftovers == [], f"残留临时文件: {leftovers}"


def test_serialization_failure_leaves_target_untouched(tmp_path):
    """序列化失败时目标文件必须保持原内容 —— 这是相对 open(path,'w') 的关键改进。"""
    target = tmp_path / "keep.json"
    atomic_write_json(target, {"good": 1})
    before = target.read_text(encoding="utf-8")

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": Unserializable()})

    assert target.read_text(encoding="utf-8") == before, "失败写入污染了目标文件"
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "keep.json"]
    assert leftovers == [], f"失败路径残留临时文件: {leftovers}"
